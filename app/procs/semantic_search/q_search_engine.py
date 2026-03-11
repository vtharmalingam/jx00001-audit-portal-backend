import os
import json
from typing import List, Dict, Any
from collections import defaultdict

from qdrant_client import QdrantClient
from qdrant_client.models import QueryRequest

from app.config import get_config
from app.procs.embeddings import EmbeddingModel


class SemanticSearchEngine:

    MAX_PER_GROUP = 3
    SCORE_DROP_THRESHOLD = 0.15

    def __init__(self, collection_name: str = "knowledge_base"):
        self.cfg = get_config()
        self.collection_name = collection_name

        self.qdclient = QdrantClient(
            host=os.getenv("QDRANT_HOST", "qdrant"),
            port=int(os.getenv("QDRANT_PORT", 6333)),
        )

        self.embedder = EmbeddingModel()

    # ---------------------------------------------------------
    # CORE SEARCH (aligned to your working code)
    # ---------------------------------------------------------
    def _search(self, query: str, limit: int = 20):
        vector = self.embedder.encode(query)[0]

        response = self.qdclient.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=limit,
            with_payload=True,
        )

        return response.points
    
    # ---------------------------------------------------------
    # GROUPING (same pattern as your handler)
    # ---------------------------------------------------------
    @staticmethod
    def _group_by_chunk_type(results):
        grouped = defaultdict(list)

        for r in results:
            payload = r.payload or {}
            key = payload.get("chunk_type", "unknown")
            grouped[key].append(r)

        return grouped

    # ---------------------------------------------------------
    # DEDUPE (doc level)
    # ---------------------------------------------------------
    @staticmethod
    def _dedupe(results):
        seen_docs = set()
        deduped = []

        for r in results:
            payload = r.payload or {}
            doc_id = payload.get("doc_id")

            if doc_id and doc_id not in seen_docs:
                deduped.append(r)
                seen_docs.add(doc_id)

        return deduped

    # ---------------------------------------------------------
    # SCORE-AWARE FILTER
    # ---------------------------------------------------------
    def _score_filter(self, results, count: int):
        selected = []
        prev_score = None

        for r in results:
            if len(selected) >= count:
                break

            if prev_score is not None:
                if (prev_score - r.score) > self.SCORE_DROP_THRESHOLD:
                    break

            selected.append(r)
            prev_score = r.score

        return selected

    # ---------------------------------------------------------
    # SELECT (balanced across chunk types)
    # ---------------------------------------------------------
    def _select(self, grouped, count: int):

        selected = []

        for chunk_type, items in grouped.items():
            items = self._score_filter(items, self.MAX_PER_GROUP)
            selected.extend(items)

        # final trim
        selected = sorted(selected, key=lambda x: x.score, reverse=True)
        return selected[:count]

    # ---------------------------------------------------------
    # PUBLIC API
    # ---------------------------------------------------------
    def semantic_summary(self, context: str, count: int = 10) -> Dict[str, Any]:

        # Step 1: retrieve
        results = self._search(context, limit=count * 3)

        # Step 2: dedupe
        results = self._dedupe(results)

        # Step 3: group
        grouped = self._group_by_chunk_type(results)

        # Step 4: select
        selected = self._select(grouped, count)

        # Step 5: format
        output = []
        for r in selected:
            payload = r.payload or {}

            output.append({
                "text": payload.get("text"),
                "score": float(r.score),
                "doc_id": payload.get("doc_id"),
                "chunk_type": payload.get("chunk_type"),
                "section_path": payload.get("section_path"),
            })

        return {
            "query": context,
            "count": len(output),
            "results": output,
        }


# ---------------------------------------------------------
# 🔥 MAIN (TEST HARNESS)
# ---------------------------------------------------------
if __name__ == "__main__":
    print("🔍 Running Semantic Search Test...\n")

    try:
        engine = SemanticSearchEngine(collection_name="docling_rag_9779f7ae79ed15ae")

        TEST_QUERY = "AI risks using competitor data without permission"
        TEST_COUNT = 10

        result = engine.semantic_summary(TEST_QUERY, TEST_COUNT)

        print("✅ RESULT:\n")
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()