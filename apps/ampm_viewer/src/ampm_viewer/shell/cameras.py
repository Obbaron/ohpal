"""The 3D plots' camera: VisPy's turntable with the mouse as users expect it.

- **Left drag** rotates (as VisPy).
- **Scroll** zooms (as VisPy).
- **Right drag** pans: the point under the mouse follows it. VisPy zooms on
  a right drag and pans only on Shift + left drag (still there).

Imported only once VisPy is (``PlotTab._build_canvas``).
"""

from __future__ import annotations

import numpy as np
from vispy.scene.cameras import TurntableCamera


class Turntable3D(TurntableCamera):
    def viewbox_mouse_event(self, event) -> None:
        if (event.type == "mouse_move" and not event.handled and self.interactive
                and event.press_event is not None
                and 2 in event.buttons and 1 not in event.buttons
                and not event.mouse_event.modifiers):
            self.pan_drag(event.mouse_event.press_event.pos, event.mouse_event.pos)
            return
        super().viewbox_mouse_event(event)

    def pan_drag(self, p1, p2) -> None:
        """Move the centre so the scene follows a drag from screen point
        ``p1`` (where the button went down) to ``p2``. The same sums as
        VisPy's Shift + drag (``Base3DRotationCamera.viewbox_mouse_event``),
        from the centre at the press, so the drag never drifts."""
        if self._event_value is None or len(self._event_value) != 3:
            self._event_value = tuple(self.center)
        norm = np.mean(self._viewbox.size)
        dist = (np.asarray(p1, float)[:2] - np.asarray(p2, float)[:2]) / norm * self._scale_factor
        dist[1] *= -1
        dx, dy, dz = self._dist_to_trans(dist)
        ff = self._flip_factors
        up, forward, right = self._get_dim_vectors()
        dx, dy, dz = right * dx + forward * dy + up * dz
        dx, dy, dz = ff[0] * dx, ff[1] * dy, dz * ff[2]
        c = self._event_value
        self.center = c[0] + dx, c[1] + dy, c[2] + dz
