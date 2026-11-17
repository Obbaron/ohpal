# ohpal/justfile

# PowerShell on Windows, sh on mac/linux
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

app_dir  := "apps/ampm_viewer"
pkg_ampm := "packages/ohpal_ampm"

data_dir := "data"
tmpl_dir := "data/templates"

# show available recipes
default:
    @just --list

# sync venv and install all packages (editable)
setup:
    uv sync --all-packages

# generate a samples-template workbook per build found under the data dir
# usage:  just templates                 (data -> data/templates)
#         just templates mydata out/dir   (override either path)
templates data=data_dir out=tmpl_dir:
    uv run --no-sync python -m ohpal.ampm.batch {{data}} {{out}}

# check Python version, imports, and namespace resolution
verify:
    uv run --no-sync python -c "import sys,struct; assert sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64, 'Need Python 3.11 64-bit; found '+sys.version.split()[0]"
    uv run --no-sync python -c "import ohpal.ampm, ampm_viewer.shell.app; import ohpal; assert type(ohpal.__path__).__name__=='_NamespacePath', 'ohpal collapsed to a regular package - check for a stray src/ohpal/__init__.py'; print('verify OK -', list(ohpal.__path__))"

# launch AMPM Viewer GUI
run:
    uv run --no-sync ampm-viewer

# run the library tests (every package under packages/)
test:
    uv --directory packages/ohpal_core run --no-sync python -m pytest
    uv --directory packages/ohpal_samples run --no-sync python -m pytest
    uv --directory {{pkg_ampm}} run --no-sync python -m pytest

# usage:  just test-app "C:\builds\JR299"   (or set AMPM_TEST_BUILD and run: just test-app)
# run the app's GUI scenarios on a build folder (written against JR299), several at once
test-app build=env_var_or_default("AMPM_TEST_BUILD", ""):
    uv --directory {{app_dir}} run --no-sync python -m pytest -n auto --dist worksteal "--build={{build}}"

# library tests, then the GUI scenarios
test-all build=env_var_or_default("AMPM_TEST_BUILD", ""): test (test-app build)

# compile binary from app.spec
build:
    uv --directory {{app_dir}} run pyinstaller app.spec

# clean then build
rebuild: clean build

# remove caches and build artifacts
clean:
    #!python
    import shutil, pathlib
    for p in ["{{app_dir}}/build", "{{app_dir}}/dist", ".pytest_cache"]:
        shutil.rmtree(p, ignore_errors=True)
    for d in pathlib.Path(".").rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
