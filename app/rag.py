import logging
import pickle
from pathlib import Path
from typing import Any

import chromadb
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.config import Settings
from app.llm import LLMClient
from app.utils import split_text

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self, settings: Settings, llm: LLMClient) -> None:
        self.settings = settings
        self.llm = llm
        self.db_path = settings.project_root / settings.chroma_dir
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.tfidf_path = self.db_path / "tfidf_index.pkl"

        self.chroma = chromadb.PersistentClient(path=str(self.db_path))
        self.collection = self.chroma.get_or_create_collection(settings.chroma_collection)

    async def ingest_markdown(self, file_path: str) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_absolute():
            path = (self.settings.project_root / file_path).resolve()

        if not path.exists():
            raise FileNotFoundError(f"knowledge file not found: {path}")

        raw = path.read_text(encoding="utf-8")
        chunks = split_text(raw, self.settings.chunk_size, self.settings.chunk_overlap)
        metadatas = [{"source": str(path), "chunk": i} for i, _ in enumerate(chunks)]

        if self.llm.available:
            logger.info("Ingest mode=chroma_openai, chunks=%s", len(chunks))
            embeddings = await self.llm.embed(chunks, self.settings.embedding_model)
            self._clear_chroma()
            ids = [f"faq-{i}" for i in range(len(chunks))]
            self.collection.upsert(
                ids=ids,
                documents=chunks,
                metadatas=metadatas,
                embeddings=embeddings,
            )
            mode = "chroma_openai"
        else:
            logger.info("Ingest mode=tfidf_fallback, chunks=%s", len(chunks))
            self._save_tfidf(chunks, metadatas)
            mode = "tfidf_fallback"

        return {"status": "ok", "mode": mode, "chunks": len(chunks), "source": str(path)}

    async def search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if self.llm.available:
            try:
                if self.collection.count() > 0:
                    q_emb = (await self.llm.embed([query], self.settings.embedding_model))[0]
                    result = self.collection.query(
                        query_embeddings=[q_emb],
                        n_results=top_k,
                        include=["documents", "metadatas", "distances"],
                    )
                    docs = result.get("documents", [[]])[0]
                    metas = result.get("metadatas", [[]])[0]
                    dists = result.get("distances", [[]])[0]
                    packed = []
                    for i, doc in enumerate(docs):
                        dist = dists[i] if i < len(dists) else 0.0
                        meta = metas[i] if i < len(metas) else {}
                        packed.append({"text": doc, "metadata": meta, "score": float(1 - dist)})
                    if packed:
                        return packed
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chroma retrieval failed, fallback tfidf: %s", exc)

        return self._search_tfidf(query, top_k)

    def _clear_chroma(self) -> None:
        count = self.collection.count()
        if count <= 0:
            return
        records = self.collection.get(limit=count, include=[])
        ids = records.get("ids", [])
        if ids:
            self.collection.delete(ids=ids)

    def _save_tfidf(self, chunks: list[str], metadatas: list[dict[str, Any]]) -> None:
        # Character n-grams keep the fallback retriever usable for Chinese FAQ text
        # and mixed inputs like order IDs without introducing a heavier dependency.
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        matrix = vectorizer.fit_transform(chunks)
        payload = {
            "vectorizer": vectorizer,
            "matrix": matrix,
            "documents": chunks,
            "metadatas": metadatas,
        }
        with self.tfidf_path.open("wb") as f:
            pickle.dump(payload, f)

    def _search_tfidf(self, query: str, top_k: int) -> list[dict[str, Any]]:
        if not self.tfidf_path.exists():
            logger.warning("TF-IDF index missing. Run /ingest first.")
            return []

        with self.tfidf_path.open("rb") as f:
            payload = pickle.load(f)  # noqa: S301

        vectorizer: TfidfVectorizer = payload["vectorizer"]
        matrix = payload["matrix"]
        docs: list[str] = payload["documents"]
        metas: list[dict[str, Any]] = payload["metadatas"]

        qv = vectorizer.transform([query])
        scores = cosine_similarity(qv, matrix).flatten()
        idx = np.argsort(scores)[::-1][:top_k]

        results = []
        for i in idx:
            if scores[i] <= 0:
                continue
            results.append({"text": docs[i], "metadata": metas[i], "score": float(scores[i])})
        return results
