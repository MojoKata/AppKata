"""scripts/tour_page.py, one self-contained page of a pull request's Linux tour: every screen inlined,
those that differ from master's published tour first, beside master's, then the new, the gone and
the rest (docs/github-workflows.md, "The tour")."""

import base64
import importlib.util
import json
import os

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location("tour_page", os.path.join(ROOT, "scripts", "tour_page.py"))
tp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp)
BASE = "https://someone.github.io/Store/"


def _tour(path, files):
    for name, data in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(data)
    return path


def _site(served):
    def get(url):
        assert url.startswith(BASE)
        return served.get(url.removeprefix(BASE).split("?")[0])
    return get


def test_changed_screens_come_first_beside_master_s(tmp_path):
    new = tp.screens(_tour(tmp_path / "t", {"dark/A01.png": b"new A01", "dark/B.png": b"same", "light/N.png": b"new one"}))
    assert list(new) == ["dark/A01.png", "dark/B.png", "light/N.png"]
    index = {"versions": {"master": ["dark/A01.png", "dark/B.png", "dark/Gone.png"], "0.1.0": ["dark/A01.png"]}}
    old = tp.published(BASE, _site({"screenshots/index.json": json.dumps(index).encode(),
                                     "screenshots/master/dark/A01.png": b"old A01", "screenshots/master/dark/B.png": b"same",
                                     "screenshots/master/dark/Gone.png": b"gone"}))
    assert tp.compare(new, old) == (["dark/A01.png"], ["light/N.png"], ["dark/Gone.png"], ["dark/B.png"])
    page = tp.page(new, old, "Tour <PR>", True)
    assert "<title>Tour &lt;PR&gt;</title>" in page
    assert "3 screens: 1 differ from master's published tour, 1 new, 1 gone, 1 the same." in page
    changed = page[page.index("id='changed'"):page.index("id='new'")]
    b64 = lambda b: base64.b64encode(b).decode()                       # noqa: E731
    assert changed.index(b64(b"old A01")) < changed.index(b64(b"new A01"))   # master's, then this run's
    assert b64(b"gone") in page[page.index("id='gone'"):page.index("id='same'")]
    assert "<details>" in page[page.index("id='same'"):]                      # the same ones folded away
    assert "src='http" not in page                                             # nothing to load from elsewhere


def _fake(get):
    return type("Site", (), {"get": staticmethod(get), "site_url": staticmethod(lambda: BASE)})


def test_a_site_with_no_master_tour_compares_nothing_but_lists_every_screen(monkeypatch, tmp_path, capsys):
    tour = _tour(tmp_path / "t", {"dark/A01.png": b"a"})
    out = tmp_path / "tour.html"
    calls = []
    monkeypatch.setattr(tp, "_site", lambda: _fake(lambda url: calls.append(url)))
    assert tp.main([str(tour), str(out)]) == 0
    assert "1 screens: 0 differ from master's published tour, 1 new" in out.read_text()
    assert calls and calls[0].startswith(BASE + "screenshots/index.json")
    assert tp.main([str(tour), str(out), "--master", "none"]) == 0
    assert "master's published tour wasn't read" in out.read_text()

    def fail(url):
        raise OSError("unreachable")
    monkeypatch.setattr(tp, "_site", lambda: _fake(fail))
    assert tp.main([str(tour), str(out)]) == 0
    assert "wasn't read" in out.read_text() and "unreachable" in capsys.readouterr().err
    assert tp.main([str(tmp_path / "empty"), str(out)]) == 1


@pytest.mark.parametrize("name", ["dark/<x>.png"])
def test_names_are_escaped(tmp_path, name):
    page = tp.page({name: b"x"}, {}, "t", True)
    assert "&lt;x&gt;" in page and "<x>" not in page
