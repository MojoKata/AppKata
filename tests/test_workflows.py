"""The workflows (.github/workflows/, docs/github-workflows.md), read as written: the artifacts each
job keeps with its run, the ones each job takes, and what the release job attaches to the draft.

How it slipped past (CR1, #592): the release job runs only on a v* tag, so no pull request runs it,
and no test read it. It took every artifact of its run (a download with no name) and attached every
file of the folder they landed in (`./*`). Those were the five release files for as long as the run
kept only the `appimage`, `windows` and `signature` artifacts, as at v0.1.0. The coverage report,
the site and the tour joined the run later, each in a pull request whose checks passed, and the next
tag would have failed after its signing was approved.

The class: what a job takes from its run, or hands on, named by something that grows as the workflow
does. The checks read every workflow for it:

- a download names what it takes (`name` or `pattern`), never the whole run;
- what it names is kept by a job it waits for (its `needs`, and theirs), so it is there by then;
- only the release job makes or changes a release, and what it gives `gh release create` is the five
  files `scripts/publish.sh verify` wants (its `expect`), each by name, from the three artifacts
  that hold them.

What no test here shows is the job running: that takes a tag (docs/github-workflows.md, "The draft,
and publishing it").

The reader below reads the workflows as this repository writes them (two-space YAML: a job's
`needs`, its steps, a step's values, its `with` and `env`, its `|` blocks) and refuses a shape it
doesn't know. A check of a workflow's triggers, permissions, environments or secrets belongs in this
file too, on `jobs()` and `steps()` or on a YAML reader in their place."""

import fnmatch
import glob
import os
import re
import shlex

import written

DOWNLOAD, UPLOAD = "actions/download-artifact", "actions/upload-artifact"
EXPR = re.compile(r"\$\{\{.*?\}\}")
# a release's files by the artifact that carries each, as the ends of AppKata-<version>-<end>
RELEASED = {"appimage": ["x86_64.AppImage", "x86_64.AppImage.sha256"], "signature": ["x86_64.AppImage.asc"],
            "windows": ["setup.exe", "setup.exe.sha256"]}
RELEASE_FLAGS = {"--draft", "--verify-tag", "--generate-notes"}
RELEASE_VALUED = {"--repo", "--title"}


def _read(rel):
    with open(written.path(rel), encoding="utf-8") as f:
        return f.read()


def workflows():
    """{file name: text} of every workflow."""
    found = sorted(glob.glob(os.path.join(written.root(), ".github", "workflows", "*.y*ml")))
    return {os.path.basename(p): _read(os.path.relpath(p, written.root())) for p in found}


# --- the reader -----------------------------------------------------------------------------------


def _scalar(value):
    value = re.sub(r"(^|\s+)#.*$", "", value).strip()       # less a comment after it
    if len(value) > 1 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


def jobs(text):
    """{job: its lines}, in the workflow's order."""
    lines = text.splitlines()
    out, name = {}, None
    for line in lines[lines.index("jobs:") + 1:]:
        assert not re.match(r"[^\s#]", line), f"after the jobs: {line}"
        m = re.fullmatch(r"  ([\w-]+):\s*(#.*)?", line)
        if m:
            name = m.group(1)
            out[name] = []
        elif name:
            out[name].append(line)
    return out


def needs(job):
    """The jobs a job names in its `needs`."""
    for line in job:
        m = re.fullmatch(r"    needs:\s*(.*)", line)
        if m:
            value = _scalar(m.group(1))
            assert re.fullmatch(r"\[[\w, -]+\]|[\w-]+", value), line        # a list on the line, or one job
            return [n.strip() for n in value.strip("[]").split(",")]
    return []


def waits_for(text):
    """{job: the jobs that have ended when it starts}: its `needs`, and theirs."""
    named = {job: needs(lines) for job, lines in jobs(text).items()}

    def before(job, seen):
        for n in named[job]:
            if n not in seen:
                seen.add(n)
                before(n, seen)
        return seen

    return {job: before(job, set()) for job in named}


