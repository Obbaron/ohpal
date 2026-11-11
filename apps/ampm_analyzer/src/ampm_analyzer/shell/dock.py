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
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyleOptionSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import plot_elements as pe
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
    # Plot-element editor → active plot.
    elementEdited = pyqtSignal(str, str, object)  # (element, property, value)
    elementReset = pyqtSignal(str, bool)          # (element, to built-in look?)
    elementDefaultRequested = pyqtSignal(str)     # save as default for new plots
    elementClosed = pyqtSignal()                  # back to the plot controls
    # Data-panel (column info) → the data tab.
    columnRenamed = pyqtSignal(str, str)   # (old display name, new name)
    sigFigsChanged = pyqtSignal(str, int)  # (column, significant figures)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setMinimumWidth(240)
        self._col = None  # the column the data page is currently showing
        self._element: str | None = None  # the plot element being edited
        self._el_controls: dict = {}      # property -> (kind, widget)

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
        """Two views in one page: the whole-plot controls, and the editor for
        one selected element (swapped in by a double-click on the plot)."""
        self._plot_stack = QStackedWidget()
        self._plot_stack.addWidget(self._plot_controls())
        self._plot_stack.addWidget(self._element_page())
        return self._plot_stack

    def _plot_controls(self) -> QWidget:
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

    # -- plot page: element editor ---------------------------------------
    def _element_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(6)
        back = QToolButton()
        back.setText("\u2039")  # ‹
        back.setAutoRaise(True)
        back.setToolTip("Back to the plot controls")
        back.setStyleSheet("QToolButton { font-size: 15pt; padding: 0 6px; }")
        back.clicked.connect(self._close_element)
        head.addWidget(back)
        self.el_heading = QLabel("")
        self.el_heading.setStyleSheet("font-weight: 600;")
        head.addWidget(self.el_heading, 1)
        lay.addLayout(head)

        # The property controls are rebuilt for each element from its schema.
        self._el_form_host = QWidget()
        self._el_form_lay = QVBoxLayout(self._el_form_host)
        self._el_form_lay.setContentsMargins(0, 0, 0, 0)
        self._el_form_lay.setSpacing(12)
        lay.addWidget(self._el_form_host)

        buttons = QHBoxLayout()
        self.el_default_btn = QPushButton("Set as default")
        self.el_default_btn.setToolTip(
            "Use this styling for new plots (this plot's text is not saved)")
        self.el_default_btn.clicked.connect(
            lambda: self._element and self.elementDefaultRequested.emit(
                self._element))
        buttons.addWidget(self.el_default_btn)
        self.el_reset_btn = QPushButton("Reset")
        self.el_reset_btn.setToolTip("Undo this element's styling")
        menu = QMenu(self.el_reset_btn)
        menu.addAction("To my default").triggered.connect(
            lambda: self._element and self.elementReset.emit(self._element, False))
        menu.addAction("To the built-in look").triggered.connect(
            lambda: self._element and self.elementReset.emit(self._element, True))
        self.el_reset_btn.setMenu(menu)
        buttons.addWidget(self.el_reset_btn)
        buttons.addStretch(1)
        lay.addLayout(buttons)

        lay.addStretch(1)
        return w

    def element_key(self) -> str | None:
        """The element the editor is showing (None: the plot controls)."""
        return self._element

    def edit_element(self, tab, key: str) -> None:
        """Open the editor on one of ``tab``'s elements."""
        element = pe.ELEMENTS.get(key)
        if element is None:
            return
        self.show_element(element, tab.element_values(key),
                          tab.element_auto_text(key))

    def show_element(self, element, values: dict, auto_text: str = "") -> None:
        """Build the editor for ``element`` from its fields and fill it in."""
        self._element = element.key
        self.el_heading.setText(element.label)
        while self._el_form_lay.count():  # drop the previous element's controls
            item = self._el_form_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._el_controls = {}
        form, group = None, object()
        for f in element.fields:
            if f.group != group:  # a new group box (or a bare form for "")
                group = f.group
                box = QGroupBox(group) if group else QWidget()
                form = QFormLayout(box)
                if not group:
                    form.setContentsMargins(0, 0, 0, 0)
                self._el_form_lay.addWidget(box)
            form.addRow(f.label, self._element_control(element.key, f, auto_text))
        self.set_element_values(values)
        self._plot_stack.setCurrentIndex(1)

    def _element_control(self, key: str, f, auto_text: str) -> QWidget:
        """One control for one field, emitting ``elementEdited`` live."""
        def emit(name):
            return lambda value: self.elementEdited.emit(key, name, value)

        if f.kind == "text":
            edit = QLineEdit()
            if auto_text:
                edit.setPlaceholderText(auto_text)
                edit.setToolTip("Leave empty to follow the column's name")
            edit.textEdited.connect(emit(f.name))
            self._el_controls[f.name] = ("text", edit)
            return edit
        if f.kind == "font":
            combo = fix_combo(QComboBox())
            for i, name in enumerate(pe.FONTS):
                combo.addItem(name)
                combo.setItemData(i, QFont(name), Qt.ItemDataRole.FontRole)
            combo.currentTextChanged.connect(emit(f.name))
            self._el_controls[f.name] = ("font", combo)
            return combo
        if f.kind == "size":
            spin = QSpinBox()
            spin.setRange(*pe.SIZE_RANGE)
            spin.setSuffix(" pt")
            spin.valueChanged.connect(emit(f.name))
            self._el_controls[f.name] = ("size", spin)
            return spin
        if f.kind == "style":
            prefix = f.name[: -len("style")]
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            for name, text, tip, css in (
                    ("bold", "B", "Bold", "font-weight: 700;"),
                    ("italic", "I", "Italic", "font-style: italic;")):
                b = QToolButton()
                b.setText(text)
                b.setToolTip(tip)
                b.setCheckable(True)
                b.setFixedWidth(30)
                b.setStyleSheet(f"QToolButton {{ {css} }}")
                b.toggled.connect(emit(prefix + name))
                self._el_controls[prefix + name] = ("bool", b)
                h.addWidget(b)
            h.addStretch(1)
            return row
        # colour: a swatch button that opens the colour picker
        btn = QPushButton()
        btn.setToolTip("Choose a colour")
        btn.clicked.connect(lambda: self._pick_colour(key, f.name))
        self._el_controls[f.name] = ("color", btn)
        return btn

    @staticmethod
    def _show_colour(btn: QPushButton, value: str) -> None:
        colour = QColor(value)
        if not colour.isValid():
            colour = QColor("#000000")
        btn.setProperty("colour", colour.name())
        # Readable label on any swatch: dark text on light colours.
        ink = "#000000" if colour.lightnessF() > 0.6 else "#ffffff"
        btn.setText(colour.name())
        btn.setStyleSheet(
            f"QPushButton {{ background: {colour.name()}; color: {ink};"
            " border: 1px solid palette(mid); border-radius: 4px;"
            " padding: 3px 10px; }")

    def _pick_colour(self, key: str, name: str) -> None:
        kind_btn = self._el_controls.get(name)
        if kind_btn is None:
            return
        btn = kind_btn[1]
        start = QColor(btn.property("colour") or "#000000")
        colour = QColorDialog.getColor(start, self, "Colour")
        if not colour.isValid():
            return
        self._show_colour(btn, colour.name())
        self.elementEdited.emit(key, name, colour.name())

    def set_element_values(self, values: dict) -> None:
        """Show ``values`` on the editor's controls without re-emitting."""
        for name, (kind, widget) in self._el_controls.items():
            if name not in values:
                continue
            value = values[name]
            widget.blockSignals(True)
            if kind == "text":
                if widget.text() != str(value or ""):
                    widget.setText(str(value or ""))
            elif kind == "font":
                i = widget.findText(str(value))
                widget.setCurrentIndex(i if i >= 0 else 0)
            elif kind == "size":
                widget.setValue(int(round(float(value))))
            elif kind == "bool":
                widget.setChecked(bool(value))
            else:
                self._show_colour(widget, str(value))
            widget.blockSignals(False)

    def show_plot_controls(self) -> None:
        """Leave the element editor for the whole-plot controls."""
        self._element = None
        self._plot_stack.setCurrentIndex(0)

    def _close_element(self) -> None:
        self.show_plot_controls()
        self.elementClosed.emit()
