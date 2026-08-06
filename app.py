"""Combined entrypoint: Setup and Dashboard as pages of one Streamlit app,
sharing session state -- so a successful deploy on the Setup page can hand
the resulting project/dataset/table straight to the Dashboard page with one
click, instead of the user re-typing them.

Run with: streamlit run app.py

Each page also still runs standalone (`streamlit run setup/streamlit_app.py`
or `streamlit run dashboard/app.py`) for users who only want one of the two.
"""

import streamlit as st

setup_page = st.Page("setup/streamlit_app.py", title="Setup", icon="⚙️", default=True)
dashboard_page = st.Page("dashboard/app.py", title="Dashboard", icon="📈")

navigation = st.navigation([setup_page, dashboard_page])
navigation.run()
