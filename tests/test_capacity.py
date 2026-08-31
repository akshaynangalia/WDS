from __future__ import annotations

import pandas as pd

from engine import capacity


def test_no_calendar_gives_full_week_defaults():
    caps, messages = capacity.build(None, "PlantX", "Line1", "Jul-26", 7)
    assert caps.wk1a == 0.0
    assert caps.wk1 == capacity.FULL_WEEK_HOURS
    assert caps.wk2 == capacity.FULL_WEEK_HOURS
    assert caps.wk5 is None  # month 7 is not a five-week month
    assert messages  # fallback should be logged


def test_five_week_month_rule():
    # month_num % 3 == 0 -> five-week month (e.g. March, June, September, December)
    caps_five, _ = capacity.build(None, "PlantX", "Line1", "Jun-26", 6)
    caps_four, _ = capacity.build(None, "PlantX", "Line1", "Jul-26", 7)
    assert caps_five.wk5 == capacity.FULL_WEEK_HOURS
    assert caps_four.wk5 is None


def test_w1a_w1_split_from_calendar():
    calendar_df = pd.DataFrame([
        {"Key1": "Jul-26", "Key2": "Jul-26|W1", "Allocated Days - Previous Month": 3,
         "Allocated Days - Current Month": 4, "PlantX - Line1": 24},
        {"Key1": "Jul-26", "Key2": "Jul-26|W2", "PlantX - Line1": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W3", "PlantX - Line1": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W4", "PlantX - Line1": 0},
    ])
    caps, messages = capacity.build(calendar_df, "PlantX", "Line1", "Jul-26", 7)  # month 7 -> not a five-week month
    # 24h total downtime in the W1 row, split proportionally 3:4 across prev/curr days
    assert caps.wk1a == round(24 * 3 - (3 / 7) * 24, 1)
    assert caps.wk1 == round(24 * 4 - (4 / 7) * 24, 1)
    assert caps.wk2 == capacity.FULL_WEEK_HOURS
    assert not messages  # calendar fully present, not a five-week month -- no fallback should fire
