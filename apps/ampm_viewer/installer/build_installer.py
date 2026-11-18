"""Make AMPM Viewer's installer from the app `just build` made (run by
`just installer`, which builds first).

- **Windows:** a setup made with Inno Setup 6.3+ from ``ampm-viewer.iss``:
  ``dist/ampm-viewer-v<version>-<arch>-setup.exe``. ISCC.exe is found on
  the PATH, in ``ISCC`` (its full path), or where Inno Setup installs it.
- **macOS:** a disk image to drag the app to Applications, made with the
  system's ``hdiutil``: ``dist/ampm-viewer-v<version>-<arch>.dmg``. The app
  is signed ad hoc (Apple silicon runs nothing unsigned); set
  ``AMPM_CODESIGN_IDENTITY`` to a Developer ID to sign it properly instead
  (notarising is a further step, not done here).

Usage (from apps/ampm_viewer):  python installer/build_installer.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent
sys.path.insert(0, str(APP_DIR))
import build_names

DIST = APP_DIR / "dist"


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


# -- Windows --------------------------------------------------------------
def find_iscc() -> str:
    if os.environ.get("ISCC"):
        return os.environ["ISCC"]
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return found
    for base in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(base)
        if not root:
            continue
        for sub in ("Inno Setup 6", r"Programs\Inno Setup 6"):
            exe = Path(root) / sub / "ISCC.exe"
            if exe.is_file():
                return str(exe)
    fail("Inno Setup's ISCC.exe was not found. Install Inno Setup 6.3 or later "
         "(winget install JRSoftware.InnoSetup) or set ISCC to its full path.")
    return ""


def windows() -> Path:
    source = DIST / build_names.dist_name()
    exe = source / f"{build_names.EXE_NAME}.exe"
    if not exe.is_file():
        fail(f"{exe} is missing: run `just build` first.")
    out = DIST / f"{build_names.dist_name()}-setup.exe"
    nums = ".".join(str(n) for n in build_names.version_numbers())
    defines = {
        "AppVersion": build_names.version(),
        "VersionNumbers": nums,
        "AppArch": build_names.arch(),
        "Publisher": build_names.PUBLISHER,
        "ExeName": build_names.EXE_NAME,
        "SourceDir": str(source),
        "OutputDir": str(DIST),
        "OutputBase": out.stem,
        "IconFile": str(APP_DIR / "src" / "ampm_viewer" / "assets" / "ampm.ico"),
    }
    cmd = [find_iscc(), *(f"/D{k}={v}" for k, v in defines.items()),
           str(HERE / "ampm-viewer.iss")]
    subprocess.run(cmd, check=True)
    return out


# -- macOS ----------------------------------------------------------------
def macos() -> Path:
    app = DIST / f"{build_names.APP_NAME}.app"
    if not (app / "Contents" / "MacOS" / build_names.EXE_NAME).is_file():
        fail(f"{app} is missing: run `just build` first.")
    identity = os.environ.get("AMPM_CODESIGN_IDENTITY") or "-"  # "-": ad hoc
    sign = ["codesign", "--force", "--deep", "--sign", identity]
    if identity != "-":
        sign += ["--options", "runtime", "--timestamp"]
    subprocess.run([*sign, str(app)], check=True)
    out = DIST / f"{build_names.dist_name()}.dmg"
    out.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "AMPM Viewer"
        stage.mkdir()
        # ditto keeps the bundle's symlinks, permissions and signature.
        subprocess.run(["ditto", str(app), str(stage / app.name)], check=True)
        (stage / "Applications").symlink_to("/Applications")
        subprocess.run(
            ["hdiutil", "create", "-volname",
             f"{build_names.APP_NAME} {build_names.version()}",
             "-srcfolder", str(stage), "-fs", "HFS+", "-format", "UDZO",
             "-ov", str(out)], check=True)
    return out


def main() -> None:
    if sys.platform == "win32":
        out = windows()
    elif sys.platform == "darwin":
        out = macos()
    else:
        fail("installers are made on Windows (Inno Setup) or macOS (a disk "
             "image); on Linux, run the folder `just build` makes.")
        return
    print(f"Installer: {out}")


if __name__ == "__main__":
    main()
