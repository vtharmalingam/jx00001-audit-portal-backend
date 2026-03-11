import numpy as np
from sentence_transformers import SentenceTransformer
from app.config import get_config



'''
Why normalize?
  - Cosine similarity via FAISS inner product 
  - Stable scoring
'''


class EmbeddingModel:
    def __init__(self):
        cfg = get_config()

        emb_cfg = cfg.ai_assessment.embedding   

        self.model_name = emb_cfg.model_name
        self.normalize = emb_cfg.normalize
        self.show_progress = emb_cfg.show_progress

        self.model = SentenceTransformer(self.model_name)

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=self.normalize,
            show_progress_bar=self.show_progress
        )
        return np.array(embeddings, dtype="float32")