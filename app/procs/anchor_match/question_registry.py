import json
import os
from typing import Dict


class QuestionRegistry:
    """
    Resolves question_id -> question JSON path.
    Built once at startup.
    """

    def __init__(self, categories_root: str = "categories"):
        self.categories_root = categories_root
        self._index: Dict[str, str] = {}
        self._build_index()

    def all_question_ids(self):
      """
      Gets all quetsion IDs
      """

      return list(self._index.keys())



    def _build_index(self):
        for category_folder in os.listdir(self.categories_root):
            folder_path = os.path.join(self.categories_root, category_folder)
            if not os.path.isdir(folder_path):
                continue

            # Require category.json
            category_json = os.path.join(folder_path, "category.json")
            if not os.path.exists(category_json):
                continue

            for file in os.listdir(folder_path):
                if not file.endswith(".json"):
                    continue
                if file in ("category.json", "consistency.json"):
                    continue

                path = os.path.join(folder_path, file)
                with open(path, "r") as f:
                    spec = json.load(f)

                qid = spec.get("question_id")
                if not qid:
                    continue

                if qid in self._index:
                    raise ValueError(
                        f"Duplicate question_id detected: {qid}"
                    )

                self._index[qid] = path

    def get_question_path(self, question_id: str) -> str:
        if question_id not in self._index:
            raise KeyError(f"Unknown question_id: {question_id}")
        return self._index[question_id]

