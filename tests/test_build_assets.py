"""scripts/build_assets.py replaces an image only when it changed visibly, and never after a failed render."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
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


# A stand-in for shoot.mjs: a flat PNG for each job, except that it fails at the job whose file is named
# `fail`, after writing the ones before it, or leaves out the one named `skip`.
def fake_renderer(monkeypatch, color, fail=None, skip=None):
    calls = []

    def run(cmd, timeout, env=None):
        jobs = json.loads(Path(cmd[-1]).read_text())
        calls.append((jobs, timeout))
        for job in jobs:
            out = Path(job["out"])
            if out.name == fail:
                raise build_assets.RenderError("it exited with status 1")
            if out.name != skip:
                out.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (job["width"] // 8, job["height"] // 8), color).save(out)

    monkeypatch.setattr(build_assets, "run", run)
    monkeypatch.setattr(build_assets, "node", lambda: "node")
    monkeypatch.setattr(build_assets, "chrome", lambda: "chrome")
    return calls


def tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A checkout that holds one clean render, standing in for the committed images."""
    root = tmp_path / "repo"
    monkeypatch.setattr(build_assets, "ROOT", root)
    fake_renderer(monkeypatch, (10, 20, 30))
    assert build_assets.main([]) == 0
    return root


def test_a_clean_run_replaces_only_visible_changes(repo, monkeypatch, capsys):
    committed = tree(repo)
    assert all((ROOT / path).is_file() for path in committed), "every output lands on a committed file"
    capsys.readouterr()
    fake_renderer(monkeypatch, (10, 20, 30 + build_assets.NOISE))
    assert build_assets.main([]) == 0
    assert tree(repo) == committed
    assert f"Rendered {len(committed)} files; replaced 0." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("fail", "skip"),
    [("hero.png", None), ("palette.png", None), ("07-how-it-works.png", None), (None, "social-preview.png")],
    ids=["first-shot", "an-asset", "last-asset", "a-file-left-out"],
)
def test_a_failed_render_replaces_nothing(repo, monkeypatch, capsys, fail, skip):
    committed = tree(repo)
    capsys.readouterr()
    # What it did write is visibly different, as a render in a fallback font would be; --force would take all of it.
    fake_renderer(monkeypatch, (200, 0, 0), fail=fail, skip=skip)
    assert build_assets.main(["--force"]) == 1
    assert tree(repo) == committed
    captured = capsys.readouterr()
    assert "failed" in captured.err and "No file was replaced." in captured.err
    assert "replaced" not in captured.out


def test_every_job_asks_for_the_brand_fonts_and_has_a_deadline(repo, monkeypatch):
    calls = fake_renderer(monkeypatch, (10, 20, 30))
    assert build_assets.main([]) == 0
    assert [len(jobs) for jobs, _ in calls] == [len(build_assets.SHOTS), len(build_assets.GALLERY) + 7]
    for jobs, timeout in calls:
        assert all(job["fonts"] == build_assets.FONTS and job["timeout"] == build_assets.JOB_SECONDS * 1000 for job in jobs)
        assert timeout > build_assets.JOB_SECONDS * len(jobs)
    # Each family it checks is one that both kinds of page load from Google Fonts.
    site = (ROOT / "site" / "index.html").read_text()
    for family in {family for family, _ in build_assets.FONTS}:
        assert f"family={family.replace(' ', '+')}" in build_assets.HEAD, family
        assert f"family={family.replace(' ', '+')}" in site, family


def test_run_reports_a_failed_exit():
    with pytest.raises(build_assets.RenderError, match="exited with status 3"):
        build_assets.run([sys.executable, "-c", "raise SystemExit(3)"], timeout=30)


def test_run_kills_a_renderer_that_hangs_and_its_browser(tmp_path):
    # A renderer that starts a child of its own, as shoot.mjs starts Chrome, and then hangs.
    pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    started = time.monotonic()
    with pytest.raises(build_assets.RenderError, match="did not finish within 2 s"):
        build_assets.run([sys.executable, "-c", script], timeout=2)
    assert time.monotonic() - started < 10
    child = int(pid_file.read_text())
    for _ in range(50):  # killed at once; the reparented child may take a moment to be reaped
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    pytest.fail("the renderer's child outlived the timeout")


