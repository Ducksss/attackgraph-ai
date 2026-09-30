"""scripts/build_assets.py replaces an image only when it changed visibly."""

import sys

from helpers import ROOT
from PIL import Image

sys.path.insert(0, str(ROOT / "scripts"))
import build_assets  # noqa: E402


def png(path, color, size=(8, 8), mode="RGB"):
    Image.new(mode, size, color).save(path)
    return path


def test_anti_aliasing_noise_is_not_a_change(tmp_path):
    old = png(tmp_path / "old.png", (100, 100, 100))
    assert not build_assets.visibly_changed(png(tmp_path / "same.png", (100, 100, 100)), old)
    assert not build_assets.visibly_changed(png(tmp_path / "noise.png", (100, 100, 100 + build_assets.NOISE)), old)
    assert build_assets.visibly_changed(png(tmp_path / "text.png", (100, 100, 101 + build_assets.NOISE)), old)


def test_a_colour_change_counts_in_an_opaque_rgba_image(tmp_path):
    # getbbox() on an RGBA difference looks at alpha only, which once hid every change like this one.
    old = png(tmp_path / "old.png", (100, 100, 100, 255), mode="RGBA")
    assert build_assets.visibly_changed(png(tmp_path / "new.png", (100, 100, 200, 255), mode="RGBA"), old)


def test_transparency_size_and_missing_files_count(tmp_path):
    old = png(tmp_path / "old.png", (0, 0, 0, 0), mode="RGBA")
    assert build_assets.visibly_changed(png(tmp_path / "opaque.png", (0, 0, 0, 255), mode="RGBA"), old)
    assert build_assets.visibly_changed(png(tmp_path / "wider.png", (0, 0, 0, 0), size=(9, 8), mode="RGBA"), old)
    assert build_assets.visibly_changed(old, tmp_path / "absent.png")


def test_text_files_compare_by_content(tmp_path):
    a, b = tmp_path / "a.svg", tmp_path / "b.svg"
    a.write_text(build_assets.MARK_SVG)
    b.write_text(build_assets.MARK_SVG)
    assert not build_assets.visibly_changed(a, b)
    b.write_text(build_assets.MARK_SVG.replace("#6366f1", "#000000"))
    assert build_assets.visibly_changed(a, b)


def test_every_output_is_a_committed_file():
    assert (ROOT / "docs" / "brand" / "mark.svg").read_text() == build_assets.MARK_SVG
    for name in build_assets.README_SHOTS.values():
        assert (ROOT / "docs" / "images" / name).is_file(), name
    for name, shot, *_ in build_assets.GALLERY:
        assert shot in build_assets.SHOTS, shot
        assert (ROOT / "docs" / "devpost" / "gallery" / f"{name}.png").is_file(), name
