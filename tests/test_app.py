"""AC-11: the Streamlit page, driven headlessly with streamlit.testing."""

import pytest
from helpers import ROOT
from streamlit.testing.v1 import AppTest
from test_explain import FakeClient

from attackgraph.explain import BedrockExplainer, configured_model


@pytest.fixture
def hidden_credentials(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def start(scenario: str | None = None) -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    if scenario:
        at.query_params["scenario"] = scenario
    at.run()
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


def test_first_visit_runs_the_flagship_demo_without_clicks(app):
    page = html(app)
    assert "See what a permission change unlocks" in page
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


def test_bedrock_explanation_is_labelled_and_translated(app):
    model_id, region = configured_model()
    app.session_state["explainer"] = BedrockExplainer(model_id, region, client=FakeClient())
    click(app, "Explain with Amazon Bedrock")
    markdown = texts(app.markdown).replace("\\", "")  # compare the rendered text, not the Markdown escapes
    assert "AI explanation" in markdown and "req-123" in markdown
    assert "f-ci-pass-deploy-admin" in markdown


def test_bedrock_failure_keeps_results_and_shows_the_deterministic_summary(app):
    click(app, "Explain with Amazon Bedrock")
    assert "AI explanation unavailable" in texts(app.warning)
    assert "Deterministic summary, not AI-generated" in texts(app.markdown)
    assert "1 new path to a protected role" in html(app)


def test_simulated_fix_closes_the_path_and_reset_restores_it(app):
    click(app, "Simulate the fix")
    page = html(app)
    assert "Verified in this model" in page and ">Revoked</span>" in page
    assert "after simulated fix 0" in page and "1 → 0" in page
    click(app, "Reset simulation")
    assert ">Revoked</span>" not in html(app)


def test_start_over_clears_simulations_and_returns_to_the_flagship_demo(app):
    click(app, "Simulate the fix")
    assert ">Revoked</span>" in html(app)
    click(app, "Start over")
    page = html(app)
    assert "1 new path to a protected role" in page and ">Revoked</span>" not in page