# shoot.mjs itself, on local pages: each failure must stop the run before the job writes its file.
NODE = shutil.which("node")
NODE_22 = bool(NODE) and subprocess.run([NODE, "-e", "process.exit(+process.versions.node.split('.')[0] >= 22 ? 0 : 1)"]).returncode == 0
CHROME = next((c for c in (os.environ.get("CHROME"), build_assets.MAC_CHROME, shutil.which("google-chrome"), shutil.which("chromium"))
               if c and Path(c).exists()), None)
needs_chrome = pytest.mark.skipif(not (NODE_22 and CHROME), reason="needs Node 22 or newer and Chrome")
# A face that loads without a network or a font file: a system font under another name.
LOCAL_FACE = "src: local('Helvetica'), local('Arial'), local('DejaVu Sans'), local('Liberation Sans')"


def shoot(tmp_path, body, **job):
    page = tmp_path / "page.html"
    page.write_text(f"<!doctype html><html><head><meta charset='utf-8'></head><body>{body}</body></html>")
    out = tmp_path / "out.png"
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps([{"url": page.as_uri(), "out": str(out), "width": 200, "height": 100, "scale": 1, "wait": 0, **job}]))
    build_assets.run([NODE, str(build_assets.SHOOT), str(jobs)], timeout=60, env={**os.environ, "CHROME": CHROME})
    return out


@needs_chrome
def test_shoot_renders_a_page_whose_fonts_loaded(tmp_path):
    body = f"<style>@font-face {{ font-family: Inter; font-weight: 400; {LOCAL_FACE} }} p {{ font-family: Inter }}</style><p>Hello</p>"
    assert Image.open(shoot(tmp_path, body, fonts=[["Inter", 400]])).size == (200, 100)


@needs_chrome
@pytest.mark.parametrize(
    ("body", "fonts", "problem"),
    [
        ("<link rel='stylesheet' href='missing.css'><p>Hello</p>", [], r"stylesheet file:.*missing\.css did not load"),
        ("<img src='missing.png'>", [], r"image file:.*missing\.png did not load"),
        ("<p>Hello</p>", [["Inter", 400]], "font Inter 400 is not registered"),
        (f"<style>@font-face {{ font-family: Inter; font-weight: 400; {LOCAL_FACE} }}</style>", [["Inter", 700]], "font Inter 700 is not registered"),
        ("<style>@font-face { font-family: Inter; src: url(missing.woff2) } p { font-family: Inter }</style><p>Hello</p>", [],
         r"font file:.*missing\.woff2 did not load.*; font Inter normal did not load"),
    ],
    ids=["stylesheet", "image", "unregistered-family", "unregistered-weight", "failed-font"],
)
def test_shoot_stops_before_capturing_a_page_that_did_not_load(tmp_path, capfd, body, fonts, problem):
    with pytest.raises(build_assets.RenderError, match="exited with status 1"):
        shoot(tmp_path, body, fonts=fonts)
    assert not (tmp_path / "out.png").exists()
    err = capfd.readouterr().err
    assert "out.png: " in err
    assert re.search(problem, err), err


@needs_chrome
def test_shoot_gives_up_on_a_page_that_never_finishes_loading(tmp_path, capfd):
    with socket.create_server(("127.0.0.1", 0)) as server:  # accepts connections and never answers
        port = server.getsockname()[1]
        started = time.monotonic()
        with pytest.raises(build_assets.RenderError, match="exited with status 1"):
            shoot(tmp_path, f"<link rel='stylesheet' href='http://127.0.0.1:{port}/stalled.css'>", timeout=1500)
        assert time.monotonic() - started < 30
    assert not (tmp_path / "out.png").exists()
    assert "timed out after 1.5 s" in capfd.readouterr().err
