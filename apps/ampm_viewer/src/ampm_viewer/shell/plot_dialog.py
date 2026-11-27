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
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .card import DraggableCard
from .plotdata import LABEL_MAX
from .plotspec import (
    BANDWIDTHS,
    BAR_AGGS,
    COV_MODES,
    ERROR_NAMES,
    ERRORS,
    SCATTER_2D,
    STAT_NAMES,
    STATS,
    PlotSpec,
    default_spec,
    repeat_base,
)
from .toolbars import LayerSpinBox
from .widgets import fix_combo

_NONE = "— none —"
_NONE_2D = "None (2D)"
_EVERY_ROW = "Every row"

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class NewPlotDialog(DraggableCard, QDialog):
    def __init__(self, kind: str, columns, layers=None, current_layer=None,
                 parent=None, *, renames=None, dbscan=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"New {kind}")
        self._kind = kind
        self._columns = list(columns)
        self._layers = list(layers or [])
        self._current = (
            current_layer if current_layer is not None
            else (self._layers[0] if self._layers else None)
        )
        base = default_spec(kind, self._columns, renames, dbscan=dbscan)

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
        self.group_combo = None
        self.bw_combo = None
        self.box_chk = None
        self.k_spin = None
        self.epsxy_spin = None
        self.epsz_spin = None
        self.values_list = None
        self.error_combo = None
        self.per_combo = None     # 2D scatter: one point per group
        self.x_stat = self.y_stat = None
        self.fit_chk = None       # 2D scatter / Mean ± SD: the trend line
        self.shape_combo = None   # ...a marker shape per value of a column
        self.label_combo = None   # ...a text by each point
        self.xerr_chk = None      # Mean ± SD: error bars on X too
        self._per_touched_span = False

        def stat_combo(current: str) -> QComboBox:
            cb = fix_combo(QComboBox())
            for key in STATS:
                cb.addItem(STAT_NAMES[key], key)
            cb.setCurrentIndex(STATS.index(current) if current in STATS else 0)
            cb.setToolTip("What the point shows of each group's rows")
            return cb

        def with_stat(axis: QComboBox, stat: QComboBox) -> QWidget:
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(axis, 1)
            row.addWidget(stat)
            return box

        def fit_check(on: bool) -> QCheckBox:
            chk = QCheckBox("Trend line (equation, R\u00b2, p)")
            chk.setChecked(bool(on))
            chk.setToolTip("A least-squares straight line through the points, "
                           "labelled with its equation, R\u00b2 and p")
            return chk

        def mark_combo(current, tip: str) -> QComboBox:
            cb = fix_combo(QComboBox())
            cb.addItem(_NONE)
            cb.addItems(self._columns)
            if current in self._columns:
                cb.setCurrentText(current)
            cb.setToolTip(tip)
            return cb

        def add_marks(form) -> None:
            """Shape by / Label points (2D scatter, Mean ± SD)."""
            self.shape_combo = mark_combo(
                base.shape_by, "A different marker shape for each value of "
                "this column (a build orientation, say), with a key")
            form.addRow("Shape by", self.shape_combo)
            self.label_combo = mark_combo(
                base.label_by, "Write this column's value by each point (a "
                f"specimen's name, say); up to {LABEL_MAX} points")
            form.addRow("Label points", self.label_combo)

        def bandwidth_combo(current: str) -> QComboBox:
            cb = fix_combo(QComboBox())
            cb.addItems([b.capitalize() for b in BANDWIDTHS])
            cb.setCurrentText(current.capitalize())
            cb.setToolTip("How smooth the density is: Scott's or Silverman's "
                          "rule, as in scipy's gaussian_kde")
            return cb

        if base.is_kde:
            # KDE: a column's density, optionally one curve per group.
            self.x_combo = axis_combo(base.x)
            form.addRow("Column", self.x_combo)
            self.y_combo = None
            self.group_combo = fix_combo(QComboBox())
            self.group_combo.addItem(_NONE)
            self.group_combo.addItems(self._columns)
            if base.group_by in self._columns:
                self.group_combo.setCurrentText(base.group_by)
            form.addRow("One curve per", self.group_combo)
            self.bw_combo = bandwidth_combo(base.bandwidth)
            form.addRow("Bandwidth", self.bw_combo)
        elif base.is_violin:
            # Violin: a value's distribution per category.
            self.x_combo = axis_combo(base.x)
            form.addRow("Category", self.x_combo)
            self.y_combo = axis_combo(base.y)
            form.addRow("Value", self.y_combo)
            self.bw_combo = bandwidth_combo(base.bandwidth)
            form.addRow("Bandwidth", self.bw_combo)
            self.box_chk = QCheckBox("Show quartile box and median")
            self.box_chk.setChecked(bool(base.show_box))
            form.addRow("", self.box_chk)
        elif base.is_kdist:
            # K-distance: DBSCAN's neighbourhood, to read eps off the elbow.
            self.x_combo = axis_combo(base.x)
            form.addRow("X", self.x_combo)
            self.y_combo = axis_combo(base.y)
            form.addRow("Y", self.y_combo)
            self.z_combo = fix_combo(QComboBox())
            self.z_combo.addItem(_NONE_2D)
            self.z_combo.addItems(self._columns)
            if base.z in self._columns:
                self.z_combo.setCurrentText(base.z)
            form.addRow("Z", self.z_combo)
            self.k_spin = QSpinBox()
            self.k_spin.setRange(1, 500)
            self.k_spin.setValue(int(base.k))
            self.k_spin.setToolTip("Which neighbour to measure: use the "
                                   "min_samples you plan to give DBSCAN")
            form.addRow("Neighbour (k)", self.k_spin)
            self.epsxy_spin = self._radius_spin(base.eps_xy)
            self.epsxy_spin.setToolTip("DBSCAN's XY radius, in mm. Drawn on the "
                                       "plot as a dashed line to compare with "
                                       "the elbow.")
            form.addRow("XY radius (eps)", self.epsxy_spin)
            self.epsz_spin = self._radius_spin(base.eps_z)
            self.epsz_spin.setToolTip("DBSCAN's Z radius, in mm. Only the ratio "
                                      "to the XY radius matters here: it scales "
                                      "Z before the distances are measured.")
            form.addRow("Z radius", self.epsz_spin)
            self.z_combo.currentTextChanged.connect(
                lambda t: self.epsz_spin.setEnabled(t != _NONE_2D))
            self.epsz_spin.setEnabled(self.z_combo.currentText() != _NONE_2D)
        elif base.is_hist:
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
        elif base.is_meansd:
            # Mean ± SD: one point per group, the mean of its value columns
            # (a measurement and its repeats) with an error bar.
            self.x_combo = axis_combo(base.x)
            form.addRow("X", self.x_combo)
            self.y_combo = None
            self.values_list = QListWidget()
            self.values_list.setToolTip(
                "Tick the measurement and its repeats, e.g. Density (1), "
                "Density (2), Density (3): each point is their mean")
            chosen = set(base.values)
            for c in self._columns:
                item = QListWidgetItem(c)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if c in chosen
                                   else Qt.CheckState.Unchecked)
                self.values_list.addItem(item)
            self.values_list.setMaximumHeight(150)
            if base.values and base.values[0] in self._columns:
                self.values_list.scrollToItem(
                    self.values_list.item(self._columns.index(base.values[0])))
            self.values_list.itemChanged.connect(self._on_value_ticked)
            form.addRow("Values", self.values_list)
            self.group_combo = fix_combo(QComboBox())
            self.group_combo.addItems(self._columns)
            if base.group_by in self._columns:
                self.group_combo.setCurrentText(base.group_by)
            form.addRow("One point per", self.group_combo)
            self.error_combo = fix_combo(QComboBox())
            for key in ERRORS:
                self.error_combo.addItem(ERROR_NAMES[key], key)
            self.error_combo.setCurrentIndex(ERRORS.index(base.error))
            form.addRow("Error bars", self.error_combo)
            self.xerr_chk = QCheckBox("On X too")
            self.xerr_chk.setChecked(bool(base.x_error))
            self.xerr_chk.setToolTip(
                "Error bars across as well, from X's spread within each "
                "group (when X differs between a group's parts)")
            form.addRow("", self.xerr_chk)
            self.color_combo = fix_combo(QComboBox())
            self.color_combo.addItem(_NONE)
            self.color_combo.addItems(self._columns)
            form.addRow("Colour by", self.color_combo)
            add_marks(form)
            self.fit_chk = fit_check(base.fit)
            form.addRow("", self.fit_chk)
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
        elif kind == SCATTER_2D:
            # Every row, or one point per group (a part, a specimen): its
            # X and Y then a statistic of the group's rows.
            self.per_combo = fix_combo(QComboBox())
            self.per_combo.addItem(_EVERY_ROW)
            self.per_combo.addItems(self._columns)
            self.per_combo.setToolTip(
                "One point per value of this column (each part, say): its X "
                "and Y are the statistic chosen beside them, over its rows")
            if base.per in self._columns:
                self.per_combo.setCurrentText(base.per)
            form.addRow("One point per", self.per_combo)
            self.x_combo = axis_combo(base.x)
            self.x_stat = stat_combo(base.x_stat)
            form.addRow("X", with_stat(self.x_combo, self.x_stat))
            self.y_combo = axis_combo(base.y)
            self.y_stat = stat_combo(base.y_stat)
            form.addRow("Y", with_stat(self.y_combo, self.y_stat))
            self.color_combo = fix_combo(QComboBox())
            self.color_combo.addItem(_NONE)
            self.color_combo.addItems(self._columns)
            if base.color in self._columns:
                self.color_combo.setCurrentText(base.color)
            form.addRow("Colour by", self.color_combo)
            add_marks(form)
            self.fit_chk = fit_check(base.fit)
            form.addRow("", self.fit_chk)
            self.per_combo.currentIndexChanged.connect(self._on_per_changed)
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
                or base.is_cov or base.is_contour or base.is_meansd):
            self._add_buttons(lay)
            self.setMinimumWidth(440)
            self._on_value_ticked()
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
        if (base.is_3d or base.is_bar or base.is_hist or base.is_kde
                or base.is_violin or base.is_kdist):
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
        # (a 2D scatter's X / Y rows carry a statistic beside the column)
        self.setMinimumWidth(580 if self.per_combo is not None else 480)
        self._on_per_changed()

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
        self._ok = ok
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())  # drop the themed cross icon
        lay.addWidget(buttons)

    def _ticked(self) -> list[str]:
        if self.values_list is None:
            return []
        return [self.values_list.item(i).text()
                for i in range(self.values_list.count())
                if self.values_list.item(i).checkState() == Qt.CheckState.Checked]

    def _on_value_ticked(self, item=None) -> None:
        """Mean ± SD: ticking one of a set of repeats ticks the rest
        (``Density (1)`` -> (2), (3)); Plot needs at least one value."""
        if self.values_list is None:
            return
        if item is not None and item.checkState() == Qt.CheckState.Checked:
            base = repeat_base(item.text())
            if base != item.text():
                self.values_list.blockSignals(True)
                for i in range(self.values_list.count()):
                    other = self.values_list.item(i)
                    if repeat_base(other.text()) == base:
                        other.setCheckState(Qt.CheckState.Checked)
                self.values_list.blockSignals(False)
        if getattr(self, "_ok", None) is not None:
            self._ok.setEnabled(bool(self._ticked()))

    def _marks(self) -> dict:
        """The shape and label columns chosen (None: not used)."""
        out = {}
        for name, combo in (("shape_by", self.shape_combo),
                            ("label_by", self.label_combo)):
            text = combo.currentText() if combo is not None else _NONE
            out[name] = None if text == _NONE else text
        return out

    def _per(self) -> str | None:
        if self.per_combo is None or self.per_combo.currentText() == _EVERY_ROW:
            return None
        return self.per_combo.currentText()

    def _on_per_changed(self, _index=None) -> None:
        """2D scatter: the statistics only mean something per group; a group
        (a part) is usually wanted whole, so the span moves to All layers the
        first time one is chosen."""
        if self.per_combo is None:
            return
        per = self._per() is not None
        for stat in (self.x_stat, self.y_stat):
            stat.setVisible(per)
        if per and not self._per_touched_span and hasattr(self, "radio_all"):
            self._per_touched_span = True
            self.radio_all.setChecked(True)

    def _sync_span_enabled(self) -> None:
        self.single_spin.setEnabled(self.radio_single.isChecked())
        on_range = self.radio_range.isChecked()
        self.lo_spin.setEnabled(on_range)
        self.hi_spin.setEnabled(on_range)

    @staticmethod
    def _radius_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(0.001, 1000.0)
        spin.setSingleStep(0.01)
        spin.setSuffix(" mm")
        spin.setValue(float(value))
        return spin

    def spec(self) -> PlotSpec:
        if self.k_spin is not None:  # k-distance
            z = self.z_combo.currentText()
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y=self.y_combo.currentText(),
                z=None if z == _NONE_2D else z,
                k=self.k_spin.value(),
                eps_xy=self.epsxy_spin.value(),
                eps_z=self.epsz_spin.value(),
            )
        if self.values_list is not None:  # mean-sd
            values = self._ticked()
            color = self.color_combo.currentText()
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y=values[0] if values else "",
                more_y=tuple(values[1:]),
                group_by=self.group_combo.currentText() or None,
                error=self.error_combo.currentData() or "sd",
                color=None if color == _NONE else color,
                fit=self.fit_chk.isChecked(),
                x_error=self.xerr_chk.isChecked(),
                **self._marks(),
            )
        if self.group_combo is not None:  # KDE
            grp = self.group_combo.currentText()
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y="density",
                group_by=None if grp == _NONE else grp,
                bandwidth=self.bw_combo.currentText().lower(),
            )
        if self.box_chk is not None:  # violin
            return PlotSpec(
                kind=self._kind,
                x=self.x_combo.currentText(),
                y=self.y_combo.currentText(),
                bandwidth=self.bw_combo.currentText().lower(),
                show_box=self.box_chk.isChecked(),
            )
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
        extra = {}
        if self.per_combo is not None:  # 2D scatter
            extra = {"per": self._per(), "fit": self.fit_chk.isChecked(),
                     **self._marks(),
                     "x_stat": self.x_stat.currentData() or "mean",
                     "y_stat": self.y_stat.currentData() or "mean"}
        return PlotSpec(
            kind=self._kind,
            x=self.x_combo.currentText(),
            y=self.y_combo.currentText(),
            z=self.z_combo.currentText() if self.z_combo is not None else None,
            color=None if color == _NONE else color,
            **extra,
        )

    def span(self) -> tuple:
        """("single", L, L), ("all", None, None) or ("range", lo, hi)."""
        if self._is_layer_viewer:  # starts on the current layer; slider scrubs
            return ("single", self._current, self._current)
        if self._is_single_layer:  # the layer chosen in the form
            L = self.sl_layer.value() if self.sl_layer is not None else self._current
            return ("single", L, L)
        if not hasattr(self, "radio_single"):  # CoV / Contour / Mean ± SD: whole build
            return ("all", None, None)
        if self.radio_single.isChecked():
            L = self.single_spin.value()
            return ("single", L, L)
        if self.radio_range.isChecked():
            return ("range", self.lo_spin.value(), self.hi_spin.value())
        return ("all", None, None)
