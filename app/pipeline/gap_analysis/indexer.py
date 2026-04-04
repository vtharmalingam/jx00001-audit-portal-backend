"""Re-index the reference PDF with OpenAI embeddings into Qdrant."""

import logging
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "aict_audit_ai_analysis")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")

PDF_PATH = Path(__file__).resolve().parent.parent.parent / "etl" / "content_index" / "ai_eat_your_business.pdf"


def get_openai_embeddings(texts: List[str]) -> List[List[float]]:
    """Generate embeddings using OpenAI text-embedding-3-large."""
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def get_single_embedding(text: str) -> List[float]:
    """Get embedding for a single text string."""
    return get_openai_embeddings([text])[0]


def extract_pdf_chunks(pdf_path: str = None) -> List[dict]:
    """Extract text chunks from PDF using pypdf."""
    from pypdf import PdfReader

    path = pdf_path or str(PDF_PATH)
    reader = PdfReader(path)
    chunks = []

    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if not text.strip():
            continue

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        for j, para in enumerate(paragraphs):
            if len(para) < 20:
                continue
            chunks.append({
                "text": para,
                "doc_id": Path(path).stem,
                "chunk_type": "section_text",
                "page_number": i + 1,
                "chunk_index": j,
                "section_path": [f"Page {i + 1}", f"Paragraph {j + 1}"],
            })

    logger.info("Extracted %d chunks from %s", len(chunks), path)
    return chunks


def reindex_pdf(pdf_path: str = None, collection_name: str = None):
    """Re-index the reference PDF with OpenAI embeddings into Qdrant."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams

    col_name = collection_name or COLLECTION_NAME

    chunks = extract_pdf_chunks(pdf_path)
    if not chunks:
        logger.error("No chunks extracted from PDF")
        return {"status": "error", "message": "No chunks extracted"}

    logger.info("Generating OpenAI embeddings for %d chunks...", len(chunks))
    texts = [c["text"] for c in chunks]

    # Batch embeddings in groups of 100
    all_embeddings = []
    batch_size = 100
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        embeddings = get_openai_embeddings(batch)
        all_embeddings.extend(embeddings)

    dim = len(all_embeddings[0])
    logger.info("Embedding dimension: %d", dim)

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=120)

    # Recreate collection
    try:
        client.delete_collection(col_name)
        logger.info("Deleted existing collection: %s", col_name)
    except Exception:
        pass

    client.create_collection(
        collection_name=col_name,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    logger.info("Created collection: %s (dim=%d)", col_name, dim)

    # Upload points
    points = []
    for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
        points.append(PointStruct(
            id=idx,
            vector=embedding,
            payload=chunk,
        ))

    # Upload in smaller batches (3072-dim vectors are large)
    upsert_batch_size = 20
    for i in range(0, len(points), upsert_batch_size):
        batch = points[i:i + upsert_batch_size]
        logger.info("Upserting batch %d–%d of %d", i, i + len(batch), len(points))
        client.upsert(collection_name=col_name, points=batch)

    logger.info("Indexed %d points into %s", len(points), col_name)
    return {
        "status": "ok",
        "collection": col_name,
        "total_chunks": len(chunks),
        "embedding_model": EMBEDDING_MODEL,
        "dimension": dim,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = reindex_pdf()
    print(result)
