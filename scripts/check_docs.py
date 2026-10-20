"""Check local Markdown links in the active documentation entry points."""

from __future__ import annotations

import re
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = (
    "README.md",
    "docs/README.md",
    "docs/architecture/overview.md",
    "docs/sources/coverage.md",
    "docs/operations/README.md",
    "docs/delivery/milestones.md",
    "backend/README.md",
    "web/README.md",
    "scripts/README.md",
    "deploy/README.md",
)
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    errors: list[str] = []
    checked = 0
    for relative in ACTIVE:
        source = ROOT / PurePosixPath(relative)
        if not source.is_file():
            errors.append(f"missing active document: {relative}")
            continue
        for line_number, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), 1):
            for raw_target in LINK.findall(line):
                target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith("//"):
                    continue
                path = unquote(parsed.path)
                if not path:
                    continue
                checked += 1
                resolved = (source.parent / path).resolve()
                try:
                    resolved.relative_to(ROOT)
                except ValueError:
                    errors.append(f"{relative}:{line_number}: target escapes repository: {target}")
                    continue
                if not resolved.exists():
                    errors.append(f"{relative}:{line_number}: missing target: {target}")

    if errors:
        print("Active documentation link check failed:")
        print("\n".join(errors))
        return 1
    print(f"Active documentation link check passed: {len(ACTIVE)} documents, {checked} local targets.")
    print("Historical inventory is separate: 151 documents, 34 missing relative targets at baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
