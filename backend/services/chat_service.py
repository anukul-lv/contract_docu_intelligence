"""Chat service — Conversation management and memory summarization.

Manages conversation lifecycle, builds context windows with memory
summarization, and coordinates between cache and agent services.
"""
from __future__ import annotations

import json
import logging
import uuid

from backend.dependencies import execute_sql
from backend.config import get_settings

logger = logging.getLogger(__name__)

MAX_RECENT_TURNS = 6
SUMMARY_INTERVAL = 10  # Summarize every 10 turns
MAX_CONCURRENT_CONVERSATIONS = 10


class ChatService:
    """Conversation management and context building."""

    async def create_conversation(
        self,
        user_email: str,
        scope_type: str = "all",
        scope_id: str | None = None,
    ) -> dict:
        """Create a new conversation.

        Enforces max 10 concurrent conversations per user.
        """
        settings = get_settings()

        # Check concurrent limit
        count_rows = await execute_sql(
            f"""
            SELECT COUNT(*) AS cnt
            FROM {settings.app_catalog}.{settings.app_schema}.chat_sessions
            WHERE created_by = :user_email
              AND last_message_at > current_timestamp() - INTERVAL 24 HOURS
            """,
            parameters={"user_email": user_email},
        )
        count = int(count_rows[0]["cnt"]) if count_rows else 0
        if count >= MAX_CONCURRENT_CONVERSATIONS:
            raise ValueError(
                f"Maximum {MAX_CONCURRENT_CONVERSATIONS} concurrent conversations reached. "
                "Please close an existing conversation first."
            )

        conv_id = str(uuid.uuid4())

        await execute_sql(
            f"""
            INSERT INTO {settings.app_catalog}.{settings.app_schema}.chat_sessions
            (conversation_id, scope_type, scope_id, created_by)
            VALUES (:conv_id, :scope_type, :scope_id, :user_email)
            """,
            parameters={
                "conv_id": conv_id,
                "scope_type": scope_type,
                "scope_id": scope_id or "",
                "user_email": user_email,
            },
        )

        return {"conversation_id": conv_id, "scope_type": scope_type}

    async def list_conversations(
        self, user_email: str, cursor: str | None = None, limit: int = 20
    ) -> dict:
        """List user's conversations with cursor pagination."""
        settings = get_settings()
        params: dict = {"user_email": user_email, "lim": str(limit + 1)}

        cursor_clause = ""
        if cursor:
            cursor_clause = "AND last_message_at < :cursor_ts"
            params["cursor_ts"] = cursor

        rows = await execute_sql(
            f"""
            SELECT
              conversation_id, scope_type, scope_id, title,
              message_count,
              CAST(created_at AS STRING) AS created_at,
              CAST(last_message_at AS STRING) AS last_message_at
            FROM {settings.app_catalog}.{settings.app_schema}.chat_sessions
            WHERE created_by = :user_email
              AND scope_type != 'deleted'
              {cursor_clause}
            ORDER BY last_message_at DESC
            LIMIT CAST(:lim AS INT)
            """,
            parameters=params,
        )

        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = items[-1]["last_message_at"] if has_more and items else None

        return {
            "items": items,
            "pagination": {"next_cursor": next_cursor, "has_more": has_more},
        }

    async def delete_conversation(self, conversation_id: str, user_email: str) -> None:
        """Soft delete a conversation (preserve for audit)."""
        settings = get_settings()
        await execute_sql(
            f"""
            UPDATE {settings.app_catalog}.{settings.app_schema}.chat_sessions
            SET title = CONCAT('[DELETED] ', COALESCE(title, '')),
                scope_type = 'deleted'
            WHERE conversation_id = :conv_id
              AND created_by = :user_email
            """,
            parameters={"conv_id": conversation_id, "user_email": user_email},
        )

    async def build_context(
        self, conversation_id: str
    ) -> list[dict]:
        """Build the context window for the agent.

        Returns: context_summary + recent_6_turns

        Strategy:
        - Full last 6 turns passed directly
        - Older context summarized every 10 turns
        - Summary stored in chat_sessions.context_summary
        """
        settings = get_settings()

        # Get conversation metadata
        session_rows = await execute_sql(
            f"""
            SELECT context_summary, message_count
            FROM {settings.app_catalog}.{settings.app_schema}.chat_sessions
            WHERE conversation_id = :conv_id
            """,
            parameters={"conv_id": conversation_id},
        )

        context_summary = ""
        message_count = 0
        if session_rows:
            context_summary = session_rows[0].get("context_summary") or ""
            message_count = int(session_rows[0].get("message_count", 0))

        # Check if we need to summarize
        if message_count > 0 and message_count % SUMMARY_INTERVAL == 0:
            context_summary = await self.summarize_history(conversation_id)

        # Get recent turns
        recent_rows = await execute_sql(
            f"""
            SELECT role, content
            FROM {settings.app_catalog}.{settings.app_schema}.chat_messages
            WHERE conversation_id = :conv_id
            ORDER BY created_at DESC
            LIMIT CAST(:lim AS INT)
            """,
            parameters={"conv_id": conversation_id, "lim": str(MAX_RECENT_TURNS)},
        )

        messages: list[dict] = []

        # Prepend summary if exists
        if context_summary:
            messages.append({
                "role": "system",
                "content": f"Previous conversation summary: {context_summary}",
            })

        # Add recent turns (reversed to chronological)
        for row in reversed(recent_rows):
            messages.append({"role": row["role"], "content": row["content"]})

        return messages

    async def summarize_history(
        self, conversation_id: str
    ) -> str:
        """Summarize older turns via ai_query when history exceeds threshold."""
        settings = get_settings()

        # Get older messages (beyond recent 6)
        older_rows = await execute_sql(
            f"""
            SELECT role, content
            FROM {settings.app_catalog}.{settings.app_schema}.chat_messages
            WHERE conversation_id = :conv_id
            ORDER BY created_at ASC
            """,
            parameters={"conv_id": conversation_id},
        )

        if len(older_rows) <= MAX_RECENT_TURNS:
            return ""

        # Take messages beyond the recent window
        to_summarize = older_rows[:-MAX_RECENT_TURNS]
        history_text = "\n".join(
            f"{r['role']}: {r['content'][:200]}" for r in to_summarize
        )

        try:
            rows = await execute_sql(
                """
                SELECT ai_query(
                  'databricks-claude-haiku-4-5',
                  CONCAT(
                    'Summarize this conversation about healthcare contracts. ',
                    'Preserve key facts, decisions, and context. Max 200 words. ',
                    '\n\n', :history_text
                  )
                ) AS summary
                """,
                parameters={"history_text": history_text[:5000]},
            )
            if rows:
                summary = rows[0].get("summary", "")
                await execute_sql(
                    f"""
                    UPDATE {settings.app_catalog}.{settings.app_schema}.chat_sessions
                    SET context_summary = :summary
                    WHERE conversation_id = :conv_id
                    """,
                    parameters={"summary": summary, "conv_id": conversation_id},
                )
                return summary
        except Exception as e:
            logger.warning("History summarization failed: %s", e)

        return ""

    async def save_feedback(
        self, message_id: str, rating: str, comment: str | None
    ) -> None:
        """Store feedback on a chat message."""
        settings = get_settings()
        await execute_sql(
            f"""
            UPDATE {settings.app_catalog}.{settings.app_schema}.chat_messages
            SET feedback_rating = :rating,
                feedback_comment = :comment
            WHERE message_id = :msg_id
            """,
            parameters={
                "rating": rating,
                "comment": comment or "",
                "msg_id": message_id,
            },
        )
