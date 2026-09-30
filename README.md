<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Live demo][demo-shield]][demo-url]
[![Amazon Bedrock: Nova Pro][bedrock-shield]][bedrock-url]
[![Python 3.11+][python-shield]][python-url]
[![Pull-request check: GitHub Actions][check-shield]][check-url]
[![Synthetic data only][synthetic-shield]][synthetic-url]



<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://attackgraph-ai.vercel.app">
    <img src="docs/brand/mark.svg" alt="AttackGraph AI logo" width="80" height="80">
  </a>

  <h3 align="center">AttackGraph AI</h3>

  <p align="center">
    See what a cloud permission change unlocks, before you deploy it.
    <br />
    <a href="#how-it-works"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://attackgraph-ai.vercel.app/demo">View Demo</a>
    &middot;
    <a href="https://github.com/Ducksss/attackgraph-ai/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/Ducksss/attackgraph-ai/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#the-demo-in-four-pictures">The demo in four pictures</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#run-the-app">Run the app</a></li>
        <li><a href="#run-it-as-a-pull-request-check">Run it as a pull-request check</a></li>
        <li><a href="#amazon-bedrock">Amazon Bedrock</a></li>
        <li><a href="#demo-script">Demo script</a></li>
        <li><a href="#hosting">Hosting</a></li>
      </ul>
    </li>
    <li>
      <a href="#how-it-works">How it works</a>
      <ul>
        <li><a href="#snapshot-format">Snapshot format</a></li>
        <li><a href="#rules">Rules</a></li>
        <li><a href="#coverage-and-comparison">Coverage and comparison</a></li>
        <li><a href="#fix-simulation">Fix simulation</a></li>
        <li><a href="#ai-explanation-boundaries">AI explanation boundaries</a></li>
      </ul>
    </li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#acceptance-criteria">Acceptance criteria</a></li>
    <li><a href="#limitations">Limitations</a></li>
    <li><a href="#project-layout">Project layout</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#licence">Licence</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgements">Acknowledgements</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

