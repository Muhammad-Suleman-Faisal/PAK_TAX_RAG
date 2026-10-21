"""FBR ke Income Tax Manual / Act PDF ko RAG corpus (JSONL) mein badalta hai.

Misal:
  python ingest.py --input IncomeTaxOrdinanace2001_RAG.pdf --act income_tax \
      --amended-upto 2026-06-30 \
      --source https://www.fbr.gov.pk/Categ/Income-Tax-Ordinance/326 \
      --out data/corpus.jsonl

Ye kya karta hai:
  1. Har page ka text nikalta hai (poppler `pdftotext`, warna pypdf).
  2. Har page se running header, page number, ".." jaisi lines hataata hai.
  3. Page ke neeche ke footnotes ("Inserted by the Finance Act, 2011") alag karta hai
     aur section ke `notes` field mein rakhta hai (retrieval text saaf rehta hai).
  4. Text ke andar ke amendment markers `1[(a) ...]` saaf karta hai.
  5. Main body ko `NNN. Title. —` headings par section-wise todta hai
     (chapter ka naam metadata mein), lambay sections ko tukron mein.
  6. Schedules ko schedule ke naam ke tehat tukron mein todta hai.

Heuristics FBR ke is format ke liye hain. Doosre acts (Sales Tax waghaira) par chalayein
to output file dekh kar check karein, zaroorat ho to regexes adjust karein.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

# ---------- regexes ----------
HEADER_RE = re.compile(r"^\s*(?:Chapter\s+[IVX]+\s*[–-]|[A-Z][a-z]+\s+Schedule)[^\n]*_{3,}[\s_]*$")  # running header
JUNK_LINE_RE = re.compile(r"^\s*(\.{2,}|…+|\. \.|_{3,})\s*$")               # "..", "….", "____"
LONE_NUM_RE = re.compile(r"^\s*(\d{1,3})\s*$")
NOTE_HINT_RE = re.compile(
    r"(Finance Act|Finance \(|Ordinance|Act,? ?\d{4}|Tax Laws|S\.?R\.?O|Amendment|substituted|"
    r"inserted|omitted|Inserted|Substituted|Omitted|Added|deleted)", re.I)
NOTE_OPEN_RE = re.compile(
    r"^\s*(Inserted|Substituted|Omitted|Added|Amended|Deleted|Section|Sub-?section|Clause|Proviso|"
    r"Explanation|New|The|Words?|Figure|Full|Comma|Colon|Semi|Paragraph|Item|Entry|Table|Serial|This|"
    r"Such|Heading|Rule|Schedule|Expression|Letter|Number|Part|Chapter|Existing|Earlier|Brackets?|"
    r"Condition|Definition|Division|Amount|Rate|Para|Same|Wording|Omission|Insertion|Substitution|"
    r"Inclusion|Replacement|Sr\.|Sub-|[A-Z][a-z]+ (Schedule|section|clause))\b|^\s*[“\"‘']")
STRONG_NOTE_RE = re.compile(
    r"^\s*(?:Clause|Sub-?section|Section|Proviso|Explanation|Words?|Figure|Item|Paragraph|Inserted|Substituted|"
    r"Omitted|Added|Amended|Deleted|The (?:word|words|expression|expressions|figure|figures|comma|colon|"
    r"full stop|proviso|explanation|clause|sub-section|section|brackets?|entry|item))\b[^\n]{0,200}?"
    r"\b(?:substituted|inserted|omitted|added|amended|deleted|renumbered)\b[^\n]{0,120}?"
    r"(?:Finance\s*(?:Act|\(|Supplementary|Ordinance)|Ordinance|Tax\s*Laws|S\.?R\.?O|Act,?\s*\d{4})", re.I)
REF_MARK_RE = re.compile(r"(?<![A-Za-z0-9])\d{1,3}\[")                      # "1[(a) ...]" ka "1["
# heading ke formats: "114. Return of income.—", "1.\nShort title.—", "1[74.\n\nTax year.—", "1[177. Audit.—"
SECTION_RE = re.compile(
    r"^(?:\d{1,3}\[\s*)*\[?(\d{1,3}[A-Z]{0,3})\.\s+([A-Z0-9][^—–\n]*(?:\n{1,2}[^—–\n]*)?)\.[ \t]*(?:[—–]|-)",
    re.MULTILINE,
)
CHAPTER_RE = re.compile(r"^CHAPTER\s+([IVX]+)\s*\n+\s*([A-Z][^\n]+)", re.MULTILINE)
SCHEDULE_RE = re.compile(r"^\s*(?:\d{1,3}\[)*\[?\s*(?:THE\s+)?([A-Z]+)\s+SCHEDULE\s*\]?\s*$", re.MULTILINE)
PAGE_MARK_RE = re.compile(r"\x02(\d+)\x02")


# ---------- text extraction ----------
def extract_pages(pdf: Path) -> list[str]:
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, check=True).stdout
        pages = out.decode("utf-8", errors="ignore").split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        return pages
    from pypdf import PdfReader  # fallback
    return [(p.extract_text() or "") for p in PdfReader(str(pdf)).pages]


def split_page(raw: str) -> tuple[str, str]:
    """Page ko (body, footnotes) mein todta hai aur header / page number hataata hai."""
    lines = [l for l in raw.split("\n") if not HEADER_RE.match(l) and not JUNK_LINE_RE.match(l)]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.fullmatch(r"\s*\d{1,4}\s*", lines[-1]):      # aakhri number = page number
        lines.pop()
    cut = None                                                    # footnote block ki shuruaat
    for k, l in enumerate(lines):
        if LONE_NUM_RE.match(l):
            look = [x for x in lines[k + 1:k + 6] if x.strip()][:3]
            if look and NOTE_OPEN_RE.match(look[0]) and NOTE_HINT_RE.search(" ".join(look)):
                cut = k
                break
    # doosri rule: reading-order ki wajah se number alag ho jaye to note line ko seedha pehchano
    ne = [k for k, l in enumerate(lines) if l.strip()]
    for pos, k in enumerate(ne):
        nxt = lines[ne[pos + 1]] if pos + 1 < len(ne) else ""
        if STRONG_NOTE_RE.match(lines[k] + " " + nxt) and not re.match(r"\s*\d{1,3}\.\s", lines[k]):
            c2 = k
            if pos > 0 and LONE_NUM_RE.match(lines[ne[pos - 1]]):
                c2 = ne[pos - 1]                  # peeche wala lone number bhi footnote ka hissa hai
            cut = c2 if cut is None else min(cut, c2)
            break
    if cut is None:
        return "\n".join(lines), ""
    notes, cur = [], ["?", ""]
    notes.append(cur)
    for l in lines[cut:]:
        m = LONE_NUM_RE.match(l)
        if m:
            cur = [m.group(1), ""]
            notes.append(cur)
        elif l.strip() and cur is not None:
            cur[1] += " " + l.strip()
    foot = " | ".join(f"({n}) {t.strip()}" for n, t in notes if t.strip())
    return "\n".join(lines[:cut]), foot


GLUED_NUM_RE = re.compile(r"(?<=[a-z])\d{1,2}(?=[;:,.\s])")                 # "expenditure2;" ka footnote number


def clean_text(t: str) -> str:
    t = REF_MARK_RE.sub("", t)
    t = GLUED_NUM_RE.sub("", t)
    t = t.replace("[", "").replace("]", "")
    t = "\n".join(l for l in t.split("\n") if not JUNK_LINE_RE.match(l))
    t = re.sub(r"\n(?=\s*\(([a-z]{1,3}|[0-9]{1,2}|[ivx]{1,5})\)\s)", "\x01", t)   # sub-clause starts
    t = re.sub(r"\s+", " ", t.replace("\x01", "\n")).replace("\n ", "\n")
    return re.sub(r" *\n *", "\n", t).strip()


def pack(text: str, max_chars: int) -> list[str]:
    """Lambay text ko max_chars ke aas paas, line/clause boundary par todta hai."""
    if len(text) <= max_chars:
        return [text]
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > max_chars * 1.5:            # bohat lambi line: space par tod do
            cut = line.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:cut])
            line = line[cut:].lstrip()
        if cur and len(cur) + len(line) + 1 > max_chars:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def num_part(sec: str) -> int:
    return int(re.match(r"\d+", sec).group())


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--act", required=True)
    ap.add_argument("--amended-upto", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", default="data/corpus.jsonl")
    ap.add_argument("--max-chars", type=int, default=3000)
    ap.add_argument("--append", action="store_true", help="file mein append karo (default: overwrite)")
    a = ap.parse_args()

    pages = extract_pages(Path(a.input))
    bodies, foots = zip(*[split_page(p) for p in pages])
    print(f"{len(pages)} pages parhe gaye")

    # body: "CHAPTER I / PRELIMINARY" wale page se pehle "THE FIRST SCHEDULE" wale page tak
    start = next((i for i, p in enumerate(pages)
                  if i > 5 and re.search(r"^CHAPTER I\s*\n+\s*PRELIMINARY", p, re.M)), 0)
    sched_start = next((i for i in range(start, len(pages))
                        if re.search(r"^\s*THE FIRST SCHEDULE\s*$", pages[i], re.M)), len(pages))
    print(f"main body: pages {start+1}-{sched_start}, schedules: pages {sched_start+1}-{len(pages)}")

    # ---- body ko ek text mein jodo, page offsets yaad rakho ----
    parts_text, offsets, pos = [], [], 0
    for i in range(start, sched_start):
        offsets.append((pos, i))
        parts_text.append(bodies[i] + "\n")
        pos += len(parts_text[-1])
    body = "".join(parts_text)

    def page_at(p: int) -> int:
        idx = offsets[0][1]
        for off, i in offsets:
            if off <= p:
                idx = i
            else:
                break
        return idx

    chapters = [(m.start(), f"Chapter {m.group(1)} - {m.group(2).strip().title()}")
                for m in CHAPTER_RE.finditer(body)]

    def chapter_at(p: int) -> str:
        c = ""
        for off, name in chapters:
            if off <= p:
                c = name
            else:
                break
        return c

    # ---- sections ----
    heads, last = [], 0
    for m in SECTION_RE.finditer(body):
        n = num_part(m.group(1))
        if last <= n <= last + 30:                       # sequence sanity: stray matches reject
            heads.append(m)
            last = n
    records = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        sec = m.group(1)
        title = re.sub(r"\s+", " ", clean_text(m.group(2))).strip(" .-—–")
        p0, p1 = page_at(m.start()), page_at(max(end - 1, m.start()))
        text = clean_text(body[m.end() - 1:end]).lstrip("—–- ").strip()
        notes = " || ".join(dict.fromkeys(f for f in foots[p0:p1 + 1] if f))[:4000]
        parts = pack(text, a.max_chars)
        for j, part in enumerate(parts):
            records.append({
                "id": f"{a.act}-{sec}" + (f"-{j+1}" if len(parts) > 1 else ""),
                "act": a.act, "section": sec, "title": title, "chapter": chapter_at(m.start()),
                "chunk": j + 1, "chunks_total": len(parts), "page_start": p0 + 1,
                "amended_upto": a.amended_upto, "source": a.source,
                "text": part, "notes": notes if j == 0 else "",
            })
    n_sections = len(heads)

    # ---- schedules ----
    stext = "".join(f"\x02{i}\x02\n{bodies[i]}\n" for i in range(sched_start, len(pages)))
    spans, seen = [], set()
    for m in SCHEDULE_RE.finditer(stext):                 # har schedule ka pehla heading hi lo
        name = m.group(1).title()
        if name not in seen:
            seen.add(name)
            spans.append((m.start(), name))
    for k, (pos_, name) in enumerate(spans):
        end = spans[k + 1][0] if k + 1 < len(spans) else len(stext)
        seg = stext[pos_:end]
        before = PAGE_MARK_RE.findall(stext[:pos_ + 1])
        first_page = int(before[-1]) + 1 if before else sched_start + 1
        seg_pages = [int(x) for x in PAGE_MARK_RE.findall(seg)]
        notes = " || ".join(dict.fromkeys(foots[p] for p in seg_pages if foots[p]))[:4000]
        parts = pack(clean_text(PAGE_MARK_RE.sub("", seg)), a.max_chars)
        label = f"{name} Schedule"
        for j, part in enumerate(parts):
            records.append({
                "id": f"{a.act}-{label.replace(' ', '')}-{j+1}",
                "act": a.act, "section": label, "title": label, "chapter": "Schedules",
                "chunk": j + 1, "chunks_total": len(parts), "page_start": first_page,
                "amended_upto": a.amended_upto, "source": a.source,
                "text": part, "notes": notes if j == 0 else "",
            })

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "a" if a.append else "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"sections: {n_sections}, schedules: {len(spans)}, total chunks: {len(records)} -> {a.out}")


if __name__ == "__main__":
    main()
