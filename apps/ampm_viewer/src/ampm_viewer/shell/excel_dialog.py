"""Dialog for importing a column from an Excel file (a key/value join).

The user picks an ``.xlsx``, a sheet, a **key** column and a **value** column;
the pairs are left-joined onto the grid on a chosen grid column to make a new
column. Keys are matched on their canonical string form (see
``derive.norm_key``), so ``1``, ``1.0`` and ``"1"`` align, and so do
``Part(12)`` and ``12``; duplicate keys are rejected. Everything is validated
on OK; errors keep the dialog open.

Given ``match_count(column, keys)`` (``derive.key_matches`` on the layer shown:
how many of the Excel keys are values of a grid column, and the share of its
rows they cover), the dialog says how many keys each choice matches, starts on
the grid column they cover best, and asks before adding a column that nothing
matches.

It starts on the choices that are usually right, so a filled-in samples
template needs no changes: the key is the Excel column whose values a grid
column holds (a ``part_id``-like name first), the value is the first column
someone filled in (not one the template generated, shaded grey, nor one the
grid has or already imported; numbers first), and the new column is named
after it.

The value dtype is inferred: all-numeric values store as floats (colormap-able,
usable in later formulas); otherwise they store as text (a discrete label).
"""

from __future__ import annotations

import re
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

from .card import DraggableCard
from .derive import norm_key
from .message_dialog import ask
from .widgets import fix_combo

# The samples template (ohpal.samples.template) shades the columns it generates
# this grey; they hold keys and coordinates, never a measurement to bring in.
_GENERATED_FILL = "D9D9D9"
# ... and these are its generated columns, for a copy that lost the shading.
_GENERATED_NAMES = {"buildid", "xmin", "xmax", "ymin", "ymax", "zmin", "zmax"}
# Key column names to try first, best first (compared by ``_canon``).
_KEY_HINTS = ("partid", "part", "sampleid", "sample", "id", "name")
_KEY_TRIES = 3  # candidate key columns counted against the grid, at most


def _canon(header: str) -> str:
    """``Part ID``, ``part_id`` and ``part-id`` alike."""
    return re.sub(r"[\s_\-]+", "", str(header).lower())


