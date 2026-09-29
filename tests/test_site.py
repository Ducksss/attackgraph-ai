"""The static hosted build: every scenario pre-rendered, no live AI, no secrets."""

import json
import sys

from helpers import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402


def test_build_renders_every_scenario_and_the_recorded_reply(tmp_path):
    index = build_site.build(tmp_path / "site")
    html = index.read_text()
    for key in ("passrole", "repair", "unknown", "invalid", "upload"):
        assert f'id="sc-{key}"' in html
    assert "See what a permission change unlocks" in html
    assert "1 new path to a protected role" in html and "Analysis incomplete" in html
    assert "Recorded AI explanation" in html and "410472bd-679f-43a1-a1a1-783459e321b7" in html
    assert "This hosted page never calls Bedrock" in html
    assert "—" not in html and "<script>alert" not in html
    assert sorted(p.name for p in (tmp_path / "site" / "reports").glob("*.md")) == ["passrole.md", "repair.md", "unknown.md"]
    headers = json.loads((tmp_path / "site" / "vercel.json").read_text())["headers"][0]["headers"]
    assert {"key": "X-Frame-Options", "value": "DENY"} in headers


def test_a_stale_recording_is_never_shown(tmp_path):
    record = json.loads(build_site.RECORDED.read_text())
    record["analysis_id"] = "0000000000000000"
    stale = tmp_path / "recorded.json"
    stale.write_text(json.dumps(record))
    html = build_site.build(tmp_path / "site", stale).read_text()
    assert "Recorded AI explanation" not in html and record["request_id"] not in html
    assert "Deterministic summary, not AI-generated" in html


def test_recorded_reply_matches_the_reviewed_evidence():
    record = json.loads(build_site.RECORDED.read_text())
    evidence = (ROOT / "docs" / "evidence" / "ac9-bedrock-review-2026-09-29.md").read_text()
    run8 = evidence.split("## Run 8: generated", 1)[1].split("## Run 9", 1)[0]
    assert record["request_id"] in run8 and record["summary"] in run8 and record["limitations"] in run8
    assert "[x] no unsupported claims" in run8


def test_committed_site_is_current(tmp_path):
    fresh = build_site.build(tmp_path / "site").read_text()
    committed = (ROOT / "site" / "index.html").read_text()
    strip = lambda text: "\n".join(line for line in text.splitlines() if "Static build of the bundled scenarios" not in line)
    assert strip(fresh) == strip(committed), "run: python scripts/build_site.py"
