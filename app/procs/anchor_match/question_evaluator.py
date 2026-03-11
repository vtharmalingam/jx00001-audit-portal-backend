import json
from typing import Any, Dict
 
from app.procs.anchor_match.question_faiss_index import \
    QuestionFaissIndex
 
from app.procs.anchor_match.question_registry import \
    QuestionRegistry

from app.procs.embeddings import EmbeddingModel
from app.procs.anchor_match.scoring import compute_alignment

from app.config import get_config

class QuestionEvaluator:
    """
    Evaluates a single question answer:
    - FAISS anchor matching
    - Alignment scoring
    - Signal extraction (JSON-driven)
    """

    def __init__(
        self,
        question_id: str,
        embedding_model: EmbeddingModel,
        registry: QuestionRegistry
    ):
        self.question_id = question_id
        self.embedder = embedding_model
        self.registry = registry

        # --------------------------------------------------
        # Load question spec (ONLY for signals & metadata)
        # --------------------------------------------------
        question_path = registry.get_question_path(question_id)
        with open(question_path, "r") as f:
            self.spec = json.load(f)

        self.signals_spec = self.spec.get("signals", {})
        self.follow_ups = self.spec.get("follow_ups", [])

        # --------------------------------------------------
        # Load FAISS index (anchors already compiled)
        # --------------------------------------------------
        # Read frmo config
        # cfg = get_config().ai_assessment
        # self.index_dir = cfg.indexes_dir
        # ---

        self.index = QuestionFaissIndex(
            question_id=question_id,
            embedding_model=self.embedder,
            registry=registry 
        )

        if self.index.exists():
            self.index.load()
        else:
            raise RuntimeError(
                f"FAISS index not found for question {question_id}. "
                f"Run index.build() first."
            )

    # ---------------------------------------------------------
    # PUBLIC API
    # ---------------------------------------------------------
    def evaluate(self, user_answer: str) -> Dict[str, Any]:

        # encode answer 
        query_embedding = self.embedder.encode([user_answer])

        # search anchors
        matches = self.index.search(query_embedding)

        # TODO: Anchor "importance" is conceptually part of the model and needs to be  explicitly introduced in the question definitions in a future iteration
        alignment = compute_alignment(matches)

        # 
        signals = self._extract_signals(user_answer, matches)

        return {
            "question_id": self.question_id,
            "alignment_score": alignment,
            "matches": matches,
            "signals": signals,
            "follow_ups" : self.follow_ups   # follow up questions
        }

    # ---------------------------------------------------------
    # SIGNAL ENGINE (JSON-DRIVEN)
    # ---------------------------------------------------------
    def _extract_signals(self, user_answer: str, matches) -> Dict[str, bool]:
        answer_text = user_answer.lower()
        signals = {}

        for signal_name, rules in self.signals_spec.items():
            signals[signal_name] = self._evaluate_signal(
                rules, answer_text, matches
            )

        return signals

    def _evaluate_signal(self, rules, answer_text, matches) -> bool:
        """
        Supported rule types (JSON-driven):
        - keywords
        - match_if_anchor_type
        """

        # Keyword-based signal
        if "keywords" in rules:
            if any(k.lower() in answer_text for k in rules["keywords"]):
                return True

        # Anchor-type-based signal
        if "match_if_anchor_type" in rules:
            for m in matches:
                if m["type"] in rules["match_if_anchor_type"]:
                    return True

        return False
