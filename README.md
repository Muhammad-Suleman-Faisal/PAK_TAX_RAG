# Pakistan Tax Navigator

A free, local search-and-browse tool for Pakistan's **Income Tax Ordinance, 2001**.
It runs entirely on your own computer: no API keys, no paid services, no data leaves your machine.

## Features

* **Browse** the Ordinance chapter by chapter, or **search** by keyword with highlighted matches.
* **Reader view**: full section text, links to the sections it refers to, footnotes / amendment history
(e.g. "Inserted by the Finance Act, 2011"), copy-citation, bookmarks, and print.
* **English / Urdu interface** (the legal text itself stays in English).
* **`ingest.py`** builds the searchable corpus from the official FBR PDF: section-wise chunks,
chapter and page metadata, footnotes kept as amendment notes.

> \*\*The data is not included in this repository.\*\* Download the Ordinance PDF from the
> \[FBR website](https://www.fbr.gov.pk) and run `ingest.py` (see below). Without it, the app falls back to
> four placeholder sample chunks that are \*not\* the real law.

## Quick start

Requires Python 3.10+ (tested with 3.12 and 3.15).

```bash
git clone https://github.com/Muhammad-Suleman-Faisal/PAK\_TAX\_RAG.git

cd PAK\_TAX\_RAG

python -m venv venv
# Windows PowerShell: venv\\Scripts\\Activate.ps1     Windows cmd: venv\\Scripts\\activate.bat
source venv/bin/activate
pip install -r requirements.txt
```

### 1\. Build the corpus from the FBR PDF

```bash
python ingest.py --input IncomeTaxOrdinance.pdf --act income\_tax \\
    --amended-upto 2026-06-30 \\
    --source https://www.fbr.gov.pk/Categ/Income-Tax-Ordinance/326 \\
    --out data/corpus.jsonl
```

Use the date printed on your PDF for `--amended-upto`. Then check the output: for the FBR "Income Tax Manual"
PDF (amended upto 30 June 2026) this produced 366 sections and 14 schedules. Other PDFs or versions may format
headings differently, so inspect `data/corpus.jsonl` and adjust the regexes in `ingest.py` if needed.
[Poppler](https://poppler.freedesktop.org) (`pdftotext`) is recommended; without it the script falls back to
`pypdf`, which has been tested less.

### 2\. Run

```bash
python webapp.py
```

Open **http://127.0.0.1:8000**. To use another port: `PORT=8001 python webapp.py`
(PowerShell: `$env:PORT=8001; python webapp.py`).

## How it works

```
Browser  ->  webapp.py (Starlette)  ->  rag\_core.py (TF-IDF retriever)  ->  data/corpus.jsonl
```

|File|Purpose|
|-|-|
|`webapp.py`|Local web server and JSON endpoints (`/api/search`, `/api/section`, `/api/tree`, `/api/meta`)|
|`rag\_core.py`|Loads the corpus and ranks chunks with TF-IDF|
|`ingest.py`|Converts the FBR PDF into `data/corpus.jsonl`|
|`static/index.html`|Single-page UI (English / Urdu, RTL support)|
|`data/sample\_corpus.jsonl`|Four placeholder chunks used when no real corpus exists|

## Limitations

* **Keyword search, not semantic search.** Short questions can miss the right section
(for example, "what is the tax year" may not rank section 74 first). Embedding-based retrieval would help.
* **Urdu queries are not supported**, because the corpus is English. The Urdu mode translates the interface only.
* **Schedule rate tables can be scrambled** by PDF text extraction. Verify any rate against the original PDF.
* About 4% of chunks still contain some leftover footnote text.
* Only the Income Tax Ordinance is covered; other laws (Sales Tax, Federal Excise, Customs) are not.

## Disclaimer

This is **not legal or tax advice**. The tool may contain extraction errors and may be out of date.
Always verify against the official text and its "amended upto" date.
The source documents are published by the Federal Board of Revenue (FBR); this repository does not
redistribute them.

