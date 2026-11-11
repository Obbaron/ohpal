"""Dialog for importing a column from an Excel file (a key/value join).

The user picks an ``.xlsx``, a sheet, a **key** column and a **value** column;
the pairs are left-joined onto the grid on a chosen grid column to make a new
column. Keys are matched on their canonical string form (see
``derive.norm_key``), so ``1``, ``1.0`` and ``"1"`` align; duplicate keys are
rejected. Everything is validated on OK — errors keep the dialog open.

The value dtype is inferred: all-numeric values store as floats (colormap-able,
usable in later formulas); otherwise they store as text (a discrete label).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .derive import norm_key
from .widgets import fix_combo

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class ExcelImportDialog(QDialog):
    def __init__(self, grid_columns, parent=None, *, taken=None,
                 start_dir=None) -> None:
        super().__init__(parent)
        self._grid_columns = list(grid_columns)
        self._taken = set(taken or [])
        self._start_dir = start_dir or str(Path.home())
        self._path: str | None = None
        self._name_edited = False
        self._result = None
        self._source: dict = {}

        # Frameless card (matches the calculation / label dialogs).
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("ExcelCard")
        card.setStyleSheet(
            "#ExcelCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Add from Excel")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        form = QFormLayout()

        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("no file chosen")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)
        form.addRow("Excel file", self._wrap(file_row))

        self.sheet_combo = fix_combo(QComboBox())
        self.sheet_combo.setEnabled(False)
        self.sheet_combo.currentIndexChanged.connect(lambda _i: self._on_sheet())
        form.addRow("Sheet", self.sheet_combo)

        self.key_combo = fix_combo(QComboBox())
        form.addRow("Excel key column", self.key_combo)
        self.val_combo = fix_combo(QComboBox())
        self.val_combo.currentIndexChanged.connect(lambda _i: self._on_val())
        form.addRow("Excel value column", self.val_combo)

        self.gridkey_combo = fix_combo(QComboBox())
        self.gridkey_combo.addItems(self._grid_columns)
        form.addRow("Match on grid column", self.gridkey_combo)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("new column name")
        self.name_edit.textEdited.connect(self._on_name_edited)
        form.addRow("New column", self.name_edit)

        lay.addLayout(form)

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
        ok.setText("Run")
        ok.setIcon(QIcon())
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())
        lay.addWidget(buttons)
        self.resize(520, self.sizeHint().height())

    # -- small helpers -------------------------------------------------
    @staticmethod
    def _wrap(inner) -> QWidget:
        w = QWidget()
        w.setLayout(inner)
        return w

    def _error(self, text: str) -> None:
        self.msg.setText(text)

    def _on_name_edited(self, _text: str) -> None:
        self._name_edited = True

    def _sheet(self) -> str:
        return self.sheet_combo.currentText()

    # -- file / sheet / column loading ---------------------------------
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Excel file", self._start_dir,
            "Excel files (*.xlsx *.xlsm *.xltx);;All files (*)",
        )
        if not path:
            return
        try:
            sheets = self._load_sheets(path)
        except Exception as exc:  # noqa: BLE001 - surface to the dialog
            self._error(f"Couldn't open the file: {exc}")
            return
        if not sheets:
            self._error("That workbook has no sheets.")
            return
        self._path = path
        self.path_edit.setText(path)
        self.msg.clear()
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        self.sheet_combo.addItems(sheets)
        self.sheet_combo.setEnabled(True)
        self.sheet_combo.blockSignals(False)
        self._on_sheet()

    def _on_sheet(self) -> None:
        if not self._path:
            return
        try:
            headers = self._read_headers(self._path, self._sheet())
        except Exception as exc:  # noqa: BLE001
            self._error(f"Couldn't read the sheet: {exc}")
            headers = []
        for cb in (self.key_combo, self.val_combo):
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(headers)
            cb.blockSignals(False)
        if len(headers) >= 2:  # sensible default: 1st = key, 2nd = value
            self.key_combo.setCurrentIndex(0)
            self.val_combo.setCurrentIndex(1)
        self._on_val()

    def _on_val(self) -> None:
        if not self._name_edited:  # mirror the value header until the user types
            self.name_edit.setText(self.val_combo.currentText())

    # -- openpyxl reads (each opens/closes; import files are small) -----
    @staticmethod
    def _load_sheets(path) -> list[str]:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return list(wb.sheetnames)
        finally:
            wb.close()

    @staticmethod
    def _read_headers(path, sheet) -> list[str]:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb[sheet]
            for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
                return [str(c).strip() for c in row
                        if c is not None and str(c).strip()]
            return []
        finally:
            wb.close()

    def _parse(self, key_h: str, val_h: str):
        """Return (mapping, dtype, n). Raises ValueError with a message."""
        return parse_mapping(self._path, self._sheet(), key_h, val_h)

    def source_values(self) -> dict:
        """Where the accepted column came from (sheet + headers) — recorded in
        a macro so the same read can be repeated on another file."""
        return dict(self._source)

    # -- accept --------------------------------------------------------
    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not self._path:
            return self._error("Choose an Excel file first.")
        if not name:
            return self._error("Give the new column a name.")
        if name in self._taken or name in self._grid_columns:
            return self._error(f"A column named {name!r} already exists.")
        key_h, val_h = self.key_combo.currentText(), self.val_combo.currentText()
        if not key_h or not val_h:
            return self._error("Choose both a key and a value column.")
        if key_h == val_h:
            return self._error("The key and value columns must differ.")
        grid_key = self.gridkey_combo.currentText()
        if not grid_key:
            return self._error("Choose a grid column to match on.")
        try:
            mapping, dtype, n = self._parse(key_h, val_h)
        except ValueError as exc:
            return self._error(str(exc))
        if not mapping:
            return self._error("No usable key/value rows found in the sheet.")
        self._result = (name, grid_key, mapping, dtype, n)
        self._source = {"sheet": self._sheet(), "key_column": key_h,
                        "value_column": val_h}
        self.accept()

    def result_values(self):
        """(name, grid_key, mapping, dtype, n_rows) — valid after accept()."""
        return self._result


def parse_mapping(path, sheet: str, key_h: str, val_h: str):
    """Read a key -> value table from an Excel sheet.

    Return (mapping, dtype, n). Raises ValueError with a message. Module-level
    (no dialog needed) so a macro's Excel step can re-read a chosen file."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet not in wb.sheetnames:
            raise ValueError(f"The workbook has no sheet named {sheet!r}.")
        rows = wb[sheet].iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            raise ValueError("The sheet is empty.")
        hdr = ["" if c is None else str(c).strip() for c in header]
        try:
            ki, vi = hdr.index(key_h), hdr.index(val_h)
        except ValueError:
            raise ValueError("Couldn't find the chosen columns in the sheet.")
        pairs = []
        for row in rows:
            k = row[ki] if ki < len(row) else None
            v = row[vi] if vi < len(row) else None
            if k is None or (isinstance(k, str) and not k.strip()):
                continue
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            pairs.append((norm_key(k), v))
    finally:
        wb.close()

    seen, dups = set(), []
    for nk, _v in pairs:
        (dups.append(nk) if nk in seen else seen.add(nk))
    if dups:
        uniq = sorted(set(dups))
        tail = " …" if len(uniq) > 5 else ""
        raise ValueError(
            f"Duplicate keys in '{key_h}': {', '.join(uniq[:5])}{tail}. "
            "Dedupe in Excel and re-import."
        )

    def _num(x) -> bool:
        try:
            float(x)
            return True
        except (TypeError, ValueError):
            return False

    if pairs and all(_num(v) for _, v in pairs):
        return {nk: float(v) for nk, v in pairs}, "f64", len(pairs)
    return {nk: str(v) for nk, v in pairs}, "str", len(pairs)
