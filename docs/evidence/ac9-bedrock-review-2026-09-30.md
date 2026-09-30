# AC-9 explanation review

- Generated: 2026-09-30T08:59:21Z
- Model: `apac.amazon.nova-pro-v1:0`; region: `ap-southeast-1`; prompt `explain-v2`; analysis `56bc16da787997e8`; finding `finding/p-ci-deployer/r-deploy-admin/privileged_role_use`
- Review each summary against the evidence and mark any unsupported access or fix claim.

## Review

Reviewed on 2026-09-30 by Claude against the evidence packet (prompt `explain-v2`). Claude is an AI assistant, and this claim review of all ten runs is its own; no person has checked it. Chai Pin Zheng read run 5 and approved it as the hosted page's recorded reply on 30 September 2026.

- Ten live Converse calls in one batch: 10 validated, 0 rejected by the reply validator, 0 refused, 0 errors. No request was retried.
- Unsupported access or fix claims: none. All ten describe the one route in the packet, cite `f-ci-pass-deploy-admin` and the engine-verified fix `revoke/f-ci-pass-deploy-admin`, and state the fix's recorded outcome; none invents another route, target, permission or fix. No reply says the result proves, guarantees or ensures anything, and "real" appears only in denials ("does not indicate a real compromise").
- Defects: runs 2, 3, 9 and 10 say the fix leaves more access untouched than the engine checked: "without affecting existing access as verified in the model" (2, 3), "other modeled accesses" (9) and "other access relationships" (10). The packet shows only the two expected-access checks, `ea-ci-reads-build-artifacts` and `ea-ci-deploys-app-runtime`, and run 3 cites neither. The wider claim happens to hold in this small snapshot (the fix changes only this finding's route: established relationships go from 4 to 3), but the packet does not show it, and it need not hold for a larger snapshot.
- Minor wording, no unsupported claim: run 1 says the change "is modeled to grant p-ci-deployer privileged access via the Lambda service", looser than the packet (the role is privileged, and the route runs through `l-build-hook`). Runs 4, 6, 7 and 8 say "other expected accesses", which implies the removed path was an expected access. Run 10's limitations leave out both scenario assumptions and the no-compromise statement.
- `explain-v1` defects: none recurred. No reply calls the entry principal trusted or compromised. "Privileged role" is attached to `r-deploy-admin` (runs 2 to 10) and never to the Lambda workload. Nine replies cite the expected-access checks and all passed validation (on 29 September the validator rejected run 9 for citing them). Every reply gives each entity's kind on first mention. The entry assumption uses the packet's words in runs 2, 3, 4, 6 and 8, is paraphrased with the same meaning as "the change proposer" in runs 1, 5, 7 and 9, and is left out of run 10.
- Recorded reply: run 5, proposed for `docs/evidence/recorded-explanation.json` in place of `explain-v1` run 8. It is the most specific reply with no defect: it names the changed fact's permission and endpoints, scopes the fix claim to both expected-access checks by ID, and states both scenario assumptions.
- Possible correction, not made: a prompt rule that the fix's effect on other access be stated only through the listed E# checks would target the four defects. Any prompt change needs a new version and a new live run. Prompt `explain-v3` adds this rule; it has not been run live yet.
- Cost: 10 calls returned model output, each with 1,637 input tokens (the `explain-v1` run used 1,573) and 194 to 229 output tokens: 16,370 in and 2,161 out in total. Latency 1,208 to 2,106 ms. No other Bedrock call was made; the script's read-only checks (caller identity and inference-profile lookup) ran once on their own and once before the batch.

## Per-run results

Validated means the reply was one JSON object with exactly the five keys, finding `A1`, a summary and limitations within their limits, only packet aliases in its text and citations, and the supplied fix `X1`.

| Run | Result | Refusal or error | Request ID | Tokens in / out | Latency | Cites both checks | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | validated | none | `e0ba1dda-b878-4aa5-8a8d-6b74eee468a1` | 1,637 / 197 | 1,322 ms | yes | no unsupported claims; minor wording |
| 2 | validated | none | `3fdcd8e7-f4f1-4cea-8d40-b3b0c51b1627` | 1,637 / 226 | 1,401 ms | yes | defect (fix scope) |
| 3 | validated | none | `4ba6d5c2-b663-44b5-a4c7-4af24c0f103d` | 1,637 / 215 | 1,309 ms | no | defect (fix scope); checks not cited |
| 4 | validated | none | `f26a6c58-eb55-457c-ac98-6f0638158c4e` | 1,637 / 229 | 1,260 ms | yes | no unsupported claims; minor wording |
| 5 | validated | none | `ebf66418-50b4-4e8f-8ee2-8675d76a6fb0` | 1,637 / 229 | 1,376 ms | yes | no unsupported claims; recorded reply |
| 6 | validated | none | `e9e5fa89-9ab3-42f7-a68a-f7b5855ea885` | 1,637 / 211 | 1,231 ms | yes | no unsupported claims; minor wording |
| 7 | validated | none | `3c73b2d9-4812-4e99-acff-d737d71f3333` | 1,637 / 217 | 2,106 ms | yes | no unsupported claims; minor wording |
| 8 | validated | none | `4437b2c6-2d0d-4b4e-beeb-1da51ff37c46` | 1,637 / 224 | 1,349 ms | yes | no unsupported claims; minor wording |
| 9 | validated | none | `a13f2f73-03d7-47de-9bd7-08f5740154b3` | 1,637 / 219 | 1,294 ms | yes | defect (fix scope) |
| 10 | validated | none | `4c149530-b60c-4c2b-b157-349be5567a99` | 1,637 / 194 | 1,208 ms | yes | defect (fix scope) |

## Evidence packet (reference)

The model saw only the aliases. The replies below show the real IDs they stand for.

| Alias | ID | What the packet says |
|---|---|---|
| A1 | `finding/p-ci-deployer/r-deploy-admin/privileged_role_use` | Added; severity High; impact `privileged_role_use`; target classification `privileged_role`; baseline unreachable, proposal reachable; coverage complete |
| P1, R1, L1 | `p-ci-deployer`, `r-deploy-admin`, `l-build-hook` | A principal, a role and a Lambda workload |
| Step 1 | Rule B, `lambda_pass_role` | P1 to R1 via L1, state true; all seven prerequisites below are true |
| F1 | `f-ci-pass-deploy-admin` | `iam_pass_role_to_lambda`, P1 to R1; false in the baseline, true in the proposal; the only changed fact |
| F2, F3 | `f-ci-create-build-hook`, `f-ci-invoke-build-hook` | P1 can create and invoke L1; true in both snapshots |
| F4 | `f-ci-controls-build-hook-code` | P1 controls L1's code; true in both; a scenario assumption, not an observed permission |
| F5 | `f-deploy-admin-trusts-lambda` | R1 trusts the Lambda service; true in both |
| D1, D2 | same-account check, policy-controls check | Both true |
| X1 | `revoke/f-ci-pass-deploy-admin` | Sets F1 to false on an in-memory copy of the proposal; removes this finding; verified in the model; coverage complete after; 0 high-risk findings after |
| E1, E2 | `ea-ci-reads-build-artifacts`, `ea-ci-deploys-app-runtime` | `object_read` and `role_use`; pass before and after X1; the only access the fix is checked against |
| Assumptions | | P1 "is treated as controlled by the party proposing the change"; F4 "is a scenario assumption, not an observed permission" |

## Claim review

Each claim as the replies word it, the evidence it rests on, and the verdict. "All" means runs 1 to 10.

| Claim | Runs | Evidence | Verdict |
|---|---|---|---|
| Kinds on first mention: "principal p-ci-deployer", "role r-deploy-admin", "Lambda workload l-build-hook" | All | Node kinds of P1, R1, L1 | Correct |
| Changed condition: "The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook" | All | `f-ci-pass-deploy-admin` (false to true, the only changed fact); step 1 runs via `l-build-hook`, which p-ci-deployer can create (`f-ci-create-build-hook`) | Supported |
| Access and route: "enabling p-ci-deployer to run code as r-deploy-admin" | All | A1 (added, unreachable to reachable); step 1, Rule B, true; the Rule B text "The subject can then run code as the role." | Supported. It credits the access to the change alone, which holds because `f-ci-pass-deploy-admin` was the only baseline blocker; the other six conditions are left to the evidence panel. |
| Severity: "modeled as a high-severity impact because r-deploy-admin is classified as a privileged role" | 2 to 10 | A1: severity High, target classification `privileged_role` | Supported. The packet gives both values but not the "because"; the engine rates every finding on a protected target High, so the reading is consistent. |
| "This change is modeled to grant p-ci-deployer privileged access via the Lambda service" | 1 | A1 impact `privileged_role_use`; `f-deploy-admin-trusts-lambda` | Minor wording: the role, not the access, is classified privileged, and the route runs through `l-build-hook` |
| Fix identity: "revoke/f-ci-pass-deploy-admin, which revokes [the iam_pass_role_to_lambda] fact f-ci-pass-deploy-admin", with "(iam_pass_role_to_lambda from p-ci-deployer to r-deploy-admin)" in run 5 | All | X1 revokes F1; F1's predicate, subject and object | Supported |
| Fix outcome: "removes" or "eliminates this finding", with "successfully" (1, 4, 6, 9, 10) or "as verified in the model" (2, 3) | All | X1: removes this finding, verified in the model | Supported |
| "without affecting existing access relationships" (1) or "expected accesses" (5), naming both checks | 1, 5 | E1 and E2 pass before and after X1 | Supported |
| "without affecting other expected accesses", naming both checks (4, 6) or neither (7, 8) | 4, 6, 7, 8 | E1 and E2, cited in `evidence_ids` by all four | Supported and within the checks. Minor wording: "other" implies the removed path was an expected access. |
| "without affecting existing access as verified in the model" | 2, 3 | Only E1 and E2 are checked; run 3 cites neither | Defect: wider than the checks |
| "without affecting other modeled accesses" | 9 | Only E1 and E2 are checked | Defect: wider than the checks |
| "without affecting other access relationships" | 10 | Only E1 and E2 are checked | Defect: wider than the checks |
| "This is a synthetic model" | All | Analysis data: synthetic configuration JSON | Supported |
| "No changes were made to any AWS account" or "No actual AWS resources were modified" | All | X1 acts on an in-memory copy; system prompt rule | Supported. None says that nothing was deployed or executed; the template does. |
| The result "does not indicate" or "does not reflect" a real compromise | 1 to 9 | System prompt rule | Supported. Run 10 says instead that the results "do not reflect the state of any real AWS account". |
| Entry assumption: "controlled by the party proposing the change" (2, 3, 4, 6, 8) or "by the change proposer" (1, 5, 7, 9) | 1 to 9 | Assumption 1 | Supported; never "trusted" or "compromised". Run 10 states no assumption. |
| Code assumption: "p-ci-deployer controls the code of l-build-hook" (2, 3, 4, 6, 8), "controls the Lambda code (f-ci-controls-build-hook-code)" (7, 9), "an assumed permission, not an observed one" (1) or "assumed, not observed" (5) | 1 to 9 | `f-ci-controls-build-hook-code`; assumption 2 | Supported |
| "The finding and fix candidate are based on the provided configuration JSON" | 10 | Analysis data | Supported |

## Deterministic template (reference)

In the proposal, `p-ci-deployer` can use the privileged role `r-deploy-admin`: `p-ci-deployer` runs code as `r-deploy-admin` through `l-build-hook` (Rule B). In the baseline this route was blocked: `f-ci-pass-deploy-admin` was false. The proposal changes `f-ci-pass-deploy-admin` from false to true. Simulating revocation of `f-ci-pass-deploy-admin` removes this finding; no high-risk findings remain and 2 of 2 expected-access checks pass. Verified in this model. This is a static analysis of synthetic facts; nothing was deployed, executed or changed in AWS.

## Run 1: generated

- request ID `e0ba1dda-b878-4aa5-8a8d-6b74eee468a1` · tokens 1637 in / 197 out · latency 1322 ms · at 2026-09-30T08:59:22Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] no unsupported claims. Minor wording: "is modeled to grant p-ci-deployer privileged access via the Lambda service" is looser than the packet, which classifies the role, not the access, as privileged and routes through `l-build-hook`; "modeled to grant" can read as intent.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This change is modeled to grant p-ci-deployer privileged access via the Lambda service. Fix candidate revoke/f-ci-pass-deploy-admin, which revokes fact f-ci-pass-deploy-admin, successfully removes this finding without affecting existing access relationships ea-ci-reads-build-artifacts and ea-ci-deploys-app-runtime.

