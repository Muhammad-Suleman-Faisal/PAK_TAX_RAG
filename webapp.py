"""Free web UI: browser mein sawal poochein, sections aur citations dekhein.

    python webapp.py            ->  http://127.0.0.1:8000

- Retrieval seedha rag_core.Retriever se hota hai, is liye tez hai.
- Koi paid API nahi, sab kuch aap ke computer par chalta hai.
"""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from rag_core import Retriever, load_corpus

HERE = Path(__file__).parent

docs = load_corpus()
retriever = Retriever(docs)
def _roman(c: str) -> int:
    import re
    m = re.match(r"Chapter ([IVX]+)", c)
    if not m:
        return 10**6
    vals = {"I": 1, "V": 5, "X": 10}
    r, prev = 0, 0
    for ch in reversed(m.group(1)):
        v = vals[ch]
        r += -v if v < prev else v
        prev = max(prev, v)
    return r


CHAPTERS = sorted({d.get("chapter", "") for d in docs if d.get("chapter")}, key=lambda c: (_roman(c), c))


def card(d: dict, snippet: int = 450) -> dict:
    return {
        "act": d["act"], "section": d["section"], "title": d["title"],
        "chapter": d.get("chapter", ""), "page": d.get("page_start"),
        "amended_upto": d.get("amended_upto", ""), "source": d.get("source", ""),
        "snippet": d["text"][:snippet] + ("…" if len(d["text"]) > snippet else ""),
        "score": d.get("score"),
    }


async def index(_: Request):
    return FileResponse(HERE / "static" / "index.html")


async def meta(_: Request):
    return JSONResponse({"chapters": CHAPTERS, "chunks": len(docs)})


async def search(request: Request):
    q = request.query_params.get("q", "").strip()
    chapter = request.query_params.get("chapter", "")
    if not q:
        return JSONResponse({"results": []})
    hits = retriever.search(q, top_k=40)
    if chapter:
        hits = [h for h in hits if h.get("chapter") == chapter]
    # ek hi section ke kai chunks ho to sirf behtareen wala dikhao
    seen, out = set(), []
    for h in hits:
        key = (h["act"], h["section"])
        if key in seen:
            continue
        seen.add(key)
        out.append(card(h))
        if len(out) >= 8:
            break
    return JSONResponse({"results": out})


async def section(request: Request):
    act = request.query_params.get("act", "")
    sec = request.query_params.get("section", "")
    d = retriever.get_section(act, sec)
    if not d:
        return JSONResponse({"error": "section nahi mila"}, status_code=404)
    return JSONResponse({**card(d, snippet=10**9), "text": d["text"], "notes": d.get("notes", ""),
                         "refs": find_refs(act, d["text"], d["section"])})


import re as _re

_SECS = {(d["act"], d["section"]): d["title"] for d in docs}
_REF = _re.compile(r"\bsections?\s+(\d{1,3}[A-Z]{0,3})\b")


def find_refs(act: str, text: str, own: str) -> list[dict]:
    """Text mein "section 113" jaise hawale dhoondta hai jo corpus mein maujood hon."""
    out, seen = [], set()
    for m in _REF.finditer(text):
        sec = m.group(1)
        if sec != own and sec not in seen and (act, sec) in _SECS:
            seen.add(sec)
            out.append({"section": sec, "title": _SECS[(act, sec)]})
    return out[:12]


async def tree(_: Request):
    out, idx = [], {}
    for d in docs:
        ch = d.get("chapter") or "Other"
        if ch not in idx:
            idx[ch] = {"name": ch, "sections": [], "_seen": set()}
            out.append(idx[ch])
        e = idx[ch]
        if d["section"] not in e["_seen"]:
            e["_seen"].add(d["section"])
            e["sections"].append({"s": d["section"], "t": d["title"], "a": d["act"]})
    for e in out:
        e.pop("_seen")
    out.sort(key=lambda e: (_roman(e["name"]), e["name"]))
    return JSONResponse(out)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/meta", meta),
    Route("/api/search", search),
    Route("/api/section", section),
    Route("/api/tree", tree),
])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8000)))
