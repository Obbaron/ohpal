# AMPM Analyzer tests

GUI scenarios: scripts that drive the real app (the main window, real builds,
plots, macros, dialogs) and assert as they go. Each runs in its own process, on
its own copy of a test build, with settings and standard folders (Documents,
app data) redirected to a temp folder, so your real settings, macro folder and
builds are never touched.

## Running

The scenarios need a build folder. They were written against **JR299** (10
layers, 20 parts, with its parts CSV, STL and DHXML); another build will fail
the checks that count its layers or parts.

```
just test-app "C:\builds\JR299"                          # from the repo root
uv run pytest apps/ampm_analyzer/tests "--build=C:\builds\JR299"
$env:AMPM_TEST_BUILD = "C:\builds\JR299"; just test-app   # PowerShell, via the environment
```

Write `--build=PATH` as one argument (pytest reads the command line before it
knows the option). Without a build, the four scenarios that don't need one
still run and the rest are skipped with a hint.

Once per run, the build is copied and its DataStore built fresh (what a user
has after opening the build and building it with default settings); each
scenario then gets its own copy of that. A full run takes a while:
`build_lifecycle` runs DBSCAN on the whole build.

A scenario that leaves a dialog waiting for a click fails after two minutes,
naming the dialog and its text, rather than hanging.

`gl_first_plot` needs a real OpenGL context, so it runs only on Linux under
`xvfb-run` and is skipped elsewhere.

## Layout

- `scenarios/*.py`: one script per area. Run one by hand while working on it:
  `python apps/ampm_analyzer/tests/scenarios/macro_folder.py <build copy>`
  (give it a copy whose DataStore is built: scenarios write caches and
  exports into the build).
- `scenarios/_harness.py`: imported first by every scenario; the temp settings
  and folders.
- `test_scenarios.py`: runs each scenario as a test.
- `conftest.py` (here and in the app folder): the `--build` option and the
  build-copy fixture.

## Adding a scenario

Add `scenarios/<area>.py` starting with a docstring and `import _harness`,
then exit non-zero on failure (a plain `assert` does). If it needs a build,
read it from `sys.argv[1]`; the runner passes a fresh copy to any scenario that
uses `sys.argv`.
