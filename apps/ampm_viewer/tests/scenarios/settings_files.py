"""Where the app keeps its files: the AMPM folder per platform, with the
settings file (ampm-viewer.conf), the default builds folder, the macro folder,
the plot library and crash reports in it."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
app = QApplication([]); app.setOrganizationName("AMPM"); app.setApplicationName("AMPM Viewer")
from ampm_viewer.shell import crash, macros, plot_library, settings

# -- where the AMPM folder is ---------------------------------------------
home = Path("/home/u")
assert settings.default_data_dir("win32", {"APPDATA": r"C:\Users\u\AppData\Roaming"}, home) \
    == Path(r"C:\Users\u\AppData\Roaming") / "AMPM"
assert settings.default_data_dir("darwin", {}, home) == home / "Library" / "Application Support" / "AMPM"
assert settings.default_data_dir("linux", {"XDG_DATA_HOME": "/data/u"}, home) == Path("/data/u/AMPM")
assert settings.default_data_dir("linux", {}, home) == home / ".local" / "share" / "AMPM"
data = _harness.ROOT / "data" / "AMPM"
assert settings.data_dir() == data, "AMPM_DATA_DIR overrides it"
print("AMPM folder: %APPDATA%/AMPM, ~/Library/Application Support/AMPM, $XDG_DATA_HOME/AMPM")

# -- what lives in it ------------------------------------------------------
assert macros.default_folder() == data / "Macros" and macros.is_default_folder()
assert plot_library.default_folder() == data / "Plots" and plot_library.is_default_folder()
assert settings.default_builds_dir() == data / "Builds"
assert crash.report_dir() == data / "crash-reports"
print("Macros, Plots, Builds and crash-reports in the AMPM folder")

# -- the settings file: ampm-viewer.conf there (the tests' own INI here) -------
ini = _harness.ROOT / "settings"
assert settings.settings_file() == ini / "AMPM Viewer.ini"
assert settings.app_settings().fileName() == str(ini / "AMPM Viewer.ini")
saved_env = os.environ.pop("AMPM_SETTINGS_DIR")
try:
    assert settings.settings_file() == data / "ampm-viewer.conf"
    s = settings.app_settings()
    assert s.fileName() == str(data / "ampm-viewer.conf")
    s.setValue("appearance/theme", "dark"); s.sync()
    assert (data / "ampm-viewer.conf").is_file()
    assert "theme=dark" in (data / "ampm-viewer.conf").read_text()
    assert settings.app_settings().value("appearance/theme") == "dark"
finally:
    os.environ["AMPM_SETTINGS_DIR"] = saved_env
print("settings: ampm-viewer.conf in the AMPM folder")
print("ALL OK")
