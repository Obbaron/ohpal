"""The Settings window (the gear in the title bar), laid out like Excel's
Options: categories down the left, the chosen category's settings on the
right in headed sections, and OK / Cancel at the bottom.

Nothing changes until OK: ``changes()`` lists what was changed, and the main
window applies it (``MainWindow._apply_settings``). Open buttons (a folder in
Explorer) act at once, as they change nothing.

Categories:

- **General**: the theme; the builds folder (where New and Open start); the
  recent builds list.
- **Plots**: the plot library folder; the plot style defaults saved with
  *Set as default*.
- **Macros**: the macro folder; the recent macros list.
- **Files**: where the app keeps its files (the AMPM folder), crash reports
  and settings (read-only, with Open).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .card import DraggableCard

# Mirror of derive_dialog._PRIMARY_QSS: accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)
_DIM = "color: palette(placeholder-text);"

# The categories down the left: (name, icon, one-line description).
PAGES = (
    ("General", "settings", "General options for working with AMPM Viewer."),
    ("Plots", "chart--scatter", "Where plots are kept, and how new plots look."),
    ("Macros", "play--outline", "Where macros are saved and listed from."),
    ("Files", "folder", "Where the app keeps its files."),
)
THEMES = (("auto", "Auto (follow the system)"), ("light", "Light"),
          ("dark", "Dark"))


def _heading(text: str) -> QWidget:
    """A section heading with a rule running to the right (as Excel's)."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 8, 0, 2)
    h.setSpacing(8)
    lab = QLabel(text)
    lab.setStyleSheet("font-weight: 600;")
    h.addWidget(lab)
    rule = QFrame()
    rule.setFrameShape(QFrame.Shape.HLine)
    rule.setStyleSheet("color: palette(mid);")
    h.addWidget(rule, 1)
    return w


def _note(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(_DIM)
    return lab


def open_folder(path) -> None:
    """Show a folder in Explorer / Finder (made first, if it can be)."""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


class _PathRow(QWidget):
    """A folder setting: the path, then Change... / Open / Use the default.
    ``value()`` is the folder chosen (None: the default)."""

    def __init__(self, current, default, *, chosen: bool, title: str,
                 can_change: bool = True, default_text: str = "Use the default") -> None:
        super().__init__()
        self._default = Path(default) if default else None
        self._value = Path(current) if (chosen and current) else None
        self._title = title
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 0, 0, 0)
        v.setSpacing(4)
        self.path = QLabel()
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path.setWordWrap(True)
        v.addWidget(self.path)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_change = QPushButton("Change…")
        self.btn_open = QPushButton("Open")
        self.btn_default = QPushButton(default_text)
        self.btn_change.clicked.connect(self._change)
        self.btn_open.clicked.connect(lambda: open_folder(self.shown()))
        self.btn_default.clicked.connect(self._use_default)
        for b in (self.btn_change, self.btn_open, self.btn_default):
            row.addWidget(b)
        row.addStretch(1)
        self.btn_change.setVisible(can_change)
        self.btn_default.setVisible(can_change)
        v.addLayout(row)
        self._initial = self._value
        self._sync()

    def value(self) -> Path | None:
        return self._value

    def changed(self) -> bool:
        return self._value != self._initial

    def shown(self) -> Path | None:
        return self._value or self._default

    def set_value(self, path) -> None:
        self._value = Path(path) if path else None
        self._sync()

    def _change(self) -> None:
        start = self.shown() or Path.home()
        chosen = QFileDialog.getExistingDirectory(self, self._title, str(start))
        if chosen:
            self.set_value(chosen)

    def _use_default(self) -> None:
        self.set_value(None)

    def _sync(self) -> None:
        shown = self.shown()
        text = str(shown) if shown else "Not set"
        if self._value is None and self._default is not None:
            text += "  (default)"
        self.path.setText(text)
        self.path.setToolTip(str(shown) if shown else "")
        self.btn_default.setEnabled(self._value is not None)
        self.btn_open.setEnabled(shown is not None)


class SettingsDialog(DraggableCard, QDialog):
    """Settings, Excel-Options style. ``state`` holds the current values:
    theme, macro_folder / macro_default / macro_chosen, plot_folder /
    plot_default / plot_chosen, builds_folder, recent_builds, favourites,
    recent_macros, plot_styles, data_dir, crash_dir, settings_file."""

    def __init__(self, state: dict, parent=None, *, icon_color: str = "#333",
                 page: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self._state = dict(state)
        self._clear_builds = False
        self._clear_macros = False
        self._reset_styles = False

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("SettingsCard")
        card.setStyleSheet(
            "#SettingsCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(12)

        title = QLabel("Settings")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(16)
        # Categories, down the left.
        self.nav = QListWidget()
        self.nav.setObjectName("SettingsNav")
        self.nav.setFixedWidth(160)
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.nav.setStyleSheet(
            "#SettingsNav { background: palette(alternate-base); border-radius: 6px;"
            " padding: 4px; outline: 0; }"
            "#SettingsNav::item { padding: 7px 8px; border-radius: 4px; }"
            "#SettingsNav::item:selected { background: palette(highlight);"
            " color: palette(highlighted-text); }")
        for name, icon, _intro in PAGES:
            item = QListWidgetItem(icons.icon(icon, icon_color), name, self.nav)
            item.setData(Qt.ItemDataRole.UserRole, name)
        body.addWidget(self.nav)

        self.pages = QStackedWidget()
        self._page_index: dict[str, int] = {}
        for name, _icon, intro in PAGES:
            builder = getattr(self, f"_page_{name.lower()}")
            self._page_index[name] = self.pages.addWidget(
                self._scrolled(intro, builder()))
        body.addWidget(self.pages, 1)
        lay.addLayout(body, 1)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.show_page(page or PAGES[0][0])

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setDefault(True)
        self.btn_ok.setStyleSheet(_PRIMARY_QSS)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_ok)
        buttons.addWidget(self.btn_cancel)
        lay.addLayout(buttons)
        self.resize(780, 540)

    # -- layout --------------------------------------------------------
    def _scrolled(self, intro: str, content: QWidget) -> QScrollArea:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 14, 0)
        v.setSpacing(6)
        head = QLabel(intro)
        head.setWordWrap(True)
        v.addWidget(head)
        v.addWidget(content)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return scroll

    def show_page(self, name: str) -> None:
        index = self._page_index.get(name, 0)
        self.nav.setCurrentRow(index)
        self.pages.setCurrentIndex(index)

    @staticmethod
    def _box() -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        return w, v

    # -- pages -----------------------------------------------------------
    def _page_general(self) -> QWidget:
        w, v = self._box()
        st = self._state

        v.addWidget(_heading("Appearance"))
        self._theme_group = QButtonGroup(self)
        self.theme_buttons: dict[str, QRadioButton] = {}
        for key, text in THEMES:
            rb = QRadioButton(text)
            rb.setChecked(key == st.get("theme", "auto"))
            self._theme_group.addButton(rb)
            self.theme_buttons[key] = rb
            row = QHBoxLayout()
            row.setContentsMargins(16, 0, 0, 0)
            row.addWidget(rb)
            v.addLayout(row)

        v.addWidget(_heading("Builds folder"))
        note = _note("New and Open start in the folder of the build opened "
                     "last. With no recent build, they start in this builds "
                     "folder.")
        note.setContentsMargins(16, 0, 0, 0)
        v.addWidget(note)
        builds = st.get("builds_folder")
        self.builds_row = _PathRow(builds, st.get("builds_default"),
                                   chosen=bool(builds), title="Builds folder")
        v.addWidget(self.builds_row)

        v.addWidget(_heading("Recent builds"))
        n, fav = st.get("recent_builds", 0), st.get("favourites", 0)
        self.lbl_recent_builds = _note(
            f"{n} on the File tab's Recent list, {fav} of them favourites.")
        self.lbl_recent_builds.setContentsMargins(16, 0, 0, 0)
        v.addWidget(self.lbl_recent_builds)
        self.btn_clear_builds = QPushButton("Clear the Recent list")
        self.btn_clear_builds.setToolTip("Favourites stay")
        self.btn_clear_builds.setEnabled(n > fav)
        self.btn_clear_builds.clicked.connect(self._clear_recent_builds)
        v.addLayout(self._indented(self.btn_clear_builds))
        return w

    def _page_plots(self) -> QWidget:
        w, v = self._box()
        st = self._state
        v.addWidget(_heading("Plot library"))
        note = _note("Frozen plots are saved to, and listed from, this folder. "
                     "A shared folder lets a team see each other's plots.")
        note.setContentsMargins(16, 0, 0, 0)
        v.addWidget(note)
        self.plot_row = _PathRow(st.get("plot_folder"), st.get("plot_default"),
                                 chosen=bool(st.get("plot_chosen")),
                                 title="Plot library folder")
        v.addWidget(self.plot_row)

        v.addWidget(_heading("Plot style defaults"))
        n = st.get("plot_styles", 0)
        self.lbl_styles = _note(
            f"{n} plot element{'s' if n != 1 else ''} start from a style saved "
            "with Set as default." if n else
            "New plots use the built-in look. Set as default, in a plot "
            "element's panel, saves a style for new plots.")
        self.lbl_styles.setContentsMargins(16, 0, 0, 0)
        v.addWidget(self.lbl_styles)
        self.btn_reset_styles = QPushButton("Reset to the built-in look")
        self.btn_reset_styles.setEnabled(n > 0)
        self.btn_reset_styles.clicked.connect(self._reset_plot_styles)
        v.addLayout(self._indented(self.btn_reset_styles))
        return w

    def _page_macros(self) -> QWidget:
        w, v = self._box()
        st = self._state
        v.addWidget(_heading("Macro folder"))
        note = _note("Macros are saved to, and listed on the Run menu from, "
                     "this folder. A shared folder lets a team use the same "
                     "macros.")
        note.setContentsMargins(16, 0, 0, 0)
        v.addWidget(note)
        self.macro_row = _PathRow(st.get("macro_folder"), st.get("macro_default"),
                                  chosen=bool(st.get("macro_chosen")),
                                  title="Macro folder")
        v.addWidget(self.macro_row)

        v.addWidget(_heading("Recent macros"))
        n = st.get("recent_macros", 0)
        self.lbl_recent_macros = _note(
            f"{n} on the Run menu's Recent list.")
        self.lbl_recent_macros.setContentsMargins(16, 0, 0, 0)
        v.addWidget(self.lbl_recent_macros)
        self.btn_clear_macros = QPushButton("Clear the Recent list")
        self.btn_clear_macros.setEnabled(n > 0)
        self.btn_clear_macros.clicked.connect(self._clear_recent_macros)
        v.addLayout(self._indented(self.btn_clear_macros))
        return w

    def _page_files(self) -> QWidget:
        w, v = self._box()
        st = self._state
        for heading, key, text in (
            ("AMPM folder", "data_dir",
             "Your settings, and by default the builds folder, the macro "
             "folder, the plot library and crash reports, live here."),
            ("Crash reports", "crash_dir",
             "A report is written here for each unexpected error (the newest "
             "30 are kept), with fatal.log for hard crashes."),
        ):
            v.addWidget(_heading(heading))
            note = _note(text)
            note.setContentsMargins(16, 0, 0, 0)
            v.addWidget(note)
            v.addWidget(_PathRow(st.get(key), None, chosen=True, title=heading,
                                 can_change=False))
        v.addWidget(_heading("Settings"))
        where = st.get("settings_file") or ""
        note = _note("Your settings (this window's, recent builds and macros, "
                     "plot style defaults) are kept in this file, in the AMPM "
                     "folder:")
        note.setContentsMargins(16, 0, 0, 0)
        v.addWidget(note)
        lab = QLabel(where)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lab.setContentsMargins(16, 0, 0, 0)
        v.addWidget(lab)
        return w

    @staticmethod
    def _indented(widget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(16, 0, 0, 0)
        row.addWidget(widget)
        row.addStretch(1)
        return row

    # -- staged actions ----------------------------------------------------
    def _clear_recent_builds(self) -> None:
        self._clear_builds = True
        fav = self._state.get("favourites", 0)
        self.lbl_recent_builds.setText(
            f"Cleared on OK: {fav} favourite{'s' if fav != 1 else ''} stay.")
        self.btn_clear_builds.setEnabled(False)

    def _clear_recent_macros(self) -> None:
        self._clear_macros = True
        self.lbl_recent_macros.setText("Cleared on OK.")
        self.btn_clear_macros.setEnabled(False)

    def _reset_plot_styles(self) -> None:
        self._reset_styles = True
        self.lbl_styles.setText(
            "Reset on OK: new plots use the built-in look (open plots keep "
            "theirs).")
        self.btn_reset_styles.setEnabled(False)

    # -- result ----------------------------------------------------------
    def theme(self) -> str:
        return next((k for k, rb in self.theme_buttons.items() if rb.isChecked()),
                    "auto")

    def changes(self) -> dict:
        """What OK applies: only the settings that changed."""
        out: dict = {}
        if self.theme() != self._state.get("theme", "auto"):
            out["theme"] = self.theme()
        for key, row in (("builds_folder", self.builds_row),
                         ("plot_folder", self.plot_row),
                         ("macro_folder", self.macro_row)):
            if row.changed():
                out[key] = row.value()  # None: the default (or not set)
        if self._clear_builds:
            out["clear_recent_builds"] = True
        if self._clear_macros:
            out["clear_recent_macros"] = True
        if self._reset_styles:
            out["reset_plot_styles"] = True
        return out
