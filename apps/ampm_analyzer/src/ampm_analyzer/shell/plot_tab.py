"""Plot tab — a VisPy 3D canvas.

VisPy is imported lazily and guarded: if VisPy (or an OpenGL context) isn't
available, the tab shows a labelled placeholder instead of crashing, so the
shell runs anywhere. When VisPy is present, a small random scatter with a
turntable camera is shown purely to prove the canvas embeds and renders.

The plot *toolbar* lives on the main window; this widget is only the canvas.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


def _placeholder(message: str) -> QWidget:
    frame = QFrame()
    frame.setStyleSheet("background:#0f1115;")
    lay = QVBoxLayout(frame)
    lab = QLabel(message)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setStyleSheet("color:#8b93a1; font-size:14px;")
    lay.addWidget(lab)
    return frame


class PlotTab(QWidget):
    _counter = 0

    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("tabkind", "plot")
        PlotTab._counter += 1
        self.title = title or f"Plot {PlotTab._counter}"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._build_canvas())

    def _build_canvas(self) -> QWidget:
        try:
            import numpy as np
            from vispy import scene
        except Exception:  # noqa: BLE001 - any import/GL issue -> placeholder
            return _placeholder(
                "3D canvas (VisPy)\n\nVisPy not available in this environment — "
                "placeholder shown.\nThe real scatter renders here once VisPy is "
                "installed."
            )

        try:
            canvas = scene.SceneCanvas(keys="interactive", bgcolor="#0f1115")
            view = canvas.central_widget.add_view()
            view.camera = scene.cameras.TurntableCamera(fov=45, distance=6)

            n = 2000
            pts = np.random.normal(size=(n, 3), scale=1.0).astype("float32")
            colors = np.random.uniform(0.4, 1.0, size=(n, 4)).astype("float32")
            colors[:, 3] = 0.9
            scatter = scene.visuals.Markers()
            scatter.set_data(pts, face_color=colors, size=5)
            view.add(scatter)
            scene.visuals.XYZAxis(parent=view.scene)

            self._canvas = canvas  # keep a reference alive
            return canvas.native
        except Exception as exc:  # noqa: BLE001 - GL context failure -> placeholder
            return _placeholder(f"3D canvas (VisPy)\n\nCould not start canvas:\n{exc}")
