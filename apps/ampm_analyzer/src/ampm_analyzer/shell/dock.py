"""Docked side panel.

Repopulates per active view (QStackedWidget). Holds the live sliders (point
size, opacity, colour range) and info panels — per the locked decision that
sliders live in the dock while discrete controls live on the toolbar.

Inert: sliders carry no connections yet.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


def _slider(lo: int, hi: int, val: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    return s


class Dock(QDockWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Panel", parent)
        self.setObjectName("SidePanel")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setMinimumWidth(250)

        body = QWidget()
        body.setObjectName("DockBody")
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.setWidget(body)

        self._pages = {"data": self._data_page(), "plot": self._plot_page()}
        for page in self._pages.values():
            self.stack.addWidget(page)

    def show_for(self, kind: str) -> None:
        page = self._pages.get(kind)
        if page is not None:
            self.stack.setCurrentWidget(page)

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
        pf.addRow("Size", _slider(1, 20, 5))
        pf.addRow("Opacity", _slider(0, 100, 90))
        lay.addWidget(points)

        colour = QGroupBox("Colour range")
        cf = QFormLayout(colour)
        cf.addRow("Min", _slider(0, 100, 0))
        cf.addRow("Max", _slider(0, 100, 100))
        lay.addWidget(colour)

        selected = QGroupBox("Selected part")
        sf = QVBoxLayout(selected)
        sf.addWidget(QLabel("Nothing selected."))
        lay.addWidget(selected)

        lay.addStretch(1)
        return w
