"""Cross-functional Traceability and Discrepancy Matrix persistence and calculations.

Connects live PAAG Work Elements, Quality Requirement Assignments, PFMEA Entries & Controls,
Control Plan Items, and Equipment Placements & Process Links.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

import pandas as pd

from utils import db_core as store
from utils.control_plan_store import _live_projection_conn, _specification
from utils.equipment_store import init_equipment_schema
from utils.pfmea_store import PFMEA_CTQ_CLASSIFICATIONS
from utils.process_store import work_element_op_contexts


CRITICAL_PFMEA_CODES = {
    "S",
    "R",
    "E",
    "P",
    "P-",
    "Q",
    "E-",
    "Safety",
    "Product Safety",
    "Critical Quality",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def cross_functional_traceability_matrix(
    project_id: str,
    scenario_id: str,
) -> dict[str, Any]:
    """Calculate and return full cross-functional traceability matrix and KPI summary."""
    with store.connection() as conn:
        init_equipment_schema(conn)

        # 1. Fetch work elements for this scenario
        work_rows = conn.execute(
            """SELECT id, station, operation, description, sequence
               FROM work_elements
               WHERE project_id=? AND scenario_id=?
               ORDER BY sequence, id""",
            (project_id, scenario_id),
        ).fetchall()

        if not work_rows:
            return {
                "rows": [],
                "summary": {
                    "total_steps": 0,
                    "steps_with_quality": 0,
                    "protected_steps": 0,
                    "critical_gap_steps": 0,
                    "warning_steps": 0,
                    "uncovered_steps": 0,
                    "fully_protected_pct": 100.0,
                    "spec_drift_count": 0,
                    "tooling_gap_count": 0,
                },
                "pitches": [],
            }

        work_ids = [str(r["id"]) for r in work_rows]
        op_contexts = work_element_op_contexts(project_id, scenario_id, work_ids)

        # Sort work_rows according to op_context sort_order
        work_elements = sorted(
            [dict(r) for r in work_rows],
            key=lambda w: (
                int(op_contexts.get(str(w["id"]), {}).get("sort_order", 0)),
                int(w.get("sequence") or 0),
            ),
        )

        # 2. Fetch active Quality Requirement Assignments (unlinked_at = '')
        q_rows = conn.execute(
            """SELECT id, work_element_id, quality_requirement_id, requirement_type,
                      description, unique_identifier, pass_fail, target_value,
                      tolerances, unit, process_operation_snapshot, station_pitch_snapshot
               FROM quality_requirement_assignments
               WHERE project_id=? AND scenario_id=? AND unlinked_at=''
               ORDER BY created_at, id""",
            (project_id, scenario_id),
        ).fetchall()

        assignments_by_work: dict[str, list[dict[str, Any]]] = {}
        for qr in q_rows:
            q_dict = dict(qr)
            assignments_by_work.setdefault(str(qr["work_element_id"]), []).append(q_dict)

        # 3. Fetch active PFMEA Entries (work_element_id IS NOT NULL)
        pfmea_rows = conn.execute(
            """SELECT id, work_element_id, potential_failure_mode, class_code,
                      process_operation_snapshot, process_pitch_snapshot
               FROM pfmea_entries
               WHERE project_id=? AND scenario_id=? AND work_element_id IS NOT NULL
               ORDER BY created_at, id""",
            (project_id, scenario_id),
        ).fetchall()

        pfmea_by_work: dict[str, list[dict[str, Any]]] = {}
        for pr in pfmea_rows:
            p_dict = dict(pr)
            pfmea_by_work.setdefault(str(pr["work_element_id"]), []).append(p_dict)



        # 4. Fetch Control Plan Items using _live_projection_conn
        cp_items = _live_projection_conn(conn, project_id, scenario_id)
        cp_by_entry_and_assignment: dict[tuple[str, str], dict[str, Any]] = {}
        cp_by_work_and_assignment: dict[tuple[str, str], dict[str, Any]] = {}
        cp_by_entry: dict[str, list[dict[str, Any]]] = {}

        for cp in cp_items:
            eid = str(cp.get("pfmea_entry_id") or "")
            aid = str(cp.get("quality_requirement_assignment_id") or "")
            wid = str(cp.get("work_element_id") or "")

            if eid and aid:
                cp_by_entry_and_assignment[(eid, aid)] = cp
            if wid and aid:
                cp_by_work_and_assignment[(wid, aid)] = cp
            if eid:
                cp_by_entry.setdefault(eid, []).append(cp)

        # 5. Fetch Placed Equipment and Links
        placed_eq_rows = conn.execute(
            """SELECT link.work_element_id, asset.id AS equipment_id, asset.name AS asset_name,
                      asset.manufacturer, asset.model, eqtype.label AS equipment_type,
                      placement.pitch_id, pitch.pitch_name, pitch.pitch_number
               FROM equipment_process_links link
               JOIN equipment_placements placement
                 ON placement.id = link.placement_id
                AND placement.project_id = link.project_id
                AND placement.scenario_id = link.scenario_id
               JOIN equipment_assets asset
                 ON asset.id = placement.equipment_id
                AND asset.project_id = link.project_id
               JOIN equipment_types eqtype
                 ON eqtype.id = asset.equipment_type_id
                AND eqtype.project_id = link.project_id
               LEFT JOIN yamazumi_pitches pitch
                 ON pitch.id = placement.pitch_id
               WHERE link.project_id=? AND link.scenario_id=? AND link.unlinked_at=''
               ORDER BY asset.name, link.id""",
            (project_id, scenario_id),
        ).fetchall()

        placed_by_work: dict[str, list[dict[str, Any]]] = {}
        for r in placed_eq_rows:
            wid = str(r["work_element_id"])
            placed_by_work.setdefault(wid, []).append(dict(r))

        # Torque links to quality requirements
        torque_req_rows = conn.execute(
            """SELECT link.quality_requirement_id, asset.id AS equipment_id, asset.name AS asset_name,
                      asset.manufacturer, asset.model, eqtype.label AS equipment_type,
                      placement.pitch_id, pitch.pitch_name, pitch.pitch_number
               FROM equipment_torque_requirement_links link
               JOIN equipment_assets asset ON asset.id = link.equipment_id
               JOIN equipment_types eqtype ON eqtype.id = asset.equipment_type_id
               LEFT JOIN equipment_placements placement
                 ON placement.equipment_id = asset.id AND placement.scenario_id = ?
               LEFT JOIN yamazumi_pitches pitch ON pitch.id = placement.pitch_id
               WHERE link.project_id=?""",
            (scenario_id, project_id),
        ).fetchall()

        torque_eq_by_req: dict[str, list[dict[str, Any]]] = {}
        for r in torque_req_rows:
            qid = str(r["quality_requirement_id"])
            torque_eq_by_req.setdefault(qid, []).append(dict(r))

        # 6. Build Cross-Functional Traceability Rows
        matrix_rows: list[dict[str, Any]] = []
        pitches_seen: set[str] = set()

        step_statuses: dict[str, str] = {}
        total_spec_drifts = 0
        total_tooling_gaps = 0

        for work in work_elements:
            wid = str(work["id"])
            op_ctx = op_contexts.get(wid, {})
            op_id = _text(op_ctx.get("op_id")) or "Op ID unavailable"
            pitch_number = _text(op_ctx.get("pitch_number"))
            pitch_label = pitch_number or _text(work.get("station")) or "Unassigned"
            pitches_seen.add(pitch_label)
            op_name = _text(op_ctx.get("operation")) or _text(work.get("operation"))
            seq_val = work.get("sequence") or 0

            work_assignments = assignments_by_work.get(wid, [])
            work_pfmea = pfmea_by_work.get(wid, [])
            work_equipment = placed_by_work.get(wid, [])

            row_severities_for_step: list[str] = []

            if work_assignments:
                # One row per assigned quality requirement
                for q_assign in work_assignments:
                    aid = str(q_assign["id"])
                    qid = str(q_assign["quality_requirement_id"])
                    req_type = _text(q_assign.get("requirement_type"))
                    q_uid = _text(q_assign.get("unique_identifier"))
                    q_desc = _text(q_assign.get("description"))
                    pub_spec = _specification(q_assign)
                    is_torque = req_type.casefold() == "torque" or "torque" in q_desc.casefold()

                    chosen_pfmea = work_pfmea[0] if work_pfmea else None
                    has_pfmea_entry = len(work_pfmea) > 0

                    # Find corresponding Control Plan item
                    cp_item = None
                    if chosen_pfmea:
                        cp_item = cp_by_entry_and_assignment.get((str(chosen_pfmea["id"]), aid))
                    if not cp_item:
                        cp_item = cp_by_work_and_assignment.get((wid, aid))

                    # Equipment matching for this requirement
                    matching_eq: list[dict[str, Any]] = []
                    # Check equipment linked to step
                    for eq in work_equipment:
                        eq_type = _text(eq.get("equipment_type"))
                        if is_torque and ("torque" in eq_type.casefold() or "torque" in _text(eq.get("asset_name")).casefold()):
                            matching_eq.append(eq)
                        elif not is_torque:
                            matching_eq.append(eq)

                    # Check equipment linked via torque requirement link
                    if is_torque and qid in torque_eq_by_req:
                        for eq in torque_eq_by_req[qid]:
                            if not any(e["equipment_id"] == eq["equipment_id"] for e in matching_eq):
                                matching_eq.append(eq)

                    has_equipment = len(matching_eq) > 0

                    # Evaluate discrepancies
                    flags: list[dict[str, str]] = []
                    spec_drift = False

                    # Check for PFMEA failure mode coverage
                    if not has_pfmea_entry:
                        flags.append({
                            "code": "MISSING_PFMEA_ENTRY",
                            "severity": "WARNING",
                            "title": "Coverage Gap: No PFMEA Analysis",
                            "message": "Quality requirement assigned to process step, but no PFMEA failure modes analyzed for this step.",
                        })

                    if cp_item is None:
                        flags.append({
                            "code": "MISSING_CONTROL_PLAN",
                            "severity": "CRITICAL",
                            "title": "Coverage Gap: Missing from Control Plan",
                            "message": "Quality requirement has no corresponding characteristic on the Control Plan.",
                        })
                    elif bool(cp_item.get("excluded")):
                        flags.append({
                            "code": "EXCLUDED_FROM_CONTROL_PLAN",
                            "severity": "CRITICAL",
                            "title": "Coverage Gap: Excluded from Control Plan",
                            "message": "Characteristic is marked Excluded on the Control Plan.",
                        })

                    if chosen_pfmea and chosen_pfmea.get("class_code") in CRITICAL_PFMEA_CODES:
                        if cp_item is None or bool(cp_item.get("excluded")):
                            flags.append({
                                "code": "UNMITIGATED_CTQ",
                                "severity": "CRITICAL",
                                "title": "Critical Gap: Unmitigated CTQ",
                                "message": f"Critical classification ({chosen_pfmea['class_code']}) lacks active Control Plan protection.",
                            })

                    # Warning checks
                    if is_torque and not has_equipment:
                        total_tooling_gaps += 1
                        flags.append({
                            "code": "TOOLING_GAP",
                            "severity": "WARNING",
                            "title": "Warning: Missing Torque Tooling",
                            "message": "Torque requirement assigned to step, but no Torque Tool is linked or placed.",
                        })

                    # Check spec drift
                    if cp_item:
                        cp_spec = _text(cp_item.get("specification_requirement"))
                        if cp_spec and pub_spec and cp_spec.strip() != pub_spec.strip():
                            spec_drift = True
                            total_spec_drifts += 1
                            flags.append({
                                "code": "SPEC_DRIFT",
                                "severity": "WARNING",
                                "title": "Warning: Specification Drift",
                                "message": f"Control Plan spec '{cp_spec}' differs from published Quality spec '{pub_spec}'.",
                            })

                        if bool(cp_item.get("source_review_required")):
                            flags.append({
                                "code": "SOURCE_REVIEW_REQUIRED",
                                "severity": "WARNING",
                                "title": "Warning: Source Review Required",
                                "message": "Control Plan item flagged for source review due to upstream change.",
                            })

                    # Check equipment pitch mismatch
                    for eq in matching_eq:
                        eq_pitch = _text(eq.get("pitch_number")) or _text(eq.get("pitch_name"))
                        if eq_pitch and pitch_number and eq_pitch != pitch_number:
                            flags.append({
                                "code": "PITCH_MISMATCH",
                                "severity": "WARNING",
                                "title": "Warning: Pitch Mismatch",
                                "message": f"Tool '{eq['asset_name']}' placed at {eq_pitch}, but step is at {pitch_number}.",
                            })

                    # Calculate status
                    has_critical = any(f["severity"] == "CRITICAL" for f in flags)
                    has_warning = any(f["severity"] == "WARNING" for f in flags)

                    if has_critical:
                        status = "CRITICAL_GAP"
                        status_label = "🔴 Critical Gap"
                    elif has_warning:
                        status = "WARNING"
                        status_label = "🟡 Warning"
                    else:
                        status = "PROTECTED"
                        status_label = "🟢 Protected"

                    row_severities_for_step.append(status)

                    eq_display = (
                        ", ".join(
                            f"{e['asset_name']} [{e.get('equipment_type') or 'Tool'}]"
                            for e in matching_eq
                        )
                        if matching_eq
                        else ("⚠️ Missing Equipment" if is_torque else "—")
                    )

                    matrix_rows.append({
                        "work_element_id": wid,
                        "op_id": op_id,
                        "pitch": pitch_label,
                        "sequence": seq_val,
                        "operation": op_name,
                        "stage_type": "Quality Requirement",
                        "quality_assignment_id": aid,
                        "quality_requirement_id": qid,
                        "quality_uid": q_uid,
                        "quality_type": req_type,
                        "quality_description": q_desc,
                        "published_spec": pub_spec,
                        "pfmea_entry_id": str(chosen_pfmea["id"]) if chosen_pfmea else "",
                        "pfmea_class_code": str(chosen_pfmea["class_code"]) if chosen_pfmea else "",
                        "pfmea_failure_mode": str(chosen_pfmea["potential_failure_mode"]) if chosen_pfmea else "—",
                        "has_pfmea_entry": has_pfmea_entry,
                        "control_plan_item_id": str(cp_item.get("id") or "") if cp_item else "",
                        "control_plan_pr_number": _text(cp_item.get("pr_number")) if cp_item else "",
                        "control_plan_spec": _text(cp_item.get("specification_requirement")) if cp_item else "",
                        "control_plan_method": _text(cp_item.get("control_method")) if cp_item else "",
                        "control_plan_placement": _text(cp_item.get("characteristic_placement")) if cp_item else "",
                        "control_plan_excluded": bool(cp_item.get("excluded")) if cp_item else False,
                        "control_plan_review_required": bool(cp_item.get("source_review_required")) if cp_item else False,
                        "equipment_names": [e["asset_name"] for e in matching_eq],
                        "equipment_display": eq_display,
                        "has_equipment": has_equipment,
                        "status": status,
                        "status_label": status_label,
                        "spec_drift": spec_drift,
                        "discrepancies": flags,
                        "discrepancy_count": len(flags),
                        "discrepancy_summary": "; ".join(f["title"] for f in flags) if flags else "All checks pass",
                    })

            elif work_pfmea:
                # Step has PFMEA entries but no assigned drawing quality requirements
                for p_entry in work_pfmea:
                    peid = str(p_entry["id"])
                    class_code = _text(p_entry.get("class_code"))
                    fmode = _text(p_entry.get("potential_failure_mode"))
                    is_ctq = class_code in CRITICAL_PFMEA_CODES

                    # Check control plan items for this entry
                    entry_cps = cp_by_entry.get(peid, [])
                    cp_item = entry_cps[0] if entry_cps else None

                    flags = []
                    if is_ctq:
                        if cp_item is None or bool(cp_item.get("excluded")):
                            flags.append({
                                "code": "UNMITIGATED_CTQ",
                                "severity": "CRITICAL",
                                "title": "Critical Gap: Unmitigated CTQ",
                                "message": f"Critical failure mode ({class_code}) lacks active Control Plan characteristic.",
                            })
                    else:
                        if cp_item is None or bool(cp_item.get("excluded")):
                            flags.append({
                                "code": "UNCONTROLLED_FAILURE_MODE",
                                "severity": "WARNING",
                                "title": "Warning: Uncontrolled Failure Mode",
                                "message": "Failure mode has no active characteristic in Control Plan.",
                            })

                    # Tooling check if control method mentions torque/vision
                    eq_display = (
                        ", ".join(
                            f"{e['asset_name']} [{e.get('equipment_type') or 'Tool'}]"
                            for e in work_equipment
                        )
                        if work_equipment
                        else "—"
                    )

                    has_critical = any(f["severity"] == "CRITICAL" for f in flags)
                    has_warning = any(f["severity"] == "WARNING" for f in flags)

                    if has_critical:
                        status = "CRITICAL_GAP"
                        status_label = "🔴 Critical Gap"
                    elif has_warning:
                        status = "WARNING"
                        status_label = "🟡 Warning"
                    else:
                        status = "PROTECTED"
                        status_label = "🟢 Protected"

                    row_severities_for_step.append(status)

                    matrix_rows.append({
                        "work_element_id": wid,
                        "op_id": op_id,
                        "pitch": pitch_label,
                        "sequence": seq_val,
                        "operation": op_name,
                        "stage_type": "PFMEA Failure Mode",
                        "quality_assignment_id": "",
                        "quality_requirement_id": "",
                        "quality_uid": "—",
                        "quality_type": "—",
                        "quality_description": "—",
                        "published_spec": "—",
                        "pfmea_entry_id": peid,
                        "pfmea_class_code": class_code,
                        "pfmea_failure_mode": fmode,
                        "has_pfmea_entry": True,
                        "control_plan_item_id": str(cp_item.get("id") or "") if cp_item else "",
                        "control_plan_pr_number": _text(cp_item.get("pr_number")) if cp_item else "",
                        "control_plan_spec": _text(cp_item.get("specification_requirement")) if cp_item else "",
                        "control_plan_method": _text(cp_item.get("control_method")) if cp_item else "",
                        "control_plan_placement": _text(cp_item.get("characteristic_placement")) if cp_item else "",
                        "control_plan_excluded": bool(cp_item.get("excluded")) if cp_item else False,
                        "control_plan_review_required": bool(cp_item.get("source_review_required")) if cp_item else False,
                        "equipment_names": [e["asset_name"] for e in work_equipment],
                        "equipment_display": eq_display,
                        "has_equipment": len(work_equipment) > 0,
                        "status": status,
                        "status_label": status_label,
                        "spec_drift": False,
                        "discrepancies": flags,
                        "discrepancy_count": len(flags),
                        "discrepancy_summary": "; ".join(f["title"] for f in flags) if flags else "Active process control",
                    })

            else:
                # Step has neither quality requirements nor PFMEA entries
                status = "UNCOVERED"
                status_label = "⚪ Uncovered"
                row_severities_for_step.append(status)

                eq_display = (
                    ", ".join(
                        f"{e['asset_name']} [{e.get('equipment_type') or 'Tool'}]"
                        for e in work_equipment
                    )
                    if work_equipment
                    else "—"
                )

                matrix_rows.append({
                    "work_element_id": wid,
                    "op_id": op_id,
                    "pitch": pitch_label,
                    "sequence": seq_val,
                    "operation": op_name,
                    "stage_type": "Standard Assembly",
                    "quality_assignment_id": "",
                    "quality_requirement_id": "",
                    "quality_uid": "—",
                    "quality_type": "—",
                    "quality_description": "—",
                    "published_spec": "—",
                    "pfmea_entry_id": "",
                    "pfmea_class_code": "",
                    "pfmea_failure_mode": "—",
                    "has_pfmea_entry": False,
                    "control_plan_item_id": "",
                    "control_plan_pr_number": "",
                    "control_plan_spec": "—",
                    "control_plan_method": "—",
                    "control_plan_placement": "—",
                    "control_plan_excluded": False,
                    "control_plan_review_required": False,
                    "equipment_names": [e["asset_name"] for e in work_equipment],
                    "equipment_display": eq_display,
                    "has_equipment": len(work_equipment) > 0,
                    "status": status,
                    "status_label": status_label,
                    "spec_drift": False,
                    "discrepancies": [],
                    "discrepancy_count": 0,
                    "discrepancy_summary": "Standard assembly step (no quality or CTQ requirements)",
                })

            # Calculate step-level status
            if "CRITICAL_GAP" in row_severities_for_step:
                step_statuses[wid] = "CRITICAL_GAP"
            elif "WARNING" in row_severities_for_step:
                step_statuses[wid] = "WARNING"
            elif "PROTECTED" in row_severities_for_step:
                step_statuses[wid] = "PROTECTED"
            else:
                step_statuses[wid] = "UNCOVERED"

        # Calculate KPIs
        total_steps = len(work_elements)
        steps_with_quality = sum(1 for s in step_statuses.values() if s != "UNCOVERED")
        protected_steps = sum(1 for s in step_statuses.values() if s == "PROTECTED")
        critical_gap_steps = sum(1 for s in step_statuses.values() if s == "CRITICAL_GAP")
        warning_steps = sum(1 for s in step_statuses.values() if s == "WARNING")
        uncovered_steps = sum(1 for s in step_statuses.values() if s == "UNCOVERED")

        fully_protected_pct = (
            round((protected_steps / steps_with_quality) * 100.0, 1)
            if steps_with_quality > 0
            else 100.0
        )

        return {
            "rows": matrix_rows,
            "summary": {
                "total_steps": total_steps,
                "steps_with_quality": steps_with_quality,
                "protected_steps": protected_steps,
                "critical_gap_steps": critical_gap_steps,
                "warning_steps": warning_steps,
                "uncovered_steps": uncovered_steps,
                "fully_protected_pct": fully_protected_pct,
                "spec_drift_count": total_spec_drifts,
                "tooling_gap_count": total_tooling_gaps,
            },
            "pitches": sorted(p for p in pitches_seen if p),
        }


def align_control_plan_specification(
    project_id: str,
    scenario_id: str,
    control_plan_item_id: str,
    editor_name: str,
) -> dict[str, Any]:
    """Align a single Control Plan item's specification with its published Quality Requirement.

    Enforces deliberate engineering review by updating one specification at a time
    and recording a detailed audit trail.
    """
    if not editor_name or not editor_name.strip():
        raise ValueError("Editor name is required to align specifications.")

    with store.connection() as conn:
        # Find item in control_plan_items
        row = conn.execute(
            """SELECT item.*, a.unique_identifier, a.target_value, a.tolerances, a.unit,
                      a.description, a.requirement_type
               FROM control_plan_items item
               LEFT JOIN quality_requirement_assignments a
                 ON a.id = item.quality_requirement_assignment_id
               WHERE item.id=? AND item.project_id=? AND item.scenario_id=?""",
            (control_plan_item_id, project_id, scenario_id),
        ).fetchone()

        if not row:
            raise ValueError(f"Control Plan item '{control_plan_item_id}' not found.")

        item = dict(row)
        previous_spec = _text(item.get("specification_requirement"))
        pub_spec = _specification(item)

        if not pub_spec:
            raise ValueError("No published Quality specification found for this requirement.")

        timestamp = store.now_iso()
        # Find projected fingerprint to mark review complete
        proj_items = _live_projection_conn(conn, project_id, scenario_id)
        current_fp = ""
        for p in proj_items:
            if _text(p.get("id")) == control_plan_item_id:
                current_fp = _text(p.get("source_fingerprint"))
                break

        conn.execute(
            """UPDATE control_plan_items
               SET specification_requirement=?, source_fingerprint_snapshot=?, source_review_required=0, updated_at=?
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (pub_spec, current_fp, timestamp, control_plan_item_id, project_id, scenario_id),
        )

        store.record_audit_event(
            project_id,
            "Control Plan",
            "Align Specification",
            1,
            editor_name.strip(),
            {
                "control_plan_item_id": control_plan_item_id,
                "unique_identifier": _text(item.get("unique_identifier")),
                "previous_specification": previous_spec,
                "aligned_specification": pub_spec,
                "scenario_id": scenario_id,
            },
            _conn=conn,
        )

        return {
            "success": True,
            "control_plan_item_id": control_plan_item_id,
            "previous_specification": previous_spec,
            "aligned_specification": pub_spec,
        }


