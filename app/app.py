"""
Entry point. Run with: python app/app.py
Serves at http://localhost:8050 -- see README.md.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root on path

import logging

from dash import Dash

from app.callbacks import register_callbacks
from app.layout import make_layout
from orchestration.logging_config import code_version, configure_logging

# Configured at import time (not inside __main__): a WSGI host such as Posit
# Connect imports `server` and never runs the __main__ block. Idempotent.
configure_logging()
logging.getLogger("wds.app").info("APP_START version=%s", code_version())

app = Dash(__name__)
app.title = "Weekly Disaggregation Tool"
app.layout = make_layout()
register_callbacks(app)

server = app.server  # exposed for WSGI-based hosting later (Phase 11)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