def steps(job):
    """A job's steps, each {key: value}: a value, a map of values (`with`, `env`) or a `|` block's text."""
    found = []
    for line in job[job.index("    steps:") + 1:]:
        if line.startswith("      - "):
            found.append([])
            line = "        " + line[8:]
        if found:
            found[-1].append(line)
        else:
            assert not line.strip() or line.lstrip().startswith("#"), line
    return [_step(lines) for lines in found]


def _step(lines):
    step, key, block = {}, None, None       # block: the lines of the `|` block being read, and its key's depth
    for line in lines:
        depth = len(line) - len(line.lstrip())
        if block and (not line.strip() or depth > block[1]):
            block[0].append(line[block[1] + 2:])
            continue
        block = None
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.fullmatch(r"([\w-]+):(?:\s+(.*))?", line.strip())
        assert m and depth in (8, 10), f"a step's line the reader doesn't know: {line}"
        name, value = m.group(1), _scalar(m.group(2) or "")
        if depth == 8:
            key, into = name, step
        else:
            assert isinstance(step.get(key), dict), f"a step's line the reader doesn't know: {line}"
            into = step[key]
        if value in ("|", "|-", ">", ">-"):
            into[name] = []
            block = (into[name], depth)
        elif value == "" and depth == 8:
            into[name] = {}
        else:
            into[name] = value
    text = lambda v: "\n".join(v) if isinstance(v, list) else v           # noqa: E731
    return {k: {n: text(x) for n, x in v.items()} if isinstance(v, dict) else text(v) for k, v in step.items()}


def _uses(step, action):
    return step.get("uses", "").split("@")[0] == action


def uploads(text):
    """[(job, artifact, path)]: what each job keeps with its run. An upload with no name is `artifact`,
    or its file's own name when it is kept unzipped (`archive: false`)."""
    out = []
    for job, lines in jobs(text).items():
        for step in steps(lines):
            if _uses(step, UPLOAD):
                w = step["with"]
                unnamed = os.path.basename(w["path"]) if w.get("archive") == "false" else "artifact"
                out.append((job, w.get("name") or unnamed, w["path"]))
    return out


def downloads(text):
    """[(job, the download's `with`)]: what each job takes."""
    return [(job, step.get("with", {})) for job, lines in jobs(text).items() for step in steps(lines)
            if _uses(step, DOWNLOAD)]


# --- the checks -----------------------------------------------------------------------------------


def whole_run_downloads(text):
    """The jobs with a download that names nothing: no name, and no pattern or one that starts with
    no name (`*`, `?*`, `[a-z]*`, an expression). It takes every artifact the run holds when it starts,
    or as good as, so whatever a later job keeps."""
    return [job for job, w in downloads(text)
            if not (w.get("name") or re.match(r"[^*?\[]", EXPR.sub("*", w.get("pattern", ""))))]


def out_of_reach(text):
    """The downloads of an artifact kept by no job, or by a job the downloading job doesn't wait for:
    it may not be there yet, or ever. A pattern is held for every artifact it takes, so one that also
    takes the artifact of a job not waited for is found. One from another run (`run-id`) needs only a
    job of the workflow that keeps it. A pattern is read as fnmatch reads it, so one with braces
    matches nothing here: name the artifacts."""
    kept, before, found = uploads(text), waits_for(text), []
    for job, w in downloads(text):
        want = w.get("name") or w.get("pattern")
        if not want:
            continue                                        # whole_run_downloads names it
        by = {j for j, name, _ in kept if fnmatch.fnmatchcase(EXPR.sub("1", name), EXPR.sub("*", want))}
        if not (by if "run-id" in w else by and by <= before[job]):
            found.append(f"{job}: {want}")
    return found


def release_changers(text):
    """The jobs that make or change a release."""
    return [job for job, lines in jobs(text).items()
            if any(re.search(r"\bgh\s+release\s+(create|upload|edit|delete)\b", s.get("run", "")) for s in steps(lines))]


