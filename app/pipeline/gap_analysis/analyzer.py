"""Per-question gap analyzer: semantic search + LLM gap analysis using OpenAI."""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "aict_audit_ai_analysis")
OPENAI_MODEL = os.getenv("OPENAI_MODEL_PRIMARY", "gpt-4o-mini")


def _semantic_search(query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """Search Qdrant for relevant context using OpenAI embeddings."""
    from qdrant_client import QdrantClient
    from app.pipeline.gap_analysis.indexer import get_single_embedding

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    vector = get_single_embedding(query)

    results = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=vector,
        limit=top_k,
        with_payload=True,
    )

    output = []
    for point in results.points:
        payload = point.payload or {}
        output.append({
            "text": payload.get("text", ""),
            "score": float(point.score),
            "doc_id": payload.get("doc_id", ""),
            "chunk_type": payload.get("chunk_type", ""),
            "section_path": payload.get("section_path", []),
        })
    return output


def _build_context(results: List[Dict]) -> str:
    """Format search results into context string for the LLM."""
    parts = []
    for r in results:
        section = " > ".join(r.get("section_path", []))
        parts.append(
            f"Document: {r.get('doc_id', 'N/A')}\n"
            f"Type: {r.get('chunk_type', 'N/A')}\n"
            f"Score: {round(r.get('score', 0), 3)}\n"
            f"Section: {section}\n\n"
            f"Text:\n{r.get('text', '')}"
        )
    return "\n\n---\n\n".join(parts)


def analyze_question(
    question_text: str,
    user_answer: str,
    question_id: str = "",
    category_id: str = "",
) -> Dict[str, Any]:
    """Run gap analysis for a single question against the reference PDF.

    Returns a dict with synthesized_summary, key_themes, user_gap, insights, match_score.
    """
    from openai import OpenAI
    from app.pipeline.gap_analysis.prompts import GAP_ANALYSIS_SYSTEM_PROMPT, GAP_ANALYSIS_USER_TEMPLATE

    # Step 1: Semantic search for relevant context
    search_results = _semantic_search(question_text, top_k=10)

    if not search_results:
        return {
            "question_id": question_id,
            "category_id": category_id,
            "status": "no_context",
            "synthesized_summary": "",
            "key_themes": [],
            "user_gap": ["Insufficient reference context found for this question."],
            "insights": [],
            "match_score": 0.0,
            "context_count": 0,
        }

    context_text = _build_context(search_results)

    # Step 2: LLM gap analysis
    user_prompt = GAP_ANALYSIS_USER_TEMPLATE.format(
        question=question_text,
        user_answer=user_answer,
        context=context_text,
    )

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": GAP_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        result = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM response as JSON for q=%s: %s", question_id, e)
        result = {
            "synthesized_summary": "",
            "key_themes": [],
            "user_gap": ["Analysis produced invalid output."],
            "insights": [],
            "match_score": 0.0,
        }
    except Exception as e:
        logger.error("LLM call failed for q=%s: %s", question_id, e)
        raise

    result["question_id"] = question_id
    result["category_id"] = category_id
    result["status"] = "completed"
    result["context_count"] = len(search_results)

    return result
