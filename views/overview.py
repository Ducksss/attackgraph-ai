"""Overview page: why the tool is needed, how it works, and why to trust it."""

from __future__ import annotations

import streamlit as st

from attackgraph import landing
from attackgraph.pipeline import PipelineResult
from attackgraph.scenarios import run_scenario


@st.cache_resource
def flagship() -> PipelineResult:
    return run_scenario("passrole")


st.html(landing.page(flagship(), hosted=False))
