"""Application configuration loaded from environment variables."""
import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Catalogs and schemas
    app_catalog: str = os.getenv("APP_CATALOG", "dev")
    app_schema: str = os.getenv("APP_SCHEMA", "doc_intel")
    customer_catalog: str = os.getenv("CUSTOMER_CATALOG", "dev")
    customer_schema: str = os.getenv("CUSTOMER_SCHEMA", "doc_intel")

    # Compute
    sql_warehouse_id: str = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
    sql_warehouse_http_path: str = os.getenv("DATABRICKS_HTTP_PATH", "")
    extraction_job_template_id: str = os.getenv("EXTRACTION_JOB_TEMPLATE_ID", "")

    # Storage
    volume_path: str = os.getenv("VOLUME_PATH", "/Volumes/dev/doc_intel/prvdr_contracts")

    # AI Gateway
    ai_gateway_chat_endpoint: str = os.getenv("AI_GATEWAY_CHAT_ENDPOINT", "")
    ai_gateway_embedding_endpoint: str = os.getenv("AI_GATEWAY_EMBEDDING_ENDPOINT", "")
    ai_search_endpoint: str = os.getenv("AI_SEARCH_ENDPOINT", "")
    agent_serving_endpoint: str = os.getenv("AGENT_SERVING_ENDPOINT", "")

    # Feature flags
    feature_flag_cache_ttl_sec: int = int(os.getenv("FEATURE_FLAG_CACHE_TTL_SEC", "60"))

    # Runtime
    environment: str = os.getenv("ENVIRONMENT", "dev")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
