"""The demo pull request: the repository's real pull-request check, run as the workflow runs it.

The pull request makes the flagship change to the watched snapshot,
snapshots/app-prod.json: one line, the PassRole grant from false to true. The
check is the actual `python -m attackgraph --github` command from
.github/workflows/permission-check.yml, run in a subprocess on copies of the
base-branch and pull-request versions, so its log, exit status and line
annotations are real output, not a mock-up. A second commit applies the
engine's verified fix to the same line, and the check runs again.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .cli import pointer_lines
from .pipeline import PipelineResult
from .simulate import FixCandidate, best_fix_for

ROOT = Path(__file__).resolve().parents[1]
WATCHED = "snapshots/app-prod.json"
BASE_COPY = f"base-branch/{WATCHED}"  # where the workflow puts the base branch's version
COMMAND = ("python", "-m", "attackgraph", "--github", "--", BASE_COPY, WATCHED)
WORKFLOW = ROOT / ".github" / "workflows" / "permission-check.yml"

_COMMAND_LINE = re.compile(r"^::(error|warning|notice)(?: (.*?))?::(.*)$")
_STATE = re.compile(r'("state"\s*:\s*)"(true|false|unknown)"')


@dataclass(frozen=True)
class Annotation:
    level: str  # error | warning | notice
    line: int | None
    title: str
    message: str


@dataclass(frozen=True)
class CheckRun:
    status: int  # the command's exit status: 0 pass, 1 new path or incomplete, 2 not analysed
    log: tuple[str, ...]
    annotations: tuple[Annotation, ...]

    @property
    def passed(self) -> bool:
        return self.status == 0

    @property
    def result(self) -> str:
        """The log's closing 'Result: ...' line."""
        return next((line for line in reversed(self.log) if line.startswith("Result:")), "")


@dataclass(frozen=True)
class PullRequest:
    title: str
    check_name: str
    base: str  # the watched snapshot on the base branch
    head: str  # the same file with the pull request's change
    check: CheckRun
    fix: FixCandidate | None  # the engine's verified fix for the new path
    fixed: str | None  # the file after the fix commit
    fixed_check: CheckRun | None


def _unescape(value: str, property_value: bool = False) -> str:
    """Undo GitHub's workflow-command escaping; %25 last, since it escapes the escapes."""
    pairs = [("%0D", "\r"), ("%0A", "\n")] + ([("%3A", ":"), ("%2C", ",")] if property_value else []) + [("%25", "%")]
    for escaped, plain in pairs:
        value = value.replace(escaped, plain)
    return value


def parse_annotation(line: str) -> Annotation | None:
    """One `::error file=...,line=...,title=...::message` workflow command, or None for a log line."""
    match = _COMMAND_LINE.match(line)
    if not match:
        return None
    level, props, message = match.groups()
    fields = dict(part.split("=", 1) for part in (props or "").split(",") if "=" in part)
    number = fields.get("line", "")
    return Annotation(
        level,
        int(number) if number.isdigit() else None,
        _unescape(fields.get("title", ""), property_value=True),
        _unescape(message),
    )


def run_check(base: str, head: str) -> CheckRun:
    """Run the check the workflow runs, on a workspace laid out as the workflow lays it out."""
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        for relative, text in ((BASE_COPY, base), (WATCHED, head)):
            (workspace / relative).parent.mkdir(parents=True, exist_ok=True)
            (workspace / relative).write_text(text, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))}
        run = subprocess.run(
            [sys.executable, *COMMAND[1:]], cwd=workspace, env=env, capture_output=True, text=True, timeout=60
        )
    log, annotations = [], []
    for line in run.stdout.splitlines():
        annotation = parse_annotation(line)
        if annotation is None:
            log.append(line)
        else:
            annotations.append(annotation)
    return CheckRun(run.returncode, tuple(log), tuple(annotations))


def set_states(text: str, states: dict[str, str]) -> str:
    """The snapshot with each named fact's state changed, editing only the line that holds it, as a person would."""
    doc = json.loads(text)
    starts = pointer_lines(text.encode("utf-8"))
    lines = text.splitlines(keepends=True)
    for fact_id, state in states.items():
        index = next(i for i, fact in enumerate(doc["facts"]) if fact["id"] == fact_id)
        number = starts[f"/facts/{index}/state"]
        edited, count = _STATE.subn(rf'\g<1>"{state}"', lines[number - 1], count=1)
        if count != 1:
            raise ValueError(f"line {number} does not hold the state of {fact_id}")
        lines[number - 1] = edited
    return "".join(lines)


def changed_lines(before: str, after: str) -> int:
    matcher = difflib.SequenceMatcher(None, before.splitlines(), after.splitlines(), autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal")


def check_name() -> str:
    """'Workflow / job', as GitHub labels the check, read from the workflow file."""
    try:
        text = WORKFLOW.read_text(encoding="utf-8")
    except OSError:
        return "AttackGraph AI"
    workflow = re.search(r"^name:\s*(.+?)\s*$", text, re.M)
    job = re.search(r"^\s+name:\s*(.+?)\s*$", text.split("\njobs:", 1)[-1], re.M)
    return " / ".join(m.group(1).strip("\"'") for m in (workflow, job) if m) or "AttackGraph AI"


def demo_pull_request(flagship: PipelineResult) -> PullRequest | None:
    """The flagship change as a pull request on the watched snapshot, checked before and after the fix."""
    comparison = flagship.comparison
    added = next((d for d in comparison.deltas if d.status == "added"), None) if comparison else None
    watched = ROOT / WATCHED
    if added is None or not watched.exists():
        return None
    base = watched.read_text(encoding="utf-8")
    current = {fact["id"]: fact["state"] for fact in json.loads(base)["facts"]}
    changes = {c.fact_id: c.proposal.state for c in comparison.fact_changes if c.kind == "state_changed"}
    if any(current.get(fact_id) != comparison.baseline.snapshot.facts[fact_id].state for fact_id in changes):
        return None  # the watched snapshot no longer matches the flagship baseline, so the change would not apply
    head = set_states(base, changes)
    fix = best_fix_for(flagship.fixes, added.id)
    fixed = set_states(head, {fix.fact_id: "false"}) if fix else None
    name = comparison.proposal.snapshot.name
    return PullRequest(
        title=name.split(": ", 1)[1] if name.startswith("Proposed: ") else name,
        check_name=check_name(),
        base=base,
        head=head,
        check=run_check(base, head),
        fix=fix,
        fixed=fixed,
        fixed_check=run_check(base, fixed) if fixed is not None else None,
    )
