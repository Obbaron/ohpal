"""The 3D plots' mouse: left drag rotates, scroll zooms, right drag pans (the
scene follows the mouse; VisPy's own Shift + drag pan still works). VisPy
mouse events go straight to the camera: the canvas's own dispatch first
renders a picking pass, which the headless test GL can't do. (VisPy's Qt
backend maps the right button to 2.) Reset view puts the camera back."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from vispy.app.canvas import MouseEvent
from vispy.scene.events import SceneMouseEvent
from vispy.util import keys
app = QApplication([])
from ampm_viewer.shell import controller as cmod
from ampm_viewer.shell.cameras import Turntable3D
from ampm_viewer.shell.plotspec import SCATTER_3D, default_spec
from ampm_viewer.shell.window import MainWindow

cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1300, 800); w.show(); c, s = w.controller, w.session
def pump(n=20):
    for _ in range(n): app.processEvents(); time.sleep(0.005)
def drain():
    t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            pump()
            if not c._queue and c._current is None and not c._busy: return
        time.sleep(0.01)
def wait_ready(kick):
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); kick(); loop.exec(); s.queryReady.disconnect(h)

wait_ready(lambda: c.open_recent(BUILD)); drain()
tab = w._open_plot(default_spec(SCATTER_3D, list(s.result.df.columns), s.renames,
                                dbscan=c.dbscan_params()), ("all", None, None))
drain(); pump(40)
cam = tab._view.camera
assert isinstance(cam, Turntable3D), type(cam)
LEFT, RIGHT = 1, 2
mid = np.array(tab._view.pos, float) + np.array(tab._view.size, float) / 2

def send(ev):
    cam.viewbox_mouse_event(SceneMouseEvent(ev, tab._view))
def drag(button, dx, dy, mods=(), steps=6):
    press = MouseEvent("mouse_press", pos=mid, button=button, buttons=[button], modifiers=mods)
    send(press); last = press
    for i in range(1, steps + 1):
        ev = MouseEvent("mouse_move", pos=mid + np.array([dx, dy]) * i / steps, button=button,
                        buttons=[button], modifiers=mods, press_event=press, last_event=last)
        send(ev); last = ev
    send(MouseEvent("mouse_release", pos=last.pos, button=button, buttons=[], modifiers=mods,
                    press_event=press, last_event=last))
    pump()
def state():
    return (np.array(cam.center, float), float(cam.scale_factor),
            float(cam.elevation), float(cam.azimuth))
def screen_of(point):
    """Where a scene point is drawn, in canvas pixels."""
    p = tab._view.scene.node_transform(tab._canvas.scene).map(np.r_[point, 1.0])
    return p[:2] / p[3]

# Right drag: pans. The scene follows the mouse, nothing rotates or zooms.
c0, s0, e0, a0 = state()
anchor = screen_of(c0)
drag(RIGHT, 80, 40)
c1, s1, e1, a1 = state()
assert not np.allclose(c1, c0), "right drag moved the camera"
assert (s1, e1, a1) == (s0, e0, a0), "right drag only pans"
moved = screen_of(c0) - anchor
assert np.allclose(moved, (80, 40), atol=6), moved   # the point under the mouse came along
print(f"right drag pans: the scene followed the mouse by {moved.round(1)} px")

# A second right drag starts from where the first left off (no jump back).
drag(RIGHT, -30, 0)
c2 = state()[0]
assert np.allclose(screen_of(c0) - anchor, (50, 40), atol=6)

# Left drag: rotates, the centre stays.
drag(LEFT, 60, 20)
c3, s3, e3, a3 = state()
assert np.allclose(c3, c2) and s3 == s1 and (e3, a3) != (e1, a1), "left drag rotates"
print(f"left drag rotates: azimuth {a1:.0f} -> {a3:.0f}, elevation {e1:.0f} -> {e3:.0f}")

# Shift + left drag: VisPy's pan, still there.
drag(LEFT, 40, 0, (keys.SHIFT,))
c4, s4, e4, a4 = state()
assert not np.allclose(c4, c3) and (e4, a4) == (e3, a3)

# Scroll: zooms.
send(MouseEvent("mouse_wheel", pos=mid, delta=(0, 1), modifiers=())); pump()
assert state()[1] < s4, "scroll in zooms in"
print("scroll zooms; Shift + left drag still pans")

# Reset view: back to the whole build, centred.
tab.set_control("reset_view", None); pump()
assert np.allclose(state()[0], c0, atol=1e-6), (state()[0], c0)
print("Reset view recentres")

# The screen DPI is found once per session, quietly: on Linux without xdpyinfo
# or xrandr (WSL, Wayland) VisPy logged "could not determine DPI" for every plot.
import io, logging, os
from vispy.util import config as vconfig, logger as vlogger
from ampm_viewer.shell import vispy_speedups
assert isinstance(vconfig["dpi"], int), vconfig["dpi"]     # settled when the first plot was made
heard = io.StringIO(); hd = logging.StreamHandler(heard); vlogger.addHandler(hd)
env = dict(os.environ)
os.environ["DISPLAY"] = ":99"; os.environ["PATH"] = ""      # an X display, no tools to ask
vconfig["dpi"] = None
assert vispy_speedups.settle_dpi() == 96 and vconfig["dpi"] == 96
tab2 = w._open_plot(default_spec(SCATTER_3D, list(s.result.df.columns), s.renames,
                                 dbscan=c.dbscan_params()), ("all", None, None)); drain()
os.environ.clear(); os.environ.update(env); vlogger.removeHandler(hd)
assert "DPI" not in heard.getvalue() and tab2._canvas.dpi == 96, heard.getvalue()
print("screen DPI: settled once, no warning per plot")
print("ALL OK")
c.shutdown()
