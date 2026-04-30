import json
import os
from typing import List, Tuple, Any

import faiss
import numpy as np


def load_index(index_path: str, meta_path: str) -> Tuple[faiss.IndexFlatL2, np.ndarray]:
    if not os.path.exists(index_path) or not os.path.exists(meta_path):
        raise RuntimeError(
            "FAISS index or metadata not found in backend/rag_data/. "
            "Run `python -m backend.build_index` from the project root to build the RAG index."
        )

    index = faiss.read_index(index_path)
    metadata = np.load(meta_path, allow_pickle=True)
    return index, metadata


def search_similar(
    index: faiss.IndexFlatL2,
    metadata: np.ndarray,
    query_vec: np.ndarray,
    k: int = 3,
) -> tuple[List[Any], List[float]]:
    """Возвращает (метаданные попаданий, L2-расстояния). Меньше distance — ближе к запросу."""
    distances, indices = index.search(query_vec, k)
    idxs = indices[0]
    dist_row = distances[0]
    results: List[Any] = []
    dists: List[float] = []
    for j, i in enumerate(idxs):
        if 0 <= i < len(metadata):
            results.append(metadata[i])
            dists.append(float(dist_row[j]))
    return results, dists


def load_faq_data(path: str):
    """Загружает FAQ данные из JSON файла."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


