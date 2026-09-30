"""Frozen oracle: the analysis engine as it was before the Rule B performance work.

Each *_v1 module is a verbatim copy of the attackgraph module of the same name
at commit a222929; only the imports differ, so that the copies use each other
and the unchanged parsing (attackgraph.snapshot) and rendering helpers.
tests/test_differential.py runs this engine beside the live one and requires
identical results. Never edit these files: an oracle that is "fixed" proves
nothing.
"""