def quick_link_step_equipment(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    equipment_id: str,
    editor_name: str,
) -> dict[str, Any]:
    """Quick-link an equipment asset to a work element in the active scenario."""
    if not editor_name or not editor_name.strip():
        raise ValueError("Editor name is required to link equipment.")

    with store.connection() as conn:
        init_equipment_schema(conn)

        # Check work element
        work = conn.execute(
            "SELECT id, station, operation FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
            (work_element_id, project_id, scenario_id),
        ).fetchone()
        if not work:
            raise ValueError("Work element not found.")

        # Check equipment asset
        asset = conn.execute(
            "SELECT id, name FROM equipment_assets WHERE id=? AND project_id=?",
            (equipment_id, project_id),
        ).fetchone()
        if not asset:
            raise ValueError("Equipment asset not found.")

        # Find or create placement
        placement = conn.execute(
            "SELECT id, pitch_id FROM equipment_placements WHERE equipment_id=? AND scenario_id=?",
            (equipment_id, scenario_id),
        ).fetchone()

        timestamp = store.now_iso()
        if placement:
            placement_id = str(placement["id"])
        else:
            placement_id = str(uuid4())
            conn.execute(
                """INSERT INTO equipment_placements
                   (id, project_id, scenario_id, equipment_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (placement_id, project_id, scenario_id, equipment_id, timestamp, timestamp),
            )

        # Check existing process link
        existing_link = conn.execute(
            """SELECT id, unlinked_at FROM equipment_process_links
               WHERE placement_id=? AND work_element_id=?""",
            (placement_id, work_element_id),
        ).fetchone()

        if existing_link:
            if existing_link["unlinked_at"]:
                conn.execute(
                    "UPDATE equipment_process_links SET unlinked_at='', updated_at=? WHERE id=?",
                    (timestamp, str(existing_link["id"])),
                )
        else:
            conn.execute(
                """INSERT INTO equipment_process_links
                   (id, project_id, scenario_id, placement_id, work_element_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid4()), project_id, scenario_id, placement_id, work_element_id, timestamp, timestamp),
            )

        store.record_audit_event(
            project_id,
            "Equipment process links",
            "Quick Link Step Equipment",
            1,
            editor_name.strip(),
            {
                "work_element_id": work_element_id,
                "equipment_id": equipment_id,
                "asset_name": str(asset["name"]),
                "operation": str(work["operation"]),
                "scenario_id": scenario_id,
            },
            _conn=conn,
        )

        return {
            "success": True,
            "work_element_id": work_element_id,
            "equipment_id": equipment_id,
            "placement_id": placement_id,
        }
