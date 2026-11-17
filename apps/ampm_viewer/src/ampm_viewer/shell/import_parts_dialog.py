"""Import columns from a QuantAM parts CSV onto the grid.

A tabbed picker — one tab per CSV section (Parent Parts, Strategy, Scan Volume,
…). Each tab shows the section's per-part data (support rows hidden) and a
checkable list of its columns; the user stages the columns they want and the
window joins each onto the grid, keyed on ``part_id``.

Styled as a frameless card to match the other dialogs.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .card import DraggableCard

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)

_PREVIEW_ROWS = 50  # cap the preview; parts tables are small, but be safe


class _SectionPage(QWidget):
    """One tab: a checkable column list on the left, a data preview on the right."""

    def __init__(self, body_df, on_toggle) -> None:
        super().__init__()
        self._cols = [c for c in body_df.columns if c != "part_id"]
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 8, 8, 8)

        self.cols_list = QListWidget()
        self.cols_list.setFixedWidth(220)
        for c in self._cols:
            it = QListWidgetItem(c)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.cols_list.addItem(it)
        self.cols_list.itemChanged.connect(lambda _i: on_toggle())
        row.addWidget(self.cols_list)

        # Read-only preview of the per-part body data (supports already removed).
        preview = QTableWidget()
        preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        preview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        headers = ["part_id", *self._cols]
        preview.setColumnCount(len(headers))
        preview.setHorizontalHeaderLabels(headers)
        n = min(body_df.height, _PREVIEW_ROWS)
        preview.setRowCount(n)
        rows = body_df.head(n)
        for r in range(n):
            for c, name in enumerate(headers):
                val = rows[name][r]
                preview.setItem(
                    r, c, QTableWidgetItem("" if val is None else str(val)))
        preview.resizeColumnsToContents()
        row.addWidget(preview, 1)

    def staged(self) -> list[str]:
        out = []
        for i in range(self.cols_list.count()):
            it = self.cols_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.text())
        return out


class ImportPartsCSVDialog(DraggableCard, QDialog):
    def __init__(self, sections, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import parts CSV")
        self._sections = list(sections)  # [(name, body_df)]
        self._pages: dict[str, _SectionPage] = {}

        # Frameless card.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("ImportCard")
        card.setStyleSheet(
            "#ImportCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Import parts CSV")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        self.tabs = QTabWidget()
        for name, body in self._sections:
            page = _SectionPage(body, self._update_count)
            self._pages[name] = page
            self.tabs.addTab(page, name)
        lay.addWidget(self.tabs, 1)

        self.count_label = QLabel("No columns staged.")
        self.count_label.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.count_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("Import")
        self._ok.setIcon(QIcon())
        self._ok.setDefault(True)
        self._ok.setStyleSheet(_PRIMARY_QSS)
        self._ok.setEnabled(False)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())
        lay.addWidget(buttons)

        self.resize(820, 520)

    def _update_count(self) -> None:
        n = len(self.result_values())
        self.count_label.setText(
            "No columns staged." if not n
            else f"{n} column{'s' if n != 1 else ''} staged to import.")
        self._ok.setEnabled(n > 0)

    def result_values(self) -> list[tuple[str, str]]:
        """Staged (section name, column name) pairs."""
        out = []
        for name, page in self._pages.items():
            for col in page.staged():
                out.append((name, col))
        return out
