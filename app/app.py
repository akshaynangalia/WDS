"""
Entry point. Run with: python app/app.py
Serves at http://localhost:8050 -- see README.md.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root on path

from dash import Dash

from app.callbacks import register_callbacks
from app.layout import make_layout

app = Dash(__name__)
app.title = "Weekly Disaggregation Tool"
app.layout = make_layout()
register_callbacks(app)

server = app.server  # exposed for WSGI-based hosting later (Phase 11)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
