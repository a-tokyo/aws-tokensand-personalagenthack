#!/usr/bin/env bash
# Export the audit trail and write web/audit-standalone.html with the data inline.
# Open the result with a double-click. No server is needed.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m services.audit export --out web/audit.json >/dev/null
python3 - <<'PY'
import json, pathlib
html = pathlib.Path("web/audit.html").read_text()
data = pathlib.Path("web/audit.json").read_text().replace("</", "<\\/")
tag = '<script type="application/json" id="audit-data">' + data + "</script>\n"
pathlib.Path("web/audit-standalone.html").write_text(html.replace("</head>", tag + "</head>", 1))
print("web/audit-standalone.html")
PY
