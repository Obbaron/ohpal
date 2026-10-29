"""Application theming.

The app uses the **Fusion** style (a platform-independent drawing engine) with a
**QPalette** per theme. The palette is the single source of truth: the
stylesheet below references ``palette(...)`` roles, so it follows whichever
palette is active and never needs re-interpolating. Switching theme is just
swapping the palette.

- ``apply_theme(app, scheme)`` — sets Fusion + the scheme's palette + the QSS,
  and repolishes existing widgets (so it works at startup *and* at runtime).
- ``initial_scheme(app)`` — picks "light"/"dark" from the OS via
  ``QStyleHints.colorScheme()`` at launch.

Adding a theme (e.g. high-contrast) is just another palette builder — the style,
the stylesheet and the switch machinery don't change.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette

Role = QPalette.ColorRole
Group = QPalette.ColorGroup


def _palette(colors: dict, *, disabled_text: str, disabled_button: str) -> QPalette:
    p = QPalette()
    for role, value in colors.items():
        p.setColor(role, QColor(value))
    # Disabled group: dimmed text so greyed-out controls read correctly.
    for role in (Role.Text, Role.WindowText, Role.ButtonText):
        p.setColor(Group.Disabled, role, QColor(disabled_text))
    p.setColor(Group.Disabled, Role.Button, QColor(disabled_button))
    return p


def _light() -> QPalette:
    return _palette(
        {
            Role.Window: "#f4f5f7",          # app background
            Role.WindowText: "#1f2328",      # primary text
            Role.Base: "#ffffff",            # inputs, table, surfaces
            Role.AlternateBase: "#e9eef5",   # tints: sidebar, headers, File tab
            Role.Text: "#1f2328",
            Role.PlaceholderText: "#6b7280", # muted / secondary text
            Role.Button: "#ffffff",
            Role.ButtonText: "#1f2328",
            Role.BrightText: "#ffffff",
            Role.Highlight: "#3b6ea5",       # accent (selection, checked)
            Role.HighlightedText: "#ffffff",
            Role.Link: "#3b6ea5",
            Role.ToolTipBase: "#ffffff",
            Role.ToolTipText: "#1f2328",
            Role.Mid: "#d7dbe0",             # borders / strokes
            Role.Dark: "#b9bfc7",
            Role.Shadow: "#c9ced5",
        },
        disabled_text="#9aa1ab",
        disabled_button="#eef0f3",
    )


def _dark() -> QPalette:
    return _palette(
        {
            Role.Window: "#2b2d30",
            Role.WindowText: "#e6e6e6",
            Role.Base: "#1e1f22",
            Role.AlternateBase: "#34373b",
            Role.Text: "#e6e6e6",
            Role.PlaceholderText: "#9aa1ab",
            Role.Button: "#34373b",
            Role.ButtonText: "#e6e6e6",
            Role.BrightText: "#ffffff",
            Role.Highlight: "#3b82f6",       # brighter accent for dark
            Role.HighlightedText: "#ffffff",
            Role.Link: "#5a9bf0",
            Role.ToolTipBase: "#34373b",
            Role.ToolTipText: "#e6e6e6",
            Role.Mid: "#45494e",
            Role.Dark: "#17181a",
            Role.Shadow: "#101113",
        },
        disabled_text="#6b7280",
        disabled_button="#2b2d30",
    )


_PALETTES = {"light": _light, "dark": _dark}

# Stylesheet references palette(...) roles only, so it follows the active
# palette. Base widgets (combos, spin boxes, sliders, group boxes, line edits,
# scrollbars) are left to Fusion + the palette; only bespoke surfaces are styled.
STYLESHEET = """
QMainWindow, QWidget { font-size: 13px; }

/* --- Tab strip (view switcher) --- */
QTabBar::tab {
    background: palette(window);
    border: 1px solid palette(mid);
    border-bottom: none;
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    color: palette(placeholder-text);
}
QTabBar::tab:selected { background: palette(base); color: palette(window-text); }
/* File tab, pinned left-most, distinguished by a subtle tint only. */
QTabBar::tab:first { background: palette(alternate-base); color: palette(window-text); font-weight: 600; }
QTabBar::tab:first:selected { background: palette(base); }
/* Close button sits inside the tab (left of the label), inset from the border. */
QTabBar::close-button { subcontrol-position: left; margin: 2px 5px 2px 7px; }

