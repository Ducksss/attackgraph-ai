"""Load, validate and compare a snapshot pair in one call."""

from __future__ import annotations

from dataclasses import dataclass

from .compare import Comparison, compare_snapshots
from .simulate import MAX_FIX_CANDIDATES, FixCandidate, eligible_grants, fix_candidates
from .snapshot import LoadResult, load_snapshot


@dataclass(frozen=True, eq=False)
class PipelineResult:
    baseline: LoadResult
    proposal: LoadResult
    comparison: Comparison | None
    fixes: tuple[FixCandidate, ...]
    untested_fixes: int = 0

    @property
    def ok(self) -> bool:
        return self.comparison is not None


def run(baseline: bytes, baseline_name: str, proposal: bytes, proposal_name: str) -> PipelineResult:
    """Neither file is analysed unless both validate."""
    return run_loaded(load_snapshot(baseline, baseline_name), load_snapshot(proposal, proposal_name))


def run_loaded(b: LoadResult, p: LoadResult) -> PipelineResult:
    if not (b.ok and p.ok):
        return PipelineResult(b, p, None, ())
    comparison = compare_snapshots(b.snapshot, p.snapshot)
    untested = max(0, len(eligible_grants(comparison)) - MAX_FIX_CANDIDATES)
    return PipelineResult(b, p, comparison, fix_candidates(comparison), untested)
