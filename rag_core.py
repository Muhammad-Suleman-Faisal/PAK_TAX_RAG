"""RAG ka core: corpus load karna aur retrieval.

Yahan TF-IDF use kiya hai taake koi model download na karna pade aur example
foran chale. Production mein `Retriever` ko embedding + vector DB (Qdrant,
Chroma, pgvector...) se replace kar dein, baqi poora system waisa hi rahega.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer

_DATA = Path(__file__).parent / "data"
# asli corpus (ingest.py ka output) ho to wahi, warna sample
DEFAULT_CORPUS = _DATA / "corpus.jsonl" if (_DATA / "corpus.jsonl").exists() else _DATA / "sample_corpus.jsonl"


def load_corpus(path: str | os.PathLike | None = None) -> list[dict]:
    path = Path(path or os.environ.get("PKTAX_CORPUS", DEFAULT_CORPUS))
    docs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return docs


class Retriever:
    SCHEDULE_WEIGHT = 0.7

    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, lowercase=True, stop_words="english")
        # title ko do dafa daalte hain taake heading match ko weight mile
        self.matrix = self.vec.fit_transform(
            [f"{d['title']} {d['title']} {d['section']} {d['text']}" for d in docs]
        )

    def search(self, query: str, act: str | None = None, top_k: int = 5) -> list[dict]:
        q = self.vec.transform([query])
        scores = (self.matrix @ q.T).toarray().ravel()
        for i, d in enumerate(self.docs):          # schedules ke bade table-chunks generic queries par haavi na hon
            if d.get("chapter") == "Schedules":
                scores[i] *= self.SCHEDULE_WEIGHT
        order = scores.argsort()[::-1]
        out = []
        for i in order:
            d = self.docs[i]
            if scores[i] <= 0:
                break
            if act and d["act"] != act:
                continue
            out.append({**d, "score": round(float(scores[i]), 4)})
            if len(out) >= top_k:
                break
        return out

    def get_section(self, act: str, section: str) -> dict | None:
        """Section ke saare chunks jod kar wapas karta hai (lambay sections kai chunks mein hote hain)."""
        section = section.strip().lower()
        parts = [d for d in self.docs if d["act"] == act and d["section"].lower() == section]
        if not parts:
            return None
        parts.sort(key=lambda d: d.get("chunk", 1))
        first = dict(parts[0])
        first["text"] = "\n".join(d["text"] for d in parts)
        first["chunk"], first["chunks_total"] = 1, 1
        return first

    def acts(self) -> list[str]:
        return sorted({d["act"] for d in self.docs})