Limitations: This is a synthetic model. No changes were made to any AWS accounts, and the results do not indicate a real compromise. The scenario assumes p-ci-deployer is controlled by the change proposer, and fact f-ci-controls-build-hook-code is an assumed permission, not an observed one.
```

## Run 2: generated

- request ID `3fdcd8e7-f4f1-4cea-8d40-b3b0c51b1627` · tokens 1637 in / 226 out · latency 1401 ms · at 2026-09-30T08:59:24Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] defect found (fix scope). "without affecting existing access as verified in the model" claims more than the packet shows: the engine checked only `ea-ci-reads-build-artifacts` and `ea-ci-deploys-app-runtime`. No unsupported access claim.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. The fix candidate revoke/f-ci-pass-deploy-admin, which revokes the iam_pass_role_to_lambda fact f-ci-pass-deploy-admin, removes this finding without affecting existing access as verified in the model.

Limitations: This is a synthetic model: no changes were made to any AWS account, and the result does not indicate a real compromise. The scenario assumes p-ci-deployer is controlled by the party proposing the change and that p-ci-deployer controls the code of l-build-hook.
```

## Run 3: generated

- request ID `4ba6d5c2-b663-44b5-a4c7-4af24c0f103d` · tokens 1637 in / 215 out · latency 1309 ms · at 2026-09-30T08:59:25Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] defect found (fix scope). Same wording as run 2, and `evidence_ids` cites neither expected-access check, so the claim rests on no cited evidence. No unsupported access claim.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. Fix candidate revoke/f-ci-pass-deploy-admin, which revokes the iam_pass_role_to_lambda fact f-ci-pass-deploy-admin, eliminates this finding without affecting existing access as verified in the model.

