"""Check Amazon Bedrock access for AttackGraph AI.

Without flags this makes read-only, no-charge AWS calls: it resolves the
configured model and region, identifies the caller, and confirms that the
model or inference profile exists in the region.

--invoke sends the bundled demo finding through the real explanation
pipeline (a chargeable Converse call, well under one US cent each) and
prints the model ID, region, request ID, token usage and latency: the
evidence AC-9 asks for. --repeat N runs N fresh calls with no cache, and
--out writes every explanation to a Markdown file for claim-by-claim review.

Usage:
    python scripts/check_bedrock.py
    python scripts/check_bedrock.py --invoke
    python scripts/check_bedrock.py --invoke --repeat 10 --out ac9-review.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from attackgraph.explain import BedrockExplainer, build_packet, configured_model, template_summary  # noqa: E402
from attackgraph.pipeline import run  # noqa: E402
from attackgraph.render import plain_segments  # noqa: E402

PROFILE_PREFIXES = ("us.", "eu.", "apac.", "au.", "jp.", "ca.", "global.", "us-gov.")


def read_only_checks(model_id: str, region: str) -> bool:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    ok = True
    try:
        arn = boto3.client("sts", region_name=region).get_caller_identity()["Arn"]
        kind = arn.split(":")[-1]
        print(f"Caller: {kind} (account ID not printed)")
        if kind == "root":
            print(
                "  WARNING: these are root-user access keys. Use an IAM user or role limited to "
                "bedrock:InvokeModel on the chosen model for the demo."
            )
    except (BotoCoreError, ClientError) as exc:
        print(f"Caller identity failed: {exc}")
        return False

    bedrock = boto3.client("bedrock", region_name=region)
    try:
        if model_id.startswith(PROFILE_PREFIXES):
            profile = bedrock.get_inference_profile(inferenceProfileIdentifier=model_id)
            print(f"Inference profile {model_id}: {profile.get('status', 'unknown')}")
        else:
            details = bedrock.get_foundation_model(modelIdentifier=model_id)["modelDetails"]
            print(f"Foundation model {model_id}: inference types {details.get('inferenceTypesSupported')}")
    except (BotoCoreError, ClientError) as exc:
        print(f"Model lookup failed for {model_id} in {region}: {exc}")
        ok = False
    return ok


def invoke(model_id: str, region: str, repeat: int, out: Path | None) -> bool:
    fixtures = ROOT / "fixtures" / "demo"
    result = run(
        (fixtures / "baseline.json").read_bytes(),
        "baseline.json",
        (fixtures / "proposed.json").read_bytes(),
        "proposed.json",
    )
    comparison = result.comparison
    delta = comparison.deltas[0]
    packet = build_packet(comparison, delta, result.fixes)
    lines = [
        "# AC-9 explanation review",
        "",
        f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"- Model: `{model_id}`; region: `{region}`; analysis `{comparison.analysis_id}`; finding `{delta.id}`",
        "- Review each summary against the evidence and mark any unsupported access or fix claim.",
        "",
        "## Deterministic template (reference)",
        "",
        template_summary(comparison, delta, result.fixes),
        "",
    ]
    successes = 0
    for attempt in range(1, repeat + 1):
        outcome = BedrockExplainer(model_id, region).explain(packet)
        print(
            f"[{attempt}/{repeat}] status={outcome.status} request_id={outcome.request_id or '-'} "
            f"tokens={outcome.input_tokens}/{outcome.output_tokens} latency_ms={outcome.latency_ms}"
        )
        lines += [f"## Run {attempt}: {outcome.status}", ""]
        lines.append(
            f"- request ID `{outcome.request_id or '-'}` · tokens {outcome.input_tokens} in / {outcome.output_tokens} out · "
            f"latency {outcome.latency_ms} ms · at {outcome.created_at}"
        )
        if outcome.ok:
            successes += 1
            summary = plain_segments(outcome.summary)
            print(f"    {summary}")
            lines += [
                f"- Evidence cited: {', '.join(outcome.evidence_ids)}; fix cited: {outcome.cited_fix or 'none'}",
                "- Reviewer verdict: [ ] no unsupported claims  [ ] defect found (describe)",
                "",
                "```text",
                summary,
                "",
                "Limitations: " + plain_segments(outcome.limitations),
                "```",
                "",
            ]
        else:
            print(f"    {outcome.error}")
            lines += [f"- Error: {outcome.error}", ""]
    if out:
        out.write_text("\n".join(lines))
        print(f"Wrote {out}")
    print(f"{successes}/{repeat} validated explanations.")
    return successes == repeat


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--invoke", action="store_true", help="make real (chargeable) Converse calls")
    parser.add_argument("--repeat", type=int, default=1, help="number of fresh calls with --invoke")
    parser.add_argument("--out", type=Path, help="write the explanations to this Markdown file")
    args = parser.parse_args()

    model_id, region = configured_model()
    print(f"Model: {model_id}\nRegion: {region}")
    ok = read_only_checks(model_id, region)
    if args.invoke:
        ok = invoke(model_id, region, max(1, args.repeat), args.out) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
