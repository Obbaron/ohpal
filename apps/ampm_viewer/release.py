"""Release AMPM Viewer: everything from "the work is pushed" to "the installers
are on GitHub", run by ``just release <version>``.

    just release 2.2.0            the whole release, step by step (asks before
                                  each step that changes the repository)
    just release-prep 2.2.0       only the files: version, changelog, notes
    just release-publish 2.2.0    publish the draft release

Steps of ``release`` (stops at the first problem; nothing is pushed before the
tests pass):

1. **Checks.** The version is X.Y.Z and newer than the app's; its tag exists
   neither here nor on GitHub; nothing is uncommitted; the branch is pushed
   and up to date; the changelog's Unreleased section has entries; ``main``
   can fast-forward to this commit.
2. **Files** (``prepare``): ``__version__``; the changelog's Unreleased
   entries filed under ``## [X.Y.Z] - <today>`` with its compare link;
   ``docs/release-notes/vX.Y.Z.md`` (the release page's text) made from that
   section, unless you have written one.
3. **Tests**: the library tests, and the GUI scenarios when a build is given
   (``--build`` or ``AMPM_TEST_BUILD``).
4. **Git**: commit "Release X.Y.Z", push the branch, fast-forward ``main`` on
   GitHub to it, tag ``vX.Y.Z`` and push the tag. The tag starts the Release
   workflow (``.github/workflows/release.yml``), which builds the Windows
   setup and the macOS disk image and attaches them to a draft release.
5. **Wait and publish** (needs the GitHub CLI, ``gh``, signed in): follows
   the workflow run, then shows the draft and asks whether to publish it.
   Without ``gh`` it says where to look instead.

Options: ``--yes`` (don't ask), ``--dry-run`` (say what would happen, change
nothing), ``--skip-tests``, ``--no-main`` (leave ``main`` alone),
``--build PATH``. Standard library only; run from anywhere in the repo.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent           # apps/ampm_viewer
ROOT = HERE.parent.parent                        # the repository
INIT = HERE / "src" / "ampm_viewer" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
NOTES_DIR = ROOT / "docs" / "release-notes"
WORKFLOW = "release.yml"
MAIN = "main"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ReleaseError(Exception):
    """A check failed: the message says what and how to fix it."""


# -- the files (pure: testable on copies) -----------------------------------
def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(n) for n in v.split("."))


def read_version(init: Path = INIT) -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
    if not m:
        raise ReleaseError(f"no __version__ in {init}")
    return m.group(1)


def set_version(version: str, init: Path = INIT) -> None:
    text = init.read_text(encoding="utf-8")
    new, n = re.subn(r'(__version__\s*=\s*")[^"]+(")', rf"\g<1>{version}\g<2>", text, count=1)
    if n != 1:
        raise ReleaseError(f"no __version__ in {init}")
    init.write_text(new, encoding="utf-8")


def unreleased(changelog_text: str) -> str:
    """The Unreleased section's entries (may be "")."""
    m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[)", changelog_text,
                  re.DOTALL | re.MULTILINE)
    if not m:
        raise ReleaseError("CHANGELOG.md has no '## [Unreleased]' section "
                           "followed by a released version")
    return m.group(1).strip()


def section(changelog_text: str, version: str) -> str:
    """A released version's entries, without its heading."""
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)",
                  changelog_text, re.DOTALL | re.MULTILINE)
    return m.group(1).strip() if m else ""


def file_changelog(changelog_text: str, version: str, date: str) -> str:
    """The Unreleased entries filed under ``## [version] - date``, and the
    compare links brought up to date."""
    body = unreleased(changelog_text)
    if not body:
        raise ReleaseError("the changelog's Unreleased section is empty: add "
                           "what changed before releasing")
    text = re.sub(r"^## \[Unreleased\][^\n]*\n.*?(?=^## \[)",
                  f"## [Unreleased]\n\n## [{version}] - {date}\n\n{body}\n\n",
                  changelog_text, count=1, flags=re.DOTALL | re.MULTILINE)
    link = re.search(r"^\[Unreleased\]: (\S+)/compare/(v[^.\s]+[^\s]*?)\.\.\.HEAD$",
                     text, re.MULTILINE)
    if link:
        base, prev = link.group(1), link.group(2)
        text = text.replace(
            link.group(0),
            f"[Unreleased]: {base}/compare/v{version}...HEAD\n"
            f"[{version}]: {base}/compare/{prev}...v{version}", 1)
    return text


