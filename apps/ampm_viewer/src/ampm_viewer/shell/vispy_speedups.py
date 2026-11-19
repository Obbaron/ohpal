"""Speed-ups for two VisPy internals every plot leans on.

Installed once (``install()``, from ``plot_tab``); each falls back to VisPy's
own code if its internals are not what this expects.

- **Glyphs.** VisPy draws text from signed-distance-field glyphs it makes on
  the CPU: each character is rendered by FreeType at 256 pt, read back as a
  Python list and turned into a distance field. A ``TextureFont`` caches them,
  but only for itself, and every text visual gets its own font manager, so
  every axis label, tick label and legend row made them all again (a quarter
  of the time to open a plot). The finished glyph tiles are kept here for the
  process, keyed by face / bold / italic / character: a font only copies the
  tile into its own texture atlas (GL objects stay per canvas).
- **Shader variables.** Each program built parses its GLSL for uniforms and
  attributes with a regex that backtracks on every line; the same few shader
  sources are parsed again for every visual. The result is kept per source.
- **No matplotlib.** A line drawn in a named colour ("#888888") asks
  VisPy's ``get_colormap`` first, which, for any name it does not know,
  tries ``import matplotlib`` (``has_matplotlib``) on every draw: it loads
  matplotlib where it is installed and searches for it again each frame
  where it is not (the built app). The app never uses matplotlib colour maps,
  so VisPy is told it is absent.
- **Font managers.** A text visual made without a font manager makes its own,
  with a 1024 x 1024 texture atlas per font. Text that VisPy makes inside its
  own widgets (axis ticks, colour bar numbers) cannot be handed one, so while
  ``shared_fonts(fm)`` is active, text visuals made without one use ``fm``.
- **Screen DPI.** Every canvas asks the OS for the screen's DPI. On Linux
  VisPy runs ``xdpyinfo`` and then ``xrandr`` for it, two new processes per
  plot, and where neither is installed or answers (WSL, Wayland, most
  minimal desktops) it logs "WARNING: could not determine DPI" for every
  plot before using 96. The DPI is now found once per session and kept in
  VisPy's config, which canvases read first; when it can't be found, 96, as
  VisPy would use, without the warning.
"""

from __future__ import annotations

from contextlib import contextmanager

import numpy as np

_installed = False
_GLYPHS: dict = {}       # (face, bold, italic, char) -> (offset, advance, bitmap, tile)
_SHADER_VARS: dict = {}  # shader source -> parsed variables
_SHADER_CACHE_MAX = 512
_FONTS: list = []        # font managers made-without-one text visuals use


@contextmanager
def shared_fonts(font_manager):
    """While active, new text visuals without a font manager use this one.
    Use it on one canvas's work only (GL objects belong to a canvas)."""
    _FONTS.append(font_manager)
    try:
        yield
    finally:
        _FONTS.pop()


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    for patch in (_patch_glyphs, _patch_shader_variables, _patch_text_visual,
                  _patch_no_matplotlib, settle_dpi):
        try:
            patch()
        except Exception:  # noqa: BLE001 - VisPy changed: keep its own code
            pass


def settle_dpi() -> int:
    """Ask for the screen DPI once and keep it in VisPy's config (canvases
    read it before asking the OS; it holds whole numbers). 96, VisPy's own
    fallback, when the OS can't say, without VisPy's warning."""
    from vispy.util import config
    from vispy.util.dpi import get_dpi

    if config["dpi"] is None:
        try:
            dpi = round(float(get_dpi(raise_error=True)))
        except Exception:  # noqa: BLE001 - no xdpyinfo / xrandr, or no answer
            dpi = 96
        config["dpi"] = dpi if dpi > 0 else 96
    return config["dpi"]


def _patch_glyphs() -> None:
    from vispy.util.fonts._freetype import _load_font
    from vispy.visuals.text import text as vt

    original = vt.TextureFont._load_char
    if not all(hasattr(vt, n) for n in ("_load_glyph", "SDFRendererCPU")):
        return

    def _load_char(self, char):
        renderer = getattr(self, "_renderer", None)
        if not isinstance(renderer, vt.SDFRendererCPU):
            return original(self, char)
        f = self._font
        key = (f["face"], bool(f["bold"]), bool(f["italic"]), char)
        hit = _GLYPHS.get(key)
        if hit is None:
            made: dict = {}
            vt._load_glyph(f, char, made)
            g = made[char]
            bitmap = g["bitmap"]
            spread = self._spread
            data = np.zeros((bitmap.shape[0] + 2 * spread,
                             bitmap.shape[1] + 2 * spread), np.uint8)
            data[spread:-spread, spread:-spread] = bitmap
            h, w = data.shape[0] // self.ratio, data.shape[1] // self.ratio
            tile = np.zeros((h, w, 3), np.uint8)
            renderer.render_to_texture(data, tile, (0, 0), (w, h))
            hit = (g["offset"], g["advance"], bitmap, tile)
            _GLYPHS[key] = hit
        offset, advance, bitmap, tile = hit
        h, w = tile.shape[:2]
        glyph = dict(char=char, offset=offset, bitmap=bitmap, advance=advance,
                     kerning={})
        self._glyphs[char] = glyph
        # Kerning against this font's glyphs, both ways (as VisPy does).
        face = _load_font(f["face"], f["bold"], f["italic"])
        face.set_char_size(f["size"] * 64)
        for other, other_glyph in self._glyphs.items():
            glyph["kerning"][other] = face.get_kerning(other, char).x / 64.0
            other_glyph["kerning"][char] = face.get_kerning(char, other).x / 64.0
        region = self._atlas.get_free_region(w + 2, h + 2)
        if region is None:
            raise RuntimeError("Cannot store glyph")
        x, y = region[0] + 1, region[1] + 1
        self._atlas[y:y + h, x:x + w, :] = tile
        aw, ah = float(self._atlas.shape[1]), float(self._atlas.shape[0])
        glyph.update(dict(size=(w, h),
                          texcoords=(x / aw, y / ah, (x + w) / aw, (y + h) / ah)))

    vt.TextureFont._load_char = _load_char


def _patch_shader_variables() -> None:
    from vispy.gloo import program as gp

    original = gp.Program._parse_variables_from_code
    if not hasattr(gp.Program, "_process_pending_variables"):
        return

    def _parse_variables_from_code(self, update_variables=True):
        code = "\n\n".join([sh.code for sh in self._shaders])
        hit = _SHADER_VARS.get(code)
        if hit is None:
            original(self, update_variables=False)
            if len(_SHADER_VARS) < _SHADER_CACHE_MAX:
                _SHADER_VARS[code] = dict(self._code_variables)
        else:
            self._code_variables = dict(hit)
        if update_variables:
            self._process_pending_variables()

    gp.Program._parse_variables_from_code = _parse_variables_from_code


def _patch_text_visual() -> None:
    from vispy.visuals.text import text as vt

    original = vt.TextVisual.__init__

    def __init__(self, *args, **kwargs):
        if (_FONTS and kwargs.get("font_manager") is None and len(args) < 11
                and kwargs.get("method", "cpu") == "cpu"):
            kwargs["font_manager"] = _FONTS[-1]
        original(self, *args, **kwargs)

    vt.TextVisual.__init__ = __init__


def _patch_no_matplotlib() -> None:
    from vispy.color import colormap

    if hasattr(colormap, "has_matplotlib"):
        colormap.has_matplotlib = lambda *args, **kwargs: False
