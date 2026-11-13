"""New-plot dialog: pick which column goes on each channel.

Dumb by design — every combo lists *all* columns, so any column can be X, Y, Z
or the colour. Defaults come from plotspec.default_spec but are freely changed.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from .card import DraggableCard
from .plotspec import BAR_AGGS, COV_MODES, PlotSpec, default_spec
from .toolbars import LayerSpinBox
from .widgets import fix_combo

_NONE = "— none —"

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class NewPlotDialog(DraggableCard, QDialog):
    def __init__(self, kind: str, columns, layers=None, current_layer=None,
                 parent=None, *, renames=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"New {kind}")
        self._kind = kind
        self._columns = list(columns)
        self._layers = list(layers or [])
        self._current = (
            current_layer if current_layer is not None
            else (self._layers[0] if self._layers else None)
        )
        base = default_spec(kind, self._columns, renames)

        # Frameless card (matches the calculation / filter dialogs): drop the
        # window chrome; a translucent window lets the rounded QFrame show.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("NewPlotCard")
        card.setStyleSheet(
            "#NewPlotCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel(f"New {kind}")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        form = QFormLayout()

        def axis_combo(selected: str | None) -> QComboBox:
            cb = fix_combo(QComboBox())
            cb.addItems(self._columns)
            if selected in self._columns:
                cb.setCurrentIndex(self._columns.index(selected))
            return cb

        self.agg_combo = None
        self.z_combo = None
        self.color_combo = None
        self.bins_spin = None
        self.cov_mode_combo = None
        self.show_points_chk = None
        self.sl_layer = None
        if base.is_hist:
            # Histogram: one numeric column + a bin count.
            self.x_combo = axis_combo(base.x)
            form.addRow("Column", self.x_combo)
            self.y_combo = None
            self.bins_spin = QSpinBox()
            self.bins_spin.setRange(1, 1000)
            self.bins_spin.setValue(base.bins)
            form.addRow("Bins", self.bins_spin)
        elif base.is_bar:
            # Bar: a category axis, a value to reduce, and how to reduce it.
            self.x_combo = axis_combo(base.x)
            form.addRow("Category", self.x_combo)
            self.y_combo = axis_combo(base.y)
            form.addRow("Value", self.y_combo)
            self.agg_combo = fix_combo(QComboBox())
            self.agg_combo.addItems(BAR_AGGS)
            self.agg_combo.setCurrentText(base.agg)
            form.addRow("Aggregate", self.agg_combo)
        elif base.is_cov:
            # CoV Summary: one bar per group of a signal's CoV.
            self.x_combo = axis_combo(base.group_by or base.x)
            form.addRow("Group by", self.x_combo)
            self.y_combo = axis_combo(base.y)
            form.addRow("Signal", self.y_combo)
            self.cov_mode_combo = fix_combo(QComboBox())
            self.cov_mode_combo.addItems(COV_MODES)
            self.cov_mode_combo.setCurrentText(base.cov_mode)
            form.addRow("Mode", self.cov_mode_combo)
        elif base.is_contour:
            # Contour: a value (z) gridded over an (x, y) parameter plane.
            self.x_combo = axis_combo(base.x)
            form.addRow("X", self.x_combo)
            self.y_combo = axis_combo(base.y)
            form.addRow("Y", self.y_combo)
            self.z_combo = axis_combo(base.z)
            form.addRow("Value (colour)", self.z_combo)
            self.show_points_chk = QCheckBox("Show measured points")
            self.show_points_chk.setChecked(bool(base.show_points))
            form.addRow("", self.show_points_chk)
        else:
            self.x_combo = axis_combo(base.x)
            form.addRow("X", self.x_combo)
            self.y_combo = axis_combo(base.y)
            form.addRow("Y", self.y_combo)
            if base.is_3d:
                self.z_combo = axis_combo(base.z)
                form.addRow("Z", self.z_combo)
            self.color_combo = fix_combo(QComboBox())
            self.color_combo.addItem(_NONE)
            self.color_combo.addItems(self._columns)
            if base.color in self._columns:
                self.color_combo.setCurrentText(base.color)
            form.addRow("Colour by", self.color_combo)
            if base.is_single_layer:
                # Static 2D scatter of one chosen layer (no scrub slider).
                self.sl_layer = LayerSpinBox()
                if self._layers:
                    self.sl_layer.set_layers(
                        self._layers,
                        self._current if self._current is not None
                        else self._layers[0])
                form.addRow("Layer", self.sl_layer)
        lay.addLayout(form)

        # These kinds carry no layer-span row: a Layer Viewer scrubs with its own
        # slider; Single Layer picks its layer above; CoV / Contour summarise the
        # whole build (all layers).
        self._is_layer_viewer = base.is_layer_viewer
        self._is_single_layer = base.is_single_layer
        if (self._is_layer_viewer or self._is_single_layer
                or base.is_cov or base.is_contour):
            self._add_buttons(lay)
            self.setMinimumWidth(440)
            return

        # Layer span this plot queries — its own, independent of the grid.
        # Default: all layers for 3D/bar/histogram (summary views); the current
        # layer for a 2D scatter (a top-down view overplots layers).
        span_row = QHBoxLayout()
        self.radio_all = QRadioButton("All layers")
        self.radio_single = QRadioButton("Single")
        self.radio_range = QRadioButton("Range")
        grp = QButtonGroup(self)
        for r in (self.radio_all, self.radio_single, self.radio_range):
            grp.addButton(r)
        # Single-layer entry (its own spinbox for quick layer typing) +
        # range lo/hi — all snap to available layers.
        self.single_spin = LayerSpinBox()
        self.lo_spin = LayerSpinBox()
        self.hi_spin = LayerSpinBox()
        for sb in (self.single_spin, self.lo_spin, self.hi_spin):
            sb.setFixedWidth(80)
        if self._layers:
            self.single_spin.set_layers(
                self._layers,
                self._current if self._current is not None else self._layers[0],
            )
            self.lo_spin.set_layers(self._layers, self._layers[0])
            self.hi_spin.set_layers(self._layers, self._layers[-1])
        if base.is_3d or base.is_bar or base.is_hist:
            self.radio_all.setChecked(True)
        else:
            self.radio_single.setChecked(True)
        self._sync_span_enabled()
        self.radio_single.toggled.connect(lambda _c: self._sync_span_enabled())
        self.radio_range.toggled.connect(lambda _c: self._sync_span_enabled())
        span_row.addWidget(QLabel("Layers"))
        span_row.addWidget(self.radio_all)
        span_row.addWidget(self.radio_single)
        span_row.addWidget(self.single_spin)
        span_row.addWidget(self.radio_range)
        span_row.addWidget(self.lo_spin)
        span_row.addWidget(QLabel("to"))
        span_row.addWidget(self.hi_spin)
        span_row.addStretch(1)
        lay.addLayout(span_row)

        self._add_buttons(lay)
        self.setMinimumWidth(480)

    def _add_buttons(self, lay) -> None:
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Plot")
        ok.setIcon(QIcon())      # drop the themed check icon
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())  # drop the themed cross icon
        lay.addWidget(buttons)

    def _sync_span_enabled(self) -> None:
        self.single_spin.setEnabled(self.radio_single.isChecked())
        on_range = self.radio_range.isChecked()
        self.lo_spin.setEnabled(on_range)
        self.hi_spin.setEnabled(on_range)

    def spec(self) -> PlotSpec:
        if self.bins_spin is not None:  # histogram
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y="count",
                color=None,
                bins=self.bins_spin.value(),
            )
        if self.cov_mode_combo is not None:  # CoV summary
            grp = self.x_combo.currentText()
            return PlotSpec(
                kind=self._kind,
                x=grp,
                y=self.y_combo.currentText(),
                color=None,  # bars colour by their value
                group_by=grp,
                cov_mode=self.cov_mode_combo.currentText(),
            )
        if self.agg_combo is not None:  # bar
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y=self.y_combo.currentText(),
                color=None,  # bars colour by their value
                agg=self.agg_combo.currentText(),
            )
        if self.show_points_chk is not None:  # contour
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y=self.y_combo.currentText(),
                z=self.z_combo.currentText(),  # the contour value
                color=None,
                show_points=self.show_points_chk.isChecked(),
            )
        color = self.color_combo.currentText()
        return PlotSpec(
            kind=self._kind,
            x=self.x_combo.currentText(),
            y=self.y_combo.currentText(),
            z=self.z_combo.currentText() if self.z_combo is not None else None,
            color=None if color == _NONE else color,
        )

    def span(self) -> tuple:
        """("single", L, L), ("all", None, None) or ("range", lo, hi)."""
        if self._is_layer_viewer:  # starts on the current layer; slider scrubs
            return ("single", self._current, self._current)
        if self._is_single_layer:  # the layer chosen in the form
            L = self.sl_layer.value() if self.sl_layer is not None else self._current
            return ("single", L, L)
        if not hasattr(self, "radio_single"):  # CoV / Contour: whole build
            return ("all", None, None)
        if self.radio_single.isChecked():
            L = self.single_spin.value()
            return ("single", L, L)
        if self.radio_range.isChecked():
            return ("range", self.lo_spin.value(), self.hi_spin.value())
        return ("all", None, None)
