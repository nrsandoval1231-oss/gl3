# F5 — readable operations text within the existing commercial theme

Base e4fa7402f420af289837763d89787359af4414f9, same isolated integration branch.
Independent visual FIX: white health panel inherits near-white commercial text,
measured1.09:1 contrast. Luna owns only web/src/styles/pursuits.css and one focused
test in web/tests/commercial-pursuits.spec.ts. Root owns documentation.

Apply existing navy #17324a to .health-panel .intelligence-operations only. Preserve
logo, navigation, layout, other commercial colors and product semantics. Add a
computed foreground/background contrast assertion >=4.5:1 for operations summary
and explanatory text while Source health is open from pursuits. Root additionally
inspects actual expanded operations screenshot on the fresh candidate.

Run focused/full affected commercial browser module, typecheck and diff check.
Mock-only loopback test surfaces; no database/provider/external mutation. Two
bounded repairs then report constraints. Return exact commands/results/release;
no commit/merge/deploy. Full e4fa backend2108 passes and browser146 passes remain
development evidence, not acceptance after this change. Re-freeze and run complete
required gates and independent review on the new candidate.

Handoff: focused contrast test1 passed in4.8s; complete commercial module16 passed in24.3s; typecheck/diff pass. Temporary ports8387/5387 clear. No other product changes.
