"""Shared FastAPI dependencies (S3, config paths)."""

from app.config import get_config
from app.etl.s3.services.s3_client import S3Client

_cfg = get_config()
data_dir = _cfg.ai_assessment.data_dir
s3_client = S3Client(bucket=_cfg.ai_assessment.s3.bucket)

# Legacy: Ollama + local semantic search (only loaded if needed)
llm_client = None
semantic_engine = None


def _get_llm_client():
    global llm_client
    if llm_client is None:
        from app.llms.ollama_client import OllamaClient
        llm_client = OllamaClient().llm
    return llm_client


def _get_semantic_engine():
    global semantic_engine
    if semantic_engine is None:
        from app.procs.semantic_search.q_search_engine import SemanticSearchEngine
        semantic_engine = SemanticSearchEngine(_cfg.ai_assessment.embedding.collection_name)
    return semantic_engine
