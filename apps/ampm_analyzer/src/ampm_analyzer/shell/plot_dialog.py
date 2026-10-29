"""New-plot dialog: pick which column goes on each channel.

Dumb by design — every combo lists *all* columns, so any column can be X, Y, Z
or the colour. Defaults come from plotspec.default_spec but are freely changed.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from .plotspec import BAR_AGGS, PlotSpec, default_spec
from .toolbars import LayerSpinBox

_NONE = "— none —"


class NewPlotDialog(QDialog):
    def __init__(self, kind: str, columns, layers=None, current_layer=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"New {kind}")
        self._kind = kind
        self._columns = list(columns)
        self._layers = list(layers or [])
        self._current = (
            current_layer if current_layer is not None
            else (self._layers[0] if self._layers else None)
        )
        base = default_spec(kind, self._columns)

        lay = QVBoxLayout(self)
        form = QFormLayout()

        def axis_combo(selected: str | None) -> QComboBox:
            cb = QComboBox()
            cb.addItems(self._columns)
            if selected in self._columns:
                cb.setCurrentIndex(self._columns.index(selected))
            return cb

        self.agg_combo = None
        self.z_combo = None
        self.color_combo = None
        self.bins_spin = None
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
            self.agg_combo = QComboBox()
            self.agg_combo.addItems(BAR_AGGS)
            self.agg_combo.setCurrentText(base.agg)
            form.addRow("Aggregate", self.agg_combo)
        else:
            self.x_combo = axis_combo(base.x)
            form.addRow("X", self.x_combo)
            self.y_combo = axis_combo(base.y)
            form.addRow("Y", self.y_combo)
            if base.is_3d:
                self.z_combo = axis_combo(base.z)
                form.addRow("Z", self.z_combo)
            self.color_combo = QComboBox()
            self.color_combo.addItem(_NONE)
            self.color_combo.addItems(self._columns)
            if base.color in self._columns:
                self.color_combo.setCurrentText(base.color)
            form.addRow("Colour by", self.color_combo)
        lay.addLayout(form)

        # Layer span this plot queries — its own, independent of the grid.
        # Default: the current layer for 2D (a top-down view overplots layers),
        # all layers for 3D.
        span_row = QHBoxLayout()
        cur_label = f"This layer ({self._current})" if self._current is not None \
            else "This layer"
        self.radio_single = QRadioButton(cur_label)
        self.radio_all = QRadioButton("All layers")
        self.radio_range = QRadioButton("Range")
        grp = QButtonGroup(self)
        for r in (self.radio_single, self.radio_all, self.radio_range):
            grp.addButton(r)
        if base.is_3d or base.is_bar or base.is_hist:
            self.radio_all.setChecked(True)  # summary/3D views span all layers
        else:
            self.radio_single.setChecked(True)
        self.lo_spin = LayerSpinBox()
        self.hi_spin = LayerSpinBox()
        for sb in (self.lo_spin, self.hi_spin):
            sb.setFixedWidth(80)
        if self._layers:
            self.lo_spin.set_layers(self._layers, self._layers[0])
            self.hi_spin.set_layers(self._layers, self._layers[-1])
        self._sync_range_enabled()
        self.radio_range.toggled.connect(lambda _c: self._sync_range_enabled())
        span_row.addWidget(QLabel("Layers"))
        span_row.addWidget(self.radio_single)
        span_row.addWidget(self.radio_all)
        span_row.addWidget(self.radio_range)
        span_row.addWidget(self.lo_spin)
        span_row.addWidget(QLabel("to"))
        span_row.addWidget(self.hi_spin)
        span_row.addStretch(1)
        lay.addLayout(span_row)

        hint = QLabel(
            "Any column can go on any channel. Numeric colour → colormap; "
            "a label column → discrete colours + legend."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _sync_range_enabled(self) -> None:
        on = self.radio_range.isChecked()
        self.lo_spin.setEnabled(on)
        self.hi_spin.setEnabled(on)

    def spec(self) -> PlotSpec:
        if self.bins_spin is not None:  # histogram
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y="count",
                color=None,
                bins=self.bins_spin.value(),
            )
        if self.agg_combo is not None:  # bar
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y=self.y_combo.currentText(),
                color=None,  # bars colour by their value
                agg=self.agg_combo.currentText(),
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
        if self.radio_single.isChecked():
            return ("single", self._current, self._current)
        if self.radio_range.isChecked():
            return ("range", self.lo_spin.value(), self.hi_spin.value())
        return ("all", None, None)
