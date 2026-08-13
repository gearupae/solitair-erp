#!/usr/bin/env python3
"""Build user guide HTML for in-app Settings menu."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import markdown
from markdown.extensions.tables import TableExtension
from markdown.extensions.toc import TocExtension

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
MD_FILE = DOCS / "USER_GUIDE.md"
HTML_FILE = ROOT / "erp_project" / "static" / "docs" / "user_guide.html"
SCREENSHOTS_SRC = DOCS / "user-guide" / "screenshots"
SCREENSHOTS_DST = ROOT / "erp_project" / "static" / "docs" / "user-guide" / "screenshots"
STATIC_IMG_PREFIX = "/static/docs/user-guide/screenshots"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Solitair ERP — User Guide</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --paper: #ffffff;
      --text: #1a1a1a;
      --muted: #5c6670;
      --accent: #111827;
      --border: #e5e7eb;
      --code-bg: #f3f4f6;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      font-size: 16px;
      line-height: 1.65;
      color: var(--text);
      background: var(--bg);
    }
    .erp-back {
      background: #111827;
      color: #fff;
      padding: 10px 24px;
      font-size: 0.9rem;
    }
    .erp-back a { color: #93c5fd; text-decoration: none; }
    .erp-back a:hover { text-decoration: underline; }
    .page {
      max-width: 920px;
      margin: 0 auto;
      padding: 32px 24px 64px;
    }
    .cover {
      background: linear-gradient(135deg, #111827 0%, #374151 100%);
      color: #ffffff;
      padding: 48px 40px;
      border-radius: 16px;
      margin-bottom: 32px;
    }
    .cover h1 {
      margin: 0 0 8px;
      font-size: 2rem;
      color: #ffffff;
    }
    .cover p {
      margin: 0;
      color: #ffffff;
      opacity: 0.92;
    }
    .content {
      background: var(--paper);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 40px 48px;
      box-shadow: 0 1px 3px rgba(0,0,0,.06);
    }
    .content h1, .content h2, .content h3, .content h4 {
      color: var(--accent);
      line-height: 1.25;
    }
    .content h1 {
      font-size: 1.75rem;
      margin-top: 2.5rem;
      border-bottom: 2px solid var(--border);
      padding-bottom: .4rem;
    }
    .content h1:first-child { margin-top: 0; }
    .content h2 { font-size: 1.35rem; margin-top: 2rem; }
    .content h3 { font-size: 1.1rem; margin-top: 1.5rem; color: #374151; }
    .content p, .content li { color: #374151; }
    .content a { color: #2563eb; }
    .content hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
    .content img {
      max-width: 100%;
      height: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      margin: 1rem 0 1.5rem;
      box-shadow: 0 4px 12px rgba(0,0,0,.08);
    }
    .content table {
      width: 100%;
      border-collapse: collapse;
      margin: 1rem 0 1.5rem;
      font-size: 0.95rem;
    }
    .content th, .content td {
      border: 1px solid var(--border);
      padding: 10px 12px;
      text-align: left;
    }
    .content th { background: #f9fafb; font-weight: 600; }
    .content code {
      background: var(--code-bg);
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.9em;
    }
    .content pre {
      background: #111827;
      color: #f9fafb;
      padding: 16px 20px;
      border-radius: 8px;
      overflow-x: auto;
      font-size: 0.9rem;
    }
    .content pre code { background: none; padding: 0; color: inherit; }
    .content ul, .content ol { padding-left: 1.4rem; }
    .content li { margin-bottom: 0.35rem; }
  </style>
</head>
<body>
  <div class="erp-back"><a href="/">&larr; Back to Solitair ERP</a></div>
  <div class="page">
    <div class="cover">
      <h1>Solitair ERP — User Guide</h1>
      <p>Purchase · HR · Inventory · Settings &nbsp;|&nbsp; https://solitair.telldb.com</p>
    </div>
    <div class="content">
      {body}
    </div>
  </div>
</body>
</html>
"""


def _rewrite_image_paths(html: str) -> str:
    html = html.replace('src="user-guide/screenshots/', f'src="{STATIC_IMG_PREFIX}/')
    return html


def build_html() -> str:
    md_text = MD_FILE.read_text(encoding="utf-8")
    md_text = re.sub(r"^# Solitair ERP — User Guide\s*\n", "", md_text, count=1)
    # Drop screenshot regen section from published guide
    md_text = re.sub(
        r"\n## Screenshots\n.*?(?=\n## Need more modules\?|\Z)",
        "\n",
        md_text,
        flags=re.S,
    )

    html_body = markdown.markdown(
        md_text,
        extensions=["extra", "sane_lists", "nl2br", TableExtension(), TocExtension(permalink=False)],
    )
    html_body = _rewrite_image_paths(html_body)
    return HTML_TEMPLATE.replace("{body}", html_body)


def copy_screenshots() -> None:
    if not SCREENSHOTS_SRC.exists():
        return
    if SCREENSHOTS_DST.exists():
        shutil.rmtree(SCREENSHOTS_DST)
    shutil.copytree(SCREENSHOTS_SRC, SCREENSHOTS_DST)


def main() -> None:
    HTML_FILE.parent.mkdir(parents=True, exist_ok=True)
    copy_screenshots()
    HTML_FILE.write_text(build_html(), encoding="utf-8")
    print(f"Wrote {HTML_FILE}")
    print(f"Screenshots: {SCREENSHOTS_DST}")


if __name__ == "__main__":
    main()
