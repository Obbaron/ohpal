"""Stacked (stepped) builds in the app: several build folders read as one.

The data side is ``ohpal.ampm.stacked`` (a ``StackedStore``: layers, Z and a
``Build time`` that continue from step to step). This module is the app's
side of it:

- ``is_stack_folder`` tells a stacked build's folder (``stacked.toml``) from
  an ordinary build without importing ohpal (which is slow to import);
- ``stack_config`` is the one setup the stack shows on the DataStore page:
  an input (STL, parts CSV, .dhxml) counts as present when every step has
  its own;
- ``step_part_table`` / ``mask_jobs`` give each step's own part assignment
  and STL mask, which the controller applies per step;
- ``NewStackDialog`` picks the steps, in order, and where the stack is kept.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from .card import DraggableCard

STACK_FILE = "stacked.toml"
_PACKET_RE = re.compile(r"^Packet data for layer (\d+), laser \d+\.txt$",
                        re.IGNORECASE)

# Mirror of derive_dialog._PRIMARY_QSS: accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


def is_stack_folder(folder) -> bool:
    """True if ``folder`` is a stacked build (holds ``stacked.toml``)."""
    try:
        return (Path(folder) / STACK_FILE).is_file()
    except OSError:
        return False


def is_stack(store) -> bool:
    """True for a ``StackedStore`` (told apart without importing ohpal)."""
    return hasattr(store, "set_step_part_assignment")


# -- the stack's one setup --------------------------------------------------
_INPUTS = (("DHXML", ".dhxml"), ("STL", "STL"), ("PARTS_CSV", "parts CSV"))


def stack_config(store) -> dict:
    """The config the DataStore page and the controller see for a stack.

    ``STL`` / ``DHXML`` / ``PARTS_CSV`` are set (to a description, not a path)
    only when every step has one, so a choice that needs them is offered only
    then; the controller reads each step's own file from ``store.steps``.
    ``STACK_INPUTS`` says, per input, which steps lack it (for the page)."""
    steps = store.steps
    first = steps[0].config
    config = {
        "STACK": True,
        "SOURCE": step_summary(store),
        "LAYER_THICKNESS": store.layer_thickness,
        # The recipe defaults come from the bottom step's config.toml.
        "METHOD": first.get("METHOD", "direct"),
        "APPLY_CORRECTION": first.get("APPLY_CORRECTION", False),
        "MAX_DISTANCE_MM": first.get("MAX_DISTANCE_MM"),
    }
    notes = {}
    for key, label in _INPUTS:
        missing = [s.label for s in steps if not s.config.get(key)]
        if not missing:
            config[key] = f"Each step's own ({len(steps)} steps)"
            notes[key] = config[key]
        elif len(missing) == len(steps):
            notes[key] = ""
        else:
            notes[key] = f"Missing in {', '.join(missing)}: not used"
    config["STACK_INPUTS"] = notes
    return config


def step_summary(store) -> str:
    """One line per step: its folder and where its layers land in the stack."""
    lines = []
    for s in store.steps:
        lines.append(f"{s.label}  {s.root.name}: layers {s.stacked(s.first)}"
                     f"-{s.stacked(s.last)} ({s.thickness:g} mm)")
    return "\n".join(lines)


def step_part_table(config: dict, method: str):
    """``(table, options)`` for one step's part assignment by ``method``
    ("direct" / "dhxml"), from the step's own files; None when the step has
    no input for it."""
    m = (method or "").lower()
    if m == "dhxml" and config.get("DHXML"):
        from ohpal.ampm.parts import BuildStartedDHXML

        table = BuildStartedDHXML.from_dhxml(config["DHXML"]).parts_table()
        return table, {"method": "bbox"}
    if m == "direct" and config.get("PARTS_CSV"):
        from ohpal.ampm.parts import QuantAMParts

        table = QuantAMParts.from_path(config["PARTS_CSV"]).parent_parts()
        return table, {"method": "nearest",
                       "max_distance_mm": config.get("MAX_DISTANCE_MM")}
    return None


def mask_jobs(store) -> list[tuple] | None:
    """One mask job per step: ``(stl, its own layers, its thickness, cache
    file, layer offset)``; None if a step has no STL. Each step's STL is
    sliced in its own coordinates, then keyed by stacked layer."""
    jobs = []
    for s in store.steps:
        stl = s.config.get("STL")
        if not stl:
            return None
        jobs.append((stl, list(s.store.layers), s.thickness,
                     Path(store.cache_dir) / f"mask_{s.label}.pkl",
                     s.layer_offset))
    return jobs


def prefix_part_ids(df, prefix: str):
    """``df`` with its ``part_id`` values prefixed (``"S2 "``), as a stacked
    build's part assignment names them."""
    import polars as pl

    if not prefix or "part_id" not in df.columns:
        return df
    return df.with_columns(
        (pl.lit(prefix) + pl.col("part_id").cast(pl.Utf8)).alias("part_id"))


