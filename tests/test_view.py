"""P5: `ad2v view` serves the viewer and the file on 127.0.0.1 only (real socket, port 0)."""

import urllib.error
import urllib.request

import pytest

from ad2v import pipeline, view

from helpers import FIXTURE, JUNIT


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>ad2v viewer</title>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not served", encoding="utf-8")
    f = tmp_path / "x.ad2v"
    pipeline.extract_to_file(FIXTURE, FIXTURE / "specs", f, test_results=[JUNIT])
    server, url = view.serve(f, 0, root)
    yield server, url, f
    server.shutdown()
    server.server_close()


def _get(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - loopback test server
        return r.status, r.headers, r.read()


def test_binds_loopback_only_and_serves(served):
    server, url, f = served
    host, port = server.server_address[:2]
    assert host == "127.0.0.1" and port > 0
    assert url.startswith(f"http://127.0.0.1:{port}/index.html?file=project.ad2v")
    status, headers, body = _get(url)
    assert status == 200 and b"ad2v viewer" in body and "no-store" in headers["Cache-Control"]
    status, headers, body = _get(f"http://127.0.0.1:{port}/project.ad2v")
    assert body == f.read_bytes() and headers["Content-Type"] == "application/octet-stream"
    status, headers, _ = _get(f"http://127.0.0.1:{port}/assets/app.js")
    assert headers["Content-Type"] == "text/javascript"
    status, headers, body = _get(f"http://127.0.0.1:{port}/project.ad2v", "HEAD")
    assert status == 200 and body == b""


def test_refuses_traversal_writes_and_listing(served):
    server, _url, _f = served
    base = f"http://127.0.0.1:{server.server_address[1]}"
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/", "/nope.js"):
        with pytest.raises(urllib.error.HTTPError) as e:
            _get(base + path)
        assert e.value.code == 404, path
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(base + "/project.ad2v", "POST")
    assert e.value.code == 405


def test_rejects_non_ad2v_file(tmp_path):
    bad = tmp_path / "bad.ad2v"
    bad.write_text("not sqlite", encoding="utf-8")
    from ad2v import store

    with pytest.raises(store.NotAnAd2vFile):
        view.serve(bad, 0, tmp_path)


def test_viewer_dir_is_found_or_explains(monkeypatch, tmp_path):
    monkeypatch.setattr(view, "_HERE", tmp_path / "pkg")
    with pytest.raises(view.ViewerNotBuilt, match="npm run build"):
        view.viewer_dir()
    (tmp_path / "pkg" / "_viewer").mkdir(parents=True)
    (tmp_path / "pkg" / "_viewer" / "index.html").write_text("x", encoding="utf-8")
    assert view.viewer_dir() == tmp_path / "pkg" / "_viewer"
