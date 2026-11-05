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
    QLineEdit,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyleOptionSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .widgets import fix_combo


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
    # Data-panel (column info) → the data tab.
    columnRenamed = pyqtSignal(str, str)   # (old display name, new name)
    sigFigsChanged = pyqtSignal(str, int)  # (column, significant figures)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setMinimumWidth(240)
        self._col = None  # the column the data page is currently showing

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # No in-panel header: the toolbar's panel toggle is the close control.
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

    def has_content_for(self, kind: str) -> bool:
        """Whether this surface has panel content worth auto-opening for."""
        return kind == "plot"

    # -- pages ---------------------------------------------------------
    def _data_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        self.col_heading = QLabel("Column")
        self.col_heading.setProperty("class", "PanelHeading")
        lay.addWidget(self.col_heading)

        # Hint shown until a column is double-clicked.
        self.col_hint = QLabel("Double-click a column to inspect it.")
        self.col_hint.setWordWrap(True)
        self.col_hint.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.col_hint)

        # The info form (hidden until a column is selected).
        self.col_form_box = QWidget()
        form = QFormLayout(self.col_form_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.col_name_edit = QLineEdit()
        self.col_name_edit.setPlaceholderText("column name")
        self.col_name_edit.editingFinished.connect(self._emit_rename)
        form.addRow("Name", self.col_name_edit)
        self.col_rows = QLabel("—")
        form.addRow("Rows", self.col_rows)
        self.col_type = QLabel("—")
        form.addRow("Type", self.col_type)
        self.col_sig_row = QWidget()
        sig_h = QHBoxLayout(self.col_sig_row)
        sig_h.setContentsMargins(0, 0, 0, 0)
        self.col_sig = QSpinBox()
        self.col_sig.setRange(1, 12)
        self.col_sig.setValue(4)
        self.col_sig.valueChanged.connect(self._emit_sigfigs)
        sig_h.addWidget(self.col_sig)
        sig_h.addStretch(1)
        self.col_sig_label = QLabel("Sig figs")
        form.addRow(self.col_sig_label, self.col_sig_row)
        self.col_form_box.setVisible(False)
        lay.addWidget(self.col_form_box)

        lay.addStretch(1)
        return w

    # -- data page (column info) ---------------------------------------
    def show_column_info(self, info: dict | None) -> None:
        """Populate the data page from a column's info dict (or clear it)."""
        if not info:
            self._col = None
            self.col_heading.setText("Column")
            self.col_hint.setVisible(True)
            self.col_form_box.setVisible(False)
            return
        self._col = info["name"]
        self.col_heading.setText(info["name"])
        self.col_hint.setVisible(False)
        self.col_form_box.setVisible(True)
        self.col_name_edit.blockSignals(True)
        self.col_name_edit.setText(info["name"])
        self.col_name_edit.blockSignals(False)
        rows, nonnull = info.get("rows", 0), info.get("nonnull", 0)
        nulls = rows - nonnull
        self.col_rows.setText(
            f"{rows:,}" + (f"  ({nulls:,} null)" if nulls else ""))
        self.col_type.setText(info.get("dtype", "—"))
        is_float = bool(info.get("is_float"))
        self.col_sig_row.setVisible(is_float)
        self.col_sig_label.setVisible(is_float)
        if is_float:
            self.col_sig.blockSignals(True)
            self.col_sig.setValue(int(info.get("sigfigs", 4)))
            self.col_sig.blockSignals(False)

    def _emit_rename(self) -> None:
        if self._col is None:
            return
        new = self.col_name_edit.text().strip()
        if new and new != self._col:
            self.columnRenamed.emit(self._col, new)

    def _emit_sigfigs(self, n: int) -> None:
        if self._col is not None:
            self.sigFigsChanged.emit(self._col, int(n))

    def _plot_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        points = QGroupBox("Points")
        pf = QFormLayout(points)
        self.marker_combo = fix_combo(QComboBox())
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
        self.map_combo = fix_combo(QComboBox())
        self.map_combo.addItems(
            ["BlueRed", "RedBlue", "viridis", "plasma", "magma", "turbo", "turbo_r"]
        )
        self.map_combo.currentTextChanged.connect(self.colormapChanged)
        cf.addRow("Map", self.map_combo)
        self.scale_combo = fix_combo(QComboBox())
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