def _command(run, *start):
    """The words of each command of a script that starts with these, a line ending in `\\` joined to the next."""
    lines = run.replace("\\\n", " ").splitlines()
    return [shlex.split(line)[len(start):] for line in lines if line.split()[:len(start)] == list(start)]


def release_command(run):
    """The tag and the files a script gives `gh release create`, as written."""
    (words,) = _command(run, "gh", "release", "create")
    tag, files = None, []
    while words:
        word = words.pop(0)
        if word in RELEASE_VALUED:
            words.pop(0)
        elif word in RELEASE_FLAGS:
            pass
        elif word.startswith("-"):
            raise AssertionError(f"gh release create {word}: say here whether a value follows it")
        elif tag is None:
            tag = word
        else:
            files.append(word)
    return tag, files


def release_faults(text, publish):
    """What is wrong with a workflow's release job, by publish.sh's text. Nothing, when it takes the
    three artifacts by name into one folder, checks there each file that has a .sha256 against it,
    and gives `gh release create` the five files `publish.sh verify` expects, each by its name; and
    each artifact holds its own files of the five (RELEASED), by what its job keeps."""
    version, faults = "1.2.3", []
    expect = re.search(r'^\s*expect="([^"\n]*)"', publish, re.M).group(1).replace("$V", version).split()
    carried = {artifact: [f"AppKata-{version}-{end}" for end in ends] for artifact, ends in RELEASED.items()}
    assert sorted(n for held in carried.values() for n in held) == sorted(expect), f"RELEASED isn't publish.sh's {expect}"
    job = steps(jobs(text)["release"])
    taken = [s.get("with", {}) for s in job if _uses(s, DOWNLOAD)]
    (create,) = [s for s in job if "gh release create" in s.get("run", "")]
    run = create["run"]
    if sorted(w.get("name", "") for w in taken) != sorted(RELEASED) or any(set(w) - {"name", "path"} for w in taken):
        faults.append(f"it takes {[w.get('name') or w.get('pattern') or 'every artifact' for w in taken]}")
    if {w.get("path") for w in taken} != {create.get("working-directory")}:
        faults.append("it attaches from a folder other than the one its downloads go to")

    def names(words):       # a script's words as file names of this version, when they are that plainly
        if "v=${GITHUB_REF_NAME#v}" not in [line.strip() for line in run.splitlines()]:
            faults.append("$v isn't the tag's version")
        out = [re.sub(r"^\./", "", w).replace("${v}", version).replace("$v", version) for w in words]
        faults.extend(f"{w} isn't a file's name" for w, n in zip(words, out) if re.search(r"[]$*?\[{}~`]", n))
        return sorted(out)

    tag, files = release_command(run)
    if tag != "$GITHUB_REF_NAME":
        faults.append(f"the release is of {tag}")
    if names(files) != sorted(expect):
        faults.append(f"it attaches {files}; publish.sh verify wants {expect}")
    for artifact, held in carried.items():      # each against its own artifact: one's glob can take another's name
        kept = [os.path.basename(p) for _, name, path in uploads(text) if name == artifact for p in path.split()]
        faults.extend(f"{artifact} doesn't hold {n}" for n in held if not any(fnmatch.fnmatchcase(n, k) for k in kept))
    checked = [w for words in _command(run[:run.index("gh release create")], "sha256sum", "-c") for w in words]
    if names(checked) != sorted(n for n in expect if n.endswith(".sha256")):
        faults.append(f"before the release it checks {checked}")
    return list(dict.fromkeys(faults))


# --- the workflows --------------------------------------------------------------------------------


