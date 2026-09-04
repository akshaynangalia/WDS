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


def test_matches_plant_underscore_line_convention():
    # #12: the client's current, preferred Calendar convention -- the column
    # header copied verbatim from the monthly plan's own "Plant_Line" column
    # (e.g. "Induri_Induri ML"), not the older "Plant - Line" spacing.
    calendar_df = pd.DataFrame([
        {"Key1": "Jul-26", "Key2": "Jul-26|W1", "Allocated Days - Previous Month": 0,
         "Allocated Days - Current Month": 7, "Induri_Induri ML": 24},
        {"Key1": "Jul-26", "Key2": "Jul-26|W2", "Induri_Induri ML": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W3", "Induri_Induri ML": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W4", "Induri_Induri ML": 0},
    ])
    caps, messages = capacity.build(calendar_df, "Induri", "Induri ML", "Jul-26", 7)  # month 7 -> not a five-week month
    assert caps.wk1 == round(24 * 7 - 24, 1)
    assert caps.wk2 == capacity.FULL_WEEK_HOURS
    assert not messages  # exact "Plant_Line" match -- no fallback, no fuzzy-match note either


def test_matches_line_name_alone_when_no_plant_prefix_present():
    # A Calendar column that carries just the line name, with no plant prefix
    # at all, is still accepted -- but only because it's the unique such
    # column on the sheet.
    calendar_df = pd.DataFrame([
        {"Key1": "Jul-26", "Key2": "Jul-26|W1", "Allocated Days - Previous Month": 0,
         "Allocated Days - Current Month": 7, "Shell": 48},
        {"Key1": "Jul-26", "Key2": "Jul-26|W2", "Shell": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W3", "Shell": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W4", "Shell": 0},
    ])
    caps, messages = capacity.build(calendar_df, "Induri", "Shell", "Jul-26", 7)
    assert caps.wk1 == round(24 * 7 - 48, 1)
    assert messages and "line name alone" in messages[0]


def test_blank_downtime_cell_means_zero_downtime_not_unlimited_capacity():
    # A blank cell in a matched downtime column means "nothing recorded" --
    # i.e. 0 downtime, a normal full week -- NOT the unbounded capacity that
    # `value or 0` would silently produce for a NaN cell (NaN is truthy, so
    # `nan or 0` evaluates to `nan`, and `min(needed, nan)` always returns
    # `needed`, acting as an infinite week downstream in allocation.py).
    blank_col = pd.DataFrame([
        {"Key1": "Jul-26", "Key2": "Jul-26|W1", "Allocated Days - Previous Month": 0,
         "Allocated Days - Current Month": 7, "P_L": float("nan")},
        {"Key1": "Jul-26", "Key2": "Jul-26|W2", "P_L": float("nan")},
        {"Key1": "Jul-26", "Key2": "Jul-26|W3", "P_L": float("nan")},
        {"Key1": "Jul-26", "Key2": "Jul-26|W4", "P_L": float("nan")},
    ])
    explicit_zero_col = pd.DataFrame([
        {"Key1": "Jul-26", "Key2": "Jul-26|W1", "Allocated Days - Previous Month": 0,
         "Allocated Days - Current Month": 7, "P_L": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W2", "P_L": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W3", "P_L": 0},
        {"Key1": "Jul-26", "Key2": "Jul-26|W4", "P_L": 0},
    ])
    caps_blank, messages_blank = capacity.build(blank_col, "P", "L", "Jul-26", 7)
    caps_zero, _ = capacity.build(explicit_zero_col, "P", "L", "Jul-26", 7)

    assert caps_blank.wk1 == caps_zero.wk1 == round(24 * 7, 1)
    assert caps_blank.wk2 == caps_zero.wk2 == capacity.FULL_WEEK_HOURS
    assert not messages_blank  # column matched fine -- a blank value isn't a fallback case


def test_blank_allocated_days_cell_defaults_like_a_missing_column():
    # Same NaN-truthiness trap for "Allocated Days" cells: a blank one must
    # fall back to its documented default (0 previous-month days, 7
    # current-month days), not silently become NaN.
    calendar_df = pd.DataFrame([
        {"Key1": "Jul-26", "Key2": "Jul-26|W1",
         "Allocated Days - Previous Month": float("nan"),
         "Allocated Days - Current Month": float("nan"), "P_L": 0},
    ])
    caps, _ = capacity.build(calendar_df, "P", "L", "Jul-26", 7)
    assert caps.wk1a == 0.0
    assert caps.wk1 == round(24 * 7, 1)


def test_no_matching_column_falls_back_loudly_and_names_what_it_searched():
    # A genuine miss (client hasn't added this line to the Calendar sheet at
    # all) must fall back to full-week capacity, but say exactly what it
    # looked for -- never a silent guess.
    calendar_df = pd.DataFrame([
        {"Key1": "Jun-26", "Key2": "Jun-26|W1", "Allocated Days - Previous Month": 0,
         "Allocated Days - Current Month": 7, "Induri_Induri ML": 24},
    ])
    caps, messages = capacity.build(calendar_df, "Malanpur", "Malanpur ML", "Jun-26", 6)
    assert caps.wk1 == capacity.FULL_WEEK_HOURS
    assert len(messages) == 1  # one loud message, not one per week
    assert "Malanpur/Malanpur ML" in messages[0]
    assert "Malanpur_Malanpur ML" in messages[0]  # names the exact column it tried
    assert "Induri_Induri ML" in messages[0]      # and what the sheet actually has
