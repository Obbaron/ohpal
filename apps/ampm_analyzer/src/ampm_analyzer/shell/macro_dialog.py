"""Macro popups, all frameless cards like the other dialogs:

- ``MacroSaveDialog``: on Stop, which recorded values to ask for when the
  macro runs (shown only when a step has such a value).
- ``MacroInputsDialog``: when a macro runs, the values it asks for.
- ``MacroPreviewDialog``: the steps, before a macro runs.
- ``MacroIssuesDialog``: why it can't run, with a column picker for each
  column the build doesn't have.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .card import DraggableCard

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class _ListCard(DraggableCard, QDialog):
    """A frameless card: title, an optional line of context, a read-only list."""

    def __init__(self, title: str, intro: str, lines: list[str], parent=None, *,
                 ok_text: str, cancel_text: str | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("MacroCard")
        card.setStyleSheet(
            "#MacroCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title_lbl)

        if intro:  # the step preview is title-only
            intro_lbl = QLabel(intro)
            intro_lbl.setWordWrap(True)
            lay.addWidget(intro_lbl)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list.addItems(lines)
        lay.addWidget(self.list, 1)
        # Room for more (the issues card's column pickers) above the buttons.
        self.extra = QVBoxLayout()
        self.extra.setSpacing(6)
        lay.addLayout(self.extra)

        flags = QDialogButtonBox.StandardButton.Ok
        if cancel_text is not None:
            flags |= QDialogButtonBox.StandardButton.Cancel
        buttons = QDialogButtonBox(flags)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok = self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(ok_text)
        ok.setIcon(QIcon())
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        if cancel_text is not None:
            cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            cancel.setText(cancel_text)
            cancel.setIcon(QIcon())
        lay.addWidget(buttons)
        self.resize(560, 420)


class MacroPreviewDialog(_ListCard):
    """What a macro will do, step by step, before it runs."""

    def __init__(self, name: str, descriptions: list[str], parent=None) -> None:
        super().__init__(
            f"Run macro '{name}'",
            "",
            [f"{i}.  {d}" for i, d in enumerate(descriptions, 1)],
            parent, ok_text="Run", cancel_text="Cancel",
        )


class MacroIssuesDialog(_ListCard):
    """Why a macro didn't run. Nothing was changed.

    ``missing`` (columns the macro reads that the build doesn't have) adds a
    picker per column, offering ``columns`` (the build's); choosing one for
    each turns OK into "Check again", and ``substitutions()`` then gives
    ``{missing: chosen}``."""

    _CHOOSE = "Choose a column…"

    def __init__(self, name: str, issues: list[str], parent=None, *,
                 missing: list[str] | None = None,
                 columns: list[str] | None = None) -> None:
        n = len(issues)
        missing = list(missing or [])
        intro = (f"'{name}' was not run and nothing was changed. "
                 f"{n} step{'s need' if n != 1 else ' needs'} attention:")
        super().__init__(
            "Macro issues", intro, issues, parent,
            ok_text="Check again" if missing else "OK",
            cancel_text="Cancel" if missing else None,
        )
        self.list.setSpacing(4)
        self._pickers: dict[str, QComboBox] = {}
        if missing:
            head = QLabel(
                "This build has no column named as below. Choose one of its "
                "columns to use instead for this run (the macro file isn't "
                "changed):")
            head.setWordWrap(True)
            self.extra.addWidget(head)
            grid = QGridLayout()
            grid.setHorizontalSpacing(10)
            for row, col in enumerate(missing):
                lbl = QLabel(f"'{col}'")
                lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse)
                grid.addWidget(lbl, row, 0)
                grid.addWidget(QLabel("→"), row, 1)
                combo = QComboBox()
                combo.addItem(self._CHOOSE)
                combo.addItems(list(columns or []))
                combo.setMinimumWidth(240)
                combo.currentIndexChanged.connect(self._sync_ok)
                grid.addWidget(combo, row, 2)
                self._pickers[col] = combo
            grid.setColumnStretch(2, 1)
            self.extra.addLayout(grid)
            self._sync_ok()
        self.resize(620, min(620, 260 + 60 * n + 34 * len(missing)))

    def _sync_ok(self) -> None:
        self.ok_button.setEnabled(all(
            c.currentIndex() > 0 for c in self._pickers.values()))

    def substitutions(self) -> dict[str, str]:
        return {col: c.currentText() for col, c in self._pickers.items()
                if c.currentIndex() > 0}


def _card(dialog: QDialog, title: str, intro: str) -> QVBoxLayout:
    """Frameless card chrome for ``dialog``; returns the card's layout with
    the title and intro already in it."""
    dialog.setWindowTitle(title)
    dialog.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
    dialog.setModal(True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    card = QFrame()
    card.setObjectName("MacroCard")
    card.setStyleSheet(
        "#MacroCard { background: palette(window); "
        "border: 1px solid palette(mid); border-radius: 10px; }")
    outer.addWidget(card)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(18, 16, 18, 14)
    lay.setSpacing(10)
    title_lbl = QLabel(title)
    title_lbl.setStyleSheet("font-size: 14pt; font-weight: 600;")
    lay.addWidget(title_lbl)
    if intro:
        intro_lbl = QLabel(intro)
        intro_lbl.setWordWrap(True)
        lay.addWidget(intro_lbl)
    return lay


def _buttons(dialog: QDialog, lay: QVBoxLayout, ok_text: str,
             cancel_text: str) -> None:
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
    ok.setText(ok_text)
    ok.setIcon(QIcon())
    ok.setDefault(True)
    ok.setStyleSheet(_PRIMARY_QSS)
    cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
    cancel.setText(cancel_text)
    cancel.setIcon(QIcon())
    lay.addWidget(buttons)


def _scrolled(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(inner)
    return area


def span_text(span) -> str:
    """A layer span as people say it."""
    mode, lo, hi = (list(span or []) + [None, None, None])[:3]
    if mode == "all":
        return "all layers"
    if mode == "current":
        return "the layer on screen"
    if mode == "range":
        return f"layers {lo} to {hi}"
    return f"layer {lo}"


class MacroSaveDialog(DraggableCard, QDialog):
    """On Stop: which recorded values the macro should ask for when it runs.

    ``items`` are ``(step_index, field, step_text, label, value_text)``; the
    ticked ones come back from ``chosen()`` as ``{step_index: [field, ...]}``.
    """

    def __init__(self, n_steps: int, items: list[tuple], parent=None) -> None:
        super().__init__(parent)
        lay = _card(
            self, "Save macro",
            f"{n_steps} step{'s' if n_steps != 1 else ''} recorded. Tick any "
            "value the macro should ask for each time it runs (the recorded "
            "value is filled in); the rest replay exactly as recorded.")
        inner = QWidget()
        rows = QVBoxLayout(inner)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        self._boxes: list[tuple[int, str, QCheckBox]] = []
        last = None
        for index, field, step_text, label, value in items:
            if index != last:
                head = QLabel(f"Step {index + 1}: {step_text}")
                head.setWordWrap(True)
                head.setStyleSheet("font-weight: 600; margin-top: 6px;")
                rows.addWidget(head)
                last = index
            box = QCheckBox(f"Ask for the {label[0].lower() + label[1:]} "
                            "when run")
            box.setToolTip(f"Recorded: {value}")
            line = QHBoxLayout()
            line.setContentsMargins(14, 0, 0, 0)
            line.addWidget(box)
            shown = QLabel(value)
            shown.setStyleSheet("color: palette(placeholder-text);")
            shown.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            line.addWidget(shown, 1)
            rows.addLayout(line)
            self._boxes.append((index, field, box))
        rows.addStretch(1)
        lay.addWidget(_scrolled(inner), 1)
        _buttons(self, lay, "Save…", "Cancel")
        self.resize(620, min(620, 200 + 34 * len(items) + 26 * len(
            {i for i, *_ in items})))

    def chosen(self) -> dict[int, list[str]]:
        out: dict[int, list[str]] = {}
        for index, field, box in self._boxes:
            if box.isChecked():
                out.setdefault(index, []).append(field)
        return out


class SpanEdit(QWidget):
    """A layer span: all layers, the layer on screen, one layer, or a range."""

    _MODES = (("all", "All layers"), ("current", "Layer on screen"),
              ("single", "One layer"), ("range", "Layers"))

    def __init__(self, span, layers: list[int], parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        for key, text in self._MODES:
            self.mode.addItem(text, key)
        lo_l, hi_l = (min(layers), max(layers)) if layers else (1, 100000)
        self.lo, self.hi = QSpinBox(), QSpinBox()
        for spin in (self.lo, self.hi):
            spin.setRange(lo_l, hi_l)
            spin.setFixedWidth(90)
        self.to = QLabel("to")
        lay.addWidget(self.mode)
        lay.addWidget(self.lo)
        lay.addWidget(self.to)
        lay.addWidget(self.hi)
        lay.addStretch(1)
        mode, lo, hi = (list(span or []) + [None, None, None])[:3]
        i = self.mode.findData(mode)
        self.mode.setCurrentIndex(max(0, i))
        self.lo.setValue(int(lo if lo is not None else lo_l))
        self.hi.setValue(int(hi if hi is not None else (lo if lo is not None
                                                        else hi_l)))
        self.mode.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        mode = self.mode.currentData()
        self.lo.setVisible(mode in ("single", "range"))
        self.to.setVisible(mode == "range")
        self.hi.setVisible(mode == "range")

    def value(self) -> list:
        mode = self.mode.currentData()
        if mode == "single":
            return ["single", self.lo.value(), self.lo.value()]
        if mode == "range":
            lo, hi = sorted((self.lo.value(), self.hi.value()))
            return ["range", lo, hi]
        return [mode, None, None]


class MacroInputsDialog(DraggableCard, QDialog):
    """When a macro runs: the values it asks for, filled in with the recorded
    ones. ``items`` are ``(key, step_text, label, kind, value)``; ``kind`` is
    "text" or "span". ``values()`` gives ``{key: value}``."""

    def __init__(self, name: str, items: list[tuple], layers: list[int],
                 parent=None) -> None:
        super().__init__(parent)
        lay = _card(self, f"Run macro '{name}'",
                    "This macro asks for these values. The recorded ones are "
                    "filled in.")
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self._editors: dict = {}
        row = 0
        for key, step_text, label, kind, value in items:
            head = QLabel(step_text)
            head.setWordWrap(True)
            head.setStyleSheet("color: palette(placeholder-text); "
                               "margin-top: 6px;")
            grid.addWidget(head, row, 0, 1, 2)
            row += 1
            grid.addWidget(QLabel(label), row, 0)
            if kind == "span":
                editor = SpanEdit(value, layers)
            else:
                editor = QLineEdit(str(value or ""))
                editor.setMinimumWidth(320)
            grid.addWidget(editor, row, 1)
            self._editors[key] = (kind, editor)
            row += 1
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(row, 1)
        lay.addWidget(_scrolled(inner), 1)
        _buttons(self, lay, "Continue", "Cancel")
        self.resize(640, min(620, 170 + 64 * len(items)))

    def values(self) -> dict:
        return {key: (editor.value() if kind == "span" else editor.text())
                for key, (kind, editor) in self._editors.items()}
