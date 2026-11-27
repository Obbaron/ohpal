"""Help pictures: every ![caption](images/x.png) in an article is a framed band
with the picture and its caption under it; dark mode shows x.dark.png where
there is one; a picture fits the reading column (never above its own size,
nor taller than most of the column) and refits when the window is resized;
clicking one opens it at full size; captions are found by search; the image
tool's marks are where its spec says."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import time
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QColor, QImage, QTextDocument, QTextFormat, QTextFrame
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell import help as hd, theme
from ampm_viewer.shell.help_window import HelpWindow, image_path, is_dark


def pump(n=30):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


# --- content -------------------------------------------------------------------
arts = hd.load_articles()
assert hd.check(arts) == [], hd.check(arts)
pictures = {a.id: a.images() for a in arts if a.images()}
assert {"export-data", "install", "overview", "open-build", "create-excel"} <= set(pictures)
assert all(cap.strip() for imgs in pictures.values() for cap, _ in imgs)
assert hd.dark_variant("images/data-tab.png") == "images/data-tab.dark.png"
assert image_path("images/data-tab.png", True).name == "data-tab.dark.png"
assert image_path("images/data-tab.png", False).name == "data-tab.png"
assert image_path("images/build-folder.png", True).name == "build-folder.png", \
    "no dark variant: the one picture in both modes"
assert [a.id for a in hd.search(arts, "unblock")][0] == "install"
assert "export-data" in [a.id for a in hd.search(arts, "datahub monitor")]
assert "Export Parameters CSV" in hd._plain_text(hd.find(arts, "export-data").body)
assert "![" not in hd.excerpt(hd.find(arts, "export-data"), "monitor")
# A missing picture, or one no article uses, is reported.
bad = hd.parse("x", "---\ntitle: X\n---\n# X\n\n![Gone](images/nope.png)\n\n![](images/data-tab.png)\n")
problems = hd.check([*arts, bad])
assert "x: picture 'images/nope.png' is missing" in problems
assert "x: picture 'images/data-tab.png' has no caption" in problems
print(f"{sum(map(len, pictures.values()))} pictures in {len(pictures)} articles; "
      "captions searchable; missing / uncaptioned pictures reported")


def figures(hw):
    """(caption, image format) per picture in the article shown."""
    doc = hw.view.document()
    out = []
    for frame in doc.rootFrame().childFrames():
        if type(frame) is not QTextFrame:
            continue
        first = doc.findBlock(frame.firstPosition())
        it = first.begin()
        img = None
        while not it.atEnd():
            f = it.fragment().charFormat()
            if f.isImageFormat():
                img = f.toImageFormat()
            it += 1
        out.append((first.next().text(), img))
    return out


# --- the window ---------------------------------------------------------------
theme.apply_theme(app, "light")
hw = HelpWindow(); hw.resize(1100, 820); hw.show(); pump()
hw.show_article("export-data"); pump()
figs = figures(hw)
want = hd.find(arts, "export-data").images()
assert [c for c, _ in figs] == [c for c, _ in want], "a framed band per picture, captioned"
room_w, room_h = hw._picture_room()
for (cap, img), (_, path) in zip(figs, want):
    assert img is not None and img.isAnchor() and img.anchorHref() == f"helpimage:{path}"
    assert img.name().startswith("helpimg:light/"), img.name()
    src = hw._picture(path, False)
    assert img.width() <= min(room_w, src.width()) + 0.5 and img.height() <= room_h + 0.5, cap
    assert hw.view.document().resource(
        QTextDocument.ResourceType.ImageResource.value, QUrl(img.name())) is not None
wide = next(img for _, img in figs if img.property(QTextFormat.Property.UserProperty)
            == "images/datahub-build-folder.png")
assert abs(wide.width() - room_w) <= 1, "a screen-wide picture fills the column"
small = next(img for _, img in figs if img.property(QTextFormat.Property.UserProperty)
             == "images/datahub-launch.png")
assert small.width() == hw._picture("images/datahub-launch.png", False).width(), \
    "a small picture keeps its own size"
# no tall gaps round a picture (Qt keeps an empty paragraph each side of a frame)
doc = hw.view.document()
lay = doc.documentLayout()
blk = doc.begin()
while blk.isValid():
    if not blk.text():
        assert lay.blockBoundingRect(blk).height() <= 3, lay.blockBoundingRect(blk).height()
    blk = blk.next()
print(f"light: {len(figs)} framed pictures, fitted to {room_w} px, small ones at their size, "
      "no gaps")

# narrower window: pictures refit
hw.resize(760, 700); pump(40)
room2, _ = hw._picture_room()
wide2 = next(img for _, img in figures(hw) if img.property(QTextFormat.Property.UserProperty)
             == "images/datahub-build-folder.png")
assert room2 < room_w and abs(wide2.width() - room2) <= 1, (room2, wide2.width())
# tall pictures are capped to most of the column's height
hw.show_article("install"); pump()
_, cap_h = hw._picture_room()
tall = next(img for _, img in figures(hw) if img.property(QTextFormat.Property.UserProperty)
            == "images/install-unblock.png")
assert tall.height() <= cap_h + 0.5 and tall.height() < hw._picture("images/install-unblock.png", False).height()
print("resize: refitted; tall pictures capped to the column's height")

# dark mode: the .dark picture where there is one
theme.apply_theme(app, "dark"); pump(40)
assert is_dark(hw.palette())
hw.show_article("overview"); pump()
(_, img), = figures(hw)
assert img.name().startswith("helpimg:dark/") and img.name().endswith("images/data-tab.png")
assert hw._picture("images/data-tab.png", True).cacheKey() != hw._picture("images/data-tab.png", False).cacheKey()
dark_src = image_path("images/data-tab.png", True)
assert dark_src.name == "data-tab.dark.png"
hw.show_article("export-data"); pump()
assert all(i.name().startswith("helpimg:dark/") for _, i in figures(hw)), "the one picture in both modes"
theme.apply_theme(app, "light"); pump(40)
assert all(i.name().startswith("helpimg:light/") for _, i in figures(hw)), "a theme switch redraws"
print("dark mode: the .dark picture; a theme switch swaps them")

# click: the picture at full size, captioned
hw.resize(1100, 820); pump()
_, img = figures(hw)[1]
hw._on_link(QUrl(img.anchorHref())); pump()
iw = hw._image_window
assert iw.isVisible() and iw.caption.text() == figures(hw)[1][0]
pm = iw.picture.pixmap()
src = hw._picture(img.property(QTextFormat.Property.UserProperty), False)
assert (pm.width(), pm.height()) == (src.width(), src.height()), "full size"
iw.close_btn.click(); assert not iw.isVisible()
print("click: opens at full size with its caption; Close")

# --- the image tool ------------------------------------------------------------
import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "help_images", pathlib.Path(hd.HELP_DIR).parents[4] / "help_images.py")
tool = importlib.util.module_from_spec(spec)
import sys; sys.modules["help_images"] = tool  # (its dataclasses look themselves up)
spec.loader.exec_module(tool)
used = {p for a in arts for _, p in a.images()}
for name, shot in tool.SHOTS.items():
    assert f"images/{name}" in used, f"{name}: made but no article uses it"
    assert (hd.IMAGES_DIR / name).is_file(), name
    if shot.dark:
        assert (hd.IMAGES_DIR / name.replace(".png", ".dark.png")).is_file(), name
    left, top, right, bottom = shot.crop
    got = QImage(str(hd.IMAGES_DIR / name))
    assert (got.width(), got.height()) == (right - left, bottom - top), name
    for b in shot.boxes:
        assert left <= b.rect[0] < b.rect[2] <= right and top <= b.rect[1] < b.rect[3] <= bottom, (name, b)
# marks: the red line is where a drawn box is
red = QColor(tool.RED)
for name in ("install-unblock.png", "uninstall-tidy.png"):
    shot = tool.SHOTS[name]
    got = QImage(str(hd.IMAGES_DIR / name))
    for b in shot.boxes:
        x0, y0 = b.rect[0] - shot.crop[0], b.rect[1] - shot.crop[1]
        c = got.pixelColor(x0 + 1, y0 + 1)
        assert abs(c.red() - red.red()) < 8 and c.green() < 60, (name, c.name())
# numbers: above / left as asked, and clear of the image's edges
for name, shot in tool.SHOTS.items():
    w = shot.crop[2] - shot.crop[0]
    stroke, px = tool._sizes(w)
    assert stroke >= tool.STROKE and px >= tool.NUMBER_PX
assert tool._sizes(1919) == (5, 30) and tool._sizes(600) == (4, 22)
assert tool._number_rect((100, 50, 200, 80), 20, 20, 400, 300) == (100, 27), "above"
assert tool._number_rect((100, 50, 200, 80), 20, 20, 400, 300, "left") == (76, 50)
assert tool._number_rect((100, 50, 200, 80), 20, 20, 400, 300, "right") == (204, 50)
assert tool._number_rect((100, 5, 200, 80), 20, 20, 400, 300) == (100, 83), "no room above: below"
print(f"image tool: {len(tool.SHOTS)} images as specified (sizes, marks, numbers)")
print("ALL HELP PICTURE CHECKS PASS")
