"""Tags for behind-the-meter, bridge, and temporary power language.

Tags are copied from explicit source text. A generator, turbine, or
interconnection row without that language is not tagged.
"""

from __future__ import annotations

import re

_BTM = re.compile(
    r"behind[- ]the[- ]meter|\bBTM\b|onsite use only|on-site use only|"
    r"on[- ]site consumption|does not sell power to the grid",
    re.IGNORECASE,
)
_BRIDGE = re.compile(r"\bbridge power\b|\bbridge generation\b|\bbridging power\b", re.IGNORECASE)
_TEMPORARY = re.compile(
    r"\btemporary (?:power|generation|generator|turbine|use)\b|"
    r"\bportable (?:turbine|generator|generation)\b|"
    r"\btrailer-mounted\b|\bconstruction power\b",
    re.IGNORECASE,
)


def power_signal_tags(text: str) -> list[str]:
    tags: list[str] = []
    if _BTM.search(text):
        tags.append("btm")
    if _BRIDGE.search(text):
        tags.append("bridge")
    if _TEMPORARY.search(text):
        tags.append("temporary")
    return tags
