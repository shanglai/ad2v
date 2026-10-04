"""An example out-of-tree ad2v framework pack: Bottle routes for the built-in Python extractor.

It contributes one route recognizer as a rules fragment (`bottle.yaml`: `bottle.Bottle` is an HTTP
application constructor), which the core merges into the Python extractor's rules when the pack is
enabled. It has no post-extract hook, so `post_extract` is a no-op. It imports only `ad2v.api`.
"""

from __future__ import annotations

from pathlib import Path

from ad2v.api import API_VERSION, FrameworkContext

__version__ = "0.1.0"


class BottlePack:
    api_version = API_VERSION
    name = "bottle"
    version = __version__
    attaches_to = ("python",)
    frameworks = ("bottle",)
    file_patterns: tuple[str, ...] = ()
    rules_files = (Path(__file__).resolve().parent / "bottle.yaml",)
    node_kinds: frozenset[str] = frozenset()
    edge_kinds: frozenset[str] = frozenset()

    def post_extract(self, ctx: FrameworkContext) -> None:
        return None
