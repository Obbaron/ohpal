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

# compile the app from app.spec: dist/ampm-viewer-v<version>-<arch>/ (AMPM Viewer.exe + _internal; on macOS also dist/AMPM Viewer.app)
build:
    uv --directory {{app_dir}} run pyinstaller --noconfirm app.spec

# build, then the installer: a setup .exe on Windows (needs Inno Setup 6.6+), a .dmg on macOS
installer: build
    uv --directory {{app_dir}} run --no-sync python installer/build_installer.py

# the help articles' pictures, cropped and marked, from a folder of screenshots
# (what each picture is made from: SHOTS in apps/ampm_viewer/help_images.py)
help-images folder:
    uv run --no-sync python {{app_dir}}/help_images.py {{folder}}

# release a version: checks, changelog, release notes, tests, commit, push, main, tag,
# then follows GitHub's installer build and offers to publish (needs gh for that part)
# usage:  just release 2.2.0            (add --dry-run to see the plan, --yes to not be asked)
release version *flags:
    uv run --no-sync python {{app_dir}}/release.py release {{version}} {{flags}}

# only the release files: version, changelog section, docs/release-notes/v<version>.md
release-prep version:
    uv run --no-sync python {{app_dir}}/release.py prepare {{version}}

# publish the draft GitHub release once its installers are attached (needs gh)
release-publish version:
    uv run --no-sync python {{app_dir}}/release.py publish {{version}}

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