def test_the_reader_reads_every_job_and_every_artifact_step():
    found = workflows()
    assert set(found) >= {"ci.yml", "mutate.yml"}
    for name, text in found.items():
        assert len(jobs(text)) == len(re.findall(r"^  [\w-]+:", text[text.index("\njobs:\n"):], re.M)) > 0, name
        assert len(uploads(text)) == text.count(f"uses: {UPLOAD}@"), name
        assert len(downloads(text)) == text.count(f"uses: {DOWNLOAD}@"), name
    ci = found["ci.yml"]
    assert ("appimage", "appimage", "releases/AppKata-*-x86_64.AppImage*") in uploads(ci)
    assert ("tour", "tour.html", "build/tour.html") in uploads(ci)                  # the one kept unzipped
    assert ("tier1", "coverage-data-${{ matrix.part }}", "build/tier1/coverage/") in uploads(ci)
    assert ("coverage", {"pattern": "coverage-data-*", "path": "build/coverage-data", "merge-multiple": "true"}) in downloads(ci)
    assert needs(jobs(ci)["release"]) == ["sign"] and needs(jobs(ci)["tour"]) == []
    assert waits_for(ci)["release"] >= {"sign", "version", "ci", "appimage", "windows", "tier1"}
    assert needs(jobs(found["mutate.yml"])["mutate"]) == ["plan"]
    cache = steps(jobs(ci)["tier1"])[1]
    assert cache["with"]["path"] == "build/appimage-cache\nbuild/pyside-*" and cache["if"] == "github.ref_type != 'tag'"


def test_a_download_names_what_it_takes_and_a_job_it_waits_for_keeps_it():
    for name, text in workflows().items():
        assert whole_run_downloads(text) == [], f"{name}: a download of every artifact of the run"
        assert out_of_reach(text) == [], f"{name}: a download of what no job before it keeps"


def test_the_release_job_attaches_the_five_files_publish_verifies_from_the_three_artifacts():
    found = workflows()
    assert release_faults(found["ci.yml"], _read("scripts/publish.sh")) == []
    for name, text in found.items():
        assert release_changers(text) == (["release"] if name == "ci.yml" else []), name


# the release job as it was until CR1's #592: every artifact of the run, and every file of the folder
AS_IT_WAS = """\
  release:
    if: github.ref_type == 'tag'
    needs: [sign]
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333  # v8.0.2
        with:
          path: out
          merge-multiple: true
      - working-directory: out
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          ls -l
          sha256sum -c ./*.sha256
          gh release create "$GITHUB_REF_NAME" --repo "$GITHUB_REPOSITORY" --draft --verify-tag \\
            --title "AppKata ${GITHUB_REF_NAME#v}" --generate-notes ./*
"""


def _changed(text, old, new):
    assert text.count(old) == 1, f"the workflow has this {text.count(old)} times: {old}"
    return text.replace(old, new)


