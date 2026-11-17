"""The AMPM folder (macros, plots, crash reports) per platform; and the
settings kept under the app's old name (AMPM Analyzer) carried over once, the
old store left alone."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
from pathlib import Path
from PyQt6.QtCore import QSettings
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
assert macros.default_folder() == data / "Macros" and plot_library.default_folder() == data / "Plots"
assert crash.report_dir() == data / "crash-reports"
print("AMPM folder: %APPDATA%/AMPM, ~/Library/Application Support/AMPM, $XDG_DATA_HOME/AMPM")

# -- settings kept under the old name come across, once ------------------------
ini = _harness.ROOT / "settings"
old = QSettings(str(ini / "AMPM Analyzer.ini"), QSettings.Format.IniFormat)
old.setValue("recent/builds", '["C:/builds/JR299"]')
old.setValue("window/theme", "dark")
old.sync()

assert settings.app_settings().fileName().endswith("AMPM Viewer.ini")
assert settings.settings_file() == ini / "AMPM Viewer.ini"
assert settings.carry_over() is True
new = settings.app_settings()
assert new.value("recent/builds") == '["C:/builds/JR299"]'
assert new.value("window/theme") == "dark"
assert macros.folder() == data / "Macros" and macros.is_default_folder()
assert plot_library.folder() == data / "Plots" and plot_library.is_default_folder()
print("carried over: the settings; macros and plots in the AMPM folder")

# Once only: a later change under the new name is never overwritten.
new.setValue("window/theme", "light")
old.setValue("window/theme", "dark"); old.sync()
assert settings.carry_over() is False
assert settings.app_settings().value("window/theme") == "light"
assert (ini / "AMPM Analyzer.ini").is_file(), "the old store is left as it was"
print("only once; the old store is left alone")

# A fresh install (no old settings): nothing to carry.
(ini / "AMPM Viewer.ini").unlink(); (ini / "AMPM Analyzer.ini").unlink()
assert settings.carry_over() is False
assert macros.folder() == data / "Macros" and macros.is_default_folder()
print("fresh install: the AMPM folder")
# -- without AMPM_SETTINGS_DIR: AMPM Viewer.conf in the AMPM folder, filled
#    once from where the settings were kept before (Qt's native store) -------
import os
saved_env = os.environ.pop("AMPM_SETTINGS_DIR")
try:
    assert settings.settings_file() == data / "AMPM Viewer.conf"
    assert settings.app_settings().fileName() == str(data / "AMPM Viewer.conf")
    native = QSettings("AMPM", "AMPM Viewer")      # the store 2.0 betas used
    native.setValue("recents/projects_root", "/builds"); native.sync()
    assert str(_harness.ROOT) in native.fileName(), "the test's own home"
    assert settings.carry_over() is True
    conf = settings.app_settings()
    assert conf.value("recents/projects_root") == "/builds"
    assert (data / "AMPM Viewer.conf").is_file()
    assert settings.carry_over() is False, "once"
    assert settings.default_builds_dir() == data / "Builds"
finally:
    os.environ["AMPM_SETTINGS_DIR"] = saved_env
print("settings file: AMPM Viewer.conf in the AMPM folder, carried over from the native store")
print("ALL OK")
