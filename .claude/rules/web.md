---
paths:
  - "web/**"
---
# Web rules
- Stack is React 19 + Vite + plain CSS with hand-rolled history navigation (`features/workspace/Workspace.tsx`). No router library or UI framework without approval.
- Keep the released visual identity (`docs/design/UI_CANON.md`); approved references drive layout changes. Never display data the API does not supply (e.g. confidence) — show the real field or an honest unavailable state.
- Unknown is not zero. Missing MW, dates or contacts render as unknown/unavailable, never `0` or a guess.
- Preserve table/row semantics via ARIA when restyling, keyboard focus states and `prefers-reduced-motion`. No horizontal page scroll at 390px.
- API contract: after backend route changes run `python scripts/export_openapi.py` then `npm run generate:api`.