def release_notes(version: str, entries: str) -> str:
    """The release page's text, from the changelog section: downloads first,
    what's new, then the first-start steps for the unsigned installers."""
    return f"""# AMPM Viewer {version}

## Download

- **Windows:** `ampm-viewer-v{version}-x64-setup.exe`. Run it to install, or to
  upgrade an earlier version in place (settings, macros and plots are kept).
- **macOS (Apple silicon):** `ampm-viewer-v{version}-arm64.dmg`. Open it and
  drag AMPM Viewer to Applications, replacing the old one.

## What's new

{entries}

## First start

Neither installer is signed yet. On Windows, if SmartScreen stops the setup,
choose **More info**, then **Run anyway**. On a Mac, the first time: macOS 15
and later, open AMPM Viewer, close the warning, then System Settings > Privacy
& Security > **Open Anyway**; macOS 14 and earlier, Control-click AMPM Viewer
in Applications and choose **Open**.

See `CHANGELOG.md` for the details.
"""


def prepare(version: str, *, root: Path = ROOT, date: str | None = None,
            dry_run: bool = False) -> list[str]:
    """Step 2: version, changelog, release notes. Returns what changed."""
    init = root / INIT.relative_to(ROOT)
    changelog = root / CHANGELOG.relative_to(ROOT)
    notes = root / NOTES_DIR.relative_to(ROOT) / f"v{version}.md"
    date = date or _dt.datetime.now().astimezone().date().isoformat()
    current = read_version(init)
    text = changelog.read_text(encoding="utf-8")
    done = []
    if current != version:
        if not dry_run:
            set_version(version, init)
        done.append(f"__version__ {current} -> {version}")
    if not section(text, version):
        new = file_changelog(text, version, date)
        if not dry_run:
            changelog.write_text(new, encoding="utf-8")
        text = new
        done.append(f"CHANGELOG.md: Unreleased filed under [{version}] - {date}")
    if not notes.exists():
        if not dry_run:
            notes.parent.mkdir(parents=True, exist_ok=True)
            notes.write_text(release_notes(version, section(text, version)),
                             encoding="utf-8")
        done.append(f"{notes.relative_to(root)} made from the changelog")
    return done


# -- git, gh and the checks ------------------------------------------------
def run(*cmd: str, check: bool = True, capture: bool = True) -> str:
    result = subprocess.run(list(cmd), cwd=ROOT, text=True,
                            capture_output=capture, check=False)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise ReleaseError(f"`{' '.join(cmd)}` failed" + (f":\n{detail}" if detail else ""))
    return (result.stdout or "").strip() if capture else ""


def git(*args: str, check: bool = True) -> str:
    return run("git", *args, check=check)


