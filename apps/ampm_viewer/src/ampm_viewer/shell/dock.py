"""Side panel.

A plain widget (not a QMainWindow dock) so it can sit *inside* the central
layout, beside the content and under the tab strip and toolbar, rather than
spanning the full height up to the title bar.

Two pages, one per kind of tab:

- **Data**: with no column selected, the whole grid (rows, columns, layer,
  filters, sig figs for every decimal column, which columns show); with one
  selected, that column (its name, a histogram and summary numbers, its sig
  figs).
- **Plot**: the active plot's point and colour settings, or the editor of the
  plot element double-clicked (title, an axis, the legend ...).

Each page is a column of cards (``panel_widgets.Card``) on the panel's tint.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QStyle,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from . import plot_elements as pe
from .panel_widgets import (
    Badge,
    Card,
    ChoiceButtons,
    CmapGallery,
    Histogram,
    LabelRow,
    RangeBar,
    Segmented,
    TileGrid,
    field_label,
    inline_row,
    stacked_row,
    two_state_icon,
)
from .widgets import fix_combo

_MARKERS = (("disc", "circle--solid"), ("square", "square--solid"),
            ("ring", "radio-button"), ("cross", "close"))
_ALIGN_STEMS = {"left": "text--align--left", "center": "text--align--center",
                "right": "text--align--right"}
# The icon on an element editor's card, by group (a text group otherwise).
_GROUP_STEMS = {
    "Points": "chart--scatter", "Colour": "color-palette", "Bars": "chart--bar",
    "Curves": "chart--line-smooth", "Curve": "chart--line",
    "Violins": "chart--violin-plot", "Level lines": "contour--draw",
    "Measured points": "dot-mark", "Ticks": "x-axis", "Axis line": "x-axis",
    "Gridlines (both axes)": "grid", "Layout": "fit-to-screen", "Box": "legend",
    "Names": "legend", "Numbers": "hashtag", "Scale": "fit-to-screen",
    "Label": "text--font", "Shows": "hashtag", "Line": "chart--line",
}
# The short type tag beside a column's name.
_KIND_TAGS = {"float": "1.2", "int": "123", "text": "Aa", "bool": "T/F",
              "date": "date", "other": "…"}


def _fmt(v, n: int = 4) -> str:
    """A number for the panel: ints with separators, floats at ``n`` sig figs."""
    if v is None:
        return "-"
    if isinstance(v, int):
        return f"{v:,}"
    return f"{v:.{n}g}"


def _scroll(page: QWidget) -> QScrollArea:
    """``page`` in a frameless vertical scroller on the panel's tint."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    # The panel is made wide enough for its widest card (SidePanel.fit_width),
    # so this only shows if something is wider still: never clipped.
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setProperty("class", "PanelScroll")
    page.setProperty("class", "PanelPage")
    area.setWidget(page)
    return area


def _page() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(10, 10, 10, 10)
    lay.setSpacing(10)
    return w, lay