# -- picking the steps ---------------------------------------------------------
def probe_layers(folder) -> tuple[int, int] | None:
    """A build folder's first and last layer, from its packet files' names
    (where config.toml says they are, else found under the folder). None if
    it has none. Reads directory listings only, no files."""
    found = _packet_dir(Path(folder))
    return None if found is None else (min(found[1]), max(found[1]))


def probe_layout(folder) -> str | None:
    """A build folder's DataHUB export layout (``"current"`` or ``"legacy"``,
    see ``ohpal.ampm.datastore.Layout``), from its first packet file's header
    line. None if it has no packet data."""
    found = _packet_dir(Path(folder))
    if found is None:
        return None
    from ohpal.ampm.datastore import read_layout

    d, layers = found
    first = min(layers)
    name = next(e.name for e in os.scandir(d) if e.is_file()
                and (m := _PACKET_RE.match(e.name)) and int(m.group(1)) == first)
    try:
        return read_layout(d / name).kind
    except OSError:
        return None


def _packet_dir(folder: Path) -> tuple[Path, set[int]] | None:
    """Where a build folder's packet files are, and their layers."""
    source = None
    cfg = folder / "config.toml"
    if cfg.is_file():
        try:
            import tomllib

            paths = tomllib.loads(cfg.read_text(encoding="utf-8")).get("paths", {})
            if paths.get("source"):
                source = Path(paths["source"])
                if not source.is_absolute():
                    source = folder / source
        except Exception:  # noqa: BLE001 - unreadable: look for the files
            source = None
    dirs = [source] if source is not None else _walk(folder, depth=3)
    for d in dirs:
        layers = _packet_layers(d)
        if layers:
            return Path(d), layers
    return None


def _walk(folder: Path, depth: int):
    yield folder
    if depth <= 0:
        return
    try:
        subs = sorted(e.path for e in os.scandir(folder)
                      if e.is_dir() and not e.name.startswith("."))
    except OSError:
        return
    for sub in subs:
        yield from _walk(Path(sub), depth - 1)


def _packet_layers(folder: Path) -> set[int]:
    try:
        names = [e.name for e in os.scandir(folder) if e.is_file()]
    except OSError:
        return set()
    out = set()
    for name in names:
        m = _PACKET_RE.match(name)
        if m:
            out.add(int(m.group(1)))
    return out


