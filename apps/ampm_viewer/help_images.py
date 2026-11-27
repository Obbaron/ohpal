"""The help articles' screenshots: cropped, marked up and saved into
``shell/assets/help/images`` from the screenshots they were taken from.

    just help-images <folder of screenshots>

The screenshots themselves are not kept in the repository (they are whole
screens, with whatever else was on them); ``SHOTS`` says, for each image an
article uses, which screenshot it comes from (by file name), the part of it
to keep, and what to mark. Run it again after retaking a screenshot: images
whose screenshot isn't in the folder are left as they are.

Marks follow the house style of the how-to guides: a red (#ED1C24) box, 4 px,
round the thing to click or look at, and when an image has more than one, a
bold red number ("1.") just above each box's top-left corner, in the order the
article goes through them. On a wide image (a whole screen) both are a little
bigger, so they can still be read when the help shows it scaled down. A box can also be ``number=False`` (drawn, not
counted), for a screenshot that came with its box already drawn.

An article shows ``name.dark.png`` instead of ``name.png`` when the app is in
dark mode, if there is one: give both screenshots (``src`` and ``dark``).

Coordinates are in the screenshot's own pixels: crop ``(left, top, right,
bottom)`` and boxes the same, so they can be read straight off the image.
Uses Qt only (no extra packages); run from anywhere in the repository.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent                       # apps/ampm_viewer
ASSETS = HERE / "src" / "ampm_viewer" / "shell" / "assets"
OUT = ASSETS / "help" / "images"
FONT = ASSETS / "fonts" / "LiberationSans-Bold.ttf"

RED = "#ED1C24"
STROKE = 4          # box line, px (at least)
NUMBER_PX = 22      # number height, px (at least)
NUMBER_GAP = 3      # number to box, px
# A wide image is shown scaled down to the help's reading column, so its marks
# grow with it to stay readable there: line and number per image width.
STROKE_PER_PX = 1 / 420
NUMBER_PER_PX = 1 / 64


@dataclass
class Box:
    rect: tuple[int, int, int, int]       # left, top, right, bottom
    number: bool = True                   # counted and labelled "n."
    draw: bool = True                     # False: already in the screenshot
    at: str = "above"                     # the number: above / left / right / below


@dataclass
class Shot:
    src: str                              # screenshot file name
    crop: tuple[int, int, int, int]
    boxes: list[Box] = field(default_factory=list)
    dark: str | None = None               # the dark-mode screenshot, if any
    # (rect, text): cover rect with the colour at its top-left, write text
    redact: list[tuple[tuple[int, int, int, int], str]] = field(default_factory=list)


def B(*rect: int, number: bool = True, draw: bool = True, at: str = "above") -> Box:
    return Box(tuple(rect), number, draw, at)


# The app's window in the four app screenshots (Windows, 100% scale), with a
# strip of the desktop round it for the numbers of boxes at its edges.
APP = (277, 70, 1643, 959)

SHOTS: dict[str, Shot] = {
    # -- Getting started: exporting the data (export-data.md) ---------------
    "datahub-launch.png": Shot(
        "01_datahub_generator.png", (1560, 0, 1919, 330),
        [B(1825, 93, 1900, 197, draw=False, number=False)]),
    "datahub-build-folder.png": Shot(
        "02a_machine.png", (0, 0, 1919, 1032),
        [B(1861, 164, 1897, 195), B(724, 326, 1326, 377)]),
    "datahub-output-folder.png": Shot(
        "02b_populate.png", (0, 0, 1919, 1032),
        [B(1861, 216, 1897, 247), B(137, 475, 1895, 532), B(856, 982, 960, 1023)]),
    "datahub-export-packets.png": Shot(
        "03a_packets.png", (0, 0, 1919, 1032),
        [B(1791, 187, 1906, 253), B(962, 982, 1068, 1023)]),
    "datahub-start.png": Shot(
        "03b_start.png", (0, 0, 1919, 1032), [B(1702, 907, 1838, 952)]),
    "datahub-monitor.png": Shot(
        "04_datahub.png", (190, 75, 1912, 985),
        [B(1826, 191, 1899, 298, draw=False, number=False)]),
    "quantam-parts-csv.png": Shot(
        "05a_parts_csv.png", (0, 0, 1919, 1038),
        [B(1787, 521, 1833, 572, draw=False, number=False),
         B(1794, 968, 1866, 1034, draw=False, number=False)]),
    "quantam-stl.png": Shot(
        "05b_stl.png", (0, 0, 1919, 1032),
        [B(327, 19, 471, 187, draw=False, number=False)]),
    "build-folder.png": Shot(
        "final-check-all-files-in-place.png", (366, 87, 1592, 899),
        [B(614, 254, 1222, 419)]),
    # -- Getting started: installing (install.md) --------------------------
    "install-smartscreen.png": Shot(
        "a_install.png", (556, 199, 1364, 954), [B(1173, 856, 1321, 917)]),
    "install-unblock.png": Shot(
        "b_install.png", (652, 180, 1261, 1045),
        [B(1046, 820, 1142, 850), B(891, 994, 1009, 1034)],
        redact=[((795, 490, 1010, 517), "C:\\Users\\you\\Downloads")]),
    "uninstall-settings.png": Shot(
        "a_uninstall.png", (600, 50, 1620, 440),
        [B(1558, 310, 1590, 342), B(1325, 386, 1592, 414, at="left")]),
    "uninstall-tidy.png": Shot(
        "b_uninstall.png", (660, 279, 1260, 745),
        [B(706, 439, 1206, 539, at="left"), B(974, 614, 1088, 643)]),
    # -- The app itself -----------------------------------------------------
    "file-start.png": Shot(
        "ampm-viewer-main-screen-light.png", APP,
        [B(550, 208, 1338, 333), B(550, 368, 840, 402), B(1433, 370, 1580, 400),
         B(1532, 444, 1562, 580)],
        dark="ampm-viewer-main-screen-dark.png"),
    "data-tab.png": Shot(
        "ampm-viewer-data-grid-light.png", APP,
        [B(309, 105, 1611, 144), B(309, 144, 1611, 202, at="left"),
         B(309, 896, 1611, 927, at="left")],
        dark="ampm-viewer-data-grid-dark.png"),
    "open-folder-picker.png": Shot(
        "open-new.png", (317, 106, 1610, 935),
        [B(566, 284, 1192, 306, at="right"), B(1369, 888, 1480, 917)]),
    "excel-template.png": Shot(
        "excel-template.png", (262, 47, 1676, 951),
        [B(371, 306, 451, 729), B(1162, 306, 1457, 729)]),
}


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QFontDatabase, QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    fid = QFontDatabase.addApplicationFont(str(FONT))
    family = QFontDatabase.applicationFontFamilies(fid)[0] if fid >= 0 else "Sans"
    return app, family


def _sizes(width: int) -> tuple[int, int]:
    """Box line and number height for an image ``width`` px wide."""
    return (max(STROKE, round(width * STROKE_PER_PX)),
            max(NUMBER_PX, round(width * NUMBER_PER_PX)))


def _number_rect(box, w, h, img_w, img_h, at="above", stroke=STROKE):
    """Where a box's number goes (its top-left): above the box's top-left
    corner by default, or left / right of its top edge, or below its
    bottom-left; when that doesn't fit, above, then below, then just inside."""
    x0, y0, x1, y1 = box
    x = max(0, min(x0, img_w - w))
    want = {"left": (x0 - NUMBER_GAP - w - 1, y0),
            "right": (x1 + NUMBER_GAP + 1, y0),
            "below": (x, y1 + NUMBER_GAP)}.get(at)
    if want and 0 <= want[0] <= img_w - w and 0 <= want[1] <= img_h - h:
        return want
    if y0 - NUMBER_GAP - h >= 0:
        return x, y0 - NUMBER_GAP - h
    if y1 + NUMBER_GAP + h <= img_h:
        return x, y1 + NUMBER_GAP
    return x0 + stroke + 2, y0 + stroke + 1


