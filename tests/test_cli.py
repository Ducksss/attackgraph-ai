"""The command-line check a CI job gates on: exit status, text, report and GitHub annotations."""

import subprocess
import sys

import pytest
from helpers import FIXTURES, PASSROLE_FACT, ROOT, proposed_doc, to_bytes

from attackgraph.cli import BLOCKED, NOT_ANALYSED, PASS, main, pointer_lines

BASELINE = FIXTURES / "demo" / "baseline.json"
PROPOSED = FIXTURES / "demo" / "proposed.json"
REPAIRED = FIXTURES / "demo" / "repaired.json"
UNKNOWN = FIXTURES / "examples" / "unknown-prerequisite.json"
INVALID = FIXTURES / "examples" / "invalid-references.json"
WATCHED = ROOT / "snapshots" / "app-prod.json"
PASSROLE_POINTER = f"/facts/{[f['id'] for f in proposed_doc()['facts']].index(PASSROLE_FACT)}"
ADDED = "Added · High · CI deploy user (build pipeline) can now run code as Deployment admin role"


def line_of(path, text: str) -> int:
    """First line of the file containing text: found without the JSON parser under test."""
    return next(n for n, line in enumerate(path.read_text().splitlines(), start=1) if text in line)


def check(capsys, *args) -> tuple[int, str]:
    status = main([str(a) for a in args])
    return status, capsys.readouterr().out


def test_a_new_path_blocks_and_names_the_changed_line(capsys):
    status, out = check(capsys, BASELINE, PROPOSED, "--github")
    line = line_of(PROPOSED, PASSROLE_FACT)
    assert status == BLOCKED == 1
    assert ADDED in out and "Route: p-ci-deployer → l-build-hook → r-deploy-admin" in out
    assert f"Changed: {PASSROLE_FACT}, false → true at {PASSROLE_POINTER} (line {line})" in out
    assert f"Fix: revoke {PASSROLE_FACT}. Verified in this model; normal access kept 2 of 2." in out
    assert "Result: 1 new high-risk finding in the proposal." in out
    assert f"::error file={PROPOSED.as_posix()},line={line},title=New path to a protected role::" in out


def test_closing_the_path_passes_with_a_notice_on_the_line(capsys):
    status, out = check(capsys, PROPOSED, REPAIRED, "--github")
    assert status == PASS == 0
    assert "Removed · High · CI deploy user (build pipeline) can no longer run code as Deployment admin role" in out
    assert "Result: No new modelled high-risk access." in out
    assert f"::notice file={REPAIRED.as_posix()},line={line_of(REPAIRED, PASSROLE_FACT)},title=Path closed::" in out
    assert "::error" not in out


def test_an_unknown_fact_is_never_a_pass(capsys):
    status, out = check(capsys, BASELINE, UNKNOWN, "--github")
    assert status == BLOCKED
    assert "Coverage: incomplete" in out and "Result: Analysis incomplete." in out
    assert "No new modelled high-risk access" not in out
    title = "Unresolved%2C so the result is incomplete"
    assert f"::error file={UNKNOWN.as_posix()},line={line_of(UNKNOWN, PASSROLE_FACT)},title={title}::" in out


def test_an_invalid_file_is_not_analysed(capsys):
    status, out = check(capsys, BASELINE, INVALID, "--github")
    line = line_of(INVALID, '"r-missing-role"')
    assert status == NOT_ANALYSED == 2
    assert f"Proposal is not a valid snapshot: {INVALID}" in out and "Added" not in out
    assert f'/facts/1/object: references unknown node "r-missing-role" (line {line})' in out
    assert f"::error file={INVALID.as_posix()},line={line},title=Invalid snapshot::/facts/1/object" in out


def test_unreadable_files_and_usage_errors_are_not_analysed(tmp_path, capsys):
    assert main([str(BASELINE), str(tmp_path / "missing.json")]) == NOT_ANALYSED
    assert "cannot read" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        main([str(BASELINE), str(PROPOSED), str(REPAIRED)])
    assert exc.value.code == NOT_ANALYSED


