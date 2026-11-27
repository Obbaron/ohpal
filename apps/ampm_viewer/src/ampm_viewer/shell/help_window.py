"""The help window: a searchable list of articles beside a reader.

Non-modal, so it can stay open next to the work. ``open_for`` shows the
article that fits where the user is (see ``MainWindow._help_context``); the
content and the search live in ``help`` and need no Qt.

It wears the same frameless-card look as the app's dialogs (rounded card, a
bold title, bold boxless section headings, muted secondary text). Having no
title bar, it is moved by dragging its top strip and resized from the grip in
its bottom-right corner.

Pictures (``![caption](images/name.png)``, see ``help``) sit in a framed band
with their caption under it, the frame and band drawn from the palette so
they follow the theme; ``name.dark.png`` is shown in dark mode when there is
one. A picture is scaled down to the reading column (smoothly, at the
screen's pixel ratio) and refitted when the window is resized; clicking it
opens it at full size (``ImageWindow``).
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QKeySequence,
    QPalette,
    QPixmap,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
    QTextImageFormat,
    QTextLength,
    QTextTable,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
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
from .card import DraggableCard

_ID_ROLE = Qt.ItemDataRole.UserRole            # article id ("" for a heading)
_EXCERPT_ROLE = Qt.ItemDataRole.UserRole + 1   # search-hit excerpt
_HIT = QColor(255, 204, 64, 130)               # search-term highlight in the text
# The dialogs' shared look (see macro_dialog / export_dialog).
_TITLE_QSS = "font-size: 14pt; font-weight: 600;"
_MUTED_QSS = "color: palette(placeholder-text);"
_DRAG_STRIP_PX = 52  # the card's top strip that moves the window when dragged
# Pictures: the placeholder paragraph a picture stands as until it is put in
# (plain letters, which Markdown leaves alone), the band round it, the scheme
# of its resource names and of its click-to-enlarge link.
_IMG_TOKEN = "HELPPICTURE{}END"
_FIG_PAD = 8.0          # band padding round the picture, px
_FIG_BORDER = 1.0
_IMG_SCHEME = "helpimg"     # resource: helpimg:<theme>/<width>/<path>
_OPEN_SCHEME = "helpimage"  # link: helpimage:<path>


def is_dark(palette: QPalette) -> bool:
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def image_path(path: str, dark: bool):
    """The file to show for an article's picture ``path`` (``images/a.png``):
    its ``.dark`` variant in dark mode when there is one. None if missing."""
    candidates = [helpdocs.dark_variant(path), path] if dark else [path]
    for c in candidates:
        f = helpdocs.HELP_DIR / c
        if f.is_file():
            return f
    return None


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


class HelpWindow(DraggableCard, QWidget):
    """Articles on the left (with search), the selected one on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AMPM Viewer Help")
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
            # The article list sits on a panel of its own shade (as the
            # Settings window's categories do).
            "#HelpSide { background: palette(alternate-base); border-radius: 6px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        # -- left: title, search, list -------------------------------------
        side = QWidget()
        side.setObjectName("HelpSide")
        side.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 10, 10, 10)
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
        from . import crash

        self.version = QLabel(f"AMPM Viewer {crash.version()}")
        self.version.setStyleSheet(_MUTED_QSS)
        self.version.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        sl.addWidget(self.version)

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
        # Pictures follow the reading column's width.
        self._fitter = _OnResize(self._schedule_fit, self.view.viewport())
        ml.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.close_btn)
        buttons.addSpacing(8)  # clear of the corner grip
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
        # Edges and corners resize the frameless window; a grip in its corner.
        self.enable_resize(outer, card)

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
                and event.position().y() <= _DRAG_STRIP_PX
                and not self._edges_at(event.position().toPoint())):
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
        if url.scheme() == _OPEN_SCHEME:
            self._open_picture(url.toString()[len(_OPEN_SCHEME) + 1:])
        elif url.scheme() == "help":
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
        pictures: list[tuple[str, str]] = []

        def hold(m) -> str:
            pictures.append((m.group(1), m.group(2)))
            return _IMG_TOKEN.format(len(pictures) - 1)

        body = helpdocs.IMAGE_RE.sub(hold, body)
        self.view.setMarkdown(body)
        self._polish(doc, base)
        self._insert_pictures(doc, pictures, base)
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

    # -- pictures ----------------------------------------------------------
    def _insert_pictures(self, doc: QTextDocument, pictures, base: QFont) -> None:
        """Put each picture where its placeholder paragraph is: a framed band
        (the palette's border colour round the alternate-base tint) holding
        the picture and its caption, muted and centred."""
        if not pictures:
            return
        pal = self.palette()
        dark = is_dark(pal)
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        for n in range(len(pictures) - 1, -1, -1):
            caption, path = pictures[n]
            found = doc.find(_IMG_TOKEN.format(n))
            if found.isNull():
                continue
            block = found.block()
            cursor.setPosition(block.position())
            cursor.setPosition(block.position() + block.length() - 1,
                               QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            # The emptied paragraph stays (a frame goes between blocks), as
            # does the one Qt adds after the frame: next to no height. (A
            # fixed line height of 0 counts as unset, hence 1 px.)
            gone = QTextBlockFormat()
            gone.setLineHeight(1.0, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
            gone.setTopMargin(0.0)
            gone.setBottomMargin(0.0)
            tiny = QTextCharFormat()       # an empty line is as tall as its font
            tiny_font = QFont(base)
            tiny_font.setPixelSize(1)
            tiny.setFont(tiny_font)
            cursor.setBlockFormat(gone)
            cursor.setBlockCharFormat(tiny)
            ff = QTextFrameFormat()
            ff.setBorder(_FIG_BORDER)
            ff.setBorderBrush(QBrush(pal.color(QPalette.ColorRole.Mid)))
            ff.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
            ff.setPadding(_FIG_PAD)
            ff.setBackground(QBrush(pal.color(QPalette.ColorRole.AlternateBase)))
            ff.setTopMargin(4.0)
            ff.setBottomMargin(12.0)
            ff.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100.0))
            frame = cursor.insertFrame(ff)
            centred = QTextBlockFormat()
            centred.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            cursor.setBlockFormat(centred)
            img = QTextImageFormat()
            img.setName(f"{_IMG_SCHEME}:pending/{path}")
            img.setProperty(QTextFormat.Property.UserProperty, path)
            img.setProperty(QTextFormat.Property.UserProperty + 1, int(dark))
            img.setAnchor(True)
            img.setAnchorHref(f"{_OPEN_SCHEME}:{path}")
            img.setToolTip(f"{caption} (click to see it full size)")
            cursor.insertImage(img)
            cap = QTextBlockFormat(centred)
            cap.setTopMargin(6.0)
            cf = QTextCharFormat()
            cf.setFont(_resized(base, -1.0),
                       QTextCharFormat.FontPropertiesInheritanceBehavior
                       .FontPropertiesSpecifiedOnly)
            cf.setForeground(QBrush(pal.color(QPalette.ColorRole.PlaceholderText)))
            cursor.insertBlock(cap, cf)
            cursor.insertText(caption, cf)
            after = QTextCursor(doc)
            after.setPosition(frame.lastPosition() + 1)
            if not after.block().text():
                after.setBlockFormat(gone)
                after.setBlockCharFormat(tiny)
        cursor.endEditBlock()
        self._fit_pictures()

    def _picture_room(self) -> tuple[int, int]:
        """Room for a picture: the reading column's width, and a height
        (most of the column's) so a tall one doesn't fill the view, px."""
        doc = self.view.document()
        vp = self.view.viewport()
        room = (vp.width() - 2 * doc.documentMargin()
                - 2 * (_FIG_PAD + _FIG_BORDER) - 6)
        return max(80, int(room)), max(220, int(vp.height() * 0.62))

    def _fit_pictures(self) -> None:
        """Scale every picture to the reading column (never above its own
        size), smoothly and at the screen's pixel ratio, so it stays sharp."""
        doc = self.view.document()
        width, height = self._picture_room()
        ratio = max(1.0, self.view.devicePixelRatioF())
        cursor = QTextCursor(doc)
        block = doc.begin()
        edits = []
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if frag.isValid() and fmt.isImageFormat():
                    imgf = fmt.toImageFormat()
                    path = imgf.property(QTextFormat.Property.UserProperty)
                    if path:
                        edits.append((frag.position(), imgf, path))
                it += 1
            block = block.next()
        if not edits:
            return
        cursor.beginEditBlock()
        for pos, imgf, path in edits:
            dark = bool(imgf.property(QTextFormat.Property.UserProperty + 1))
            source = self._picture(path, dark)
            if source is None:
                continue
            scale = min(1.0, width / source.width(), height / source.height())
            w = max(1, round(source.width() * scale))
            h = max(1, round(source.height() * scale))
            name = f"{_IMG_SCHEME}:{'dark' if dark else 'light'}/{w}/{path}"
            if imgf.name() == name:
                continue
            if doc.resource(QTextDocument.ResourceType.ImageResource.value,
                            QUrl(name)) is None:
                scaled = source if w == source.width() else source.scaled(
                    round(w * ratio), round(h * ratio),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                if w != source.width():
                    scaled.setDevicePixelRatio(ratio)
                doc.addResource(QTextDocument.ResourceType.ImageResource.value,
                                QUrl(name), scaled)
            new = QTextImageFormat(imgf)
            new.setName(name)
            new.setWidth(w)
            new.setHeight(h)
            cursor.setPosition(pos)
            cursor.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(new)
        cursor.endEditBlock()

    def _picture(self, path: str, dark: bool) -> QImage | None:
        """A picture's file, read once per window."""
        f = image_path(path, dark)
        if f is None:
            return None
        cache = self.__dict__.setdefault("_pictures", {})
        key = str(f)
        if key not in cache:
            img = QImage(key)
            cache[key] = None if img.isNull() else img
        return cache[key]

    def _schedule_fit(self) -> None:
        if not getattr(self, "_fit_pending", False):
            self._fit_pending = True

            def run() -> None:
                self._fit_pending = False
                self._fit_pictures()

            QTimer.singleShot(60, run)

    def _open_picture(self, path: str) -> None:
        source = self._picture(path, is_dark(self.palette()))
        if source is None:
            return
        caption = next((c for c, p in (helpdocs.find(self._articles, self._current)
                                        .images() if self._current else [])
                        if p == path), "")
        win = getattr(self, "_image_window", None)
        if win is None:
            win = self._image_window = ImageWindow(self)
        win.show_image(source, caption)

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


class _OnResize(QObject):
    """Calls ``slot`` when the watched widget is resized."""

    def __init__(self, slot, widget: QWidget) -> None:
        super().__init__(widget)
        self._slot = slot
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.Resize:
            self._slot()
        return False


class ImageWindow(DraggableCard, QWidget):
    """A help picture at its own size (a screenshot as it was on the screen),
    scrolling when it is bigger than the window; the help window's card look.
    Esc or Close closes it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Picture")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(360, 240)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("HelpCard")
        card.setStyleSheet(
            "#HelpCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)
        self.caption = QLabel("")
        self.caption.setStyleSheet(_TITLE_QSS)
        self.caption.setWordWrap(True)
        lay.addWidget(self.caption)
        self.area = QScrollArea()
        self.area.setFrameShape(QFrame.Shape.NoFrame)
        self.area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.area.setWidget(self.picture)
        self.area.setWidgetResizable(True)
        lay.addWidget(self.area, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.close_btn)
        buttons.addSpacing(8)
        lay.addLayout(buttons)
        self.enable_resize(outer, card)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)

    def show_image(self, image: QImage, caption: str) -> None:
        self.caption.setText(caption)
        self.picture.setPixmap(QPixmap.fromImage(image))
        screen = (self.parentWidget() or self).screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        chrome_w, chrome_h = 2 * 18 + 24, 14 + 40 + 10 + 40 + 14 + 24
        w = min(image.width() + chrome_w, int(avail.width() * 0.92))
        h = min(image.height() + chrome_h, int(avail.height() * 0.92))
        self.show()
        self.resize(max(w, 360), max(h, 240))
        self.move(avail.center() - self.rect().center())
        self.raise_()
        self.activateWindow()
