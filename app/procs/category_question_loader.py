import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
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
            "control_id": category_meta.get("control_id"),
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

            with open(category_json, "r", encoding="utf-8") as f:
                meta = json.load(f)

            
            
            categories.append({
                "category_id": meta["category_id"],
                "display_name": meta.get("display_name"),
                "description": meta.get("description"),
                "control_id": meta.get("control_id"),
            })

        categories.sort(key=lambda c: c["category_id"])
        return categories

    def load_all(self) -> List[Dict]:
        """Load all categories with their questions in parallel using ThreadPoolExecutor."""
        cats = self.list_categories()
        if not cats:
            return []

        def _load_one(cat_id: str) -> Dict:
            return self.load_category(cat_id)

        with ThreadPoolExecutor(max_workers=min(len(cats), 8)) as pool:
            results = list(pool.map(_load_one, [c["category_id"] for c in cats]))

        results.sort(key=lambda c: c.get("category_id", ""))
        return results

    # ---------------------------------------------------------
    # CATEGORY CRUD
    # ---------------------------------------------------------
    def create_category(self, category_id: str, display_name: str, description: str = "", control_id: str = None) -> Dict:
        folder_name = category_id.lower().replace(" ", "_")
        folder_path = os.path.join(self.categories_root, folder_name)
        os.makedirs(folder_path, exist_ok=True)

        meta = {
            "category_id": category_id,
            "display_name": display_name,
            "description": description,
            **({"control_id": control_id} if control_id else {}),
        }
        with open(os.path.join(folder_path, "category.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        return meta

    def update_category(self, category_id: str, updates: Dict) -> Dict:
        folder_path = self._find_category_folder(category_id)
        meta_path = os.path.join(folder_path, "category.json")

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        for key in ("display_name", "description", "status", "control_id"):
            if key in updates:
                meta[key] = updates[key]

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        return meta

    def delete_category(self, category_id: str) -> bool:
        folder_path = self._find_category_folder(category_id)
        shutil.rmtree(folder_path)
        return True

    # ---------------------------------------------------------
    # QUESTION CRUD
    # ---------------------------------------------------------
    def create_question(self, question_data: Dict) -> Dict:
        category_id = question_data.get("category_id")
        question_id = question_data.get("question_id")
        if not category_id or not question_id:
            raise ValueError("category_id and question_id are required")

        folder_path = self._find_category_folder(category_id)
        file_path = os.path.join(folder_path, f"{question_id}.json")

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(question_data, f, indent=2, ensure_ascii=False)

        return question_data

    def update_question(self, question_id: str, updates: Dict) -> Dict:
        folder_path, file_name = self._find_question_file(question_id)
        file_path = os.path.join(folder_path, file_name)

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        data.update(updates)
        data["question_id"] = question_id  # prevent overwrite

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return data

    def delete_question(self, question_id: str) -> bool:
        folder_path, file_name = self._find_question_file(question_id)
        os.remove(os.path.join(folder_path, file_name))
        return True

    def _find_question_file(self, question_id: str):
        """Find the category folder and filename for a given question_id."""
        for folder in os.listdir(self.categories_root):
            folder_path = os.path.join(self.categories_root, folder)
            if not os.path.isdir(folder_path):
                continue
            for file in os.listdir(folder_path):
                if not file.endswith(".json") or file in ("category.json", "consistency.json"):
                    continue
                path = os.path.join(folder_path, file)
                with open(path, "r", encoding="utf-8") as f:
                    spec = json.load(f)
                if spec.get("question_id") == question_id:
                    return folder_path, file
        raise ValueError(f"Question not found: {question_id}")

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

            with open(category_json, "r", encoding="utf-8") as f:
                meta = json.load(f)

            if meta.get("category_id") == category_id:
                return folder_path

        raise ValueError(f"Category not found: {category_id}")

    def _load_category_meta(self, category_folder: str) -> Dict:
        path = os.path.join(category_folder, "category.json")
        with open(path, "r", encoding="utf-8") as f:
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

            with open(path, "r", encoding="utf-8") as f:
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
