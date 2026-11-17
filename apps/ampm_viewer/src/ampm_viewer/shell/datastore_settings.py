"""DataStore setup page (backstage).

Reached via New (always) or Open-with-no-cache. Four foldable groups:

- **Build inputs**: the packet source, .dhxml, STL and parts CSV found in the
  build folder, each with Browse... to choose another (``browseRequested``;
  the controller writes it to config.toml);
- **Layers**: thickness, and all layers or a From / To range;
- **Columns**: which source columns load, and a rename for each;
- **Processing**: masking, part assignment (with its settings and a Part
  filter of the parts to keep) and the melt-pool correction.

A choice's availability derives from the inputs. The controller performs the
build; this widget collects the choices (``scope``, ``thickness``,
``recipe``) and emits ``buildRequested``.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .widgets import CollapsibleGroup, Disclosure, fix_combo

_DEFAULT_THICKNESS = 0.03  # mm — fallback when a build has nothing to detect from
# DBSCAN defaults when config.toml has none (ohpal's [clustering] defaults).
# overlap_layers None = enough for the Z radius (worked out per build).
_DBSCAN_DEFAULTS = {"eps_xy": 0.3, "eps_z": 0.06, "min_samples": 10,
                    "layers_per_chunk": 11, "overlap_layers": None}

# The build inputs a user can point at themselves (Browse...): config key,
# label, and whether it's a folder.
INPUTS = (("SOURCE", "Packet source", True), ("DHXML", "DHXML", False),
          ("STL", "STL", False), ("PARTS_CSV", "Parts CSV", False))

_MISSING = "— not found —"

# Always loaded (coordinates + layer/Z + the mask-keep key): locked on, and
# never removable from the grid (see controller.remove_columns).
# LaserVIEW rides along because the melt-pool correction needs it, and a
# default import that left it out silently disabled Correction.
REQUIRED_COLUMNS = {"Demand X", "Demand Y", "Start time", "layer", "Z",
                    "LaserVIEW (mean)"}
_ALWAYS = REQUIRED_COLUMNS

# Correction is calibrated for exactly one machine + signal for now; the melt-pool
# and LaserVIEW columns must both be loaded for it to run (see correction.py).
_CORR_MACHINES = ["MAIN"]
_CORR_COLUMN = "MeltVIEW melt pool (mean)"
_CORR_LASER_COLUMN = "LaserVIEW (mean)"

# Fixed default import set (besides the always-required columns) and the renames
# applied to a fresh build, so a new DataStore lands ready to go.
_DEFAULT_IMPORT = [
    "Duration",
    "Demand laser power (mean)",
    "MeltVIEW plasma (mean)",
    "MeltVIEW melt pool (mean)",
    "Laser output power (mean)",
]
_DEFAULT_RENAMES = {
    "Demand X": "X",
    "Demand Y": "Y",
    "Demand laser power (mean)": "Demand Power",
    "MeltVIEW plasma (mean)": "Plasma",
    "MeltVIEW melt pool (mean)": "Meltpool",
    "Laser output power (mean)": "Output power",
}

# Accent (primary) button — mirrors the other dialogs' primary style via palette.
_ACCENT_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 7px 22px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class _ColumnRow:
    """Holds one import-checklist row's widgets — an include toggle (the column
    name), a muted arrow, and an optional rename box. The widgets are placed in a
    shared grid (see _make_cols_host) so the rename boxes line up columnarly.
    Required columns are locked on but still renameable."""

    def __init__(self, name: str, *, locked: bool = False) -> None:
        self.name = name
        self.locked = locked
        self.chk = QCheckBox(name)
        self.chk.setChecked(True)
        if locked:
            self.chk.setEnabled(False)  # always imported
            self.chk.setToolTip("Always imported (required column)")
        self.arrow = QLabel("→")
        self.arrow.setStyleSheet("color: palette(mid);")
        self.rename = QLineEdit()
        self.rename.setPlaceholderText("rename…")
        self.rename.setClearButtonEnabled(True)
        self.rename.setFixedWidth(150)

    def included(self) -> bool:
        return self.chk.isChecked()

    def new_name(self) -> str:
        return self.rename.text().strip()

    def set_state(self, *, included: bool, rename: str) -> None:
        if not self.locked:
            self.chk.setChecked(included)
        self.rename.setText(rename or "")


def _value_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    return lab


class DataStoreSettings(QWidget):
    buildRequested = pyqtSignal()
    cancelRequested = pyqtSignal()  # leave the setup surface, back to backstage
    browseRequested = pyqtSignal(str)  # an INPUTS key: choose that input

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Who lists the parts a method assigns, for the Part filter:
        # ``part_lister(method) -> [part ids]`` (set by the window).
        self.part_lister = None
        self._stack = False
        self._excluded: set[str] = set()
        self._parts_for = None  # the method the Part filter list was made for

        lay = QVBoxLayout(self)
        # Room on the right, so nothing sits against the page's scrollbar.
        lay.setContentsMargins(0, 0, 18, 0)
        lay.setSpacing(14)

        self.grp_inputs = self._config_group()
        self.grp_layers = self._scope_group()
        self.grp_columns = self._columns_group()
        self.grp_processing = self._processing_group()
        for grp in (self.grp_inputs, self.grp_layers, self.grp_columns,
                    self.grp_processing):
            lay.addWidget(grp)

        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancelRequested)
        row.addWidget(self.cancel_btn)
        self.build_btn = QPushButton("Build DataStore")
        self.build_btn.setStyleSheet(_ACCENT_QSS)
        self.build_btn.clicked.connect(self.buildRequested)
        row.addWidget(self.build_btn)
        lay.addLayout(row)
        lay.addStretch(1)

    # -- groups --------------------------------------------------------
    def _config_group(self) -> CollapsibleGroup:
        box = CollapsibleGroup("Build inputs")
        grid = QGridLayout(box.body)
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(1, 1)
        self.input_labels: dict[str, QLabel] = {}
        self.input_values: dict[str, QLabel] = {}
        self.browse_buttons: dict[str, QPushButton] = {}
        for row, (key, label, _folder) in enumerate(INPUTS):
            name = QLabel(label)
            value = _value_label(_MISSING)
            browse = QPushButton("Browse…")
            browse.clicked.connect(lambda _c, k=key: self.browseRequested.emit(k))
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            grid.addWidget(browse, row, 2)
            self.input_labels[key] = name
            self.input_values[key] = value
            self.browse_buttons[key] = browse
        self.lbl_source_key = self.input_labels["SOURCE"]
        self.lbl_source = self.input_values["SOURCE"]
        self.lbl_dhxml = self.input_values["DHXML"]
        self.lbl_stl = self.input_values["STL"]
        self.lbl_csv = self.input_values["PARTS_CSV"]
        return box

    def _scope_group(self) -> CollapsibleGroup:
        box = CollapsibleGroup("Layers")
        grid = QGridLayout(box.body)
        grid.setHorizontalSpacing(8)

        # Thickness (mm): detected, editable (so a build with nothing to
        # detect from can still be given one).
        self.thickness_spin = QDoubleSpinBox()
        self.thickness_spin.setDecimals(3)
        self.thickness_spin.setRange(0.001, 5.0)
        self.thickness_spin.setSingleStep(0.005)
        self.thickness_spin.setValue(_DEFAULT_THICKNESS)
        self.thickness_spin.setFixedWidth(90)
        grid.addWidget(QLabel("Thickness (mm)"), 0, 0)
        grid.addWidget(self.thickness_spin, 0, 1)

        self.chk_all_layers = QCheckBox("All layers")
        self.chk_all_layers.setChecked(True)
        self.chk_all_layers.toggled.connect(self._sync_scope_enabled)
        grid.addWidget(self.chk_all_layers, 1, 0, 1, 2)

        # A range, live once All layers is off.
        self.layer_min = QSpinBox()
        self.layer_max = QSpinBox()
        for s in (self.layer_min, self.layer_max):
            s.setRange(1, 100_000)
            s.setFixedWidth(90)
        rng = QHBoxLayout()
        rng.setContentsMargins(0, 0, 0, 0)
        rng.setSpacing(8)
        self.lbl_from = QLabel("From")
        self.lbl_to = QLabel("To")
        for w in (self.lbl_from, self.layer_min, self.lbl_to, self.layer_max):
            rng.addWidget(w)
        rng.addSpacing(10)
        self.lbl_available = QLabel("")
        self.lbl_available.setStyleSheet("color: palette(placeholder-text);")
        rng.addWidget(self.lbl_available)
        rng.addStretch(1)
        grid.addLayout(rng, 2, 0, 1, 4)
        grid.setColumnStretch(3, 1)  # keep everything left
        self._sync_scope_enabled()
        return box

    def _sync_scope_enabled(self) -> None:
        on = not self.chk_all_layers.isChecked()
        for w in (self.lbl_from, self.layer_min, self.lbl_to, self.layer_max):
            w.setEnabled(on)

    def _columns_group(self) -> CollapsibleGroup:
        """Which columns the store loads, and an optional rename for each. Always-
        required ones are locked on. A fresh build opens with the fixed default
        set + renames already applied (see set_config)."""
        box = CollapsibleGroup("Columns")
        v = QVBoxLayout(box.body)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.btn_cols_all = QPushButton("All")
        self.btn_cols_none = QPushButton("None")
        self.btn_cols_default = QPushButton("Default")
        self.btn_clear_renames = QPushButton("Clear renames")
        self.btn_cols_all.setToolTip("Load every column")
        self.btn_cols_none.setToolTip("Load only the required columns")
        self.btn_cols_default.setToolTip(
            "The default columns and renames of a new DataStore")
        self.btn_clear_renames.setToolTip("Remove every rename")
        self.btn_cols_all.clicked.connect(lambda: self.select_columns("all"))
        self.btn_cols_none.clicked.connect(lambda: self.select_columns("none"))
        self.btn_cols_default.clicked.connect(lambda: self.select_columns("default"))
        self.btn_clear_renames.clicked.connect(self.clear_renames)
        buttons.addWidget(self.btn_cols_all)
        buttons.addWidget(self.btn_cols_none)
        buttons.addWidget(self.btn_cols_default)
        buttons.addSpacing(16)
        buttons.addWidget(self.btn_clear_renames)
        buttons.addStretch(1)
        v.addLayout(buttons)

        self._col_rows: list[_ColumnRow] = []
        self._cols_area = QScrollArea()
        self._cols_area.setWidgetResizable(True)
        self._cols_area.setFixedHeight(190)
        self._cols_area.setWidget(self._make_cols_host([]))
        v.addWidget(self._cols_area)
        return box

    def _make_cols_host(self, rows: list[_ColumnRow]) -> QWidget:
        """Lay the rows out in one grid so the arrows and rename boxes align into
        columns (grid column 0 sizes to the widest column name)."""
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(2, 2, 2, 2)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        for i, r in enumerate(rows):
            grid.addWidget(r.chk, i, 0)
            grid.addWidget(r.arrow, i, 1)
            grid.addWidget(r.rename, i, 2)
        grid.setColumnStretch(3, 1)       # keep everything left-packed
        grid.setRowStretch(len(rows), 1)  # rows hug the top
        return host

    def _default_columns(self) -> set[str]:
        # A stacked build's step and Build time come by default.
        return (set(_DEFAULT_IMPORT) | set(_ALWAYS)
                | ({"step", "Build time"} if self._stack else set()))

    def select_columns(self, which: str) -> None:
        """All / None (locked columns stay on) / Default: the columns and
        renames a new DataStore starts with."""
        if which == "default":
            self._apply_column_state(included=self._default_columns(),
                                     renames=_DEFAULT_RENAMES)
            return
        for r in self._col_rows:
            if not r.locked:
                r.chk.setChecked(which == "all")

    def clear_renames(self) -> None:
        for r in self._col_rows:
            r.rename.clear()

    def _processing_group(self) -> CollapsibleGroup:
        """Recipe defined with the DataStore: mask / assign parts / correction.

        Each control is disabled when its input is missing (reason in tooltip);
        changing these means reconfiguring + rebuilding the store.
        """
        box = CollapsibleGroup("Processing")
        f = QFormLayout(box.body)

        self.chk_mask = QCheckBox("Apply mask")
        f.addRow("Masking", self.chk_mask)

        # Part assignment leads with a toggle (to match masking/correction), with
        # the method beside it; None is simply the toggle being off.
        self.chk_parts = QCheckBox("Assign parts")
        self.cmb_parts = fix_combo(QComboBox())
        self.cmb_parts.addItems(["Direct", "DHXML", "DBSCAN"])
        parts_row = QHBoxLayout()
        parts_row.setContentsMargins(0, 0, 0, 0)
        parts_row.addWidget(self.chk_parts)
        parts_row.addWidget(self.cmb_parts, 1)
        parts_w = QWidget()
        parts_w.setLayout(parts_row)
        f.addRow("Part assignment", parts_w)

        # Direct: how far a point may be from a part and still join it.
        self.direct_detail = QWidget()
        dr = QFormLayout(self.direct_detail)
        dr.setContentsMargins(16, 2, 0, 0)
        self.spin_max_distance = QDoubleSpinBox()
        self.spin_max_distance.setDecimals(2)
        self.spin_max_distance.setRange(0.0, 1000.0)
        self.spin_max_distance.setSingleStep(0.5)
        self.spin_max_distance.setSpecialValueText("No limit")
        self.spin_max_distance.setFixedWidth(110)
        self.spin_max_distance.setToolTip(
            "A point further than this from every part's centre is left "
            "without a part. 0: no limit (every point joins its nearest part).")
        dr.addRow("Max distance (mm)", self.spin_max_distance)
        self.direct_detail.setVisible(False)
        f.addRow("", self.direct_detail)

        # DBSCAN's settings, revealed with it. They start from config.toml and
        # are kept with the build.
        self.dbscan_detail = QWidget()
        dd = QFormLayout(self.dbscan_detail)
        dd.setContentsMargins(16, 2, 0, 0)

        def radius(tip: str) -> QDoubleSpinBox:
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(0.001, 50.0)
            spin.setSingleStep(0.01)
            spin.setFixedWidth(110)
            spin.setToolTip(tip)
            return spin

        def count(lo: int, hi: int, tip: str) -> QSpinBox:
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setFixedWidth(110)
            spin.setToolTip(tip)
            return spin

        self.spin_eps_xy = radius(
            "How close points must be in the plane to count as neighbours "
            "(DBSCAN's eps).")
        dd.addRow("XY radius (mm)", self.spin_eps_xy)
        self.spin_eps_z = radius(
            "How close points must be between layers to count as neighbours.")
        dd.addRow("Z radius (mm)", self.spin_eps_z)
        self.spin_min_samples = count(
            1, 10000,
            "How many neighbours a point needs within the radius to start or "
            "grow a cluster (DBSCAN's min_samples).")
        dd.addRow("Min samples", self.spin_min_samples)
        self.spin_layers_per_chunk = count(
            2, 100000,
            "Layers clustered at a time. Fewer use less memory; more run "
            "faster.")
        dd.addRow("Layers per chunk", self.spin_layers_per_chunk)
        self.spin_overlap = count(
            0, 100000,
            "Layers each chunk shares with the next, so clusters join up "
            "across chunks. Auto: just enough for the Z radius.")
        self.spin_overlap.setSpecialValueText("Auto")
        dd.addRow("Overlap chunks", self.spin_overlap)
        self.dbscan_detail.setVisible(False)
        f.addRow("", self.dbscan_detail)
        self.set_dbscan_values(_DBSCAN_DEFAULTS)

        # Part filter: which parts the DataStore keeps (all, by default).
        self.part_filter = Disclosure("Part filter", expanded=False)
        pf = QVBoxLayout(self.part_filter.body)
        pf.setContentsMargins(16, 0, 0, 0)
        pf.setSpacing(4)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.btn_parts_all = QPushButton("All")
        self.btn_parts_none = QPushButton("None")
        self.btn_parts_all.clicked.connect(lambda: self._tick_parts(True))
        self.btn_parts_none.clicked.connect(lambda: self._tick_parts(False))
        prow.addWidget(self.btn_parts_all)
        prow.addWidget(self.btn_parts_none)
        prow.addSpacing(10)
        self.lbl_parts_count = QLabel("")
        self.lbl_parts_count.setStyleSheet("color: palette(placeholder-text);")
        prow.addWidget(self.lbl_parts_count)
        prow.addStretch(1)
        pf.addLayout(prow)
        self.parts_list = QListWidget()
        self.parts_list.setFixedHeight(170)
        self.parts_list.itemChanged.connect(self._on_part_ticked)
        pf.addWidget(self.parts_list)
        self.part_filter.expandedChanged.connect(
            lambda open_: open_ and self.refresh_parts())
        f.addRow("", self.part_filter)

        self.chk_parts.toggled.connect(self._sync_parts_enabled)
        self.cmb_parts.currentIndexChanged.connect(self._sync_parts_enabled)

        self.chk_correction = QCheckBox("Apply correction")
        f.addRow("Correction", self.chk_correction)

        # Correction detail — revealed by the toggle. Only the MAIN machine's
        # MeltVIEW melt-pool (mean) signal is calibrated for now, so both
        # selectors carry a single option (the UI is future-proofed for more).
        # The corrected signal lands in a new named column or overrides the
        # source column.
        self.corr_detail = QWidget()
        cd = QFormLayout(self.corr_detail)
        cd.setContentsMargins(16, 2, 0, 0)

        self.cmb_corr_machine = fix_combo(QComboBox())
        self.cmb_corr_machine.addItems(_CORR_MACHINES)
        cd.addRow("Machine", self.cmb_corr_machine)

        self.cmb_corr_column = fix_combo(QComboBox())
        self.cmb_corr_column.addItems([_CORR_COLUMN])
        cd.addRow("Column", self.cmb_corr_column)

        self.rb_corr_override = QRadioButton("Override column")
        self.rb_corr_new = QRadioButton("New column")
        self.rb_corr_new.setChecked(True)
        self._corr_mode = QButtonGroup(self)
        self._corr_mode.addButton(self.rb_corr_override)
        self._corr_mode.addButton(self.rb_corr_new)
        self.txt_corr_name = QLineEdit()
        self.txt_corr_name.setPlaceholderText("name…")
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addWidget(self.rb_corr_override)
        mode_row.addWidget(self.rb_corr_new)
        mode_row.addWidget(self.txt_corr_name, 1)
        mode_w = QWidget()
        mode_w.setLayout(mode_row)
        cd.addRow("Output", mode_w)

        f.addRow("", self.corr_detail)

        self.chk_correction.toggled.connect(self._sync_correction_enabled)
        self.rb_corr_new.toggled.connect(self._sync_correction_enabled)
        self._sync_correction_enabled()
        return box

    def _sync_correction_enabled(self) -> None:
        """Gate the correction detail on the toggle, and the name box on new-col
        mode (an override writes the source column, so no name is needed)."""
        on = self.chk_correction.isChecked() and self.chk_correction.isEnabled()
        self.corr_detail.setEnabled(on)
        self.txt_corr_name.setEnabled(on and self.rb_corr_new.isChecked())

    def _sync_parts_enabled(self) -> None:
        """The method dropdown is live only while part assignment is toggled on."""
        on = self.chk_parts.isChecked() and self.chk_parts.isEnabled()
        self.cmb_parts.setEnabled(on)
        method = self.cmb_parts.currentText()
        self.direct_detail.setVisible(on and method == "Direct")
        self.dbscan_detail.setVisible(on and method == "DBSCAN")
        self.part_filter.setVisible(on)
        if on and self.part_filter.is_expanded():
            self.refresh_parts()

    # -- part filter ---------------------------------------------------
    def _method(self) -> str:
        return self.cmb_parts.currentText().lower()

    def refresh_parts(self) -> None:
        """List the parts the chosen method assigns (once per method), ticked
        unless filtered out."""
        method = self._method()
        if method == self._parts_for:
            return
        names: list[str] = []
        if self.part_lister is not None:
            try:
                names = list(self.part_lister(method) or [])
            except Exception:  # noqa: BLE001 - an empty list, not a crash
                names = []
        self._parts_for = method
        self.parts_list.blockSignals(True)
        self.parts_list.clear()
        for name in names:
            item = QListWidgetItem(str(name), self.parts_list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if name in self._excluded
                               else Qt.CheckState.Checked)
        self.parts_list.blockSignals(False)
        if not names:
            self.lbl_parts_count.setText("No parts found for this method")
        self._count_parts()

    def _tick_parts(self, on: bool) -> None:
        self.parts_list.blockSignals(True)
        for i in range(self.parts_list.count()):
            self.parts_list.item(i).setCheckState(
                Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.parts_list.blockSignals(False)
        self._read_parts()

    def _on_part_ticked(self, _item) -> None:
        self._read_parts()

    def _read_parts(self) -> None:
        listed = {self.parts_list.item(i).text()
                  for i in range(self.parts_list.count())}
        off = {self.parts_list.item(i).text()
               for i in range(self.parts_list.count())
               if self.parts_list.item(i).checkState() != Qt.CheckState.Checked}
        # Parts not listed now (another method's) keep their choice.
        self._excluded = (self._excluded - listed) | off
        self._count_parts()

    def _count_parts(self) -> None:
        n = self.parts_list.count()
        if not n:
            return
        kept = sum(1 for i in range(n) if self.parts_list.item(i).checkState()
                   == Qt.CheckState.Checked)
        self.lbl_parts_count.setText(f"{kept} of {n} parts kept")

    def excluded_parts(self) -> list[str]:
        """The parts left out of the DataStore (of the chosen method's)."""
        if self._parts_for == self._method():
            return sorted(self.parts_list.item(i).text()
                          for i in range(self.parts_list.count())
                          if self.parts_list.item(i).checkState()
                          != Qt.CheckState.Checked)
        return sorted(self._excluded)

    def set_excluded_parts(self, parts) -> None:
        self._excluded = set(parts or [])
        self._parts_for = None  # re-tick on the next look

    # -- DBSCAN / Direct values -----------------------------------------
    def set_dbscan_values(self, values: dict) -> None:
        """Show DBSCAN settings (eps_xy, eps_z, min_samples, layers_per_chunk,
        overlap_layers; None overlap = Auto)."""
        v = {**_DBSCAN_DEFAULTS, **{k: x for k, x in values.items()
                                    if x is not None}}
        self.spin_eps_xy.setValue(float(v["eps_xy"]))
        self.spin_eps_z.setValue(float(v["eps_z"]))
        self.spin_min_samples.setValue(int(v["min_samples"]))
        self.spin_layers_per_chunk.setValue(int(v["layers_per_chunk"]))
        overlap = values.get("overlap_layers")
        self.spin_overlap.setValue(int(overlap) if overlap else 0)

    def dbscan_values(self) -> dict:
        overlap = int(self.spin_overlap.value())
        return {"eps_xy": round(self.spin_eps_xy.value(), 6),
                "eps_z": round(self.spin_eps_z.value(), 6),
                "min_samples": int(self.spin_min_samples.value()),
                "layers_per_chunk": int(self.spin_layers_per_chunk.value()),
                "overlap_layers": overlap or None}

    def max_distance(self) -> float | None:
        """Direct's max distance (mm); None = no limit."""
        value = round(self.spin_max_distance.value(), 6)
        return value or None

    def _set_part_option_enabled(self, index: int, enabled: bool) -> None:
        """Enable/disable one Part-assignment dropdown item (greys it out)."""
        item = self.cmb_parts.model().item(index)
        if item is not None:
            item.setEnabled(enabled)

    def _part_option_enabled(self, index: int) -> bool:
        item = self.cmb_parts.model().item(index)
        return bool(item is not None and item.isEnabled())

    # -- state ---------------------------------------------------------
    def set_config(
        self,
        config: dict,
        layers: list[int],
        columns: list[str] | None = None,
        renames: dict | None = None,
        included: list[str] | None = None,
    ) -> None:
        """Populate detected inputs, available columns, and scope bounds.

        ``included``, with ``renames``, is a live build's column selection —
        ticked as it was built (None = every column).

        ``renames`` (original -> display), when given, is a live build's current
        rename map — reflected in the rows so a rebuild preserves it. When it's
        None (a fresh setup) the fixed default import set + renames is applied.
        """
        self._stack = bool(config.get("STACK"))
        # Rebuild the column rows — optional first, the locked always-required
        # ones grouped at the bottom. part_id is assignment output (not a loadable
        # source column), so it's never offered here.
        cols = [c for c in (columns or []) if c != "part_id"]
        optional = [c for c in cols if c not in _ALWAYS]
        required = [c for c in cols if c in _ALWAYS]
        self._col_rows = [
            _ColumnRow(name, locked=name in _ALWAYS)
            for name in optional + required
        ]
        self._cols_area.setWidget(self._make_cols_host(self._col_rows))

        # Reflect the live build's renames (keep all included), or apply the fixed
        # default on a fresh setup: import the default set + required, with the
        # default renames prefilled.
        if renames is not None:
            self._apply_column_state(
                included=set(included) if included else None, renames=renames)
        else:
            self._apply_column_state(
                included=self._default_columns(), renames=_DEFAULT_RENAMES)

        lt = config.get("LAYER_THICKNESS")
        self.thickness_spin.setValue(float(lt) if lt else _DEFAULT_THICKNESS)
        # Each step builds at its own config's thickness.
        self.thickness_spin.setEnabled(not self._stack)
        self.thickness_spin.setToolTip(
            "Each step uses the layer thickness in its own config.toml"
            if self._stack else "")

        self.chk_all_layers.setChecked(True)
        if layers:
            lo, hi = min(layers), max(layers)
            for s in (self.layer_min, self.layer_max):
                s.setRange(lo, hi)
            self.layer_min.setValue(lo)
            self.layer_max.setValue(hi)
            self.lbl_available.setText(
                f"Available: {lo} - {hi} ({len(layers):,} layers)")
        else:
            self.lbl_available.setText("")

        self.set_excluded_parts(config.get("EXCLUDED_PARTS") or [])
        md = config.get("MAX_DISTANCE_MM")
        self.spin_max_distance.setValue(float(md) if md else 0.0)
        self.set_dbscan_values({"eps_xy": config.get("EPS_XY"),
                                "eps_z": config.get("EPS_Z"),
                                "min_samples": config.get("MIN_SAMPLES"),
                                "layers_per_chunk": config.get("LAYERS_PER_CHUNK"),
                                "overlap_layers": config.get("OVERLAP_LAYERS")})
        self.set_inputs(config, fresh=True, live=renames is not None)

        # Correction needs both the melt-pool and LaserVIEW signals loaded.
        cols_set = set(cols)
        has_corr = _CORR_COLUMN in cols_set and _CORR_LASER_COLUMN in cols_set
        self.chk_correction.setEnabled(has_corr)
        self.chk_correction.setChecked(
            has_corr and bool(config.get("APPLY_CORRECTION")))
        self.chk_correction.setToolTip(
            "" if has_corr
            else f"Needs both '{_CORR_COLUMN}' and '{_CORR_LASER_COLUMN}'")
        if not self.txt_corr_name.text().strip():
            self.txt_corr_name.setText(f"{_CORR_COLUMN} corrected")
        self._sync_correction_enabled()

    def set_inputs(self, config: dict, *, fresh: bool = False,
                   live: bool = False) -> None:
        """Show the build's inputs and offer what they allow. ``fresh``: a
        new setup, so each choice starts at its default; otherwise (an input
        just chosen with Browse...) the choices made stay, and one the new
        input makes possible is switched on."""
        def shown(value) -> str:
            return str(value) if value else _MISSING

        # A stacked build: its steps, and per input whether every step has
        # its own (an input some step lacks isn't used). Each step's inputs
        # are its own build's, so they're chosen there.
        notes = config.get("STACK_INPUTS") or {}
        self.lbl_source_key.setText("Steps" if self._stack else "Packet source")
        for key, _label, _folder in INPUTS:
            value = (config.get(key) if key == "SOURCE"
                     else notes.get(key) or config.get(key))
            self.input_values[key].setText(shown(value))
            btn = self.browse_buttons[key]
            btn.setEnabled(not self._stack)
            btn.setToolTip("Each step's inputs are chosen in its own build"
                           if self._stack else "")

        # Processing availability derives from the inputs.
        has_stl = bool(config.get("STL"))
        has_parts = bool(config.get("PARTS_CSV"))
        has_dhxml = bool(config.get("DHXML"))
        was_mask = self.chk_mask.isEnabled()
        self.chk_mask.setEnabled(has_stl)
        if fresh or not was_mask:
            self.chk_mask.setChecked(has_stl)
        self.chk_mask.setToolTip("" if has_stl else "No STL found to mask with")

        # Part assignment: Direct/DBSCAN need the parts CSV; DHXML needs the
        # dhxml. Gate each method on its own input; the toggle leads (off = None)
        # and defaults on when assignment is available.
        was_parts = self.chk_parts.isEnabled()
        self._set_part_option_enabled(0, has_parts)   # Direct
        self._set_part_option_enabled(1, has_dhxml)   # DHXML
        # DBSCAN clusters one build's points; not offered across steps.
        self._set_part_option_enabled(2, has_parts and not self._stack)
        parts_available = has_parts or has_dhxml
        self.chk_parts.setEnabled(parts_available)
        if fresh or not was_parts:
            self.chk_parts.setChecked(parts_available)
        self.chk_parts.setToolTip(
            "" if parts_available else "No parts CSV or DHXML found")
        if parts_available:
            if fresh:
                method = str(config.get("METHOD", "direct")).lower()
                if method == "dbscan" and not live:
                    method = "direct"  # never the default; only a live build's own
                index = {"direct": 0, "dhxml": 1, "dbscan": 2}.get(method, 0)
            else:
                index = self.cmb_parts.currentIndex()
            if not self._part_option_enabled(index):
                index = 1 if has_dhxml and not has_parts else 0
            self.cmb_parts.setCurrentIndex(index)
            self.cmb_parts.setToolTip("")
        else:
            self.cmb_parts.setToolTip("No parts CSV or DHXML found")
        self._parts_for = None  # the parts may differ with the new inputs
        self._sync_parts_enabled()

    def set_exists(self, exists: bool) -> None:
        self.build_btn.setText("Rebuild DataStore" if exists else "Build DataStore")

    def scope(self) -> tuple[int, int]:
        """Selected layer range (inclusive): all layers, or From / To."""
        if self.chk_all_layers.isChecked():
            return (self.layer_min.minimum(), self.layer_max.maximum())
        lo, hi = self.layer_min.value(), self.layer_max.value()
        return (lo, hi) if lo <= hi else (hi, lo)

    def thickness(self) -> float:
        """Layer thickness (mm) to build with."""
        return self.thickness_spin.value()

    def columns(self) -> list[str]:
        """Checked columns (always-required ones are included)."""
        return [r.name for r in self._col_rows if r.included()]

    def renames_map(self) -> dict:
        """Original -> new name for every row given a rename (included or not;
        a rename on an excluded column is simply ignored downstream)."""
        return {r.name: r.new_name() for r in self._col_rows if r.new_name()}

    def _apply_column_state(
        self, *, included: set | None, renames: dict
    ) -> None:
        """Set each row's include + rename. ``included=None`` keeps the current
        include state (used when reflecting a live build); otherwise a row is
        ticked iff its name is in ``included`` (locked rows stay on)."""
        for r in self._col_rows:
            inc = True if included is None else (r.name in included)
            r.set_state(included=inc, rename=renames.get(r.name, ""))

    def recipe(self) -> dict:
        """Selected processing recipe (used when the store applies it later)."""
        parts_on = self.chk_parts.isChecked() and self.chk_parts.isEnabled()
        method = self._method() if parts_on else "none"
        return {
            "dbscan": self.dbscan_values() if method == "dbscan" else None,
            "max_distance": self.max_distance() if method == "direct" else None,
            "excluded_parts": self.excluded_parts() if parts_on else [],
            "columns": self.columns(),
            "renames": self.renames_map(),
            "apply_mask": self.chk_mask.isEnabled() and self.chk_mask.isChecked(),
            "part_method": method,
            "apply_correction": (
                self.chk_correction.isEnabled()
                and self.chk_correction.isChecked()),
            "correction": {
                "machine": self.cmb_corr_machine.currentText(),
                "column": self.cmb_corr_column.currentText(),
                "mode": (
                    "override" if self.rb_corr_override.isChecked() else "new"),
                "output": self.txt_corr_name.text().strip(),
            },
        }
