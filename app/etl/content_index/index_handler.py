import os
import asyncio
import hashlib
import json
import re
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.types.doc.labels import DocItemLabel
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer


from app.llms.ollama_client import OllamaClient


class IndexHandler:

    # Cold storage for raw tables (NOT used during retrieval, only for inspection / follow-up) 
    TABLE_STORE_DIR = Path("./table_store")
    TABLE_STORE_DIR.mkdir(parents=True, exist_ok=True)


    COLLECTION_PREFIX = "docling_rag"

    TABLE_SYSTEM_PROMPT = """
You summarize technical tables for retrieval purposes.

Guidelines:
- Describe what the table compares
- Mention units only if explicitly present in column names
- Do NOT compute, infer, or extrapolate values
- Do NOT restate every row
- Do NOT introduce information not present in the table
- Use neutral, technical language
- One short paragraph only
"""

    EQUATION_SYSTEM_PROMPT = """
You convert mathematical equations into neutral, textbook-style definitions.

Guidelines:
- Use only the symbols provided in the equation
- Do NOT infer domain assumptions
- Do NOT explain derivations or implications
- Do NOT introduce new variables or units
- Write exactly one clear declarative sentence
- Use precise but simple technical language
"""

    def __init__(self, pdf_path: str):
        self.pdf = pdf_path
        self.doc_id = Path(pdf_path).name

        self.ollama_client = OllamaClient(model="qwen2.5:1.5b")

        # self.embed_model = SentenceTransformer("BAAI/bge-large-en-v1.5")
        self.embed_model = SentenceTransformer("BAAI/bge-base-en-v1.5")
        self.embedding_dim = self.embed_model.get_sentence_embedding_dimension()

        self.qdclient = QdrantClient(host=os.getenv("QDRANT_HOST", "qdrant"), 
            port=int(os.getenv("QDRANT_PORT", 6333)))

        self.collection_name = f"{self.COLLECTION_PREFIX}_{self.safe_id(self.doc_id)}"

        self.qdclient.recreate_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=self.embedding_dim,
                distance=Distance.COSINE,
            ),
        )

    # ------------------------------------------------------------------
    @staticmethod
    def safe_id(raw_id: str) -> str:
        return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def qdrant_id(raw_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw_id))

    # ------------------------------------------------------------------
    @staticmethod
    def extract_table_struct(item):
        """
        Correct extractor for Docling TableData.table_cells (latest versions).
        """
        table_data = item.data

        # Defensive
        if not hasattr(table_data, "table_cells") or not table_data.table_cells:
            return {
                "columns": [],
                "rows": [],
            }

        # Build grid using row/col offsets
        grid = {}

        for cell in table_data.table_cells:
            r = cell.start_row_offset_idx
            c = cell.start_col_offset_idx
            text = (cell.text or "").strip()

            grid.setdefault(r, {})[c] = text

        # Sort rows and columns
        rows = [
            [row[c] for c in sorted(row)]
            for _, row in sorted(grid.items())
        ]

        # Heuristic: first row = column headers
        columns = rows[0] if rows else []
        body_rows = rows[1:] if len(rows) > 1 else []

        return {
            "columns": columns,
            "rows": body_rows,
        }
    



    @staticmethod
    def store_raw_table(table_id: str, raw_table: dict) -> str:
        safe_id = IndexHandler.safe_id(table_id)
        path = IndexHandler.TABLE_STORE_DIR / f"{safe_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(raw_table, f, indent=2, ensure_ascii=False)
        return safe_id

    @staticmethod
    def build_table_prompt(columns, rows, section_path):
        return f"""
      Table columns:
      {columns}

      Sample rows:
      {rows[:5]}

      Section context:
      {section_path}
      """

    @staticmethod
    def extract_symbols(latex: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z]+", latex))

    @staticmethod
    def extract_equation_content(item):
        if getattr(item, "latex", None):
            return item.latex, "symbolic"
        if getattr(item, "mathml", None):
            return item.mathml, "symbolic"
        return None, "reference"

    # ------------------------------------------------------------------
    def doc_converter(self):
        converter = DocumentConverter()
        result = converter.convert(self.pdf)
        return result.document

    def make_chunk(self, chunk_id, chunk_type, verbal_text, payload=None):
        return {
            "id": chunk_id,
            "chunk_type": chunk_type,
            "verbal": verbal_text,
            "payload": payload or {},
        }

    # ------------------------------------------------------------------
    async def generate_chunks(self):
        section_stack = []
        section_text_buffer = defaultdict(list)
        chunks = []

        def update_section_stack(stack, level, title):
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))

        doc = self.doc_converter()

        for item, level in doc.iterate_items():
            if item.label == DocItemLabel.SECTION_HEADER:
                update_section_stack(section_stack, level, item.text)
                continue

            section_path = [t for _, t in section_stack]
            page_no = item.prov[0].page_no if item.prov else None

            if item.label == DocItemLabel.TEXT and item.text:
                section_text_buffer[tuple(section_path)].append(item.text)

                if len(item.text.split()) >= 40:
                    chunks.append(
                        self.make_chunk(
                            f"text_p{page_no}_{item.self_ref}",
                            "section_text",
                            item.text,
                            {
                                "page": page_no,
                                "section_path": section_path,
                            },
                        )
                    )
                continue

            if item.label == DocItemLabel.LIST_ITEM and item.text:
                if len(item.text.split()) >= 20:
                    chunks.append(
                        self.make_chunk(
                            f"list_p{page_no}_{item.self_ref}",
                            "algorithm_step",
                            item.text,
                            {
                                "page": page_no,
                                "section_path": section_path,
                            },
                        )
                    )
                continue

            if item.label == DocItemLabel.FORMULA:
                equation, mode = self.extract_equation_content(item)

                if mode == "symbolic" and equation:
                    symbols = self.extract_symbols(equation)
                    verbal = await self.ollama_client.complete(
                        system_prompt=self.EQUATION_SYSTEM_PROMPT,
                        user_prompt=equation,
                    )
                    text = verbal.strip() if verbal else "Mathematical equation."
                else:
                    text = "This section contains a mathematical equation."
                    symbols = set()

                chunks.append(
                    self.make_chunk(
                        f"eq_p{page_no}_{item.self_ref}",
                        "equation_reference",
                        text,
                        {
                            "page": page_no,
                            "section_path": section_path,
                            "latex": equation,
                            "symbols": list(symbols),
                        },
                    )
                )
                continue

            if item.label == DocItemLabel.TABLE:
                table_id = f"tbl_p{page_no}_{item.self_ref}"
                raw_table = self.extract_table_struct(item)
                table_ref = self.store_raw_table(table_id, raw_table)

                summary = await self.ollama_client.complete(
                    system_prompt=self.TABLE_SYSTEM_PROMPT,
                    user_prompt=self.build_table_prompt(
                        raw_table["columns"],
                        raw_table["rows"],
                        section_path,
                    ),
                )

                if summary:
                    chunks.append(
                        self.make_chunk(
                            f"tbl_{table_ref}",
                            "table_summary",
                            summary.strip(),
                            {
                                "page": page_no,
                                "section_path": section_path,
                                "table_ref": table_ref,
                                "columns": raw_table["columns"],
                            },
                        )
                    )
                continue

        # Section summaries
        for section_path, texts in section_text_buffer.items():
            full_text = "\n".join(texts)
            if len(full_text.split()) < 80:
                continue

            summary = await self.ollama_client.complete(
                system_prompt="Summarize this technical section in 2–3 sentences.",
                user_prompt=full_text,
            )

            if summary:
                chunks.append(
                    self.make_chunk(
                        f"summary_{hash(section_path)}",
                        "text_summary",
                        summary.strip(),
                        {"section_path": list(section_path)},
                    )
                )

        return chunks

    # ------------------------------------------------------------------
    def encode(self):
        chunks = asyncio.run(self.generate_chunks())

        EMBEDDABLE = {
            "text_summary",
            "table_summary",
            "equation_reference",
            "algorithm_step",
        }

        embeddable_chunks = [c for c in chunks if c["chunk_type"] in EMBEDDABLE]
        texts = [c["verbal"] for c in embeddable_chunks]

        vectors = self.embed_model.encode(texts, normalize_embeddings=True)

        points = []
        for chunk, vector in zip(embeddable_chunks, vectors):
            payload = {
                "doc_id": self.doc_id,
                "chunk_id": chunk["id"],
                "chunk_type": chunk["chunk_type"],
                "text": chunk["verbal"],
                **chunk["payload"],
            }

            points.append(
                PointStruct(
                    id=self.qdrant_id(chunk["id"]),
                    vector=vector.tolist(),
                    payload=payload,
                )
            )

        self.qdclient.upsert(
            collection_name=self.collection_name,
            points=points,
        )

    # ------------------------------------------------------------------
    def print_collection(self):
        counts = Counter()
        offset = None

        while True:
            points, offset = self.qdclient.scroll(
                collection_name=self.collection_name,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            for p in points:
                counts[p.payload["chunk_type"]] += 1
            if offset is None:
                break

        print(counts)


if __name__ == "__main__":
    ih = IndexHandler("/app/app/etc/docs/ai_eat_your_business.pdf")
    # import os
    # print(f"------------Current Dir: ------------{os.getcwd()}")
    ih.encode()
    ih.print_collection()