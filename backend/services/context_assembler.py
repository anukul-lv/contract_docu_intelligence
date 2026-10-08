"""Context assembler — Post-retrieval processing for agent context.

6-step pipeline: dedup → doc-boost → amendment chain → sort → format → truncate.
Produces a formatted context string ready for the agent's system prompt.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.services.vector_service import SearchResult

logger = logging.getLogger(__name__)

# Context window budget (tokens)
MAX_CONTEXT_TOKENS = 96_000
OUTPUT_RESERVE_TOKENS = 4_000
EFFECTIVE_BUDGET = MAX_CONTEXT_TOKENS - OUTPUT_RESERVE_TOKENS
CHARS_PER_TOKEN = 4  # rough estimate for English text


@dataclass
class AssemblyResult:
    context: str
    chunk_count: int
    total_chars: int
    estimated_tokens: int
    deduped_count: int
    truncated: bool
    document_ids: list[str] = field(default_factory=list)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars/token for English)."""
    return len(text) // CHARS_PER_TOKEN


def _dedup_chunks(chunks: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate by (document_version_id, page_numbers).

    When multiple chunks cover the same page of the same document,
    keep only the highest-scored one.
    """
    seen: dict[str, SearchResult] = {}
    for c in chunks:
        pages_key = str(sorted(c.page_numbers)) if c.page_numbers else "none"
        key = f"{c.document_version_id}:{pages_key}"
        if key not in seen or c.score > seen[key].score:
            seen[key] = c
    return list(seen.values())


def _boost_document_chunks(
    chunks: list[SearchResult],
    target_document_ids: list[str] | None,
    boost_factor: float = 2.0,
) -> list[SearchResult]:
    """Boost score for chunks from a specific document.

    When the query references a specific contract, boost those chunks
    so they appear higher in the context.
    """
    if not target_document_ids:
        return chunks

    target_set = set(target_document_ids)
    boosted = []
    for c in chunks:
        if c.document_version_id in target_set:
            # Create a copy with boosted score
            boosted.append(SearchResult(
                chunk_id=c.chunk_id,
                document_version_id=c.document_version_id,
                chunk_index=c.chunk_index,
                chunk_to_retrieve=c.chunk_to_retrieve,
                page_numbers=c.page_numbers,
                section_header=c.section_header,
                contract_type=c.contract_type,
                state_jurisdiction=c.state_jurisdiction,
                effective_date=c.effective_date,
                expiration_date=c.expiration_date,
                reimbursement_method=c.reimbursement_method,
                contains_table=c.contains_table,
                score=c.score * boost_factor,
            ))
        else:
            boosted.append(c)
    return boosted


def _format_chunk(chunk: SearchResult, index: int) -> str:
    """Format a single chunk with metadata header."""
    # Build metadata header
    parts = []
    if chunk.contract_type:
        parts.append(chunk.contract_type)
    if chunk.state_jurisdiction:
        parts.append(chunk.state_jurisdiction)
    if chunk.section_header:
        parts.append(chunk.section_header)
    if chunk.page_numbers:
        pages = ", ".join(str(p) for p in chunk.page_numbers)
        parts.append(f"Page {pages}")
    if chunk.contains_table:
        parts.append("TABLE")

    header = " | ".join(parts) if parts else f"Chunk {index + 1}"

    return f"[{header}]\n{chunk.chunk_to_retrieve}\n"


def assemble_context(
    chunks: list[SearchResult],
    query: str,
    target_document_ids: list[str] | None = None,
    amendment_chunks: list[SearchResult] | None = None,
    max_tokens: int = EFFECTIVE_BUDGET,
) -> AssemblyResult:
    """Assemble retrieved chunks into agent context string.

    6-step pipeline:
    1. Deduplicate by (document_version_id, page_numbers)
    2. Boost chunks from target document (if query references a specific doc)
    3. Merge amendment chain chunks (if applicable)
    4. Sort by score descending
    5. Format each chunk with metadata header
    6. Truncate to token budget

    Args:
        chunks: Retrieved chunks from vector search.
        query: The original user query (for context).
        target_document_ids: IDs of documents referenced in the query.
        amendment_chunks: Additional chunks from amendment chain.
        max_tokens: Token budget for the context.

    Returns:
        AssemblyResult with formatted context string and metadata.
    """
    original_count = len(chunks)

    # Step 1: Dedup
    deduped = _dedup_chunks(chunks)
    dedup_removed = original_count - len(deduped)

    # Step 2: Doc-specific boost
    boosted = _boost_document_chunks(deduped, target_document_ids)

    # Step 3: Merge amendment chain chunks
    if amendment_chunks:
        amendment_deduped = _dedup_chunks(amendment_chunks)
        # Tag amendment chunks for clarity
        for ac in amendment_deduped:
            ac.section_header = f"[AMENDMENT] {ac.section_header or ''}"
        boosted.extend(amendment_deduped)

    # Step 4: Sort by score descending
    sorted_chunks = sorted(boosted, key=lambda c: c.score, reverse=True)

    # Step 5 & 6: Format and truncate
    context_parts: list[str] = []
    running_tokens = 0
    truncated = False
    included_doc_ids: set[str] = set()

    for i, chunk in enumerate(sorted_chunks):
        formatted = _format_chunk(chunk, i)
        chunk_tokens = _estimate_tokens(formatted)

        if running_tokens + chunk_tokens > max_tokens:
            truncated = True
            # Try to fit a partial chunk
            remaining_chars = (max_tokens - running_tokens) * CHARS_PER_TOKEN
            if remaining_chars > 200:  # Only include if meaningful
                context_parts.append(formatted[:remaining_chars] + "\n[TRUNCATED]")
                included_doc_ids.add(chunk.document_version_id)
            break

        context_parts.append(formatted)
        running_tokens += chunk_tokens
        included_doc_ids.add(chunk.document_version_id)

    context = "\n---\n".join(context_parts)

    result = AssemblyResult(
        context=context,
        chunk_count=len(context_parts),
        total_chars=len(context),
        estimated_tokens=_estimate_tokens(context),
        deduped_count=dedup_removed,
        truncated=truncated,
        document_ids=list(included_doc_ids),
    )

    logger.info(
        "Context assembled: %d chunks (%d deduped), ~%d tokens, truncated=%s",
        result.chunk_count, dedup_removed, result.estimated_tokens, truncated,
    )

    return result
