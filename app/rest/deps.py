"""Shared FastAPI dependencies (S3, config paths, LLM, semantic search)."""

from app.config import get_config
from app.etl.s3.services.s3_client import S3Client
from app.llms.ollama_client import OllamaClient
from app.procs.semantic_search.q_search_engine import SemanticSearchEngine

_cfg = get_config()
data_dir = _cfg.ai_assessment.data_dir
s3_client = S3Client(bucket=_cfg.ai_assessment.s3.bucket)
llm_client = OllamaClient().llm
semantic_engine = SemanticSearchEngine(_cfg.ai_assessment.embedding.collection_name)
