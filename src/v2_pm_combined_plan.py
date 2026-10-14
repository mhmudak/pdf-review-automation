"""Source-verified PM change integration.

Uses existing source, reply and cell planners. No Google I/O.
Supports restart-safe comment changes and single new replies.
New ROOTs and unsupported changes fail closed.
"""

from v2_pm_source_delta import plan_verified_source_delta
from v2_pm_reply_delta import plan_reply_changes
from v2_pm_cell_plan import plan_pm_comment_cells
from v2_pm_reply_cell_plan import plan_pm_reply_cells


def plan_verified_pm_cells(
    sheet_values,
    previous_projection,
    current_projection,
):
    if not sheet_values:
        raise ValueError("Empty PM sheet")

    previous = {}
    for row in previous_projection:
        key = str(row.get("Root Entry ID") or "").strip()
        if not key or key in previous:
            raise ValueError("Invalid previous ROOT identity")
        previous[key] = row

    pm = []
    seen = set()
    for raw in sheet_values[1:]:
        row = list(raw) + [""] * (22 - len(raw))
        if len(row) != 22:
            raise ValueError("Unexpected PM width")
        key = str(row[14]).strip()
        if not key or key in seen:
            raise ValueError("Invalid PM ROOT identity")
        seen.add(key)
        pm.append({
            "Root Entry ID": key,
            "Comment": row[4],
            "Reply 1": row[5],
            "Reply 2": row[6],
            "Reply 3": row[7],
            "Reply Entry IDs": row[21],
        })

    # Authorize source changes against the previously verified
    # source, not against a potentially half-written destination.
    # Actual PM values are checked by the cell planners below.
    policy_pm = []
    for row in pm:
        key = row["Root Entry ID"]
        old = previous.get(key)
        if old is None:
            policy_pm.append(row)
        else:
            policy_pm.append(dict(old))

    source = plan_verified_source_delta(
        policy_pm, previous_projection, current_projection
    )

    comments = plan_pm_comment_cells(
        sheet_values,
        source["verified_cell_update_candidates"],
    )

    # Generate reply candidates strictly from source versions.
    # The actual PM IDs/text are checked independently below.
    reply_source = plan_reply_changes(
        previous_projection,
        previous_projection,
        current_projection,
    )

    reply_cells = plan_pm_reply_cells(
        sheet_values,
        previous_projection,
        reply_source["new_reply_cell_candidates"],
    )

    blocked_roots = {
        str(item["root_entry_id"])
        for item in reply_source["held_for_review"]
    }

    accepted_reply_roots = {
        str(item["root_entry_id"])
        for item in reply_source["new_reply_cell_candidates"]
    } - blocked_roots

    blockers = []

    for item in source["held_for_review"]:
        if (
            item["reason"] == "REPLY_CHANGE_NEEDS_ID_AWARE_PLANNER"
            and str(item["id"]) in accepted_reply_roots
        ):
            continue
        blockers.append(item)

    blockers.extend(reply_source["held_for_review"])
    blockers.extend(comments["conflicts"])
    blockers.extend(reply_cells["conflicts"])

    if source["new_root_candidates"]:
        blockers.append({
            "reason": "NEW_ROOT_INSERTION_NOT_CONNECTED",
            "count": len(source["new_root_candidates"]),
        })

    if source["historical_root_ids"]:
        blockers.append({
            "reason": "HISTORICAL_ROOT_REQUIRES_REVIEW",
            "count": len(source["historical_root_ids"]),
        })

    candidates = (
        comments["cell_update_candidates"]
        + reply_cells["cell_update_candidates"]
    )

    cells = [item["cell"] for item in candidates]
    if len(cells) != len(set(cells)):
        raise ValueError("Duplicate planned PM cell")

    if blockers:
        candidates = []

    return {
        "mode": "DRY_RUN",
        "cell_update_candidates": candidates,
        "already_applied": (
            comments["already_applied_ids"]
            + reply_cells["already_applied"]
        ),
        "blockers": blockers,
        "new_root_count": len(source["new_root_candidates"]),
        "google_write_operations": [],
    }
