---
paths:
  - "docs/**"
  - "experience/**"
  - "AGENTS.md"
  - "CLAUDE.md"
---
# Documentation rules
- Update the existing canonical document instead of adding a new planning file. Dated receipts are evidence, not proof of current operation.
- Run `uv run --project backend python scripts/check_docs.py` after editing maintained docs.
- `experience/` is curated knowledge: short, dated, factual. Policy changes go through `experience/proposed-improvements.md` first.
