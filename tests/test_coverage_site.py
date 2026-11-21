"""scripts/coverage_site.py, the Pages site: each push's totals added to the history the published site
holds, never starting it over by mistake, the screenshots carried from one build to the next, and the
pages built from them."""

import importlib.util
import json
import os
import re
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location("coverage_site", os.path.join(ROOT, "scripts", "coverage_site.py"))
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)
BASE = "https://someone.github.io/Store/"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Never GitHub here: the repository SomeOne/Store, outside CI, with no issues unless a test says."""
    monkeypatch.setattr(cs.hardening, "fetch_issues", lambda repo: [])
    monkeypatch.setenv("GITHUB_REPOSITORY", "SomeOne/Store")
    for var in ("GITHUB_ACTIONS", "APPKATA_SITE", "GITHUB_SERVER_URL"):
        monkeypatch.delenv(var, raising=False)


def area(lines, branches, count=100):
    """An area's totals with the counts behind its figures, `count` lines and as many branches."""
    reached = round(lines * count / 100)
    taken = 0 if branches is None else round(branches * count / 100)
    return cs.cr.counted(1, count, reached, 0 if branches is None else count, taken)


def point(commit, areas, pr=None):
    return {"commit": commit, "date": "2026-11-21T06:00:00-06:00", "pr": pr, "subject": f"work <{commit}>",
            "areas": areas}


def site(served):
    """A stand-in for the published site: what each path answers, None for a 404."""

    def get(url):
        answer = served.get(url.removeprefix(BASE).split("?")[0])
        if isinstance(answer, Exception):
            raise answer
        return answer

    return get


def test_the_site_is_the_repository_s_own_pages(monkeypatch):
    assert cs.site_url() == BASE and cs.repo_url() == "https://github.com/SomeOne/Store"
    monkeypatch.setenv("APPKATA_SITE", "http://localhost:8000")
    assert cs.site_url() == "http://localhost:8000/"
    # outside CI, the repository APPKATA_REPO names
    monkeypatch.delenv("GITHUB_REPOSITORY")
    text = open(os.path.join(ROOT, "src", "appkata_core", "__init__.py"), encoding="utf-8").read()
    assert "https://github.com/" + cs.repository() in text


def test_the_history_is_read_back_and_never_started_over(monkeypatch):
    history = [point("a" * 40, {"trust": area(90.0, 80.0)})]
    monkeypatch.setattr(cs, "get", site({"history.json": json.dumps(history).encode()}))
    assert cs.fetch_history(BASE, "1") == history
    # no site at all: the first push starts the history
    monkeypatch.setattr(cs, "get", site({}))
    assert cs.fetch_history(BASE, "1") == []
    # a site without its history is a mistake somewhere, not a fresh start
    monkeypatch.setattr(cs, "get", site({"": b"<html>"}))
    with pytest.raises(SystemExit, match="not starting it over"):
        cs.fetch_history(BASE, "1")


def test_a_run_done_again_replaces_its_own_point():
    one, two = point("1" * 40, {}), point("2" * 40, {})
    again = point("1" * 40, {"trust": area(50.0, None)})
    assert cs.add([one, two], again) == [two, again]
    assert cs.add([one], two) == [one, two]


def test_an_entry_names_its_pull_request(monkeypatch):
    out = "c" * 40 + "\n2026-11-21T06:00:00-06:00\nH1.3 Requirements layout (#53)\n"
    monkeypatch.setattr(cs, "git", lambda *a: subprocess.CompletedProcess(a, 0, out, ""))
    e = cs.entry({"trust": area(80.0, 70.0)})
    assert (e["commit"], e["pr"], e["subject"]) == ("c" * 40, 53, "H1.3 Requirements layout (#53)")
    monkeypatch.setattr(cs, "git", lambda *a: subprocess.CompletedProcess(a, 0, "d" * 40 + "\nx\nMerge it\n", ""))
    assert cs.entry({})["pr"] is None


