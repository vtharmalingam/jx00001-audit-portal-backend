import json
import os
from typing import Dict, List, Optional

import faiss
import numpy as np 


from app.config import get_config

from app.procs.anchor_match.question_registry import \
    QuestionRegistry

from app.procs.embeddings import EmbeddingModel


class QuestionFaissIndex:
    """
    One FAISS index per question.
    Builds itself directly from question JSON.
    """

    def __init__(
        self,
        question_id: str,
        embedding_model: EmbeddingModel,
        registry: QuestionRegistry, 
    ):
        self.question_id = question_id
        self.embedding_model = embedding_model
        self.embedding_dim = self.embedding_model.encode(
            ["__dim_check__"]
        ).shape[1]

        self.registry = registry
        self.question_spec_path = registry.get_question_path(question_id)

        with open(self.question_spec_path, "r", encoding="utf-8") as f:
            self.spec = json.load(f)

        # -------------------------------------------
        cfg = get_config()
        self.index_dir = cfg.ai_assessment.indexes_dir
        # -------------------------------------------

        print(f"-- Question :  Id: {self.question_id} | Path => {self.question_spec_path} ")
        print(f"-- Index Directory: -----------> {self.index_dir}")
 
        self.index_path = os.path.join(self.index_dir, f"{question_id}.faiss")
        self.meta_path = os.path.join(self.index_dir, f"{question_id}_meta.json")

        self.index: Optional[faiss.Index] = None
        self.metadata: List[Dict] = []

        os.makedirs(self.index_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # BUILD / REBUILD (JSON-DRIVEN)
    # ------------------------------------------------------------------
    def build(self, overwrite: bool = True):
        if os.path.exists(self.index_path) and not overwrite:
            raise RuntimeError(
                f"Index already exists for question {self.question_id}"
            )

        anchors_dict = self.spec.get("anchors", {})

        if not anchors_dict:
            raise ValueError(
                f"No anchors found for question {self.question_id}"
            )

        # Flatten anchors across categories (good, bad, etc.)
        anchors = [
            {**a, "type": a.get("type", category)}
            for category, items in anchors_dict.items()
            for a in items
        ]

        if not anchors:
            raise ValueError(
                f"No valid anchor entries found for question {self.question_id}"
            )

        # print(anchors)

        # Extract texts for embedding
        texts = [a["text"] for a in anchors]
        embeddings = self.embedding_model.encode(texts)

        # Build FAISS index
        self.index = faiss.IndexFlatIP(self.embedding_dim)
        self.index.add(embeddings)

        # Prepare metadata
        self.metadata = [
            {
                "anchor_id": a["anchor_id"],
                "type": a["type"],
                "weight": a["weight"],
                "text": a["text"],
            }
            for a in anchors
        ]

        self._persist()

    # ------------------------------------------------------------------
    # LOAD
    # ------------------------------------------------------------------
    def load(self):
        if not os.path.exists(self.index_path):
            raise FileNotFoundError(
                f"No FAISS index found for question {self.question_id}"
            )

        self.index = faiss.read_index(self.index_path)

        with open(self.meta_path, "r", encoding="utf-8") as f:
            self.metadata = json.load(f)

    # ------------------------------------------------------------------
    # SEARCH
    # ------------------------------------------------------------------
    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 8,
        min_similarity: float = 0.0
    ) -> List[Dict]:

        if self.index is None:
            raise RuntimeError("Index not loaded or built")

        scores, indices = self.index.search(query_embedding, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1 or score < min_similarity:
                continue

            anchor = self.metadata[idx].copy()
            anchor["similarity"] = float(score)
            results.append(anchor)

        return results

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------
    def delete(self):
        if os.path.exists(self.index_path):
            os.remove(self.index_path)

        if os.path.exists(self.meta_path):
            os.remove(self.meta_path)

        self.index = None
        self.metadata = []

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------
    def _persist(self):
        faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # UTIL
    # ------------------------------------------------------------------
    def exists(self) -> bool:
        return os.path.exists(self.index_path)

    def info(self) -> Dict:
        return {
            "question_id": self.question_id,
            "num_anchors": len(self.metadata),
            "embedding_dim": self.embedding_dim,
            "index_path": self.index_path
        }
