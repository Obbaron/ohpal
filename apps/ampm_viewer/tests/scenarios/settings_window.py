"""The Settings window (Excel-Options style): categories on the left, headed
sections on the right, OK / Cancel. Nothing changes until OK; OK applies the
theme (kept for the next start), the builds folder, the plot library and macro
folders, clearing the recent lists (favourites stay) and resetting plot style
defaults."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QFileDialog
app = QApplication([]); app.setOrganizationName("AMPM"); app.setApplicationName("AMPM Viewer")
from ampm_viewer.shell import macros, plot_elements, plot_library, theme
from ampm_viewer.shell.recents import RecentStore
from ampm_viewer.shell.settings import app_settings, data_dir
from ampm_viewer.shell.settings_dialog import PAGES, SettingsDialog
from ampm_viewer.shell.window import MainWindow

def pump(n=20):
    for _ in range(n): app.processEvents()
def dark() -> bool:
    return QApplication.instance().palette().window().color().lightness() < 128

# A theme chosen earlier is applied at start.
app_settings().setValue("appearance/theme", "dark")
w = MainWindow(); w.resize(1200, 700); w.show(); pump()
assert w._theme_choice == "dark" and dark(), "the saved theme applies at start"

# Things to change: recent builds (one a favourite), a recent macro, a saved
# plot style default.
root = _harness.ROOT
builds = [root / n for n in ("JR1", "JR2", "JR3")]
for b in builds: b.mkdir()
rs = RecentStore()
for b in builds: rs.record(b, has_cache=True)
rs.set_favourite(builds[0], True)
mfile = root / "m.macro.json"; mfile.write_text("{}"); macros.remember(mfile)
style = dict(plot_elements.builtin_style("title")); style["size"] = 21
plot_elements.save_default("title", style)
assert plot_elements.saved_defaults() == ["title"]

dlg = w._settings_dialog(); dlg.show(); pump()
assert [dlg.nav.item(i).text() for i in range(dlg.nav.count())] == [p[0] for p in PAGES] \
    == ["General", "Plots", "Macros", "Files"]
assert dlg.nav.currentRow() == 0 and dlg.pages.currentIndex() == 0
dlg.nav.setCurrentRow(2); pump(); assert dlg.pages.currentIndex() == 2
assert dlg.theme_buttons["dark"].isChecked()
assert "3 on the File tab's Recent list, 1 of them favourites." == dlg.lbl_recent_builds.text()
assert dlg.macro_row.path.text().endswith("(default)") and not dlg.macro_row.btn_default.isEnabled()
assert dlg.btn_reset_styles.isEnabled() and dlg.btn_clear_macros.isEnabled()
assert dlg.changes() == {}, "nothing changed yet"
print("Settings: General / Plots / Macros / Files; current values shown")

# Cancel: nothing changes.
dlg.theme_buttons["light"].setChecked(True); dlg._clear_recent_builds()
assert dlg.changes() == {"theme": "light", "clear_recent_builds": True}
dlg.reject(); pump()
assert dark() and len(RecentStore().load()) == 3
print("Cancel: nothing applied")

# OK: everything applies.
team = root / "team-macros"; team.mkdir(); (team / "shared.macro.json").write_text("{}")
plots = root / "team-plots"; plots.mkdir()
picks = iter([str(team), str(plots), str(root)])
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: next(picks))
dlg = w._settings_dialog(page="Macros"); dlg.show(); pump()
assert dlg.pages.currentIndex() == 2, "opens on the page asked for"
dlg.theme_buttons["light"].setChecked(True)
dlg.macro_row.btn_change.click(); dlg.plot_row.btn_change.click(); dlg.builds_row.btn_change.click()
assert dlg.macro_row.path.text() == str(team) and dlg.macro_row.btn_default.isEnabled()
dlg.btn_clear_builds.click(); dlg.btn_clear_macros.click(); dlg.btn_reset_styles.click()
changes = dlg.changes()
assert changes == {"theme": "light", "builds_folder": root, "plot_folder": plots,
                   "macro_folder": team, "clear_recent_builds": True,
                   "clear_recent_macros": True, "reset_plot_styles": True}, changes
dlg.accept(); w._apply_settings(changes); pump()
assert not dark() and w._theme_choice == "light"
assert app_settings().value("appearance/theme") == "light"
assert macros.folder() == team and plot_library.folder() == plots
assert RecentStore().projects_root() == str(root)
left = RecentStore().load()
assert [Path(e.path) for e in left] == [builds[0].resolve()], "favourites stay"
assert macros.recent() == [] and plot_elements.saved_defaults() == []
assert plot_elements.default_style("title")["size"] != 21
assert w.log_bus.history().rstrip().endswith(
    "Settings: theme, builds folder, plot library folder, macro folder, recent "
    "builds cleared, recent macros cleared, plot style defaults reset.")
print("OK: theme, folders, recent lists and plot styles applied")

# Back to the defaults; Files shows where things are.
dlg = w._settings_dialog(page="Files"); pump()
dlg.macro_row._use_default(); dlg.plot_row._use_default(); dlg.builds_row._use_default()
assert dlg.changes() == {"plot_folder": None, "macro_folder": None, "builds_folder": None}
w._apply_settings(dlg.changes())
assert macros.is_default_folder() and plot_library.is_default_folder()
assert RecentStore().projects_root() is None
assert RecentStore().builds_folder() == data_dir() / "Builds"
assert dlg.builds_row.path.text() == f"{data_dir() / 'Builds'}  (default)"
texts = [l.text() for l in dlg.pages.widget(3).findChildren(type(dlg.lbl_styles))]
assert any(t.startswith(str(data_dir())) for t in texts), texts
from ampm_viewer.shell.settings import settings_file
assert str(settings_file()) in texts and app_settings().fileName() == str(settings_file())
print("defaults again; Files shows the AMPM folder and the settings file")

# With no recent build and no folder chosen, New and Open start in the
# default builds folder (made for them).
RecentStore().clear()
assert RecentStore().start_dir() == str(data_dir() / "Builds") and (data_dir() / "Builds").is_dir()
print("builds folder: Builds in the AMPM folder by default")

# The next start keeps the theme.
w.close(); w2 = MainWindow(); pump()
assert w2._theme_choice == "light" and not dark()
w2.close()
print("ALL OK")
