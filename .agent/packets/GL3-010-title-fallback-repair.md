# GL3-010 title fallback repair

Repair-only packet after `FIX` in `.agent/artifacts/GL3-010/REVIEW.json` for candidate `43f9faa5c6cd1b653da96a03e6fcc299becb126c110cfe918a1b571169b32f23` on `fix/project-cards`.

Change only `web/src/features/opportunities/projectCards.ts` and `web/tests/project_cards.spec.ts`. Preserve the review and existing grouping/50-record result. If `supported_action` is absent, safely extract a substantive `description`, `work`, `project`, or `type` value from structured permit evidence; never use row ID/date/status labels as project text. If permit boilerplate cleanup leaves no usable work description, show neutral activity plus the record location. Add focused regressions for boilerplate-only supported action and a structured raw abstract without supported action.

Run the focused Playwright regression and frontend typecheck/build. Do not change grouping, app layout, runtime, database, or other scope. Builder reports evidence; controller freezes, reruns final gates, and requests independent review of the changed candidate.