[![AttackGraph AI overview: a pull request widens iam:PassRole, completes all 7 conditions of a route to the admin role, and the engine reports the new path and a verified fix][product-screenshot]](https://attackgraph-ai.vercel.app)

A pull request that widens one IAM permission can quietly let a build pipeline run code as an administrator. Code review sees the changed line. AttackGraph AI compares the current and proposed configuration, draws the exact route that line opens, explains it in plain English with Amazon Bedrock, and proves which single revocation closes it.

It is a static, defensive review prototype built for the AWS Build Beyond Student AI Demo Challenge 2026. It reads synthetic JSON snapshots, never connects to the accounts they describe, and never deploys or executes anything. Its only AWS call is the Bedrock request for explanation text.

Try it at **[attackgraph-ai.vercel.app](https://attackgraph-ai.vercel.app)**: the overview explains the problem, and the [live demo](https://attackgraph-ai.vercel.app/demo) runs the real engine on bundled synthetic scenarios. No sign-up, no uploads, no AI calls on the hosted pages.

### The demo in four pictures

**1. The pull request is blocked on the line that opens the route.** The live demo opens on the flagship change as a pull request: line 27 of `snapshots/app-prod.json` flips PassRole from `false` to `true`, the repository's check leaves its note on that line, and the check fails with exit status 1.

![The pull request: the one-line diff, the check's note on line 27 and the failed check](docs/images/pull-request.png)

**2. One changed permission opens a route to the admin role.** The proposal lets the CI deploy user pass the deployment admin role to Lambda. The CI user can already create, invoke and control a Lambda function, so it can now run code as the admin role. In the baseline, that one fact was false and the route was blocked.

![Verdict, key numbers and the new route in the live demo](docs/images/demo.png)

**3. Amazon Bedrock explains it; the engine decides it.** Amazon Nova Pro writes the plain-English explanation from an evidence packet of placeholder IDs. It cannot add findings, change severity or invent fixes, and a reply that cites anything outside the packet is rejected.

![The recorded Amazon Nova Pro explanation, each entity shown by name, next to its model, region, request ID and token usage](docs/images/explanation.png)

**4. Simulating the revocation closes the route and keeps normal work running.**

![Fix card: the route after the fix with the revoked arrow red and dashed, high-risk paths 1 to 0, normal access 2 of 2, verified in this model](docs/images/fix.png)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



### Built With

* [![Python][Python-badge]][Python-url]
* [![Streamlit][Streamlit-badge]][Streamlit-url]
* [![NetworkX][NetworkX-badge]][NetworkX-url]
* [![Amazon Bedrock][Bedrock-badge]][Bedrock-url]
* [![GitHub Actions][Actions-badge]][Actions-url]
* [![Vercel][Vercel-badge]][Vercel-url]
* [![pytest][Pytest-badge]][Pytest-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

The app runs locally in about a minute. Live Amazon Bedrock explanations are optional: without AWS credentials, the app says the explanation is unavailable and shows its deterministic summary.

### Prerequisites

* Python 3.11 or newer
* Optional, for live explanations: AWS credentials allowed to call `bedrock:InvokeModel` on the model you choose (see [Amazon Bedrock](#amazon-bedrock))

### Installation

1. Clone the repository
   ```bash
   git clone https://github.com/Ducksss/attackgraph-ai.git && cd attackgraph-ai
   ```
2. Create a virtual environment and install the pinned dependencies
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
3. Run the automated suite
   ```bash
   .venv/bin/python -m pytest
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

### Run the app

```bash
.venv/bin/streamlit run app.py
```

Open http://localhost:8501 for the overview, or go straight to the live demo at http://localhost:8501/demo. The flagship scenario runs as soon as the demo page loads, so the result is visible without a click. The other scenarios open from the switcher or by link: `/demo?scenario=repair`, `/demo?scenario=unknown`, `/demo?scenario=invalid` and `/demo?scenario=upload`. The local app is the one that makes live Amazon Bedrock calls and accepts uploads.

### Run it as a pull-request check

The engine also runs from the command line, so a CI job can gate on it. This compares the flagship pair and exits 1:

```bash
.venv/bin/python -m attackgraph fixtures/demo/baseline.json fixtures/demo/proposed.json
```

| Exit status | Meaning |
|---|---|
| 0 | No new modelled high-risk access, and coverage is complete |
| 1 | The proposal opens a new path to a protected target, or the result is incomplete. An unknown is never a pass. |
| 2 | Nothing was analysed: a file is missing, unreadable or not a valid snapshot, or the arguments are wrong |

`--report FILE` also writes the Markdown report, and `--github` adds GitHub Actions annotations on the proposal's lines. Given one file, the check compares it with an empty baseline, so every path in it counts as new. It is offline: no Amazon Bedrock or other AWS call.

[`.github/workflows/permission-check.yml`](.github/workflows/permission-check.yml) runs the check on every pull request. Each snapshot the pull request adds or changes under [`snapshots/`](snapshots/) is compared with its version on the base branch. A new path, an incomplete result or an invalid file fails the job and is marked on the line responsible, and the full report goes to the job summary. The job needs no secrets or AWS credentials, and it runs even when no snapshot changed, so it can be made a required check in branch protection.

To see it block a change, open a pull request that sets `f-ci-pass-deploy-admin` on line 27 of [`snapshots/app-prod.json`](snapshots/app-prod.json) to `"true"`, the flagship change. The check fails, and line 27 is annotated with the route it opens and the verified fix. Revert the line and the check passes again. A pull request that closes a path already on the base branch passes with a "Path closed" notice on the line.

The check sees only what the snapshots declare. Terraform and IAM policies are not parsed, so keeping the snapshots in step with the real infrastructure code is manual. The workflow also runs the pull request's own copy of the engine; a team adopting it would pin a released version instead.

### Amazon Bedrock

| Variable | Default | Purpose |
|---|---|---|
| `ATTACKGRAPH_BEDROCK_MODEL_ID` | `apac.amazon.nova-pro-v1:0` | Any Converse-capable text model or inference profile enabled in your account |
| `ATTACKGRAPH_BEDROCK_REGION` | `AWS_REGION`, then `ap-southeast-1` | Bedrock runtime region |
| `ATTACKGRAPH_AI` | `on` | `off` disables the explanation button, for example on a public host |

The default is Amazon Nova Pro through the APAC cross-region inference profile, confirmed with live inference in `ap-southeast-1` on 29 September 2026. A newly created AWS account can return `AccessDeniedException: Your account is currently being verified` for up to about two hours; the app shows its fallback until then.

Credentials come from the standard AWS credential chain of the machine running Streamlit. They never enter uploads, prompts, reports, logs or the browser. For the demo, use an IAM user or role limited to `bedrock:InvokeModel` on the inference profile and the foundation models it routes to, not root-user keys.

```bash
.venv/bin/python scripts/check_bedrock.py
```

Read-only: prints the model, region and caller type, and checks that the model exists. No inference, no charge.

```bash
.venv/bin/python scripts/check_bedrock.py --invoke --repeat 10 --out ac9-review.md
```

Sends the demo finding through the real pipeline ten times (chargeable, each call well under one US cent), prints request IDs, token usage and latency, and writes every explanation to `ac9-review.md` for claim-by-claim review.

### Demo script

1. Open the overview. The hero diagram is the whole idea: a pull request widens `iam:PassRole`, that one change completes all 7 conditions of a route to the admin role, and the engine reports the new path and a verified fix.
2. Scroll to **Permission reviews miss paths**: the four reasons a line-by-line review misses this.
3. **Open the live demo**. It opens on **The pull request**: line 27 of `snapshots/app-prod.json` flips PassRole from `false` to `true`, the repository's check leaves its note on that line ("New path to a protected role"), and the check fails with exit status 1. Press **Apply the suggested fix**: the fix commit reverts the line and the check passes. Under **Inside the check**, the flagship analysis is already computed: "1 new path to a protected role", high-risk paths 0 to 1, coverage complete.
4. **The path it opens**: CI deploy user, then the post-build hook function, then the deployment admin role. The amber arrow is the one new permission. **The change** shows the fact that flipped and its JSON pointer, and explains `iam:PassRole` in one paragraph. **Why the route works** lists all 7 conditions and marks the changed one.
5. **What this means**: press **Explain with Amazon Bedrock** in the local app, or read the recorded Nova Pro reply on the hosted page. Match each claim to the conditions card.
6. **Simulate the fix**. The fix card redraws the route with the revoked arrow red and dashed, high-risk paths go from 1 to 0, normal access stays at 2 of 2, and the card says "Verified in this model", all in one view.
7. Close on **Trust and limits** on the overview: synthetic data only. The prototype verifies this explicit model; wider AWS policy coverage is future work.

The other scenarios show a comparison that closes the path, an unknown fact that makes the result incomplete rather than safe, and field-level validation errors.

### Hosting

Streamlit needs a long-lived WebSocket server, which Vercel does not run, so the hosted site is a static build. `scripts/build_site.py` runs the engine on every bundled scenario and renders the overview to `site/index.html` and the demo to `site/demo/index.html`, using the same card code as the app. The scenario tabs and the fix toggle switch between pre-computed states in the browser. The flagship's pull-request card comes from `attackgraph/pullrequest.py`, which runs the real check (`python -m attackgraph --github`, laid out as the workflow lays it out) on the pull-request and fix-commit versions of `snapshots/app-prod.json`, so its note and log are that command's output.

The hosted pages make no AI calls and accept no uploads, as the PRD requires for anonymous visitors. The recorded Nova Pro reply appears only while its analysis ID and finding ID match the fresh analysis, so a change to the fixtures or rules hides it instead of showing a stale explanation. `tests/test_site.py` fails when the committed build is out of date.

```bash
.venv/bin/python scripts/build_site.py
```

```bash
cd site && vercel deploy --prod
```

If you host the Streamlit app itself, restrict it to bundled fixtures or set `ATTACKGRAPH_AI=off`. Do not expose an anonymous upload endpoint that can trigger chargeable Bedrock calls.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- HOW IT WORKS -->
## How it works

```text
baseline.json + proposed.json (synthetic)
        |
  validate: size, UTF-8, duplicate keys, raw-policy keys, JSON Schema, references
        |
  derive Rule A / Rule B candidates (three-valued AND over explicit prerequisites)
        |
  NetworkX graph of candidates -> shortest witness per (entry, target), ties broken by fact IDs
        |
  compare findings  ->  revoke each newly enabled grant on a copy and recompute
        |                               |
        |                     Amazon Bedrock (explanation only, aliased evidence)
        +---------------+---------------+
                        |
      Streamlit app, static site, Markdown report and pull-request check
```

### Snapshot format

Snapshots are hand-authored JSON that follow [`attackgraph/snapshot.schema.json`](attackgraph/snapshot.schema.json). They are not Terraform plans or raw IAM policies, and the report labels them "Synthetic configuration JSON".

| Record | Content |
|---|---|
| Snapshot | `schema_version` `"1.0"`, `snapshot_id`, optional `name`, `synthetic: true`, `model_version` `"attackgraph-rules-v1"`, `coverage`, `nodes`, `facts`, `entry_principals`, `protected_targets`, `expected_access` |
| Node | `id`, `kind` (`principal`, `role`, `lambda`, `s3_object`), `label` (display only), `account_id` (must start with `syn-`, so real account numbers stay out) |
| Fact | `id`, `predicate`, `subject`, `object` (omitted for unary predicates), `state` (`"true"`, `"false"`, `"unknown"`). Its JSON pointer is its position in the file. |
| Entry principal | A `principal` node whose control is an explicit scenario assumption |
| Protected target | A node with `privileged_role` (role) or `sensitive_object` (S3 object) classification |
| Expected access | An entry principal, a target and `object_read` or `role_use` that a fix should preserve |
| Coverage | `policy_controls`: whether permissions boundaries, SCPs, resource policies, conditions and explicit denies are `resolved` (already reflected in the facts) or `unresolved`; `unmodelled_mechanisms` present in the scenario |

| Predicate | Subject | Object | Kind |
|---|---|---|---|
| `s3_get_object` | principal or role | s3_object | permission |
| `iam_pass_role_to_lambda` | principal or role | role | permission |
| `lambda_create_function` | principal or role | lambda | permission |
| `lambda_invoke_function` | principal or role | lambda | permission |
| `controls_workload_code` | principal or role | lambda | scenario assumption |
| `role_trusts_lambda_service` | role | none | trust |

Validation stops analysis of both files on any error and reports each one with a JSON pointer. It rejects files over 1 MiB, non-UTF-8 text, duplicate JSON keys, `NaN`, control characters, capitalised IAM policy keys (`Statement`, `Effect`, ...), unknown fields, unsupported versions, dangling references, duplicate IDs, kind mismatches and duplicate facts. Limits: 100 nodes and 300 facts.

### Rules

**Rule A, direct S3 object read.** Established when the subject has a declared effective `s3_get_object` fact for that exact object and policy controls are declared resolved.

**Rule B, role use through a Lambda workload.** One composite edge from a subject to a role, established only when all of these are true for the same subject, role and workload: the subject can pass the role to Lambda, create the workload, invoke it and controls its code; the role trusts the Lambda service; all three share one synthetic account; policy controls are declared resolved. `iam:PassRole` alone never establishes the edge, and no single permission is traversable on its own.

Prerequisites combine with three-valued AND. A false prerequisite blocks the candidate; otherwise an unknown one leaves it unresolved. A prerequisite with no declared fact is unknown, not false. Cross-account combinations and unresolved policy controls are also unknown.

Candidates are evaluated for every subject that is reachable, or possibly reachable, from an entry principal. Rule A is evaluated against every protected object and expected-access object, and Rule B against every other role through every Lambda workload. **A fixture must declare an explicit `false` fact for each relationship it rules out**; otherwise that relationship is unknown and coverage is incomplete.

### Coverage and comparison

Coverage is complete only when every evaluated candidate resolves to true or false, every policy control is resolved and no unmodelled mechanism is declared. "Complete" means complete for the declared synthetic model, not for an AWS account.

A finding's identity is `(entry principal, protected target, impact)`, so array order and labels never change it. Added, removed and unchanged are computed from those identities. When either snapshot is incomplete every label is provisional, and a change that involves an unresolved side is shown as inconclusive. An unchanged finding whose witness differs is flagged "evidence changed". Every finding is High severity, whatever its comparison status. This is a demo rubric, not CVSS. Access to unprotected objects appears only as an informational expected-access check.

### Fix simulation

Candidates are grants that the baseline declares false and the proposal turns true under the same fact ID, and that lie on a route to a proposal finding. Scenario assumptions are excluded. Each candidate is set back to `false` on a copy of the proposal; the record is kept, because deleting it would make it unknown. The whole analysis is then recomputed. A candidate is **Verified in this model** only when the finding disappears and coverage stays complete.

Complete candidates rank by fewest failing expected-access checks, then most findings removed, then fact ID, and any collateral change is shown. At most 25 candidates are simulated per comparison. A single-revocation test does not find a minimum cut or prove that real workflows keep working.

### AI explanation boundaries

- The evidence packet replaces every node, fact, check and fix with an opaque alias (`P1`, `F1`, `X1`...). No label or uploaded ID reaches the prompt.
- Converse is called with no tools, `maxTokens` 700, temperature 0.2, one attempt and a 20-second timeout. The call runs only when the button is pressed.
- The reply must be exactly `{finding_id, summary, evidence_ids, fix_candidate_id, limitations}`. Every cited ID and every alias in the prose must exist in the packet, and length limits apply. Anything else is discarded.
- Refusals, timeouts, credential errors and rejected replies show "AI explanation unavailable" with the reason, above the deterministic template summary. Engine results never change.
- Successful replies are cached per analysis, finding, fix, model and prompt version, and a cached reply is labelled. A reply produced for different inputs is never shown.
- Model text is escaped before rendering. Each alias in a reply is shown as the name it stands for, in a tag set apart from the prose, so an uploaded label can never read as the model's own words; facts, checks and fixes keep their IDs. Identifier checks cannot prove that the prose is true, so review generated claims against the evidence.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ROADMAP -->
## Roadmap

State on 30 September 2026.

- [x] Engine: validation, Rules A and B, comparison and fix simulation. The automated suite passes (`pytest`).
- [x] Streamlit app: two pages styled after the [Close](https://closecrm.webflow.io/) template, an overview at `/` that explains why the check is needed and the live demo at `/demo`. Checked in a browser at desktop and phone widths in every scenario, and by headless `streamlit.testing` tests.
- [x] Hosted site: [attackgraph-ai.vercel.app](https://attackgraph-ai.vercel.app), a static build of the same two pages for the bundled scenarios (see [Hosting](#hosting)). No uploads and no AI calls. The flagship scenario shows the recorded, reviewed Nova Pro reply from run 8 of the AC-9 evidence.
- [x] Bedrock explanation: live on 29 September 2026, Amazon Nova Pro returned 8 validated explanations out of 10 with prompt `explain-v1`, none with an unsupported access or fix claim ([evidence](docs/evidence/ac9-bedrock-review-2026-09-29.md)).
- [x] Pull-request check: `python -m attackgraph` and a GitHub Actions workflow (see [Run it as a pull-request check](#run-it-as-a-pull-request-check)). Covered by `tests/test_cli.py`, and the workflow script was run against local merge commits for new, changed, renamed, deleted and broken snapshots. On GitHub on 30 September 2026 it passed the pull request that added it and failed the demo pull request ([#3](https://github.com/Ducksss/attackgraph-ai/pull/3)) as intended, with an annotation on line 27 of `snapshots/app-prod.json`.
- [x] Brand kit and Devpost submission assets, in [`docs/brand/`](docs/brand/) and [`docs/devpost/`](docs/devpost/).
- [ ] A live AC-9 run of `explain-v2`, which fixes the wording defects found in the first run
- [ ] Demo video
- [ ] Beyond the prototype (not started)
    - [ ] Terraform plans and IAM policies as input, instead of hand-written snapshots
    - [ ] Policy evaluation: SCPs, permissions boundaries, conditions and explicit denies
    - [ ] More rule families, such as `sts:AssumeRole` chains and EC2 instance profiles
    - [ ] Multi-account analysis, and fixes that find the smallest set of revocations

See the [open issues](https://github.com/Ducksss/attackgraph-ai/issues) for known issues and requests.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACCEPTANCE CRITERIA -->
## Acceptance criteria

| ID | Where it is checked |
|---|---|
| AC-1 | `tests/test_rules.py::test_ac1_baseline_proposal_and_repair` |
| AC-2 | `tests/test_rules.py`: each prerequisite false, cross-account, unresolved controls, PassRole alone |
| AC-3 | `tests/test_compare.py` (unknown, unresolved, inconclusive transitions) and `tests/test_validation.py` (field-level errors) |
| AC-4 | `tests/test_rules.py`: every pointer resolves to the supplied record; labels confer no privilege |
| AC-5 | `tests/test_compare.py`: reordering, relabelling, removal, evidence change, severity, informational access |
| AC-6 | `tests/test_rules.py`: alternative routes, no effective single fix, cycles, stable tie-breaks |
| AC-7 | `tests/test_simulate.py`: verified fix, expected access kept, input bytes unchanged, ranking |
| AC-8 | `tests/test_explain.py`: invalid IDs, malformed output, refusal, timeout, errors, cache, stale replies |
| AC-9 | [Run on 29 September](docs/evidence/ac9-bedrock-review-2026-09-29.md) with `explain-v1`: 8 of 10 validated, no unsupported claims, wording defects fixed in `explain-v2`. Re-run `scripts/check_bedrock.py --invoke --repeat 10 --out ac9-review.md` for `explain-v2` and review every claim before recording |
| AC-10 | `tests/test_explain.py` (no uploaded text in the prompt, escaping) and `tests/test_validation.py` (oversized and unsupported files) |
| AC-11 | `tests/test_report.py`, `tests/test_app.py` (both pages), `tests/test_site.py` (hosted build); keyboard pass by hand |
| AC-12 | Manual: fresh clone run, video in a signed-out browser, claims match this README |

Performance, measured on the build laptop against the two-second target: the bundled comparison plus fix simulation takes about 5 ms. A generated 100-node, 300-fact pair compares in about 1.5 s, and each fix simulation on it adds about 0.7 s.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- LIMITATIONS -->
## Limitations

- Only the two rule families above are modelled. There is no Terraform or CloudFormation parsing, IAM policy evaluation, EC2, general AssumeRole, live discovery, multi-account analysis or automatic remediation.
- Policy controls are not evaluated. The fixture declares whether their effect is already reflected in its facts.
- Entry-principal control and workload-code control are scenario assumptions, not findings about any real account.
- Results describe the declared synthetic model. They are not a detection rate on real cloud environments.
- The pull-request check compares the snapshots in the repository. It cannot see an infrastructure change that nobody reflected in them.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- PROJECT LAYOUT -->
## Project layout

```text
app.py                         Streamlit router: overview at /, live demo at /demo
views/overview.py              overview page
views/demo.py                  live demo: scenario switching, uploads, Bedrock, fix simulation
attackgraph/landing.py         overview sections: pipeline diagram, why, how, trust, footer
attackgraph/page.py            demo cards shared by the app and the static build
attackgraph/pullrequest.py     the flagship's pull-request card: the real check on the demo change and its fix
attackgraph/scenarios.py       bundled scenarios
attackgraph/story.py           plain-language view of one finding (path, conditions, changes)
attackgraph/web.py             Close-style CSS and escaped HTML fragments
attackgraph/snapshot.py        records, parsing, validation
attackgraph/snapshot.schema.json
attackgraph/analysis.py        Rule A/B candidates, coverage, witnesses (NetworkX)
attackgraph/compare.py         finding deltas, fact and configuration changes
attackgraph/simulate.py        fix candidates and ranking
attackgraph/explain.py         Bedrock packet, validation, fallback template
attackgraph/report.py          Markdown export
attackgraph/cli.py             command-line check for CI: exit status, report, GitHub annotations
attackgraph/__main__.py        python -m attackgraph
attackgraph/render.py          escaping and Graphviz witness
fixtures/demo/                 baseline, proposed, repaired
fixtures/examples/             unknown fact, unresolved SCP, label injection, invalid files
snapshots/                     the snapshot the pull-request check watches (the demo baseline)
scripts/check_bedrock.py       Bedrock access and AC-9 evidence
scripts/build_site.py          static build of both pages for Vercel
.github/workflows/             permission-check.yml: the pull-request check
site/                          the built site: index.html, demo/, reports/, vercel.json
docs/brand/                    logo, palette, social preview and brand guide
docs/devpost/                  Devpost submission text, thumbnail and gallery
docs/evidence/                 recorded live Bedrock runs and their review
docs/images/                   README screenshots of the hosted build
tests/                         automated suite
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Suggestions and fixes are welcome. For anything bigger than a small fix, open an issue first so the change can be discussed.

1. Fork the project
2. Create a feature branch (`git checkout -b feat/amazing-feature`)
3. Run the suite (`.venv/bin/python -m pytest`). If you change the fixtures, the rules or the UI, rebuild the static site with `.venv/bin/python scripts/build_site.py`, because `tests/test_site.py` fails when the committed build is out of date
4. Commit your changes (`git commit -m "feat: add amazing feature"`)
5. Push the branch (`git push origin feat/amazing-feature`)
6. Open a pull request. The permission check runs on it, and a snapshot change that opens a new path fails the check

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- LICENCE -->
## Licence

Released under the MIT License. See [`LICENSE`](LICENSE) for the full text.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Chai Pin Zheng: [@Ducksss](https://github.com/Ducksss) on GitHub

Project link: [github.com/Ducksss/attackgraph-ai](https://github.com/Ducksss/attackgraph-ai) · Live site: [attackgraph-ai.vercel.app](https://attackgraph-ai.vercel.app)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACKNOWLEDGEMENTS -->
## Acknowledgements

* [Best-README-Template](https://github.com/othneildrew/Best-README-Template), the structure of this README
* [Close](https://closecrm.webflow.io/) Webflow template, the visual style of the app and the hosted site
* [Amazon Bedrock](https://aws.amazon.com/bedrock/) and [Amazon Nova](https://aws.amazon.com/ai/generative-ai/nova/), the explanations
* [NetworkX](https://networkx.org/), [jsonschema](https://python-jsonschema.readthedocs.io/) and [Streamlit](https://streamlit.io/), the engine and the app
* [Inter](https://rsms.me/inter/), [JetBrains Mono](https://www.jetbrains.com/lp/mono/) and [Material Symbols](https://fonts.google.com/icons), the type and icons
* [Shields.io](https://shields.io/), the badges

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[demo-shield]: https://img.shields.io/badge/live_demo-attackgraph--ai.vercel.app-6366f1?style=for-the-badge&logo=vercel&logoColor=white
[demo-url]: https://attackgraph-ai.vercel.app/demo
[bedrock-shield]: https://img.shields.io/badge/Amazon_Bedrock-Nova_Pro-232F3E?style=for-the-badge
[bedrock-url]: #amazon-bedrock
[python-shield]: https://img.shields.io/badge/python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white
[python-url]: #prerequisites
[check-shield]: https://img.shields.io/badge/pull--request_check-GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white
[check-url]: .github/workflows/permission-check.yml
[synthetic-shield]: https://img.shields.io/badge/data-synthetic_only-5f5f72?style=for-the-badge
[synthetic-url]: #limitations
[product-screenshot]: docs/images/hero.png
[Python-badge]: https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white
[Python-url]: https://www.python.org/
[Streamlit-badge]: https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white
[Streamlit-url]: https://streamlit.io/
[NetworkX-badge]: https://img.shields.io/badge/NetworkX-2C5AA0?style=for-the-badge
[NetworkX-url]: https://networkx.org/
[Bedrock-badge]: https://img.shields.io/badge/Amazon_Bedrock-232F3E?style=for-the-badge
[Bedrock-url]: https://aws.amazon.com/bedrock/
[Actions-badge]: https://img.shields.io/badge/GitHub_Actions-2088FF?style=for-the-badge&logo=githubactions&logoColor=white
[Actions-url]: https://github.com/features/actions
[Vercel-badge]: https://img.shields.io/badge/Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white
[Vercel-url]: https://vercel.com/
[Pytest-badge]: https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white
[Pytest-url]: https://docs.pytest.org/
