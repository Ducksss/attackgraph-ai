"""The live engine against the frozen oracle in tests/reference: identical results on every case.

The cases are every pairing of the bundled fixtures, examples and snapshots,
the two adversarial worst cases, and 200 seeded random pairs; differential.py
says what is compared and what the random pairs vary. The oracle needs
several seconds per worst case, so those run in worker processes that start
with this module, while the other cases are checked here.
"""

import dataclasses
import hashlib
import inspect
import json
import subprocess
import sys
from collections import Counter
from functools import cached_property

import differential
import pytest
from helpers import ROOT
from reference import analysis_v1, compare_v1, pipeline_v1, simulate_v1

from attackgraph import analysis, compare, pipeline, simulate

RANDOM_PAIRS = 200
REFERENCE = ROOT / "tests" / "reference"
# Digests of the oracle as frozen. A change here needs a reason other than making a test pass.
ORACLE_SHA256 = {
    "__init__.py": "03d5233ad3050ff9d2054031aff70d7f449d8afdaaaad67f47d4c4dd82bf3398",
    "analysis_v1.py": "b4747b8920d0c0faab53739c20760314a53d24a2b4cd0ce348f7efef8ef2bc8d",
    "compare_v1.py": "496e437c027537d8b8fd3e519b89267cef4d9c03d6bbfbb5b6453de2c6e47e4f",
    "pipeline_v1.py": "e90f61708930e779a0e118e68f61a562e10a03ca26237f9591219b8ebf229b67",
    "report_v1.py": "6333055e1565de144c9124d109b96cf449a98d376c697f4d8d6ad2a4b2e39308",
    "simulate_v1.py": "17f921ec2219f458dc81d8b7183fcce208889c7629289f7ef35632a60e43c98f",
}


class _Workers:
    """One worker process per worst case, each read once."""

    def __init__(self) -> None:
        self.processes = {
            case: subprocess.Popen(
                [sys.executable, str(ROOT / "tests" / "differential.py"), case],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for case in differential.WORST_CASES
        }
        self.results: dict[str, tuple[int, str, str]] = {}

    def result(self, case: str) -> tuple[int, str, str]:
        if case not in self.results:
            out, err = self.processes[case].communicate(timeout=900)
            self.results[case] = (self.processes[case].returncode, out, err)
        return self.results[case]

    def stop(self) -> None:
        for case, process in self.processes.items():
            if case not in self.results:
                process.kill()
                process.communicate()


@pytest.fixture(scope="module", autouse=True)
def worst_case_workers():
    """Start the oracle on the worst cases first, so it runs while the other cases are checked."""
    workers = _Workers()
    yield workers
    workers.stop()


def test_the_oracle_is_frozen():
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(REFERENCE.glob("*.py"))}
    assert digests == ORACLE_SHA256, "tests/reference is the frozen pre-optimisation engine; restore it rather than edit it"


def test_live_classes_keep_the_oracle_fields():
    """Results are compared field by field as the oracle defines them, so the live classes may add no field unseen."""
    for old_module, new_module in ((analysis_v1, analysis), (compare_v1, compare), (simulate_v1, simulate), (pipeline_v1, pipeline)):
        for name, old in vars(old_module).items():
            if not (inspect.isclass(old) and dataclasses.is_dataclass(old) and old.__module__ == old_module.__name__):
                continue
            new = getattr(new_module, name)
            old_fields = [f.name for f in dataclasses.fields(old)]
            new_fields = [f.name for f in dataclasses.fields(new) if not f.name.startswith("_")]
            if name == "SnapshotAnalysis" and "graph" not in new_fields:
                # The graph may be built on first use instead, from the compared candidates.
                assert isinstance(inspect.getattr_static(new, "graph"), cached_property)
                old_fields.remove("graph")
            assert new_fields == old_fields, name


def test_bundled_fixtures_examples_and_snapshots():
    files = differential.fixture_files()
    assert len(files) >= 9
    for base in files:
        for prop in files:
            old, new = differential.run_both(base.read_bytes(), base.name, prop.read_bytes(), prop.name)
            found = differential.differences(old, new)
            assert not found, (base.name, prop.name, found)


def test_seeded_random_pairs():
    failures, seen = [], Counter()
    for seed in range(RANDOM_PAIRS):
        baseline, proposal = differential.random_pair(seed)
        old, new = differential.run_both_loaded(baseline, proposal)
        found = differential.differences(old, new)
        if found:
            failures.append((seed, found[:3]))
        comparison = new.comparison
        issues = [i for a in (comparison.baseline, comparison.proposal) for i in a.coverage.issues]
        seen["complete"] += comparison.complete
        seen["fixes"] += len(new.fixes)
        seen["over the fix cap"] += new.untested_fixes > 0
        seen["verified fix"] += any(fix.rank for fix in new.fixes)
        seen["unverified fix"] += any(not fix.rank for fix in new.fixes)
        seen["witness of 2+ steps"] += any(len(f.witness) > 1 for f in comparison.proposal.findings.values())
        seen["evidence changed"] += any(d.evidence_changed for d in comparison.deltas)
        seen["added"] += comparison.count("added") > 0
        seen["removed"] += comparison.count("removed") > 0
        seen["inconclusive"] += comparison.count("inconclusive") > 0
        seen["missing fact"] += any("no fact declares" in i.message for i in issues)
        seen["unknown fact"] += any(") is unknown" in i.message for i in issues)
        seen["cross-account"] += any("cross-account" in i.message for i in issues)
        seen["unresolved policy control"] += any(i.kind == "policy_control" for i in issues)
        seen["unmodelled mechanism"] += any(i.kind == "unmodelled_mechanism" for i in issues)
        seen["expected access inconclusive"] += any(r.result == "inconclusive" for r in comparison.proposal.expected_access)
        seen["over 1,000 candidates"] += len(comparison.proposal.candidates) > 1000
    assert not failures, failures
    # The generator must keep producing every situation the comparison is meant to cover.
    assert min(seen.values()) >= 2 and len(seen) == 17, dict(seen)
    assert seen["complete"] >= 50 and seen["fixes"] >= 100, dict(seen)


@pytest.mark.parametrize("case", sorted(differential.WORST_CASES))
def test_worst_cases(case, worst_case_workers):
    returncode, out, err = worst_case_workers.result(case)
    assert returncode == 0, err
    result = json.loads(out)
    assert result["differences"] == [], result
    assert result["candidates"] > 100_000 and result["fixes"] == 1, result
