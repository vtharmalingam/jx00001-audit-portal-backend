"""Shared clients and config for handlers (one import per request module)."""

from app.config import get_config
from app.etl.s3.services.s3_client import S3Client
from app.llms.ollama_client import OllamaClient
from app.procs.semantic_search.q_search_engine import SemanticSearchEngine

cfg = get_config()
data_dir = cfg.ai_assessment.data_dir
s3_client = S3Client(bucket=cfg.ai_assessment.s3.bucket)
llm_client = OllamaClient().llm
engine = SemanticSearchEngine(cfg.ai_assessment.embedding.collection_name)
