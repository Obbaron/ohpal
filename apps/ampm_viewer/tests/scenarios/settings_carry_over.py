"""The app was named AMPM Analyzer before 2.0.0: at the first start as AMPM
Viewer its settings and its macro / plot folders come across, once, and the
old ones are left alone."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
from pathlib import Path
from PyQt6.QtCore import QSettings, QStandardPaths
from PyQt6.QtWidgets import QApplication
app = QApplication([]); app.setOrganizationName("AMPM"); app.setApplicationName("AMPM Viewer")
from ampm_viewer.shell import macros, plot_library, settings

ini = _harness.ROOT / "settings"
old = QSettings(str(ini / "AMPM Analyzer.ini"), QSettings.Format.IniFormat)
old.setValue("recent/builds", '["C:/builds/JR299"]')
old.setValue("window/theme", "dark")
old.sync()
docs = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
(docs / "AMPM Analyzer" / "Macros").mkdir(parents=True)
(docs / "AMPM Analyzer" / "Macros" / "cov.macro.json").write_text("{}")
(docs / "AMPM Analyzer" / "Plots").mkdir(parents=True)   # empty: not kept

assert settings.app_settings().fileName().endswith("AMPM Viewer.ini")
assert settings.carry_over() is True
new = settings.app_settings()
assert new.value("recent/builds") == '["C:/builds/JR299"]'
assert new.value("window/theme") == "dark"
assert macros.folder() == docs / "AMPM Analyzer" / "Macros", macros.folder()
assert plot_library.folder() == docs / "AMPM Viewer" / "Plots", "an empty old folder isn't kept"
print("carried over: settings, and the old macro folder (it holds macros)")

# Once only: a later change under the new name is never overwritten.
new.setValue("window/theme", "light")
old.setValue("window/theme", "dark"); old.sync()
assert settings.carry_over() is False
assert settings.app_settings().value("window/theme") == "light"
assert (ini / "AMPM Analyzer.ini").is_file(), "the old store is left as it was"
print("only once; the old store is left alone")

# A fresh install (no old settings, no old folders): nothing to carry.
(ini / "AMPM Viewer.ini").unlink(); (ini / "AMPM Analyzer.ini").unlink()
import shutil; shutil.rmtree(docs / "AMPM Analyzer")
assert settings.carry_over() is False
assert macros.folder() == docs / "AMPM Viewer" / "Macros" and macros.is_default_folder()
print("fresh install: the new defaults")
print("ALL OK")
