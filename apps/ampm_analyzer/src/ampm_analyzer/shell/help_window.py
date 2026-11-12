"""The help window: a searchable list of articles beside a reader.

Non-modal, so it can stay open next to the work. ``open_for`` shows the
article that fits where the user is (see ``MainWindow._help_context``); the
content and the search live in ``help`` and need no Qt.

It wears the same frameless-card look as the app's dialogs (rounded card, a
bold title, bold boxless section headings, muted secondary text). Having no
title bar, it is moved by dragging its top strip and resized from the grip in
its bottom-right corner.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QRect, QSize, Qt, QUrl
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QPalette,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
    QTextLength,
    QTextTable,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizeGrip,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import help as helpdocs

_ID_ROLE = Qt.ItemDataRole.UserRole            # article id ("" for a heading)
_EXCERPT_ROLE = Qt.ItemDataRole.UserRole + 1   # search-hit excerpt
_HIT = QColor(255, 204, 64, 130)               # search-term highlight in the text
# The dialogs' shared look (see macro_dialog / export_dialog).
_TITLE_QSS = "font-size: 14pt; font-weight: 600;"
_MUTED_QSS = "color: palette(placeholder-text);"
_DRAG_STRIP_PX = 52  # the card's top strip that moves the window when dragged


def _resized(font: QFont, delta: float) -> QFont:
    """``font`` made ``delta`` points larger (or smaller). A stylesheet font is
    sized in pixels and reports no point size, so both cases are handled."""
    out = QFont(font)
    if font.pointSizeF() > 0:
        out.setPointSizeF(max(6.0, font.pointSizeF() + delta))
    elif font.pixelSize() > 0:
        out.setPixelSize(max(8, int(round(font.pixelSize() + delta * 96 / 72))))
    return out


class _ArticleDelegate(QStyledItemDelegate):
    """List rows: a section heading, an article title, or (while searching)
    a title with a line of the matching text under it."""

    def _excerpt_font(self, option) -> QFont:
        return _resized(option.font, -1.0)

    def sizeHint(self, option, index) -> QSize:
        base = super().sizeHint(option, index)
        height = option.fontMetrics.height() + 12
        if index.data(_EXCERPT_ROLE):
            height += option.fontMetrics.height() + 2
        if not index.data(_ID_ROLE):
            height += 6  # air above a section heading
        return QSize(base.width(), height)

    def paint(self, painter, option, index) -> None:
        article_id = index.data(_ID_ROLE)
        excerpt = index.data(_EXCERPT_ROLE)
        if article_id and not excerpt:
            super().paint(painter, option, index)  # a plain title row
            return
        painter.save()
        rect: QRect = option.rect
        pal = option.palette
        if not article_id:  # a section heading: bold, not selectable
            f = QFont(option.font)
            f.setWeight(QFont.Weight.DemiBold)
            painter.setFont(f)
            # (The row is not selectable, so its own palette is the greyed
            # "disabled" one; a heading takes the normal text colour.)
            painter.setPen(pal.color(QPalette.ColorGroup.Active,
                                     QPalette.ColorRole.WindowText))
            painter.drawText(
                rect.adjusted(2, 6, -6, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(index.data(Qt.ItemDataRole.DisplayRole)))
            painter.restore()
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(rect, pal.highlight())
        ink = pal.color(QPalette.ColorRole.HighlightedText if selected
                        else QPalette.ColorRole.Text)
        fm = option.fontMetrics
        inner = rect.adjusted(10, 6, -8, -6)
        painter.setPen(ink)
        painter.setFont(option.font)
        title = fm.elidedText(str(index.data(Qt.ItemDataRole.DisplayRole)),
                              Qt.TextElideMode.ElideRight, inner.width())
        painter.drawText(inner, Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignTop, title)
        small = self._excerpt_font(option)
        painter.setFont(small)
        soft = QColor(ink)
        soft.setAlpha(170)
        painter.setPen(soft)
        from PyQt6.QtGui import QFontMetrics

        line = QFontMetrics(small).elidedText(
            str(excerpt), Qt.TextElideMode.ElideRight, inner.width())
        painter.drawText(inner, Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignBottom, line)
        painter.restore()


class HelpWindow(QWidget):
    """Articles on the left (with search), the selected one on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AMPM Analyzer Help")
        # Frameless card, like the dialogs, but a window rather than a modal.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(720, 420)
        self.resize(1000, 680)
        self._articles = helpdocs.load_articles()
        self._current: str | None = None
        self._history: list[str] = []   # visited article ids
        self._at = -1                   # position in the history
        self._rendering = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("HelpCard")
        card.setStyleSheet(
            "#HelpCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
            "#HelpCard QSplitter::handle { background: transparent; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        # -- left: title, search, list -------------------------------------
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)
        title = QLabel("Help")
        title.setStyleSheet(_TITLE_QSS)
        sl.addWidget(title)
        self.search = QLineEdit()
        self.search.setStyleSheet("QLineEdit { padding: 4px 6px; }")
        self.search.setPlaceholderText("Search help")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        self.search.returnPressed.connect(self._open_first_result)
        sl.addWidget(self.search)
        self.list = QListWidget()
        self._boxless(self.list)
        self.list.setItemDelegate(_ArticleDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setUniformItemSizes(False)
        self.list.currentItemChanged.connect(self._on_item)
        sl.addWidget(self.list, 1)
        self.count = QLabel("")
        self.count.setStyleSheet(_MUTED_QSS)
        sl.addWidget(self.count)

        # -- right: back / forward, the article's title, the article --------
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.back_btn = self._nav_button("‹", "Back", lambda: self._step(-1))
        self.fwd_btn = self._nav_button("›", "Forward", lambda: self._step(1))
        bar.addWidget(self.back_btn)
        bar.addWidget(self.fwd_btn)
        self.crumb = QLabel("")
        self.crumb.setStyleSheet(_MUTED_QSS)
        bar.addSpacing(6)
        bar.addWidget(self.crumb, 1)
        ml.addLayout(bar)
        self.title = QLabel("")           # the open article's title
        self.title.setStyleSheet(_TITLE_QSS)
        self.title.setWordWrap(True)
        ml.addWidget(self.title)
        self.view = QTextBrowser()
        self._boxless(self.view)
        self.view.setOpenLinks(False)  # links are ours: help:<article id>
        self.view.setOpenExternalLinks(False)
        self.view.anchorClicked.connect(self._on_link)
        ml.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.close_btn)
        buttons.addWidget(
            QSizeGrip(self), 0,
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        ml.addLayout(buttons)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(side)
        split.addWidget(main)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setHandleWidth(16)  # the gap between the two columns
        split.setSizes([270, 700])
        split.setChildrenCollapsible(False)
        lay.addWidget(split)

        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Esc"), self, activated=self._escape)
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self._step(-1))
        QShortcut(QKeySequence("Alt+Right"), self, activated=lambda: self._step(1))

        self._fill_list()
        self.show_article(helpdocs.HOME)

    @staticmethod
    def _boxless(area) -> None:
        """No frame and no fill, so the list / article sit straight on the
        card. Done through the palette: a stylesheet background would restyle
        the scroll bars too."""
        area.setFrameShape(QFrame.Shape.NoFrame)
        pal = area.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
        area.setPalette(pal)
        area.viewport().setAutoFillBackground(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        """No title bar: dragging the card's top strip moves the window.
        (Controls in the strip take their own clicks and never get here.)"""
        handle = self.windowHandle()
        if (event.button() == Qt.MouseButton.LeftButton and handle is not None
                and event.position().y() <= _DRAG_STRIP_PX):
            handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    @staticmethod
    def _nav_button(text: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.setStyleSheet("QToolButton { font-size: 15pt; padding: 0 8px; }")
        b.clicked.connect(slot)
        return b

    # -- opening ---------------------------------------------------------
    def open_for(self, keys: list[str]) -> None:
        """Show the article for where the user is (``keys``: most specific
        first), clearing any search, and bring the window forward."""
        article = helpdocs.for_context(self._articles, keys)
        if self.search.text():
            self.search.clear()
        if article is not None:
            self.show_article(article.id)
        self.show()
        self.raise_()
        self.activateWindow()

    def current_article(self) -> str | None:
        return self._current

    def show_article(self, article_id: str, *, record: bool = True) -> bool:
        """Display an article. ``record`` adds it to the back/forward history."""
        article = helpdocs.find(self._articles, article_id)
        if article is None:
            return False
        if record and article_id != self._current:
            del self._history[self._at + 1:]
            self._history.append(article_id)
            self._at = len(self._history) - 1
        self._current = article_id
        self._render(article)
        self._select_in_list(article_id)
        self.crumb.setText(f"{article.section}  ›  {article.title}")
        self.title.setText(article.title)
        self.back_btn.setEnabled(self._at > 0)
        self.fwd_btn.setEnabled(self._at < len(self._history) - 1)
        return True

    def _step(self, delta: int) -> None:
        at = self._at + delta
        if 0 <= at < len(self._history):
            self._at = at
            self.show_article(self._history[at], record=False)

    def _on_link(self, url: QUrl) -> None:
        if url.scheme() == "help":
            self.show_article(url.path() or url.toString()[len("help:"):])
        elif url.scheme() in ("http", "https"):
            from PyQt6.QtGui import QDesktopServices

            QDesktopServices.openUrl(url)

    # -- the list --------------------------------------------------------
    def _fill_list(self) -> None:
        """Rebuild the list: every article under its section, or (with a
        search) the matches, best first, each with a line of context."""
        query = self.search.text().strip()
        self._rendering = True
        self.list.clear()
        if not query:
            for section, articles in helpdocs.by_section(self._articles):
                head = QListWidgetItem(section)
                head.setData(_ID_ROLE, "")
                head.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(head)
                for a in articles:
                    item = QListWidgetItem("   " + a.title)
                    item.setData(_ID_ROLE, a.id)
                    self.list.addItem(item)
            self.count.setText(f"{len(self._articles)} articles")
        else:
            hits = helpdocs.search(self._articles, query)
            for a in hits:
                item = QListWidgetItem(a.title)
                item.setData(_ID_ROLE, a.id)
                item.setData(_EXCERPT_ROLE, helpdocs.excerpt(a, query))
                item.setToolTip(a.section)
                self.list.addItem(item)
            n = len(hits)
            self.count.setText(
                f"{n} result{'s' if n != 1 else ''}" if n
                else f"No articles match “{query}”")
        self._rendering = False
        if self._current:
            self._select_in_list(self._current)

    def _select_in_list(self, article_id: str) -> None:
        self._rendering = True
        found = None
        for i in range(self.list.count()):
            if self.list.item(i).data(_ID_ROLE) == article_id:
                found = self.list.item(i)
                break
        self.list.setCurrentItem(found)  # None clears (article not in results)
        if found is not None:
            self.list.scrollToItem(found)
        self._rendering = False

    def _on_item(self, item, _previous) -> None:
        if self._rendering or item is None:
            return
        article_id = item.data(_ID_ROLE)
        if article_id:
            self.show_article(article_id)

    def _on_search(self, _text: str) -> None:
        self._fill_list()
        # Keep the reader in step: re-mark the hits in the open article.
        article = helpdocs.find(self._articles, self._current or "")
        if article is not None:
            self._mark_hits()

    def _open_first_result(self) -> None:
        for i in range(self.list.count()):
            article_id = self.list.item(i).data(_ID_ROLE)
            if article_id:
                self.show_article(article_id)
                return

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _escape(self) -> None:
        if self.search.text():
            self.search.clear()
        else:
            self.close()

    # -- the reader ------------------------------------------------------
    def _render(self, article) -> None:
        doc = self.view.document()
        base = QFont(self.font())
        doc.setDefaultFont(base)
        doc.setDocumentMargin(2)
        # The article's "# Title" line is shown by the title label instead.
        body = re.sub(r"\A\s*#(?!#)[^\n]*\n+", "", article.body)
        self.view.setMarkdown(body)
        self._polish(doc, base)
        self._mark_hits()
        self.view.verticalScrollBar().setValue(0)
        if self.search.text().strip():
            self._scroll_to_first_hit()

    def _polish(self, doc: QTextDocument, base: QFont) -> None:
        """Typography Qt's Markdown import leaves plain: heading sizes and
        spacing, line height, code backgrounds, boxless tables."""
        pal = self.palette()
        code_bg = pal.color(QPalette.ColorRole.AlternateBase)
        link = pal.color(QPalette.ColorRole.Link)
        # Headings follow the dialogs' section labels: bold, barely larger
        # than the text (the big title is the card's own label).
        sizes = {1: 3.0, 2: 1.5, 3: 0.0}        # heading level → pt above body
        tops = {1: 0.0, 2: 16.0, 3: 10.0}

        def is_code(b) -> bool:
            f = b.blockFormat()
            return b.isValid() and (
                f.hasProperty(QTextFormat.Property.BlockCodeFence)
                or f.hasProperty(QTextFormat.Property.BlockCodeLanguage))

        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        block = doc.begin()
        while block.isValid():
            bfmt = block.blockFormat()
            level = bfmt.headingLevel()
            new = QTextBlockFormat(bfmt)
            in_code = is_code(block)
            nxt = block.next()
            if level:
                first = not block.previous().isValid()
                new.setTopMargin(0.0 if first else tops.get(level, 12.0))
                new.setBottomMargin(6.0)
            elif in_code:
                new.setBackground(QBrush(code_bg))
                new.setLeftMargin(10.0)
                new.setRightMargin(10.0)
                # Air around the block as a whole, not between its lines.
                new.setTopMargin(0.0 if is_code(block.previous()) else 4.0)
                new.setBottomMargin(0.0 if is_code(nxt) else 12.0)
            else:
                new.setLineHeight(
                    128.0, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
                in_list = block.textList() is not None
                last_of_list = in_list and not (
                    nxt.isValid() and nxt.textList() is not None)
                if not in_list or last_of_list:
                    new.setBottomMargin(8.0)
            cursor.setPosition(block.position())
            cursor.setBlockFormat(new)
            # Character formats, fragment by fragment.
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    cf = frag.charFormat()
                    out = QTextCharFormat()
                    if level:
                        out.setFont(
                            _resized(base, sizes.get(level, 1.0)),
                            QTextCharFormat.FontPropertiesInheritanceBehavior
                            .FontPropertiesSpecifiedOnly)
                        # Markdown import also scales headings by level;
                        # the size above is the whole story.
                        out.setProperty(
                            QTextFormat.Property.FontSizeAdjustment, 0)
                        out.setFontWeight(QFont.Weight.DemiBold)
                    elif cf.fontFixedPitch() and not in_code:
                        out.setBackground(QBrush(code_bg))  # inline `code`
                    if cf.isAnchor():
                        out.setForeground(QBrush(link))
                        out.setFontUnderline(False)
                    if not out.isEmpty():
                        cursor.setPosition(frag.position())
                        cursor.setPosition(frag.position() + frag.length(),
                                           QTextCursor.MoveMode.KeepAnchor)
                        cursor.mergeCharFormat(out)
                it += 1
            block = block.next()

        for frame in doc.rootFrame().childFrames():
            if isinstance(frame, QTextTable):
                tf = frame.format()
                # Boxless, like the dialogs: no grid, a tinted header row.
                tf.setCellPadding(5.0)
                tf.setCellSpacing(0.0)
                tf.setBorder(0.0)
                tf.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_None)
                tf.setTopMargin(4.0)
                tf.setBottomMargin(12.0)
                tf.setWidth(QTextLength(
                    QTextLength.Type.PercentageLength, 100.0))
                frame.setFormat(tf)
                for col in range(frame.columns()):  # header row
                    cell = frame.cellAt(0, col)
                    cfmt = cell.format()
                    cfmt.setBackground(QBrush(code_bg))
                    cell.setFormat(cfmt)
        cursor.endEditBlock()

    def _hit_selections(self) -> list:
        terms = helpdocs._terms(self.search.text())
        if not terms:
            return []
        doc = self.view.document()
        fmt = QTextCharFormat()
        fmt.setBackground(QBrush(_HIT))
        out = []
        from PyQt6.QtCore import QRegularExpression

        for term in terms:
            rx = QRegularExpression(
                r"\b" + re.escape(term),
                QRegularExpression.PatternOption.CaseInsensitiveOption)
            cursor = doc.find(rx, 0)
            while not cursor.isNull() and len(out) < 400:
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = fmt
                out.append(sel)
                cursor = doc.find(rx, cursor)
        return out

    def _mark_hits(self) -> None:
        self.view.setExtraSelections(self._hit_selections())

    def _scroll_to_first_hit(self) -> None:
        hits = self.view.extraSelections()
        if not hits:
            return
        first = min(hits, key=lambda s: s.cursor.selectionStart())
        cursor = QTextCursor(first.cursor)
        cursor.clearSelection()
        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        # A theme switch changes the palette the article was drawn with.
        if event.type() == event.Type.PaletteChange and self._current:
            article = helpdocs.find(self._articles, self._current)
            if article is not None and not self._rendering:
                self._render(article)
