"""Escaping and presentation helpers shared by the UI and the report.

Labels and model output are untrusted text. Markdown output escapes every
ASCII punctuation character (CommonMark allows backslash escapes for all of
them), which also disables Streamlit's colour directives, emoji shortcodes and
math. Identifiers are pattern-restricted, so they are safe inside code spans.
"""

from __future__ import annotations

import re

from .analysis import RULE_S3, Candidate, SnapshotAnalysis
from .snapshot import KIND_TITLES

_PUNCTUATION = re.compile(r"([!-/:-@\[-`{-~])")


def md_escape(text: str) -> str:
    return _PUNCTUATION.sub(r"\\\1", text).replace("\n", " ")


def md_segments(segments: tuple[tuple[str, str], ...]) -> str:
    return "".join(f"`{value}`" if kind == "id" else md_escape(value) for kind, value in segments)


def plain_segments(segments: tuple[tuple[str, str], ...]) -> str:
    return "".join(value for _, value in segments)


def fenced(text: str) -> str:
    """A fenced block that the text cannot close early."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def truncate(text: str, limit: int = 48) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def dot_string(text: str) -> str:
    # Backslash sequences (\N, \G, \l) have meaning in DOT labels, so escape them first.
    return text.replace("\\", "\\\\").replace('"', '\\"')


KIND_FILL = {
    "principal": "#0b2414",
    "role": "#0f1f24",
    "lambda": "#12240f",
    "s3_object": "#241f10",
}
RULE_SHORT = {RULE_S3: "Rule A: reads", "lambda_pass_role": "Rule B: runs code as"}


def step_text(candidate: Candidate) -> str:
    if candidate.rule == RULE_S3:
        return f"{candidate.subject} reads {candidate.target} (Rule A)"
    return f"{candidate.subject} runs code as {candidate.target} through Lambda workload {candidate.via} (Rule B)"


def witness_dot(analysis: SnapshotAnalysis, witness: tuple[Candidate, ...], changed_fact_ids: frozenset[str] = frozenset()) -> str:
    """Graphviz source for one witness; the text path shows the same edges."""
    snapshot = analysis.snapshot
    direction = "LR" if len(witness) <= 2 else "TB"
    lines = [
        "digraph witness {",
        f'rankdir={direction}; bgcolor="transparent"; pad=0.3; nodesep=0.5; ranksep=1.1;',
        'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=14, color="#2b3a2e", fontcolor="#f2f5f2", penwidth=1.2, margin="0.22,0.12"];',
        'edge [fontname="Helvetica", fontsize=12, color="#53db78", fontcolor="#a7aea8", arrowsize=0.9];',
    ]
    order = list(dict.fromkeys(n for c in witness for n in (c.subject, c.target)))
    for node_id in order:
        node = snapshot.nodes[node_id]
        tags = [KIND_TITLES[node.kind]]
        target = snapshot.protected_targets.get(node_id)
        if target:
            tags.append("PROTECTED: " + target.classification.replace("_", " "))
        label = "\\n".join([dot_string(node_id), dot_string(" · ".join(tags)), dot_string(truncate(node.label))])
        border = ', color="#ffc24b", penwidth=2.2' if target else ""
        lines.append(f'"{node_id}" [label="{label}", fillcolor="{KIND_FILL[node.kind]}"{border}];')
    for step, candidate in enumerate(witness, start=1):
        parts = [f"{step}. {RULE_SHORT[candidate.rule]}"]
        if candidate.via:
            parts.append(f"via {candidate.via}")
        changed = sorted(set(candidate.fact_ids) & changed_fact_ids)
        if changed:
            parts.append("CHANGED: " + ", ".join(changed))
        style = ', color="#ffc24b", fontcolor="#ffc24b", penwidth=2.4' if changed else ""
        if candidate.state != "true":
            style += ', style="dashed"'
        label = "\\n".join(dot_string(p) for p in parts)
        lines.append(f'"{candidate.subject}" -> "{candidate.target}" [label="{label}"{style}];')
    lines.append("}")
    return "\n".join(lines)
