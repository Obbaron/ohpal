"""Recent builds — a small persisted list, plus the dialog start-dir policy.

Backed by the app's existing ``QSettings("AMPM", "AMPM Analyzer")`` store (the
same one that holds window geometry), so it needs no extra file. Entries are a
JSON blob under a single key; favourites and the two directory hints
(``projects_root``, ``last_browse_dir``) are separate keys.

The store is a thin, stateless wrapper: every call reads/writes QSettings, so
several instances (the controller's and the backstage's) stay in sync.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import QSettings

_ORG = "AMPM"
_APP = "AMPM Analyzer"

_ENTRIES_KEY = "recents/entries"
_PROJECTS_ROOT_KEY = "recents/projects_root"
_LAST_BROWSE_KEY = "recents/last_browse_dir"

_MAX = 10  # cap applies to non-favourites; favourites are always kept


@dataclass
class RecentEntry:
    path: str
    name: str
    last_opened: str            # ISO 8601 (UTC)
    has_cache: bool = False
    favourite: bool = False

    @property
    def exists(self) -> bool:
        try:
            return Path(self.path).is_dir()
        except OSError:
            return False


class RecentStore:
    """Read/write access to the recent-builds list and directory hints."""

    def __init__(self) -> None:
        self._s = QSettings(_ORG, _APP)

    # -- raw entries ---------------------------------------------------
    def _read(self) -> list[RecentEntry]:
        raw = self._s.value(_ENTRIES_KEY, "")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        out: list[RecentEntry] = []
        for d in data:
            try:
                out.append(RecentEntry(**d))
            except TypeError:
                continue  # skip a row from an older/mismatched schema
        return out

    def _write(self, entries: list[RecentEntry]) -> None:
        self._s.setValue(_ENTRIES_KEY, json.dumps([asdict(e) for e in entries]))

    @staticmethod
    def _trim(entries: list[RecentEntry]) -> list[RecentEntry]:
        """Keep every favourite + the newest ``_MAX`` non-favourites, in order."""
        kept: list[RecentEntry] = []
        n = 0
        for e in entries:
            if e.favourite:
                kept.append(e)
            elif n < _MAX:
                kept.append(e)
                n += 1
        return kept

    # -- public: entries ----------------------------------------------
    def load(self, *, prune: bool = True) -> list[RecentEntry]:
        """Entries newest-first. Prunes rows whose folder no longer exists."""
        entries = self._read()
        if prune:
            kept = [e for e in entries if e.exists]
            if len(kept) != len(entries):
                self._write(kept)
            entries = kept
        return entries

    def record(self, path: str | Path, *, has_cache: bool) -> None:
        """Upsert ``path`` to the top, carrying over its favourite flag."""
        p = str(Path(path).resolve())
        entries = self._read()
        fav = next((e.favourite for e in entries if e.path == p), False)
        entries = [e for e in entries if e.path != p]  # dedupe
        entries.insert(
            0,
            RecentEntry(
                path=p,
                name=Path(p).name,
                last_opened=datetime.now(timezone.utc).isoformat(),
                has_cache=has_cache,
                favourite=fav,
            ),
        )
        self._write(self._trim(entries))

    def set_favourite(self, path: str | Path, favourite: bool) -> None:
        p = str(Path(path).resolve())
        entries = self._read()
        for e in entries:
            if e.path == p:
                e.favourite = favourite
        self._write(self._trim(entries))

    def remove(self, path: str | Path) -> None:
        p = str(Path(path).resolve())
        self._write([e for e in self._read() if e.path != p])

    def clear(self) -> None:
        self._s.remove(_ENTRIES_KEY)

    def most_recent(self) -> RecentEntry | None:
        existing = self.load()  # pruned
        return existing[0] if existing else None

    # -- public: directory hints --------------------------------------
    def projects_root(self) -> str | None:
        v = self._s.value(_PROJECTS_ROOT_KEY, "")
        return v or None

    def set_projects_root(self, path: str | Path | None) -> None:
        self._s.setValue(_PROJECTS_ROOT_KEY, str(path) if path else "")

    def last_browse_dir(self) -> str | None:
        v = self._s.value(_LAST_BROWSE_KEY, "")
        return v or None

    def set_last_browse_dir(self, path: str | Path | None) -> None:
        self._s.setValue(_LAST_BROWSE_KEY, str(path) if path else "")

    # -- public: dialog start directory -------------------------------
    def start_dir(self) -> str:
        """Directory the New/Open dialog should open in.

        Tree (first match wins):
          1. the most recent build's parent, if it still exists
          2. the configured projects root, if set and it exists
          3. the last directory browsed to, if it still exists
          4. the user's home directory (the floor)
        """
        mr = self.most_recent()
        if mr is not None:
            parent = Path(mr.path).parent
            if parent.is_dir():
                return str(parent)

        root = self.projects_root()
        if root and Path(root).is_dir():
            return root

        last = self.last_browse_dir()
        if last and Path(last).is_dir():
            return last

        return str(Path.home())
