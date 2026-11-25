#!/usr/bin/env python3
"""
Pass 1 + Pass 2 engine for the deck-reader skill.

Reads a .pdf or .pptx and emits, into an output directory:

    slides/slide-N.png    rendered pages, for the vision pass (Pass 3)
    shape_structure.txt   every object with geometry, fill and z-index,
                          in TRUE content-stream order; text blocks carry
                          font, point size and hex colour
    rawmeta.txt           file metadata, image inventory, font subsets,
                          and (pptx only) theme, masters and speaker notes
    outline.md            Pass 2: title/bullet hierarchy, per-slide function
                          label, visual-element tags and chunk boundaries

Design notes that matter, and why:

  * Content-stream order is taken from pdfminer's LTPage children, which
    interleave rects, lines, curves, images and chars as the page paints
    them. pdfplumber's page.objects groups by type and therefore destroys
    cross-type ordering -- earlier dumps in this repo carried a caveat
    saying cross-type z-order claims were invalid. They are valid here.

  * A .pptx is read through its shape tree, which yields shape NAMES.
    Those are the highest-value archaeology in a deck (a chip still named
    for a partner who was dropped, say) and no PDF can give them up.

Usage:
    extract_deck.py SOURCE [-o OUTDIR] [--dpi N] [--ocr auto|always|never]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

EMU_PER_PT = 12700


def die(msg: str) -> None:
    sys.stderr.write(f"error: {msg}\n")
    raise SystemExit(1)


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def to_hex(color) -> str:
    """pdfminer colours arrive as gray, rgb or cmyk tuples, or bare floats."""
    if color is None:
        return "none"
    if isinstance(color, (int, float)):
        color = (color,)
    try:
        vals = [float(c) for c in color]
    except (TypeError, ValueError):
        return "?"
    if len(vals) == 1:
        r = g = b = vals[0]
    elif len(vals) == 3:
        r, g, b = vals
    elif len(vals) == 4:
        c, m, y, k = vals
        r, g, b = (1 - min(1, c + k), 1 - min(1, m + k), 1 - min(1, y + k))
    else:
        return "?"
    # values are normally 0..1 but some producers emit 0..255
    if max(vals) > 1.0:
        r, g, b = (v / 255.0 for v in (r, g, b))
    clamp = lambda v: max(0, min(255, int(round(v * 255))))  # noqa: E731
    return f"#{clamp(r):02X}{clamp(g):02X}{clamp(b):02X}"


def fmt_box(x0, y0, w, h) -> str:
    return f"box(x{x0:.0f} y{y0:.0f} w{w:.0f} h{h:.0f})"


def clean_font(name: str) -> str:
    """Drop the arbitrary six-letter subset prefix ('AAAAAB+Arial' -> 'Arial').

    The prefix is assigned per embedded subset, so the same typeface at the
    same size can carry three different prefixes on one page. Grouping on the
    raw name shatters a single visual line into several blocks.
    """
    return re.sub(r"^[A-Z]{6}\+", "", name or "?")


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def soffice_to_pdf(src: Path, workdir: Path) -> Path:
    """Convert a .pptx to PDF so it can be rendered and measured."""
    if not have("soffice"):
        die("soffice (LibreOffice) not found; needed to render a .pptx")
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir",
         str(workdir), str(src)],
        check=True, capture_output=True, timeout=300,
    )
    out = workdir / (src.stem + ".pdf")
    if not out.exists():
        die(f"LibreOffice produced no PDF for {src.name}")
    return out


def render(pdf: Path, slides_dir: Path, dpi: int) -> list[Path]:
    if not have("pdftoppm"):
        die("pdftoppm not found (brew install poppler)")
    slides_dir.mkdir(parents=True, exist_ok=True)
    for stale in slides_dir.glob("slide-*.png"):
        stale.unlink()
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(slides_dir / "slide")],
        check=True, capture_output=True, timeout=600,
    )
    # pdftoppm zero-pads (slide-01.png); normalise to slide-1.png
    out = []
    for p in sorted(slides_dir.glob("slide-*.png")):
        n = int(re.search(r"slide-(\d+)\.png$", p.name).group(1))
        target = slides_dir / f"slide-{n}.png"
        if p != target:
            p.rename(target)
        out.append(target)
    return sorted(out, key=lambda p: int(re.search(r"(\d+)", p.name).group(1)))


# --------------------------------------------------------------------------
# PDF structure  (Pass 1)
# --------------------------------------------------------------------------


def group_chars(chars: list[dict], page_height: float) -> list[dict]:
    """Cluster characters into styled text blocks, preserving reading order.

    Chars arrive in content-stream order. We break a line when the baseline
    moves, and break a block when style changes or the vertical gap exceeds
    ~1.6x the line height. Lines inside a block are kept separate and marked
    with a leading bullet so wrapped text stays visible as wrapped text.
    """
    lines: list[dict] = []
    for ch in chars:
        if not ch.get("text", "").strip() and ch.get("text") != " ":
            continue
        size = round(float(ch.get("size", 0)), 1)
        style = (
            clean_font(ch.get("fontname", "?")),
            size,
            to_hex(ch.get("non_stroking_color")),
        )
        top = round(float(ch["top"]), 1)
        # A horizontal jump far wider than a word space means a new column,
        # not a continuation. Without this guard two columns that happen to
        # share a baseline are merged into one nonsense line.
        col_break = bool(lines) and float(ch["x0"]) - lines[-1]["x1"] > (size or 10) * 2.0
        if (
            lines
            and lines[-1]["style"] == style
            and abs(lines[-1]["top"] - top) <= 1.5
            and not col_break
        ):
            cur = lines[-1]
            cur["text"] += ch["text"]
            cur["x1"] = max(cur["x1"], float(ch["x1"]))
            cur["bottom"] = max(cur["bottom"], float(ch["bottom"]))
        else:
            lines.append({
                "style": style, "top": top, "text": ch["text"],
                "x0": float(ch["x0"]), "x1": float(ch["x1"]),
                "bottom": float(ch["bottom"]),
            })

    blocks: list[dict] = []
    for ln in lines:
        ln["text"] = ln["text"].rstrip()
        if not ln["text"].strip():
            continue
        size = ln["style"][1] or 10.0
        if blocks:
            prev = blocks[-1]
            gap = ln["top"] - prev["lines"][-1]["top"]
            overlap = min(prev["x1"], ln["x1"]) - max(prev["x0"], ln["x0"])
            if (
                prev["style"] == ln["style"]
                and 0 <= gap <= size * 1.9
                and overlap > 0
            ):
                prev["lines"].append(ln)
                prev["x0"] = min(prev["x0"], ln["x0"])
                prev["x1"] = max(prev["x1"], ln["x1"])
                prev["bottom"] = max(prev["bottom"], ln["bottom"])
                continue
        blocks.append({
            "style": ln["style"], "lines": [ln], "top": ln["top"],
            "x0": ln["x0"], "x1": ln["x1"], "bottom": ln["bottom"],
        })
    return blocks


def pdf_structure(pdf: Path, out: Path, ocr_mode: str, slides: list[Path]) -> dict:
    import pdfplumber
    from pdfminer.layout import (
        LTChar, LTCurve, LTFigure, LTImage, LTLine, LTRect,
    )

    summary: dict = {"pages": [], "size": None}
    lines_out: list[str] = []

    with pdfplumber.open(str(pdf)) as doc:
        n = len(doc.pages)
        w, h = doc.pages[0].width, doc.pages[0].height
        summary["size"] = (w, h)
        lines_out += [
            f"SOURCE: {pdf}",
            f"PAGES: {n}   SIZE: {w:.0f} x {h:.0f} pt",
            "",
            "Legend: objects are listed in TRUE content-stream order (paint order).",
            "RECT = filled/stroked rectangle - LINE/CURVE = vector rule or path",
            "IMAGE = embedded raster - TEXT = styled text block (font - pt - colour)",
            "Each line's [zNN] is a genuine cross-type paint index: a later index",
            "paints over an earlier one. Text blocks are interleaved at the point",
            "their first glyph is painted.",
            "",
        ]

        for idx, page in enumerate(doc.pages, start=1):
            entries: list[tuple[str, str]] = []
            page_blocks: list[dict] = []
            pending_chars: list[dict] = []
            ph = page.height

            def flush_text():
                """Emit buffered glyphs as styled blocks at their paint position."""
                if not pending_chars:
                    return
                for blk in group_chars(pending_chars, ph):
                    font, size, color = blk["style"]
                    body = "\n".join(
                        f"      - {ln['text']}" for ln in blk["lines"]
                    )
                    head = (
                        f"{fmt_box(blk['x0'], blk['top'], blk['x1'] - blk['x0'], blk['bottom'] - blk['top']):<46}"
                        f"{font:<28} {size:>5}pt {color}"
                    )
                    entries.append(("TEXT", head + "\n" + body))
                    page_blocks.append({
                        "text": " ".join(ln["text"] for ln in blk["lines"]).strip(),
                        "lines": [ln["text"] for ln in blk["lines"]],
                        "x0": blk["x0"], "x1": blk["x1"], "top": blk["top"],
                        "size": size, "font": font, "color": color,
                    })
                pending_chars.clear()

            def walk(container):
                for obj in container:
                    if isinstance(obj, LTChar):
                        pending_chars.append({
                            "text": obj.get_text(),
                            "fontname": obj.fontname,
                            "size": obj.size,
                            "non_stroking_color": getattr(obj, "graphicstate", None)
                            and obj.graphicstate.ncolor,
                            "x0": obj.x0, "x1": obj.x1,
                            "top": ph - obj.y1, "bottom": ph - obj.y0,
                        })
                        continue
                    flush_text()
                    bx = fmt_box(obj.x0, ph - obj.y1, obj.width, obj.height)
                    if isinstance(obj, LTImage):
                        px = ""
                        if getattr(obj, "srcsize", None):
                            px = f"  {obj.srcsize[0]}x{obj.srcsize[1]}px"
                        entries.append(("IMAGE", f"{bx:<46}{px}  {obj.name}"))
                    elif isinstance(obj, LTRect):
                        entries.append((
                            "RECT",
                            f"{bx:<46}fill={to_hex(obj.non_stroking_color)} "
                            f"stroke={to_hex(obj.stroking_color) if obj.stroke else 'none'}",
                        ))
                    elif isinstance(obj, LTLine):
                        entries.append((
                            "LINE",
                            f"{bx:<46}stroke={to_hex(obj.stroking_color)} "
                            f"w={obj.linewidth}",
                        ))
                    elif isinstance(obj, LTCurve):
                        entries.append((
                            "CURVE",
                            f"{bx:<46}fill={to_hex(obj.non_stroking_color)} "
                            f"stroke={to_hex(obj.stroking_color)}",
                        ))
                    elif isinstance(obj, LTFigure):
                        walk(obj)
                flush_text()

            walk(page.layout)

            n_text = sum(1 for k, _ in entries if k == "TEXT")
            n_shape = len(entries) - n_text
            n_img = sum(1 for k, _ in entries if k == "IMAGE")

            # OCR fallback: a page that paints images but no text is a scan.
            ocr_text = ""
            want_ocr = ocr_mode == "always" or (
                ocr_mode == "auto" and n_text == 0 and n_img > 0
            )
            if want_ocr and have("tesseract") and idx <= len(slides):
                try:
                    r = subprocess.run(
                        ["tesseract", str(slides[idx - 1]), "stdout"],
                        capture_output=True, text=True, timeout=120,
                    )
                    ocr_text = r.stdout.strip()
                except Exception:
                    ocr_text = ""

            lines_out.append("=" * 100)
            lines_out.append(
                f"PAGE {idx}    shapes={n_shape}  textblocks={n_text}"
                + ("  [OCR]" if ocr_text else "")
            )
            lines_out.append("=" * 100)
            for z, (kind, body) in enumerate(entries):
                lines_out.append(f"[z{z:02d}] {kind:<6} {body}")
            if ocr_text:
                lines_out.append("  --- OCR (rendered page; no embedded text) ---")
                for ln in ocr_text.splitlines():
                    if ln.strip():
                        lines_out.append(f"      - {ln.strip()}")
            lines_out.append("")

            summary["pages"].append({
                "n": idx,
                "blocks": page_blocks,
                "n_images": n_img,
                "n_shapes": n_shape,
                "ocr": ocr_text,
                "height": ph,
                "width": page.width,
            })

    out.write_text("\n".join(lines_out), encoding="utf-8")
    tag_chrome(summary)
    return summary


# --------------------------------------------------------------------------
# PPTX structure  (Pass 1, richer -- shape names, notes, placeholders)
# --------------------------------------------------------------------------


def shape_paint(shp) -> str:
    """Fill and line colour of a .pptx shape, as hex or a theme-slot name.

    Without this, a dump carries only *text* colours, and a claim like "the
    theme's accent red is never used" can be made while a rule painted in
    exactly that colour sits on the cover. Theme-linked colours are reported
    as `theme:<slot>` so inherited paint is distinguishable from hard-coded.
    """
    def colour(fmt) -> str | None:
        try:
            c = fmt.fore_color if hasattr(fmt, "fore_color") else fmt.color
        except (AttributeError, TypeError, ValueError):
            return None
        try:
            return f"#{c.rgb}"
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            return f"theme:{str(c.theme_color).split(' (')[0]}"
        except (AttributeError, TypeError, ValueError):
            return None

    bits = []
    try:
        f = shp.fill
        if f.type is not None and "BACKGROUND" not in str(f.type):
            bits.append(f"fill={colour(f) or str(f.type).split(' (')[0].lower()}")
        elif f.type is not None:
            bits.append("fill=none")
    except (AttributeError, TypeError, ValueError, NotImplementedError):
        pass
    try:
        ln = shp.line
        c = colour(ln)
        if c:
            w = ""
            try:
                if ln.width:
                    w = f" w={ln.width.pt:.2f}pt"
            except (AttributeError, TypeError, ValueError):
                pass
            bits.append(f"line={c}{w}")
    except (AttributeError, TypeError, ValueError, NotImplementedError):
        pass
    return " ".join(bits)


def pptx_structure(src: Path, out: Path) -> dict:
    from pptx import Presentation
    from pptx.util import Emu

    prs = Presentation(str(src))
    W = prs.slide_width / EMU_PER_PT
    H = prs.slide_height / EMU_PER_PT
    lines = [
        f"SOURCE: {src}",
        f"SLIDES: {len(prs.slides)}   SIZE: {W:.0f} x {H:.0f} pt",
        "",
        "Legend: shapes are listed in slide-tree order (true paint order).",
        "NAME is the shape's stored name -- the highest-value archaeology in a",
        "deck, and unavailable from any exported PDF. PH = placeholder type.",
        "",
    ]
    summary: dict = {"pages": [], "size": (W, H), "notes": {}}

    def add_block(page_entry, shp, paras):
        """Record a text block with its geometry, for reading-order sorting.

        The shape tree is paint order, not visual order — on a slide whose
        cards were re-arranged after authoring, tree order and what a reader
        sees diverge. Geometry is the only reliable source of reading order.
        """
        try:
            x0, top = Emu(shp.left).pt, Emu(shp.top).pt
            x1 = x0 + Emu(shp.width).pt
        except (TypeError, ValueError):
            x0, x1, top = 0.0, 0.0, 1e6
        page_entry["blocks"].append(
            {"x0": x0, "x1": x1, "top": top, "paras": paras}
        )

    def walk(shapes, page_entry, depth=0):
        for shp in shapes:
            pad = "  " * depth
            try:
                box = fmt_box(
                    Emu(shp.left).pt, Emu(shp.top).pt,
                    Emu(shp.width).pt, Emu(shp.height).pt,
                )
            except (TypeError, ValueError):
                box = "box(unpositioned)"
            kind = str(shp.shape_type).split(" (")[0]
            ph = ""
            if shp.is_placeholder:
                ph = f" PH={shp.placeholder_format.type}"
            paint = f" {shape_paint(shp)}"
            lines.append(f"{pad}[{kind}] {box:<46} name={shp.name!r}{ph}{paint}")

            if shp.has_table:
                tbl = shp.table
                lines.append(f"{pad}  TABLE {len(tbl.rows)}x{len(tbl.columns)}")
                rows = []
                for i, r in enumerate(tbl.rows):
                    cells = [c.text.replace("\n", " / ").strip() for c in r.cells]
                    row = " | ".join(cells)
                    lines.append(f"{pad}    | " + row)
                    # Carry rows into the outline too. A slide whose whole
                    # content is a table would otherwise reach Pass 2 empty.
                    if row.strip(" |"):
                        rows.append((0 if i == 0 else 1, row))
                if rows:
                    add_block(page_entry, shp, rows)
                page_entry["visuals"].append("table")
            if shp.has_chart:
                ch = shp.chart
                lines.append(f"{pad}  CHART type={ch.chart_type}")
                try:
                    cats = [str(c) for c in ch.plots[0].categories]
                    lines.append(f"{pad}    categories: {cats}")
                    for s in ch.plots[0].series:
                        lines.append(f"{pad}    series {s.name!r}: {list(s.values)}")
                except Exception as e:
                    lines.append(f"{pad}    (series unreadable: {e})")
                page_entry["visuals"].append("chart")
            if shp.shape_type is not None and "PICTURE" in str(shp.shape_type):
                page_entry["visuals"].append("image")
            if shp.has_text_frame:
                paras = []
                for para in shp.text_frame.paragraphs:
                    txt = "".join(r.text for r in para.runs).strip()
                    if not txt:
                        continue
                    r0 = para.runs[0]
                    sz = r0.font.size.pt if r0.font.size else None
                    col = "?"
                    try:
                        if r0.font.color and r0.font.color.rgb:
                            col = f"#{r0.font.color.rgb}"
                    except Exception:
                        pass
                    bold = " bold" if r0.font.bold else ""
                    lines.append(
                        f"{pad}    L{para.level} {sz}pt{bold} {col}  {txt}"
                    )
                    paras.append((para.level, txt))
                if paras:
                    add_block(page_entry, shp, paras)
            if shp.shape_type is not None and "GROUP" in str(shp.shape_type):
                walk(shp.shapes, page_entry, depth + 1)

    for i, slide in enumerate(prs.slides, start=1):
        entry = {"n": i, "texts": [], "blocks": [], "visuals": [],
                 "layout": slide.slide_layout.name}
        lines.append("=" * 100)
        lines.append(f"SLIDE {i}    layout={slide.slide_layout.name!r}")
        lines.append("=" * 100)
        walk(slide.shapes, entry)
        # Shapes inherited from the layout are painted on the slide but are
        # NOT in slide.shapes. Cover photography and template rules live here,
        # so a dump that skips them can report a colour as "never used" while
        # it sits on the title slide.
        inherited = []
        for lay in slide.slide_layout.shapes:
            paint = shape_paint(lay)
            pic = "PICTURE" in str(lay.shape_type)
            if paint or pic:
                try:
                    box = fmt_box(Emu(lay.left).pt, Emu(lay.top).pt,
                                  Emu(lay.width).pt, Emu(lay.height).pt)
                except (TypeError, ValueError):
                    box = "box(unpositioned)"
                kind = str(lay.shape_type).split(" (")[0]
                inherited.append(
                    f"    [{kind}] {box:<46} name={lay.name!r} {paint}".rstrip()
                )
        if inherited:
            lines.append(f"  --- inherited from layout {slide.slide_layout.name!r} ---")
            lines += inherited
            entry["inherited"] = inherited

        if slide.has_notes_slide:
            note = slide.notes_slide.notes_text_frame.text.strip()
            if note:
                lines.append("  --- speaker notes ---")
                for ln in note.splitlines():
                    lines.append(f"      {ln}")
                summary["notes"][i] = note
        lines.append("")
        summary["pages"].append(entry)

    out.write_text("\n".join(lines), encoding="utf-8")
    return summary


# --------------------------------------------------------------------------
# raw metadata  (Pass 1, third read: what nobody meant to leave in)
# --------------------------------------------------------------------------


def raw_meta(src: Path, pdf: Path, out: Path) -> None:
    lines = [f"SOURCE: {src}", ""]

    if src.suffix.lower() == ".pptx":
        lines.append("=== OOXML document properties ===")
        with zipfile.ZipFile(src) as z:
            for name in ("docProps/core.xml", "docProps/app.xml"):
                if name in z.namelist():
                    lines.append(f"--- {name} ---")
                    body = z.read(name).decode("utf-8", "replace")
                    for tag, val in re.findall(r"<([^/>\s]+)[^>]*>([^<]+)</\1>", body):
                        lines.append(f"  {tag:<34}{val}")
            lines.append("")
            lines.append("=== theme colour scheme ===")
            for name in sorted(z.namelist()):
                if name.startswith("ppt/theme/"):
                    body = z.read(name).decode("utf-8", "replace")
                    lines.append(f"--- {name} ---")
                    scheme = re.search(r"<a:clrScheme.*?</a:clrScheme>", body, re.S)
                    if scheme:
                        for slot, srgb, sysclr in re.findall(
                            r'<a:(\w+)>\s*<a:(?:srgbClr val="([0-9A-Fa-f]{6})"'
                            r'|sysClr[^>]*lastClr="([0-9A-Fa-f]{6})")',
                            scheme.group(0),
                        ):
                            lines.append(
                                f"  {slot:<16}#{(srgb or sysclr).upper()}"
                            )
                    for fnt in re.findall(r'typeface="([^"]+)"', body)[:12]:
                        lines.append(f"  typeface       {fnt}")
            lines.append("")
            lines.append("=== media inventory ===")
            for info in sorted(z.infolist(), key=lambda i: i.filename):
                if info.filename.startswith("ppt/media/"):
                    lines.append(
                        f"  {info.filename:<44}{info.file_size:>10,} bytes"
                    )

    lines.append("")
    lines.append("=== PDF metadata ===")
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf)) as doc:
            for k, v in (doc.metadata or {}).items():
                lines.append(f"  {k:<24}{v}")
            lines.append("")
            lines.append("=== fonts (subsets reveal how many faces are really used) ===")
            fonts: dict[str, int] = {}
            for pg in doc.pages:
                for ch in pg.chars:
                    fonts[ch["fontname"]] = fonts.get(ch["fontname"], 0) + 1
            for f, c in sorted(fonts.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {f:<44}{c:>8} glyphs")
            lines.append("")
            lines.append("=== embedded images (object id reveals asset reuse) ===")
            seen: dict[str, list[int]] = {}
            for i, pg in enumerate(doc.pages, start=1):
                for im in pg.images:
                    key = f"{im.get('name','?')} {im.get('srcsize')}"
                    seen.setdefault(key, []).append(i)
            for key, pages in seen.items():
                lines.append(f"  {key:<44}pages {pages}")
    except Exception as e:
        lines.append(f"  (unreadable: {e})")

    out.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# layout awareness -- chrome (headers, footers, page numbers) and reading order
# --------------------------------------------------------------------------


def tag_chrome(summary: dict) -> None:
    """Mark repeating furniture so it stops drowning the real content.

    A block is chrome when the same normalised string appears at the same
    place on at least half the pages. Digits are normalised to '#' first, so
    a page number that changes every page still collapses to one key.
    """
    pages = summary["pages"]
    if len(pages) < 3:
        return
    H = pages[0].get("height") or 540

    def key(b: dict) -> tuple:
        norm = re.sub(r"\d+", "#", b["text"]).strip().lower()
        return (round(b["top"] / 6), round(b["x0"] / 12), norm)

    counts: dict[tuple, int] = {}
    for pg in pages:
        for k in {key(b) for b in pg["blocks"]}:
            counts[k] = counts.get(k, 0) + 1

    threshold = max(2, int(len(pages) * 0.5))
    for pg in pages:
        for b in pg["blocks"]:
            b["chrome"] = None
            if counts.get(key(b), 0) < threshold:
                continue
            if re.fullmatch(r"[\W\d]*\d+[\W\d]*", b["text"]):
                b["chrome"] = "page-number"
            elif b["top"] < H * 0.12:
                b["chrome"] = "header"
            elif b["top"] > H * 0.85:
                b["chrome"] = "footer"
            else:
                b["chrome"] = "recurring"


def reading_order(blocks: list[dict], page_width: float) -> list[dict]:
    """Order blocks the way a person reads them: columns, then top-to-bottom.

    Columns are found by sweeping for a vertical gutter -- an x range that no
    block crosses. With no gutter this degrades to plain top-to-bottom,
    left-to-right, which is correct for a single-column slide.
    """
    flat = lambda bs: sorted(bs, key=lambda b: (b["top"], b["x0"]))  # noqa: E731
    if len(blocks) < 4:
        return flat(blocks)

    # A full-width headline or kicker crosses every would-be gutter, so it has
    # to sit out the gutter sweep -- otherwise a three-column slide with a
    # headline over it looks like one column and reads back row-major.
    wide = [b for b in blocks if (b["x1"] - b["x0"]) > page_width * 0.55]
    narrow = [b for b in blocks if b not in wide]
    if len(narrow) < 4:
        return flat(blocks)

    spans = sorted((b["x0"], b["x1"]) for b in narrow)
    gutters: list[float] = []
    reach = spans[0][1]
    for x0, x1 in spans[1:]:
        if x0 - reach > page_width * 0.04:
            gutters.append((reach + x0) / 2)
        reach = max(reach, x1)
    if not gutters:
        return flat(blocks)

    bounds = [0.0] + gutters + [page_width]
    columns: list[list[dict]] = [[] for _ in range(len(bounds) - 1)]
    for b in narrow:
        mid = (b["x0"] + b["x1"]) / 2
        for i in range(len(bounds) - 1):
            if bounds[i] <= mid < bounds[i + 1]:
                columns[i].append(b)
                break
    columns = [c for c in columns if c]
    # One column holding nearly everything means the gutter was spurious.
    if len(columns) < 2 or max(len(c) for c in columns) > len(narrow) * 0.9:
        return flat(blocks)

    col_top = min(b["top"] for b in narrow)
    out = flat([b for b in wide if b["top"] < col_top])
    for col in columns:
        out.extend(flat(col))
    out.extend(flat([b for b in wide if b["top"] >= col_top]))
    return out


def infer_levels(blocks: list[dict]) -> list[tuple[int, str]]:
    """Turn styled blocks into a title/bullet/sub-bullet hierarchy.

    Point size carries the hierarchy in almost every deck: the largest text is
    the title, and each smaller distinct size is one level deeper. Indent
    breaks ties within a size.
    """
    if not blocks:
        return []
    sizes = sorted({round(b["size"], 1) for b in blocks}, reverse=True)
    rank = {s: i for i, s in enumerate(sizes)}
    left = min(b["x0"] for b in blocks)
    out = []
    for b in blocks:
        lvl = rank[round(b["size"], 1)]
        if b["x0"] - left > 24:
            lvl += 1
        for line in b["lines"]:
            if line.strip():
                out.append((lvl, line.strip()))
    return out


# --------------------------------------------------------------------------
# Pass 2 -- semantic chunking, function labels, chunk map
# --------------------------------------------------------------------------

FUNCTION_RULES = [
    (r"\bagenda\b|\btable of contents\b|\bcontents\b|\boverview of\b", "Agenda"),
    (r"\bexecutive summary\b|\bkey takeaways?\b|\btl;?dr\b", "Executive Summary"),
    (r"\bthank you\b|\bq ?& ?a\b|\bquestions\b|\bcontact\b|\bget in touch\b", "Closing / Contact"),
    (r"\bappendix\b|\bbackup\b|\bdisclaimer\b|\bdisclosure\b", "Appendix / Legal"),
    (r"\brevenue\b|\bebitda\b|\bforecast\b|\bp ?& ?l\b|\bvaluation\b|\bfunding\b|\bcap table\b|\barr\b|\bmrr\b", "Financial"),
    (r"\broadmap\b|\btimeline\b|\bmilestones?\b|\bphase \d|\bq[1-4] 20\d\d", "Roadmap / Timeline"),
    (r"\bteam\b|\bleadership\b|\bfounders?\b|\badvisors?\b", "Team"),
    (r"\bmarket\b|\btam\b|\bsam\b|\bsom\b|\bcompetit|\blandscape\b", "Market / Competition"),
    (r"\bproblem\b|\bchallenge\b|\bwhy .*not enough\b|\bgap\b|\bstuck\b", "Problem"),
    (r"\bsolution\b|\bhow it works\b|\barchitecture\b|\bplatform\b|\bproduct\b", "Solution / Product"),
    (r"\bpartners?\b|\becosystem\b|\bcustomers?\b|\bcase stud|\btraction\b", "Traction / Partners"),
    (r"\bgovernance\b|\bcompliance\b|\bregulat|\blicen[cs]e\b", "Governance / Regulatory"),
]


def label_function(page_no: int, total: int, texts: list[str], visuals: list[str]) -> str:
    if page_no == 1 and len(texts) <= 8:
        return "Title Slide"
    # The title names the slide's job; body prose is full of words that
    # accidentally match ("optional revenue booster" on a market slide).
    # So match the title first and only fall back to the body.
    title = " ".join(texts[:2]).lower()
    joined = " ".join(texts).lower()
    for scope in (title, joined):
        for pattern, name in FUNCTION_RULES:
            if re.search(pattern, scope):
                return name
    if "chart" in visuals:
        return "Data / Chart"
    if "table" in visuals:
        return "Table"
    if not texts and visuals:
        return "Full-bleed Visual"
    if page_no == total:
        return "Closing"
    return "Content"


def build_outline(src: Path, summary: dict, out: Path, kind: str,
                  chunk_slides: int) -> None:
    total = len(summary["pages"])
    lines = [
        f"# outline: `{src.name}`",
        "",
        f"**{total} slides - {summary['size'][0]:.0f}x{summary['size'][1]:.0f}pt "
        f"- source type `{kind}`**",
        "",
        "Pass 2 output: hierarchy, function label and visual tags per slide, plus",
        "a chunk map for reading a large deck without blowing the context window.",
        "Function labels are heuristic - confirm them against the render in Pass 3.",
        "",
        "---",
        "",
    ]

    for pg in summary["pages"]:
        n = pg["n"]
        chrome_notes: list[str] = []
        if kind == "pptx":
            ordered = reading_order(pg["blocks"], summary["size"][0])
            levels = [pr for b in ordered for pr in b["paras"]]
            texts = [t for _, t in levels]
            visuals = pg["visuals"]
        else:
            # Bullet glyphs are painted as their own text blocks in most
            # decks. Left in, they scatter through the columns and break
            # gutter detection; the hierarchy renders its own markers anyway.
            body = [
                b for b in pg["blocks"]
                if not b.get("chrome")
                and not re.fullmatch(r"[\s•·▪◦‣\-–—*]+", b["text"])
            ]
            chrome_notes = [
                f"{b['chrome']}: {b['text']}"
                for b in pg["blocks"] if b.get("chrome")
            ]
            ordered = reading_order(body, pg.get("width") or 960)
            levels = infer_levels(ordered)
            texts = [t for _, t in levels]
            if pg.get("ocr"):
                extra = [l.strip() for l in pg["ocr"].splitlines() if l.strip()]
                levels += [(1, t) for t in extra]
                texts += extra
            visuals = ["image"] * pg["n_images"]

        fn = label_function(n, total, texts, visuals)
        tags = sorted(set(visuals))
        lines.append(f"## slide {n} - {fn}")
        meta = []
        if tags:
            meta.append(f"visual elements: {', '.join(tags)}")
        if chrome_notes:
            meta.append("chrome stripped - " + "; ".join(sorted(set(chrome_notes))))
        if pg.get("ocr"):
            meta.append("text recovered by OCR - no embedded text layer")
        for m in meta:
            lines.append(f"*{m}*")
        lines.append("")
        if levels:
            base = levels[0][0]
            lines.append(f"**{levels[0][1]}**")
            for lvl, t in levels[1:]:
                lines.append("  " * max(0, lvl - base) + f"- {t}")
        else:
            lines.append("*(no text; visual-only slide - read the render)*")
        if kind == "pptx" and summary.get("notes", {}).get(n):
            lines.append("")
            lines.append(f"> speaker notes: {summary['notes'][n]}")
        lines.append("")

    lines += ["---", "", "## chunk map", "",
              f"Read in chunks of {chunk_slides} slides; each chunk cites the",
              "renders it covers so Pass 3 can look at exactly those pages.", ""]
    for start in range(1, total + 1, chunk_slides):
        end = min(start + chunk_slides - 1, total)
        imgs = " ".join(f"slides/slide-{i}.png" for i in range(start, end + 1))
        lines.append(f"- **chunk {start}-{end}** - {imgs}")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract a deck for multi-pass reading.")
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--outdir", type=Path, default=None)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--chunk", type=int, default=5,
                    help="slides per chunk in the Pass 2 chunk map")
    ap.add_argument("--ocr", choices=["auto", "always", "never"], default="auto",
                    help="auto = OCR only pages with images but no text layer")
    args = ap.parse_args()

    src = args.source.expanduser().resolve()
    if not src.exists():
        die(f"no such file: {src}")
    kind = src.suffix.lower().lstrip(".")
    if kind not in ("pdf", "pptx"):
        die(f"unsupported source type {src.suffix!r} (need .pdf or .pptx)")

    outdir = (args.outdir or Path("Decks") / src.stem).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        pdf = src if kind == "pdf" else soffice_to_pdf(src, tmpdir)

        print(f"  rendering at {args.dpi}dpi ...", file=sys.stderr)
        slides = render(pdf, outdir / "slides", args.dpi)

        print("  dumping structure ...", file=sys.stderr)
        struct = outdir / "shape_structure.txt"
        if kind == "pptx":
            summary = pptx_structure(src, struct)
        else:
            summary = pdf_structure(pdf, struct, args.ocr, slides)

        print("  reading raw metadata ...", file=sys.stderr)
        raw_meta(src, pdf, outdir / "rawmeta.txt")

        print("  building outline ...", file=sys.stderr)
        build_outline(src, summary, outdir / "outline.md", kind, args.chunk)

    print(f"\nwrote {outdir}", file=sys.stderr)
    for f in ("slides", "shape_structure.txt", "rawmeta.txt", "outline.md"):
        p = outdir / f
        note = f"{len(list(p.glob('*.png')))} pages" if p.is_dir() else \
            f"{p.stat().st_size:,} bytes"
        print(f"  {f:<22}{note}", file=sys.stderr)


if __name__ == "__main__":
    main()