def _num(x) -> bool:
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class ExcelImportDialog(DraggableCard, QDialog):
    def __init__(self, grid_columns, parent=None, *, taken=None,
                 start_dir=None, match_count=None, align=None) -> None:
        super().__init__(parent)
        self._grid_columns = list(grid_columns)
        self._match_count = match_count
        # ``align(path, sheet, key column)`` -> {sheet key: build part key}, by
        # the rows' X/Y boxes (the samples template), or None: keys as written.
        self._align = align
        self._aligned: dict = {}  # (sheet, key column) -> that, or None
        self._keys: set[str] = set()       # the Excel key column, normalised
        self._matches: dict[str, tuple] = {}  # grid column -> (keys, row share)
        self._grid_picked = False           # the user chose the grid column
        self._columns: dict[str, tuple[list, bool]] = {}  # header -> (values, generated)
        self._counted: dict[str, tuple[set, dict]] = {}   # key header -> (keys, matches)
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
        self.key_combo.currentIndexChanged.connect(lambda _i: self._on_key())
        form.addRow("Excel key column", self.key_combo)
        self.val_combo = fix_combo(QComboBox())
        self.val_combo.currentIndexChanged.connect(lambda _i: self._on_val())
        form.addRow("Excel value column", self.val_combo)

        self.gridkey_combo = fix_combo(QComboBox())
        self.gridkey_combo.addItems(self._grid_columns)
        self.gridkey_combo.activated.connect(self._on_grid_picked)
        self.gridkey_combo.currentIndexChanged.connect(lambda _i: self._show_matches())
        form.addRow("Match on grid column", self.gridkey_combo)
        # How many of the Excel keys the grid column holds (on this layer).
        self.match_label = QLabel("")
        self.match_label.setWordWrap(True)
        form.addRow("", self.match_label)

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
        self._counted = {}
        try:
            self._columns = read_columns(self._path, self._sheet())
        except Exception as exc:  # noqa: BLE001
            self._error(f"Couldn't read the sheet: {exc}")
            self._columns = {}
        headers = list(self._columns)
        key = self._pick_key()
        value = self._pick_value(key)
        for cb, pick in ((self.key_combo, key), (self.val_combo, value)):
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(headers)
            if pick:
                cb.setCurrentText(pick)
            cb.blockSignals(False)
        self._on_val()
        self._on_key()

    # -- the starting choices ------------------------------------------
    def _keys_of(self, header: str) -> list[str]:
        return [norm_key(v) for v in self._columns.get(header, ([], False))[0]]

    def _alignment(self, header: str):
        """The sheet's part keys -> the build's, by position (see ``align``)."""
        at = (self._sheet() if self._path else None, header)
        if at not in self._aligned:
            got = None
            if self._align is not None and self._path:
                try:
                    got = self._align(self._path, self._sheet(), header)
                except Exception:  # noqa: BLE001 - a help, not a must
                    got = None
            self._aligned[at] = got
        return self._aligned[at]

    def _count(self, header: str) -> tuple[set, dict]:
        """The column's keys, and (keys, row share) for each grid column."""
        if header not in self._counted:
            keys = set(self._keys_of(header))
            align = self._alignment(header)
            if align:  # the build's names for the parts, by position
                keys = {align[k] for k in keys if k in align}
            matches = {}
            if keys and self._match_count is not None:
                matches = {c: self._match_count(c, keys) for c in self._grid_columns}
            self._counted[header] = (keys, matches)
        return self._counted[header]

    def _pick_key(self) -> str | None:
        """A column that could be a key (unique, varied values), ``part_id``-like
        names first, then ones the grid also has, then left to right; the
        first whose values a grid column holds."""
        grid = {_canon(c) for c in self._grid_columns}

        def rank(item):
            pos, header = item
            name = _canon(header)
            if name in _KEY_HINTS:
                return (_KEY_HINTS.index(name), pos)
            return (len(_KEY_HINTS) + (name not in grid), pos)

        keyish = []
        for item in sorted(enumerate(self._columns), key=rank):
            keys = self._keys_of(item[1])
            if len(set(keys)) > 1 and len(set(keys)) == len(keys):
                keyish.append(item[1])
        if not keyish:
            return next(iter(self._columns), None)
        if self._match_count is not None:
            for header in keyish[:_KEY_TRIES]:
                if any(n for n, _share in self._count(header)[1].values()):
                    return header
        return keyish[0]

    def _pick_value(self, key: str | None) -> str | None:
        """The first column someone filled in: not the key, not generated (grey
        or a template name), not a grid column or one imported already, not
        empty; numbers before text. With none left, one imported before (to
        bring it in again)."""
        imported = {_canon(c) for c in self._taken}
        have = {_canon(c) for c in self._grid_columns} | imported
        ours = [h for h, (values, generated) in self._columns.items()
                if h != key and values and not generated
                and _canon(h) not in _GENERATED_NAMES
                and (_canon(h) not in have or _canon(h) in imported)]
        filled = [h for h in ours if _canon(h) not in have]
        numeric = [h for h in filled if all(_num(v) for v in self._columns[h][0])]
        rest = [h for h in self._columns if h != key]
        return next(iter(numeric or filled or ours or rest), None)

    def _unique(self, name: str) -> str:
        """``name``, or ``name 2``, ``name 3``... if a column has it already."""
        have = {*self._grid_columns, *self._taken}
        out, n = name, 1
        while out in have:
            n += 1
            out = f"{name} {n}"
        return out

    # -- which grid column the keys are in ---------------------------------
    def _on_grid_picked(self, _index: int) -> None:
        self._grid_picked = True

    def _on_key(self) -> None:
        """Read the key column; count its keys in each grid column and, until
        the user picks one, start on the column that holds the most."""
        self._keys, self._matches = set(), {}
        key_h = self.key_combo.currentText()
        if self._match_count is not None and key_h in self._columns:
            try:
                self._keys, self._matches = self._count(key_h)
            except Exception:  # noqa: BLE001 - the count is a help, not a must
                self._keys, self._matches = set(), {}
        if self._keys and self._matches:
            best = self._best()
            if best and not self._grid_picked:
                self.gridkey_combo.setCurrentText(best)
        self._show_matches()

    def _hits(self, col: str) -> int:
        return self._matches.get(col, (0, 0.0))[0]

    def _best(self) -> str | None:
        """The grid column the keys cover best: the largest share of its rows,
        then the most keys (None: no column holds any)."""
        found = [c for c in self._grid_columns if self._hits(c)]
        if not found:
            return None
        return max(found, key=lambda c: (self._matches[c][1], self._matches[c][0]))

    def _show_matches(self) -> None:
        col = self.gridkey_combo.currentText()
        if not self._keys or col not in self._matches:
            self.match_label.setText("")
            return
        n, total = self._hits(col), len(self._keys)
        if n:
            self.match_label.setStyleSheet("color: palette(mid);")
            self.match_label.setText(f"{n} of {total} keys match.")
        else:
            best = self._best()
            try_ = f" Try {best!r} ({self._hits(best)} of {total})." if best else ""
            self.match_label.setStyleSheet("color: #c0392b;")
            self.match_label.setText(f"No keys match.{try_}")
        self._fit()

    def _fit(self) -> None:
        """Grow (or shrink) to show the whole note: a wrapped label in a form
        doesn't ask for its height by itself, so the last line was cut off."""
        width = self.match_label.width()
        if not self.isVisible() or width <= 0:
            return
        self.match_label.setMinimumHeight(0)
        need = self.match_label.heightForWidth(width) if self.match_label.text() else 0
        self.match_label.setMinimumHeight(max(0, need))
        self.resize(self.width(), self.sizeHint().height())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit()

    def _on_val(self) -> None:
        if not self._name_edited:  # mirror the value header until the user types
            value = self.val_combo.currentText()
            self.name_edit.setText(self._unique(value) if value else "")

    # -- openpyxl reads (each opens/closes; import files are small) -----
    @staticmethod
    def _load_sheets(path) -> list[str]:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        try:
            return list(wb.sheetnames)
        finally:
            wb.close()

    def _parse(self, key_h: str, val_h: str):
        """Return (mapping, dtype, n). Raises ValueError with a message."""
        return parse_mapping(self._path, self._sheet(), key_h, val_h,
                             align=self._alignment(key_h))

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
        if self._keys and grid_key in self._matches and not self._hits(grid_key):
            best = self._best()
            text = f"No keys match {grid_key!r}, so the new column would be empty."
            if best:
                text += f" Try {best!r} ({self._hits(best)} of {len(self._keys)})."
            if not ask(self, "No keys match", text,
                       ok_text="Add anyway", cancel_text="Go back"):
                return None
        self._result = (name, grid_key, mapping, dtype, n)
        self._source = {"sheet": self._sheet(), "key_column": key_h,
                        "value_column": val_h}
        self.accept()

    def result_values(self):
        """(name, grid_key, mapping, dtype, n_rows) — valid after accept()."""
        return self._result


