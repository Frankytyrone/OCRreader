#!/usr/bin/env python3
# Requires: pip install openai pdf2image Pillow mistralai
import sys
import os
import base64
import io
import re
from openai import OpenAI
# mistralai package layouts differ across versions; support both import paths.
try:
    from mistralai import Mistral
except ImportError:
    from mistralai.client import Mistral
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
  p {
    margin: 4px 0;
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

OCR_PROMPT = (
    "You are an OCR assistant reading a scanned Irish parish bulletin page. Extract ALL text exactly as it appears. "
    "Do NOT wrap your response in markdown code fences or backticks. "
    "The bulletin may have multiple columns, tables, and mixed English and Irish (Gaeilge) text — preserve both "
    "languages faithfully without translating. Preserve the layout and structure as closely as possible using plain text spacing."
)

MARKDOWN_FENCE_PATTERN = re.compile(r"^\s*```(?:[A-Za-z0-9_-]+)?\s*$")


def pdf_to_images(pdf_path):
    return convert_from_path(pdf_path, dpi=150)


def ocr_with_mistral(pdf_path):
    """Run Mistral OCR on a PDF and return list of page strings."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set.")

    client = Mistral(api_key=api_key)

    with open(pdf_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")

    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{pdf_data}",
        },
    )

    pages = []
    for page in ocr_response.pages:
        text = page.markdown or ""
        lines = [
            line for line in text.splitlines()
            if line.strip() and not MARKDOWN_FENCE_PATTERN.match(line)
        ]
        pages.append("\n".join(lines))
    return pages


def ocr_images(images):
    """Run OCR across images and return (pages_text, provider_summary)."""
    github_token = os.environ.get("GITHUB_TOKEN")
    openai_api_key = os.environ.get("OPENAI_API_KEY")

    if not github_token and not openai_api_key:
        print("Error: Neither GITHUB_TOKEN nor OPENAI_API_KEY is set. Please set at least one credential.")
        sys.exit(1)

    use_github_models = bool(github_token)
    if use_github_models:
        print("  Using GitHub Models (gpt-4o-mini) for image OCR...")
        client = OpenAI(
            api_key=github_token,
            base_url="https://models.inference.ai.azure.com",
        )
        provider_used = "GitHub Models"
    else:
        print("  GITHUB_TOKEN not set, using OpenAI gpt-4o-mini directly...")
        client = OpenAI(
            api_key=openai_api_key,
        )
        provider_used = "OpenAI fallback"
    fallback_used = False

    pages_text = []
    for i, image in enumerate(images, start=1):
        print(f"  OCR on page {i}/{len(images)} ...", flush=True)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        buffer.close()
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": OCR_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            },
                        ],
                    }
                ],
            )
        except Exception as e:
            if use_github_models and openai_api_key:
                print(
                    f"  GitHub Models failed on page {i} ({type(e).__name__}: {e}), "
                    "falling back to OpenAI gpt-4o-mini..."
                )
                client = OpenAI(api_key=openai_api_key)
                use_github_models = False
                provider_used = "OpenAI fallback"
                fallback_used = True
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": OCR_PROMPT},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                                },
                            ],
                        }
                    ],
                )
            else:
                raise
        text = response.choices[0].message.content or ""
        lines = [
            line for line in text.splitlines()
            if line.strip() and not MARKDOWN_FENCE_PATTERN.match(line)
        ]
        pages_text.append(lines)
    if fallback_used:
        return pages_text, "GitHub Models + OpenAI fallback"
    return pages_text, provider_used


def build_html_content(pages_text):
    parts = []
    for i, lines in enumerate(pages_text, start=1):
        if i > 1:
            parts.append("<hr>")
        parts.append(f"<h2>Page {i}</h2>")
        for line in lines:
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
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

    mistral_api_key = os.environ.get("MISTRAL_API_KEY")
    github_token = os.environ.get("GITHUB_TOKEN")
    openai_api_key = os.environ.get("OPENAI_API_KEY")

    if not mistral_api_key and not github_token and not openai_api_key:
        print("Error: None of MISTRAL_API_KEY, GITHUB_TOKEN, or OPENAI_API_KEY is set.")
        print("Please set at least one credential.")
        sys.exit(1)

    print(f"Converting '{pdf_file}' for date {date} ...")
    pages_text = None
    provider_used = None

    if mistral_api_key:
        print("Step 1/3 — Trying Mistral OCR (mistral-ocr-latest) on PDF ...")
        try:
            mistral_pages = ocr_with_mistral(pdf_file)
            pages_text = [page_text.splitlines() for page_text in mistral_pages]
            provider_used = "Mistral"
            print(f"  Mistral OCR succeeded on {len(mistral_pages)} page(s).")
        except Exception as e:
            print(f"  Mistral OCR failed ({type(e).__name__}: {e}). Falling back to image OCR...")
    else:
        print("Step 1/3 — MISTRAL_API_KEY not set, skipping Mistral OCR ...")

    if pages_text is None:
        if not github_token and not openai_api_key:
            print("Error: Mistral OCR was unavailable/failed and no image OCR credentials are set.")
            print("Set GITHUB_TOKEN and/or OPENAI_API_KEY for fallback OCR.")
            sys.exit(1)
        print("Step 1/3 — Converting PDF pages to images ...")
        images = pdf_to_images(pdf_file)
        print(f"  {len(images)} page(s) found.")

        print("Step 2/3 — Running image OCR (GitHub Models, then OpenAI fallback) ...")
        pages_text, provider_used = ocr_images(images)
    else:
        print("Step 2/3 — Skipping image OCR because Mistral OCR succeeded.")

    print("Step 3/3 — Building HTML ...")
    content = build_html_content(pages_text)

    output_filename = f"bulletin-{date}.html"
    html = HTML_TEMPLATE.format(date=date, css=CSS, content=content)

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDone! Output saved to: {output_filename}")
    print(f"Summary: Processed {len(pages_text)} page(s) using {provider_used}.")


if __name__ == "__main__":
    main()
