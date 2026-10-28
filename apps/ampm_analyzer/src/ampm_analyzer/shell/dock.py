"""Side panel.

A plain widget (not a QMainWindow dock) so it can sit *inside* the central
layout, beside the content and under the tab strip and toolbar — rather than
spanning the full height up to the title bar.

Hidden by default; the window shows it only when the active surface has
relevant content (currently the Plot tab). It carries a close button and
repopulates per view. Holds the live sliders and info panels — per the locked
decision that sliders live in the panel while discrete controls live on the
toolbar. Inert: no control is connected yet.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_TITLES = {"plot": "Plot", "data": "Data"}


def _slider(lo: int, hi: int, val: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    return s


class SidePanel(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setMinimumWidth(240)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header: title + close button.
        header = QWidget()
        header.setObjectName("PanelHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(10, 6, 6, 6)
        self.title = QLabel("Panel")
        self.title.setProperty("class", "PanelHeading")
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.setToolTip("Close panel")
        close.clicked.connect(self.closed)
        h.addWidget(self.title)
        h.addStretch(1)
        h.addWidget(close)
        root.addWidget(header)

        # Body: one page per view.
        body = QWidget()
        body.setObjectName("DockBody")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        bl.addWidget(self.stack)
        root.addWidget(body, 1)

        self._pages = {"data": self._data_page(), "plot": self._plot_page()}
        for page in self._pages.values():
            self.stack.addWidget(page)

    def show_for(self, kind: str) -> None:
        page = self._pages.get(kind)
        if page is not None:
            self.stack.setCurrentWidget(page)
            self.title.setText(_TITLES.get(kind, "Panel"))

    def has_content_for(self, kind: str) -> bool:
        """Whether this surface has panel content worth auto-opening for."""
        return kind == "plot"

    # -- pages ---------------------------------------------------------
    def _data_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        heading = QLabel("Build info")
        heading.setProperty("class", "PanelHeading")
        lay.addWidget(heading)
        lay.addWidget(QLabel("No packet loaded."))
        lay.addStretch(1)
        return w

    def _plot_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        points = QGroupBox("Points")
        pf = QFormLayout(points)
        marker = QComboBox()
        marker.addItems(["disc", "square", "ring", "cross"])
        pf.addRow("Marker", marker)
        pf.addRow("Size", _slider(1, 20, 5))
        pf.addRow("Opacity", _slider(0, 100, 90))
        lay.addWidget(points)

        colour = QGroupBox("Colour")
        cf = QFormLayout(colour)
        cmap = QComboBox()
        cmap.addItems(["BlueRed", "RedBlue", "viridis", "plasma", "magma", "turbo"])
        cf.addRow("Map", cmap)
        scale = QComboBox()
        scale.addItems(["Linear", "Log"])
        cf.addRow("Scale", scale)
        cf.addRow("Min", _slider(0, 100, 0))
        cf.addRow("Max", _slider(0, 100, 100))
        lay.addWidget(colour)

        selected = QGroupBox("Selected part")
        sf = QVBoxLayout(selected)
        sf.addWidget(QLabel("Nothing selected."))
        lay.addWidget(selected)

        lay.addStretch(1)
        return w
