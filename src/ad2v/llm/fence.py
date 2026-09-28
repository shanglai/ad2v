"""Fencing untrusted repository content, and deterministic guards on outputs (format spec §11.9).

Everything cut from the repository (code, comments, specs, prose) goes into the prompt inside
`<untrusted-data>` fences whose id is derived from the content, and any text that could close or
forge a fence is neutralized. The system prompt tells the model the fenced text is data. Outputs
are then checked deterministically: long verbatim copies of fenced text are flagged (an echoed
injection), and instruction-like phrases in the input are recorded as a warning.
"""

from __future__ import annotations

import re
from typing import Any

from ad2v import ids

FENCE_TAG = "untrusted-data"
VERBATIM_MIN_CHARS = 60  # an output string sharing this many consecutive chars with the data is flagged
INJECTION_RE = re.compile(
    r"(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?|rules)"
    r"|you\s+are\s+now\b|new\s+instructions\s*:|system\s+prompt|answer\s+(with\s+)?[\"']?(conforms|match)\b",
    re.I,
)


def fence(kind: str, label: str, text: str) -> str:
    """Wrap untrusted text. The fence id depends only on the content, so prompts are deterministic."""
    safe = re.sub(r"untrusted-data", "untrusted_data", text, flags=re.I)
    fid = ids.sha256_hex(f"{kind}|{label}|{safe}")[:8]
    return (
        f'<{FENCE_TAG} id="{fid}" kind="{kind}" source="{_attr(label)}">\n{safe}\n</{FENCE_TAG} id="{fid}">'
    )


def _attr(s: str) -> str:
    return s.replace('"', "'").replace("\n", " ")[:200]


def numbered(lines: list[tuple[int, str]]) -> str:
    """Lines with their real 1-based line numbers, so outputs can cite ranges."""
    width = max((len(str(n)) for n, _ in lines), default=1)
    return "\n".join(f"{n:>{width}}| {t}" for n, t in lines)


def strings(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in strings(v)]
    return []


def verbatim_copy(output: Any, data: str, min_chars: int = VERBATIM_MIN_CHARS) -> str | None:
    """The first output substring of `min_chars` that appears verbatim in `data`, else None."""
    hay = " ".join(data.split())
    for s in strings(output):
        t = " ".join(s.split())
        for i in range(0, max(0, len(t) - min_chars + 1)):
            window = t[i : i + min_chars]
            if window in hay:
                return window
    return None


def injection_phrases(data: str) -> list[str]:
    return sorted({m.group(0).lower() for m in INJECTION_RE.finditer(data)})
