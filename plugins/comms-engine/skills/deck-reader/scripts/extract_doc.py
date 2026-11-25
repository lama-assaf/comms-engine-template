#!/usr/bin/env python3
"""Extract a prose source (docx, xlsx, html, txt, md, or a prose pdf) to Markdown.

The deck reader handles slides. This handles the rest of the strategy corpus so
`corpus_sweep.py` can count it as read. Output goes to

    Docs/Research/sources/<stem>.md        (gitignored: internal-only syntheses)

with a small header recording the source path, its modification time and sha256,
so a later sweep can tell whether the reading is stale.

    extract_doc.py "<path>"            # writes Docs/Research/sources/<stem>.md
    extract_doc.py "<path>" -o out.md  # anywhere else
    extract_doc.py "<path>" --stdout   # print, write nothing

Dependencies: python-docx for .docx (present), pdfplumber for .pdf (present).
.xlsx and .html are read with the standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import sys
import zipfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO / "Docs" / "Research" / "sources"


# ---------------------------------------------------------------- docx


def read_docx(path: Path) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        return _read_docx_raw(path)
    from docx.oxml.ns import qn

    d = docx.Document(str(path))
    out: list[str] = []
    body = d.element.body
    for child in body.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            para = docx.text.paragraph.Paragraph(child, d)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            m = re.match(r"heading (\d)", style)
            if m:
                out.append("#" * (int(m.group(1)) + 1) + " " + text)
            elif style == "title":
                out.append("# " + text)
            elif "list" in style:
                out.append("- " + text)
            else:
                out.append(text)
            out.append("")
        elif tag == qn("w:tbl"):
            table = docx.table.Table(child, d)
            rows = [[c.text.strip().replace("\n", " ") for c in r.cells] for r in table.rows]
            if rows:
                out.append("| " + " | ".join(rows[0]) + " |")
                out.append("|" + "---|" * len(rows[0]))
                for r in rows[1:]:
                    out.append("| " + " | ".join(r) + " |")
                out.append("")
    # comments, if any, are evidence of review state
    try:
        with zipfile.ZipFile(path) as z:
            if "word/comments.xml" in z.namelist():
                root = ET.fromstring(z.read("word/comments.xml"))
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                comments = []
                for c in root.findall("w:comment", ns):
                    who = c.get(f"{{{ns['w']}}}author", "?")
                    txt = " ".join(t.text or "" for t in c.iter(f"{{{ns['w']}}}t")).strip()
                    if txt:
                        comments.append(f"- **{who}:** {txt}")
                if comments:
                    out += ["## document comments", "", *comments, ""]
    except zipfile.BadZipFile:
        pass
    return "\n".join(out)


def _read_docx_raw(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter(f"{ns}p"):
        t = "".join(x.text or "" for x in p.iter(f"{ns}t")).strip()
        if t:
            paras.append(t)
    return "\n\n".join(paras)


# ---------------------------------------------------------------- xlsx (stdlib)


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def read_xlsx(path: Path) -> str:
    main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    out: list[str] = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sroot.iter(f"{main}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{main}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rmap = {r.get("Id"): r.get("Target") for r in rels}
        for sheet in wb.iter(f"{main}sheet"):
            title = sheet.get("name")
            target = rmap.get(sheet.get(f"{rel}id"), "")
            target = target if target.startswith("xl/") else "xl/" + target.lstrip("/")
            if target not in names:
                continue
            sroot = ET.fromstring(z.read(target))
            grid: list[list[str]] = []
            for row in sroot.iter(f"{main}row"):
                cells: dict[int, str] = {}
                for c in row.iter(f"{main}c"):
                    v = c.find(f"{main}v")
                    is_ = c.find(f"{main}is")
                    if c.get("t") == "s" and v is not None:
                        val = shared[int(v.text)]
                    elif c.get("t") == "inlineStr" and is_ is not None:
                        val = "".join(t.text or "" for t in is_.iter(f"{main}t"))
                    else:
                        val = (v.text or "") if v is not None else ""
                    cells[_col_index(c.get("r", "A1"))] = val.strip()
                if any(cells.values()):
                    width = max(cells)
                    grid.append([cells.get(i, "") for i in range(1, width + 1)])
            out.append(f"## sheet: {title}")
            out.append("")
            if grid:
                width = max(len(r) for r in grid)
                grid = [r + [""] * (width - len(r)) for r in grid]
                out.append("| " + " | ".join(grid[0]) + " |")
                out.append("|" + "---|" * width)
                for r in grid[1:]:
                    out.append("| " + " | ".join(x.replace("|", "\\|") for x in r) + " |")
            else:
                out.append("_empty_")
            out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- html


class _Text(HTMLParser):
    BLOCK = {"p", "div", "li", "br", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote"}
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._tag: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def read_html(path: Path) -> str:
    p = _Text()
    p.feed(path.read_text(errors="replace"))
    text = html.unescape("".join(p.parts))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- pdf


def read_pdf(path: Path) -> str:
    import pdfplumber

    out: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            txt = page.extract_text() or ""
            out.append(f"<!-- page {i} -->")
            out.append(txt.strip())
            out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- probe


def probe(path: Path) -> str:
    """Say whether a file is slides or prose. PDFs: landscape pages or sparse
    text per page read as slides; everything else is prose."""
    ext = path.suffix.lower()
    if ext in (".pptx", ".key"):
        return "slides"
    if ext != ".pdf":
        return "prose"
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        pages = pdf.pages[:6]
        if not pages:
            return "prose"
        landscape = sum(1 for pg in pages if pg.width > pg.height)
        if landscape >= len(pages) / 2:
            return "slides"  # orientation settles it without touching the text
        words = [len((pg.extract_text() or "").split()) for pg in pages]
    if sum(words) / len(words) < 120:
        return "slides"
    return "prose"


# ---------------------------------------------------------------- main

READERS = {
    ".docx": read_docx,
    ".xlsx": read_xlsx,
    ".html": read_html,
    ".htm": read_html,
    ".pdf": read_pdf,
    ".txt": lambda p: p.read_text(errors="replace"),
    ".md": lambda p: p.read_text(errors="replace"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=None)
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--probe", action="store_true", help="print 'slides' or 'prose' and exit")
    args = ap.parse_args()

    src: Path = args.source.expanduser().resolve()
    if not src.is_file():
        print(f"not a file: {src}", file=sys.stderr)
        return 2
    if args.probe:
        print(probe(src))
        return 0
    reader = READERS.get(src.suffix.lower())
    if reader is None:
        print(f"no reader for {src.suffix}; slides go through extract_deck.py", file=sys.stderr)
        return 2

    body = reader(src)
    st = src.stat()
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    header = "\n".join(
        [
            f"# {src.stem}",
            "",
            f"- source: `{src}`",
            f"- modified: {datetime.fromtimestamp(st.st_mtime).isoformat(timespec='minutes')}",
            f"- sha256: `{digest}`",
            f"- extracted: {datetime.now().isoformat(timespec='minutes')} by extract_doc.py",
            "",
            "---",
            "",
        ]
    )
    text = header + body.rstrip() + "\n"

    if args.stdout:
        sys.stdout.write(text)
        return 0
    out = args.out or (DEFAULT_OUT / f"{src.stem}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    words = len(body.split())
    print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}  ({words} words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
