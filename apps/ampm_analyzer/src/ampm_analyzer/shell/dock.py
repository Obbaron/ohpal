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

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QStackedWidget,
    QStyle,
    QStyleOptionSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_TITLES = {"plot": "Plot", "data": "Data"}


class ValueSlider(QSlider):
    """Horizontal slider that pops a small value bubble above the handle while
    it's being changed, then hides it shortly after."""

    def __init__(self, suffix: str = "", parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._suffix = suffix
        self._bubble: QLabel | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(900)
        self._hide_timer.timeout.connect(self._hide_bubble)
        self.valueChanged.connect(self._on_value)

    def _on_value(self, _v: int) -> None:
        self._show_bubble()
        self._hide_timer.start()

    def _show_bubble(self) -> None:
        if self._bubble is None:
            self._bubble = QLabel(self)
            self._bubble.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._bubble.setStyleSheet(
                "background: rgba(28,32,38,0.92); color: #f2f4f7;"
                " border-radius: 3px; padding: 1px 5px; font-size: 11px;"
            )
        self._bubble.setText(f"{self.value()}{self._suffix}")
        self._bubble.adjustSize()
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderHandle, self,
        )
        x = handle.center().x() - self._bubble.width() // 2
        y = handle.top() - self._bubble.height() - 2
        x = max(0, min(x, self.width() - self._bubble.width()))
        self._bubble.move(x, max(0, y))
        self._bubble.show()
        self._bubble.raise_()

    def _hide_bubble(self) -> None:
        if self._bubble is not None:
            self._bubble.hide()


def _slider(lo: int, hi: int, val: int, suffix: str = "") -> ValueSlider:
    s = ValueSlider(suffix)
    s.setRange(lo, hi)
    s.setValue(val)
    return s


class SidePanel(QWidget):
    closed = pyqtSignal()
    # Plot-panel controls → active plot.
    markerSizeChanged = pyqtSignal(int)
    markerSymbolChanged = pyqtSignal(str)
    opacityChanged = pyqtSignal(int)
    colormapChanged = pyqtSignal(str)
    scaleChanged = pyqtSignal(str)
    colorMinChanged = pyqtSignal(int)
    colorMaxChanged = pyqtSignal(int)

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

    def sync_plot(self, state: dict) -> None:
        """Reflect an active plot's appearance on the controls (no re-emit)."""
        def set_slider(sl, v):
            sl.blockSignals(True)
            sl.setValue(int(v))
            sl.blockSignals(False)

        def set_combo(cb, text):
            cb.blockSignals(True)
            i = cb.findText(str(text))
            if i >= 0:
                cb.setCurrentIndex(i)
            cb.blockSignals(False)

        set_slider(self.size_slider, state.get("size", 7))
        set_slider(self.opacity_slider, state.get("opacity", 100))
        set_combo(self.marker_combo, state.get("symbol", "disc"))
        set_combo(self.map_combo, state.get("cmap", "turbo"))
        set_combo(self.scale_combo, state.get("scale", "Linear"))
        set_slider(self.min_slider, state.get("cmin", 0))
        set_slider(self.max_slider, state.get("cmax", 100))
        # Colour controls are meaningful only with a numeric colour column.
        self.colour_box.setEnabled(bool(state.get("has_color", False)))

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
        self.marker_combo = QComboBox()
        self.marker_combo.addItems(["disc", "square", "ring", "cross"])
        self.marker_combo.currentTextChanged.connect(self.markerSymbolChanged)
        pf.addRow("Marker", self.marker_combo)
        self.size_slider = _slider(1, 20, 3, " px")
        self.size_slider.valueChanged.connect(self.markerSizeChanged)
        pf.addRow("Size", self.size_slider)
        self.opacity_slider = _slider(0, 100, 100, "%")
        self.opacity_slider.valueChanged.connect(self.opacityChanged)
        pf.addRow("Opacity", self.opacity_slider)
        lay.addWidget(points)

        self.colour_box = QGroupBox("Colour")
        cf = QFormLayout(self.colour_box)
        self.map_combo = QComboBox()
        self.map_combo.addItems(
            ["BlueRed", "RedBlue", "viridis", "plasma", "magma", "turbo", "turbo_r"]
        )
        self.map_combo.currentTextChanged.connect(self.colormapChanged)
        cf.addRow("Map", self.map_combo)
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["Linear", "Log"])
        self.scale_combo.currentTextChanged.connect(self.scaleChanged)
        cf.addRow("Scale", self.scale_combo)
        self.min_slider = _slider(0, 100, 0, "%")
        self.min_slider.valueChanged.connect(self.colorMinChanged)
        cf.addRow("Min", self.min_slider)
        self.max_slider = _slider(0, 100, 100, "%")
        self.max_slider.valueChanged.connect(self.colorMaxChanged)
        cf.addRow("Max", self.max_slider)
        lay.addWidget(self.colour_box)

        selected = QGroupBox("Selected part")
        sf = QVBoxLayout(selected)
        sf.addWidget(QLabel("Nothing selected."))
        lay.addWidget(selected)

        lay.addStretch(1)
        return w