def checks(version: str, *, main: bool) -> str:
    """Step 1. Returns the branch being released."""
    if not VERSION_RE.match(version):
        raise ReleaseError(f"version must look like 2.2.0, not {version!r}")
    current = read_version()
    if version_tuple(version) < version_tuple(current):
        raise ReleaseError(f"{version} is older than the app's {current}")
    tag = f"v{version}"
    git("fetch", "--quiet", "--tags", "origin")
    if git("tag", "--list", tag):
        raise ReleaseError(f"tag {tag} already exists: released already? "
                           f"(to start over: git tag -d {tag})")
    if git("status", "--porcelain"):
        raise ReleaseError("there are uncommitted changes: commit or stash them first")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise ReleaseError("not on a branch (detached HEAD)")
    upstream = git("rev-parse", "--abbrev-ref", "@{u}", check=False)
    if not upstream:
        raise ReleaseError(f"branch {branch} isn't pushed: git push -u origin {branch}")
    git("fetch", "--quiet", "origin")
    behind = git("rev-list", "--count", "HEAD..@{u}")
    ahead = git("rev-list", "--count", "@{u}..HEAD")
    if behind != "0":
        raise ReleaseError(f"{branch} is {behind} commit(s) behind {upstream}: pull first")
    if ahead != "0":
        raise ReleaseError(f"{branch} has {ahead} unpushed commit(s): push first")
    text = CHANGELOG.read_text(encoding="utf-8")
    if not section(text, version) and not unreleased(text):
        raise ReleaseError("the changelog's Unreleased section is empty: add "
                           "what changed before releasing")
    if main and branch != MAIN:
        git("fetch", "--quiet", "origin", f"{MAIN}:refs/remotes/origin/{MAIN}")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", f"origin/{MAIN}", "HEAD"],
            cwd=ROOT, check=False).returncode == 0
        if not ancestor:
            raise ReleaseError(
                f"{MAIN} has commits that {branch} doesn't: merge {MAIN} into "
                f"{branch} first (git merge origin/{MAIN}), or release with --no-main")
    return branch


def ask(question: str, yes: bool) -> bool:
    if yes:
        print(f"{question} yes (--yes)")
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def step(title: str) -> None:
    print(f"\n== {title}")


def tests(build: str | None) -> None:
    uv = shutil.which("uv")
    if not uv:
        raise ReleaseError("uv isn't on the PATH (needed to run the tests)")
    for pkg in ("packages/ohpal_core", "packages/ohpal_samples", "packages/ohpal_ampm"):
        print(f"-- {pkg}")
        run(uv, "--directory", pkg, "run", "--no-sync", "python", "-m", "pytest", "-q",
            capture=False)
    if build:
        print(f"-- GUI scenarios on {build}")
        run(uv, "--directory", "apps/ampm_viewer", "run", "--no-sync", "python", "-m",
            "pytest", "-q", "-n", "auto", "--dist", "worksteal", f"--build={build}",
            capture=False)
    else:
        print("-- GUI scenarios skipped: no build (--build PATH or AMPM_TEST_BUILD)")


def gh_ready() -> bool:
    if not shutil.which("gh"):
        return False
    return subprocess.run(["gh", "auth", "status"], cwd=ROOT,
                          capture_output=True, check=False).returncode == 0


