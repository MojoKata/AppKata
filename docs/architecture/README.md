# AppKata: architecture

The [requirements](../requirements/README.md) say what AppKata does. These files say why a part of
it is built the way it is, where that takes more than a sentence: the design, the choices weighed
and the evidence behind them.

They are laid out as the requirements are, with A in place of R: each section has a file of its
own, `AN-name.md`, or a folder, `AN-name/README.md`, once it passes 500 lines, with a file per
first-level item named by its id. `A1.12.5` is decision 5 of the app sandboxing design. Ids are
never renumbered or reused, and the doc check (`tests/test_doccheck.py`) fails on an id that names
nothing. Like the requirements, they are written in the present tense and carry no dates or status:
how the work went is in [`../reviews/`](../reviews/), and git holds the rest.

# 1. App sandboxing (Linux)

[A1](A1-app-sandboxing/README.md): what a hostile app can do, the approach (bubblewrap, the
AppArmor profile, the launcher, Landlock later), templates, AppImages and tarballs, the screens, the
experiments, the limits, the evidence for the UI's words and the third-party claims, and the
decisions behind R17.

# 2. What a sandboxed app can see

[A2](A2-sandbox-exposure.md): everything of the host a sandboxed app can see, when, and which
requirement says so; `tests/test_sandbox_exposure.py` keeps it true.
