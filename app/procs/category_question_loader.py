import json
import os
from typing import Dict, List


class CategoryQuestionLoader:
    """
    Loads category metadata and all questions belonging to that category
    using the folder + category.json model.
    Intended for UI / API consumption.
    """

    def __init__(self, categories_root: str = "categories"):
        self.categories_root = categories_root

    # ---------------------------------------------------------
    # PUBLIC API
    # ---------------------------------------------------------
    def load_category(self, category_id: str) -> Dict:
        """
        Load a single category (metadata + questions) by category_id.
        """

        category_folder = self._find_category_folder(category_id)
        category_meta = self._load_category_meta(category_folder)
        questions = self._load_questions(category_folder, category_id)

        return {
            "category_id": category_meta["category_id"],
            "display_name": category_meta.get("display_name"),
            "description": category_meta.get("description"),
            "questions": questions
        }

    def list_categories(self) -> List[Dict]:
        """
        List all categories with basic metadata (no questions).
        Useful for navigation menus.
        """

        categories = []

        for folder in os.listdir(self.categories_root):
            folder_path = os.path.join(self.categories_root, folder)
            # print(f"----------------folder_path: {folder_path}")
            if not os.path.isdir(folder_path):
                # print(f"----------------(not exists) folder_path: {folder_path}")
                continue

            # print(f"----------------folder_path: {folder_path}")
            
            category_json = os.path.join(folder_path, "category.json")
            if not os.path.exists(category_json):
                continue

            # print(f"----------------category_json: {category_json}")

            with open(category_json, "r") as f:
                meta = json.load(f)

            
            
            categories.append({
                "category_id": meta["category_id"],
                "display_name": meta.get("display_name"),
                "description": meta.get("description")
            })

        categories.sort(key=lambda c: c["category_id"])
        return categories

    # ---------------------------------------------------------
    # INTERNAL HELPERS
    # ---------------------------------------------------------
    def _find_category_folder(self, category_id: str) -> str:
        """
        Find the folder whose category.json matches the given category_id.
        """

        for folder in os.listdir(self.categories_root):
            folder_path = os.path.join(self.categories_root, folder)
            if not os.path.isdir(folder_path):
                continue

            category_json = os.path.join(folder_path, "category.json")
            if not os.path.exists(category_json):
                continue

            with open(category_json, "r") as f:
                meta = json.load(f)

            if meta.get("category_id") == category_id:
                return folder_path

        raise ValueError(f"Category not found: {category_id}")

    def _load_category_meta(self, category_folder: str) -> Dict:
        path = os.path.join(category_folder, "category.json")
        with open(path, "r") as f:
            return json.load(f)

    def _load_questions(
        self,
        category_folder: str,
        category_id: str
    ) -> List[Dict]:

        questions = []

        for file in os.listdir(category_folder):
            if not file.endswith(".json"):
                continue

            if file in ("category.json", "consistency.json"):
                continue

            path = os.path.join(category_folder, file)

            with open(path, "r") as f:
                spec = json.load(f)

            # Enforce category consistency
            if spec.get("category_id") != category_id:
                raise ValueError(
                    f"Category mismatch in {file}: "
                    f"{spec.get('category_id')} != {category_id}"
                )

            questions.append(spec)

        # Stable ordering for UI
        questions.sort(key=lambda q: q.get("question_id", ""))
        return questions