def wait_for_run(tag: str, timeout: float = 120) -> str | None:
    """The Release workflow run the tag started (its id), once GitHub has it."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        out = run("gh", "run", "list", "--workflow", WORKFLOW, "--limit", "10",
                  "--json", "databaseId,headBranch,event", check=False)
        try:
            for r in json.loads(out or "[]"):
                if r.get("headBranch") == tag:
                    return str(r["databaseId"])
        except ValueError:
            pass
        time.sleep(5)
    return None


def publish(version: str, yes: bool) -> None:
    tag = f"v{version}"
    if not gh_ready():
        raise ReleaseError("the GitHub CLI (gh) isn't installed or signed in: "
                           "publish the draft on GitHub's Releases page instead")
    out = run("gh", "release", "view", tag, "--json", "isDraft,url,assets,name")
    info = json.loads(out)
    names = [a["name"] for a in info.get("assets", [])]
    print(f"{info.get('name')}: {info.get('url')}")
    for n in names:
        print(f"  {n}")
    missing = [f for f in (f"ampm-viewer-{tag}-x64-setup.exe", f"ampm-viewer-{tag}-arm64.dmg")
               if f not in names]
    if missing:
        raise ReleaseError("the draft is missing " + ", ".join(missing))
    if not info.get("isDraft"):
        print("Already published.")
        return
    if ask("Publish it now (colleagues can then download it)?", yes):
        run("gh", "release", "edit", tag, "--draft=false")
        print(f"Published: {info.get('url')}")
    else:
        print(f"Left as a draft. Later: just release-publish {version}")


def release(version: str, *, yes: bool, dry_run: bool, skip_tests: bool,
            main: bool, build: str | None) -> None:
    tag = f"v{version}"
    step("1. Checks")
    branch = checks(version, main=main)
    print(f"Releasing {version} from {branch}"
          + (f", then fast-forwarding {MAIN}" if main and branch != MAIN else ""))

    step("2. Version, changelog, release notes")
    for line in prepare(version, dry_run=dry_run) or ["already prepared"]:
        print(f"  {line}")
    notes = NOTES_DIR / f"v{version}.md"
    if not dry_run and notes.exists():
        print(f"  Release page text: {notes.relative_to(ROOT)} (edit it now if you like)")

    step("3. Tests")
    if skip_tests or dry_run:
        print("skipped" + (" (--dry-run)" if dry_run else " (--skip-tests)"))
    else:
        tests(build)

    step("4. Commit, push, main, tag")
    plan = [f"commit 'Release {version}'", f"push {branch}"]
    if main and branch != MAIN:
        plan.append(f"fast-forward {MAIN} on GitHub")
    plan += [f"tag {tag}", f"push {tag} (starts the Release workflow)"]
    print("Will: " + "; ".join(plan))
    if dry_run:
        print("Dry run: nothing changed.")
        return
    if not ask("Go ahead?", yes):
        print("Stopped. The prepared files are left as they are (git diff shows them).")
        return
    git("add", str(INIT), str(CHANGELOG), str(notes))
    if git("diff", "--cached", "--name-only"):
        git("commit", "-m", f"Release {version}")
    git("push", "origin", branch)
    if main and branch != MAIN:
        git("push", "origin", f"HEAD:refs/heads/{MAIN}")
        print(f"{MAIN} now at {git('rev-parse', '--short', 'HEAD')}")
    git("tag", "-a", tag, "-m", f"AMPM Viewer {version}")
    git("push", "origin", tag)
    print(f"Pushed {tag}.")

    step("5. Installers and publishing")
    if not gh_ready():
        print("The GitHub CLI (gh) isn't installed or signed in, so follow it on "
              "GitHub: the Actions tab builds the installers (10 to 15 minutes), "
              "then publish the draft on the Releases page.")
        return
    run_id = wait_for_run(tag)
    if run_id is None:
        print("The workflow run hasn't appeared yet: see the Actions tab. "
              f"Then: just release-publish {version}")
        return
    print(f"Following the Release workflow (run {run_id}); this takes 10 to 15 minutes.")
    result = subprocess.run(["gh", "run", "watch", run_id, "--exit-status",
                             "--interval", "30"], cwd=ROOT, check=False)
    if result.returncode != 0:
        raise ReleaseError(f"the Release workflow failed: gh run view {run_id} --log-failed; "
                           f"fix it, then re-run it from the Actions tab and "
                           f"run: just release-publish {version}")
    publish(version, yes)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="release", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("release", "prepare", "publish"):
        s = sub.add_parser(name)
        s.add_argument("version")
        s.add_argument("--yes", "-y", action="store_true", help="don't ask")
        if name != "publish":
            s.add_argument("--dry-run", action="store_true",
                           help="say what would happen, change nothing")
        if name == "release":
            s.add_argument("--skip-tests", action="store_true")
            s.add_argument("--no-main", action="store_true",
                           help=f"don't fast-forward {MAIN}")
            s.add_argument("--build", default=os.environ.get("AMPM_TEST_BUILD") or None,
                           help="a build folder for the GUI scenarios")
    a = p.parse_args(argv)
    version = a.version.lstrip("v")
    try:
        if a.command == "prepare":
            if not VERSION_RE.match(version):
                raise ReleaseError(f"version must look like 2.2.0, not {version!r}")
            for line in prepare(version, dry_run=a.dry_run) or ["already prepared"]:
                print(line)
        elif a.command == "publish":
            publish(version, a.yes)
        else:
            release(version, yes=a.yes, dry_run=a.dry_run, skip_tests=a.skip_tests,
                    main=not a.no_main, build=a.build)
    except ReleaseError as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
