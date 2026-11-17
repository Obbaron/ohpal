"""Building blocks of the side panel: cards, joined toggle buttons, the
colormap gallery, the colour range bar, a small histogram and stat tiles.

The choice widgets (``ChoiceButtons``, ``CmapGallery``) answer the parts of
the ``QComboBox`` API the panel and its callers use (``currentText``,
``currentData``, ``findText``, ``findData``, ``setCurrentIndex``, the
``currentIndexChanged`` / ``currentTextChanged`` signals), so they drop in
where a combo was.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons


def _pal(role) -> QColor:
    return QApplication.instance().palette().color(role)


def _ink() -> str:
    from PyQt6.QtGui import QPalette
    return _pal(QPalette.ColorRole.WindowText).name()


def _accent() -> str:
    from PyQt6.QtGui import QPalette
    return _pal(QPalette.ColorRole.Highlight).name()


def two_state_icon(stem: str, px: int = 16) -> QIcon:
    """An icon in the text colour, white when its button is checked."""
    out = QIcon()
    for state, colour in ((QIcon.State.Off, _ink()), (QIcon.State.On, "#ffffff")):
        pm = icons.icon(stem, colour, px).pixmap(QSize(px, px))
        out.addPixmap(pm, QIcon.Mode.Normal, state)
    return out


# -- card ------------------------------------------------------------------
class Card(QFrame):
    """A rounded panel section: an accent icon, a small capitalised caption
    (with an optional widget on the right) and a body (``body``)."""

    def __init__(self, stem: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "PanelCard")
        self._stem = stem
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        head.addWidget(self.icon)
        self.caption = QLabel()
        self.caption.setProperty("class", "CardCaption")
        head.addWidget(self.caption, 1)
        self._head = head
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body)
        self.set_title(title)
        self.retint()

    def set_title(self, title: str) -> None:
        self.caption.setText(title.upper())

    def title(self) -> str:
        return self.caption.text()

    def add_right(self, widget: QWidget) -> None:
        self._head.addWidget(widget)

    def retint(self) -> None:
        self.icon.setPixmap(icons.icon(self._stem, _accent(), 16).pixmap(16, 16))


def field_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("class", "FieldLabel")
    return lab


class LabelRow(QWidget):
    """A field's label on the left and its value (muted) on the right."""

    def __init__(self, text: str, value: str = "") -> None:
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 2, 0, 0)
        h.setSpacing(6)
        self.label = field_label(text)
        h.addWidget(self.label)
        h.addStretch(1)
        self.value = QLabel(value)
        self.value.setProperty("class", "FieldValue")
        h.addWidget(self.value)


