"""New-plot dialog: pick which column goes on each channel.

Dumb by design — every combo lists *all* columns, so any column can be X, Y, Z
or the colour. Defaults come from plotspec.default_spec but are freely changed.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from .plotspec import PlotSpec, default_spec

_NONE = "— none —"


class NewPlotDialog(QDialog):
    def __init__(self, kind: str, columns, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"New {kind}")
        self._kind = kind
        self._columns = list(columns)
        base = default_spec(kind, self._columns)

        lay = QVBoxLayout(self)
        form = QFormLayout()

        def axis_combo(selected: str | None) -> QComboBox:
            cb = QComboBox()
            cb.addItems(self._columns)
            if selected in self._columns:
                cb.setCurrentIndex(self._columns.index(selected))
            return cb

        self.x_combo = axis_combo(base.x)
        form.addRow("X", self.x_combo)
        self.y_combo = axis_combo(base.y)
        form.addRow("Y", self.y_combo)

        self.z_combo = None
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

    def spec(self) -> PlotSpec:
        color = self.color_combo.currentText()
        return PlotSpec(
            kind=self._kind,
            x=self.x_combo.currentText(),
            y=self.y_combo.currentText(),
            z=self.z_combo.currentText() if self.z_combo is not None else None,
            color=None if color == _NONE else color,
        )
