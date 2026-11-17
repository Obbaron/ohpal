"""Runs each GUI scenario in ``scenarios/`` as its own process.

A scenario is a plain script that drives the real app (a QApplication, the
main window, real builds, VisPy canvases) and asserts as it goes; it exits 0
when every check passes. Each runs in a fresh process because Qt allows one
QApplication per process and the scenarios change app-wide state (settings,
fonts, OpenGL contexts). A scenario can also be run by hand:

    python apps/ampm_viewer/tests/scenarios/macro_folder.py <build folder>

Scenarios that read ``sys.argv`` get a fresh copy of the test build (see
conftest.py); the rest run without one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent / "scenarios"
SCENARIOS = sorted(p.stem for p in HERE.glob("*.py") if not p.name.startswith("_"))
TIMEOUT_S = 1200          # the DBSCAN scenarios cluster a whole build

# Need a real OpenGL context: Linux under xvfb only (skipped elsewhere).
GL = {"gl_first_plot", "plot_elements_layout"}   # (the latter: real plot sizes)


def _needs_build(name: str) -> bool:
    return "sys.argv" in (HERE / f"{name}.py").read_text(encoding="utf-8")


def _duplicated_build(build: Path) -> tuple[Path, Path]:
    """Copy of the build whose parts CSV places Part(5) four times (what
    were Part(5) to Part(8)): the duplicate-names case. Returns (the
    original CSV, the new build)."""
    csv = next(p for p in build.iterdir() if p.suffix.lower() == ".csv")
    dup = build.with_name(build.name + "-dup")
    shutil.copytree(build, dup)
    text = csv.read_text(encoding="utf-8")
    text = re.sub(r"Part\((6|7|8)\)", "Part(5)", text)
    (dup / csv.name).write_text(text, encoding="utf-8")
    return csv, dup


def _run(name: str, args: list[str], tmp_path: Path) -> None:
    cmd = [sys.executable, str(HERE / f"{name}.py"), *args]
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if name in GL:
        if not sys.platform.startswith("linux") or not shutil.which("xvfb-run"):
            pytest.skip("needs a real OpenGL context: Linux with xvfb-run")
        # Each parallel worker starts looking for a free X display at its own
        # number, so two scenarios starting together don't race for one.
        worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
        first = 99 + 10 * int("".join(ch for ch in worker if ch.isdigit()) or 0)
        cmd = ["xvfb-run", "-a", "-n", str(first), *cmd]
        env["QT_QPA_PLATFORM"] = "offscreen"
    try:
        proc = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        tail = (exc.stdout or "")[-3000:] if isinstance(exc.stdout, str) else ""
        pytest.fail(f"{name} did not finish in {TIMEOUT_S} s (a hang?)\n{tail}")
    if proc.returncode != 0:
        out = (proc.stdout + "\n" + proc.stderr).strip()
        pytest.fail(f"{name} exited {proc.returncode}\n...\n{out[-6000:]}",
                    pytrace=False)


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario(name: str, request, tmp_path: Path) -> None:
    args: list[str] = []
    if name == "parts_csv_duplicates":
        build = request.getfixturevalue("build_copy")
        csv, dup = _duplicated_build(build)
        args = [str(csv), str(dup), str(csv)]
    elif _needs_build(name):
        args = [str(request.getfixturevalue("build_copy"))]
    _run(name, args, tmp_path)
