# AttackGraph AI comparison report

> **Synthetic configuration JSON.** Static analysis of declared facts. No configuration was deployed or executed, and no represented account was contacted. Amazon Bedrock is called only to explain results.

| Field | Value |
|---|---|
| Generated | 2026-09-30T09:37:46Z |
| Analysis ID | `1985aa1c5454e5bb` |
| Engine | 0.1.0 |
| Security model | `attackgraph-rules-v1` |
| Schema | 1.0 |
| Baseline | `demo-baseline` · Baseline\: CI deploys with the app runtime role · file baseline\.json · sha256 `0b074dd0c9453890` · synthetic: true |
| Proposal | `example-unknown-passrole` · Proposed\: PassRole change with an unresolved condition · file unknown\-prerequisite\.json · sha256 `bda8411cdf382b4d` · synthetic: true |
| Coverage | incomplete |

## Result

**Analysis incomplete. Deltas are provisional and no result is a safe verdict.**

- High-risk findings: baseline 0, proposal 0
- Added 0, removed 0, unchanged 0, inconclusive 1
- Severity is a demo rubric (reachable privileged role or readable protected object = High), not CVSS or an AWS rating.

## Coverage

- **Baseline: complete.** Rule A: direct S3 object read: 2 established, 2 blocked, 0 unresolved; Rule B: role use through a Lambda workload: 1 established, 2 blocked, 0 unresolved.
- **Proposal: incomplete.** Rule A: direct S3 object read: 2 established, 4 blocked, 0 unresolved; Rule B: role use through a Lambda workload: 1 established, 2 blocked, 1 unresolved.
  - p\-ci\-deployer can run code as r\-deploy\-admin through Lambda workload l\-build\-hook\: unresolved because fact f\-ci\-pass\-deploy\-admin \(p\-ci\-deployer can pass role r\-deploy\-admin to Lambda \(iam\:PassRole\)\) is unknown (`/facts/1`)

- Candidates are evaluated for every subject that is reachable\, or possibly reachable\, from an entry principal\.
- Rule A evaluates S3 objects that are protected or named in an expected\-access check\, plus objects with a declared s3\_get\_object fact\.

## Configuration changes

| Fact | Statement | Baseline | Proposal | Pointer (proposal) |
|---|---|---|---|---|
| `f-ci-pass-deploy-admin` | p\-ci\-deployer can pass role r\-deploy\-admin to Lambda \(iam\:PassRole\) | false | unknown | `/facts/1` |

## Findings

| Status | Severity | Finding | Baseline | Proposal |
|---|---|---|---|---|
| Inconclusive (provisional) | High | p\-ci\-deployer can use privileged role r\-deploy\-admin | unreachable | inconclusive |

### Inconclusive (provisional) · High · p\-ci\-deployer can use privileged role r\-deploy\-admin

- Finding ID: `finding/p-ci-deployer/r-deploy-admin/privileged_role_use`
- Impact: privileged role use; target classification `privileged_role`
- Baseline: unreachable; proposal: inconclusive

Possible route in the proposal snapshot (not established):

1. p\-ci\-deployer runs code as r\-deploy\-admin through Lambda workload l\-build\-hook \(Rule B\): candidate `B:p-ci-deployer->r-deploy-admin@l-build-hook` is **unknown**

   | Prerequisite | State | Evidence | JSON pointer |
   |---|---|---|---|
   | p\-ci\-deployer can pass role r\-deploy\-admin to Lambda \(iam\:PassRole\) | unknown | `f-ci-pass-deploy-admin` **CHANGED** | `/facts/1` |
   | p\-ci\-deployer can create Lambda workload l\-build\-hook | true | `f-ci-create-build-hook` | `/facts/2` |
   | p\-ci\-deployer can invoke Lambda workload l\-build\-hook | true | `f-ci-invoke-build-hook` | `/facts/3` |
   | p\-ci\-deployer controls the code of l\-build\-hook | true | `f-ci-controls-build-hook-code` (scenario assumption) | `/facts/4` |
   | r\-deploy\-admin trust policy allows the Lambda service | true | `f-deploy-admin-trusts-lambda` | `/facts/6` |
   | p\-ci\-deployer\, r\-deploy\-admin and l\-build\-hook are in the same synthetic account | true | derived | `/nodes/0/account_id`, `/nodes/2/account_id`, `/nodes/3/account_id` |
   | policy restrictions are declared resolved for this scenario | true | derived | `/coverage/policy_controls` |

## Expected-access checks

| Check | Relationship | Baseline | Proposal |
|---|---|---|---|
| `ea-ci-reads-build-artifacts` | `p-ci-deployer` object read `o-build-artifacts` | pass | pass |
| `ea-ci-deploys-app-runtime` | `p-ci-deployer` role use `r-app-runtime` | pass | pass |

## Fix simulation

No newly enabled grant participates in a proposal finding, so no single-permission fix was tested.

No fix was simulated in this session.

## AI explanations

No AI explanation was requested for this analysis.

## Nodes

| ID | Kind | Account | Label (display only) |
|---|---|---|---|
| `l-build-hook` | Lambda workload | `syn-app-prod` | Post\-build hook function |
| `o-build-artifacts` | S3 object | `syn-app-prod` | artifacts\/release\.zip |
| `o-customer-export` | S3 object | `syn-app-prod` | exports\/customers\.csv |
| `p-ci-deployer` | Principal | `syn-app-prod` | CI deploy user \(build pipeline\) |
| `r-app-runtime` | Role | `syn-app-prod` | App runtime execution role |
| `r-deploy-admin` | Role | `syn-app-prod` | Deployment admin role |

## Limitations

- Input is hand-authored synthetic configuration JSON. Terraform, CloudFormation and raw IAM policies are not parsed.
- Only two rule families are modelled: direct S3 object reads (Rule A) and role use through a Lambda workload (Rule B).
- Permissions boundaries, SCPs, resource policies, conditions and explicit denies are not evaluated; the fixture declares whether their effect is already reflected in its facts.
- Complete coverage means complete for the declared synthetic model, not for an AWS account.
- Fix candidates are single revocations of newly enabled grants. They are not a minimum cut and do not prove that real business workflows keep working.
- The AI explanation is generated text. Identifier checks do not prove its prose is true; the deterministic evidence is authoritative.