def test_the_checks_find_each_fault():
    ci, publish = workflows()["ci.yml"], _read("scripts/publish.sh")
    faults = lambda text: " | ".join(release_faults(text, publish))      # noqa: E731

    # as it was: the run's every artifact, and the folder's every file
    was = re.sub(r"(?ms)^  release:\n.*?(?=^  \S|\Z)", lambda m: AS_IT_WAS, ci)
    assert was != ci and whole_run_downloads(was) == ["release"]
    assert "it takes ['every artifact']" in faults(was) and "./* isn't a file's name" in faults(was)
    assert "it attaches ['./*']" in faults(was) and "before the release it checks ['./*.sha256']" in faults(was)
    # the finding's shorter way, which still brings every artifact to the job that may write releases
    glob_only = was.replace("--generate-notes ./*", "--generate-notes ./AppKata-*")
    assert whole_run_downloads(glob_only) == ["release"] and "./AppKata-* isn't a file's name" in faults(glob_only)
    # every artifact, by a pattern
    star = _changed(was, "          path: out\n          merge-multiple: true\n",
                    "          pattern: \"*\"\n          path: out\n          merge-multiple: true\n")
    assert whole_run_downloads(star) == ["release"] and "it takes ['*']" in faults(star)
    # and by a pattern that starts with no name, however it is spelt
    for pattern in ("?*", "[a-z]*", "${{ matrix.any }}"):
        broad = _changed(ci, "          name: coverage\n          path: build/coverage\n",
                         f"          pattern: \"{pattern}\"\n          path: build/coverage\n")
        assert whole_run_downloads(broad) == ["site"], pattern
    # a pattern that takes what its job waits for, and with it the artifact of a job it doesn't wait for
    assert out_of_reach(_changed(ci, "          name: site\n          path: site\n",
                                 "          pattern: si*\n          path: site\n")) == ["pages: si*"]

    # an artifact of a job the release doesn't wait for, and one no job keeps
    tour = _changed(ci, "          name: signature\n          path: out\n", "          name: tour\n          path: out\n")
    assert out_of_reach(tour) == ["release: tour"] and "it takes ['appimage', 'windows', 'tour']" in faults(tour)
    renamed = _changed(ci, "          name: appimage\n          path: releases/", "          name: linux\n          path: releases/")
    assert out_of_reach(renamed) == ["sign: appimage", "release: appimage"]
    assert "appimage doesn't hold AppKata-1.2.3-x86_64.AppImage" in faults(renamed)
    assert out_of_reach(_changed(ci, "    needs: [sign]\n", "    needs: [version]\n")) == [
        "release: appimage", "release: windows", "release: signature"]
    assert out_of_reach(_changed(ci, "    needs: [coverage, tour]\n", "    needs: [coverage]\n")) == ["site: tour"]
    # a fourth artifact beside the three, and a download into another folder
    fourth = _changed(ci, "          name: signature\n          path: out\n",
                      "          name: signature\n          path: out\n"
                      "      - uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333\n"
                      "        with:\n          name: coverage\n          path: out\n")
    assert out_of_reach(fourth) == [] and "'coverage']" in faults(fourth)
    assert "a folder other than" in faults(_changed(ci, "          name: windows\n          path: out\n",
                                                    "          name: windows\n          path: win\n"))

    # a sixth file, a file short, a file no artifact holds, another version's, and a checksum unchecked
    last = '"AppKata-$v-setup.exe" "AppKata-$v-setup.exe.sha256"\n'
    assert "it attaches [" in faults(_changed(ci, last, last[:-1] + " durations.json\n"))
    assert "it attaches [" in faults(_changed(ci, last, '"AppKata-$v-setup.exe"\n'))
    assert "$OTHER-setup.exe isn't a file's name" in faults(_changed(ci, last, last.replace("$v-setup.exe\"", "$OTHER-setup.exe\"", 1)))
    assert "$v isn't the tag's version" in faults(_changed(ci, "          v=${GITHUB_REF_NAME#v}\n", "          v=$GITHUB_REF_NAME\n"))
    assert "the release is of v1" in faults(_changed(ci, 'gh release create "$GITHUB_REF_NAME"', "gh release create v1"))
    moved = _changed(ci, "          path: releases/AppKata-*-setup.exe*\n", "          path: releases/Setup-*.exe*\n")
    assert "windows doesn't hold AppKata-1.2.3-setup.exe" in faults(moved)
    unchecked = _changed(ci, ' "AppKata-$v-setup.exe.sha256"\n          gh release create', "\n          gh release create")
    assert "before the release it checks ['AppKata-$v-x86_64.AppImage.sha256']" in faults(unchecked)
    # the signature's artifact without the .asc, whose name the appimage's glob takes too: the sign job
    # still ends well on the second, and the release job would be the one to fail, after the signing
    for path in ("out/signature.sig", "out/AppKata-*-x86_64.AppImage"):
        unsigned = _changed(ci, "          path: out/AppKata-*-x86_64.AppImage.asc\n", f"          path: {path}\n")
        assert faults(unsigned) == "signature doesn't hold AppKata-1.2.3-x86_64.AppImage.asc"
    assert faults(_changed(ci, "          path: releases/AppKata-*-x86_64.AppImage*\n",
                           "          path: releases/AppKata-*-x86_64.AppImage\n")) == "appimage doesn't hold AppKata-1.2.3-x86_64.AppImage.sha256"

    # a release changed by another job
    upload = _changed(ci, "          f=$(echo AppKata-*-x86_64.AppImage)\n",
                      "          f=$(echo AppKata-*-x86_64.AppImage)\n          gh release upload \"$GITHUB_REF_NAME\" \"$f\"\n")
    assert release_changers(upload) == ["sign", "release"]
