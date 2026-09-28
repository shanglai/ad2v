"""Versioned prompt templates (`<task>.v1.md`) and their hashes (format spec §11.2).

A template file has two sections, `# system` and `# user`. `prompt_hash` is sha256 of the
normalized file (LF line endings, trailing whitespace stripped), so editing a prompt invalidates
the cache for that task and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from ad2v import ids

PROMPT_DIR = Path(__file__).parent
VERSION = "v1"


@dataclass(frozen=True)
class Prompt:
    task: str
    system: str
    user: str
    prompt_hash: str


@cache
def load(task: str) -> Prompt:
    path = PROMPT_DIR / f"{task}.{VERSION}.md"
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    text = "\n".join(line.rstrip() for line in raw.split("\n")).strip() + "\n"
    parts = text.split("\n# user\n")
    if len(parts) != 2 or not parts[0].startswith("# system\n"):
        raise ValueError(f"{path.name}: needs '# system' then '# user' sections")
    system = parts[0][len("# system\n") :].strip()
    return Prompt(task, system, parts[1].strip(), ids.sha256_hex(text))
