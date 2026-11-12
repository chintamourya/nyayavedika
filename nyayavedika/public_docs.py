"""Render the project's public Markdown documents as web pages."""
from html import escape
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = {
    "how-it-works": ("How NyayaVedika works", "HOW_IT_WORKS.md"),
    "research-evidence": ("Research & evidence", "RESEARCH_EVIDENCE.md"),
}
_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def render_page(document: str) -> str:
    title, filename = DOCUMENTS[document]
    source = (ROOT / "docs" / filename).read_text(encoding="utf-8")
    content = _MARKDOWN.render(source)
    safe_title = escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0866ff">
<title>{safe_title} · NyayaVedika</title>
<link rel="icon" href="/static/favicon.svg?v=3" type="image/svg+xml">
<link rel="stylesheet" href="/static/styles.css?v=15">
</head>
<body class="document-page">
<header class="doc-top">
  <a class="doc-brand" href="/"><span aria-hidden="true">⚖</span><b>NyayaVedika</b></a>
  <a class="doc-back" href="/">← Back to home</a>
  <button type="button" class="theme-toggle">Dark mode</button>
</header>
<main class="doc-main">
  <article class="doc-content">{content}</article>
</main>
<script src="/static/common.js?v=14"></script>
{"<script src=\"/static/docs.js?v=2\" defer></script>" if "language-mermaid" in content else ""}
</body>
</html>"""