def test_the_sums_are_their_areas_summed_from_their_counts():
    h = point("e" * 40, {"trust": area(100.0, 50.0, count=300), "sandbox": area(50.0, None),
                         "scripts": area(20.0, 60.0, count=100)})
    assert cs.figure(h, "app", "lines") == 87.5 and cs.figure(h, "app", "branches") == 50.0
    assert cs.figure(h, "overall", "lines") == 74.0
    assert cs.figure(h, "sandbox", "branches") is None and cs.figure(h, "windows", "lines") is None
    assert cs.figure(point("f" * 40, {}), "app", "lines") is None


def test_a_chart_breaks_where_an_area_was_not_measured():
    history = [point("1" * 40, {"trust": area(90.0, 80.0)}, pr=1), point("2" * 40, {}, pr=2),
               point("3" * 40, {"trust": area(91.0, 81.0)}, pr=3), point("4" * 40, {"trust": area(92.0, 82.0)}, pr=4)]
    svg = cs.chart(history, "trust")
    lines = re.search(r'class="line lines" d="([^"]+)"', svg)[1]
    assert lines.count("M") == 2 and lines.count("L") == 1
    # the point alone and each series' last point carry a dot
    assert svg.count('class="dot lines"') == 2 and svg.count('class="dot branches"') == 2
    assert ">#1</text>" in svg and ">#4</text>" in svg
    one = cs.chart(history[:1], "trust")
    assert 'text-anchor="middle">#1</text>' in one


def test_a_bar_takes_its_band_s_colour_and_stripes_below_its_floor():
    assert "class='meter lines good'" in cs.meter("lines", 92.0, 90.0)
    assert "class='meter branches fair below'" in cs.meter("branches", 70.0, 71.0)
    top, good = cs.meter("lines", 95.0), cs.meter("lines", 94.9)
    assert "class='meter lines top'" in top and ">★</span>" in top
    assert "class='meter lines good'" in good and "★" not in good
    assert "class='meter lines low'" in cs.meter("lines", 57.2)
    assert "class='pct'>—" in cs.meter("lines", None)
    assert "<span class='delta'>+1.5</span>" in cs.meter("lines", 61.5, None, 60.0)
    assert "<span class='delta'>−0.5</span>" in cs.meter("lines", 60.0, None, 60.5)


def coverage_dir(tmp_path, totals, files):
    out = tmp_path / "coverage"
    (out / "html").mkdir(parents=True)
    (out / "html" / "index.html").write_text("the report")
    status = {"files": {"z_1": {"index": {"url": "z_1_trustfile_py.html", "file": "src/appkata_core/trustfile.py"}}}}
    (out / "html" / "status.json").write_text(json.dumps(status))
    (out / "totals.json").write_text(json.dumps(totals))
    (out / "files.json").write_text(json.dumps(files))
    return out


def test_the_site_holds_the_report_the_history_and_its_pages(monkeypatch, tmp_path):
    totals = {"trust": area(90.0, 80.0), "scripts": area(60.0, None)}
    files = [{"path": "src/appkata_core/trustfile.py", "area": "trust", **cs.cr.counted(1, 10, 9, 4, 3)},
             {"path": "scripts/public_text.py", "area": "scripts", **cs.cr.counted(1, 10, 6, 0, 0)}]
    coverage = coverage_dir(tmp_path, totals, files)
    before = point("0" * 40, {"trust": area(89.0, 80.0)}, pr=17)
    monkeypatch.setattr(cs, "get", site({"history.json": json.dumps([before]).encode(),
                                         "screenshots/index.json": b'{"versions": {}}'}))
    monkeypatch.setattr(cs.hardening, "fetch_issues",
                        lambda repo: [{"number": 37, "title": "H1.1 Pages site", "body": "", "state": "open",
                                       "reason": None, "labels": ["hardening", "area:tooling"], "parent": None,
                                       "prs": []}])
    out = tmp_path / "site"
    assert cs.build(coverage, out) == 0
    history = json.loads((out / "history.json").read_text())
    assert len(history) == 2 and history[0] == before
    assert history[-1]["areas"] == totals and history[-1]["hardening"]["tooling"]["all"] == 0
    assert (out / "report" / "index.html").read_text() == "the report"
    rows = json.loads((out / "files.json").read_text())
    assert rows[0]["report"] == "report/z_1_trustfile_py.html" and "report" not in rows[1]

    page = (out / "index.html").read_text()
    assert "<title>AppKata coverage</title>" in page
    assert "work &lt;" + "0" * 40 + "&gt;" in page                # an old subject, escaped
    assert "<span class='pct'>90.0%</span><span class='delta'>+1.0</span>" in page
    # the two sums' charts, then each area's
    assert page.count('<figure class="chart"') == 2 + len(totals)
    assert page.count("<tbody class='area'>") == len(totals)
    assert "<a href='report/z_1_trustfile_py.html'>src/appkata_core/trustfile.py</a>" in page
    assert "<th>App</th>" in page and "<th>Overall</th>" in page
    assert "<!-- built from " + BASE + " -->" in page
    hard = (out / "hardening.html").read_text()
    assert "<title>AppKata hardening</title>" in hard and '"what":"Pages site"' in hard
    assert json.loads((out / "screenshots" / "index.json").read_text()) == {"versions": {}}
    assert "None are published" in (out / "screenshots" / "index.html").read_text()


