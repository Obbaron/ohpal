"""The release script (apps/ampm_viewer/release.py): its file changes on a copy
of the real changelog, and a whole release against a throwaway GitHub stand-in
(a bare repository), without the GitHub CLI. No build or GUI needed."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent.parent
spec = importlib.util.spec_from_file_location("release", APP / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- **A thing.** It does things.

## [1.0.0] - 2026-01-01

- First.

[Unreleased]: https://github.com/o/r/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/o/r/releases/tag/v1.0.0
"""


def make_repo(root: Path, changelog: str = CHANGELOG, version: str = "1.0.0") -> None:
    init = root / "apps/ampm_viewer/src/ampm_viewer/__init__.py"
    init.parent.mkdir(parents=True)
    init.write_text(f'"""App."""\n\n__version__ = "{version}"\n', encoding="utf-8")
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    shutil.copy(APP / "release.py", root / "apps/ampm_viewer/release.py")


def test_file_changelog_and_links():
    out = release.file_changelog(CHANGELOG, "1.1.0", "2026-02-02")
    assert "## [Unreleased]\n\n## [1.1.0] - 2026-02-02\n\n### Added\n\n- **A thing.**" in out
    assert "[Unreleased]: https://github.com/o/r/compare/v1.1.0...HEAD\n" in out
    assert "[1.1.0]: https://github.com/o/r/compare/v1.0.0...v1.1.0\n" in out
    assert release.section(out, "1.1.0").startswith("### Added")
    assert release.section(out, "1.0.0") == "- First."
    assert release.unreleased(out) == ""
    with pytest.raises(release.ReleaseError, match="empty"):
        release.file_changelog(out, "1.2.0", "2026-03-03")


def test_prepare_on_the_real_changelog(tmp_path):
    """The repository's own changelog files cleanly (whatever it holds)."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if not release.unreleased(text):  # just after a release: give it an entry
        text = text.replace("## [Unreleased]\n", "## [Unreleased]\n\n- **Test.**\n", 1)
    make_repo(tmp_path, text)
    done = release.prepare("99.0.0", root=tmp_path, date="2026-12-31")
    assert len(done) == 3, done
    assert release.read_version(tmp_path / "apps/ampm_viewer/src/ampm_viewer/__init__.py") == "99.0.0"
    notes = (tmp_path / "docs/release-notes/v99.0.0.md").read_text(encoding="utf-8")
    assert notes.startswith("# AMPM Viewer 99.0.0") and "ampm-viewer-v99.0.0-x64-setup.exe" in notes
    assert release.prepare("99.0.0", root=tmp_path) == [], "a second run changes nothing"


def test_prepare_keeps_handwritten_notes(tmp_path):
    make_repo(tmp_path)
    notes = tmp_path / "docs/release-notes/v1.1.0.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("mine", encoding="utf-8")
    release.prepare("1.1.0", root=tmp_path, date="2026-02-02")
    assert notes.read_text(encoding="utf-8") == "mine"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


def test_whole_release_against_a_bare_remote(tmp_path):
    """Checks, files, commit, push, main fast-forwarded, tag pushed; no gh."""
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-q", "-b", "main", str(remote))
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    git(work, "config", "user.email", "t@example.com")
    git(work, "config", "user.name", "T")
    make_repo(work)
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "start")
    git(work, "remote", "add", "origin", str(remote))
    git(work, "push", "-q", "-u", "origin", "main")
    git(work, "checkout", "-q", "-b", "feat")
    (work / "x.txt").write_text("feature", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "feature")
    git(work, "push", "-q", "-u", "origin", "feat")

    env = dict(os.environ, PATH=os.path.dirname(shutil.which("git")))  # no gh, no uv
    script = work / "apps/ampm_viewer/release.py"

    def go(*args):
        return subprocess.run([sys.executable, str(script), *args], cwd=work, env=env,
                              text=True, capture_output=True, check=False)

    dry = go("release", "1.1.0", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert git(work, "status", "--porcelain") == "", "a dry run changes nothing"

    bad = go("release", "1.1", "--yes", "--skip-tests")
    assert bad.returncode == 1 and "must look like" in bad.stderr

    done = go("release", "1.1.0", "--yes", "--skip-tests")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "gh) isn't installed" in done.stdout
    head = git(work, "rev-parse", "HEAD")
    assert git(work, "log", "-1", "--format=%s") == "Release 1.1.0"
    assert git(remote, "rev-parse", "feat") == head
    assert git(remote, "rev-parse", "main") == head, "main fast-forwarded"
    assert git(remote, "rev-parse", "v1.1.0^{commit}") == head, "tag pushed"
    assert '__version__ = "1.1.0"' in (work / "apps/ampm_viewer/src/ampm_viewer/__init__.py").read_text()
    assert (work / "docs/release-notes/v1.1.0.md").is_file()

    again = go("release", "1.1.0", "--yes", "--skip-tests")
    assert again.returncode == 1 and "already exists" in again.stderr

    # main moved on without the branch: stop before changing anything
    git(work, "checkout", "-q", "main")
    git(work, "pull", "-q", "--ff-only")
    (work / "y.txt").write_text("hotfix", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "hotfix on main")
    git(work, "push", "-q", "origin", "main")
    git(work, "checkout", "-q", "feat")
    (work / "CHANGELOG.md").write_text(
        (work / "CHANGELOG.md").read_text().replace(
            "## [Unreleased]\n", "## [Unreleased]\n\n- **More.**\n", 1))
    git(work, "commit", "-q", "-am", "more")
    git(work, "push", "-q")
    blocked = go("release", "1.2.0", "--yes", "--skip-tests")
    assert blocked.returncode == 1 and "merge main into feat first" in blocked.stderr
    assert not git(work, "tag", "--list", "v1.2.0")