Limitations: This is a synthetic model: no changes were made in any AWS account, and the result does not reflect a real compromise. The scenario assumes p-ci-deployer is controlled by the party proposing the change and that p-ci-deployer controls the code of l-build-hook.
```

## Run 4: generated

- request ID `f26a6c58-eb55-457c-ac98-6f0638158c4e` · tokens 1637 in / 229 out · latency 1260 ms · at 2026-09-30T08:59:27Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] no unsupported claims. Minor wording: "other expected accesses" implies the removed path was an expected access.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. The fix candidate revoke/f-ci-pass-deploy-admin, which revokes the iam_pass_role_to_lambda fact f-ci-pass-deploy-admin, successfully removes this finding without affecting other expected accesses ea-ci-reads-build-artifacts and ea-ci-deploys-app-runtime.

Limitations: This is a synthetic model: no changes were made in any AWS account, and the result does not indicate a real compromise. The scenario assumes p-ci-deployer is controlled by the party proposing the change and that p-ci-deployer controls the code of l-build-hook.
```

## Run 5: generated

- request ID `ebf66418-50b4-4e8f-8ee2-8675d76a6fb0` · tokens 1637 in / 229 out · latency 1376 ms · at 2026-09-30T08:59:28Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] no unsupported claims. Proposed as the recorded reply. The entry assumption is paraphrased ("the change proposer") with the packet's meaning.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. Fix candidate revoke/f-ci-pass-deploy-admin, which revokes fact f-ci-pass-deploy-admin (iam_pass_role_to_lambda from p-ci-deployer to r-deploy-admin), removes this finding without affecting expected accesses ea-ci-reads-build-artifacts and ea-ci-deploys-app-runtime.

