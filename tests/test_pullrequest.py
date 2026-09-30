"""The demo pull request: the repository's real check, run as the workflow runs it."""

import pytest
from helpers import PASSROLE_FACT, ROOT

from attackgraph import page
from attackgraph.pullrequest import WATCHED, changed_lines, demo_pull_request, parse_annotation, set_states
from attackgraph.scenarios import run_scenario


@pytest.fixture(scope="module")
def pr():
    return demo_pull_request(run_scenario("passrole"))


def test_the_pull_request_changes_one_line_of_the_watched_snapshot(pr):
    base, head = pr.base.splitlines(), pr.head.splitlines()
    assert pr.base == (ROOT / WATCHED).read_text()
    assert len(base) == len(head) and [n for n, (a, b) in enumerate(zip(base, head), start=1) if a != b] == [27]
    assert PASSROLE_FACT in head[26] and '"state": "true"' in head[26] and '"state": "false"' in base[26]


def test_the_check_fails_on_the_changed_line_and_passes_after_the_fix(pr):
    assert pr.check.status == 1 and not pr.check.passed
    assert pr.check.result == "Result: 1 new high-risk finding in the proposal."
    [note] = pr.check.annotations
    assert (note.level, note.line, note.title) == ("error", 27, "New path to a protected role")
    assert note.message.startswith("CI deploy user (build pipeline) can now run code as Deployment admin role.")
    assert "Verified in this model" in note.message
    assert pr.fix.fact_id == PASSROLE_FACT and pr.fixed == pr.base  # the fix commit reverts the line
    assert pr.fixed_check.passed and pr.fixed_check.annotations == ()
    assert pr.fixed_check.result == "Result: No new modelled high-risk access."


def test_the_card_puts_the_check_note_under_the_changed_line(pr):
    opened = page.pull_request(pr)
    assert "Check failed" in opened and "exit status 1" in opened and "Permission check / AttackGraph AI" in opened
    assert "<mark>false</mark>" in opened and "<mark>true</mark>" in opened
    added, note, next_line = (
        opened.index('<span class="n">27</span><span class="s">+</span>'),
        opened.index('class="ag-annot error"'),
        opened.index('<span class="n">28</span>'),
    )
    assert added < note < next_line
    fixed = page.pull_request(pr, fixed=True)
    assert "Check passed" in fixed and "exit status 0" in fixed and "ag-annot" not in fixed
    assert "Fix commit: revoke f-ci-pass-deploy-admin, the verified fix." in fixed


def test_workflow_command_escapes_are_undone():
    note = parse_annotation("::error file=a%2Cb.json,line=3,title=A%3A B%25::one%0Atwo %25")
    assert (note.level, note.line, note.title, note.message) == ("error", 3, "A: B%", "one\ntwo %")
    assert parse_annotation("Result: 1 new high-risk finding in the proposal.") is None


def test_set_states_edits_only_the_line_that_holds_the_fact():
    text = (ROOT / WATCHED).read_text()
    edited = set_states(text, {PASSROLE_FACT: "unknown"})
    assert changed_lines(text, edited) == 1 and '"state": "unknown"' in edited.splitlines()[26]
