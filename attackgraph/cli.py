"""Command-line check for pull requests and CI.

    python -m attackgraph BASELINE PROPOSAL [--report FILE] [--github]

Exit status 0 means no new modelled high-risk access, with complete coverage.
1 means the proposal opens a new path to a protected target, or the result is
incomplete: an unknown is never a pass. 2 means nothing was analysed, because
a file could not be read or is not a valid snapshot.

With PROPOSAL alone, the snapshot is compared with an empty baseline, so every
path in it counts as new; that is the case of a snapshot a pull request adds.
The check is static and offline. It never calls Amazon Bedrock or AWS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from bisect import bisect_right
from json.decoder import scanstring
from pathlib import Path

from . import ENGINE_VERSION, MODEL_VERSION
from .compare import Comparison, FindingDelta
from .pipeline import PipelineResult, run_loaded
from .render import md_escape
from .report import MAX_LISTED_ISSUES, STATUS_WORDS, build_report, verdict_text
from .simulate import best_fix_for
from .snapshot import POLICY_CONTROLS, LoadResult, Snapshot, load_snapshot, pointer
from .story import Condition, build_story, summary

PASS, BLOCKED, NOT_ANALYSED = 0, 1, 2

_SPACE = re.compile(r"[ \t\n\r]*")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _no_baseline() -> LoadResult:
    """Stands in for a snapshot that has no base version: every path in the proposal counts as new."""
    empty = Snapshot(
        snapshot_id="none",
        name="No base version",
        source_name="none",
        sha256=hashlib.sha256(b"").hexdigest(),
        size_bytes=0,
        policy_controls=dict.fromkeys(POLICY_CONTROLS, "resolved"),
        unmodelled_mechanisms=(),
        nodes={},
        facts={},
        entry_principals=(),
        protected_targets={},
        expected_access=(),
    )
    return LoadResult(empty, (), empty.source_name, empty.sha256, 0)


def pointer_lines(data: bytes) -> dict[str, int]:
    """The 1-based line on which the value at each JSON pointer starts; empty unless the file is JSON."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {}
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    decode = json.JSONDecoder().raw_decode
    lines: dict[str, int] = {}

    def skip(i: int) -> int:
        return _SPACE.match(text, i).end()

    def value(i: int, path: tuple) -> int:
        """Record where the value at i starts; return the index just past it."""
        i = skip(i)
        lines[pointer(*path)] = bisect_right(starts, i)
        if text[i] == "{":
            i = skip(i + 1)
            while text[i] != "}":
                key, i = scanstring(text, i + 1)
                i = skip(value(skip(i) + 1, (*path, key)))
                if text[i] == ",":
                    i = skip(i + 1)
            return i + 1
        if text[i] == "[":
            i, index = skip(i + 1), 0
            while text[i] != "]":
                i = skip(value(i, (*path, index)))
                index += 1
                if text[i] == ",":
                    i = skip(i + 1)
            return i + 1
        return decode(text, i)[1]

    try:
        value(0, ())
    except (ValueError, IndexError, RecursionError):
        return {}
    return lines


def _line(lines: dict[str, int], ptr: str | None) -> int | None:
    """The line of ptr, or of its nearest ancestor in the file: a missing field is reported on its object."""
    if ptr is None:
        return None
    while ptr and ptr not in lines:
        ptr = ptr.rpartition("/")[0]
    return lines.get(ptr)


def _at(lines: dict[str, int], ptr: str | None) -> str:
    line = _line(lines, ptr)
    return f" (line {line})" if line else ""


def _proposal_pointer(comparison: Comparison, delta: FindingDelta, condition: Condition) -> str | None:
    """Where a changed condition is declared in the proposal, if it is declared there."""
    if condition.fact_id:
        fact = comparison.proposal.snapshot.facts.get(condition.fact_id)
        return fact.pointer if fact else None
    # A derived check, such as the policy controls: its pointers name the snapshot the story was built from.
    return condition.pointers[0] if condition.pointers and delta.proposal is not None else None