Limitations: This is a synthetic model. No changes were made to any AWS accounts. The result does not indicate a real compromise. The scenario assumes p-ci-deployer is controlled by the change proposer, and fact f-ci-controls-build-hook-code is assumed, not observed.
```

## Run 6: generated

- request ID `e9e5fa89-9ab3-42f7-a68a-f7b5855ea885` · tokens 1637 in / 211 out · latency 1231 ms · at 2026-09-30T08:59:30Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] no unsupported claims. Minor wording: "other expected accesses", as in run 4.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. The fix candidate revoke/f-ci-pass-deploy-admin, which revokes the iam_pass_role_to_lambda fact f-ci-pass-deploy-admin, successfully removes this finding without affecting other expected accesses ea-ci-reads-build-artifacts and ea-ci-deploys-app-runtime.

Limitations: This is a synthetic model. No changes were made to any AWS account. The result does not indicate a real compromise. The scenario assumes p-ci-deployer is controlled by the party proposing the change and that p-ci-deployer controls the code of l-build-hook.
```

## Run 7: generated

- request ID `3c73b2d9-4812-4e99-acff-d737d71f3333` · tokens 1637 in / 217 out · latency 2106 ms · at 2026-09-30T08:59:32Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] no unsupported claims. Minor wording: "other expected accesses", as in run 4; the checks are cited in `evidence_ids` but not named in the summary.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. Fix candidate revoke/f-ci-pass-deploy-admin, which revokes the iam_pass_role_to_lambda fact f-ci-pass-deploy-admin, removes this finding without affecting other expected accesses.

