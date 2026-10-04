"""P8 M5 (docs/security.md): hostile .ad2v files, read-only opens, writers refusing triggers,
path containment of repository-supplied paths, and the local server basics."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from hostile import MARK, make

from ad2v import bootstrap, pipeline, specroots, store, validate
from ad2v.manifest import ManifestError, from_data
from ad2v.mcp.files import FileSet

from helpers import FIXTURE, write_tree


@pytest.fixture(scope="module")
def clean_file(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("sec") / "clean.ad2v"
    pipeline.extract_to_file(FIXTURE, None, out)
    return out


@pytest.mark.parametrize(
    "variant,expected",
    [
        ("huge", "characters (limit"),
        ("deep", "JSON nested deeper than 64"),
        ("version", "format_version is '9.9'"),
        ("objects", "schema: trigger evil_t"),
        ("xss", "id does not match"),
    ],
)
def test_validate_rejects_hostile_files(tmp_path, clean_file, variant, expected):
    assert validate.validate(clean_file) == []
    bad = make(clean_file, tmp_path / f"{variant}.ad2v", variant)
    problems = validate.validate(bad)
    assert problems and any(expected in p for p in problems), problems
    if variant == "objects":
        joined = "\n".join(problems)
        assert "unknown table evil" in joined and "unknown view evil_v" in joined
        assert "view nodes differs" in joined


def test_xss_payloads_reach_every_text_column(tmp_path, clean_file):
    bad = make(clean_file, tmp_path / "x.ad2v", "xss")
    conn = sqlite3.connect(bad)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM node_versions LIMIT 50")]
        assert all(MARK in n for n in names)
        assert (
            MARK
            in conn.execute(
                "SELECT attrs_json FROM node_versions WHERE attrs_json != '{}' LIMIT 1"
            ).fetchone()[0]
        )
        assert MARK in conn.execute("SELECT value FROM meta WHERE key = 'system_name'").fetchone()[0]
    finally:
        conn.close()


def test_read_only_open_blocks_triggers_and_writers_refuse(tmp_path, clean_file):
    bad = make(clean_file, tmp_path / "t.ad2v", "objects")
    before = sqlite3.connect(bad).execute("SELECT COUNT(*) FROM node_versions").fetchone()[0]
    conn = store.open_readonly(bad)
    try:
        assert conn.execute("PRAGMA trusted_schema").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("INSERT INTO meta VALUES ('x', 'y', 'I')")
    finally:
        conn.close()
    assert sqlite3.connect(bad).execute("SELECT COUNT(*) FROM node_versions").fetchone()[0] == before
    with pytest.raises(store.NotAnAd2vFile, match="refusing to write"):
        store.open_rw(bad)
    with pytest.raises(store.NotAnAd2vFile, match="refusing to write"):
        pipeline.extract_to_file(FIXTURE, None, bad, into=True)
    assert sqlite3.connect(bad).execute("SELECT COUNT(*) FROM node_versions").fetchone()[0] == before
    from ad2v.mcp.files import FileAccessError

    with pytest.raises(FileAccessError, match="schema objects"):  # the MCP server refuses to serve it
        FileSet(single=bad).conn(bad)


def test_writer_connections_are_hardened(tmp_path):
    conn = store.connect(tmp_path / "w.ad2v")
    assert conn.execute("PRAGMA trusted_schema").fetchone()[0] == 0
    conn.close()


def test_manifest_paths_stay_inside_the_repository(tmp_path):
    repo = tmp_path / "repo"
    write_tree(repo, {"app.py": "x = 1\n", "specs/a.md": "# A\n"})
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "s.md").write_text("# secret\n", encoding="utf-8")
    with pytest.raises(specroots.SpecRootError, match="inside the repository"):
        specroots.resolve(repo, None, ["../secret"], ())
    (tmp_path / "evil.yaml").write_text("severity: {}\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="inside the manifest"):
        from_data({"rules_overlay": "../evil.yaml"}, repo)


def test_autodetect_does_not_follow_a_symlink_out_of_the_repository(tmp_path):
    repo = tmp_path / "repo"
    write_tree(repo, {"app.py": "x = 1\n"})
    outside = tmp_path / "elsewhere"
    write_tree(outside, {"a.md": "# Component: X {#CMP-001}\n\n- [REQ-001] The x shall y.\n"})
    try:
        (repo / "specs").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need privileges on this system")
    assert specroots.resolve(repo, None, None, ()).roots == []


def test_specs_approve_refuses_a_destination_outside_the_repository(tmp_path):
    repo = tmp_path / "repo"
    xdir = repo / "specs" / ".ad2v-extracted"
    write_tree(repo, {"specs/.ad2v-extracted/p.md": "# P\n", "specs/a.md": "# A\n"})
    with pytest.raises(bootstrap.BootstrapError, match="inside the repository"):
        bootstrap.approve(repo, repo / "specs", "p.md", to=tmp_path / "outside")
    assert (xdir / "p.md").is_file()


def test_view_rejects_traversal_and_non_get(tmp_path, clean_file):
    import http.client

    from ad2v import view

    root = tmp_path / "www"
    root.mkdir()
    (root / "index.html").write_text("<p>ok</p>", encoding="utf-8")
    srv, _url = view.serve(clean_file, 0, root)
    try:
        port = srv.server_address[1]
        for path in ("/../../etc/passwd", "/..%2f..%2fpyproject.toml", "/%2e%2e/%2e%2e/README.md"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", path)
            assert c.getresponse().status == 404, path
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/data.ad2v", headers={"Host": f"rebind.example:{port}"})  # DNS rebinding
        assert c.getresponse().status == 403
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/index.html")
        r = c.getresponse()
        csp = r.getheader("Content-Security-Policy") or ""
        assert r.status == 200 and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
        assert "unsafe-eval'" not in csp.replace("wasm-unsafe-eval'", "")
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("PUT", "/index.html", body=b"x")
        assert c.getresponse().status in (404, 405, 501)
    finally:
        srv.shutdown()
