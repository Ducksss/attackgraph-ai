"""AttackGraph AI: the Streamlit app, in the same two pages as the hosted site.

Run with: streamlit run app.py
The overview is at / and the live demo at /demo. Deep link a scenario with
/demo?scenario=passrole|repair|unknown|invalid|upload.
"""

from __future__ import annotations

import streamlit as st

from attackgraph import landing, web

st.set_page_config(page_icon=":material/conversion_path:", layout="wide")
st.html(web.CSS + landing.CSS)
st.navigation(
    [
        st.Page("views/overview.py", title="AttackGraph AI", default=True),
        st.Page("views/demo.py", title="Live demo: AttackGraph AI", url_path="demo"),
    ],
    position="hidden",
).run()
