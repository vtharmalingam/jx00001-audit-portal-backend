from typing import List, Optional

from app.procs.embeddings import EmbeddingModel
from app.etl.anchor_indexer.question_faiss_index import \
    QuestionFaissIndex
from app.procs.anchor_match.question_registry import \
    QuestionRegistry


class FaissIndexBuilder:
    """
    Builds FAISS indices for all questions registered in the QuestionRegistry.
    Intended as a pre-evaluation / pre-deployment step.
    """

    def __init__(
        self,
        registry: QuestionRegistry,
        embedding_model: EmbeddingModel
    ):
        self.registry = registry
        self.embedding_model = embedding_model 

    # ---------------------------------------------------------
    # PUBLIC API
    # ---------------------------------------------------------
    def build_all(self, overwrite: bool = False) -> List[str]:
        """
        Build FAISS indices for all questions.

        overwrite=False → only build missing indices
        overwrite=True  → rebuild everything

        Returns list of question_ids that were built.
        """

        built = []

        for question_id in self.registry.all_question_ids():
            index = QuestionFaissIndex(
                question_id=question_id,
                embedding_model=self.embedding_model,
                registry=self.registry
            )

            if index.exists() and not overwrite:
                continue

            index.build(overwrite=True)
            built.append(question_id)

        return built



if __name__ == "__main__":


    from app.config import get_config
    # -------------------------------------------
    cfg = get_config()
    question_dir = cfg.ai_assessment.data_dir
    # -------------------------------------------

    print(f"-- Question Directory: -----------> {question_dir}")

    registry = QuestionRegistry(categories_root=question_dir)
    embedder = EmbeddingModel()

    builder = FaissIndexBuilder(registry, embedder)
    built = builder.build_all()

    print(f"Built {len(built)} FAISS indices")
    