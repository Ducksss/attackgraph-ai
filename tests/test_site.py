"""The static hosted build: every scenario pre-rendered, no live AI, no secrets."""

import json
import re
import sys

from helpers import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402


def pages(out):
    return (out / "index.html").read_text(), (out / "demo" / "index.html").read_text()


def test_build_renders_the_landing_page_and_every_scenario(tmp_path):
    build_site.build(tmp_path / "site")
    landing, demo = pages(tmp_path / "site")
    assert "Ship permission changes without shipping admin access." in landing and 'href="/demo"' in landing
    assert "Permission reviews miss paths," in landing and "Recorded Nova Pro reply" in landing
    assert 'id="sc-' not in landing
    for key in ("passrole", "repair", "unknown", "invalid", "upload"):
        assert f'id="sc-{key}"' in demo
    assert "1 new path to a protected role" in demo and "Analysis incomplete" in demo
    assert "Recorded AI explanation" in demo and "ebf66418-50b4-4e8f-8ee2-8675d76a6fb0" in demo
    assert "<dt>Prompt</dt><dd>explain-v2</dd>" in demo  # the prompt that produced the recording, not the current one
    assert "This hosted page never calls Bedrock" in demo
    # The recorded reply names each entity, on the overview quote and in the demo, instead of printing raw IDs.
    for html in (landing, demo):
        assert '<span class="ag-ent" title="p-ci-deployer">' in html and "allows p-ci-deployer" not in html
    assert "The route after the fix" in demo
    # The flagship opens with the pull request: the failing check, and the passing one after the fix commit.
    flagship = demo.split('id="sc-passrole"', 1)[1].split('id="sc-repair"', 1)[0]
    assert flagship.index("The pull request") < flagship.index("Inside the check") < flagship.index("1 new path to a protected role")
    assert "Check failed" in flagship and "Check passed" in flagship and "Apply the suggested fix" in flagship
    assert "The pull request" not in demo.split('id="sc-repair"', 1)[1]
    assert "Can it block a pull request?" in landing and "CI blocking" not in landing
    for html in (landing, demo):
        assert "\u2014" not in html and "<script>alert" not in html
    assert sorted(p.name for p in (tmp_path / "site" / "reports").glob("*.md")) == ["passrole.md", "repair.md", "unknown.md"]
    headers = json.loads((tmp_path / "site" / "vercel.json").read_text())["headers"][0]["headers"]
    assert {"key": "X-Frame-Options", "value": "DENY"} in headers


def test_a_stale_recording_is_never_shown(tmp_path):
    record = json.loads(build_site.RECORDED.read_text())
    record["analysis_id"] = "0000000000000000"
    stale = tmp_path / "recorded.json"
    stale.write_text(json.dumps(record))
    build_site.build(tmp_path / "site", stale)
    landing, demo = pages(tmp_path / "site")
    assert "Recorded AI explanation" not in demo and "Recorded Nova Pro reply" not in landing
    assert record["request_id"] not in demo and record["request_id"] not in landing
    assert "Deterministic summary, not AI-generated" in demo


def test_recorded_reply_matches_the_reviewed_evidence():
    record = json.loads(build_site.RECORDED.read_text())
    evidence = (ROOT / "docs" / "evidence" / "ac9-bedrock-review-2026-09-30.md").read_text()
    run5 = evidence.split("## Run 5: generated", 1)[1].split("## Run 6", 1)[0]
    assert record["request_id"] in run5 and record["summary"] in run5 and record["limitations"] in run5
    assert "[x] no unsupported claims" in run5


def test_committed_site_is_current(tmp_path):
    build_site.build(tmp_path / "site")
    undate = lambda text: re.sub(r"generated \d{4}-\d{2}-\d{2} \(UTC\)", "generated (date) (UTC)", text)
    for fresh, committed in zip(pages(tmp_path / "site"), pages(ROOT / "site")):
        assert "generated (date) (UTC)" in undate(fresh)
        assert undate(fresh) == undate(committed), "run: python scripts/build_site.py"
