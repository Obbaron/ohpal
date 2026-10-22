# AMPM Analyzer — GUI shell

The overhauled in-app GUI (PyQt6 + VisPy), built shell-first: every control is
present but **not wired up**, so the layout can be tweaked freely before the
actions are connected to the analysis logic in `../main.py` and `../views/`.

See the layout design for the full rationale and the locked decisions.

## Run

```
python -m ampm_analyzer.shell      # the shell directly
python -m ampm_analyzer            # same shell (the app entry now points here)
```

## What's live vs inert

- **Live (structural navigation only):** File → Data navigation, spawning Plot
  tabs (`+` or "New plot"), closing Plot tabs, the toolbar/dock swapping per
  active tab, and the status-bar helpers.
- **Inert (stubs):** every data action (Add column, filters, layer selector,
  export…), every plot action (colour, camera, selection, decimation…), and
  all dock sliders. No signals connected yet.

## Layout map (files)

| File | Surface |
| --- | --- |
| `window.py` | Main window: tab strip, context toolbar, dock, status bar |
| `backstage.py` | File tab (backstage): sidebar + tiles + Recent/Favourites/Search |
| `data_tab.py` | Data tab: the grid (columnar selection, placeholder rows) |
| `plot_tab.py` | Plot tab: VisPy canvas (guarded; placeholder if VisPy absent) |
| `toolbars.py` | Context-swapping toolbar contents + pinned undo/redo/help glyphs |
| `dock.py` | Side panel pages (sliders + info), swapped per view |
| `theme.py` | Stylesheet (incl. the subtle File-tab tint) |
| `app.py` | Entry point (`main()`) |

## Dependencies

- **PyQt6** — already in the workspace (`ampm-analyzer` depends on `PyQt6`).
- **VisPy + NumPy** — needed for the real 3D canvas. Not yet added to
  `pyproject.toml`; the Plot tab falls back to a labelled placeholder until
  they're installed. Add them when wiring the plot path.
