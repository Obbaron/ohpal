"""Help articles: loading, searching, and picking one for where the user is.

An article is a Markdown file under ``assets/help`` with a small header::

    ---
    title: Filters
    section: Data
    order: 60
    keywords: filter, condition, rows, chip
    context: data.filters
    ---
    The article, in Markdown…

``context`` lists the places in the app the article is the right one to open
for (see ``MainWindow._help_context``). Links between articles are written
``[Filters](help:filters)``; the id is the file's name.

No Qt in here, so the content can be checked without a display.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HELP_DIR = Path(__file__).parent / "assets" / "help"
# Sidebar order of the sections; an unknown section sorts after these.
SECTIONS = ("Getting started", "Data", "Plots", "Reference")
HOME = "overview"  # opened when nothing more specific fits

_LINK_RE = re.compile(r"\]\(help:([a-z0-9-]+)\)")
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    section: str
    order: int
    keywords: tuple[str, ...]
    context: tuple[str, ...]
    body: str
    # Lower-cased text for searching, built once.
    _plain: str = field(default="", compare=False, repr=False)
    _headings: str = field(default="", compare=False, repr=False)

    def links(self) -> list[str]:
        """Ids of the articles this one links to."""
        return _LINK_RE.findall(self.body)


def _plain_text(markdown: str) -> str:
    """Markdown with its markup stripped, for searching and excerpts."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", markdown)   # links → label
    text = re.sub(r"^\s*\|?[\s:|-]+\|?\s*$", " ", text, flags=re.M)  # table rules
    text = re.sub(r"[#*`|>]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse(article_id: str, text: str) -> Article:
    """One article from its file text. A missing header is tolerated (the id
    becomes the title) so a half-written file never breaks the help window."""
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        head, sep, rest = text[3:].partition("\n---")
        if sep:
            body = rest.lstrip("\n")
            for line in head.splitlines():
                key, colon, value = line.partition(":")
                if colon:
                    meta[key.strip().lower()] = value.strip()

    def items(key: str) -> tuple[str, ...]:
        return tuple(v.strip() for v in meta.get(key, "").split(",") if v.strip())

    try:
        order = int(meta.get("order", "1000"))
    except ValueError:
        order = 1000
    headings = " ".join(re.findall(r"^#+\s*(.+)$", body, flags=re.M))
    return Article(
        id=article_id,
        title=meta.get("title") or article_id.replace("-", " ").capitalize(),
        section=meta.get("section") or "Reference",
        order=order,
        keywords=items("keywords"),
        context=items("context"),
        body=body,
        _plain=_plain_text(body).lower(),
        _headings=headings.lower(),
    )


def load_articles(directory: Path | None = None) -> list[Article]:
    """Every article, in sidebar order (section, then ``order``, then title)."""
    directory = directory or HELP_DIR
    out = []
    for path in sorted(directory.glob("*.md")):
        try:
            out.append(parse(path.stem, path.read_text(encoding="utf-8")))
        except OSError:
            continue

    def key(a: Article):
        sec = SECTIONS.index(a.section) if a.section in SECTIONS else len(SECTIONS)
        return (sec, a.section, a.order, a.title.lower())

    return sorted(out, key=key)


def by_section(articles: list[Article]) -> list[tuple[str, list[Article]]]:
    """Articles grouped under their section headings, in order."""
    groups: list[tuple[str, list[Article]]] = []
    for a in articles:
        if not groups or groups[-1][0] != a.section:
            groups.append((a.section, []))
        groups[-1][1].append(a)
    return groups


# -- search ------------------------------------------------------------------
def _terms(query: str) -> list[str]:
    return _WORD_RE.findall(query.lower())


def search(articles: list[Article], query: str) -> list[Article]:
    """Articles matching every word of ``query`` (prefix match, so "filt" finds
    "filters"), best first: a hit in the title outranks a keyword, which
    outranks a heading, which outranks the text."""
    terms = _terms(query)
    if not terms:
        return list(articles)
    scored = []
    for position, a in enumerate(articles):
        title = a.title.lower()
        keys = " ".join(a.keywords).lower()
        total = 0
        for t in terms:
            pat = re.compile(r"\b" + re.escape(t))
            score = 0
            if pat.search(title):
                score += 12
            if pat.search(keys):
                score += 8
            if pat.search(a._headings):
                score += 5
            score += min(4, len(pat.findall(a._plain)))
            if score == 0:
                total = 0
                break
            total += score
        if total:
            scored.append((-total, position, a))
    return [a for _score, _pos, a in sorted(scored)]


def excerpt(article: Article, query: str, width: int = 90) -> str:
    """A line of the article's text around the first search hit."""
    # Skip the opening "# Title" line: the list already shows the title.
    plain = _plain_text(re.sub(r"\A\s*#[^\n]*\n", "", article.body))
    low = plain.lower()
    at = -1
    for t in _terms(query):
        m = re.search(r"\b" + re.escape(t), low)
        if m and (at == -1 or m.start() < at):
            at = m.start()
    if at == -1:
        return plain[:width].rstrip() + ("…" if len(plain) > width else "")
    start = max(0, at - width // 3)
    if start:
        space = plain.find(" ", start)
        start = space + 1 if 0 <= space < at else start
    end = min(len(plain), start + width)
    return (("…" if start else "") + plain[start:end].rstrip()
            + ("…" if end < len(plain) else ""))


# -- context -----------------------------------------------------------------
def for_context(articles: list[Article], keys: list[str]) -> Article | None:
    """The article for where the user is. ``keys`` run from most to least
    specific ("plot.elements", "plot.3D Scatter", "plot"); the first one an
    article claims wins, and the overview is the fallback."""
    for key in keys:
        for a in articles:
            if key in a.context:
                return a
    return find(articles, HOME) or (articles[0] if articles else None)


def find(articles: list[Article], article_id: str) -> Article | None:
    for a in articles:
        if a.id == article_id:
            return a
    return None


def check(articles: list[Article]) -> list[str]:
    """Problems in the content: links to articles that don't exist, a context
    claimed twice, a missing overview. Empty when all is well (used by tests)."""
    problems = []
    ids = {a.id for a in articles}
    if HOME not in ids:
        problems.append(f"no '{HOME}' article")
    claimed: dict[str, str] = {}
    for a in articles:
        for target in a.links():
            if target not in ids:
                problems.append(f"{a.id}: links to missing article '{target}'")
        for key in a.context:
            if key in claimed:
                problems.append(
                    f"context '{key}' claimed by both {claimed[key]} and {a.id}")
            claimed[key] = a.id
        if a.section not in SECTIONS:
            problems.append(f"{a.id}: unknown section '{a.section}'")
    return problems