Limitations: This is a synthetic model. No changes were made to any AWS account. The result does not indicate a real compromise. The scenario assumes p-ci-deployer is controlled by the change proposer and that p-ci-deployer controls the Lambda code (f-ci-controls-build-hook-code).
```

## Run 8: generated

- request ID `4437b2c6-2d0d-4b4e-beeb-1da51ff37c46` · tokens 1637 in / 224 out · latency 1349 ms · at 2026-09-30T08:59:33Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] no unsupported claims. Minor wording: as in run 7.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. Fix candidate revoke/f-ci-pass-deploy-admin, which revokes the iam_pass_role_to_lambda fact f-ci-pass-deploy-admin, eliminates this finding without affecting other expected accesses.

Limitations: This is a synthetic model: no changes were made in any AWS account, and the result does not reflect a real-world compromise. The scenario assumes p-ci-deployer is controlled by the party proposing the change and that p-ci-deployer controls the code of l-build-hook.
```

## Run 9: generated

- request ID `a13f2f73-03d7-47de-9bd7-08f5740154b3` · tokens 1637 in / 219 out · latency 1294 ms · at 2026-09-30T08:59:34Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] defect found (fix scope). "without affecting other modeled accesses" covers every access in the model; the engine checked two. No unsupported access claim.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. The fix candidate revoke/f-ci-pass-deploy-admin, which revokes the iam_pass_role_to_lambda fact f-ci-pass-deploy-admin, successfully removes this finding without affecting other modeled accesses.

Limitations: This is a synthetic model. No changes were made to any AWS account. The result does not indicate a real compromise. The scenario assumes p-ci-deployer is controlled by the change proposer and that p-ci-deployer controls the Lambda code (f-ci-controls-build-hook-code).
```

## Run 10: generated

- request ID `4c149530-b60c-4c2b-b157-349be5567a99` · tokens 1637 in / 194 out · latency 1208 ms · at 2026-09-30T08:59:36Z
- Evidence cited: f-ci-pass-deploy-admin, f-ci-create-build-hook, f-ci-invoke-build-hook, f-ci-controls-build-hook-code, f-deploy-admin-trusts-lambda, same-account check, policy-controls check, ea-ci-reads-build-artifacts, ea-ci-deploys-app-runtime; fix cited: revoke/f-ci-pass-deploy-admin
- Reviewer verdict: [x] defect found (fix scope). "without affecting other access relationships" claims more than the two checks show. The limitations also leave out both scenario assumptions and the no-compromise statement. No unsupported access claim.

```text
The proposed change allows principal p-ci-deployer to pass role r-deploy-admin to Lambda workload l-build-hook, enabling p-ci-deployer to run code as r-deploy-admin. This is modeled as a high-severity impact because r-deploy-admin is classified as a privileged role. The fix candidate revoke/f-ci-pass-deploy-admin, which revokes the iam_pass_role_to_lambda fact f-ci-pass-deploy-admin, successfully removes this finding without affecting other access relationships.

Limitations: This is a synthetic model. No actual AWS resources were modified. The finding and fix candidate are based on the provided configuration JSON and do not reflect the state of any real AWS account.
```