class NewStackDialog(DraggableCard, QDialog):
    """Choose a stacked build's steps (bottom first), its name and the folder
    it's kept in. ``chosen()`` is ``(folder, name, [step folders])``."""

    def __init__(self, parent=None, *, start_dir: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New stacked build")
        self.setModal(True)
        self._start_dir = start_dir or str(Path.home())
        self._steps: list[tuple[Path, tuple[int, int]]] = []
        self._layouts: dict[Path, str | None] = {}  # step -> its export layout
        self._folder_edited = False
        self._result = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("StackCard")
        card.setStyleSheet(
            "#StackCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("New stacked build")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)
        hint = QLabel(
            "Add the steps' build folders, bottom first. They are read as one "
            "build: layers, Z and Build time carry on from each step to the "
            "next. Each step keeps its own STL, parts CSV and .dhxml.")
        hint.setWordWrap(True)
        hint.setProperty("class", "Hint")
        lay.addWidget(hint)

        self.list = QListWidget()
        self.list.setMinimumSize(460, 150)
        self.list.currentRowChanged.connect(lambda _r: self._sync())
        lay.addWidget(self.list)

        row = QHBoxLayout()
        self.btn_add = QPushButton("Add step...")
        self.btn_remove = QPushButton("Remove")
        self.btn_up = QPushButton("Move up")
        self.btn_down = QPushButton("Move down")
        for b in (self.btn_add, self.btn_remove, self.btn_up, self.btn_down):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.btn_add.clicked.connect(self._add)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))

        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name of the stacked build")
        self.name.textEdited.connect(lambda _t: self._suggest_folder())
        form.addRow("Name", self.name)
        self.folder = QLineEdit()
        self.folder.setPlaceholderText("A new folder for the stack")
        self.folder.textEdited.connect(self._folder_typed)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        frow = QHBoxLayout()
        frow.addWidget(self.folder, 1)
        frow.addWidget(browse)
        form.addRow("Keep in", frow)
        lay.addLayout(form)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c0392b;")
        self.error.setVisible(False)
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Create")
        self.ok.setIcon(QIcon())
        self.ok.setDefault(True)
        self.ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setIcon(QIcon())
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._sync()

    # -- steps ----------------------------------------------------------
    def add_step(self, folder) -> str | None:
        """Add a step folder (also what Add step... does); an error, or None."""
        folder = Path(folder).resolve()
        if any(folder == p for p, _ in self._steps):
            return f"{folder.name} is already a step."
        if is_stack_folder(folder):
            return f"{folder.name} is a stacked build, not a step."
        span = probe_layers(folder)
        if span is None:
            return f"No packet data found in {folder.name}."
        # One DataHUB export layout for the whole stack.
        kind = probe_layout(folder)
        other = next((p for p, _ in self._steps
                      if self._layouts.get(p) not in (None, kind)), None)
        if other is not None and kind is not None:
            from ohpal.ampm.datastore import LAYOUT_NAMES

            return (f"{folder.name} is in the {LAYOUT_NAMES[kind]} but "
                    f"{other.name} is in the {LAYOUT_NAMES[self._layouts[other]]}: "
                    f"a stack's steps must all use the same one.")
        self._layouts[folder] = kind
        self._steps.append((folder, span))
        if not self.name.text().strip():
            self.name.setText(f"{folder.name} stacked")
        self._suggest_folder()
        self._refill(len(self._steps) - 1)
        return None

    def _add(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Add a step's build folder", self._next_dir())
        if not chosen:
            return
        self._show_error(self.add_step(chosen))

    def _next_dir(self) -> str:
        return str(self._steps[-1][0].parent) if self._steps else self._start_dir

    def _remove(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self._steps):
            del self._steps[row]
            self._refill(min(row, len(self._steps) - 1))

    def _move(self, by: int) -> None:
        row = self.list.currentRow()
        to = row + by
        if 0 <= row < len(self._steps) and 0 <= to < len(self._steps):
            self._steps[row], self._steps[to] = self._steps[to], self._steps[row]
            self._refill(to)

    def _refill(self, current: int) -> None:
        self.list.clear()
        offset = None
        for i, (folder, (lo, hi)) in enumerate(self._steps, start=1):
            if offset is None:  # the bottom step keeps its own numbering
                offset = lo - 1
            first = offset + 1
            last = offset + (hi - lo + 1)
            offset = last
            item = QListWidgetItem(
                f"S{i}   {folder.name}   layers {lo}-{hi}  ->  {first}-{last}")
            item.setToolTip(str(folder))
            self.list.addItem(item)
        if current >= 0:
            self.list.setCurrentRow(current)
        self._sync()

    def _sync(self) -> None:
        row = self.list.currentRow()
        have = 0 <= row < len(self._steps)
        self.btn_remove.setEnabled(have)
        self.btn_up.setEnabled(have and row > 0)
        self.btn_down.setEnabled(have and row < len(self._steps) - 1)

    # -- where it's kept ------------------------------------------------
    def _suggest_folder(self) -> None:
        if self._folder_edited or not self._steps:
            return
        name = re.sub(r'[<>:"/\\|?*]+', "_", self.name.text()).strip()
        if name:
            self.folder.setText(str(self._steps[0][0].parent / name))

    def _folder_typed(self, _text: str) -> None:
        self._folder_edited = True

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Keep the stacked build in", self._next_dir())
        if chosen:
            self.folder.setText(chosen)
            self._folder_edited = True

    # -- result -----------------------------------------------------------
    def _show_error(self, message: str | None) -> None:
        self.error.setText(message or "")
        self.error.setVisible(bool(message))

    def problem(self) -> str | None:
        """Why the choices can't be created yet (None: they can)."""
        if len(self._steps) < 2:
            return "A stacked build needs at least two steps."
        if not self.name.text().strip():
            return "Give the stacked build a name."
        text = self.folder.text().strip()
        if not text:
            return "Choose a folder to keep the stacked build in."
        folder = Path(text).resolve()
        for step, _ in self._steps:
            if folder == step or step in folder.parents:
                return "Keep the stacked build outside its steps' folders."
        if folder.exists() and not folder.is_dir():
            return f"{folder} is a file."
        if (folder / "config.toml").exists():
            return f"{folder.name} is a build folder: choose another."
        return None

    def _accept(self) -> None:
        message = self.problem()
        if message:
            self._show_error(message)
            return
        self._result = (Path(self.folder.text().strip()).resolve(),
                        self.name.text().strip(),
                        [p for p, _ in self._steps])
        self.accept()

    def chosen(self):
        """``(folder, name, steps)`` once created, else None."""
        return self._result
