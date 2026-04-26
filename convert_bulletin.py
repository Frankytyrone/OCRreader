#!/usr/bin/env python3
"""
convert_bulletin.py
Converts a scanned PDF bulletin to a styled, scrollable HTML file.

Usage:
    python convert_bulletin.py <pdf_file> <YYYY-MM-DD>

Example:
    python convert_bulletin.py merged.pdf 2026-04-26
"""

import sys
import os
import tempfile
import easyocr
from pdf2image import convert_from_path

CSS = """
<style>
  .scrollable-viewer {
    max-width: 800px;
    margin: 0 auto;
    background: #ffffff;
    border: 1px solid #ccc;
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
    font-family: Georgia, serif;
    font-size: 16px;
    line-height: 1.7;
    max-height: 90vh;
    overflow-y: auto;
    padding: 32px 40px;
  }
</style>
"""

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Parish Bulletin {date}</title>
  {css}
</head>
<body>
<div class="scrollable-viewer">
{content}
</div>
</body>
</html>
"""


def pdf_to_images(pdf_path):
    """Convert each page of the PDF to a PIL image."""
    return convert_from_path(pdf_path, dpi=200)


def ocr_images(images):
    """Run EasyOCR on a list of PIL images and return extracted text per page."""
    reader = easyocr.Reader(["en", "ga"], gpu=False)
    pages_text = []
    for i, image in enumerate(images, start=1):
        print(f"  OCR on page {i}/{len(images)} …", flush=True)
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
        try:
            os.close(tmp_fd)
            image.save(tmp_path, format="PNG")
            results = reader.readtext(tmp_path, detail=0, paragraph=True)
        finally:
            os.remove(tmp_path)
        pages_text.append(results)
    return pages_text


def build_html_content(pages_text):
    """Turn the list-of-lists of text into HTML paragraphs grouped by page."""
    parts = []
    for i, lines in enumerate(pages_text, start=1):
        parts.append(f"<h2>Page {i}</h2>")
        for line in lines:
            escaped = (
                line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
            )
            parts.append(f"<p>{escaped}</p>")
    return "\n".join(parts)


def main():
    if len(sys.argv) != 3:
        print("Usage: python convert_bulletin.py <pdf_file> <YYYY-MM-DD>")
        sys.exit(1)

    pdf_file = sys.argv[1]
    date = sys.argv[2]

    if not os.path.isfile(pdf_file):
        print(f"Error: '{pdf_file}' not found.")
        sys.exit(1)

    print(f"Converting '{pdf_file}' for date {date} …")

    print("Step 1/3 — Converting PDF pages to images …")
    images = pdf_to_images(pdf_file)
    print(f"  {len(images)} page(s) found.")

    print("Step 2/3 — Running EasyOCR (this may take a few minutes) …")
    pages_text = ocr_images(images)

    print("Step 3/3 — Building HTML …")
    content = build_html_content(pages_text)

    output_filename = f"bulletin-{date}.html"
    html = HTML_TEMPLATE.format(date=date, css=CSS, content=content)

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDone! Output saved to: {output_filename}")


if __name__ == "__main__":
    main()
