"""DataStore setup page (backstage).

Reached via New (always) or Open-with-no-cache. It shows the build's detected
*config/inputs* (source dir, STL, parts CSV, layer thickness — read-only here,
flagged when missing) and the **cache scope** (all layers or a range), and
drives the parquet build via the Build / Rebuild button.

This is build-level setup only. The apply-or-not recipe toggles (mask / assign
parts / correction) live on the Data toolbar, not here; their *availability*
derives from the inputs shown on this page.

Still inert w.r.t. the pipeline: the controller performs the build; this widget
only collects scope and emits ``buildRequested``.
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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .widgets import fix_combo

_DEFAULT_THICKNESS = 0.03  # mm — fallback when a build has nothing to detect from

_MISSING = "— not found —"

# Always loaded (coordinates + layer/Z + the mask-keep key): locked on, and
# never removable from the grid (see controller.remove_columns).
REQUIRED_COLUMNS = {"Demand X", "Demand Y", "Start time", "layer", "Z"}
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.status = QLabel("No DataStore for this build yet.")
        self.status.setProperty("class", "PanelHeading")
        lay.addWidget(self.status)

        lay.addWidget(self._config_group())
        lay.addWidget(self._scope_group())
        lay.addWidget(self._columns_group())
        lay.addWidget(self._processing_group())

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
    def _config_group(self) -> QGroupBox:
        box = QGroupBox("Build inputs (detected)")
        f = QFormLayout(box)
        self.lbl_source = _value_label(_MISSING)
        self.lbl_dhxml = _value_label(_MISSING)
        self.lbl_stl = _value_label(_MISSING)
        self.lbl_csv = _value_label(_MISSING)
        f.addRow("Packet source", self.lbl_source)
        f.addRow("DHXML", self.lbl_dhxml)
        f.addRow("STL", self.lbl_stl)
        f.addRow("Parts CSV", self.lbl_csv)
        return box

    def _columns_group(self) -> QGroupBox:
        """Which columns the store loads, and an optional rename for each. Always-
        required ones are locked on. A fresh build opens with the fixed default
        set + renames already applied (see set_config)."""
        box = QGroupBox("Columns")
        v = QVBoxLayout(box)
        hint = QLabel("Tick to import; rename a column on the right.")
        hint.setProperty("class", "Hint")
        v.addWidget(hint)

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

    def _processing_group(self) -> QGroupBox:
        """Recipe defined with the DataStore: mask / assign parts / correction.

        Each control is disabled when its input is missing (reason in tooltip);
        changing these means reconfiguring + rebuilding the store.
        """
        box = QGroupBox("Processing")
        f = QFormLayout(box)

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
        self.chk_parts.toggled.connect(self._sync_parts_enabled)

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

        self.rb_corr_new = QRadioButton("New column")
        self.rb_corr_override = QRadioButton("Override column")
        self.rb_corr_new.setChecked(True)
        self._corr_mode = QButtonGroup(self)
        self._corr_mode.addButton(self.rb_corr_new)
        self._corr_mode.addButton(self.rb_corr_override)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addWidget(self.rb_corr_new)
        mode_row.addWidget(self.rb_corr_override)
        mode_row.addStretch(1)
        mode_w = QWidget()
        mode_w.setLayout(mode_row)
        cd.addRow("Output", mode_w)

        self.txt_corr_name = QLineEdit()
        self.txt_corr_name.setPlaceholderText("Corrected column name")
        cd.addRow("New name", self.txt_corr_name)

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
        self.cmb_parts.setEnabled(
            self.chk_parts.isChecked() and self.chk_parts.isEnabled())

    def _set_part_option_enabled(self, index: int, enabled: bool) -> None:
        """Enable/disable one Part-assignment dropdown item (greys it out)."""
        item = self.cmb_parts.model().item(index)
        if item is not None:
            item.setEnabled(enabled)

    def _part_option_enabled(self, index: int) -> bool:
        item = self.cmb_parts.model().item(index)
        return bool(item is not None and item.isEnabled())

    def _scope_group(self) -> QGroupBox:
        box = QGroupBox("Layers")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)

        # Range — defaults to the full extent, so it effectively *is* all layers.
        self.layer_min = QSpinBox()
        self.layer_max = QSpinBox()
        for s in (self.layer_min, self.layer_max):
            s.setRange(1, 100_000)
            s.setFixedWidth(90)
        grid.addWidget(QLabel("Range"), 0, 0)
        grid.addWidget(self.layer_min, 0, 1)
        grid.addWidget(QLabel("to"), 0, 2)
        grid.addWidget(self.layer_max, 0, 3)

        # Thickness (mm) — autodetected into the value, editable (so a build
        # with nothing to detect from can still be given a thickness).
        self.thickness_spin = QDoubleSpinBox()
        self.thickness_spin.setDecimals(3)
        self.thickness_spin.setRange(0.001, 5.0)
        self.thickness_spin.setSingleStep(0.005)
        self.thickness_spin.setValue(_DEFAULT_THICKNESS)
        self.thickness_spin.setFixedWidth(90)
        grid.addWidget(QLabel("Thickness"), 1, 0)
        grid.addWidget(self.thickness_spin, 1, 1)
        grid.addWidget(QLabel("mm"), 1, 2)  # units outside the box

        grid.setColumnStretch(4, 1)  # keep everything left
        return box

    # -- state ---------------------------------------------------------
    def set_config(
        self,
        config: dict,
        layers: list[int],
        columns: list[str] | None = None,
        renames: dict | None = None,
    ) -> None:
        """Populate detected inputs, available columns, and scope bounds.

        ``renames`` (original -> display), when given, is a live build's current
        rename map — reflected in the rows so a rebuild preserves it. When it's
        None (a fresh setup) the fixed default import set + renames is applied.
        """
        def shown(value) -> str:
            return str(value) if value else _MISSING

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
            self._apply_column_state(included=None, renames=renames)
        else:
            self._apply_column_state(
                included=set(_DEFAULT_IMPORT) | set(_ALWAYS),
                renames=_DEFAULT_RENAMES)

        self.lbl_source.setText(shown(config.get("SOURCE")))
        self.lbl_dhxml.setText(shown(config.get("DHXML")))
        self.lbl_stl.setText(shown(config.get("STL")))
        self.lbl_csv.setText(shown(config.get("PARTS_CSV")))
        lt = config.get("LAYER_THICKNESS")
        self.thickness_spin.setValue(float(lt) if lt else _DEFAULT_THICKNESS)

        if layers:
            lo, hi = min(layers), max(layers)
            for s in (self.layer_min, self.layer_max):
                s.setRange(lo, hi)
            self.layer_min.setValue(lo)
            self.layer_max.setValue(hi)

        # Processing availability derives from the detected inputs.
        has_stl = bool(config.get("STL"))
        has_parts = bool(config.get("PARTS_CSV"))
        self.chk_mask.setEnabled(has_stl)
        self.chk_mask.setChecked(has_stl)
        self.chk_mask.setToolTip("" if has_stl else "No STL found to mask with")

        # Part assignment: Direct/DBSCAN need the parts CSV; DHXML needs the
        # dhxml. Gate each method on its own input; the toggle leads (off = None)
        # and defaults on when assignment is available.
        has_dhxml = bool(config.get("DHXML"))
        self._set_part_option_enabled(0, has_parts)   # Direct
        self._set_part_option_enabled(1, has_dhxml)   # DHXML
        self._set_part_option_enabled(2, has_parts)   # DBSCAN
        parts_available = has_parts or has_dhxml
        self.chk_parts.setEnabled(parts_available)
        self.chk_parts.setChecked(parts_available)
        self.chk_parts.setToolTip(
            "" if parts_available else "No parts CSV or DHXML found")
        if parts_available:
            method = str(config.get("METHOD", "direct")).lower()
            index = {"direct": 0, "dhxml": 1, "dbscan": 2}.get(method, 0)
            if not self._part_option_enabled(index):
                index = 1 if has_dhxml else 0  # fall back to what's available
            self.cmb_parts.setCurrentIndex(index)
            self.cmb_parts.setToolTip("")
        else:
            self.cmb_parts.setToolTip("No parts CSV or DHXML found")
        self._sync_parts_enabled()

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

    def set_exists(self, exists: bool) -> None:
        if exists:
            self.status.setText("DataStore exists. Rebuild below if needed.")
            self.build_btn.setText("Rebuild DataStore")
        else:
            self.status.setText("No DataStore for this build yet.")
            self.build_btn.setText("Build DataStore")

    def scope(self) -> tuple[int, int]:
        """Selected layer range (inclusive); defaults to the full extent."""
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
        return {
            "columns": self.columns(),
            "renames": self.renames_map(),
            "apply_mask": self.chk_mask.isEnabled() and self.chk_mask.isChecked(),
            "part_method": (
                self.cmb_parts.currentText().lower()
                if self.chk_parts.isChecked() and self.chk_parts.isEnabled()
                else "none"),
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
