"""scripts/ci_times.py, the check on CI's times: tier 1's parts within the budget and within SPREAD of
each other, from the jobs GitHub's API lists."""

import importlib.util
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_spec = importlib.util.spec_from_file_location("ci_times", os.path.join(ROOT, "scripts", "ci_times.py"))
ct = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ct)


def job(name, start, end, conclusion="success"):
    return {"name": name, "started_at": f"2026-11-21T10:{start}Z", "completed_at": f"2026-11-21T10:{end}Z",
            "conclusion": conclusion}


def test_parts_within_the_budget_and_the_spread_pass():
    jobs = [job("tier1 1 of 3", "00:00", "02:00"), job("tier1 2 of 3", "00:00", "02:30"),
            job("tier1 3 of 3", "00:05", "02:10"), job("windows", "00:00", "03:00"),
            job("release", "00:00", "00:00", "skipped")]
    lines, todo = ct.report(jobs)
    assert todo == []
    assert lines[0] == "run: 3m00s from the first job's start to the last one's end"
    assert lines[1].split() == ["3m00s", "windows"]
    assert "tier1: 3 parts, 2m00s to 2m30s, 1.25:1 (at most 1.4:1)" in lines
    assert not any("release" in line for line in lines)


def test_a_part_past_the_budget_or_parts_too_uneven_fail():
    lines, todo = ct.report([job("tier1 1 of 2", "00:00", "05:01"), job("tier1 2 of 2", "00:00", "03:00")])
    assert todo == ["tier1 1 of 2: 5m01s, past the 5m00s budget",
                    "tier1: parts from 3m00s to 5m01s, more than 1.4:1"]
    assert any(line.endswith("tier1 1 of 2  ⚠ over budget") for line in lines)
    # a job that isn't a part has no budget here
    assert ct.report([job("windows", "00:00", "09:00")])[1] == []


def test_a_job_still_running_is_left_out():
    jobs = [job("tier1 1 of 2", "00:00", "01:00"), job("tier1 2 of 2", "00:00", "01:10"),
            {"name": "ci-times", "started_at": "2026-11-21T10:01:20Z", "completed_at": None, "conclusion": None}]
    assert ct.report(jobs)[1] == []
