"""AC-11: the Streamlit app's two pages, driven headlessly with streamlit.testing."""

import json

import pytest
from helpers import ROOT
from streamlit.testing.v1 import AppTest
from test_explain import AC9_RUNS, FakeClient

from attackgraph.explain import BedrockExplainer, configured_model


@pytest.fixture
def hidden_credentials(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def start(scenario: str | None = None, page: str | None = "views/demo.py") -> AppTest:
    """Open the app at / and, unless page is None, follow the link to that page."""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    if scenario:
        at.query_params["scenario"] = scenario
    at.run()
    assert not at.exception, at.exception
    if page:
        at.switch_page(page).run()
        assert not at.exception, at.exception
    return at


@pytest.fixture
def app(hidden_credentials):
    return start()


def html(at: AppTest) -> str:
    return " ".join(str(e.proto.body) for e in at.get("html"))


def texts(elements) -> str:
    return " ".join(str(e.value) for e in elements)


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception
    return at


def test_overview_explains_the_problem_and_links_to_the_demo(hidden_credentials):
    page = html(start(page=None))
    assert "Ship permission changes without shipping admin access." in page
    assert 'href="/demo"' in page and "Permission reviews miss paths," in page
    assert "Recorded Nova Pro reply" in page and "1 new path" not in page


def test_first_visit_runs_the_flagship_demo_without_clicks(app):
    page = html(app)
    assert "Watch one permission" in page and "Ship permission changes" not in page
    assert "1 new path to a protected role" in page
    assert ">New</span><div class=\"ag-hop-text\">can pass Deployment admin role to</div>" in page
    assert "Why the route works" in page and "7 of 7 hold" in page


def test_scenarios_switch_without_a_compare_step(app):
    app.segmented_control(key="scenario").set_value("unknown").run()
    page = html(app)
    assert "Analysis incomplete" in page and "0 confirmed" in page and ">Unknown</span>" in page
    assert "1 new path" not in page

    app.segmented_control(key="scenario").set_value("invalid").run()
    page = html(app)
    assert "These files can&#x27;t be analysed yet" in page or "These files can't be analysed yet" in page
    assert "3 field errors found" in page and "r-missing-role" in page

    app.segmented_control(key="scenario").set_value("repair").run()
    page = html(app)
    assert "The change closes 1 path and opens none" in page and ">Removed</span>" in page

    app.segmented_control(key="scenario").set_value("upload").run()
    assert "Add both snapshot files" in html(app)


def test_deep_link_opens_a_scenario(hidden_credentials):
    assert "Analysis incomplete" in html(start("unknown"))


def test_bedrock_explanation_is_labelled_and_shows_names(app):
    model_id, region = configured_model()
    app.session_state["explainer"] = BedrockExplainer(model_id, region, client=FakeClient())
    click(app, "Explain with Amazon Bedrock")
    page = html(app)
    assert '<span class="ag-badge green">AI explanation</span>' in page
    assert 'title="r-deploy-admin">' in page and '<span class="ag-mono">f-ci-pass-deploy-admin</span>' in page
    assert "<dt>Request</dt><dd>req-123</dd>" in page


def test_bedrock_failure_keeps_results_and_shows_the_deterministic_summary(app):
    click(app, "Explain with Amazon Bedrock")
    assert "AI explanation unavailable" in texts(app.warning)
    assert "Deterministic summary, not AI-generated" in texts(app.markdown)
    assert "1 new path to a protected role" in html(app)


def test_reply_that_overstates_the_fix_is_rejected_with_its_reason(app):
    run10 = next(run for run in AC9_RUNS if run["run"] == 10)  # "without affecting other access relationships"
    model_id, region = configured_model()
    app.session_state["explainer"] = BedrockExplainer(model_id, region, client=FakeClient(reply=json.dumps(run10["reply"])))
    click(app, "Explain with Amazon Bedrock")
    warning = texts(app.warning)
    assert "AI explanation unavailable** (reply rejected)" in warning and "other access relationships" in warning
    assert "Deterministic summary, not AI-generated" in texts(app.markdown)
    assert '<span class="ag-badge green">AI explanation</span>' not in html(app)


def test_simulated_fix_closes_the_path_and_reset_restores_it(app):
    click(app, "Simulate the fix")
    page = html(app)
    assert "Verified in this model" in page and ">Revoked</span>" in page
    assert "after simulated fix 0" in page and "1 → 0" in page
    fix_card = page.split('<div class="ag-fix-result">', 1)[1]
    assert "The route after the fix" in fix_card and ">Revoked</span>" in fix_card  # cause and effect in one view
    click(app, "Reset simulation")
    assert ">Revoked</span>" not in html(app)


def test_the_pull_request_check_fails_until_the_fix_is_applied(app):
    page = html(app)
    assert page.index("The pull request") < page.index("1 new path to a protected role")
    assert "Check failed" in page and "New path to a protected role" in page and "exit status 1" in page
    click(app, "Apply the suggested fix")
    page = html(app)
    assert "Check passed" in page and "exit status 0" in page and ">Revoked</span>" in page  # the whole page follows
    click(app, "Undo the fix")
    assert "Check failed" in html(app) and ">Revoked</span>" not in html(app)
    app.segmented_control(key="scenario").set_value("repair").run()
    assert "The pull request" not in html(app)


def test_start_over_clears_simulations_and_returns_to_the_flagship_demo(app):
    click(app, "Simulate the fix")
    assert ">Revoked</span>" in html(app)
    click(app, "Start over")
    page = html(app)
    assert "1 new path to a protected role" in page and ">Revoked</span>" not in page