def test_a_snapshot_without_a_base_version_counts_every_path_as_new(capsys):
    status, out = check(capsys, PROPOSED)
    assert status == BLOCKED
    assert "Baseline: none, so every path in the proposal counts as new" in out and ADDED in out


def test_the_watched_snapshot_passes_until_a_change_opens_the_path(tmp_path, capsys):
    """The demo pull request: one line of snapshots/app-prod.json sets the PassRole grant to true."""
    status, _ = check(capsys, WATCHED)
    assert status == PASS
    lines = WATCHED.read_text().splitlines(keepends=True)
    n = line_of(WATCHED, PASSROLE_FACT)
    lines[n - 1] = lines[n - 1].replace('"state": "false"', '"state": "true"')
    changed = tmp_path / "app-prod.json"
    changed.write_text("".join(lines))
    status, out = check(capsys, WATCHED, changed, "--github")
    assert status == BLOCKED and ADDED in out
    assert f"::error file={changed.as_posix()},line={n},title=New path to a protected role::" in out


def test_the_report_is_written_for_analysed_and_invalid_inputs(tmp_path, capsys):
    report = tmp_path / "report.md"
    main([str(BASELINE), str(PROPOSED), "--report", str(report)])
    text = report.read_text()
    assert text.startswith("# AttackGraph AI comparison report") and "1 new high-risk finding in the proposal." in text
    main([str(BASELINE), str(INVALID), "--report", str(report)])
    text = report.read_text()
    assert "**Not analysed." in text and r"\/facts\/1\/object" in text


def commands(out: str) -> list[str]:
    """Lines GitHub would run as workflow commands (it ignores leading spaces)."""
    return [line for line in out.splitlines() if line.lstrip().startswith("::")]


def test_untrusted_labels_cannot_start_or_break_a_workflow_command(tmp_path, capsys):
    doc = proposed_doc()
    entry = next(n for n in doc["nodes"] if n["id"] == "p-ci-deployer")
    entry["label"] = "::warning::injected, 100% %0A"
    proposal = tmp_path / "proposed.json"
    proposal.write_bytes(to_bytes(doc))
    status, out = check(capsys, BASELINE, proposal, "--github")
    assert status == BLOCKED and commands(out)
    assert all(line.startswith(("::error ", "::notice ")) for line in commands(out))
    assert "::warning::injected, 100%25 %250A can now run code as" in out


def test_line_breaks_in_keys_and_paths_cannot_start_a_workflow_command(tmp_path, capsys):
    # A duplicated key is reported at a pointer that contains the key, line break included.
    bad = tmp_path / "bad\n::warning::path.json"
    bad.write_bytes(b'{"k\\n::warning::key": 1, "k\\n::warning::key": 2}')
    status, out = check(capsys, BASELINE, bad, "--github")
    assert status == NOT_ANALYSED and "duplicate key" in out
    assert commands(out) and all(line.startswith("::error ") for line in commands(out))


def test_pointer_lines_follow_the_json_layout():
    data = b'{\n  "a": [\n    {"b": 1},\n    2\n  ],\n  "c/d~e": {"f": "x"}\n}\n'
    assert pointer_lines(data) == {"": 1, "/a": 2, "/a/0": 3, "/a/0/b": 3, "/a/1": 4, "/c~1d~0e": 6, "/c~1d~0e/f": 6}
    assert pointer_lines(b'{"a": ') == {} and pointer_lines(b"\xff") == {}


def test_python_dash_m_returns_the_check_status():
    run = subprocess.run(
        [sys.executable, "-m", "attackgraph", str(BASELINE), str(PROPOSED)], cwd=ROOT, capture_output=True, text=True
    )
    assert run.returncode == BLOCKED and "Result: 1 new high-risk finding in the proposal." in run.stdout
