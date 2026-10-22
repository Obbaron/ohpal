"""DataStore settings form (inert).

The DataStore is the parquet cache materialised from a build with a specific
configuration — columns to include, layer range, spatial bounds, masking,
correction, and part-assignment method. This form *is* that configuration. It
lives in the backstage and appears once a build is loaded; "Create / Rebuild"
(re)materialises the cache.

This is distinct from the Data tab's view filters, which query the existing
cache cheaply (subregion / sub-range) without rebuilding it.

Everything here is inert — no control is connected to the pipeline yet.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
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

# Raw packet columns that could be materialised (placeholder set). The first
# few are always loaded by the pipeline and so are shown checked + disabled.
_RAW_COLUMNS = [
    "Demand X", "Demand Y", "Z", "layer", "Start time",
    "Laser power", "Laser speed", "Focus", "Hatch",
    "MeltVIEW melt pool (mean)",
]
_ALWAYS = {"Demand X", "Demand Y", "Z", "layer", "Start time"}


def _wrap(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w


def _dspin(value: float) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(-100_000, 100_000)
    s.setDecimals(2)
    s.setValue(value)
    s.setFixedWidth(90)
    return s


class DataStoreSettings(QWidget):
    createRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.status = QLabel("No datastore exists for this build.")
        self.status.setProperty("class", "PanelHeading")
        lay.addWidget(self.status)

        lay.addWidget(self._columns_group())
        lay.addWidget(self._range_group())
        lay.addWidget(self._pipeline_group())

        row = QHBoxLayout()
        row.addStretch(1)
        self.create_btn = QPushButton("Create DataStore")
        self.create_btn.setProperty("primary", "true")
        self.create_btn.clicked.connect(self.createRequested)
        row.addWidget(self.create_btn)
        lay.addLayout(row)
        lay.addStretch(1)

    # -- groups --------------------------------------------------------
    def _columns_group(self) -> QGroupBox:
        box = QGroupBox("Columns to include")
        v = QVBoxLayout(box)
        self.columns = QListWidget()
        for name in _RAW_COLUMNS:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            always = name in _ALWAYS
            item.setCheckState(
                Qt.CheckState.Checked if always else Qt.CheckState.Unchecked
            )
            if always:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.columns.addItem(item)
        self.columns.setFixedHeight(160)
        v.addWidget(self.columns)
        return box

    def _range_group(self) -> QGroupBox:
        box = QGroupBox("Materialisation range")
        f = QFormLayout(box)

        lr = QHBoxLayout()
        self.layer_min = QSpinBox()
        self.layer_min.setRange(0, 100_000)
        self.layer_min.setValue(1)
        self.layer_max = QSpinBox()
        self.layer_max.setRange(0, 100_000)
        self.layer_max.setValue(80)
        lr.addWidget(self.layer_min)
        lr.addWidget(QLabel("to"))
        lr.addWidget(self.layer_max)
        lr.addStretch(1)
        f.addRow("Layer range", _wrap(lr))

        xr = QHBoxLayout()
        self.x_min, self.x_max = _dspin(0), _dspin(250)
        xr.addWidget(self.x_min)
        xr.addWidget(QLabel("to"))
        xr.addWidget(self.x_max)
        xr.addStretch(1)
        f.addRow("X bounds", _wrap(xr))

        yr = QHBoxLayout()
        self.y_min, self.y_max = _dspin(0), _dspin(250)
        yr.addWidget(self.y_min)
        yr.addWidget(QLabel("to"))
        yr.addWidget(self.y_max)
        yr.addStretch(1)
        f.addRow("Y bounds", _wrap(yr))
        return box

    def _pipeline_group(self) -> QGroupBox:
        box = QGroupBox("Pipeline")
        f = QFormLayout(box)
        self.mask = QCheckBox("Apply mask")
        self.mask.setChecked(True)
        f.addRow("Masking", self.mask)
        self.correction = QComboBox()
        self.correction.addItems(["None", "MAIN / MeltVIEW melt pool (mean)"])
        f.addRow("Correction", self.correction)
        self.part_method = QComboBox()
        self.part_method.addItems(["None", "Direct (dhxml)", "DBSCAN"])
        f.addRow("Part assignment", self.part_method)
        return box

    # -- state ---------------------------------------------------------
    def set_exists(self, exists: bool) -> None:
        if exists:
            self.status.setText("DataStore ready. Reconfigure and rebuild below.")
            self.create_btn.setText("Rebuild DataStore")
        else:
            self.status.setText("No datastore exists for this build.")
            self.create_btn.setText("Create DataStore")