def _text(result: PipelineResult, baseline: Path | None, proposal: Path, base_lines: dict, prop_lines: dict) -> list[str]:
    # Every line starts with fixed text, because GitHub reads a line that starts with "::" as a workflow
    # command. File paths and issue pointers can hold line breaks, so main() also keeps each on one line.
    out = [
        f"AttackGraph AI {ENGINE_VERSION} ({MODEL_VERSION}). Static check of synthetic snapshots; no AWS calls.",
        f"Baseline: {baseline or 'none, so every path in the proposal counts as new'}",
        f"Proposal: {proposal}",
        "",
    ]
    if not result.ok:
        for role, path, load, lines in (
            ("Baseline", baseline, result.baseline, base_lines),
            ("Proposal", proposal, result.proposal, prop_lines),
        ):
            if load.issues:
                out.append(f"{role} is not a valid snapshot: {path}")
                out += [f"  {issue}{_at(lines, issue.pointer)}" for issue in load.issues]
        return out + ["", "Result: not analysed. Both files must validate before either is compared."]

    comparison = result.comparison
    for delta in comparison.deltas:
        story = build_story(comparison, delta)
        status = STATUS_WORDS[delta.status] + (" (provisional)" if delta.provisional else "")
        out.append(f"{status} · {delta.severity} · {story.headline}" + ("; evidence changed" if delta.evidence_changed else ""))
        out.append("  Route: " + " → ".join(node.id for node in story.nodes))
        for change in story.changes:
            ptr = _proposal_pointer(comparison, delta, change)
            where = f" at {ptr}{_at(prop_lines, ptr)}" if ptr else ""
            out.append(f"  Changed: {change.fact_id or change.text}, {change.change}{where}")
        if delta.status == "added":
            fix = best_fix_for(result.fixes, delta.id)
            if fix is None:
                out.append("  Fix: no single revocation of a newly enabled grant closes this path.")
            else:
                kept = sum(1 for r in fix.expected_after if r.result == "pass")
                out.append(f"  Fix: revoke {fix.fact_id}. Verified in this model; normal access kept {kept} of {len(fix.expected_after)}.")
        out.append("")
    if not comparison.deltas:
        out += ["No modelled high-risk access in either snapshot.", ""]

    issues = [("Baseline", issue, base_lines) for issue in comparison.baseline.coverage.issues]
    issues += [("Proposal", issue, prop_lines) for issue in comparison.proposal.coverage.issues]
    out.append(f"Coverage: {'complete' if comparison.complete else 'incomplete'}")
    for role, issue, lines in issues[:MAX_LISTED_ISSUES]:
        where = f" at {', '.join(issue.pointers)}{_at(lines, issue.pointers[0])}" if issue.pointers else ""
        out.append(f"  {role}: {issue.message}{where}")
    if len(issues) > MAX_LISTED_ISSUES:
        out.append(f"  {len(issues) - MAX_LISTED_ISSUES} more in the report.")
    out.append(f"Result: {verdict_text(comparison)}")
    return out


def _escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _command(level: str, title: str, message: str, file: str | None = None, line: int | None = None) -> str:
    """One GitHub Actions workflow command. Every value is escaped, so no text can end it early or start another."""

    def prop(value: str) -> str:
        return _escape(value).replace(":", "%3A").replace(",", "%2C")

    props = ([f"file={prop(file)}"] + ([f"line={line}"] if line else [])) if file else []
    props.append(f"title={prop(title)}")
    return f"::{level} {','.join(props)}::{_escape(message)}"


