"""Tier 1's parts in CI, split by measured time (tests/parts.py): every test in exactly one part, the
tests sharing a module's fixture together, the heavy ones spread, and the times gathered from a run's
parts into a file per area."""

import json

import pytest

import parts


def test_the_heaviest_go_first_each_to_the_part_with_the_least():
    assert parts.assign([30, 30, 30, 30, 1, 1, 1, 1], 4) == [0, 1, 2, 3, 0, 1, 2, 3]
    # 10 and 6 apart, 5 beside the 6, then 4 beside the 10: 14 / 11
    assert parts.assign([4, 10, 5, 6], 2) == [0, 0, 1, 1]
    # equal weights spread in order, as a split by count would
    assert parts.assign([1.0] * 7, 3) == [0, 1, 2, 0, 1, 2, 0]


def items():
    """Four 30 s tests that a split by count puts in one part, a module's tests sharing a fixture,
    and short tests."""
    out = [(f"tests/test_sandbox_w.py::test_a[{i}]", None) for i in range(28)]
    out += [("tests/test_qml_slots.py::test_one", "tests/test_qml_slots.py"),
            ("tests/test_qml_slots.py::test_two", "tests/test_qml_slots.py")]
    out += [(f"tests/test_trust.py::test_{i}", None) for i in range(40)]
    return out


TIMES = {f"tests/test_sandbox_w.py::test_a[{i}]": 30.0 for i in range(0, 28, 7)}
TIMES |= {"tests/test_qml_slots.py::test_one": 20.0, "tests/test_qml_slots.py::test_two": 20.0}
SHORT = {"sandbox": 0.2, "trust": 0.2, "qml": 0.2}


def test_every_test_is_in_exactly_one_part_and_a_unit_stays_whole():
    tests = items()
    chosen = [parts.choose(tests, k, 7, TIMES, SHORT) for k in range(1, 8)]
    for i, _ in enumerate(tests):
        assert sum(c[i] for c in chosen) == 1, tests[i]
    unit = [k for k, c in enumerate(chosen) for i, t in enumerate(tests) if c[i] and t[1]]
    assert len(set(unit)) == 1 and len(unit) == 2
    # the same choice every time: each part's run makes it on its own
    assert chosen == [parts.choose(tests, k, 7, TIMES, SHORT) for k in range(1, 8)]


def test_the_heavy_ones_are_spread_where_counting_put_them_together():
    tests = items()
    by_count = [sum(parts.weight(t, TIMES, SHORT) for i, (t, _) in enumerate(tests) if i % 7 == k) for k in range(7)]
    by_time = []
    for k in range(1, 8):
        keep = parts.choose(tests, k, 7, TIMES, SHORT)
        by_time.append(sum(parts.weight(t, TIMES, SHORT) for (t, _), ok in zip(tests, keep) if ok))
    assert max(by_count) > 120 and max(by_time) <= 42
    assert sum(by_time) == pytest.approx(sum(by_count))


def test_a_test_not_named_weighs_what_a_short_test_of_its_area_takes():
    assert parts.weight("tests/test_trust.py::test_new", {}, {"trust": 0.3}) == 0.3
    assert parts.weight("tests/test_trust.py::test_new", {}, {}) == parts.SHORT
    assert parts.weight("tests/test_trust.py::test_new", {"tests/test_trust.py::test_new": 4.0}, {}) == 4.0


def test_a_tests_unit_is_its_module_where_it_shares_a_module_fixture():
    class Def:
        def __init__(self, scope):
            self.scope = scope

    class Info:
        def __init__(self, *scopes):
            self.name2fixturedefs = {f"f{i}": [Def(s)] for i, s in enumerate(scopes)}

    class Item:
        def __init__(self, nodeid, info, cls=None):
            self.nodeid, self._fixtureinfo, self.cls = nodeid, info, cls

    assert parts.unit(Item("tests/test_a.py::test_x", Info("function", "session"))) is None
    assert parts.unit(Item("tests/test_a.py::test_x", Info("function", "module"))) == "tests/test_a.py"
    assert parts.unit(Item("tests/test_a.py::TestC::test_x", Info("class"), cls=object)) == "tests/test_a.py::TestC"
    assert parts.unit(Item("tests/test_a.py::test_x", None)) is None


def test_the_part_is_k_of_n():
    assert parts.parse("2/3") == (2, 3)
    for bad in ("0/3", "4/3", "3", "a/b"):
        with pytest.raises(ValueError):
            parts.parse(bad)


def test_a_run_writes_its_long_tests_by_name_and_the_short_ones_as_a_total_by_area():
    r = parts.Recorder()
    for phase in (0.5, 0.75, 0.1):      # setup, call, teardown
        r.add("tests/test_trust.py::test_long", phase)
    r.add("tests/test_trust.py::test_short", 0.25)
    r.add("tests/test_windows.py::test_other", 0.25)
    assert r.written() == {
        "trust": {"tests": {"tests/test_trust.py::test_long": 1.4}, "shortTotal": 0.25, "shortCount": 1},
        "windows": {"tests": {}, "shortTotal": 0.25, "shortCount": 1},
    }


def test_a_runs_parts_are_gathered_into_a_file_per_area(tmp_path):
    a = {"trust": {"tests": {"tests/test_trust.py::x": 3.0}, "shortTotal": 1.0, "shortCount": 4}}
    b = {"trust": {"tests": {}, "shortTotal": 1.0, "shortCount": 4},
         "windows": {"tests": {"tests/test_windows.py::y": 2.0}, "shortTotal": 0.0, "shortCount": 0}}
    found = parts.gathered([a, b])
    assert found == {"trust": {"short": 0.25, "tests": {"tests/test_trust.py::x": 3.0}},
                     "windows": {"short": parts.SHORT, "tests": {"tests/test_windows.py::y": 2.0}}}
    (tmp_path / "old.json").write_text("{}")
    parts.write(found, tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["trust.json", "windows.json"]
    assert json.loads((tmp_path / "trust.json").read_text()) == found["trust"]
    assert parts.load(tmp_path) == ({"tests/test_trust.py::x": 3.0, "tests/test_windows.py::y": 2.0},
                                    {"trust": 0.25, "windows": parts.SHORT})
    assert parts.load(tmp_path / "none") == ({}, {})


def test_the_committed_times_are_by_area_and_name_tests_of_at_least_keep_seconds():
    times, short = parts.load()
    assert set(short) <= set(parts._areas().AREAS)
    assert all(0 < s < parts.KEEP for s in short.values())
    assert all(t >= parts.KEEP and "::" in n and parts.area_of_test(n) for n, t in times.items())
    for path in parts.DURATIONS.glob("*.json"):
        d = json.loads(path.read_text())
        assert all(parts.area_of_test(n) == path.stem for n in d["tests"]), path.name
