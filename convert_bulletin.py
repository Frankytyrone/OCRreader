#!/usr/bin/env python3
import sys
import os
import base64
import io
import re
from openai import OpenAI
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
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_PATTERN = re.compile(r"(?<!@)\b(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
PHONE_WITH_COUNTRY_OPTIONAL_TRUNK = r"\+353\s*\(0\)\s*\d{1,2}(?:[\s-]?\d{3,4}){1,2}"
PHONE_WITH_COUNTRY = r"\+353[\s-]?\d{1,2}(?:[\s-]?\d{3,4}){1,2}"
PHONE_LOCAL = r"0\d{1,2}(?:[\s-]?\d{3,4}){1,2}"
PHONE_PATTERN = re.compile(
    rf"(?<!\w)(?:{PHONE_WITH_COUNTRY_OPTIONAL_TRUNK}|{PHONE_WITH_COUNTRY}|{PHONE_LOCAL})(?!\w)"
)


def pdf_to_images(pdf_path):
    return convert_from_path(pdf_path, dpi=150)


def ocr_images(images):
    """Run OCR across images and return (pages_text, provider_summary)."""
    github_token = os.environ.get("GITHUB_TOKEN")
    openai_api_key = os.environ.get("OPENAI_API_KEY")

    if not github_token and not openai_api_key:
        print("Error: Neither GITHUB_TOKEN nor OPENAI_API_KEY is set. Please set at least one credential.")
        sys.exit(1)

    use_github_models = bool(github_token)
    if use_github_models:
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


def linkify(text):
    placeholders = []

    def stash(replacement):
        token = f"__LINKIFY_{len(placeholders)}__"
        placeholders.append(replacement)
        return token

    def split_trailing_punctuation(value):
        trailing = ""
        while value and value[-1] in ".,;:!?":
            trailing = value[-1] + trailing
            value = value[:-1]
        while value.endswith(")") and value.count(")") > value.count("("):
            trailing = ")" + trailing
            value = value[:-1]
        return value, trailing

    def replace_email(match):
        email = match.group(0)
        return stash(f'<a href="mailto:{email}">{email}</a>')

    def replace_url(match):
        url = match.group(0)
        trimmed_url, trailing = split_trailing_punctuation(url)
        href = trimmed_url if trimmed_url.startswith(("http://", "https://")) else f"https://{trimmed_url}"
        link = (
            f'<a href="{href}" target="_blank" rel="noopener noreferrer">'
            f"{trimmed_url}</a>"
        )
        return f"{stash(link)}{trailing}"

    def to_tel_href(display):
        digits = re.sub(r"\D", "", display)
        if digits.startswith("353"):
            national = digits[3:]
            if national.startswith("0"):
                national = national[1:]
            if national:
                return f"+353{national}"
            return None
        if digits.startswith("0"):
            national = digits[1:]
            if national:
                return f"+353{national}"
        return None

    def replace_phone(match):
        phone = match.group(0)
        href = to_tel_href(phone)
        if not href:
            return phone
        return stash(f'<a href="tel:{href}">{phone}</a>')

    linked = EMAIL_PATTERN.sub(replace_email, text)
    linked = URL_PATTERN.sub(replace_url, linked)
    linked = PHONE_PATTERN.sub(replace_phone, linked)

    for i, replacement in enumerate(placeholders):
        linked = linked.replace(f"__LINKIFY_{i}__", replacement)
    return linked


def build_html_content(pages_text):
    parts = []
    for i, lines in enumerate(pages_text, start=1):
        if i > 1:
            parts.append("<hr>")
        parts.append(f"<h2>Page {i}</h2>")
        for line in lines:
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            parts.append(f"<p>{linkify(escaped)}</p>")
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

    print(f"Converting '{pdf_file}' for date {date} ...")
    print("Step 1/3 — Converting PDF pages to images ...")
    images = pdf_to_images(pdf_file)
    print(f"  {len(images)} page(s) found.")

    print("Step 2/3 — Running gpt-4o-mini Vision OCR ...")
    pages_text, provider_used = ocr_images(images)

    print("Step 3/3 — Building HTML ...")
    content = build_html_content(pages_text)

    output_filename = f"bulletin-{date}.html"
    html = HTML_TEMPLATE.format(date=date, css=CSS, content=content)

    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDone! Output saved to: {output_filename}")
    print(f"Summary: Processed {len(images)} page(s) using {provider_used}.")


if __name__ == "__main__":
    main()