def inline_row(text: str, widget: QWidget) -> QWidget:
    """A label on the left, a compact control on the right."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    h.addWidget(field_label(text))
    h.addStretch(1)
    h.addWidget(widget)
    return row


def stacked_row(text: str, widget: QWidget) -> QWidget:
    """A label above a full-width control."""
    row = QWidget()
    v = QVBoxLayout(row)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    v.addWidget(field_label(text))
    v.addWidget(widget)
    return row


class Badge(QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setProperty("class", "PanelBadge")


# -- joined toggle buttons -------------------------------------------------
class Segmented(QFrame):
    """A row of joined toggle buttons. ``exclusive``: one checked at a time."""

    def __init__(self, exclusive: bool = True) -> None:
        super().__init__()
        self.setProperty("class", "Segmented")
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(2, 2, 2, 2)
        self._lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(exclusive)
        self.buttons: list[QToolButton] = []

    def add(self, text: str = "", stem: str | None = None, tip: str = "") -> QToolButton:
        b = QToolButton()
        b.setCheckable(True)
        b.setAutoRaise(False)
        if stem:
            b.setIcon(two_state_icon(stem))
            b.setProperty("stem", stem)
            b.setToolTip(tip or text[:1].upper() + text[1:])
        else:
            b.setText(text)
            if tip:
                b.setToolTip(tip)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        b.setFixedHeight(24)
        self.group.addButton(b, len(self.buttons))
        self.buttons.append(b)
        self._lay.addWidget(b)
        return b


class ChoiceButtons(Segmented):
    """One-of-several as joined buttons, with a combo-like API.

    ``options``: ``(value, text, stem)`` triples; with a ``stem`` the button
    shows the icon (the text becomes its tooltip)."""

    currentIndexChanged = pyqtSignal(int)
    currentTextChanged = pyqtSignal(str)

    def __init__(self, options) -> None:
        super().__init__(exclusive=True)
        self._values: list = []
        self._texts: list[str] = []
        for value, text, stem in options:
            self.add(text, stem)
            self._values.append(value)
            self._texts.append(text)
        if self.buttons:
            self.buttons[0].setChecked(True)
        self.group.idToggled.connect(self._on_toggled)

    def _on_toggled(self, i: int, on: bool) -> None:
        if on:
            self.currentIndexChanged.emit(i)
            self.currentTextChanged.emit(self._texts[i])

    # combo-like API
    def count(self) -> int:
        return len(self._values)

    def currentIndex(self) -> int:  # noqa: N802
        return self.group.checkedId()

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        if 0 <= i < len(self.buttons) and i != self.currentIndex():
            self.buttons[i].setChecked(True)

    def currentText(self) -> str:  # noqa: N802
        i = self.currentIndex()
        return self._texts[i] if i >= 0 else ""

    def setCurrentText(self, text: str) -> None:  # noqa: N802
        self.setCurrentIndex(self.findText(text))

    def currentData(self):  # noqa: N802
        i = self.currentIndex()
        return self._values[i] if i >= 0 else None

    def itemText(self, i: int) -> str:  # noqa: N802
        return self._texts[i]

    def itemData(self, i: int):  # noqa: N802
        return self._values[i] if 0 <= i < len(self._values) else None

    def findText(self, text: str) -> int:  # noqa: N802
        low = str(text).lower()
        for i, t in enumerate(self._texts):
            if t.lower() == low:
                return i
        return -1

    def findData(self, value) -> int:  # noqa: N802
        try:
            return self._values.index(value)
        except ValueError:
            return -1


# -- colormaps -------------------------------------------------------------
def _cmap_colors(name: str) -> list[QColor]:
    from .plotdata import colormap_stops
    return [QColor.fromRgbF(*rgb) for rgb in colormap_stops(name)]


def _gradient(name: str, x0: float, x1: float, lo: float = 0.0,
              hi: float = 1.0) -> QLinearGradient:
    """The colormap from ``x0`` to ``x1``; with a range, its colours span
    ``lo``..``hi`` (fractions) and stay at the end colours outside it."""
    g = QLinearGradient(x0, 0, x1, 0)
    cs = _cmap_colors(name)
    span = max(hi - lo, 1e-6)
    g.setColorAt(0.0, cs[0])
    for i, c in enumerate(cs):
        g.setColorAt(min(1.0, max(0.0, lo + span * i / (len(cs) - 1))), c)
    g.setColorAt(1.0, cs[-1])
    return g


class _CmapTile(QToolButton):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.setCheckable(True)
        self.setToolTip(name)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QToolButton { border: none; background: transparent; }")

    def paintEvent(self, _e) -> None:  # noqa: N802
        from PyQt6.QtGui import QPalette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        accent = _pal(QPalette.ColorRole.Highlight)
        r = QRectF(1.5, 1.5, self.width() - 3, 17)
        p.setBrush(_gradient(self.name, r.left(), r.right()))
        if on:
            p.setPen(QPen(accent, 2.5))
        else:
            p.setPen(QPen(_pal(QPalette.ColorRole.Mid), 1))
        p.drawRoundedRect(r, 5, 5)
        f = p.font()
        f.setPixelSize(11)
        f.setBold(on)
        p.setFont(f)
        p.setPen(accent if on else _pal(QPalette.ColorRole.PlaceholderText))
        p.drawText(QPointF(2, 33), self.name)


class CmapGallery(QWidget):
    """The colormaps as gradient tiles (three a row), with a combo-like API."""

    currentIndexChanged = pyqtSignal(int)
    currentTextChanged = pyqtSignal(str)

    def __init__(self, names, columns: int = 3) -> None:
        super().__init__()
        self._names = list(names)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(2)
        self.group = QButtonGroup(self)
        self.tiles: list[_CmapTile] = []
        for i, n in enumerate(self._names):
            t = _CmapTile(n)
            self.group.addButton(t, i)
            self.tiles.append(t)
            g.addWidget(t, i // columns, i % columns)
        if self.tiles:
            self.tiles[0].setChecked(True)
        self.group.idToggled.connect(self._on_toggled)

    def _on_toggled(self, i: int, on: bool) -> None:
        if on:
            self.currentIndexChanged.emit(i)
            self.currentTextChanged.emit(self._names[i])

    def count(self) -> int:
        return len(self._names)

    def currentIndex(self) -> int:  # noqa: N802
        return self.group.checkedId()

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        if 0 <= i < len(self.tiles) and i != self.currentIndex():
            self.tiles[i].setChecked(True)

    def currentText(self) -> str:  # noqa: N802
        i = self.currentIndex()
        return self._names[i] if i >= 0 else ""

    def setCurrentText(self, text: str) -> None:  # noqa: N802
        self.setCurrentIndex(self.findText(text))

    currentData = currentText  # the value is the name

    def itemText(self, i: int) -> str:  # noqa: N802
        return self._names[i]

    itemData = itemText

    def findText(self, text: str) -> int:  # noqa: N802
        try:
            return self._names.index(str(text))
        except ValueError:
            return -1

    findData = findText


class RangeBar(QWidget):
    """The colormap as a bar with two handles: the part of the data the
    colours span, as percents (0..100) of the full range. Drag a handle (or
    click near one); the labels under the ends say what the handles are at."""

    lowChanged = pyqtSignal(int)
    highChanged = pyqtSignal(int)

    _BAR = 16
    _PAD = 7

    def __init__(self) -> None:
        super().__init__()
        self._cmap = "turbo"
        self._lo, self._hi = 0, 100
        self._labels = ("", "")
        self._drag: int | None = None  # 0: low handle, 1: high handle
        self.setFixedHeight(self._BAR + 26)
        self.setMouseTracking(True)
        self.setToolTip("Drag the handles to choose the range the colours span")

    def set_cmap(self, name: str) -> None:
        self._cmap = name
        self.update()

    def set_labels(self, lo: str, hi: str) -> None:
        self._labels = (lo, hi)
        self.update()

    def low(self) -> int:
        return self._lo

    def high(self) -> int:
        return self._hi

    def set_values(self, lo: int, hi: int) -> None:
        """Move both handles without emitting."""
        self._lo, self._hi = int(lo), int(hi)
        self.update()

    def set_low(self, v: int) -> None:
        v = max(0, min(int(v), self._hi))
        if v != self._lo:
            self._lo = v
            self.update()
            self.lowChanged.emit(v)

    def set_high(self, v: int) -> None:
        v = min(100, max(int(v), self._lo))
        if v != self._hi:
            self._hi = v
            self.update()
            self.highChanged.emit(v)

    def _bar(self) -> QRectF:
        return QRectF(self._PAD, 4, self.width() - 2 * self._PAD, self._BAR)

    def _x(self, v: int) -> float:
        r = self._bar()
        return r.left() + r.width() * v / 100.0

    def _value_at(self, x: float) -> int:
        r = self._bar()
        return int(round(100.0 * (x - r.left()) / max(r.width(), 1.0)))

    def mousePressEvent(self, e) -> None:  # noqa: N802
        x = e.position().x()
        lo, hi = self._x(self._lo), self._x(self._hi)
        if abs(x - lo) == abs(x - hi):
            self._drag = 0 if x < lo else 1
        else:
            self._drag = 0 if abs(x - lo) < abs(x - hi) else 1
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is None:
            return
        v = self._value_at(e.position().x())
        (self.set_low if self._drag == 0 else self.set_high)(v)

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802
        self._drag = None

    def paintEvent(self, _e) -> None:  # noqa: N802
        from PyQt6.QtGui import QPalette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._bar()
        p.setPen(QPen(_pal(QPalette.ColorRole.Mid), 1))
        p.setBrush(_gradient(self._cmap, r.left(), r.right(),
                             self._lo / 100.0, self._hi / 100.0))
        p.drawRoundedRect(r, 4, 4)
        for v in (self._lo, self._hi):
            x = self._x(v)
            p.setPen(QPen(_pal(QPalette.ColorRole.WindowText), 1.5))
            p.setBrush(_pal(QPalette.ColorRole.Base))
            p.drawRoundedRect(QRectF(x - 5, r.top() - 3, 10, r.height() + 6), 3, 3)
        f = p.font()
        f.setPixelSize(11)
        p.setFont(f)
        p.setPen(_pal(QPalette.ColorRole.PlaceholderText))
        y = r.bottom() + 17
        lo, hi = self._labels
        p.drawText(QPointF(r.left(), y), lo)
        p.drawText(QPointF(r.right() - p.fontMetrics().horizontalAdvance(hi), y), hi)


# -- column summaries ------------------------------------------------------
class Histogram(QWidget):
    """Bars of a column's value counts (``set_counts``)."""

    def __init__(self, height: int = 54) -> None:
        super().__init__()
        self._counts: list[int] = []
        self.setFixedHeight(height)

    def set_counts(self, counts) -> None:
        self._counts = [int(c) for c in (counts or [])]
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        from PyQt6.QtGui import QPalette
        if not self._counts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = max(self._counts) or 1
        w = self.width() / len(self._counts)
        h = self.height() - 1
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_pal(QPalette.ColorRole.Highlight))
        for i, c in enumerate(self._counts):
            bh = h * c / top
            if bh > 0:
                p.drawRoundedRect(QRectF(i * w + 0.5, h - bh, max(w - 1, 1), bh), 1, 1)
        p.setPen(QPen(_pal(QPalette.ColorRole.Mid), 1))
        p.drawLine(0, h, self.width(), h)


class StatTile(QFrame):
    """A small tinted tile: a muted name over a value."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.setProperty("class", "StatTile")
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 5, 8, 6)
        v.setSpacing(0)
        self.name = QLabel(name)
        self.name.setProperty("class", "StatName")
        self.value = QLabel("")
        self.value.setProperty("class", "StatValue")
        v.addWidget(self.name)
        v.addWidget(self.value)

    def set(self, name: str, value: str) -> None:
        self.name.setText(name)
        self.value.setText(value)
        self.value.setToolTip(value)


class TileGrid(QWidget):
    """Stat tiles, two a row; ``show_stats`` fills / hides them."""

    def __init__(self, n: int = 6) -> None:
        super().__init__()
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        self.tiles = [StatTile("") for _ in range(n)]
        for i, t in enumerate(self.tiles):
            g.addWidget(t, i // 2, i % 2)

    def show_stats(self, pairs) -> None:
        pairs = list(pairs)
        for i, t in enumerate(self.tiles):
            if i < len(pairs):
                t.set(*pairs[i])
                t.setVisible(True)
            else:
                t.setVisible(False)
