"""Escaping and presentation helpers shared by the UI and the report.

Labels and model output are untrusted text. Markdown output escapes every
ASCII punctuation character (CommonMark allows backslash escapes for all of
them), which also disables Streamlit's colour directives, emoji shortcodes and
math. Identifiers are pattern-restricted, so they are safe inside code spans.
"""

from __future__ import annotations

import re

from .analysis import RULE_LAMBDA, RULE_S3, Candidate
from .snapshot import KIND_TITLES
from .story import Story

_PUNCTUATION = re.compile(r"([!-/:-@\[-`{-~])")


def md_escape(text: str) -> str:
    return _PUNCTUATION.sub(r"\\\1", text).replace("\n", " ")


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


def step_text(candidate: Candidate) -> str:
    if candidate.rule == RULE_S3:
        return f"{candidate.subject} reads {candidate.target} (Rule A)"
    return f"{candidate.subject} runs code as {candidate.target} through Lambda workload {candidate.via} (Rule B)"


def witness_dot(story: Story) -> str:
    """Graphviz source for the route, with the same stops as the path card.

    Rule B is one relationship in the engine: all of its conditions hold
    together. Like the path card, the graph draws its Lambda function as a
    stop, so the route reads as the pipeline it is.
    """
    changed = {c.fact_id for c in story.changes if c.fact_id}
    lines = [
        "digraph witness {",
        f'rankdir={"LR" if len(story.nodes) <= 4 else "TB"}; bgcolor="transparent"; pad=0.3; nodesep=0.5; ranksep=0.9;',
        'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=13, color="#e2e2e8", fillcolor="#ffffff", '
        'fontcolor="#111114", penwidth=1.2, margin="0.22,0.12"];',
        'edge [fontname="Helvetica", fontsize=11, color="#6366f1", fontcolor="#5f5f72", penwidth=1.5, arrowsize=0.8];',
    ]
    for node in story.nodes:
        tags = [KIND_TITLES[node.kind]] + (["protected " + node.protected.replace("_", " ")] if node.protected else [])
        label = "\\n".join(dot_string(part) for part in (truncate(node.label), " · ".join(tags), node.id))
        style = ', color="#f59e0b", fillcolor="#fffbeb", penwidth=2' if node.protected else ""
        lines.append(f'"{node.id}" [label="{label}"{style}];')
    hops = iter(zip(story.hops, story.nodes, story.nodes[1:]))
    for number, step in enumerate(story.steps, start=1):
        rule = "Rule B" if step.candidate.rule == RULE_LAMBDA else "Rule A"
        for part in range(2 if step.candidate.rule == RULE_LAMBDA else 1):
            hop, source, target = next(hops)
            parts = ([f"{number}. {rule}"] if part == 0 else []) + [hop.text]
            changed_here = sorted(set(hop.fact_ids) & changed)
            if changed_here:
                parts.append("CHANGED: " + ", ".join(changed_here))
            style = ', color="#d97706", fontcolor="#b45309", penwidth=2.2' if changed_here else ""
            if hop.state != "true":
                style += ', style="dashed"'
            label = "\\n".join(dot_string(p) for p in parts)
            lines.append(f'"{source.id}" -> "{target.id}" [label="{label}"{style}];')
    lines.append("}")
    return "\n".join(lines)
