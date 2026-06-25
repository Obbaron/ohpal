# ohpal/justfile

# PowerShell on Windows, sh on mac/linux
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

app_dir  := "apps/ampm_analyzer"
pkg_ampm := "packages/ohpal_ampm"

# show available recipes
default:
    @just --list

# sync venv and install all packages (editable)
setup:
    uv sync --all-packages

# check Python version, imports, and namespace resolution
verify:
    uv run --no-sync python -c "import sys,struct; assert sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64, 'Need Python 3.11 64-bit; found '+sys.version.split()[0]"
    uv run --no-sync python -c "import ohpal.ampm, ampm_analyzer.main; import ohpal; assert type(ohpal.__path__).__name__=='_NamespacePath', 'ohpal collapsed to a regular package - check for a stray src/ohpal/__init__.py'; print('verify OK -', list(ohpal.__path__))"

# launch AMPM Analyzer GUI
run:
    uv run --no-sync ampm-analyzer

# run pipeline test suite
test:
    uv --directory {{pkg_ampm}} run --no-sync python -m pytest

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