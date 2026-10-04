"""P8 M4: the Python license gate script (scripts/check_python_licenses.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_python_licenses.py"


def _mod():
    spec = importlib.util.spec_from_file_location("check_python_licenses", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_runtime_closure_is_clean(capsys):
    m = _mod()
    assert m.main([]) == 0
    out = capsys.readouterr().out
    assert "licenses OK" in out and "certifi" not in out


def test_copyleft_and_banned_are_detected(monkeypatch, capsys):
    m = _mod()

    class FakeDist:
        def __init__(self, name, lic):
            self.metadata = {"Name": name, "License-Expression": lic}
            self.version = "1"
            self.requires = []

    fake = {
        "ad2v": FakeDist("ad2v", "Apache-2.0"),
        "evil": FakeDist("evil", "GPL-3.0-only"),
        "certifi": FakeDist("certifi", "MPL-2.0"),
        "odd": FakeDist("odd", "Proprietary-ish"),
    }
    monkeypatch.setattr(m, "closure", lambda root, extras: fake)
    monkeypatch.setattr(m, "license_of", lambda d: d.metadata["License-Expression"])
    assert m.main([]) == 1
    err = capsys.readouterr().err
    assert "evil 1: copyleft" in err and "certifi: banned" in err and "odd 1: unknown license" in err
