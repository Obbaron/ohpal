"""Dialog for exporting the grid to Excel (the inverse of Add-from-Excel).

Two modes:

* **Summary** — one row per *key* (default ``part_id``), with one or more value
  columns each reduced by an aggregation. The natural part-wise table.
* **Raw** — the rows as they are, a chosen subset of columns.

Plus a **scope** (current view / all layers / a range) and whether to respect
the active row filters. Produces a spec via ``result_values``; the window runs
the query + ``export`` helpers and writes the file.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

from . import colref, export
from .toolbars import LayerSpinBox
from .widgets import fix_combo

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


def _section(text: str) -> QLabel:
    """A bold section header (replaces the old group-box frames)."""
    lbl = QLabel(text)
    lbl.setStyleSheet("font-weight: 600;")
    return lbl


class ExcelExportDialog(QDialog):
    def __init__(self, columns, parent=None, *, layers=None, current_layer=None,
                 key_default="part_id", start_dir=None, renames=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export to Excel")
        self._columns = list(columns)
        self._renames = dict(renames or {})
        self._layers = list(layers or [])
        self._current = current_layer
        self._start_dir = start_dir or str(Path.home())
        self._value_rows: list = []
        self._result = None

        # Frameless card (matches the calculation / filter / new-plot dialogs).
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("ExportCard")
        card.setStyleSheet(
            "#ExportCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Export to Excel")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        # -- Mode: Summary vs Raw -------------------------------------
        mode_row = QHBoxLayout()
        self.radio_summary = QRadioButton("Summary (one row per key)")
        self.radio_raw = QRadioButton("Raw rows")
        self.radio_summary.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.radio_summary)
        grp.addButton(self.radio_raw)
        mode_row.addWidget(self.radio_summary)
        mode_row.addWidget(self.radio_raw)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        # -- Stacked body: summary page / raw page --------------------
        self.body = QStackedWidget()
        self.body.addWidget(self._summary_page())
        self.body.addWidget(self._raw_page())
        lay.addWidget(self.body)
        self.radio_summary.toggled.connect(
            lambda on: self.body.setCurrentIndex(0 if on else 1))

        # -- Scope ----------------------------------------------------
        lay.addWidget(self._scope_box())

        # -- Respect filters ------------------------------------------
        self.chk_filters = QCheckBox("Respect the active row filters")
        self.chk_filters.setChecked(True)
        lay.addWidget(self.chk_filters)

        # -- Output file + sheet --------------------------------------
        lay.addWidget(_section("Output"))
        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("choose where to save…")
        browse = QPushButton("Save as…")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)
        lay.addLayout(file_row)
        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Sheet"))
        self.sheet_edit = QLineEdit("Export")
        sheet_row.addWidget(self.sheet_edit, 1)
        lay.addLayout(sheet_row)

        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: #c0392b;")
        lay.addWidget(self.msg)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Export")
        ok.setIcon(QIcon())      # drop the themed check icon
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())  # drop the themed cross icon
        lay.addWidget(buttons)

        # Seed one value row (a melt-pool column if present, else the first);
        # follow a renamed melt-pool column.
        mp = self._renames.get("MeltVIEW melt pool (mean)",
                               "MeltVIEW melt pool (mean)")
        seed = (mp if mp in self._columns else
                next((c for c in self._columns if "melt pool (mean)" in c.lower()),
                     self._columns[0] if self._columns else None))
        self._add_value_row(seed, "mean")

    # -- pages --------------------------------------------------------
    def _summary_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Key (one row per)"))
        self.key_combo = fix_combo(QComboBox())
        self.key_combo.addItems(self._columns)
        for cand in ("part_id", "region", "side"):  # a sensible default key
            disp = self._renames.get(cand, cand)  # follow a renamed key column
            if disp in self._columns:
                self.key_combo.setCurrentText(disp)
                break
        key_row.addWidget(self.key_combo, 1)
        v.addLayout(key_row)

        v.addWidget(QLabel("Values"))
        self._values_box = QVBoxLayout()
        self._values_box.setSpacing(4)
        v.addLayout(self._values_box)
        add = QPushButton("+ Add value")
        add.clicked.connect(lambda: self._add_value_row())
        v.addWidget(add, alignment=Qt.AlignmentFlag.AlignLeft)

        hint = QLabel(colref.resolve_all(
            "“as-is” takes each key’s single value — use it for a column already "
            "computed per key (e.g. a CoV derived “by [part_id]”).",
            self._renames,
        ))
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        return page

    def _raw_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("Columns to include"))
        self.col_list = QListWidget()
        for c in self._columns:
            it = QListWidgetItem(c)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            self.col_list.addItem(it)
        v.addWidget(self.col_list, 1)
        btns = QHBoxLayout()
        allb = QPushButton("Select all")
        noneb = QPushButton("Select none")
        allb.clicked.connect(lambda: self._set_all_cols(True))
        noneb.clicked.connect(lambda: self._set_all_cols(False))
        btns.addWidget(allb)
        btns.addWidget(noneb)
        btns.addStretch(1)
        v.addLayout(btns)
        return page

    def _scope_box(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(_section("Scope"))
        row = QHBoxLayout()
        self.scope_current = QRadioButton("Current view")
        self.scope_all = QRadioButton("All layers")
        self.scope_range = QRadioButton("Range")
        self.scope_current.setChecked(True)
        g = QButtonGroup(self)
        for r in (self.scope_current, self.scope_all, self.scope_range):
            g.addButton(r)
        self.lo_spin = LayerSpinBox()
        self.hi_spin = LayerSpinBox()
        for sb in (self.lo_spin, self.hi_spin):
            sb.setFixedWidth(80)
        if self._layers:
            self.lo_spin.set_layers(self._layers, self._layers[0])
            self.hi_spin.set_layers(self._layers, self._layers[-1])
        self._sync_range()
        self.scope_range.toggled.connect(lambda _c: self._sync_range())
        row.addWidget(self.scope_current)
        row.addWidget(self.scope_all)
        row.addWidget(self.scope_range)
        row.addWidget(self.lo_spin)
        row.addWidget(QLabel("to"))
        row.addWidget(self.hi_spin)
        row.addStretch(1)
        v.addLayout(row)
        return wrap

    # -- value rows ---------------------------------------------------
    def _add_value_row(self, col=None, agg="mean") -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        col_cb = fix_combo(QComboBox())
        col_cb.addItems(self._columns)
        if col in self._columns:
            col_cb.setCurrentText(col)
        agg_cb = fix_combo(QComboBox())
        agg_cb.addItems(export.AGGS)
        agg_cb.setCurrentText(agg if agg in export.AGGS else "mean")
        rm = QToolButton()
        rm.setText("✕")
        rm.setAutoRaise(True)
        holder = QWidget()
        holder.setLayout(row)
        row.addWidget(col_cb, 2)
        row.addWidget(agg_cb, 1)
        row.addWidget(rm)
        self._values_box.addWidget(holder)
        entry = (holder, col_cb, agg_cb)
        self._value_rows.append(entry)
        rm.clicked.connect(lambda: self._remove_value_row(entry))

    def _remove_value_row(self, entry) -> None:
        if len(self._value_rows) <= 1:
            return  # keep at least one
        holder, _c, _a = entry
        self._value_rows.remove(entry)
        holder.setParent(None)

    def _set_all_cols(self, on: bool) -> None:
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for i in range(self.col_list.count()):
            self.col_list.item(i).setCheckState(state)

    def _sync_range(self) -> None:
        on = self.scope_range.isChecked()
        self.lo_spin.setEnabled(on)
        self.hi_spin.setEnabled(on)

    # -- output -------------------------------------------------------
    def _browse(self) -> None:
        start = self._start_dir
        if not self.path_edit.text():
            start = str(Path(self._start_dir) / "export.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Excel file", start, "Excel files (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        self.path_edit.setText(path)

    def _error(self, text: str) -> None:
        self.msg.setText(text)

    def _scope(self) -> tuple:
        if self.scope_all.isChecked():
            return ("all", None, None)
        if self.scope_range.isChecked():
            return ("range", self.lo_spin.value(), self.hi_spin.value())
        return ("current", self._current, self._current)

    def _accept(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            return self._error("Choose where to save the file.")
        summary = self.radio_summary.isChecked()
        if summary:
            values = [(c.currentText(), a.currentText())
                      for _h, c, a in self._value_rows]
            if not values:
                return self._error("Add at least one value column.")
            payload = {
                "mode": "summary",
                "key": self.key_combo.currentText(),
                "values": values,
            }
        else:
            cols = [self.col_list.item(i).text()
                    for i in range(self.col_list.count())
                    if self.col_list.item(i).checkState() == Qt.CheckState.Checked]
            if not cols:
                return self._error("Select at least one column.")
            payload = {"mode": "raw", "columns": cols}
        payload.update(
            scope=self._scope(),
            respect_filters=self.chk_filters.isChecked(),
            path=path,
            sheet=self.sheet_edit.text().strip() or "Export",
        )
        self._result = payload
        self.accept()

    def result_values(self):
        """The export spec (dict) — valid after accept()."""
        return self._result
