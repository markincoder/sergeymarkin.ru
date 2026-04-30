import os
from typing import List

import faiss
import numpy as np
from openai import OpenAI

from config import RAG_DATA_DIR

from .openai_key import openai_api_key

from .rag_index import load_faq_data


def _client() -> OpenAI:
    key = openai_api_key()
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to .env or environment before building the index."
        )
    return OpenAI(api_key=key)


RAG_DATA_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = str(RAG_DATA_DIR)
FAQ_JSON = "faq-items.json"
DATA_PATH = os.path.join(DATA_DIR, FAQ_JSON)
INDEX_PATH = os.path.join(DATA_DIR, "faiss_index.bin")
META_PATH = os.path.join(DATA_DIR, "faqs_metadata.npy")


def embed_texts(texts: List[str]) -> np.ndarray:
    response = _client().embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    vectors = [d.embedding for d in response.data]
    return np.array(vectors, dtype="float32")


def load_txt_documents(directory: str):
    """
    Загружает все .txt-файлы из папки и приводит их к формату FAQ.
    question — заголовок (первая непустая строка или имя файла),
    answer — остальной текст файла.
    """
    docs = []
    if not os.path.isdir(directory):
        return docs

    for name in os.listdir(directory):
        if not name.lower().endswith(".txt"):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read().strip()
        except OSError:
            continue

        if not content:
            continue

        lines = content.splitlines()
        # первая непустая строка как "заголовок"
        title = next((line.strip() for line in lines if line.strip()), name)
        body_lines = lines[1:] if len(lines) > 1 else []
        body = "\n".join(body_lines).strip() or content

        docs.append(
            {
                "question": title,
                "answer": body,
                "source": name,
            }
        )

    return docs


def main():
    items = []

    # 1) FAQ из JSON (если файл есть)
    if os.path.exists(DATA_PATH):
        faqs = load_faq_data(DATA_PATH)
        items.extend(faqs)
        print(f"Loaded {len(faqs)} FAQ items from {FAQ_JSON}")

    # 2) Документы из .txt-файлов
    txt_docs = load_txt_documents(DATA_DIR)
    items.extend(txt_docs)
    print(f"Loaded {len(txt_docs)} TXT documents from {DATA_DIR}")

    if not items:
        raise RuntimeError(
            f"Нет данных для индекса: положите {FAQ_JSON} и/или *.txt в backend/rag_data/, "
            "затем снова запустите этот скрипт и пересоберите Docker-образ."
        )

    texts = [f"{item['question']}\n{item['answer']}" for item in items]

    print(f"Embedding {len(texts)} items...")
    embeddings = embed_texts(texts)

    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)

    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    faiss.write_index(index, INDEX_PATH)

    # Save metadata (questions + answers + optional source)
    meta = np.array(
        [
            {
                "question": item["question"],
                "answer": item["answer"],
                "source": item.get("source", FAQ_JSON),
            }
            for item in items
        ],
        dtype=object,
    )
    np.save(META_PATH, meta)

    print(f"Index built and saved to {INDEX_PATH}")


if __name__ == "__main__":
    main()

