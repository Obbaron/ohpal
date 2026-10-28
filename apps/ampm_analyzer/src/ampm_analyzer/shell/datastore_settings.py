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
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_DEFAULT_THICKNESS = 0.03  # mm — fallback when a build has nothing to detect from

_MISSING = "— not found —"

# Always loaded (coordinates + layer/Z + the mask-keep key): locked on, and
# never removable from the grid (see controller.remove_columns).
REQUIRED_COLUMNS = {"Demand X", "Demand Y", "Start time", "layer", "Z"}
_ALWAYS = REQUIRED_COLUMNS


def _value_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    return lab


class DataStoreSettings(QWidget):
    buildRequested = pyqtSignal()

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
        self.build_btn = QPushButton("Build DataStore")
        self.build_btn.setProperty("primary", "true")
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
        """Which columns the store loads. Always-required ones are locked on."""
        box = QGroupBox("Columns")
        v = QVBoxLayout(box)
        self.columns_list = QListWidget()
        self.columns_list.setFixedHeight(150)
        v.addWidget(self.columns_list)
        return box

    def _processing_group(self) -> QGroupBox:
        """Recipe defined with the DataStore: mask / assign parts / correction.

        Each control is disabled when its input is missing (reason in tooltip);
        changing these means reconfiguring + rebuilding the store.
        """
        box = QGroupBox("Processing")
        f = QFormLayout(box)

        self.chk_mask = QCheckBox("Apply mask")
        f.addRow("Masking", self.chk_mask)

        self.cmb_parts = QComboBox()
        self.cmb_parts.addItems(["None", "Direct", "DHXML", "DBSCAN"])
        f.addRow("Part assignment", self.cmb_parts)

        self.chk_correction = QCheckBox("Apply correction")
        f.addRow("Correction", self.chk_correction)
        return box

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
        self.thickness_spin.setSuffix(" mm")
        self.thickness_spin.setFixedWidth(90)
        grid.addWidget(QLabel("Thickness"), 1, 0)
        grid.addWidget(self.thickness_spin, 1, 1)

        grid.setColumnStretch(4, 1)  # keep everything left
        return box

    # -- state ---------------------------------------------------------
    def set_config(
        self, config: dict, layers: list[int], columns: list[str] | None = None
    ) -> None:
        """Populate detected inputs, available columns, and scope bounds."""
        def shown(value) -> str:
            return str(value) if value else _MISSING

        # Columns to include — optional first, the locked always-required ones
        # grouped together at the bottom.
        self.columns_list.clear()
        cols = columns or []
        optional = [c for c in cols if c not in _ALWAYS]
        required = [c for c in cols if c in _ALWAYS]
        for name in optional + required:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            if name in _ALWAYS:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.columns_list.addItem(item)

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
        # dhxml. Gate each option on its own input and pick an available one.
        has_dhxml = bool(config.get("DHXML"))
        self._set_part_option_enabled(1, has_parts)   # Direct
        self._set_part_option_enabled(2, has_dhxml)   # DHXML
        self._set_part_option_enabled(3, has_parts)   # DBSCAN
        self.cmb_parts.setEnabled(has_parts or has_dhxml)
        if has_parts or has_dhxml:
            method = str(config.get("METHOD", "direct")).lower()
            index = {"direct": 1, "dhxml": 2, "dbscan": 3}.get(method, 1)
            if not self._part_option_enabled(index):
                index = 2 if has_dhxml else 1  # fall back to what's available
            self.cmb_parts.setCurrentIndex(index)
            self.cmb_parts.setToolTip("")
        else:
            self.cmb_parts.setCurrentIndex(0)  # None
            self.cmb_parts.setToolTip("No parts CSV or DHXML found")

        self.chk_correction.setChecked(bool(config.get("APPLY_CORRECTION")))

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
        out = []
        for i in range(self.columns_list.count()):
            item = self.columns_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.text())
        return out

    def recipe(self) -> dict:
        """Selected processing recipe (used when the store applies it later)."""
        return {
            "columns": self.columns(),
            "apply_mask": self.chk_mask.isEnabled() and self.chk_mask.isChecked(),
            "part_method": self.cmb_parts.currentText().lower(),  # none/direct/…
            "apply_correction": self.chk_correction.isChecked(),
        }