def test_nothing_measured_builds_nothing(tmp_path, capsys):
    assert cs.build(tmp_path / "none", tmp_path / "site") == 1
    assert "nothing measured" in capsys.readouterr().out and not (tmp_path / "site").exists()


def test_ci_fails_when_the_history_or_the_issues_cannot_be_read(monkeypatch, tmp_path):
    coverage = coverage_dir(tmp_path, {}, [])
    monkeypatch.setattr(cs, "get", site({"history.json": OSError("unreachable")}))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(OSError):
        cs.build(coverage, tmp_path / "site")
    # a preview goes on without it, and without carrying the screenshots
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert cs.build(coverage, tmp_path / "site") == 0
    assert len(json.loads((tmp_path / "site" / "history.json").read_text())) == 1

    asked = []

    def fail(repo):
        asked.append(repo)
        raise OSError("unreachable")

    monkeypatch.setattr(cs, "get", site({}))
    monkeypatch.setattr(cs.hardening, "fetch_issues", fail)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(OSError):
        cs.build(coverage, tmp_path / "site")
    assert asked == ["SomeOne/Store"]
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert cs.build(coverage, tmp_path / "site") == 0 and (tmp_path / "site" / "hardening.html").exists()


def test_the_published_screenshots_are_carried_and_a_new_version_added(monkeypatch, tmp_path):
    index = {"versions": {"0.1.0": ["tour/01-apps.png"], "0.0.9": ["a.png"]}}
    monkeypatch.setattr(cs, "get", site({"screenshots/index.json": json.dumps(index).encode(),
                                         "screenshots/0.1.0/tour/01-apps.png": b"old 0.1.0",
                                         "screenshots/0.0.9/a.png": b"0.0.9"}))
    new = tmp_path / "new"
    (new / "0.1.0").mkdir(parents=True)
    (new / "0.1.0" / "b.png").write_bytes(b"new 0.1.0")
    (new / "0.10.0").mkdir()
    (new / "0.10.0" / "c.png").write_bytes(b"0.10.0")
    dest = tmp_path / "site"
    got = cs.screenshots(BASE, "1", dest, new)
    # newest first; a version this build brings replaces the published one
    assert got == {"0.10.0": ["c.png"], "0.1.0": ["b.png"], "0.0.9": ["a.png"]}
    assert (dest / "0.0.9" / "a.png").read_bytes() == b"0.0.9"
    assert (dest / "0.1.0" / "b.png").read_bytes() == b"new 0.1.0" and not (dest / "0.1.0" / "tour").exists()
    page = cs.screenshots_page(got)
    assert page.index("<h2 id='v0.10.0'>") < page.index("<h2 id='v0.1.0'>") < page.index("<h2 id='v0.0.9'>")
    assert "src='0.0.9/a.png'" in page


