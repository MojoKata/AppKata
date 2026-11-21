"""Where the repository's files are as written, for a test that reads a file's text rather than
running its code: the checkout, or in a mutation run (scripts/mutate.py, docs/testing.md "Mutation
testing") the checkout the run's copy was made from, which APPKATA_WRITTEN_ROOT names.

In the copy, a mutated module's file is mutmut's: every change at once, each behind a switch, so a
test reading it reads no code that ever runs. Its tests run the copy's code; a test checking what
the source says (the documents against it, an AST walk, the addresses in it) reads it here.

    with open(written.path("src/appkata/backend.py"), encoding="utf-8") as f: ..."""

import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def root():
    """The repository's root as written."""
    return os.environ.get("APPKATA_WRITTEN_ROOT") or ROOT


def path(rel):
    """A file of the repository, by its path from the root, as written."""
    return os.path.join(root(), rel)
