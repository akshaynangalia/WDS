"""
Phase 8 gate: every component id referenced by a callback (as Output, Input,
or State) must exist in the actual rendered layout. This is precisely the
defect visible in both reference screenshots ("ID not found in layout" x2 in
Dash's debug panel) -- Development Planning Document, Risk Register item 5.
"""
from __future__ import annotations

from dash import Dash

from app.callbacks import register_callbacks
from app.layout import make_layout


def _collect_layout_ids(component) -> set[str]:
    ids = set()
    comp_id = getattr(component, "id", None)
    if comp_id:
        ids.add(comp_id)
    children = getattr(component, "children", None)
    if children is None:
        return ids
    if isinstance(children, (list, tuple)):
        for child in children:
            ids |= _collect_layout_ids(child)
    else:
        ids |= _collect_layout_ids(children)
    return ids


def test_every_callback_id_exists_in_the_layout():
    app = Dash(__name__)
    app.layout = make_layout()
    register_callbacks(app)

    layout_ids = _collect_layout_ids(app.layout)

    missing = []
    for callback in app.callback_map.values():
        for item in callback.get("inputs", []) + callback.get("state", []):
            if item["id"] not in layout_ids:
                missing.append(item["id"])
        for output in callback.get("output", []) if isinstance(callback.get("output"), list) else [callback.get("output")]:
            pass  # outputs validated via app.callback_map keys below

    for output_key in app.callback_map.keys():
        # output_key looks like "component_id.property" or "..component_id.property...anotherid.prop.."
        for part in output_key.split(".."):
            if "." in part:
                comp_id = part.split(".")[0]
                if comp_id and comp_id not in layout_ids:
                    missing.append(comp_id)

    assert missing == [], f"Callback references id(s) not present in the layout: {sorted(set(missing))}"
