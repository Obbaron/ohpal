"""DBSCAN clusters: the Data tab's clustering, for any purpose (not only
part assignment).

The dialog asks what to cluster on: the position (X, Y and Z, each with a
radius) and / or other numeric columns, each with its own radius. Two points
are neighbours when they are within every radius; a point with at least
*min samples* neighbours starts a cluster. The run goes on in the
background and adds a column naming each point's cluster ("1" the largest,
then "2" ... and "noise"). ``ClusterRunDialog`` shows a run that has to
finish before anything else happens (a macro's DBSCAN step).
"""

from __future__ import annotations

from math import ceil

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .card import DraggableCard
from .widgets import fix_combo

_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


def _radius_box(value: float, suffix: str = "", decimals: int = 4) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(0.0001, 1e9)
    box.setValue(value)
    box.setSuffix(suffix)
    box.setFixedWidth(130)
    return box


def _card(dialog: QDialog, name: str) -> QVBoxLayout:
    """Make ``dialog`` a frameless card; returns the card's layout."""
    dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
    dialog.setModal(True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    card = QFrame()
    card.setObjectName(name)
    card.setStyleSheet(
        f"#{name} {{ background: palette(window); "
        "border: 1px solid palette(mid); border-radius: 10px; }")
    outer.addWidget(card)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(18, 16, 18, 14)
    lay.setSpacing(10)
    return lay


class ClusterDialog(DraggableCard, QDialog):
    """Choose what to cluster on. ``columns``: the numeric columns that can
    be added; ``position``: the build's names for X, Y and Z (or None when it
    lacks them); ``defaults``: (XY radius, Z radius, min samples);
    ``chunking``: (layers per chunk, overlap layers or None for the least
    the Z radius needs); ``layer_thickness`` in mm; ``suggest(column)``: a
    starting radius for a column. It starts on the position alone (no other
    columns); what it does is in the help."""

    def __init__(self, columns, *, position, defaults, chunking=(11, None),
                 layer_thickness=0.03, taken=(), suggest=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DBSCAN clusters")
        self._columns = list(columns)
        self._position = position
        self._taken = set(taken)
        self._suggest = suggest or (lambda _c: 1.0)
        self._thickness = float(layer_thickness)
        self._rows: list[tuple[QWidget, QComboBox, QDoubleSpinBox]] = []
        eps_xy, eps_z, min_samples = defaults

        lay = _card(self, "ClusterCard")
        title = QLabel("DBSCAN clusters")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        form = QFormLayout()
        self.name_edit = QLineEdit(self._free_name("cluster"))
        form.addRow("Column name", self.name_edit)
        lay.addLayout(form)

        # Position.
        self.position_check = QCheckBox("Cluster on position (X, Y and Z)")
        self.position_check.setChecked(position is not None)
        self.position_check.setEnabled(position is not None)
        lay.addWidget(self.position_check)
        self.position_box = QWidget()
        pf = QFormLayout(self.position_box)
        pf.setContentsMargins(24, 0, 0, 0)
        pf.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.eps_xy = _radius_box(eps_xy, " mm", 3)
        self.eps_z = _radius_box(eps_z, " mm", 3)
        pf.addRow("XY radius", self.eps_xy)
        pf.addRow("Z radius", self.eps_z)
        # The build is clustered a few layers at a time (memory); chunks
        # overlap so a cluster crossing a chunk's edge stays one cluster.
        per_chunk, overlap = chunking
        self.layers_per_chunk = QSpinBox()
        self.layers_per_chunk.setRange(2, 100000)
        self.layers_per_chunk.setValue(int(per_chunk))
        self.layers_per_chunk.setFixedWidth(130)
        self.layers_per_chunk.setToolTip(
            "Layers clustered at once: fewer use less memory")
        self.overlap = QSpinBox()
        self.overlap.setRange(0, 100000)
        self.overlap.setSpecialValueText("Auto")
        self.overlap.setValue(int(overlap or 0))
        self.overlap.setFixedWidth(130)
        self.overlap.setToolTip(
            "Layers shared by neighbouring chunks. Auto: the least the Z "
            "radius needs")
        pf.addRow("Layers per chunk", self.layers_per_chunk)
        pf.addRow("Overlap layers", self.overlap)
        lay.addWidget(self.position_box)
        self.position_check.toggled.connect(self.position_box.setEnabled)
        self.position_box.setEnabled(self.position_check.isChecked())

        # Other columns.
        head = QHBoxLayout()
        head.addWidget(QLabel("Other columns"))
        head.addStretch(1)
        self.add_btn = QPushButton("Add column")
        self.add_btn.clicked.connect(lambda: self.add_column())
        self.add_btn.setEnabled(bool(self._columns))
        head.addWidget(self.add_btn)
        lay.addLayout(head)
        self.columns_box = QVBoxLayout()
        self.columns_box.setContentsMargins(24, 0, 0, 0)
        lay.addLayout(self.columns_box)

        form2 = QFormLayout()
        form2.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.min_samples = QSpinBox()
        self.min_samples.setFixedWidth(130)
        self.min_samples.setRange(1, 100000)
        self.min_samples.setValue(int(min_samples))
        form2.addRow("Min samples", self.min_samples)
        lay.addLayout(form2)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        self.error.setStyleSheet("color: #d9534f;")
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Run")
        ok.setIcon(QIcon())
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())
        lay.addWidget(buttons)
        # A fixed width, and the height its contents need at that width (a
        # window's own size ignores how wrapped text grows).
        self.setFixedWidth(540)
        self._fit()

    def _fit(self) -> None:
        # Each wrapped note's height at the card's text width (18 px margins
        # and a 1 px border each side), then the height everything needs.
        text_width = self.width() - 2 * 19
        for lab in self.findChildren(QLabel):
            if lab.wordWrap() and lab.isVisibleTo(self):
                m = lab.contentsMargins()
                lab.setMinimumHeight(lab.heightForWidth(text_width) + m.top()
                                     + m.bottom())
        lay = self.layout()
        lay.activate()
        h = max(lay.totalHeightForWidth(self.width()),
                lay.totalMinimumSize().height())
        if h > 0:
            self.setFixedHeight(h)

    def _free_name(self, base: str) -> str:
        name, i = base, 2
        while name in self._taken or name in self._columns:
            name, i = f"{base} {i}", i + 1
        return name

    # -- other columns ---------------------------------------------------
    def add_column(self, column: str | None = None, radius: float | None = None) -> None:
        used = {c.currentText() for _w, c, _r in self._rows}
        if column is None:
            column = next((c for c in self._columns if c not in used),
                          self._columns[0] if self._columns else "")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        combo = fix_combo(QComboBox())
        combo.addItems(self._columns)
        combo.setCurrentText(column)
        h.addWidget(combo, 1)
        h.addWidget(QLabel("radius"))
        spin = _radius_box(radius if radius is not None else self._suggest(column))
        spin.setToolTip("How close two points must be in this column")
        h.addWidget(spin)
        combo.currentTextChanged.connect(lambda c, s=spin: s.setValue(self._suggest(c)))
        rm = QToolButton()
        rm.setAutoRaise(True)
        rm.setIcon(icons.ui("clear_sel", self.palette().windowText().color().name()))
        rm.setToolTip("Remove this column")
        h.addWidget(rm)
        entry = (row, combo, spin)
        self._rows.append(entry)
        rm.clicked.connect(lambda _c=False, e=entry: self._remove_row(e))
        self.columns_box.addWidget(row)
        self._fit()

    def _remove_row(self, entry) -> None:
        self._rows.remove(entry)
        entry[0].hide()
        entry[0].setParent(None)
        entry[0].deleteLater()
        self._fit()

    # -- result ----------------------------------------------------------
    def settings(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "position": self.position_check.isChecked(),
            "eps_xy": self.eps_xy.value(),
            "eps_z": self.eps_z.value(),
            "features": [[c.currentText(), s.value()] for _w, c, s in self._rows],
            "min_samples": self.min_samples.value(),
            "layers_per_chunk": self.layers_per_chunk.value(),
            "overlap_layers": self.overlap.value() or None,
        }

    def _accept(self) -> None:
        s = self.settings()
        problem = check_settings(s, self._columns, self._position,
                                 self._taken | set(self._columns),
                                 layer_thickness=self._thickness)
        if problem:
            self.error.setText(problem)
            self.error.setVisible(True)
            self._fit()
            return
        self.accept()


def min_overlap(eps_z: float, layer_thickness: float) -> int:
    """The fewest overlap layers that keep clusters whole across chunks for
    a Z radius (as ``ohpal.ampm.clustering.cluster_dbscan_chunked``)."""
    return max(2, int(ceil(eps_z / layer_thickness) * 2))


def check_settings(s: dict, columns, position, taken, *,
                   layer_thickness: float = 0.03) -> str:
    """What is wrong with a DBSCAN's settings ("" when nothing)."""
    if not s.get("name"):
        return "Give the column a name."
    if s["name"] in taken:
        return f"A column named {s['name']!r} already exists."
    feats = [c for c, _r in s.get("features") or []]
    if not s.get("position") and not feats:
        return "Cluster on the position, other columns, or both."
    if len(set(feats)) != len(feats):
        return "Each column can be added once."
    missing = [c for c in feats if c not in columns]
    if missing:
        return f"Not a numeric column of this build: {missing[0]!r}."
    if s.get("position"):
        if position is None:
            return "This build has no X, Y and Z to cluster on."
        if any(c in set(position) for c in feats):
            return "X, Y and Z are part of the position already."
        least = min_overlap(float(s.get("eps_z") or 0.06), layer_thickness)
        overlap = s.get("overlap_layers")
        if overlap and overlap < least:
            return (f"A Z radius of {s.get('eps_z'):g} mm needs at least "
                    f"{least} overlap layers (or Auto).")
        per_chunk = s.get("layers_per_chunk")
        if per_chunk and per_chunk <= (overlap or least):
            return (f"Layers per chunk must be more than the overlap "
                    f"({overlap or least}).")
    return ""


class ClusterRunDialog(DraggableCard, QDialog):
    """A DBSCAN run that must finish first (a macro's step): its progress,
    and Cancel."""

    def __init__(self, name: str, on_cancel, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DBSCAN")
        lay = _card(self, "ClusterRunCard")
        title = QLabel(f"DBSCAN: '{name}'")
        title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        lay.addWidget(title)
        self.status = QLabel("Starting…")
        self.status.setMinimumWidth(360)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(on_cancel)
        row.addWidget(cancel)
        lay.addLayout(row)

    def show_progress(self, text: str) -> None:
        self.status.setText(text[:1].upper() + text[1:] + "…")
