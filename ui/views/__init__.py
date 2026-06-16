"""ui/views/ — Streamlit render functions for the four T5.8 demo views.

Each module exposes ``render(artifacts, ...)`` and imports ``streamlit`` at module
level. These are imported only when the Streamlit app runs (ui/app.py); the headless
view-model logic lives in ui/artifacts.py and is tested without Streamlit.
"""