def render(shot: Shot, src: Path, family: str):
    """The finished image (a QImage) from one screenshot."""
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen

    img = QImage(str(src))
    if img.isNull():
        raise SystemExit(f"can't read {src}")
    left, top, right, bottom = shot.crop
    img = img.copy(QRect(left, top, right - left, bottom - top)).convertToFormat(
        QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    for (x0, y0, x1, y1), text in shot.redact:
        r = QRect(x0 - left, y0 - top, x1 - x0, y1 - y0)
        bg = img.pixelColor(r.left() + 1, r.top() + 1)
        p.fillRect(r, bg)
        font = QFont(family)
        font.setPixelSize(int((y1 - y0) * 0.58))
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor("#1a1a1a"))
        p.drawText(r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    stroke, number_px = _sizes(img.width())
    red = QColor(RED)
    pen = QPen(red, stroke)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    font = QFont(family)
    font.setPixelSize(number_px)
    font.setWeight(QFont.Weight.Bold)
    fm = QFontMetrics(font)
    counted = sum(b.number for b in shot.boxes)
    n = 0
    for b in shot.boxes:
        x0, y0, x1, y1 = (b.rect[0] - left, b.rect[1] - top,
                          b.rect[2] - left, b.rect[3] - top)
        if b.draw:
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            half = stroke // 2   # the line inside the rect, like a paint tool's
            p.drawRect(x0 + half, y0 + half, x1 - x0 - stroke, y1 - y0 - stroke)
        if b.number and counted > 1:
            n += 1
            label = f"{n}."
            w, h = fm.horizontalAdvance(label), fm.ascent()
            x, y = _number_rect((x0, y0, x1, y1), w, h, img.width(), img.height(),
                                b.at, stroke)
            p.setFont(font)
            p.setPen(red)
            p.drawText(x, y + fm.ascent() - 1, label)
    p.end()
    return img


def save(img, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not img.save(str(path), "PNG", 0):         # 0: smallest file
        raise SystemExit(f"can't write {path}")
    try:                                          # optional: pip install pyoxipng
        import oxipng
        oxipng.optimize(str(path), level=3)
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("screenshots", type=Path, help="folder of the screenshots")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", nargs="*", help="image names to make (default: all)")
    args = ap.parse_args(argv)
    _, family = _app()
    made, missing = 0, []
    for name, shot in SHOTS.items():
        if args.only and name not in args.only:
            continue
        for src, out in ((shot.src, name), (shot.dark, name.replace(".png", ".dark.png"))):
            if src is None:
                continue
            path = args.screenshots / src
            if not path.exists():
                missing.append(src)
                continue
            save(render(shot, path, family), args.out / out)
            made += 1
            print(f"  {out}  <-  {src}")
    print(f"{made} image(s) written to {args.out}")
    if missing:
        print("Not in the folder (left as they are): " + ", ".join(sorted(set(missing))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
