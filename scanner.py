#!/usr/bin/env python3
"""Scan a PDF for text an AI reviewer would read but a human skim would not.

Checks four independent hiding techniques, each one that has been used (or
discussed) in the wild to smuggle instructions past a document-review
pipeline:

  1. low-contrast text   -- glyph color close to the page's own fill color
                             (the "white-on-white" technique)
  2. microscopic text    -- font size below a legibility floor
  3. off-page text       -- glyph bbox outside the visible page rect
  4. zero-opacity text  -- glyph painted with alpha 0 (nothing rendered),
                             the mode real OCR text-overlay layers use,
                             which also hides arbitrary text from a reader

Any one hit means the PDF carries content a human proofreader is very
unlikely to see but a text-extraction pipeline (the kind that feeds an LLM)
will read in full. That asymmetry is the attack surface; this script does
not guess intent, it reports the asymmetry so a human or gate can decide.
"""
import argparse
import json
import sys

import fitz  # pymupdf

MIN_LEGIBLE_FONT_SIZE = 4.0
LOW_CONTRAST_THRESHOLD = 0.08  # max color distance from page background to flag
ZERO_WIDTH_CHARS = {
    "​": "ZERO WIDTH SPACE",
    "‌": "ZERO WIDTH NON-JOINER",
    "‍": "ZERO WIDTH JOINER",
    "﻿": "ZERO WIDTH NO-BREAK SPACE / BOM",
    "⁠": "WORD JOINER",
}


def color_distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def page_background_color(page):
    # Assume the common case (white page) unless a full-page fill rect says
    # otherwise. Good enough for a demo-scale scanner; a production version
    # would sample rendered pixels instead.
    return (1.0, 1.0, 1.0)


def as_rgb(color):
    """pymupdf's texttrace 'color' is already a float RGB/gray tuple (or an
    int-packed color on some colorspaces/versions) -- normalize both."""
    if color is None:
        return (0.0, 0.0, 0.0)
    if isinstance(color, (tuple, list)):
        if len(color) == 3:
            return tuple(color)
        if len(color) == 1:  # grayscale
            return (color[0], color[0], color[0])
        return (0.0, 0.0, 0.0)
    r = ((color >> 16) & 0xFF) / 255.0
    g = ((color >> 8) & 0xFF) / 255.0
    b = (color & 0xFF) / 255.0
    return (r, g, b)


def scan_pdf(path):
    doc = fitz.open(path)
    findings = []

    for page_index, page in enumerate(doc):
        bg = page_background_color(page)
        page_rect = page.rect

        # Render-mode + per-span color/size/position via the texttrace API,
        # which exposes render_mode (fill/stroke/invisible) per character
        # span -- the get_text("dict") API does not.
        try:
            trace = page.get_texttrace()
        except AttributeError:
            trace = []

        for span in trace:
            text = "".join(chr(c[0]) for c in span.get("chars", []))
            if not text.strip():
                continue
            opacity = span.get("opacity", 1.0)
            color = as_rgb(span.get("color"))
            size = span.get("size", 0.0)
            bbox = fitz.Rect(span.get("bbox", (0, 0, 0, 0)))

            if opacity is not None and opacity <= 0.01:
                findings.append({
                    "page": page_index + 1,
                    "reason": "zero-opacity-text",
                    "detail": f"opacity {opacity} (nothing painted)",
                    "preview": text[:80],
                })
                continue  # already flagged, skip redundant color/size checks

            if color_distance(color, bg) < LOW_CONTRAST_THRESHOLD:
                findings.append({
                    "page": page_index + 1,
                    "reason": "low-contrast-text",
                    "detail": f"glyph color {tuple(round(c,3) for c in color)} vs page background {bg}",
                    "preview": text[:80],
                })

            if 0 < size < MIN_LEGIBLE_FONT_SIZE:
                findings.append({
                    "page": page_index + 1,
                    "reason": "microscopic-text",
                    "detail": f"font size {size:.2f}pt (below {MIN_LEGIBLE_FONT_SIZE}pt legibility floor)",
                    "preview": text[:80],
                })

            if not page_rect.contains(bbox) and bbox.get_area() > 0:
                findings.append({
                    "page": page_index + 1,
                    "reason": "off-page-text",
                    "detail": f"bbox {tuple(round(v,1) for v in bbox)} outside page rect {tuple(round(v,1) for v in page_rect)}",
                    "preview": text[:80],
                })

        # Zero-width character check runs over plain extracted text,
        # independent of the texttrace pass above.
        plain_text = page.get_text("text")
        for ch, name in ZERO_WIDTH_CHARS.items():
            count = plain_text.count(ch)
            if count:
                idx = plain_text.find(ch)
                context = plain_text[max(0, idx - 20):idx + 20].replace("\n", " ")
                findings.append({
                    "page": page_index + 1,
                    "reason": "zero-width-chars",
                    "detail": f"{count}x {name} (U+{ord(ch):04X})",
                    "preview": context,
                })

    doc.close()
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="path to the PDF to scan")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a text report")
    args = parser.parse_args()

    findings = scan_pdf(args.pdf)

    if args.json:
        print(json.dumps({"path": args.pdf, "flagged": bool(findings), "findings": findings}, indent=2))
    else:
        if not findings:
            print(f"PASS  {args.pdf}  -- no hidden text detected")
        else:
            print(f"FLAGGED  {args.pdf}  -- {len(findings)} finding(s)")
            for f in findings:
                print(f"  page {f['page']}: [{f['reason']}] {f['detail']}")
                print(f"    preview: {f['preview']!r}")

    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
