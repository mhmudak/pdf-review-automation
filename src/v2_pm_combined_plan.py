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

    # Verify actual PM reply identities independently of policy_pm.
    # policy_pm represents source state and must never conceal
    # an unauthorized change to the destination's reply IDs.
    from v2_pm_reply_delta import reply_ids

    actual_reply_conflicts = []
    current_lookup = {
        str(row["Root Entry ID"]): row
        for row in current_projection
    }

    for pm_row in pm:
        root_id = pm_row["Root Entry ID"]
        before = previous.get(root_id)
        if before is None:
            continue

        actual_ids = reply_ids(pm_row)
        previous_ids = reply_ids(before)
        current_row = current_lookup.get(root_id)
        current_ids = (
            reply_ids(current_row)
            if current_row is not None
            else []
        )

        # During an interrupted verified reply append, the PM
        # may already contain the authorized current ID sequence.
        # No other divergence is permitted.
        authorized_append = (
            len(current_ids) > len(previous_ids)
            and current_ids[:len(previous_ids)] == previous_ids
        )

        valid = (
            actual_ids == previous_ids
            or (
                authorized_append
                and actual_ids == current_ids
            )
        )

        if not valid:
            actual_reply_conflicts.append({
                "root_entry_id": root_id,
                "reason": "PM_REPLY_ID_BASELINE_CONFLICT",
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

    blockers = list(actual_reply_conflicts)

    current_by_root = {
        str(row["Root Entry ID"]): row
        for row in current_projection
    }

    # Historical reply presentation differences are not new
    # PDF changes. Only suppress the general source warning
    # when the source reply sequence itself is unchanged and
    # PM still retains the previously verified reply IDs.
    from v2_pm_reply_delta import reply_ids

    pm_by_root = {
        row["Root Entry ID"]: row
        for row in pm
    }

    def source_replies_unchanged(root_id):
        before = previous.get(root_id)
        after = current_by_root.get(root_id)
        destination = pm_by_root.get(root_id)

        if not before or not after or not destination:
            return False

        old_ids = reply_ids(before)
        new_ids = reply_ids(after)
        pm_ids = reply_ids(destination)

        if old_ids != new_ids or pm_ids != old_ids:
            return False

        for position in range(1, len(old_ids) + 1):
            field = f"Reply {position}"
            if (
                str(before.get(field) or "").strip()
                != str(after.get(field) or "").strip()
            ):
                return False

        return True

    for item in source["held_for_review"]:
        root_id = str(item.get("id") or "")

        if item.get("reason") == "REPLY_CHANGE_NEEDS_ID_AWARE_PLANNER":
            if root_id in accepted_reply_roots:
                continue

            if source_replies_unchanged(root_id):
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