def _slider(lo: int, hi: int, val: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    return s


def _back_button(text: str = "") -> QToolButton:
    b = QToolButton()
    b.setAutoRaise(True)
    b.setProperty("class", "PanelBack")
    b.setIcon(icons.icon("arrow--left", icons_ink(), 16))
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    return b


def icons_ink() -> str:
    from .panel_widgets import _ink
    return _ink()


class _SwatchButton(QPushButton):
    """A colour field: the colour, with its hex code in a readable ink."""

    def show_colour(self, value: str) -> None:
        colour = QColor(value)
        if not colour.isValid():
            colour = QColor("#000000")
        self.setProperty("colour", colour.name())
        ink = "#000000" if colour.lightnessF() > 0.6 else "#ffffff"
        self.setText(colour.name())
        self.setStyleSheet(
            f"QPushButton {{ background: {colour.name()}; color: {ink};"
            " border: 1px solid palette(mid); border-radius: 4px;"
            " padding: 3px 10px; }")


class SidePanel(QWidget):
    closed = pyqtSignal()
    # Plot-panel controls -> active plot.
    markerSizeChanged = pyqtSignal(int)
    markerSymbolChanged = pyqtSignal(str)
    opacityChanged = pyqtSignal(int)
    colormapChanged = pyqtSignal(str)
    scaleChanged = pyqtSignal(str)
    colorMinChanged = pyqtSignal(int)
    colorMaxChanged = pyqtSignal(int)
    # Plot-element editor -> active plot.
    elementEdited = pyqtSignal(str, str, object)  # (element, property, value)
    elementReset = pyqtSignal(str, bool)          # (element, to built-in look?)
    elementDefaultRequested = pyqtSignal(str)     # save as default for new plots
    elementClosed = pyqtSignal()                  # back to the plot controls
    # Data panel (one column) -> the data tab.
    columnRenamed = pyqtSignal(str, str)   # (old display name, new name)
    sigFigsChanged = pyqtSignal(str, int)  # (column, significant figures)
    columnClosed = pyqtSignal()            # back to the whole grid
    # Data panel (the whole grid) -> the window.
    columnPicked = pyqtSignal(str)                 # show this column
    columnVisibilityChanged = pyqtSignal(str, bool)
    filterAddRequested = pyqtSignal()
    filterEditRequested = pyqtSignal(int)
    filterRemoveRequested = pyqtSignal(int)
    filtersClearRequested = pyqtSignal()
    gridSigFigsChanged = pyqtSignal(int)   # every decimal column

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setMinimumWidth(self._MIN_WIDTH)
        self._widest_el: int | None = None  # see _widest_element
        self._col = None  # the column the data page is currently showing
        self._col_stats: dict = {}
        self._element: str | None = None  # the plot element being edited
        self._el_controls: dict = {}      # property -> (kind, widget)
        self._full_range = None           # the colour column's (min, max)
        self._cards: list[Card] = []      # every card, to retint
        self._grid_columns: list = []     # (name, kind, visible) last shown

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
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

    def _card(self, stem: str, title: str) -> Card:
        c = Card(stem, title)
        self._cards.append(c)
        return c

    def retint(self) -> None:
        """Re-colour icons after a theme change."""
        self._cards = [c for c in self._cards if _alive(c)]
        for c in self._cards:
            c.retint()
        for b in self.findChildren(QToolButton):
            if b.property("class") == "PanelBack":
                b.setIcon(icons.icon("arrow--left", icons_ink(), 16))
        for seg in self.findChildren(Segmented):
            for b in seg.buttons:
                stem = b.property("stem")
                if stem:
                    b.setIcon(two_state_icon(stem))
        self.update()

    def show_for(self, kind: str) -> None:
        page = self._pages.get(kind)
        if page is not None:
            self.stack.setCurrentWidget(page)

    # =================================================================
    # Plot page: the whole-plot controls, or one element's editor
    # =================================================================
    def _plot_page(self) -> QWidget:
        self._plot_stack = QStackedWidget()
        self._plot_stack.addWidget(_scroll(self._plot_controls()))
        self._plot_stack.addWidget(_scroll(self._element_page()))
        return self._plot_stack

    def _plot_controls(self) -> QWidget:
        w, lay = _page()

        # Each card shows only on plots it applies to (see sync_plot).
        self.points_box = points = self._card("chart--scatter", "Points")
        points.body.addWidget(field_label("Marker"))
        self.marker_combo = ChoiceButtons(
            [(name, name, stem) for name, stem in _MARKERS])
        self.marker_combo.currentTextChanged.connect(self.markerSymbolChanged)
        points.body.addWidget(self.marker_combo)
        self._size_row = LabelRow("Size", "3 px")
        points.body.addWidget(self._size_row)
        self.size_slider = _slider(1, 20, 3)
        self.size_slider.valueChanged.connect(
            lambda v: self._size_row.value.setText(f"{v} px"))
        self.size_slider.valueChanged.connect(self.markerSizeChanged)
        points.body.addWidget(self.size_slider)
        self._opacity_row = LabelRow("Opacity", "100%")
        points.body.addWidget(self._opacity_row)
        self.opacity_slider = _slider(0, 100, 100)
        self.opacity_slider.valueChanged.connect(
            lambda v: self._opacity_row.value.setText(f"{v}%"))
        self.opacity_slider.valueChanged.connect(self.opacityChanged)
        points.body.addWidget(self.opacity_slider)
        lay.addWidget(points)

        from .plotdata import COLORMAP_NAMES
        self.colour_box = colour = self._card("color-palette", "Colour")
        self.colour_by = QLabel("")
        self.colour_by.setProperty("class", "FieldNote")
        self.colour_by.setWordWrap(True)
        colour.body.addWidget(self.colour_by)
        colour.body.addWidget(field_label("Colour map"))
        self.map_combo = CmapGallery(COLORMAP_NAMES, columns=4)
        self.map_combo.currentTextChanged.connect(self._on_cmap)
        colour.body.addWidget(self.map_combo)
        self.scale_combo = ChoiceButtons([("Linear", "Linear", None), ("Log", "Log", None)])
        self.scale_combo.currentTextChanged.connect(self.scaleChanged)
        self._scale_row = stacked_row("Scale", self.scale_combo)
        colour.body.addWidget(self._scale_row)
        self._range_row = LabelRow("Range", "0% to 100%")
        colour.body.addWidget(self._range_row)
        self.range_bar = RangeBar()
        self.range_bar.lowChanged.connect(self._on_range)
        self.range_bar.highChanged.connect(self._on_range)
        self.range_bar.lowChanged.connect(self.colorMinChanged)
        self.range_bar.highChanged.connect(self.colorMaxChanged)
        colour.body.addWidget(self.range_bar)
        lay.addWidget(colour)

        # When a plot has none of the above (a single k-distance curve).
        self.plot_note = QLabel(
            "This plot has no point or colour settings. Double-click its "
            "title, an axis or the legend to style it.")
        self.plot_note.setWordWrap(True)
        self.plot_note.setProperty("class", "FieldNote")
        self.plot_note.setVisible(False)
        lay.addWidget(self.plot_note)
        lay.addStretch(1)
        return w

    def _on_cmap(self, name: str) -> None:
        self.range_bar.set_cmap(name)
        self.colormapChanged.emit(name)

    def _on_range(self, *_a) -> None:
        self._show_range_text()

    def _show_range_text(self) -> None:
        lo, hi = self.range_bar.low(), self.range_bar.high()
        self._range_row.value.setText(f"{lo}% to {hi}%")
        if self._full_range is not None:
            fmin, fmax = self._full_range
            span = fmax - fmin
            self.range_bar.set_labels(_fmt(fmin + span * lo / 100.0),
                                      _fmt(fmin + span * hi / 100.0))
        else:
            self.range_bar.set_labels("", "")

    def sync_plot(self, state: dict) -> None:
        """Reflect an active plot's appearance on the controls (no re-emit)."""
        def set_slider(sl, v):
            sl.blockSignals(True)
            sl.setValue(int(v))
            sl.blockSignals(False)

        def set_choice(cb, text):
            cb.blockSignals(True)
            i = cb.findText(str(text))
            if i >= 0:
                cb.setCurrentIndex(i)
            cb.blockSignals(False)

        set_slider(self.size_slider, state.get("size", 7))
        self._size_row.value.setText(f"{self.size_slider.value()} px")
        set_slider(self.opacity_slider, state.get("opacity", 100))
        self._opacity_row.value.setText(f"{self.opacity_slider.value()}%")
        set_choice(self.marker_combo, state.get("symbol", "disc"))
        set_choice(self.map_combo, state.get("cmap", "turbo"))
        set_choice(self.scale_combo, state.get("scale", "Linear"))
        self.range_bar.set_cmap(self.map_combo.currentText())
        self.range_bar.set_values(state.get("cmin", 0), state.get("cmax", 100))
        fr = state.get("full_range")
        self._full_range = tuple(fr) if fr is not None else None
        self._show_range_text()
        by = state.get("color_by") or ""
        self.colour_by.setText(f"By {by}" if by else "")
        self.colour_by.setVisible(bool(by))
        # Only what applies to this plot is shown. Points: plots drawn as
        # markers. Colour: a numeric colour column, or the map alone where it
        # colours curves or many categories (no scale or range then).
        points = bool(state.get("has_points", True))
        map_only = bool(state.get("map_only", False))
        colour = bool(state.get("has_color", False)) or map_only
        self.points_box.setVisible(points)
        self.colour_box.setVisible(colour)
        for w in (self._scale_row, self._range_row, self.range_bar):
            w.setVisible(not map_only)
        self.plot_note.setVisible(not (points or colour))
        self.fit_width()

    # -- plot page: element editor ---------------------------------------
    def _element_page(self) -> QWidget:
        w, lay = _page()
        head = QHBoxLayout()
        head.setSpacing(6)
        back = _back_button()
        back.setToolTip("Back to the plot controls")
        back.clicked.connect(self._close_element)
        head.addWidget(back)
        self.el_heading = QLabel("")
        self.el_heading.setProperty("class", "PanelTitle")
        head.addWidget(self.el_heading, 1)
        lay.addLayout(head)

        # The cards are rebuilt for each element from its fields.
        self._el_form_host = QWidget()
        self._el_form_lay = QVBoxLayout(self._el_form_host)
        self._el_form_lay.setContentsMargins(0, 0, 0, 0)
        self._el_form_lay.setSpacing(10)
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
        # At the foot of the panel, out of the way of the properties.
        lay.addStretch(1)
        lay.addLayout(buttons)
        return w

    def element_key(self) -> str | None:
        """The element the editor is showing (None: the plot controls)."""
        return self._element

    def edit_element(self, tab, key: str) -> None:
        """Open the editor on one of ``tab``'s elements."""
        element = pe.ELEMENTS.get(key)
        if element is None:
            return
        schema = getattr(tab, "element_schema", None)
        if schema is not None:  # only the fields that apply to this plot
            element = schema(key)
        self.show_element(element, tab.element_values(key),
                          tab.element_auto_text(key))

    def show_element(self, element, values: dict, auto_text: str = "") -> None:
        """Build the editor's cards for ``element`` and fill them in."""
        self._widest_element()  # measured once, before these cards exist
        self._element = element.key
        self.el_heading.setText(element.label)
        self._build_element_cards(element, auto_text)
        self.set_element_values(values)
        self._plot_stack.setCurrentIndex(1)
        self.fit_width()

    def _build_element_cards(self, element, auto_text: str = "") -> None:
        self._cards = [c for c in self._cards if _alive(c)]
        while self._el_form_lay.count():  # drop the previous element's cards
            item = self._el_form_lay.takeAt(0)
            _drop(item.widget())
        self._el_controls = {}
        groups: list[tuple[str, list]] = []
        for f in element.fields:
            if not groups or groups[-1][0] != f.group:
                groups.append((f.group, []))
            groups[-1][1].append(f)
        for group, fields in groups:
            card = self._card(_GROUP_STEMS.get(group, "text--font"), group or "Text")
            self._fill_card(card, element.key, fields, auto_text)
            self._el_form_lay.addWidget(card)

    # -- width -----------------------------------------------------------
    _MIN_WIDTH = 260

    def _content_width(self) -> int:
        """The width the widest page's cards need, with room for a vertical
        scroll bar."""
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        pages = [a.widget() for a in self.findChildren(QScrollArea)
                 if a.widget() is not None]
        widest = max((p.minimumSizeHint().width() for p in pages), default=0)
        return widest + bar + 2

    def _widest_element(self) -> int:
        """The width the widest element editor needs: each element's cards are
        built once (off screen) and measured."""
        if self._widest_el is None:
            keep, keep_controls = self._element, self._el_controls
            widest = 0
            for element in pe.ELEMENTS.values():
                self._build_element_cards(element)
                self._el_form_host.adjustSize()
                widest = max(widest, self._content_width())
            self._build_element_cards_empty()
            self._element, self._el_controls = keep, keep_controls
            self._widest_el = widest
        return self._widest_el

    def _build_element_cards_empty(self) -> None:
        while self._el_form_lay.count():
            _drop(self._el_form_lay.takeAt(0).widget())
        self._el_controls = {}

    def fit_width(self) -> None:
        """Make the panel at least as wide as its widest card (any page, any
        element editor), so no card is ever cut off; the splitter widens it."""
        need = max(self._MIN_WIDTH, self._content_width(), self._widest_element())
        if need != self.minimumWidth():
            self.setMinimumWidth(need)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.fit_width()

    def _fill_card(self, card: Card, key: str, fields, auto_text: str) -> None:
        """One card's rows. Font and size share a row; so do the bold / italic
        toggles and the alignment."""
        i = 0
        while i < len(fields):
            f = fields[i]
            nxt = fields[i + 1] if i + 1 < len(fields) else None
            if f.kind == "font" and nxt is not None and nxt.kind == "size":
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(6)
                h.addWidget(self._element_control(key, f, auto_text), 1)
                size = self._element_control(key, nxt, auto_text)
                size.setFixedWidth(76)
                h.addWidget(size)
                card.body.addWidget(stacked_row("Font", row))
                i += 2
                continue
            if f.kind == "style":
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(8)
                h.addWidget(self._element_control(key, f, auto_text))
                rest = [x for x in fields[i + 1:] if x.name == "align"]
                if rest:
                    h.addWidget(self._element_control(key, rest[0], auto_text))
                    fields = [x for x in fields if x is not rest[0]]
                h.addStretch(1)
                card.body.addWidget(row)
                i += 1
                continue
            control = self._element_control(key, f, auto_text)
            if f.kind == "text":
                card.body.addWidget(control)
            elif f.kind == "check":
                card.body.addWidget(control)
            elif f.kind in ("int", "size", "color", "number"):
                card.body.addWidget(inline_row(f.label, control))
            else:
                card.body.addWidget(stacked_row(f.label, control))
            i += 1

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
            seg = Segmented(exclusive=False)
            for name, stem, tip in (("bold", "text--bold", "Bold"),
                                    ("italic", "text--italic", "Italic")):
                b = seg.add(stem=stem, tip=tip)
                b.setFixedWidth(36)
                b.toggled.connect(emit(prefix + name))
                self._el_controls[prefix + name] = ("bool", b)
            seg.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            return seg
        if f.kind == "choice":
            if f.name == "cmap":
                widget = CmapGallery([v for v, _t in f.options], columns=4)
            elif f.name == "align":
                widget = ChoiceButtons([(v, t, _ALIGN_STEMS.get(v)) for v, t in
                                        sorted(f.options, key=lambda o: list(
                                            _ALIGN_STEMS).index(o[0]))])
            elif f.name == "symbol":
                stems = dict(_MARKERS)
                widget = ChoiceButtons([(v, t, stems.get(v)) for v, t in f.options])
            elif len(f.options) <= 2:
                widget = ChoiceButtons([(v, t, None) for v, t in f.options])
            else:
                widget = fix_combo(QComboBox())
                for value, text in f.options:
                    widget.addItem(text, value)
            widget.currentIndexChanged.connect(
                lambda i, c=widget, n=f.name: self.elementEdited.emit(
                    key, n, c.itemData(i)))
            self._el_controls[f.name] = ("choice", widget)
            return widget
        if f.kind == "int":
            spin = QSpinBox()
            spin.setRange(f.lo, f.hi)
            if f.suffix:
                spin.setSuffix(f.suffix)
            if f.special:
                spin.setSpecialValueText(f.special)
            spin.setMinimumWidth(76)
            spin.valueChanged.connect(emit(f.name))
            self._el_controls[f.name] = ("int", spin)
            return spin
        if f.kind == "number":
            edit = QLineEdit()
            edit.setPlaceholderText(f.special or "")
            edit.setToolTip("A number; leave empty for automatic")
            edit.setMinimumWidth(96)
            edit.setMaximumWidth(140)

            def commit(e=edit, n=f.name):
                text = e.text().strip()
                try:
                    value = float(text) if text else None
                except ValueError:  # not a number: back to what it was
                    e.setText(e.property("shown") or "")
                    return
                if (e.property("shown") or "") != text:
                    e.setProperty("shown", text)
                    self.elementEdited.emit(key, n, value)
            edit.editingFinished.connect(commit)
            self._el_controls[f.name] = ("number", edit)
            return edit
        if f.kind == "check":
            box = QCheckBox(f.label)
            box.toggled.connect(emit(f.name))
            self._el_controls[f.name] = ("bool", box)
            return box
        # colour: a swatch button that opens the colour picker
        btn = _SwatchButton()
        btn.setToolTip("Choose a colour")
        btn.setFixedWidth(110)
        btn.clicked.connect(lambda: self._pick_colour(key, f.name))
        self._el_controls[f.name] = ("color", btn)
        return btn

    @staticmethod
    def _show_colour(btn: QPushButton, value: str) -> None:
        _SwatchButton.show_colour(btn, value)

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
            elif kind in ("size", "int"):
                widget.setValue(int(round(float(value))))
            elif kind == "number":
                shown = "" if value is None else f"{float(value):g}"
                widget.setText(shown)
                widget.setProperty("shown", shown)
            elif kind == "choice":
                i = widget.findData(value)
                if i >= 0:
                    widget.setCurrentIndex(i)
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

    # =================================================================
    # Data page: the whole grid, or one column
    # =================================================================
    def _data_page(self) -> QWidget:
        self._data_stack = QStackedWidget()
        self._data_stack.addWidget(_scroll(self._grid_page()))
        self._data_stack.addWidget(_scroll(self._column_page()))
        return self._data_stack

    # -- the whole grid --------------------------------------------------
    def _grid_page(self) -> QWidget:
        w, lay = _page()

        self.grid_card = self._card("data-table", "Grid")
        self.grid_tiles = TileGrid(4)
        self.grid_card.body.addWidget(self.grid_tiles)
        lay.addWidget(self.grid_card)

        self.filters_card = self._card("filter", "Filters")
        self._filter_list = QVBoxLayout()
        self._filter_list.setSpacing(4)
        self.filters_card.body.addLayout(self._filter_list)
        self.filters_empty = QLabel("No filters: every row shows.")
        self.filters_empty.setProperty("class", "FieldNote")
        self.filters_card.body.addWidget(self.filters_empty)
        h = QHBoxLayout()
        self.btn_add_filter = QPushButton("Add filter")
        self.btn_add_filter.clicked.connect(self.filterAddRequested)
        h.addWidget(self.btn_add_filter)
        self.btn_clear_filters = QPushButton("Clear all")
        self.btn_clear_filters.clicked.connect(self.filtersClearRequested)
        h.addWidget(self.btn_clear_filters)
        h.addStretch(1)
        self.filters_card.body.addLayout(h)
        lay.addWidget(self.filters_card)

        self.grid_display_card = self._card("hashtag", "Display")
        self.grid_sig = QSpinBox()
        self.grid_sig.setRange(1, 12)
        self.grid_sig.setValue(4)
        self.grid_sig.setSpecialValueText("")
        self.grid_sig.valueChanged.connect(self.gridSigFigsChanged)
        self.grid_display_card.body.addWidget(inline_row("Significant figures", self.grid_sig))
        self.grid_sig_note = QLabel(
            "For every decimal column. Select a column to set its own.")
        self.grid_sig_note.setProperty("class", "FieldNote")
        self.grid_sig_note.setWordWrap(True)
        self.grid_display_card.body.addWidget(self.grid_sig_note)
        lay.addWidget(self.grid_display_card)

        self.columns_card = self._card("view", "Columns")
        self.columns_count = QLabel("")
        self.columns_count.setProperty("class", "FieldNote")
        self.columns_card.add_right(self.columns_count)
        self.column_search = QLineEdit()
        self.column_search.setPlaceholderText("Find a column")
        self.column_search.setClearButtonEnabled(True)
        self.column_search.textChanged.connect(self._filter_column_rows)
        self.columns_card.body.addWidget(self.column_search)
        self._column_list = QVBoxLayout()
        self._column_list.setSpacing(0)
        self.columns_card.body.addLayout(self._column_list)
        h = QHBoxLayout()
        self.btn_show_all = QPushButton("Show all")
        self.btn_show_all.clicked.connect(self._show_all_columns)
        h.addWidget(self.btn_show_all)
        h.addStretch(1)
        self.columns_card.body.addLayout(h)
        lay.addWidget(self.columns_card)
        lay.addStretch(1)
        return w

    def show_grid_info(self, info: dict | None) -> None:
        """The whole grid: ``info`` has ``rows`` / ``total`` (after / before
        the filters), ``layer`` / ``layers`` (number, how many), ``columns``
        (``(name, kind, visible)`` in the grid's order), ``filters`` (the
        conditions) and ``sigfigs`` (shared by the decimal columns, else
        None)."""
        self._col = None
        self._data_stack.setCurrentIndex(0)
        info = info or {}
        cols = list(info.get("columns", []))
        shown_cols = sum(1 for _n, _k, v in cols if v)
        rows, total = info.get("rows", 0), info.get("total", 0)
        filters = list(info.get("filters", []))
        layer, layers = info.get("layer"), info.get("layers", 0)
        self.grid_tiles.show_stats([
            ("Rows" if rows == total else f"Rows of {total:,}", f"{rows:,}"),
            ("Columns", f"{shown_cols} of {len(cols)}" if shown_cols != len(cols)
             else f"{len(cols)}"),
            ("Layer", "-" if layer is None else f"{layer}"
             + (f" of {layers}" if layers else "")),
            ("Filters", f"{len(filters)}" if filters else "None"),
        ])

        while self._filter_list.count():
            item = self._filter_list.takeAt(0)
            _drop(item.widget())
        for i, cond in enumerate(filters):
            self._filter_list.addWidget(self._filter_row(i, cond))
        self.filters_empty.setVisible(not filters)
        self.btn_clear_filters.setEnabled(bool(filters))

        floats = any(k == "float" for _n, k, _v in cols)
        self.grid_display_card.setVisible(floats)
        self.grid_sig.blockSignals(True)
        sig = info.get("sigfigs")
        self.grid_sig.setValue(int(sig) if sig else 4)
        self.grid_sig.blockSignals(False)
        self.grid_sig_note.setText(
            "For every decimal column. Select a column to set its own."
            if sig else "Decimal columns differ now; a value here sets them all.")

        if cols != self._grid_columns:
            self._grid_columns = cols
            while self._column_list.count():
                item = self._column_list.takeAt(0)
                _drop(item.widget())
            for name, kind, visible in cols:
                self._column_list.addWidget(self._column_row(name, kind, visible))
            self._filter_column_rows(self.column_search.text())
        self.columns_count.setText(f"{shown_cols} of {len(cols)} shown")
        self.btn_show_all.setEnabled(shown_cols < len(cols))
        self.fit_width()

    def showing_grid(self) -> bool:
        """Whether the data page is on the whole grid (no column)."""
        return self._data_stack.currentIndex() == 0

    def _filter_row(self, index: int, cond: str) -> QWidget:
        row = QFrame()
        row.setProperty("class", "FilterRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 2, 2, 2)
        h.setSpacing(2)
        one_line = " ".join(cond.split())
        edit = QPushButton(one_line)
        edit.setProperty("class", "FilterText")
        edit.setToolTip(f"{cond}\n\nClick to edit")
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        edit.clicked.connect(lambda _c=False, i=index: self.filterEditRequested.emit(i))
        h.addWidget(edit, 1)
        rm = QToolButton()
        rm.setAutoRaise(True)
        rm.setIcon(icons.icon("close", icons_ink(), 14))
        rm.setToolTip("Remove this filter")
        rm.clicked.connect(lambda _c=False, i=index: self.filterRemoveRequested.emit(i))
        h.addWidget(rm)
        return row

    def _column_row(self, name: str, kind: str, visible: bool) -> QWidget:
        row = QWidget()
        row.setProperty("column", name)
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 1, 0, 1)
        h.setSpacing(6)
        box = QCheckBox()
        box.setChecked(visible)
        box.setToolTip("Show this column in the grid")
        box.toggled.connect(lambda on, n=name: self.columnVisibilityChanged.emit(n, on))
        h.addWidget(box)
        tag = QLabel(_KIND_TAGS.get(kind, _KIND_TAGS["other"]))
        tag.setProperty("class", "KindTag")
        tag.setFixedWidth(30)
        tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(tag)
        btn = QPushButton(name)
        btn.setProperty("class", "ColumnLink")
        btn.setToolTip(f"{name}\n\nClick to see this column")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        btn.clicked.connect(lambda _c=False, n=name: self.columnPicked.emit(n))
        h.addWidget(btn, 1)
        return row

    def _column_rows(self) -> list[QWidget]:
        out = []
        for i in range(self._column_list.count()):
            w = self._column_list.itemAt(i).widget()
            if w is not None:
                out.append(w)
        return out

    def _filter_column_rows(self, text: str) -> None:
        low = (text or "").strip().lower()
        for row in self._column_rows():
            row.setVisible(not low or low in str(row.property("column")).lower())

    def _show_all_columns(self) -> None:
        for name, _k, visible in list(self._grid_columns):
            if not visible:
                self.columnVisibilityChanged.emit(name, True)

    # -- one column ------------------------------------------------------
    def _column_page(self) -> QWidget:
        w, lay = _page()
        back = _back_button("All columns")
        back.setToolTip("Back to the whole grid")
        back.clicked.connect(self.columnClosed)
        lay.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)

        self.col_card = self._card("data--1", "Column")
        self.col_type = Badge("")
        self.col_card.add_right(self.col_type)
        self.col_name_edit = QLineEdit()
        self.col_name_edit.setPlaceholderText("column name")
        self.col_name_edit.setToolTip("Rename the column (Enter to apply)")
        self.col_name_edit.editingFinished.connect(self._emit_rename)
        self.col_card.body.addWidget(self.col_name_edit)
        lay.addWidget(self.col_card)

        self.values_card = self._card("chart--histogram", "Values")
        self.col_hist = Histogram(54)
        self.values_card.body.addWidget(self.col_hist)
        self.col_tiles = TileGrid(6)
        self.values_card.body.addWidget(self.col_tiles)
        lay.addWidget(self.values_card)

        self.col_display_card = self._card("hashtag", "Display")
        self.col_sig = QSpinBox()
        self.col_sig.setRange(1, 12)
        self.col_sig.setValue(4)
        self.col_sig.valueChanged.connect(self._emit_sigfigs)
        self.col_display_card.body.addWidget(inline_row("Significant figures", self.col_sig))
        self.col_sig_preview = QLabel("")
        self.col_sig_preview.setProperty("class", "FieldNote")
        self.col_display_card.body.addWidget(self.col_sig_preview)
        lay.addWidget(self.col_display_card)
        lay.addStretch(1)
        return w

    def show_column_info(self, info: dict | None) -> None:
        """One column, from ``DataTab.column_info`` (None: the grid page)."""
        if not info:
            self._col = None
            self._data_stack.setCurrentIndex(0)
            return
        self._data_stack.setCurrentIndex(1)
        self._col = info["name"]
        self._col_stats = info
        self.col_name_edit.blockSignals(True)
        self.col_name_edit.setText(info["name"])
        self.col_name_edit.setCursorPosition(0)
        self.col_name_edit.blockSignals(False)
        dtype = str(info.get("dtype", ""))
        self.col_type.setText(dtype.split("(", 1)[0])
        self.col_type.setToolTip(dtype)
        is_float = bool(info.get("is_float"))
        n = int(info.get("sigfigs", 4)) if is_float else 4
        rows, nonnull = info.get("rows", 0), info.get("nonnull", 0)
        nulls = rows - nonnull
        empty = f"{nulls:,}" + (f" ({100.0 * nulls / rows:.0f}%)" if nulls and rows else "")
        pairs = [("Rows", f"{rows:,}"), ("Empty", empty)]
        if info.get("min") is not None:
            pairs += [("Min", _fmt(info["min"], n)), ("Max", _fmt(info["max"], n)),
                      ("Mean", _fmt(info.get("mean"), n)),
                      ("Std dev", _fmt(info.get("std"), n))]
        elif info.get("distinct") is not None:
            pairs += [("Distinct", f"{info['distinct']:,}")]
        self.col_tiles.show_stats(pairs)
        hist = info.get("hist") or []
        self.col_hist.set_counts(hist)
        self.col_hist.setVisible(bool(hist))
        self.col_display_card.setVisible(is_float)
        if is_float:
            self.col_sig.blockSignals(True)
            self.col_sig.setValue(n)
            self.col_sig.blockSignals(False)
            self._show_sig_preview(n)
        self.fit_width()

    def _show_sig_preview(self, n: int) -> None:
        s = self._col_stats
        vals = [s.get(k) for k in ("min", "mean", "max")]
        vals = [f"{v:.{n}g}" for v in vals if v is not None]
        self.col_sig_preview.setText(
            "Shows as  " + "  ·  ".join(vals) if vals else "")

    def _emit_rename(self) -> None:
        if self._col is None:
            return
        new = self.col_name_edit.text().strip()
        if new and new != self._col:
            self.columnRenamed.emit(self._col, new)

    def _emit_sigfigs(self, n: int) -> None:
        if self._col is not None:
            self._col_stats["sigfigs"] = int(n)
            self._show_sig_preview(int(n))
            self.sigFigsChanged.emit(self._col, int(n))


def _drop(w) -> None:
    """Take a widget off screen now and delete it soon (``deleteLater`` alone
    leaves it painted where it was until the event loop gets to it)."""
    if w is not None:
        w.hide()
        w.setParent(None)
        w.deleteLater()


def _alive(w) -> bool:
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False
