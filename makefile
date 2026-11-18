# ohpal/makefile

ifeq ($(OS),Windows_NT)
	SHELL := powershell.exe
	.SHELLFLAGS := -NoLogo -NoProfile -Command
else
	SHELL := /bin/sh
endif

APP_DIR  := apps/ampm_viewer
PKG_AMPM := packages/ohpal_ampm

.DEFAULT_GOAL := help
.PHONY: help setup verify run test test-app build installer rebuild clean

help:
	@echo "  setup    - sync venv and install all packages (editable)"
	@echo "  verify   - checks Python version, imports, and namespace"
	@echo "  run      - launch the AMPM GUI"
	@echo "  test     - run the library tests (every package under packages/)"
	@echo "  test-app - run the app's GUI scenarios: make test-app BUILD=<build folder>"
	@echo "  build    - compile the app from $(APP_DIR)/app.spec (a folder in $(APP_DIR)/dist)"
	@echo "  installer - build, then a setup .exe (Windows, Inno Setup 6.6+) or a .dmg (macOS)"
	@echo "  clean    - remove caches and build artifacts"
	@echo "  rebuild  - clean then build"

setup:
	uv sync --all-extras

verify:
	uv run --no-sync python -c "import sys,struct; assert sys.version_info[:2]==(3,11) and struct.calcsize('P')*8==64, 'Need Python 3.11 64-bit; found '+sys.version.split()[0]"
	uv run --no-sync python -c "import ohpal.ampm, ampm_viewer.shell.app; import ohpal; assert type(ohpal.__path__).__name__=='_NamespacePath', 'ohpal collapsed to a regular package - check for a stray src/ohpal/__init__.py'; print('verify OK -', list(ohpal.__path__))"

run:
	uv run --no-sync ampm-viewer

test:
	uv --directory packages/ohpal_core run --no-sync python -m pytest
	uv --directory packages/ohpal_samples run --no-sync python -m pytest
	uv --directory $(PKG_AMPM) run --no-sync python -m pytest

# BUILD (or the AMPM_TEST_BUILD variable): the build the scenarios run on.
test-app:
	uv --directory $(APP_DIR) run --no-sync python -m pytest -n auto --dist worksteal "--build=$(BUILD)"

build:
	uv --directory $(APP_DIR) run pyinstaller --noconfirm app.spec

installer: build
	uv --directory $(APP_DIR) run --no-sync python installer/build_installer.py

rebuild:
	$(MAKE) clean
	$(MAKE) build

ifeq ($(OS),Windows_NT)
clean:
	-Remove-Item -Recurse -Force $(APP_DIR)/build, $(APP_DIR)/dist, .pytest_cache -ErrorAction SilentlyContinue
	-Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
else
clean:
	rm -rf $(APP_DIR)/build $(APP_DIR)/dist .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
endif
