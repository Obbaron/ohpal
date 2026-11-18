# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AMPM Viewer (build with `just build` / `just rebuild`;
`just installer` builds it and then its setup).

Build on Windows (PowerShell): a Windows .exe must be built on Windows; a WSL
build produces a Linux binary. From the repo root:

    just setup            # once: sync the venv (uv sync --all-packages)
    just build            # runs: uv --directory apps/ampm_viewer run pyinstaller app.spec
    just installer        # build, then the setup (installer/build_installer.py)

Output: a folder, apps/ampm_viewer/dist/ampm-viewer-v<version>-<arch>/ (for
example ampm-viewer-v2.0.0-x64), holding "AMPM Viewer.exe" and its
_internal folder of libraries and data. The folder is what the installer
installs; it can also be run where it is. A folder starts much faster than a
one-file .exe, which unpacked all of itself (about 550 MB) to a temporary
folder at every start. The version is __version__ and the architecture (x64
or arm64) that of the Python running PyInstaller (see build_names.py). A
DBSCAN job the app starts is the same .exe with --dbscan-job. Paths here are
relative to this spec's folder (apps/ampm_viewer), which is where
`just build` runs it.
"""

import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)  # noqa: F821 (spec global): build_names.py beside it
import build_names  # noqa: E402

from PyInstaller.utils.hooks import collect_data_files, collect_submodules  # noqa: E402

MACOS = sys.platform == "darwin"
ICON = "src/ampm_viewer/assets/" + ("ampm.icns" if MACOS else "ampm.ico")
VERSION = build_names.version()
# The build's folder in dist (ampm-viewer-v2.0.0-x64) and the program in it.
NAME = build_names.dist_name()
EXE_NAME = build_names.EXE_NAME
_nums = build_names.version_numbers()

# The Windows file properties (Details tab): name, version, description.
# (Written into PyInstaller's build folder, ``workpath``, not the source tree.)
_version_file = Path(workpath) / "version_info.txt"  # noqa: F821 (spec global)
_version_file.parent.mkdir(parents=True, exist_ok=True)
_version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_nums}, prodvers={_nums},
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{build_names.PUBLISHER}'),
      StringStruct('FileDescription', 'AMPM Viewer'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'ampm-viewer'),
      StringStruct('LegalCopyright', 'All rights reserved'),
      StringStruct('OriginalFilename', '{EXE_NAME}.exe'),
      StringStruct('ProductName', 'AMPM Viewer'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")

# -- data files ---------------------------------------------------------
datas = []
# The app's icon, help articles, fonts and SVG icons, loaded at runtime from
# the package (Path(__file__)/assets), so they keep their package-relative
# location in the bundle.
datas += collect_data_files("ampm_viewer", includes=["assets/**/*",
                                                        "shell/assets/**/*"])
# VisPy ships GLSL shaders, fonts and data it loads at runtime.
datas += collect_data_files("vispy")

# -- hidden imports -----------------------------------------------------
hiddenimports = []
# ohpal.* is a namespace package imported lazily inside functions, so
# PyInstaller's static scan misses most of it — pull every submodule in.
hiddenimports += collect_submodules("ohpal")
# VisPy resolves its GUI backend dynamically; name the PyQt6 one explicitly.
hiddenimports += ["vispy.app.backends._pyqt6"]
# QtSvg renders the icons; keep it even if the PyQt6 hook would add it.
hiddenimports += ["PyQt6.QtSvg"]

a = Analysis(
    ["src/ampm_viewer/__main__.py"],
    pathex=[
        "src",
        "../../packages/ohpal_ampm/src",
        "../../packages/ohpal_core/src",
        "../../packages/ohpal_samples/src",
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim weight: nothing in the app uses these (should one be installed in
    # the build environment anyway).
    excludes=["tkinter", "matplotlib", "plotly", "IPython", "pytest",
              "pyarrow", "pandas"],
    noarchive=False,
)


# Qt pieces the app never loads: the translations of Qt's own dialog text (the
# app is English only) and the PDF module and its image plugin.
def _unused_qt(dest: str) -> bool:
    d = dest.replace("\\", "/")
    name = d.rsplit("/", 1)[-1]
    return (d.startswith("PyQt6/Qt6/translations/") or "Qt6Pdf" in name
            or "qpdf" in name)


a.datas = [entry for entry in a.datas if not _unused_qt(entry[0])]
a.binaries = [entry for entry in a.binaries if not _unused_qt(entry[0])]
pyz = PYZ(a.pure)

# A folder: the .exe holds only the bootloader and the scripts; the libraries
# and data files go beside it, in _internal (COLLECT), and are read in place.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app: no console window. Flip to True to see tracebacks.
    disable_windowed_traceback=False,
    icon=ICON,  # the .exe's own icon (Explorer, taskbar)
    version=str(_version_file),
)
coll = COLLECT(  # noqa: F821 (spec global)
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=NAME,
)

# macOS: the folder as an app, dist/AMPM Viewer.app (installer/build_installer.py
# puts it on a disk image). It opens .ampmplot files (a FileOpen event, see
# shell/app.py) and follows the system's light / dark appearance.
if MACOS:
    app = BUNDLE(  # noqa: F821 (spec global)
        coll,
        name=f"{build_names.APP_NAME}.app",
        icon=ICON,
        bundle_identifier="io.github.obbaron.ampmviewer",
        version=VERSION,
        info_plist={
            "CFBundleName": build_names.APP_NAME,
            "CFBundleDisplayName": build_names.APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "NSHumanReadableCopyright": "All rights reserved",
            "UTExportedTypeDeclarations": [{
                "UTTypeIdentifier": "io.github.obbaron.ampmplot",
                "UTTypeDescription": "AMPM Viewer plot",
                "UTTypeConformsTo": ["public.data"],
                "UTTypeTagSpecification": {"public.filename-extension": ["ampmplot"]},
            }],
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "AMPM Viewer plot",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Owner",
                "LSItemContentTypes": ["io.github.obbaron.ampmplot"],
            }],
        },
    )
