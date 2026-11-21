"""AppKata's areas, the same as the repository's `area:` labels: which code and which test files each
holds. Coverage is totalled and floored by area (scripts/coverage_report.py), and the tests' measured
times are kept in a file per area (tests/durations/), by which CI splits tier 1 into parts
(tests/parts.py). tests/test_areas.py holds every module, script and test file to exactly one area.

    area_of_code("src/appkata_core/sync.py") == "sources"
    area_of_test("tests/test_trust.py") == "trust"

Paths are from the repository's root, with "/". A pattern is an fnmatch one."""

import fnmatch

# every Area value; docs and tooling hold tests but no code coverage.py measures
AREAS = ("trust", "sources", "install", "windows", "sandbox", "channels", "store", "ui-backend", "qml",
         "scripts", "docs", "tooling")


def _core(*names):
    return [f"src/appkata_core/{n}.py" for n in names]


def _gui(*names):
    return [f"src/appkata/{n}.py" for n in names]


CODE = {
    "trust": _core("trustfile", "gitsig", "sshsig", "nostr", "review", "scoring"),
    "sources": _core("forges", "sync", "explore", "http", "urls", "metadata", "versions"),
    "install": _core("install", "assets", "appkind", "foreign", "transfer", "desktop", "selfinstall", "autoupdate"),
    "windows": _core("windows") + _gui("winframe"),
    "sandbox": _core("sandbox", "dbus"),
    "channels": _core("channels", "flatpak", "pkgbackend", "appstream") + _gui("channelui"),
    # the core package's __init__ too: the version and AppKata's own repository, read everywhere
    "store": _core("catalog", "db", "audit", "applog", "platform", "devtools", "__init__") + _gui("prefs", "single"),
    # the GUI package's __init__ and __main__ too: how the app starts
    "ui-backend": _gui("backend", "app", "tour", "layout", "__init__", "__main__"),
    # QML, which coverage.py doesn't measure: the area holds its files, without a figure
    "qml": ["src/appkata/qml/*"],
    # the sandbox tiers' own scripts too (scripts/sandbox/), which run mostly inside the VMs and
    # containers those tiers start
    "scripts": ["scripts/*.py", "scripts/sandbox/*.py"],
}

TESTS = {
    "trust": ["tests/test_trust.py", "tests/test_version_reviews.py"],
    # URLs, versions, assets, metadata, AppKata.md and scoring: mostly the Sources' parsing
    "sources": ["tests/test_core.py", "tests/test_forges.py"],
    "install": ["tests/test_appkind.py", "tests/test_install_review.py", "tests/test_launch.py",
                "tests/test_selfinstall.py"],
    "windows": ["tests/test_windows.py"],
    "sandbox": ["tests/test_sandbox*.py", "tests/test_launcher_golden.py", "tests/test_booted.py",
                "tests/test_platform_matrix.py"],
    "channels": ["tests/test_channels.py", "tests/test_channel_ui.py"],
    # the Audit and the App log, with Explore beside them
    "store": ["tests/test_audit_log_explore.py"],
    "ui-backend": ["tests/test_tour_rules.py", "tests/test_demo_promises.py"],
    "qml": ["tests/test_qml_slots.py", "tests/test_dialog_contract.py", "tests/test_layout.py",
            "tests/test_theme_shown.py", "tests/test_time_shown.py"],
    "scripts": ["tests/test_appimage_host_libs.py", "tests/test_appimage_trim.py", "tests/test_demo_remake.py",
                "tests/test_pins_newest.py", "tests/test_publish.py", "tests/test_third_party_notices.py",
                "tests/test_coverage_report.py"],
    "docs": ["tests/test_doc_links.py", "tests/test_docs_facts.py", "tests/test_field_test_plan.py",
             "tests/test_requirements_trace.py", "tests/test_public_text.py", "tests/test_doccheck.py"],
    "tooling": ["tests/test_coworker_calls.py", "tests/test_imports_on_windows.py", "tests/test_pinned_inputs.py",
                "tests/test_scripts_executable.py", "tests/test_skip_lists.py", "tests/test_tier_args.py",
                "tests/test_parts.py", "tests/test_areas.py", "tests/test_ci_times.py",
                "tests/test_mutate.py"],
}


def _area(table, rel):
    found = [a for a, patterns in table.items() for p in patterns if fnmatch.fnmatchcase(rel, p)]
    return found[0] if len(set(found)) == 1 else None


def area_of_code(rel):
    """The area a source file or script counts in, or None (not code an area holds, or in two)."""
    return _area(CODE, rel)


def area_of_test(rel):
    """The area a test file (or a test's id, tests/test_x.py::test_y) belongs to, or None."""
    return _area(TESTS, rel.split("::")[0])
