---
name: gf-pl-web-research
description: Pick the right tool to search the web, read a web page, extract a PDF or get library documentation. Use it when asked to look something up online, find a source, read a URL, pull text from a PDF, or check current docs for a library or framework.
metadata: { "openclaw": { "emoji": "🔎" } }
---

# Web search, pages, PDFs and docs

- `brave` is the web search provider (`BRAVE_API_KEY`).
- `duckduckgo` is installed, but it is not an automatic fallback. OpenClaw never falls back to a
  key-free provider. To use it, select it explicitly with `tools.web.search.provider`.
- `web-readability` is built in. You always have page extraction.
- Use the `llm-context` skill for pre-extracted page content.
- Use the `answers` skill for cited answers.
- `document-extract` reads PDFs. You do not need a custom skill for them.
- For library documentation, use `context7-cli` (`CONTEXT7_API_KEY`). Prefer it over any web search.
