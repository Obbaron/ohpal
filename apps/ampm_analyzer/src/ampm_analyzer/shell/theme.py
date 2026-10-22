"""Application styling.

Light-touch so it's easy to restyle. The one layout-relevant rule here is the
**subtle tint on the left-most File tab** (``QTabBar::tab:first``), per the
locked design decision — a tint, not an accent-coloured block.
"""

from __future__ import annotations

# A restrained neutral palette. Swap these for the project's own later.
BG = "#f4f5f7"
SURFACE = "#ffffff"
BORDER = "#d7dbe0"
TEXT = "#1f2328"
MUTED = "#6b7280"
ACCENT = "#3b6ea5"
FILE_TINT = "#e9eef5"  # subtle tint for the File tab

STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 13px;
}}

/* --- Tab strip (view switcher) --- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {SURFACE};
    top: -1px;
}}
QTabBar::tab {{
    background: {BG};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 6px 14px;
    margin-right: 2px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    color: {MUTED};
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {TEXT};
}}
/* The File tab, pinned left-most, distinguished by a subtle tint only. */
QTabBar::tab:first {{
    background: {FILE_TINT};
    color: {TEXT};
    font-weight: 600;
}}
QTabBar::tab:first:selected {{
    background: {SURFACE};
}}

/* --- Toolbar --- */
QToolBar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
    spacing: 3px;
    padding: 3px;
}}
QToolButton {{
    padding: 4px 8px;
    border-radius: 4px;
    color: {TEXT};
}}
QToolButton:hover {{ background: {BG}; }}
QToolButton:checked {{ background: {FILE_TINT}; }}
QToolBar QComboBox, QToolBar QSpinBox, QToolBar QDoubleSpinBox {{
    padding: 2px 4px;
    min-height: 20px;
}}
QToolBar QLabel {{ color: {MUTED}; padding: 0 2px 0 6px; }}
.ToolbarGlyph {{ font-size: 15px; padding: 4px 8px; }}

/* --- Backstage --- */
#Backstage {{ background: {SURFACE}; }}
#BackstageSidebar {{
    background: {FILE_TINT};
    border-right: 1px solid {BORDER};
}}
#BackstageSidebar QPushButton {{
    text-align: left;
    padding: 9px 16px;
    border: none;
    border-radius: 0;
    color: {TEXT};
}}
#BackstageSidebar QPushButton:hover {{ background: {SURFACE}; }}
#BackstageSidebar QPushButton[primary="true"] {{ font-weight: 600; }}
.Tile {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
.Tile:hover {{ border-color: {ACCENT}; }}
.TileTitle {{ font-size: 15px; font-weight: 600; }}
.TileSub {{ color: {MUTED}; }}
.SectionHeading {{ font-size: 18px; font-weight: 600; }}

QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}

/* --- Grid --- */
QTableView {{
    background: {SURFACE};
    gridline-color: {BORDER};
    selection-background-color: {FILE_TINT};
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {BG};
    padding: 5px 8px;
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    color: {MUTED};
    font-weight: 600;
}}

/* --- Dock --- */
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {FILE_TINT};
    padding: 6px 10px;
    border-bottom: 1px solid {BORDER};
}}
#DockBody {{ background: {SURFACE}; }}
.PanelHeading {{ font-weight: 600; color: {MUTED}; }}

/* --- Status bar --- */
QStatusBar {{
    background: {SURFACE};
    border-top: 1px solid {BORDER};
}}
QStatusBar::item {{ border: none; }}
#StatusLog {{ color: {MUTED}; }}
.StatChip {{ color: {MUTED}; padding: 0 8px; border-left: 1px solid {BORDER}; }}
"""


def apply_theme(app) -> None:
    """Apply the stylesheet to a QApplication."""
    app.setStyleSheet(STYLESHEET)
