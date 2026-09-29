"""AC-11: the Streamlit workflow, driven headlessly with streamlit.testing."""

import pytest
from helpers import ROOT
from streamlit.testing.v1 import AppTest
from test_explain import FakeClient

from attackgraph.explain import BedrockExplainer, configured_model


@pytest.fixture
def app(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception
    return at


def texts(elements) -> str:
    return " ".join(str(e.value) for e in elements)


def load_and_compare(at: AppTest, scenario: str = "passrole") -> AppTest:
    at.selectbox(key="scenario").set_value(scenario).run()
    click(at, "Load demo")
    return click(at, "Compare changes")


def test_first_run_state_explains_what_to_do(app):
    assert "Nothing loaded yet" in texts(app.info)


def test_demo_flow_compare_inspect_explain_simulate(app):
    load_and_compare(app)
    assert "1 new high-risk finding in the proposal." in texts(app.error)
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Baseline high-risk"] == "0" and metrics["Proposed high-risk"] == "1"
    markdown = texts(app.markdown)
    assert "f-ci-pass-deploy-admin" in markdown and "changed false → true" in markdown

    # AI explanation with a fake client: generated, labelled and translated to real IDs.
    model_id, region = configured_model()
    app.session_state["explainer"] = BedrockExplainer(model_id, region, client=FakeClient())
    click(app, "Explain with Amazon Bedrock")
    markdown = texts(app.markdown)
    assert "AI explanation: Amazon Bedrock" in markdown and "req-123" in markdown

    click(app, "Simulate fix")
    assert "Verified in this model" in texts(app.success)
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Simulated fix high-risk"] == "0"
    click(app, "Reset simulation")
    assert {m.label: m.value for m in app.metric}["Simulated fix high-risk"] == "-"


def test_ai_failure_keeps_results_and_shows_template(app):
    load_and_compare(app)
    click(app, "Explain with Amazon Bedrock")
    assert "AI explanation unavailable" in texts(app.warning)
    assert "Template summary: deterministic, not AI-generated" in texts(app.markdown)
    assert "1 new high-risk finding in the proposal." in texts(app.error)


def test_incomplete_scenario_is_never_safe(app):
    load_and_compare(app, "unknown")
    assert "Analysis incomplete." in texts(app.warning)
    assert not any("No new modelled high-risk access" in str(s.value) for s in app.success)


def test_invalid_scenario_blocks_analysis(app):
    load_and_compare(app, "invalid")
    errors = texts(app.error)
    assert "3 validation errors." in errors and "Analysis not run" in errors
    assert not app.metric


def test_reset_clears_everything(app):
    load_and_compare(app)
    click(app, "Reset app")
    assert "Nothing loaded yet" in texts(app.info)
    assert not app.metric
