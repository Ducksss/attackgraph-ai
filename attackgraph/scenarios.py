"""Bundled scenarios shared by the Streamlit app and the static hosted build."""

from __future__ import annotations

from pathlib import Path

from .pipeline import PipelineResult, run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SCENARIOS = {
    "passrole": ("PassRole change", "demo/baseline.json", "demo/proposed.json"),
    "repair": ("Proposed vs repaired", "demo/proposed.json", "demo/repaired.json"),
    "unknown": ("Unknown fact", "demo/baseline.json", "examples/unknown-prerequisite.json"),
    "invalid": ("Invalid file", "demo/baseline.json", "examples/invalid-references.json"),
}
UPLOAD = "upload"
SCENARIO_LABELS = {**{key: value[0] for key, value in SCENARIOS.items()}, UPLOAD: "Upload your own"}


def run_scenario(key: str) -> PipelineResult:
    _, baseline, proposal = SCENARIOS[key]
    return run(
        (FIXTURES / baseline).read_bytes(), Path(baseline).name, (FIXTURES / proposal).read_bytes(), Path(proposal).name
    )