def annotations(result: PipelineResult, proposal: str, lines: dict[str, int]) -> list[str]:
    """GitHub annotations on the proposal lines behind the result.

    A new path is marked on each changed line on its route (or on the target's
    declaration when no fact changed), a closed path gets a notice, and an
    incomplete result marks each unresolved item. Baseline problems carry no
    line: the baseline is usually a copy from the base branch.
    """
    if not result.ok:
        out = [_command("error", "Invalid snapshot", str(i), proposal, _line(lines, i.pointer)) for i in result.proposal.issues]
        return out + [_command("error", "Invalid baseline snapshot", str(i)) for i in result.baseline.issues]

    comparison = result.comparison
    out = []
    for delta in comparison.deltas:
        if delta.status not in ("added", "removed"):
            continue
        story = build_story(comparison, delta)
        message = " ".join(summary(story, best_fix_for(result.fixes, delta.id)))
        where = [p for p in (_proposal_pointer(comparison, delta, c) for c in story.changes) if p]
        if delta.status == "added":
            kind = "role" if delta.impact == "privileged_role_use" else "object"
            level, title = "error", f"New path to a protected {kind}"
            where = where or [comparison.proposal.snapshot.protected_targets[delta.target].pointer]
        else:
            level, title = "notice", "Path closed"
        out += [_command(level, title, message, proposal, _line(lines, ptr)) for ptr in dict.fromkeys(where)]
    if not comparison.complete:
        for issue in comparison.proposal.coverage.issues:
            ptr = issue.pointers[0] if issue.pointers else None
            out.append(_command("error", "Unresolved, so the result is incomplete", issue.message, proposal, _line(lines, ptr)))
        out += [_command("error", "Unresolved in the baseline", i.message) for i in comparison.baseline.coverage.issues]
    return out


def _invalid_report(result: PipelineResult) -> str:
    lines = [
        "# AttackGraph AI comparison report",
        "",
        "> **Synthetic configuration JSON.** Static analysis of declared facts. Nothing was deployed or executed.",
        "",
        "## Result",
        "",
        "**Not analysed. Both files must validate before either is compared.**",
        "",
        "| File | JSON pointer | Problem |",
        "|---|---|---|",
    ]
    for role, load in (("Baseline", result.baseline), ("Proposal", result.proposal)):
        lines += [
            f"| {role}: {md_escape(load.source_name)} | {md_escape(issue.pointer or '(file)')} | {md_escape(issue.message)} |"
            for issue in load.issues
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m attackgraph",
        description="Compare two synthetic snapshots. Fails when the proposal opens a new path to a protected "
        "target or leaves the result incomplete. Static and offline.",
        epilog="Exit status: 0 pass, 1 new path or incomplete result, 2 not analysed.",
    )
    parser.add_argument("baseline", nargs="?", type=Path, help="current snapshot; omit it for a snapshot with no base version")
    parser.add_argument("proposal", type=Path, help="proposed snapshot")
    parser.add_argument("--report", type=Path, metavar="FILE", help="also write the Markdown report to FILE")
    parser.add_argument("--github", action="store_true", help="also print GitHub Actions annotations on the proposal's lines")
    args = parser.parse_args(argv)

    try:
        base_data = args.baseline.read_bytes() if args.baseline else None
        prop_data = args.proposal.read_bytes()
    except OSError as exc:
        print(_CONTROL.sub("?", f"error: cannot read {exc.filename}: {exc.strerror or exc}"), file=sys.stderr)
        return NOT_ANALYSED
    baseline = _no_baseline() if base_data is None else load_snapshot(base_data, args.baseline.name)
    result = run_loaded(baseline, load_snapshot(prop_data, args.proposal.name))
    base_lines, prop_lines = pointer_lines(base_data or b""), pointer_lines(prop_data)

    for line in _text(result, args.baseline, args.proposal, base_lines, prop_lines):
        print(_CONTROL.sub("?", line))
    if args.github:
        for command in annotations(result, args.proposal.as_posix(), prop_lines):
            print(command)
    if args.report:
        report = build_report(result.comparison, result.fixes) if result.ok else _invalid_report(result)
        args.report.write_text(report, encoding="utf-8")
    if not result.ok:
        return NOT_ANALYSED
    return PASS if result.comparison.verdict == "no_new_high_risk" else BLOCKED