/* --- Toolbar --- */
QToolBar { background: palette(base); border-bottom: 1px solid palette(mid); spacing: 3px; padding: 3px; }
QToolButton { padding: 4px 8px; border-radius: 4px; color: palette(button-text); }
QToolButton:hover { background: palette(window); }
QToolButton:checked { background: palette(alternate-base); }
QToolBar QLabel { color: palette(placeholder-text); padding: 0 2px 0 6px; }
.ToolbarGlyph { font-size: 15px; padding: 4px 8px; }

/* --- Backstage --- */
#Backstage { background: palette(base); }
#BackstageSidebar { background: palette(alternate-base); border-right: 1px solid palette(mid); }
#BackstageSidebar QPushButton { text-align: left; padding: 9px 16px; border: none; border-radius: 0; color: palette(window-text); }
#BackstageSidebar QPushButton:hover { background: palette(base); }
#BackstageSidebar QPushButton[primary="true"] { font-weight: 600; }
.Tile { background: palette(base); border: 1px solid palette(mid); border-radius: 8px; }
.Tile:hover { border-color: palette(highlight); }
.TileTitle { font-size: 15px; font-weight: 600; }
.TileSub { color: palette(placeholder-text); }
.SectionHeading { font-size: 18px; font-weight: 600; }

QPushButton { background: palette(base); border: 1px solid palette(mid); border-radius: 4px; padding: 5px 12px; }
QPushButton:hover { border-color: palette(highlight); }
QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); border-color: palette(highlight); }

/* --- Grid --- */
QTableView { background: palette(base); gridline-color: palette(mid); selection-background-color: palette(alternate-base); selection-color: palette(window-text); }
QHeaderView::section { background: palette(window); padding: 5px 8px; border: none; border-right: 1px solid palette(mid); border-bottom: 1px solid palette(mid); color: palette(placeholder-text); font-weight: 600; }

/* --- Side panel --- */
#FilterBar { background: palette(alternate-base); border-bottom: 1px solid palette(mid); }
#FilterBar .FilterChip { background: palette(base); border: 1px solid palette(mid); border-radius: 9px; }
#FilterBar .FilterChip QPushButton { border: none; background: transparent; padding: 2px 2px 2px 9px; font-size: 12px; }
#FilterBar .FilterChip QToolButton { border: none; background: transparent; padding: 2px 8px 2px 3px; }
#FilterBar .FilterChip QPushButton:hover, #FilterBar .FilterChip QToolButton:hover { color: palette(highlight); }

#SidePanel { background: palette(base); border-left: 1px solid palette(mid); }
#PanelHeader { background: palette(alternate-base); border-bottom: 1px solid palette(mid); }
#DockBody { background: palette(base); }
.PanelHeading { font-weight: 600; color: palette(placeholder-text); }

/* --- Status bar --- */
QStatusBar { background: palette(base); border-top: 1px solid palette(mid); }
QStatusBar::item { border: none; }
#StatusLog { color: palette(placeholder-text); }
.StatChip { color: palette(placeholder-text); padding: 0 8px; border-left: 1px solid palette(mid); }
"""


def icon_color(app) -> str:
    """Hex colour icons should be tinted to for the active palette."""
    return app.palette().color(Role.WindowText).name()


def initial_scheme(app) -> str:
    """Pick the launch theme from the OS preference (Qt 6.5+)."""
    try:
        if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            return "dark"
    except Exception:  # noqa: BLE001 - fall back if unavailable
        pass
    return "light"


def apply_theme(app, scheme: str = "light") -> None:
    """Apply Fusion + the scheme's palette + the stylesheet, and repolish."""
    app.setStyle("Fusion")  # fresh style; also resets palette to standard
    app.setPalette(_PALETTES.get(scheme, _light)())
    # Clearing before re-setting forces the stylesheet to be re-parsed against
    # the new palette; re-setting the identical string alone can be a no-op, so
    # the palette(...) references wouldn't pick up the new colours.
    app.setStyleSheet("")
    app.setStyleSheet(STYLESHEET)
    # Repolish existing widgets so a runtime switch repaints cleanly.
    for widget in app.allWidgets():
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