_BOX = ("x_min", "x_max", "y_min", "y_max")


def read_part_boxes(path, sheet: str, key_h: str):
    """Each row's key (normalised) and XY box, ``part_id`` ``x_min`` ``x_max``
    ``y_min`` ``y_max`` ``x_center`` ``y_center``, when the sheet has the box
    columns (the samples template does); else None."""
    import polars as pl
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet not in wb.sheetnames:
            return None
        rows = wb[sheet].iter_rows(values_only=True)
        header = next(rows, None) or ()
        hdr = ["" if c is None else str(c).strip() for c in header]
        if key_h not in hdr or any(c not in hdr for c in _BOX):
            return None
        ki, idx = hdr.index(key_h), [hdr.index(c) for c in _BOX]
        out = []
        for row in rows:
            k = row[ki] if ki < len(row) else None
            if _blank(k):
                continue
            try:
                box = [float(row[i]) for i in idx]
            except (TypeError, ValueError, IndexError):
                continue
            out.append((norm_key(k), *box))
    finally:
        wb.close()
    if not out:
        return None
    df = pl.DataFrame(out, schema=["part_id", *_BOX], orient="row")
    return df.with_columns(((pl.col("x_min") + pl.col("x_max")) / 2).alias("x_center"),
                           ((pl.col("y_min") + pl.col("y_max")) / 2).alias("y_center"))


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _generated(cell) -> bool:
    """Shaded the template's grey (``_GENERATED_FILL``)."""
    try:
        return str(cell.fill.fgColor.rgb).upper().endswith(_GENERATED_FILL)
    except Exception:  # noqa: BLE001 - no fill, a theme colour, ...
        return False


def read_columns(path, sheet: str) -> dict[str, tuple[list, bool]]:
    """Each named column of the sheet: header -> (its non-empty values,
    shaded as generated). The first column of a repeated header wins."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = wb[sheet].iter_rows()
        cols: dict[str, tuple[list, bool]] = {}
        where = []
        for i, cell in enumerate(next(rows, None) or ()):
            header = "" if cell.value is None else str(cell.value).strip()
            if header and header not in cols:
                cols[header] = ([], _generated(cell))
                where.append((i, header))
        for row in rows:
            for i, header in where:
                v = row[i].value if i < len(row) else None
                if not _blank(v):
                    cols[header][0].append(v)
        return cols
    finally:
        wb.close()


def parse_mapping(path, sheet: str, key_h: str, val_h: str, *, align=None):
    """Read a key -> value table from an Excel sheet.

    Return (mapping, dtype, n). Raises ValueError with a message. Module-level
    (no dialog needed) so a macro's Excel step can re-read a chosen file.

    ``align`` ({sheet key: build key}, from ``read_part_boxes`` matched by
    position) renames the keys to the build's part names; rows whose part
    is at no part of the build are left out."""
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
    if align:
        pairs = [(align[k], v) for k, v in pairs if k in align]

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

    if pairs and all(_num(v) for _, v in pairs):
        return {nk: float(v) for nk, v in pairs}, "f64", len(pairs)
    return {nk: str(v) for nk, v in pairs}, "str", len(pairs)