def test_a_listed_screenshot_that_is_gone_or_outside_its_version_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "get", site({"screenshots/index.json": b'{"versions": {"0.1.0": ["a.png"]}}'}))
    with pytest.raises(SystemExit, match="listed but not there"):
        cs.screenshots(BASE, "1", tmp_path)
    monkeypatch.setattr(cs, "get", site({"screenshots/index.json": b'{"versions": {"0.1.0": ["../../x"]}}'}))
    with pytest.raises(SystemExit, match="not a file under its version"):
        cs.screenshots(BASE, "1", tmp_path)
    # a site without its screenshots' index isn't a fresh start either
    monkeypatch.setattr(cs, "get", site({"": b"<html>"}))
    with pytest.raises(SystemExit, match="not starting it over"):
        cs.screenshots(BASE, "1", tmp_path)
    assert cs.screenshots(BASE, "1", tmp_path, fetch=False) == {}


def test_the_command_line_builds_into_the_folder_given(monkeypatch, tmp_path):
    coverage = coverage_dir(tmp_path, {"trust": area(90.0, 80.0)}, [])
    monkeypatch.setattr(cs, "get", site({}))
    assert cs.main(["build", "--coverage", str(coverage), "--out", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "index.html").exists()


def test_master_s_tour_comes_first_and_says_what_it_is(monkeypatch, tmp_path):
    monkeypatch.setattr(cs, "get", site({"screenshots/index.json": b'{"versions": {}}'}))
    new = tmp_path / "new"
    for v in ("master", "0.2.0"):
        (new / v / "dark").mkdir(parents=True)
        (new / v / "dark" / "A01-apps.png").write_bytes(v.encode())
    got = cs.screenshots(BASE, "1", tmp_path / "site", new)
    assert list(got) == ["master", "0.2.0"]
    page = cs.screenshots_page(got)
    assert "The newest push to master, replaced by each one: 1 screens." in page
    assert "Release 0.2.0, from CI's run of its tag: 1 screens." in page


def test_a_published_release_s_tour_is_brought_from_its_tag_s_run_once(monkeypatch, tmp_path, capsys):
    """release_tours brings each published release's tour the site doesn't hold, from its tag's CI run;
    a draft, a release the site holds, and one whose run or artifact is gone bring nothing, and the
    site goes on."""
    monkeypatch.setattr(cs, "get", site({"screenshots/index.json": b'{"versions": {"0.1.0": ["dark/a.png"]}}'}))
    asked = []

    def gh(*args):
        asked.append(args)
        if args[0] == "api":
            assert "select(.draft | not)" in args[-1]             # drafts aren't releases yet
            return "v0.1.0\nv0.2.0\nv0.3.0\nv0.4.0\n"
        if args[:2] == ("run", "list"):
            tag = args[args.index("--branch") + 1]
            return {"v0.2.0": "11\n", "v0.4.0": "44\n"}.get(tag, "")
        if args[:2] == ("run", "download"):
            if args[2] == "44":
                return None
            d = tmp_path / "shots" / "0.2.0" / "dark"
            d.mkdir(parents=True)
            (d / "A01-apps.png").write_bytes(b"0.2.0")
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(cs, "gh", gh)
    assert cs.release_tours(tmp_path / "shots") == ["0.2.0"]
    lists = [a for a in asked if a[:2] == ("run", "list")]
    assert [a[a.index("--branch") + 1] for a in lists] == ["v0.2.0", "v0.3.0", "v0.4.0"]     # not v0.1.0: held
    assert all("--status" in a and "success" in a for a in lists)
    assert sorted(p.name for p in (tmp_path / "shots").iterdir()) == ["0.2.0"]          # 0.4.0's partial one gone
    out = capsys.readouterr().out
    assert "v0.3.0: no passing CI run" in out and "v0.4.0: run 44 has no tour artifact" in out

    monkeypatch.setattr(cs, "gh", lambda *a: None)
    with pytest.raises(SystemExit, match="releases of SomeOne/Store couldn't be read"):
        cs.release_tours(tmp_path / "shots")


def test_gh_passes_ci_s_token_and_says_none_when_it_fails(monkeypatch, tmp_path, capsys):
    fake = tmp_path / "gh"
    fake.write_text('#!/bin/sh\n[ "$1" = fail ] && { echo "no such thing" >&2; exit 1; }\necho "$GH_TOKEN $*"\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    assert cs.gh("api", "x") == "t0ken api x\n"
    assert cs.gh("fail") is None and "no such thing" in capsys.readouterr().err
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    cs.notice("gone")
    assert capsys.readouterr().out == "::warning title=release tours::gone\n"
