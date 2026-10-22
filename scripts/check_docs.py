"""Validate local Markdown links and heading anchors in the maintained docs graph."""

from __future__ import annotations

import re
import sys
from collections import Counter, deque
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINTS = (
    "README.md",
    "docs/README.md",
    "docs/architecture/README.md",
    "docs/architecture/overview.md",
    "docs/sources/README.md",
    "docs/sources/coverage.md",
    "docs/operations/README.md",
    "docs/operations/local-runtime.md",
    "docs/operations/runtime-recovery.md",
    "docs/operations/runtime-configuration.md",
    "docs/delivery/README.md",
    "docs/delivery/milestones.md",
    "backend/README.md",
    "backend/tests/README.md",
    "config/README.md",
    "web/README.md",
    "scripts/README.md",
    "deploy/README.md",
    "deploy/digitalocean/README.md",
)
# These folders contain immutable or candidate-scoped evidence. Check links to
# those documents when encountered, but do not promote their outgoing links to
# the maintained documentation graph.
HISTORICAL_PREFIXES = (
    "docs/validation/",
    "docs/superpowers/",
    ".agent/archive/",
)
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCED_CODE = re.compile(r"(?ms)^\s*(```|~~~).*?^\s*\1[^\n]*$")
INLINE_CODE = re.compile(r"`+[^`]*`+")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
HTML_ID = re.compile(r"\b(?:id|name)=[\"']([^\"']+)[\"']", re.IGNORECASE)


def markdown_source(path: Path) -> str:
    text = path.read_text(encoding="utf-8-sig")
    text = FENCED_CODE.sub("", text)
    return INLINE_CODE.sub("", text)


def anchors(path: Path) -> set[str]:
    result: set[str] = set()
    duplicates: Counter[str] = Counter()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        for match in HTML_ID.finditer(line):
            result.add(match.group(1))
        heading = HEADING.match(line)
        if not heading:
            continue
        label = heading.group(2)
        label = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", label)
        label = re.sub(r"<[^>]+>", "", label)
        label = re.sub(r"[`*_~]", "", label).lower()
        label = re.sub(r"[^\w\- ]", "", label, flags=re.UNICODE)
        slug = re.sub(r"\s+", "-", label.strip())
        suffix = duplicates[slug]
        duplicates[slug] += 1
        result.add(slug if suffix == 0 else f"{slug}-{suffix}")
    return result


def link_target(raw: str) -> str:
    value = raw.strip()
    match = re.match(r"^<([^>]+)>(?:\s+.*)?$", value)
    if match:
        return match.group(1)
    return value.split(maxsplit=1)[0] if value else ""


def is_historical(relative: str) -> bool:
    return relative.startswith(HISTORICAL_PREFIXES)


def main() -> int:
    errors: list[str] = []
    visited: set[Path] = set()
    pending = deque((ROOT / entry).resolve() for entry in ENTRY_POINTS)
    checked_targets = 0
    checked_anchors = 0

    while pending:
        source = pending.popleft()
        if source in visited:
            continue
        visited.add(source)
        if not source.is_file():
            try:
                relative = source.relative_to(ROOT).as_posix()
            except ValueError:
                relative = str(source)
            errors.append(f"missing entry or linked document: {relative}")
            continue

        try:
            relative_source = source.relative_to(ROOT).as_posix()
        except ValueError:
            errors.append(f"documentation path escapes repository: {source}")
            continue

        if is_historical(relative_source):
            continue

        text = markdown_source(source)
        for line_number, line in enumerate(text.splitlines(), 1):
            for raw_target in LINK.findall(line):
                target = link_target(raw_target)
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith("//"):
                    continue
                target_path = unquote(parsed.path)
                fragment = unquote(parsed.fragment)
                resolved = (source.parent / target_path).resolve() if target_path else source
                checked_targets += 1
                try:
                    resolved.relative_to(ROOT)
                except ValueError:
                    errors.append(f"{relative_source}:{line_number}: target escapes repository: {target}")
                    continue
                if not resolved.exists():
                    errors.append(f"{relative_source}:{line_number}: missing local target: {target}")
                    continue
                if fragment and resolved.is_file() and resolved.suffix.lower() in {".md", ".html", ".htm"}:
                    checked_anchors += 1
                    if resolved.suffix.lower() == ".md" and fragment not in anchors(resolved):
                        errors.append(f"{relative_source}:{line_number}: missing anchor #{fragment} in {resolved.relative_to(ROOT).as_posix()}")
                if resolved.is_file() and resolved.suffix.lower() == ".md" and not is_historical(resolved.relative_to(ROOT).as_posix()):
                    pending.append(resolved)

    if errors:
        print("Maintained documentation graph check failed:")
        print("\n".join(errors))
        print(f"Checked {len(visited)} documents, {checked_targets} local targets, and {checked_anchors} anchors.")
        return 1

    print(
        f"Maintained documentation graph passed: {len(visited)} documents, "
        f"{checked_targets} local targets, {checked_anchors} anchors."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
