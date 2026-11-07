"""Domain persistence extracted from the historical utils.store module."""

from __future__ import annotations

import sys as _sys
from utils import db_core as _db_core
from utils.cache_store import cached_store_read
from utils.recycle_bin_store import capture_deletion_to_recycle_bin, safe_unlink_upload_path
from utils.safety_store import parse_ppe, resolve_pitch_ppe_rollup

globals().update({name: value for name, value in vars(_db_core).items() if not name.startswith('__')})
MATERIAL_SELECTION_RULES = {"Model choice", "Choose one", "Use all", "Optional"}

_YAMAZUMI_PITCH_ADDRESS_PATTERN = re.compile(
    r"^(?P<subline>\d+)-(?P<work_area_letters>[A-Za-z]+)"
    r"(?P<work_area_number>\d+)-(?P<position>\d+)$"
)

def _normalize_handling_type(value) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    handling_type = str(value).strip()
    if handling_type not in HANDLING_TYPES:
        raise ValueError("Handling type must be Handle or Consume.")
    return handling_type

def _normalize_fishbone_assignment_id(value) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return str(value).strip()


def part_has_model_variants(
    part_id: str,
    placements_df: pd.DataFrame,
    *,
    section_id: str | None = None,
    fallback_model_applicability: object = None,
    feature_rule_part_ids: set[str] | None = None,
) -> bool:
    """Return True only when a part genuinely represents a model-variant choice."""
    pid = str(part_id or "").strip()
    if not pid:
        return False
    explicit_all_applicability = False
    if not placements_df.empty and "part_id" in placements_df.columns:
        scoped_df = placements_df
        if section_id and "section_id" in placements_df.columns:
            sec_rows = placements_df.loc[
                placements_df["section_id"].astype(str) == str(section_id).strip()
            ]
            if not sec_rows.empty and (sec_rows["part_id"].astype(str) == pid).any():
                scoped_df = sec_rows
        part_rows = scoped_df.loc[scoped_df["part_id"].astype(str) == pid]
        for _, prow in part_rows.iterrows():
            m_app = (
                ""
                if pd.isna(prow.get("model_applicability"))
                else str(prow.get("model_applicability") or "").strip()
            )
            if m_app.casefold() not in {"", "all", "all models", "base"}:
                return True
            if m_app.casefold() in {"all", "all models", "base"}:
                explicit_all_applicability = True
            try:
                sg = int(prow.get("step_number") or 1)
            except (TypeError, ValueError):
                sg = 1
            if sg > 1:
                prow_sec = str(prow.get("section_id") or section_id or "").strip()
                peer_pool = (
                    placements_df.loc[
                        placements_df["section_id"].astype(str) == prow_sec
                    ]
                    if prow_sec and "section_id" in placements_df.columns
                    else scoped_df
                )
                if "step_number" in peer_pool.columns:
                    sg_peers = peer_pool.loc[
                        pd.to_numeric(peer_pool["step_number"], errors="coerce")
                        .fillna(1)
                        .astype(int)
                        == sg
                    ]
                    if len(sg_peers) >= 2:
                        return True
    if fallback_model_applicability is not None and not pd.isna(
        fallback_model_applicability
    ):
        fb_app = str(fallback_model_applicability or "").strip()
        if fb_app.casefold() not in {"", "all", "all models", "base"}:
            return True
        if fb_app.casefold() in {"all", "all models", "base"}:
            explicit_all_applicability = True
    if (
        not explicit_all_applicability
        and feature_rule_part_ids
        and pid in feature_rule_part_ids
    ):
        return True
    return False


def sync_model_variant_placement_selections(
    part_entries: list[dict],
    all_placements: pd.DataFrame | None,
    state_map: object,
) -> dict[str, str]:
    """Propagate a chosen Use / installation location across tied model-variant parts."""
    if not part_entries or state_map is None:
        return {}

    vg_by_pid: dict[str, set[str]] = {}
    stack_by_pid: dict[str, set[tuple[str, int]]] = {}
    if all_placements is not None and not all_placements.empty and "part_id" in all_placements.columns:
        for _, pl_r in all_placements.iterrows():
            r_pid = str(pl_r.get("part_id") or "").strip()
            if not r_pid:
                continue
            raw_vg = pl_r.get("variant_group")
            vg_str = "" if raw_vg is None or pd.isna(raw_vg) else str(raw_vg or "").strip().casefold()
            if vg_str:
                vg_by_pid.setdefault(r_pid, set()).add(vg_str)
            r_sec = str(pl_r.get("section_id") or "").strip()
            try:
                r_step = int(pl_r.get("step_number") or 1)
            except (TypeError, ValueError):
                r_step = 1
            if r_sec and r_step > 1:
                stack_by_pid.setdefault(r_pid, set()).add((r_sec, r_step))

    mv_entries: list[dict] = []
    for raw_entry in part_entries:
        if not isinstance(raw_entry, dict):
            continue
        p_key = str(raw_entry.get("placement_key") or "").strip()
        if not p_key:
            continue
        if not bool(raw_entry.get("is_model_variant")) or str(raw_entry.get("handling_type") or "Consume") != "Consume":
            continue
        p_opts = raw_entry.get("placement_options")
        meta_list: list[dict] = []
        occ_counts: dict[tuple[str, str], int] = {}
        sec_occ_counts: dict[str, int] = {}
        if isinstance(p_opts, pd.DataFrame) and not p_opts.empty:
            for _, opt_r in p_opts.iterrows():
                aid = str(opt_r.get("fishbone_assignment_id") or "").strip()
                if not aid:
                    continue
                can_cons = bool(opt_r.get("can_consume", True))
                s_id = str(opt_r.get("section_id") or "").strip()
                s_name = str(opt_r.get("section_name") or "").strip().casefold()
                raw_u = opt_r.get("use_description")
                u_desc = "" if raw_u is None or pd.isna(raw_u) else str(raw_u or "").strip().casefold()
                occ_key = (s_id, u_desc)
                occ_i = occ_counts.get(occ_key, 0)
                occ_counts[occ_key] = occ_i + 1
                s_occ_i = sec_occ_counts.get(s_id, 0)
                sec_occ_counts[s_id] = s_occ_i + 1
                meta_list.append(
                    {
                        "aid": aid,
                        "can_consume": can_cons,
                        "sec_id": s_id,
                        "sec_name": s_name,
                        "use_desc": u_desc,
                        "occ_idx": occ_i,
                        "sec_occ_idx": s_occ_i,
                    }
                )
        meta_by_aid = {m["aid"]: m for m in meta_list}
        enabled_metas = [m for m in meta_list if m["can_consume"]]
        curr_raw = state_map.get(p_key)
        curr_aid = "" if curr_raw is None else str(curr_raw or "").strip()
        if curr_aid not in meta_by_aid or not meta_by_aid[curr_aid]["can_consume"]:
            def_aid = str(raw_entry.get("default_aid") or "").strip()
            if p_key not in state_map and def_aid in meta_by_aid and meta_by_aid[def_aid]["can_consume"]:
                curr_aid = def_aid
            elif len(meta_by_aid) == 1 and len(enabled_metas) == 1:
                curr_aid = enabled_metas[0]["aid"]
            else:
                curr_aid = ""
        prev_key = f"{p_key}__mv_prev"
        prev_raw = state_map.get(prev_key)
        prev_aid = "" if prev_raw is None else str(prev_raw or "").strip()
        p_num = str(raw_entry.get("part_number") or "").strip().upper()
        mv_entries.append(
            {
                "part_id": str(raw_entry.get("part_id") or "").strip(),
                "part_number": p_num,
                "prefix": p_num[:8] if len(p_num) >= 8 else p_num,
                "placement_key": p_key,
                "prev_key": prev_key,
                "meta_by_aid": meta_by_aid,
                "enabled_metas": enabled_metas,
                "curr_aid": curr_aid,
                "prev_aid": prev_aid,
                "just_selected": bool(curr_aid and curr_aid != prev_aid),
            }
        )

    if len(mv_entries) < 2:
        for e in mv_entries:
            state_map[e["prev_key"]] = e["curr_aid"]
        return {}

    prefix_counts: dict[str, int] = {}
    for e in mv_entries:
        if e["prefix"]:
            prefix_counts[e["prefix"]] = prefix_counts.get(e["prefix"], 0) + 1

    def _explicitly_tied(a: dict, b: dict) -> bool:
        if a["part_id"] == b["part_id"]:
            return False
        if a["prefix"] and a["prefix"] == b["prefix"]:
            return True
        vgs_a = vg_by_pid.get(a["part_id"], set())
        vgs_b = vg_by_pid.get(b["part_id"], set())
        if vgs_a and vgs_b and (vgs_a & vgs_b):
            return True
        st_a = stack_by_pid.get(a["part_id"], set())
        st_b = stack_by_pid.get(b["part_id"], set())
        if st_a and st_b and (st_a & st_b):
            return True
        return False

    def _peers_for(src: dict) -> list[dict]:
        explicit_peers = [other for other in mv_entries if _explicitly_tied(src, other)]
        if explicit_peers:
            extra_peers = [
                other
                for other in mv_entries
                if other["part_id"] != src["part_id"]
                and other not in explicit_peers
                and prefix_counts.get(other["prefix"], 0) <= 1
            ]
            return explicit_peers + extra_peers
        return [other for other in mv_entries if other["part_id"] != src["part_id"]]

    def _match_target_aid(src_meta: dict, target_entry: dict) -> str:
        candidates = target_entry["enabled_metas"]
        if not candidates:
            return ""
        for m in candidates:
            if (
                m["sec_id"] == src_meta["sec_id"]
                and m["use_desc"] == src_meta["use_desc"]
                and m["occ_idx"] == src_meta["occ_idx"]
            ):
                return m["aid"]
        for m in candidates:
            if m["sec_id"] == src_meta["sec_id"] and m["use_desc"] == src_meta["use_desc"]:
                return m["aid"]
        for m in candidates:
            if m["sec_name"] == src_meta["sec_name"] and m["use_desc"] == src_meta["use_desc"]:
                return m["aid"]
        for m in candidates:
            if m["sec_id"] == src_meta["sec_id"] and m["sec_occ_idx"] == src_meta["sec_occ_idx"]:
                return m["aid"]
        for m in candidates:
            if m["sec_id"] == src_meta["sec_id"]:
                return m["aid"]
        return ""

    synced_by_pid: dict[str, str] = {}
    changed_sources = [e for e in mv_entries if e["just_selected"] and e["curr_aid"] in e["meta_by_aid"]]
    if changed_sources:
        for src in changed_sources:
            src_meta = src["meta_by_aid"][src["curr_aid"]]
            for peer in _peers_for(src):
                if peer["just_selected"]:
                    continue
                matched_aid = _match_target_aid(src_meta, peer)
                if matched_aid:
                    state_map[peer["placement_key"]] = matched_aid
                    peer["curr_aid"] = matched_aid
                    synced_by_pid[peer["part_id"]] = matched_aid
    else:
        populated_sources = [e for e in mv_entries if e["curr_aid"] and e["curr_aid"] in e["meta_by_aid"]]
        for src in populated_sources:
            src_meta = src["meta_by_aid"][src["curr_aid"]]
            for peer in _peers_for(src):
                if peer["curr_aid"]:
                    continue
                matched_aid = _match_target_aid(src_meta, peer)
                if matched_aid:
                    state_map[peer["placement_key"]] = matched_aid
                    peer["curr_aid"] = matched_aid
                    synced_by_pid[peer["part_id"]] = matched_aid

    for e in mv_entries:
        state_map[e["prev_key"]] = e["curr_aid"]

    return synced_by_pid


def _unused_normalize_fishbone_assignment_id(value) -> str | None:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    return str(value).strip()

def _project_variant_alias_map(
    conn: sqlite3.Connection, project_id: str
) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for row in conn.execute(
        """SELECT model_number, display_name
           FROM project_models
           WHERE project_id=?""",
        (project_id,),
    ).fetchall():
        mnum = str(row["model_number"] or "").strip()
        if not mnum:
            continue
        canonical = mnum.casefold()
        alias_map[canonical] = canonical
        disp = str(row["display_name"] or "").strip()
        if disp:
            alias_map[disp.casefold()] = canonical
            alias_map[f"{disp} ({mnum})".casefold()] = canonical
    return alias_map


def _extract_raw_variant_items(
    value: object, fallback: object = None
) -> list[str]:
    items: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = [part.strip() for part in text.split(",") if part.strip()]
            if isinstance(parsed, (list, tuple, set)):
                for item in parsed:
                    cleaned = str(item or "").strip()
                    if cleaned:
                        items.append(cleaned)
            elif parsed is not None:
                cleaned = str(parsed).strip()
                if cleaned:
                    items.append(cleaned)
        elif text:
            items.extend(part.strip() for part in text.split(",") if part.strip())
    elif isinstance(value, (list, tuple, set)):
        for elem in value:
            items.extend(_extract_raw_variant_items(elem))
    elif value is not None and not pd.isna(value):
        cleaned = str(value).strip()
        if cleaned:
            items.append(cleaned)
    if not items and fallback is not None:
        return _extract_raw_variant_items(fallback)
    return items


def _normalize_variant_tokens(
    raw_items: list[str], alias_map: dict[str, str]
) -> set[str]:
    if not raw_items:
        return {"__all__"}
    tokens: set[str] = set()
    for item in raw_items:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        folded = cleaned.casefold()
        if folded in {"all", "all models", "base"}:
            return {"__all__"}
        tokens.add(alias_map.get(folded, folded))
    return tokens or {"__all__"}


def _group_same_pitch_yamazumi_rows(
    rows: list[dict] | list[sqlite3.Row],
    *,
    keep_private_fields: bool = False,
) -> list[dict]:
    """Combine same-pitch Yamazumi element rows that represent the same step across model variants."""
    grouped: list[dict] = []
    candidates_by_sig: dict[tuple[str, str, str, str, float], list[dict]] = {}
    candidates_by_pitch_proc: dict[tuple[str, str, str], dict] = {}
    for raw_row in rows:
        row = dict(raw_row)
        row_id = str(row.get("id") or row.get("yamazumi_element_id") or "").strip()
        row_variants = parse_yamazumi_model_variants(
            row.get("model_variants"), row.get("model_variant")
        )
        row_variant_keys = (
            {"__all__"}
            if (
                not row_variants
                or any(
                    v.casefold() in {"base", "all", "all models"}
                    for v in row_variants
                )
            )
            else {v.casefold() for v in row_variants}
        )
        raw_primary_variant = str(row.get("model_variant") or "").strip()
        if not raw_primary_variant and len(row_variants) == 1:
            raw_primary_variant = row_variants[0]
        primary_variant_key = (
            "__all__"
            if (
                not raw_primary_variant
                or raw_primary_variant.casefold() in {"base", "all", "all models"}
            )
            else raw_primary_variant.casefold()
        )
        row_proc_id = str(row.get("process_element_id") or "").strip()
        pitch_id = str(
            row.get("pitch_id") or row.get("resolved_pitch_id") or ""
        ).strip()
        area_id = str(row.get("area_id") or "").strip()

        if not pitch_id:
            entry = dict(row)
            entry["_member_ids"] = [row_id] if row_id else []
            entry["_variants"] = list(row_variants)
            entry["_seen_variants"] = {v.casefold() for v in row_variants}
            entry["_variant_keys"] = set(row_variant_keys)
            entry["_primary_variant_keys"] = {primary_variant_key}
            entry["_process_element_id"] = row_proc_id
            grouped.append(entry)
            continue

        work_type_key = (
            str(row.get("work_type") or "Cycle").strip().casefold() or "cycle"
        )
        desc_text = (
            row.get("description")
            if "description" in row
            else row.get("yamazumi_description")
        )
        desc_key = str(desc_text or "").strip().casefold()
        raw_time = (
            row.get("time_s")
            if "time_s" in row
            else row.get("yamazumi_time_s")
        )
        time_key = round(float(raw_time or 0.0), 6)
        sig = (area_id, pitch_id, work_type_key, desc_key, time_key)

        matched_group: dict | None = None
        if row_proc_id:
            matched_group = candidates_by_pitch_proc.get(
                (area_id, pitch_id, row_proc_id)
            )
        if matched_group is None:
            for candidate in candidates_by_sig.get(sig, []):
                cand_proc_id = candidate["_process_element_id"]
                if cand_proc_id and row_proc_id and cand_proc_id != row_proc_id:
                    continue
                if not (cand_proc_id and row_proc_id and cand_proc_id == row_proc_id):
                    if (
                        "__all__" in candidate["_variant_keys"]
                        or "__all__" in row_variant_keys
                    ):
                        continue
                    is_disjoint = row_variant_keys.isdisjoint(
                        candidate["_variant_keys"]
                    )
                    is_different_primary_stack = (
                        primary_variant_key != "__all__"
                        and primary_variant_key
                        not in candidate["_primary_variant_keys"]
                    )
                    is_multi_variant_subset = (
                        (
                            len(candidate["_variant_keys"]) > 1
                            and row_variant_keys.issubset(
                                candidate["_variant_keys"]
                            )
                        )
                        or (
                            len(row_variant_keys) > 1
                            and candidate["_variant_keys"].issubset(
                                row_variant_keys
                            )
                        )
                    )
                    if not (
                        is_disjoint
                        or is_different_primary_stack
                        or is_multi_variant_subset
                    ):
                        continue
                matched_group = candidate
                break

        if matched_group is not None:
            if row_id and row_id not in matched_group["_member_ids"]:
                matched_group["_member_ids"].append(row_id)
            for v in row_variants:
                vk = v.casefold()
                if vk not in matched_group["_seen_variants"]:
                    matched_group["_seen_variants"].add(vk)
                    matched_group["_variants"].append(v)
            matched_group["_variant_keys"].update(row_variant_keys)
            matched_group["_primary_variant_keys"].add(primary_variant_key)
            if not matched_group["_process_element_id"] and row_proc_id:
                matched_group["_process_element_id"] = row_proc_id
                matched_group["process_element_id"] = row_proc_id
                candidates_by_pitch_proc[(area_id, pitch_id, row_proc_id)] = (
                    matched_group
                )
                if "process_sync_status" in row and row.get("process_sync_status"):
                    matched_group["process_sync_status"] = row["process_sync_status"]
            if "process_reflected" in matched_group or "process_reflected" in row:
                matched_group["process_reflected"] = (
                    1
                    if (
                        int(matched_group.get("process_reflected") or 0)
                        or int(row.get("process_reflected") or 0)
                    )
                    else 0
                )
            if (
                "material_group_count" in matched_group
                or "material_group_count" in row
            ):
                matched_group["material_group_count"] = max(
                    int(matched_group.get("material_group_count") or 0),
                    int(row.get("material_group_count") or 0),
                )
        else:
            entry = dict(row)
            entry["_member_ids"] = [row_id] if row_id else []
            entry["_variants"] = list(row_variants)
            entry["_seen_variants"] = {v.casefold() for v in row_variants}
            entry["_variant_keys"] = set(row_variant_keys)
            entry["_primary_variant_keys"] = {primary_variant_key}
            entry["_process_element_id"] = row_proc_id
            grouped.append(entry)
            candidates_by_sig.setdefault(sig, []).append(entry)
            if row_proc_id:
                candidates_by_pitch_proc[(area_id, pitch_id, row_proc_id)] = entry

    for group in grouped:
        combined_variants = list(group.get("_variants") or ["All models"])
        if any(
            v.casefold() in {"base", "all", "all models"}
            for v in combined_variants
        ):
            combined_variants = ["All models"]
        group["model_variant"] = combined_variants[0]
        group["model_variants"] = json.dumps(combined_variants)
        if "process_element_id" in group:
            group["process_element_id"] = group.get("_process_element_id") or None
        if not keep_private_fields:
            group.pop("_member_ids", None)
            group.pop("_variants", None)
            group.pop("_seen_variants", None)
            group.pop("_variant_keys", None)
            group.pop("_primary_variant_keys", None)
            group.pop("_process_element_id", None)
    return grouped


def _find_same_pitch_yamazumi_group_for_element(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    yamazumi_element_id: str,
) -> dict | None:
    """Resolve the same-pitch variant group containing yamazumi_element_id."""
    clean_id = str(yamazumi_element_id or "").strip()
    if not clean_id:
        return None
    target = conn.execute(
        """SELECT e.*, p.pitch_number, a.name AS area_name, a.section_id,
                  COALESCE(NULLIF(TRIM(e.work_type), ''), 'Cycle') AS work_type
           FROM yamazumi_elements e
           LEFT JOIN yamazumi_pitches p ON p.id=e.pitch_id
           JOIN yamazumi_areas a ON a.id=e.area_id
           WHERE e.id=? AND e.project_id=? AND a.scenario_id=?""",
        (clean_id, project_id, scenario_id),
    ).fetchone()
    if not target:
        return None
    target_pitch_id = str(target["pitch_id"] or "").strip()
    if not target_pitch_id:
        groups = _group_same_pitch_yamazumi_rows(
            [dict(target)], keep_private_fields=True
        )
        return groups[0] if groups else None
    pitch_rows = conn.execute(
        """SELECT e.*, p.pitch_number, a.name AS area_name, a.section_id,
                  COALESCE(NULLIF(TRIM(e.work_type), ''), 'Cycle') AS work_type
           FROM yamazumi_elements e
           LEFT JOIN yamazumi_pitches p ON p.id=e.pitch_id
           JOIN yamazumi_areas a ON a.id=e.area_id
           WHERE e.project_id=? AND a.scenario_id=? AND e.area_id=? AND e.pitch_id=?
           ORDER BY e.sequence, e.id""",
        (project_id, scenario_id, target["area_id"], target_pitch_id),
    ).fetchall()
    groups = _group_same_pitch_yamazumi_rows(
        pitch_rows, keep_private_fields=True
    )
    for group in groups:
        if clean_id in (group.get("_member_ids") or []):
            return group
    fallback = _group_same_pitch_yamazumi_rows(
        [dict(target)], keep_private_fields=True
    )
    return fallback[0] if fallback else None


def _resolve_target_variant_tokens(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    *,
    work_element_id: str | None = None,
    yamazumi_element_id: str | None = None,
    target_variants: object = None,
    process_part_option_id: str | None = None,
    alias_map: dict[str, str] | None = None,
) -> set[str]:
    amap = (
        alias_map
        if alias_map is not None
        else _project_variant_alias_map(conn, project_id)
    )
    if target_variants is not None:
        return _normalize_variant_tokens(
            _extract_raw_variant_items(target_variants), amap
        )
    resolved_we_id = str(work_element_id or "").strip() or None
    resolved_yam_id = str(yamazumi_element_id or "").strip() or None
    if resolved_yam_id:
        yam_row = _find_same_pitch_yamazumi_group_for_element(
            conn, project_id, scenario_id, resolved_yam_id
        )
        if yam_row:
            yam_items = _extract_raw_variant_items(
                yam_row.get("model_variants"), yam_row.get("model_variant")
            )
            yam_tokens = _normalize_variant_tokens(yam_items, amap)
            if yam_tokens != {"__all__"}:
                return yam_tokens
            if not resolved_we_id and yam_row.get("process_element_id"):
                resolved_we_id = (
                    str(yam_row["process_element_id"]).strip() or None
                )
    if not resolved_we_id and process_part_option_id:
        opt_row = conn.execute(
            """SELECT group_row.work_element_id
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE option.id=? AND group_row.project_id=? AND group_row.scenario_id=?""",
            (process_part_option_id, project_id, scenario_id),
        ).fetchone()
        if opt_row and opt_row["work_element_id"]:
            resolved_we_id = str(opt_row["work_element_id"]).strip() or None
    if resolved_we_id:
        we_row = conn.execute(
            """SELECT model_applicability
               FROM work_elements
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (resolved_we_id, project_id, scenario_id),
        ).fetchone()
        if we_row:
            we_tokens = _normalize_variant_tokens(
                _extract_raw_variant_items(we_row["model_applicability"]), amap
            )
            if we_tokens != {"__all__"}:
                return we_tokens
        yam_rows = conn.execute(
            """SELECT e.model_variants, e.model_variant
               FROM yamazumi_elements e
               JOIN yamazumi_areas a ON a.id=e.area_id
               WHERE e.project_id=? AND a.scenario_id=? AND e.process_element_id=?""",
            (project_id, scenario_id, resolved_we_id),
        ).fetchall()
        if yam_rows:
            combined_items: list[str] = []
            for yr in yam_rows:
                combined_items.extend(
                    _extract_raw_variant_items(
                        yr["model_variants"], yr["model_variant"]
                    )
                )
            return _normalize_variant_tokens(combined_items, amap)
    return {"__all__"}


def _process_part_assignment_consume_count(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    fishbone_assignment_id: str,
    *,
    exclude_process_part_option_id: str | None = None,
    exclude_group_id: str | None = None,
    work_element_id: str | None = None,
    yamazumi_element_id: str | None = None,
    target_variants: object = None,
    any_variant: bool = False,
) -> int | float:
    exclude_clause = ""
    params: tuple = (project_id, scenario_id, fishbone_assignment_id)
    if exclude_process_part_option_id:
        exclude_clause += " AND option.id<>?"
        params += (exclude_process_part_option_id,)
    if exclude_group_id:
        exclude_clause += " AND option.group_id<>?"
        params += (exclude_group_id,)
    if any_variant:
        total_any = float(
            conn.execute(
                f"""SELECT COALESCE(
                        SUM(
                            CASE
                                WHEN COALESCE(option.quantity, group_row.quantity, 1.0) > 0
                                THEN COALESCE(option.quantity, group_row.quantity, 1.0)
                                ELSE 1.0
                            END
                        ),
                        0.0
                    )
                    FROM process_part_options option
                    JOIN process_part_groups group_row ON group_row.id=option.group_id
                    WHERE group_row.project_id=? AND group_row.scenario_id=?
                      AND option.fishbone_assignment_id=?
                      AND option.handling_type='Consume'{exclude_clause}""",
                params,
            ).fetchone()[0]
            or 0.0
        )
        return int(total_any) if total_any.is_integer() else total_any
    rows = conn.execute(
        f"""SELECT group_row.work_element_id,
                   CASE
                       WHEN COALESCE(option.quantity, group_row.quantity, 1.0) > 0
                       THEN COALESCE(option.quantity, group_row.quantity, 1.0)
                       ELSE 1.0
                   END AS effective_quantity
            FROM process_part_options option
            JOIN process_part_groups group_row ON group_row.id=option.group_id
            WHERE group_row.project_id=? AND group_row.scenario_id=?
              AND option.fishbone_assignment_id=?
              AND option.handling_type='Consume'{exclude_clause}""",
        params,
    ).fetchall()
    if not rows:
        return 0
    alias_map = _project_variant_alias_map(conn, project_id)
    target_tokens = _resolve_target_variant_tokens(
        conn,
        project_id,
        scenario_id,
        work_element_id=work_element_id,
        yamazumi_element_id=yamazumi_element_id,
        target_variants=target_variants,
        process_part_option_id=exclude_process_part_option_id,
        alias_map=alias_map,
    )
    all_count = 0.0
    variant_counts: dict[str, float] = {}
    we_token_cache: dict[str, set[str]] = {}
    for row in rows:
        we_id = str(row["work_element_id"] or "").strip()
        row_qty = float(row["effective_quantity"] or 1.0)
        if row_qty <= 0:
            row_qty = 1.0
        if we_id not in we_token_cache:
            we_token_cache[we_id] = _resolve_target_variant_tokens(
                conn,
                project_id,
                scenario_id,
                work_element_id=we_id,
                alias_map=alias_map,
            )
        row_tokens = we_token_cache[we_id]
        if "__all__" in row_tokens:
            all_count += row_qty
        else:
            for tok in row_tokens:
                variant_counts[tok] = variant_counts.get(tok, 0.0) + row_qty
    if "__all__" in target_tokens:
        total = all_count + (max(variant_counts.values()) if variant_counts else 0.0)
    else:
        total = max(all_count + variant_counts.get(tok, 0.0) for tok in target_tokens)
    return int(total) if float(total).is_integer() else float(total)

def _validate_process_part_option_handling(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    scenario_id: str,
    section_id: str,
    process_part_option_id: str,
    part_id: str,
    handling_type: str | None,
    fishbone_assignment_id: str | None,
    quantity: float | None = None,
    exclude_group_id: str | None = None,
    work_element_id: str | None = None,
    yamazumi_element_id: str | None = None,
    target_variants: object = None,
) -> None:
    if handling_type is None and fishbone_assignment_id is None:
        return
    if handling_type is not None and fishbone_assignment_id is None:
        raise ValueError(
            f"A Fishbone placement is required before this part can be {handling_type.lower()}d."
        )
    if fishbone_assignment_id is None:
        return

    assignment = conn.execute(
        """SELECT assignment.id, assignment.section_id, assignment.quantity,
                  assignment.use_description,
                  part.part_number, section.name AS section_name
           FROM fishbone_part_assignments assignment
           JOIN parts part ON part.id=assignment.part_id
           JOIN assembly_sections section ON section.id=assignment.section_id
           WHERE assignment.id=? AND assignment.project_id=?
             AND assignment.part_id=?""",
        (fishbone_assignment_id, project_id, part_id),
    ).fetchone()
    if not assignment or (
        handling_type != "Handle"
        and str(assignment["section_id"]) != str(section_id)
    ):
        raise ValueError(
            "Choose a Fishbone placement for the same part in this part requirement's "
            "Fishbone section."
        )
    if handling_type is None:
        return

    placement_label = str(assignment["part_number"])
    use_description = str(assignment["use_description"] or "").strip()
    if use_description:
        placement_label = f"{placement_label} — {use_description}"
    placement_label = f"{placement_label} [{assignment['id']}]"

    if handling_type == "Consume":
        consume_quantity = (
            float(quantity)
            if quantity is not None and not pd.isna(quantity)
            else 1.0
        )
        if not math.isfinite(consume_quantity) or consume_quantity <= 0:
            raise ValueError("Part quantity must be greater than zero.")
        other_consume_count = _process_part_assignment_consume_count(
            conn,
            project_id,
            scenario_id,
            fishbone_assignment_id,
            exclude_process_part_option_id=process_part_option_id,
            exclude_group_id=exclude_group_id,
            work_element_id=work_element_id,
            yamazumi_element_id=yamazumi_element_id,
            target_variants=target_variants,
        )
        recorded_quantity = float(assignment["quantity"])
        if float(other_consume_count) + consume_quantity > recorded_quantity + 1e-9:
            remaining_allowance = max(recorded_quantity - float(other_consume_count), 0.0)
            if remaining_allowance <= 1e-9:
                raise ValueError(
                    f"Fishbone placement {placement_label} has a recorded quantity of "
                    f"{recorded_quantity:g}, which has already been fully consumed elsewhere "
                    "in this scenario."
                )
            raise ValueError(
                f"Fishbone placement {placement_label} has a recorded quantity of "
                f"{recorded_quantity:g} and a remaining Consume allowance of "
                f"{remaining_allowance:g}, so quantity {consume_quantity:g} cannot be consumed."
            )
        return

    other_any_consume_count = _process_part_assignment_consume_count(
        conn,
        project_id,
        scenario_id,
        fishbone_assignment_id,
        exclude_process_part_option_id=process_part_option_id,
        exclude_group_id=exclude_group_id,
        any_variant=True,
    )
    if float(other_any_consume_count) <= 0:
        raise ValueError(
            f"Fishbone placement {placement_label} must be Consumed before it can be Handled "
            "in this scenario."
        )

@cached_store_read
def process_part_placement_options(
    project_id: str,
    scenario_id: str,
    section_id: str,
    part_id: str,
    *,
    exclude_group_id: str | None = None,
    work_element_id: str | None = None,
    yamazumi_element_id: str | None = None,
    target_variants: object = None,
) -> pd.DataFrame:
    """Return exact Fishbone uses with scenario-specific Consume availability."""
    columns = [
        "fishbone_assignment_id",
        "part_id",
        "part_number",
        "section_id",
        "section_name",
        "use_description",
        "fishbone_quantity",
        "consumed_count",
        "remaining_consume_allowance",
        "can_consume",
        "can_handle",
    ]
    with connection() as conn:
        if not conn.execute(
            """SELECT 1 FROM planning_scenarios
               WHERE id=? AND project_id=?""",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        assignments = conn.execute(
            """SELECT assignment.id AS fishbone_assignment_id,
                      assignment.part_id, part.part_number,
                      assignment.section_id, section.name AS section_name,
                      assignment.use_description,
                      assignment.quantity AS fishbone_quantity
               FROM fishbone_part_assignments assignment
               JOIN parts part ON part.id=assignment.part_id
               JOIN assembly_sections section ON section.id=assignment.section_id
               LEFT JOIN part_scenario_activity activity
                 ON activity.project_id=assignment.project_id
                AND activity.scenario_id=? AND activity.part_id=assignment.part_id
               WHERE assignment.project_id=?
                 AND assignment.part_id=? AND COALESCE(activity.active, 1)=1
               ORDER BY CASE WHEN assignment.section_id=? THEN 0 ELSE 1 END,
                        section.sequence, assignment.sequence, assignment.id""",
            (scenario_id, project_id, part_id, section_id),
        ).fetchall()
        rows: list[dict] = []
        for assignment in assignments:
            assignment_id = str(assignment["fishbone_assignment_id"])
            in_current_section = str(assignment["section_id"]) == str(section_id)
            consumed_count = _process_part_assignment_consume_count(
                conn,
                project_id,
                scenario_id,
                assignment_id,
                exclude_group_id=exclude_group_id,
                work_element_id=work_element_id,
                yamazumi_element_id=yamazumi_element_id,
                target_variants=target_variants,
            )
            any_consumed_count = _process_part_assignment_consume_count(
                conn,
                project_id,
                scenario_id,
                assignment_id,
                exclude_group_id=exclude_group_id,
                any_variant=True,
            )
            if not in_current_section and float(any_consumed_count) <= 0:
                continue
            fishbone_quantity = float(assignment["fishbone_quantity"])
            remaining = (
                max(fishbone_quantity - float(consumed_count), 0.0)
                if in_current_section
                else 0.0
            )
            row = dict(assignment)
            row.update(
                consumed_count=consumed_count,
                remaining_consume_allowance=remaining,
                can_consume=(
                    in_current_section and (remaining > 1e-9)
                ),
                can_handle=(float(any_consumed_count) > 0),
            )
            rows.append(row)
    if not rows:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})
    return pd.DataFrame(rows, columns=columns)

def _resolve_handle_fishbone_assignment_id(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    scenario_id: str,
    section_id: str,
    part_id: str,
    exclude_process_part_option_id: str | None = None,
    exclude_group_id: str | None = None,
) -> str | None:
    """Resolve an appropriate Fishbone placement automatically when Handling a part."""
    candidates = conn.execute(
        """SELECT id
           FROM fishbone_part_assignments
           WHERE project_id=? AND part_id=?
           ORDER BY CASE WHEN section_id=? THEN 0 ELSE 1 END, sequence, id""",
        (project_id, part_id, str(section_id or "")),
    ).fetchall()
    if not candidates:
        return None
    for row in candidates:
        cand_id = str(row["id"])
        consumed = _process_part_assignment_consume_count(
            conn,
            project_id,
            scenario_id,
            cand_id,
            exclude_process_part_option_id=exclude_process_part_option_id,
            exclude_group_id=exclude_group_id,
            any_variant=True,
        )
        if float(consumed) > 0:
            return cand_id
    return str(candidates[0]["id"])


def validate_process_part_option_pairings(
    project_id: str,
    scenario_id: str,
    section_id: str,
    pairings: list[dict],
    *,
    exclude_group_id: str | None = None,
    work_element_id: str | None = None,
    yamazumi_element_id: str | None = None,
    target_variants: object = None,
) -> None:
    """Validate new Process part pairings before any surrounding workflow writes."""
    with connection() as conn:
        if not conn.execute(
            """SELECT 1 FROM planning_scenarios
               WHERE id=? AND project_id=?""",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        for pairing in pairings:
            raw_qty = pairing.get("quantity")
            opt_qty: float | None = None
            if raw_qty is not None and not pd.isna(raw_qty) and str(raw_qty).strip() != "":
                opt_qty = _optional_nonnegative_number(raw_qty, "Part quantity")
                if opt_qty is None or opt_qty <= 0:
                    raise ValueError("Part quantity must be greater than zero.")
            norm_ht = _normalize_handling_type(pairing.get("handling_type"))
            norm_aid = _normalize_fishbone_assignment_id(
                pairing.get("fishbone_assignment_id")
            )
            opt_id_str = str(pairing.get("id") or uuid4())
            part_id_str = str(pairing.get("part_id") or "")
            if norm_ht == "Handle" and not norm_aid:
                norm_aid = _resolve_handle_fishbone_assignment_id(
                    conn,
                    project_id=project_id,
                    scenario_id=scenario_id,
                    section_id=section_id,
                    part_id=part_id_str,
                    exclude_process_part_option_id=opt_id_str,
                    exclude_group_id=exclude_group_id,
                )
            _validate_process_part_option_handling(
                conn,
                project_id=project_id,
                scenario_id=scenario_id,
                section_id=section_id,
                process_part_option_id=opt_id_str,
                part_id=part_id_str,
                handling_type=norm_ht,
                fishbone_assignment_id=norm_aid,
                quantity=opt_qty,
                exclude_group_id=exclude_group_id,
                work_element_id=work_element_id,
                yamazumi_element_id=yamazumi_element_id,
                target_variants=target_variants,
            )

@cached_store_read
def yamazumi_elements_for_section(
    project_id: str, scenario_id: str, section_id: str
) -> pd.DataFrame:
    rows = query(
        """SELECT element.id, element.process_element_id, element.description,
                   element.time_s, element.model_variant, element.model_variants,
                   COALESCE(NULLIF(TRIM(element.work_type), ''), 'Cycle') AS work_type,
                   element.process_sync_status, area.id AS area_id, area.name AS area_name,
                   element.pitch_id AS pitch_id, pitch.pitch_number, pitch.pitch_name,
                   CASE WHEN process.id IS NULL THEN 0 ELSE 1 END AS process_reflected,
                   COUNT(DISTINCT group_row.id) AS material_group_count
           FROM yamazumi_elements element
            JOIN yamazumi_areas area ON area.id=element.area_id
            LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
            LEFT JOIN work_elements process
              ON process.id=element.process_element_id
             AND process.project_id=element.project_id
             AND process.scenario_id=area.scenario_id
            LEFT JOIN process_part_groups group_row
             ON group_row.work_element_id=element.process_element_id
            AND group_row.scenario_id=area.scenario_id
           WHERE element.project_id=? AND area.scenario_id=? AND area.section_id=?
             AND LOWER(COALESCE(NULLIF(TRIM(element.work_type), ''), 'Cycle')) = 'cycle'
           GROUP BY element.id
           ORDER BY area.name, pitch.sequence, element.sequence, element.id""",
        (project_id, scenario_id, section_id),
    )
    if not rows:
        return pd.DataFrame(
            columns=[
                "id", "process_element_id", "description", "time_s", "model_variant",
                "model_variants", "work_type", "process_sync_status", "area_id",
                "area_name", "pitch_id", "pitch_number", "pitch_name", "process_reflected",
                "material_group_count",
            ]
        )
    return pd.DataFrame(_group_same_pitch_yamazumi_rows(rows))

@cached_store_read
def yamazumi_context_for_process(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return Yamazumi source labels linked to Process at a Glance rows."""
    df = _yamazumi_context_raw_df(project_id, scenario_id)
    if df.empty or "process_element_id" not in df.columns:
        return df
    rows = df.to_dict(orient="records")
    variants_by_process_id: dict[str, list[str]] = {}
    seen_by_process_id: dict[str, set[str]] = {}
    for row in rows:
        pid = str(row.get("process_element_id") or "").strip()
        if not pid:
            continue
        bucket = variants_by_process_id.setdefault(pid, [])
        seen = seen_by_process_id.setdefault(pid, set())
        for variant in parse_yamazumi_model_variants(
            row.get("model_variants"), row.get("model_variant")
        ):
            v_key = variant.casefold()
            if v_key not in seen:
                seen.add(v_key)
                bucket.append(variant)
    applicability_by_process_id: dict[str, str] = {}
    for pid, variants in variants_by_process_id.items():
        if not variants or any(
            v.casefold() in {"base", "all", "all models"} for v in variants
        ):
            applicability_by_process_id[pid] = "All"
        else:
            applicability_by_process_id[pid] = ", ".join(variants)
    out = df.copy()
    out["yamazumi_model_applicability"] = [
        applicability_by_process_id.get(str(pid or "").strip(), "All")
        for pid in out["process_element_id"]
    ]
    return out
def _yamazumi_context_raw_df(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Return Yamazumi source labels linked to Process at a Glance rows."""
    rows = query(
        """SELECT element.process_element_id, element.id AS yamazumi_element_id,
                   element.description AS yamazumi_description,
                   element.time_s AS yamazumi_time_s,
                   element.model_variant, element.model_variants,
                   COALESCE(NULLIF(TRIM(element.work_type), ''), 'Cycle') AS work_type,
                   area.id AS area_id,
                   area.section_id AS section_id,
                   pitch.id AS pitch_id, pitch.pitch_number, pitch.pitch_name
           FROM yamazumi_elements element
           JOIN yamazumi_areas area ON area.id=element.area_id
           LEFT JOIN yamazumi_pitches pitch ON pitch.id=element.pitch_id
           WHERE element.project_id=? AND area.scenario_id=?
           ORDER BY area.name, pitch.sequence, element.sequence, element.id""",
        (project_id, scenario_id),
    )
    grouped = [
        {
            k: v
            for k, v in row.items()
            if k not in {"work_type", "area_id"}
        }
        for row in _group_same_pitch_yamazumi_rows(rows)
        if str(row.get("process_element_id") or "").strip()
    ]
    return pd.DataFrame(grouped)

@cached_store_read
def process_element_id_for_yamazumi(
    project_id: str, scenario_id: str, yamazumi_element_id: str
) -> str | None:
    with connection() as conn:
        group = _find_same_pitch_yamazumi_group_for_element(
            conn, project_id, scenario_id, yamazumi_element_id
        )
    if not group:
        return None
    return str(group.get("process_element_id") or "").strip() or None

def _ensure_process_part_options_model_variant_column(conn: sqlite3.Connection) -> None:
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(process_part_options)").fetchall()
    }
    if "is_model_variant" not in cols:
        conn.execute(
            "ALTER TABLE process_part_options ADD COLUMN is_model_variant INTEGER NOT NULL DEFAULT 0 CHECK (is_model_variant IN (0, 1))"
        )
        conn.execute(
            """UPDATE process_part_options
               SET is_model_variant = 1
               WHERE group_id IN (
                   SELECT id FROM process_part_groups
                   WHERE selection_rule IN ('Choose one', 'Model choice')
               )"""
        )

@cached_store_read
def process_part_groups(
    project_id: str,
    scenario_id: str,
    work_element_id: str | None = None,
    *,
    active_only: bool = False,
) -> list[dict]:
    with connection() as conn:
        _ensure_process_part_options_model_variant_column(conn)
    element_clause = " AND group_row.work_element_id=?" if work_element_id else ""
    params = (project_id, scenario_id, work_element_id) if work_element_id else (project_id, scenario_id)
    groups = query(
        f"""SELECT group_row.*, section.name AS section_name,
                   element.operation, element.station
            FROM process_part_groups group_row
            JOIN work_elements element ON element.id=group_row.work_element_id
            LEFT JOIN assembly_sections section ON section.id=group_row.section_id
            WHERE group_row.project_id=? AND group_row.scenario_id=?{element_clause}
            ORDER BY element.sequence, group_row.name""",
        params,
    )
    for group in groups:
        activity_join = """
            LEFT JOIN part_scenario_activity activity
              ON activity.project_id=? AND activity.scenario_id=?
             AND activity.part_id=option.part_id
        """ if active_only else ""
        activity_clause = " AND COALESCE(activity.active, 1)=1" if active_only else ""
        option_params = (
            (project_id, scenario_id, group["id"])
            if active_only else (group["id"],)
        )
        options = query(
            f"""SELECT option.id, option.part_id, option.handling_type,
                      option.fishbone_assignment_id, option.quantity,
                      COALESCE(option.is_model_variant, 0) AS is_model_variant,
                      part.part_number, part.description AS part_description,
                      part.model_applicability, part.weight_lb
               FROM process_part_options option
               JOIN parts part ON part.id=option.part_id
               {activity_join}
               WHERE option.group_id=?{activity_clause} ORDER BY part.part_number""",
            option_params,
        )
        for option in options:
            raw_opt_qty = option.get("quantity")
            if raw_opt_qty is None:
                option["quantity"] = (
                    float(group.get("quantity") or 1.0)
                    if str(option.get("handling_type") or "").strip() == "Consume"
                    else None
                )
            else:
                option["quantity"] = float(raw_opt_qty)
            option["is_model_variant"] = bool(option.get("is_model_variant"))
        group["options"] = options
        group["part_ids"] = [str(option["part_id"]) for option in options]
    return [group for group in groups if group["options"]] if active_only else groups

def save_process_part_group(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    section_id: str,
    group_id: str | None,
    name: str,
    selection_rule: str,
    quantity: float | None,
    part_ids: list[str],
    notes: str = "",
    handling_types_by_part: dict[str, str | None] | None = None,
    fishbone_assignment_ids_by_part: dict[str, str | None] | None = None,
    quantities_by_part: dict[str, float | None] | None = None,
    model_variants_by_part: dict[str, bool] | None = None,
) -> str:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Part requirement name is required.")
    if selection_rule not in MATERIAL_SELECTION_RULES:
        raise ValueError("Choose a valid part-selection rule.")
    selected_part_ids = list(dict.fromkeys(str(part_id) for part_id in part_ids if str(part_id)))
    if not selected_part_ids:
        raise ValueError("Select at least one fishbone part.")
    normalized_quantities: dict[str, float | None] = {}
    if quantities_by_part is not None:
        unknown_part_ids = set(quantities_by_part) - set(selected_part_ids)
        if unknown_part_ids:
            raise ValueError("Part quantities may only be supplied for selected parts.")
        for part_id, raw_qty in quantities_by_part.items():
            if raw_qty is None or str(raw_qty).strip() == "":
                normalized_quantities[str(part_id)] = None
            else:
                clean_qty = _optional_nonnegative_number(raw_qty, "Part quantity")
                if clean_qty is None or clean_qty <= 0:
                    raise ValueError("Part quantity must be greater than zero.")
                normalized_quantities[str(part_id)] = clean_qty
    if quantity is None and normalized_quantities:
        positive_part_quantities = [
            float(val)
            for val in normalized_quantities.values()
            if val is not None and float(val) > 0
        ]
        quantity = positive_part_quantities[0] if positive_part_quantities else 1.0
    quantity = _optional_nonnegative_number(quantity, "Part quantity")
    if quantity is None or quantity <= 0:
        raise ValueError("Part quantity must be greater than zero.")
    normalized_handling_types: dict[str, str | None] = {}
    if handling_types_by_part is not None:
        unknown_part_ids = set(handling_types_by_part) - set(selected_part_ids)
        if unknown_part_ids:
            raise ValueError("Handling types may only be supplied for selected parts.")
        for part_id, value in handling_types_by_part.items():
            normalized_handling_types[str(part_id)] = _normalize_handling_type(value)
    normalized_assignment_ids: dict[str, str | None] = {}
    if fishbone_assignment_ids_by_part is not None:
        unknown_part_ids = set(fishbone_assignment_ids_by_part) - set(selected_part_ids)
        if unknown_part_ids:
            raise ValueError("Fishbone placements may only be supplied for selected parts.")
        for part_id, value in fishbone_assignment_ids_by_part.items():
            normalized_assignment_ids[str(part_id)] = _normalize_fishbone_assignment_id(value)
    normalized_model_variants: dict[str, bool] = {}
    if model_variants_by_part is not None:
        unknown_part_ids = set(model_variants_by_part) - set(selected_part_ids)
        if unknown_part_ids:
            raise ValueError("Model variant flags may only be supplied for selected parts.")
        for part_id, value in model_variants_by_part.items():
            normalized_model_variants[str(part_id)] = bool(value)
    if selection_rule in {"Model choice", "Choose one"} and model_variants_by_part is not None:
        if not any(normalized_model_variants.get(pid, False) for pid in selected_part_ids):
            raise ValueError(
                "Check 'Model variant' on at least one part when Selection rule is Model choice."
            )
    group_id = str(group_id or "").strip() or str(uuid4())
    timestamp = now_iso()
    try:
        with connection() as conn:
            _ensure_process_part_options_model_variant_column(conn)
            if not conn.execute(
                """SELECT 1 FROM work_elements
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (work_element_id, project_id, scenario_id),
            ).fetchone():
                raise ValueError("That process-plan work element no longer exists.")
            if not conn.execute(
                "SELECT 1 FROM assembly_sections WHERE id=? AND project_id=? AND active=1",
                (section_id, project_id),
            ).fetchone():
                raise ValueError("Choose an active fishbone section.")
            existing_group = conn.execute(
                """SELECT project_id, scenario_id, work_element_id
                   FROM process_part_groups WHERE id=?""",
                (group_id,),
            ).fetchone()
            if existing_group and (
                str(existing_group["project_id"]) != project_id
                or str(existing_group["scenario_id"]) != scenario_id
                or str(existing_group["work_element_id"]) != work_element_id
            ):
                raise ValueError("That part requirement no longer belongs to this process step.")
            existing_options = {
                str(row["part_id"]): dict(row)
                for row in conn.execute(
                    """SELECT id, part_id, handling_type, fishbone_assignment_id,
                              quantity, COALESCE(is_model_variant, 0) AS is_model_variant,
                              source_snapshot_json, source_acknowledged_at
                       FROM process_part_options WHERE group_id=?""",
                    (group_id,),
                ).fetchall()
            }
            placeholders = ",".join("?" for _ in selected_part_ids)
            section_available = {
                str(row[0]) for row in conn.execute(
                    f"""SELECT DISTINCT part_id FROM fishbone_part_assignments
                        WHERE project_id=? AND section_id=? AND part_id IN ({placeholders})""",
                    (project_id, section_id, *selected_part_ids),
                ).fetchall()
            }
            project_available = {
                str(row[0]) for row in conn.execute(
                    f"""SELECT DISTINCT part_id FROM fishbone_part_assignments
                        WHERE project_id=? AND part_id IN ({placeholders})""",
                    (project_id, *selected_part_ids),
                ).fetchall()
            }
            for pid in selected_part_ids:
                effective_ht = (
                    normalized_handling_types.get(pid)
                    if handling_types_by_part is not None
                    else _normalize_handling_type(
                        existing_options.get(pid, {}).get("handling_type")
                    )
                )
                if effective_ht == "Handle":
                    if pid not in project_available:
                        raise ValueError(
                            "Every selected part must be available in the active fishbone section."
                        )
                elif pid not in section_available:
                    raise ValueError(
                        "Every selected part must be available in the active fishbone section."
                    )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id, name,
                    selection_rule, quantity, notes, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET section_id=excluded.section_id,
                    name=excluded.name, selection_rule=excluded.selection_rule,
                    quantity=excluded.quantity, notes=excluded.notes,
                    updated_at=excluded.updated_at""",
                (
                    group_id, project_id, scenario_id, work_element_id, section_id,
                    name, selection_rule, quantity, str(notes or "").strip(), timestamp,
                ),
            )
            we_inputs = _fetch_work_element_snapshot_inputs(
                conn, project_id, scenario_id, [work_element_id]
            )
            we_snap_row = we_inputs.get(str(work_element_id), {})
            sec_row = (
                conn.execute(
                    "SELECT name FROM assembly_sections WHERE id=?",
                    (section_id,),
                ).fetchone()
                if section_id
                else None
            )
            live_mat_snap_json = json.dumps(
                build_materials_process_snapshot(
                    {
                        "station": we_snap_row.get("pitch", ""),
                        "work_element_label": we_snap_row.get("work_element_label", ""),
                        "section_name": str(sec_row["name"]) if sec_row else "",
                        "group_name": name,
                        "selection_rule": selection_rule,
                        "quantity": quantity,
                        "group_notes": str(notes or "").strip(),
                    }
                ),
                sort_keys=True,
            )
            conn.execute(
                f"""DELETE FROM process_part_options
                    WHERE group_id=? AND part_id NOT IN ({placeholders})""",
                (group_id, *selected_part_ids),
            )
            for part_id in selected_part_ids:
                existing_option = existing_options.get(part_id)
                handling_type = normalized_handling_types.get(
                    part_id,
                    existing_option.get("handling_type") if existing_option else None,
                )
                fishbone_assignment_id = normalized_assignment_ids.get(
                    part_id,
                    existing_option.get("fishbone_assignment_id") if existing_option else None,
                )
                if handling_type == "Handle":
                    option_quantity = None
                elif (
                    part_id in normalized_quantities
                    and normalized_quantities[part_id] is not None
                ):
                    option_quantity = float(normalized_quantities[part_id])
                elif existing_option and existing_option.get("quantity") is not None:
                    option_quantity = float(existing_option["quantity"])
                else:
                    option_quantity = float(quantity)
                option_mat_snap_json = (
                    json.dumps(
                        build_materials_process_snapshot(
                            {
                                "station": we_snap_row.get("pitch", ""),
                                "work_element_label": we_snap_row.get(
                                    "work_element_label", ""
                                ),
                                "section_name": str(sec_row["name"]) if sec_row else "",
                                "group_name": name,
                                "selection_rule": selection_rule,
                                "quantity": (
                                    option_quantity
                                    if option_quantity is not None
                                    else quantity
                                ),
                                "group_notes": str(notes or "").strip(),
                            }
                        ),
                        sort_keys=True,
                    )
                    if option_quantity is not None and option_quantity != quantity
                    else live_mat_snap_json
                )
                option_id = (
                    str(existing_option["id"]) if existing_option else str(uuid4())
                )
                if handling_type == "Handle" and not fishbone_assignment_id:
                    fishbone_assignment_id = _resolve_handle_fishbone_assignment_id(
                        conn,
                        project_id=project_id,
                        scenario_id=scenario_id,
                        section_id=section_id,
                        part_id=part_id,
                        exclude_process_part_option_id=option_id,
                    )
                _validate_process_part_option_handling(
                    conn,
                    project_id=project_id,
                    scenario_id=scenario_id,
                    section_id=section_id,
                    process_part_option_id=option_id,
                    part_id=part_id,
                    handling_type=handling_type,
                    fishbone_assignment_id=fishbone_assignment_id,
                    quantity=option_quantity,
                    work_element_id=work_element_id,
                )
                if selection_rule not in {"Model choice", "Choose one"}:
                    is_model_variant_int = 0
                elif model_variants_by_part is not None:
                    is_model_variant_int = (
                        1 if normalized_model_variants.get(part_id, False) else 0
                    )
                elif existing_option is not None:
                    is_model_variant_int = (
                        1 if bool(existing_option.get("is_model_variant")) else 0
                    )
                else:
                    is_model_variant_int = 1
                if existing_option:
                    prev_ht = str(existing_option.get("handling_type") or "").strip()
                    new_ht = str(handling_type or "").strip()
                    existing_snap = str(existing_option.get("source_snapshot_json") or "").strip()
                    existing_ack = str(existing_option.get("source_acknowledged_at") or "").strip()
                    if prev_ht and prev_ht == new_ht and existing_snap:
                        snap_to_save = existing_snap
                        ack_to_save = existing_ack or timestamp
                    else:
                        snap_to_save = option_mat_snap_json
                        ack_to_save = timestamp if new_ht else ""
                    conn.execute(
                        """UPDATE process_part_options
                           SET handling_type=?, fishbone_assignment_id=?,
                               quantity=?, is_model_variant=?,
                               source_snapshot_json=?,
                               source_acknowledged_at=?, updated_at=?
                           WHERE id=? AND group_id=?""",
                        (
                            handling_type,
                            fishbone_assignment_id,
                            option_quantity,
                            is_model_variant_int,
                            snap_to_save,
                            ack_to_save,
                            timestamp,
                            option_id,
                            group_id,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO process_part_options
                           (id, group_id, part_id, handling_type,
                            fishbone_assignment_id, quantity, is_model_variant,
                            source_snapshot_json, source_acknowledged_at,
                            updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            option_id,
                            group_id,
                            part_id,
                            handling_type,
                            fishbone_assignment_id,
                            option_quantity,
                            is_model_variant_int,
                            option_mat_snap_json,
                            timestamp if handling_type else "",
                            timestamp,
                        ),
                    )
    except sqlite3.IntegrityError as exc:
        raise ValueError("Part requirement names must be unique within a process step.") from exc
    return group_id

def set_part_weight_lb(project_id: str, part_id: str, weight_lb) -> str:
    """Set or clear a project-wide Parts Catalog weight in pounds."""
    weight = _optional_nonnegative_number(weight_lb, "Part weight")
    if weight is not None and not math.isfinite(weight):
        raise ValueError("Part weight must be a finite number.")
    timestamp = now_iso()
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM parts WHERE id=? AND project_id=?",
            (part_id, project_id),
        ).fetchone():
            raise ValueError("That part no longer exists in this project.")
        conn.execute(
            "UPDATE parts SET weight_lb=?, updated_at=? WHERE id=? AND project_id=?",
            (weight, timestamp, part_id, project_id),
        )
    return timestamp

def set_process_part_option_handling_type(
    project_id: str,
    scenario_id: str,
    process_part_option_id: str,
    handling_type: str | None,
    fishbone_assignment_id: str | None = None,
) -> str:
    """Classify one scenario-specific Process part-use, or restore compatibility NULL."""
    normalized = _normalize_handling_type(handling_type)
    timestamp = now_iso()
    with connection() as conn:
        option = conn.execute(
            """SELECT option.id, option.part_id, option.fishbone_assignment_id,
                      COALESCE(option.quantity, group_row.quantity, 1.0) AS effective_quantity,
                      group_row.section_id, group_row.work_element_id
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               WHERE option.id=? AND group_row.project_id=? AND group_row.scenario_id=?""",
            (process_part_option_id, project_id, scenario_id),
        ).fetchone()
        if not option:
            raise ValueError("That Process part-use no longer exists in this scenario.")
        option_we_id = str(option["work_element_id"] or "").strip() or None
        option_qty = (
            float(option["effective_quantity"] or 1.0)
            if normalized == "Consume"
            else None
        )
        target_assignment_id = (
            _normalize_fishbone_assignment_id(fishbone_assignment_id)
            or _normalize_fishbone_assignment_id(option["fishbone_assignment_id"])
        )
        if not target_assignment_id and normalized is not None:
            # Check if there is a fishbone placement for this part in this section
            sec_assignments = conn.execute(
                """SELECT id FROM fishbone_part_assignments
                   WHERE project_id=? AND section_id=? AND part_id=?
                   ORDER BY sequence, id""",
                (project_id, str(option["section_id"] or ""), str(option["part_id"])),
            ).fetchall()
            if not sec_assignments and normalized == "Handle":
                sec_assignments = conn.execute(
                    """SELECT id FROM fishbone_part_assignments
                       WHERE project_id=? AND part_id=?
                       ORDER BY sequence, id""",
                    (project_id, str(option["part_id"])),
                ).fetchall()
            if len(sec_assignments) == 1:
                target_assignment_id = str(sec_assignments[0]["id"])
            elif len(sec_assignments) > 1:
                for sa in sec_assignments:
                    sa_id = str(sa["id"])
                    try:
                        _validate_process_part_option_handling(
                            conn,
                            project_id=project_id,
                            scenario_id=scenario_id,
                            section_id=str(option["section_id"] or ""),
                            process_part_option_id=process_part_option_id,
                            part_id=str(option["part_id"]),
                            handling_type=normalized,
                            fishbone_assignment_id=sa_id,
                            quantity=option_qty,
                            work_element_id=option_we_id,
                        )
                        target_assignment_id = sa_id
                        break
                    except ValueError:
                        continue
                if not target_assignment_id:
                    target_assignment_id = str(sec_assignments[0]["id"])

        _validate_process_part_option_handling(
            conn,
            project_id=project_id,
            scenario_id=scenario_id,
            section_id=str(option["section_id"] or ""),
            process_part_option_id=process_part_option_id,
            part_id=str(option["part_id"]),
            handling_type=normalized,
            fishbone_assignment_id=target_assignment_id,
            quantity=option_qty,
            work_element_id=option_we_id,
        )
        opt_inputs = _fetch_part_option_snapshot_inputs(
            conn, project_id, scenario_id, [process_part_option_id]
        )
        opt_snap_row = opt_inputs.get(str(process_part_option_id))
        live_snap_json = (
            json.dumps(build_materials_process_snapshot(opt_snap_row), sort_keys=True)
            if opt_snap_row
            else ""
        )
        ack_at = timestamp if normalized else ""
        conn.execute(
            """UPDATE process_part_options
               SET handling_type=?, fishbone_assignment_id=?,
                   source_snapshot_json=?, source_acknowledged_at=?,
                   updated_at=?
               WHERE id=?""",
            (
                normalized,
                target_assignment_id,
                live_snap_json,
                ack_at,
                timestamp,
                process_part_option_id,
            ),
        )
    return timestamp

@cached_store_read
def work_element_criticality(
    project_id: str, scenario_id: str
) -> dict[str, list[str]]:
    """Return live CTQ and Safety tags keyed by scenario-owned Process step."""
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        result: dict[str, list[str]] = {
            str(row["id"]): []
            for row in conn.execute(
                """SELECT id FROM work_elements
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
        }
        placeholders = ",".join("?" for _ in PFMEA_CTQ_CLASSIFICATIONS)
        for row in conn.execute(
            f"""SELECT DISTINCT entry.work_element_id
                FROM pfmea_entries entry
                JOIN work_elements work
                  ON work.id=entry.work_element_id
                 AND work.project_id=entry.project_id
                 AND work.scenario_id=entry.scenario_id
                WHERE entry.project_id=? AND entry.scenario_id=?
                  AND entry.class_code IN ({placeholders})""",
            (project_id, scenario_id, *PFMEA_CTQ_CLASSIFICATIONS),
        ).fetchall():
            work_element_id = str(row["work_element_id"])
            if work_element_id in result:
                result[work_element_id].append("CTQ")
        for row in conn.execute(
            """SELECT DISTINCT requirement.work_element_id
               FROM safety_requirements requirement
               JOIN work_elements work
                 ON work.id=requirement.work_element_id
                AND work.project_id=requirement.project_id
                AND work.scenario_id=requirement.scenario_id
               WHERE requirement.project_id=? AND requirement.scenario_id=?
                 AND requirement.active=1""",
            (project_id, scenario_id),
        ).fetchall():
            work_element_id = str(row["work_element_id"])
            if work_element_id in result:
                result[work_element_id].append("Safety")
    return result

def delete_process_part_groups(
    project_id: str, scenario_id: str, group_ids: list[str]
) -> int:
    """Delete validated process-part groups together and reopen their source parts."""
    normalized_ids = list(
        dict.fromkeys(
            str(group_id).strip()
            for group_id in group_ids
            if str(group_id).strip()
        )
    )
    if not normalized_ids:
        return 0
    placeholders = ", ".join("?" for _ in normalized_ids)
    with connection() as conn:
        group_rows = conn.execute(
            f"""SELECT id, name, work_element_id FROM process_part_groups
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *normalized_ids),
        ).fetchall()
        found_ids = {str(row["id"]) for row in group_rows}
        missing_ids = [group_id for group_id in normalized_ids if group_id not in found_ids]
        if missing_ids:
            raise ValueError(
                "One or more selected part pairings no longer exist. Refresh and try again."
            )
        affected_work_element_ids = {
            str(row["work_element_id"]) for row in group_rows
        }
        names = [str(row["name"] or "") for row in group_rows if row["name"]]
        label = names[0] if len(names) == 1 else f"{len(normalized_ids)} process part pairings ({', '.join(names[:3])})"
        with capture_deletion_to_recycle_bin(
            conn,
            project_id=project_id,
            scenario_id=scenario_id,
            entity_type="Process Part Pairing",
            entity_table="process_part_groups",
            entity_id=normalized_ids[0] if len(normalized_ids) == 1 else "",
            entity_label=label,
        ):
            cursor = conn.execute(
                f"""DELETE FROM process_part_groups
                    WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
                (project_id, scenario_id, *normalized_ids),
            )
            timestamp = now_iso()
            for work_element_id in affected_work_element_ids:
                remaining = conn.execute(
                    """SELECT 1 FROM process_part_groups
                       WHERE project_id=? AND scenario_id=? AND work_element_id=? LIMIT 1""",
                    (project_id, scenario_id, work_element_id),
                ).fetchone()
                if not remaining:
                    conn.execute(
                        """UPDATE yamazumi_elements
                           SET process_sync_status='Needs IE review', updated_at=?
                           WHERE project_id=? AND process_element_id=?""",
                        (timestamp, project_id, work_element_id),
                    )
        return int(cursor.rowcount)

def delete_process_part_group(
    project_id: str, scenario_id: str, group_id: str
) -> bool:
    return bool(delete_process_part_groups(project_id, scenario_id, [group_id]))


def unlink_part_from_process_group(
    project_id: str, scenario_id: str, group_id: str, part_id: str
) -> int:
    """Unlink one part option from a process-part group, or delete the group if it was the only part."""
    norm_group_id = str(group_id or "").strip()
    norm_part_id = str(part_id or "").strip()
    if not norm_group_id or not norm_part_id:
        return 0
    with connection() as conn:
        group_row = conn.execute(
            """SELECT id, name, selection_rule, work_element_id
               FROM process_part_groups
               WHERE project_id=? AND scenario_id=? AND id=?""",
            (project_id, scenario_id, norm_group_id),
        ).fetchone()
        if not group_row:
            raise ValueError(
                "One or more selected part pairings no longer exist. Refresh and try again."
            )
        options = conn.execute(
            """SELECT opt.id, opt.part_id, p.part_number, p.description
               FROM process_part_options opt
               LEFT JOIN parts p ON p.id = opt.part_id
               WHERE opt.group_id=?
               ORDER BY p.part_number, opt.id""",
            (norm_group_id,),
        ).fetchall()
        matching_opts = [
            row for row in options if str(row["part_id"]) == norm_part_id
        ]
        if not matching_opts:
            raise ValueError(
                "That part is no longer linked to this PAAG element. Refresh and try again."
            )
        if len(options) > 1:
            timestamp = now_iso()
            cursor = conn.execute(
                "DELETE FROM process_part_options WHERE group_id=? AND part_id=?",
                (norm_group_id, norm_part_id),
            )
            conn.execute(
                "UPDATE process_part_groups SET updated_at=? WHERE id=?",
                (timestamp, norm_group_id),
            )
            return int(cursor.rowcount)
    return delete_process_part_groups(project_id, scenario_id, [norm_group_id])

@cached_store_read
def pin_map_for_scenario(project_id: str, scenario_id: str) -> pd.DataFrame:
    """Load pitches and their explicitly linked Process work for one scenario."""
    rows = pd.DataFrame(query(
        """SELECT p.id AS pitch_id, p.area_id, a.name AS area_name,
                  a.section_id,
                  p.pitch_number, p.pitch_name, p.pitch_type,
                  p.status AS pitch_status, p.sequence AS pitch_sequence,
                  work.id AS process_element_id,
                  work.sequence AS process_sequence,
                  work.operation AS work_element,
                  work.description AS process_description,
                  work.cycle_time_s, work.tool, work.torque,
                  work.quality_requirement, work.ergo_requirement,
                  work.location, work.unit_orientation,
                  work.model_applicability,
                  work.status AS process_status
           FROM yamazumi_pitches p
           JOIN yamazumi_areas a ON a.id=p.area_id
           LEFT JOIN yamazumi_elements yamazumi
             ON yamazumi.pitch_id=p.id AND yamazumi.project_id=p.project_id
           LEFT JOIN work_elements work
             ON work.id=yamazumi.process_element_id
            AND work.project_id=p.project_id
            AND work.scenario_id=a.scenario_id
           WHERE p.project_id=? AND a.scenario_id=?
           ORDER BY a.name, p.sequence, p.pitch_number,
                    work.sequence, work.operation""",
        (project_id, scenario_id),
    ))
    if rows.empty:
        return pd.DataFrame({
            "pitch_id": pd.Series(dtype="string"),
            "area_id": pd.Series(dtype="string"),
            "area_name": pd.Series(dtype="string"),
            "section_id": pd.Series(dtype="string"),
            "pitch_number": pd.Series(dtype="string"),
            "pitch_name": pd.Series(dtype="string"),
            "pitch_type": pd.Series(dtype="string"),
            "pitch_status": pd.Series(dtype="string"),
            "pitch_sequence": pd.Series(dtype="Int64"),
            "process_element_id": pd.Series(dtype="string"),
            "process_sequence": pd.Series(dtype="Int64"),
            "work_element": pd.Series(dtype="string"),
            "process_description": pd.Series(dtype="string"),
            "cycle_time_s": pd.Series(dtype="Float64"),
            "tool": pd.Series(dtype="string"),
            "torque": pd.Series(dtype="string"),
            "quality_requirement": pd.Series(dtype="string"),
            "ergo_requirement": pd.Series(dtype="string"),
            "location": pd.Series(dtype="string"),
            "unit_orientation": pd.Series(dtype="string"),
            "model_applicability": pd.Series(dtype="string"),
            "process_status": pd.Series(dtype="string"),
        })
    rows = rows.drop_duplicates(
        subset=["pitch_id", "process_element_id"], keep="first"
    )
    linked_pitch_ids = set(
        rows.loc[rows["process_element_id"].notna(), "pitch_id"].astype(str)
    )
    rows = rows.loc[
        ~(
            rows["pitch_id"].astype(str).isin(linked_pitch_ids)
            & rows["process_element_id"].isna()
        )
    ]
    return rows.reset_index(drop=True)

def reconcile_yamazumi_to_process(project_id: str, scenario_id: str, element_ids: list[str]) -> int:
    """Accept Yamazumi station/time changes while retaining IE-authored process details."""
    if not element_ids:
        return 0
    timestamp = now_iso()
    reconciled_count = 0
    processed_member_ids: set[str] = set()
    with connection() as conn:
        for raw_eid in element_ids:
            clean_eid = str(raw_eid or "").strip()
            if not clean_eid or clean_eid in processed_member_ids:
                continue
            group = _find_same_pitch_yamazumi_group_for_element(
                conn, project_id, scenario_id, clean_eid
            )
            if not group:
                continue
            member_ids = [
                str(mid)
                for mid in (group.get("_member_ids") or [clean_eid])
                if str(mid).strip()
            ]
            processed_member_ids.update(member_ids)
            station = str(group.get("pitch_number") or "Unassigned")
            model_variants = list(
                group.get("_variants")
                or parse_yamazumi_model_variants(
                    group.get("model_variants"), group.get("model_variant")
                )
            )
            model_applicability = (
                "All"
                if any(value.casefold() in {"base", "all", "all models"} for value in model_variants)
                else ", ".join(model_variants)
            )
            process_id = str(group.get("process_element_id") or "").strip()
            if process_id:
                exists = conn.execute(
                    "SELECT 1 FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
                    (process_id, project_id, scenario_id),
                ).fetchone()
            else:
                exists = None
            if not exists and station and station != "Unassigned":
                desc_str = str(group.get("description") or "").strip()
                if desc_str:
                    candidate = conn.execute(
                        """SELECT w.id
                           FROM work_elements w
                           WHERE w.project_id=? AND w.scenario_id=?
                             AND LOWER(TRIM(COALESCE(w.station, ''))) = LOWER(TRIM(?))
                             AND LOWER(TRIM(COALESCE(w.operation, ''))) = LOWER(TRIM(?))
                             AND NOT EXISTS (
                                 SELECT 1 FROM yamazumi_elements y
                                 JOIN yamazumi_areas a ON a.id = y.area_id AND a.project_id = y.project_id
                                 WHERE y.project_id = w.project_id
                                   AND a.scenario_id = w.scenario_id
                                   AND y.process_element_id = w.id
                             )
                           ORDER BY w.sequence, w.id
                           LIMIT 1""",
                        (project_id, scenario_id, station, desc_str),
                    ).fetchone()
                    if candidate:
                        process_id = str(candidate["id"])
                        exists = candidate
            if exists:
                conn.execute(
                    """UPDATE work_elements SET operation=COALESCE(NULLIF(TRIM(?), ''), operation), station=?, cycle_time_s=?, model_applicability=?, updated_at=?
                       WHERE id=? AND project_id=? AND scenario_id=?""",
                    (
                        str(group.get("description") or ""),
                        station, float(group.get("time_s") or 0),
                        model_applicability,
                        timestamp, process_id, project_id, scenario_id,
                    ),
                )
            else:
                next_sequence = conn.execute(
                    """SELECT COALESCE(MAX(sequence), 0) + 10 FROM work_elements
                       WHERE project_id=? AND scenario_id=?""",
                    (project_id, scenario_id),
                ).fetchone()[0]
                process_id = _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    scenario_id,
                    {
                        "sequence": next_sequence,
                        "station": station,
                        "operation": str(group.get("description") or ""),
                        "description": f"Yamazumi area: {group.get('area_name') or ''}",
                        "cycle_time_s": float(group.get("time_s") or 0),
                        "part_number": "",
                        "tool": "",
                        "torque": "",
                        "quality_requirement": "",
                        "ergo_requirement": "",
                        "location": station,
                        "conveyor_height_in": None,
                        "platform_height_in": None,
                        "pit_depth_in": None,
                        "model_applicability": model_applicability,
                        "status": "Draft",
                    },
                    timestamp,
                )
            member_placeholders = ",".join("?" for _ in member_ids)
            conn.execute(
                f"""UPDATE yamazumi_elements SET process_element_id=?, process_sync_status='Synced', updated_at=?
                    WHERE project_id=? AND id IN ({member_placeholders})""",
                (process_id, timestamp, project_id, *member_ids),
            )
            reconciled_count += 1
    return reconciled_count

def _op_id_depth_letter(depth: int) -> str:
    """Return a lowercase spreadsheet-style letter for a zero-based depth."""
    value = depth + 1
    letters = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters

def parse_yamazumi_pitch_address(value: object) -> dict[str, object]:
    """Decode the approved Pitch convention into natural-order components."""
    address = str(value or "").strip()
    match = _YAMAZUMI_PITCH_ADDRESS_PATTERN.fullmatch(address)
    if not match:
        return {
            "address": address,
            "parsed": False,
            "subline_number": 0,
            "work_area_letters": "",
            "work_area_number": 0,
            "position_number": 0,
        }
    return {
        "address": address,
        "parsed": True,
        "subline_number": int(match.group("subline")),
        "work_area_letters": match.group("work_area_letters").casefold(),
        "work_area_number": int(match.group("work_area_number")),
        "position_number": int(match.group("position")),
    }

@cached_store_read
def work_element_op_contexts(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | None = None,
) -> dict[str, dict]:
    """Compute live Op ID labels and physical picker order without persisting them."""
    requested_ids = None
    if work_element_ids is not None:
        requested_ids = list(dict.fromkeys(
            str(value or "").strip() for value in work_element_ids
            if str(value or "").strip()
        ))
        if not requested_ids:
            return {}

    with connection() as conn:
        scenario = conn.execute(
            "SELECT id FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")

        parameters: list[object] = [project_id, scenario_id]
        work_filter = ""
        if requested_ids is not None:
            placeholders = ",".join("?" for _ in requested_ids)
            work_filter = f" AND id IN ({placeholders})"
            parameters.extend(requested_ids)
        work_rows = conn.execute(
            f"""SELECT id, sequence AS work_sequence FROM work_elements
                WHERE project_id=? AND scenario_id=?{work_filter}
                ORDER BY sequence, id""",
            tuple(parameters),
        ).fetchall()
        work_ids = [str(row["id"]) for row in work_rows]
        work_sequence_by_id = {
            str(row["id"]): int(row["work_sequence"] or 0) for row in work_rows
        }
        if requested_ids is not None and set(work_ids) != set(requested_ids):
            raise ValueError(
                "One or more Process at a Glance Work Elements are missing or belong to "
                "another planning scenario."
            )
        if not work_ids:
            return {}

        yamazumi_rows = conn.execute(
            """SELECT element.id AS yamazumi_element_id,
                      element.process_element_id, element.pitch_id,
                      element.sequence, element.description,
                      element.time_s, element.model_variant, element.model_variants,
                      COALESCE(NULLIF(TRIM(element.work_type), ''), 'Cycle') AS work_type,
                      area.id AS area_id, area.section_id,
                      pitch.id AS resolved_pitch_id, pitch.pitch_number,
                      pitch.sequence AS pitch_sequence
               FROM yamazumi_elements element
               JOIN yamazumi_areas area
                 ON area.id=element.area_id
                AND area.project_id=element.project_id
                AND area.scenario_id=?
               LEFT JOIN yamazumi_pitches pitch
                 ON pitch.id=element.pitch_id
                AND pitch.project_id=element.project_id
                AND pitch.area_id=area.id
               WHERE element.project_id=?
               ORDER BY element.sequence,
                        element.description COLLATE NOCASE,
                        element.id""",
            (scenario_id, project_id),
        ).fetchall()
        conn_rows = conn.execute(
            """SELECT from_section_id, to_section_id, connection_type
               FROM assembly_section_connections WHERE project_id=?""",
            (project_id,),
        ).fetchall()

    subassembly_destinations: dict[str, list[str]] = {}
    for r in conn_rows:
        if r["connection_type"] == "subassembly":
            subassembly_destinations.setdefault(str(r["from_section_id"]), []).append(str(r["to_section_id"]))

    grouped_yamazumi_rows = _group_same_pitch_yamazumi_rows(yamazumi_rows)
    links_by_work: dict[str, list[dict]] = {}
    stack_rows: dict[str, list[dict]] = {}
    for row in grouped_yamazumi_rows:
        process_id = str(row["process_element_id"] or "").strip()
        if process_id:
            links_by_work.setdefault(process_id, []).append(row)
        pitch_id = str(row["resolved_pitch_id"] or "").strip()
        if pitch_id:
            stack_rows.setdefault(pitch_id, []).append(row)
    stack_positions = {
        str(row["yamazumi_element_id"]): position
        for rows in stack_rows.values()
        for position, row in enumerate(rows, start=1)
    }

    walk = assembly_section_walk_order(project_id)
    section_by_id = {
        str(row["id"]): row.to_dict() for _, row in walk.iterrows()
    } if not walk.empty else {}

    def _norm_pid(row_or_dict) -> str:
        val = row_or_dict.get("parent_id")
        if val is None or pd.isna(val):
            return ""
        return str(val).strip()

    def _is_root_assembly(row_or_dict) -> bool:
        sec_type = str(row_or_dict.get("section_type") or "")
        if sec_type == "Main spine":
            return True
        if sec_type == "Assembly" and not _norm_pid(row_or_dict):
            return True
        return False

    def _is_child_assembly(row_or_dict) -> bool:
        sec_type = str(row_or_dict.get("section_type") or "")
        if sec_type == "Subassembly":
            return True
        if sec_type == "Assembly" and bool(_norm_pid(row_or_dict)):
            return True
        return False

    mainline_numbers = {
        str(row["id"]): position
        for position, (_, row) in enumerate(
            (r for r in walk.iterrows() if _is_root_assembly(r[1])), start=1
        )
    } if not walk.empty else {}
    support_numbers = {
        str(row["id"]): position
        for position, (_, row) in enumerate(
            walk.loc[walk["section_type"].eq("Support Operations")].iterrows(), start=1
        )
    } if not walk.empty else {}
    subassembly_children: dict[str, list[str]] = {}
    for section_id, section in section_by_id.items():
        if not _is_child_assembly(section):
            continue
        parent_id = _norm_pid(section)
        subassembly_children.setdefault(parent_id, []).append(section_id)
    for child_ids in subassembly_children.values():
        child_ids.sort(
            key=lambda child_id: (
                int(section_by_id[child_id]["sequence"]),
                str(section_by_id[child_id]["name"]),
            )
        )

    def fishbone_prefix(section_id: str) -> str | None:
        section = section_by_id.get(section_id)
        if not section:
            return None
        if _is_root_assembly(section):
            number = mainline_numbers.get(section_id)
            return f"M{number}" if number else None
        if str(section.get("section_type") or "") == "Support Operations":
            number = support_numbers.get(section_id)
            return f"SO{number}" if number else None

        reverse_path: list[str] = []
        visited: set[str] = set()
        current_id = section_id
        mainline_id = ""
        while current_id and current_id not in visited:
            visited.add(current_id)
            current = section_by_id.get(current_id)
            if not current:
                return None
            if _is_root_assembly(current):
                mainline_id = current_id
                break
            if not _is_child_assembly(current):
                return None
            reverse_path.append(current_id)
            current_id = _norm_pid(current)
        if not mainline_id or mainline_id not in mainline_numbers:
            return None

        path = list(reversed(reverse_path))
        lineages = subassembly_children.get(mainline_id, [])
        if not path or path[0] not in lineages:
            return None
        lineage_number = lineages.index(path[0]) + 1
        branch_path: list[str] = []
        for depth, path_section_id in enumerate(path):
            if depth:
                parent_id = path[depth - 1]
                siblings = subassembly_children.get(parent_id, [])
                if path_section_id not in siblings:
                    return None
                if len(siblings) > 1:
                    branch_path.append(str(siblings.index(path_section_id) + 1))
            depth_designator = _op_id_depth_letter(depth) + "".join(branch_path)

        def find_mainlines(sid: str, visited_set: set[str]) -> list[str]:
            if sid in visited_set:
                return []
            visited_set.add(sid)
            sec = section_by_id.get(sid)
            if not sec:
                return []
            if _is_root_assembly(sec):
                return [sid]
            parents = subassembly_destinations.get(sid) or ([_norm_pid(sec)] if _norm_pid(sec) else [])
            roots: list[str] = []
            for p in parents:
                if p:
                    roots.extend(find_mainlines(p, visited_set.copy()))
            return list(dict.fromkeys(roots))

        all_mainlines = find_mainlines(section_id, set())
        mainline_nums = sorted([mainline_numbers[m] for m in all_mainlines if m in mainline_numbers])
        if len(mainline_nums) > 1:
            mainline_tag = "+".join(f"M{num}" for num in mainline_nums) + "."
        else:
            mainline_tag = f"M{mainline_numbers[mainline_id]}"

        return f"{mainline_tag}S{lineage_number}{depth_designator}"

    section_order = {
        str(row["id"]): position
        for position, (_, row) in enumerate(walk.iterrows())
    } if not walk.empty else {}
    result: dict[str, dict] = {}

    def incomplete(work_id: str, label: str) -> None:
        result[work_id] = {
            "op_id": label,
            "complete": False,
            "sort_key": (
                1,
                work_sequence_by_id.get(work_id, 0),
                work_id,
            ),
        }

    for work_id in work_ids:
        links = links_by_work.get(work_id, [])
        if not links:
            incomplete(work_id, "Yamazumi link required")
            continue
        if len(links) != 1:
            incomplete(work_id, "Unique Yamazumi link required")
            continue
        link = links[0]
        pitch_id = str(link["resolved_pitch_id"] or "").strip()
        if not pitch_id:
            incomplete(work_id, "Yamazumi pitch required")
            continue
        section_id = str(link["section_id"] or "").strip()
        if not section_id:
            incomplete(work_id, "Fishbone link required")
            continue
        prefix = fishbone_prefix(section_id)
        if not prefix:
            incomplete(work_id, "Fishbone hierarchy required")
            continue
        position = stack_positions.get(str(link["yamazumi_element_id"]))
        if position is None:
            incomplete(work_id, "Yamazumi link required")
            continue
        pitch_address = parse_yamazumi_pitch_address(link["pitch_number"])
        result[work_id] = {
            "op_id": f"{prefix}.{link['pitch_number']}.{position}",
            "complete": True,
            "sort_key": (
                0,
                section_order.get(section_id, len(section_order)),
                0 if pitch_address["parsed"] else 1,
                int(pitch_address["subline_number"]),
                str(pitch_address["work_area_letters"]),
                int(pitch_address["work_area_number"]),
                int(pitch_address["position_number"]),
                int(link["pitch_sequence"] or 0),
                int(link["sequence"] or 0),
                position,
                work_id,
            ),
        }

    ordered_ids = sorted(result, key=lambda work_id: result[work_id]["sort_key"])
    for sort_order, work_id in enumerate(ordered_ids):
        result[work_id]["sort_order"] = sort_order
        result[work_id].pop("sort_key", None)
    return result

@cached_store_read
def work_element_op_ids(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | None = None,
) -> dict[str, str]:
    """Compute scenario-scoped, human-readable Op IDs without persisting them."""
    contexts = work_element_op_contexts(project_id, scenario_id, work_element_ids)
    return {work_id: str(context["op_id"]) for work_id, context in contexts.items()}

@cached_store_read
def work_element_op_id(project_id: str, scenario_id: str, work_element_id: str) -> str:
    """Compute one Op ID through the shared batch implementation."""
    normalized_id = str(work_element_id or "").strip()
    if not normalized_id:
        raise ValueError("Choose a Process at a Glance Work Element.")
    return work_element_op_ids(project_id, scenario_id, [normalized_id])[normalized_id]


@cached_store_read
def work_element_validation_contexts(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | None = None,
) -> dict[str, dict]:
    """Compute PAAG technical completeness and validation gating status (Option A) per work element."""
    op_contexts = work_element_op_contexts(project_id, scenario_id, work_element_ids)
    normalized_ids = list(dict.fromkeys(str(wid).strip() for wid in (work_element_ids or []) if str(wid).strip()))
    with connection() as conn:
        if normalized_ids:
            placeholders = ", ".join("?" for _ in normalized_ids)
            rows = conn.execute(
                f"""SELECT id, operation, status
                    FROM work_elements
                    WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
                (project_id, scenario_id, *normalized_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, operation, status
                   FROM work_elements
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()

        validated_scenario_count = int(
            conn.execute(
                """SELECT COUNT(*)
                   FROM work_elements
                   WHERE project_id=? AND scenario_id=? AND COALESCE(status, 'Draft')='Validated'""",
                (project_id, scenario_id),
            ).fetchone()[0]
        )
        yamazumi_scenario_count = int(
            conn.execute(
                """SELECT COUNT(*)
                   FROM yamazumi_elements y
                   JOIN yamazumi_areas a ON a.id=y.area_id
                   WHERE y.project_id=? AND a.scenario_id=?""",
                (project_id, scenario_id),
            ).fetchone()[0]
        )

        unclassified_counts: dict[str, int] = {}
        if normalized_ids:
            placeholders = ", ".join("?" for _ in normalized_ids)
            part_rows = conn.execute(
                f"""SELECT group_row.work_element_id, COUNT(*) AS cnt
                    FROM process_part_options option
                    JOIN process_part_groups group_row ON group_row.id=option.group_id
                    JOIN parts part
                      ON part.id=option.part_id AND part.project_id=group_row.project_id
                    LEFT JOIN part_scenario_activity activity
                      ON activity.project_id=group_row.project_id
                     AND activity.scenario_id=group_row.scenario_id
                     AND activity.part_id=option.part_id
                    WHERE group_row.project_id=? AND group_row.scenario_id=?
                      AND COALESCE(activity.active, 1)=1
                      AND COALESCE(TRIM(option.handling_type), '')=''
                      AND group_row.work_element_id IN ({placeholders})
                    GROUP BY group_row.work_element_id""",
                (project_id, scenario_id, *normalized_ids),
            ).fetchall()
        else:
            part_rows = conn.execute(
                """SELECT group_row.work_element_id, COUNT(*) AS cnt
                   FROM process_part_options option
                   JOIN process_part_groups group_row ON group_row.id=option.group_id
                   JOIN parts part
                     ON part.id=option.part_id AND part.project_id=group_row.project_id
                   LEFT JOIN part_scenario_activity activity
                     ON activity.project_id=group_row.project_id
                    AND activity.scenario_id=group_row.scenario_id
                    AND activity.part_id=option.part_id
                   WHERE group_row.project_id=? AND group_row.scenario_id=?
                     AND COALESCE(activity.active, 1)=1
                     AND COALESCE(TRIM(option.handling_type), '')=''
                   GROUP BY group_row.work_element_id""",
                (project_id, scenario_id),
            ).fetchall()
        for prow in part_rows:
            unclassified_counts[str(prow["work_element_id"])] = int(prow["cnt"] or 0)

    result: dict[str, dict] = {}
    for row in rows:
        wid = str(row["id"])
        op_ctx = op_contexts.get(wid) or {}
        op_id = str(op_ctx.get("op_id") or "")
        op_complete = bool(op_ctx.get("complete"))
        has_operation = bool(str(row["operation"] or "").strip())
        unclassified_cnt = int(unclassified_counts.get(wid, 0))
        technically_complete = bool(op_complete and has_operation and unclassified_cnt == 0)
        status_val = str(row["status"] or "Draft").strip() or "Draft"
        is_validated_status = status_val == "Validated"
        pfmea_eligible = bool(technically_complete and is_validated_status)

        missing_reasons: list[str] = []
        if not op_complete:
            missing_reasons.append(f"Incomplete Op ID ({op_id or 'Unassigned'})")
        if not has_operation:
            missing_reasons.append("Missing Operation name")
        if unclassified_cnt > 0:
            missing_reasons.append(f"{unclassified_cnt} Unclassified part handling(s)")
        if not is_validated_status:
            missing_reasons.append(f"PAAG Status is '{status_val}' (must be 'Validated')")

        result[wid] = {
            "work_element_id": wid,
            "op_id": op_id,
            "op_complete": op_complete,
            "has_operation": has_operation,
            "unclassified_part_count": unclassified_cnt,
            "technically_complete": technically_complete,
            "status": status_val,
            "is_validated_status": is_validated_status,
            "pfmea_eligible": pfmea_eligible,
            "missing_reasons": missing_reasons,
            "validated_scenario_count": validated_scenario_count,
            "paag_gate_enforced": bool(
                is_validated_status or validated_scenario_count > 0 or yamazumi_scenario_count > 0
            ),
        }
    return result

@cached_store_read
def get_pitch_visual_media(
    project_id: str, scenario_id: str, pitch_id: str
) -> list[dict]:
    """Return all visual media records and their tagged work elements for a pitch.

    A visual aid appears on this pitch if:
    1. It is tagged to one or more work elements currently assigned to this pitch in Yamazumi, OR
    2. It has no work element tags (general pitch visual) and its base pitch_id is this pitch.
    """
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        return []
    with connection() as conn:
        pitch = conn.execute(
            """SELECT pitch.id, pitch.pitch_number, pitch.pitch_name
               FROM yamazumi_pitches pitch
               WHERE pitch.id=? AND pitch.project_id=?""",
            (normalized_pitch_id, project_id),
        ).fetchone()
        if not pitch:
            return []

        pitch_number = pitch["pitch_number"]
        pitch_name = pitch["pitch_name"]
        _db_core._sync_part_sourced_visual_media(conn, project_id=project_id)

        media_rows = conn.execute(
            """SELECT DISTINCT m.*
               FROM process_visual_media m
               WHERE m.project_id=? AND m.scenario_id=?
                 AND (
                     EXISTS (
                         SELECT 1 FROM process_visual_media_tags t
                         JOIN yamazumi_elements y ON (
                             y.process_element_id = t.work_element_id
                             OR (y.process_element_id IS NULL AND y.id = t.work_element_id)
                         )
                         JOIN yamazumi_areas a ON a.id = y.area_id AND a.scenario_id = ?
                         WHERE t.media_id = m.id
                           AND t.project_id = ?
                           AND t.scenario_id = ?
                           AND y.project_id = ?
                           AND y.pitch_id = ?
                     )
                     OR EXISTS (
                         SELECT 1 FROM process_visual_media_tags t
                         JOIN work_elements w
                           ON w.id = t.work_element_id
                          AND w.project_id = t.project_id
                          AND w.scenario_id = t.scenario_id
                         WHERE t.media_id = m.id
                           AND t.project_id = ?
                           AND t.scenario_id = ?
                           AND NOT EXISTS (
                               SELECT 1 FROM yamazumi_elements y2
                               JOIN yamazumi_areas a2 ON a2.id = y2.area_id AND a2.scenario_id = t.scenario_id
                               WHERE y2.project_id = t.project_id
                                 AND y2.process_element_id = t.work_element_id
                                 AND y2.pitch_id IS NOT NULL
                           )
                           AND (
                               m.pitch_id = ?
                               OR LOWER(TRIM(COALESCE(w.station, ''))) = LOWER(TRIM(?))
                           )
                     )
                     OR (
                         m.pitch_id = ?
                         AND NOT EXISTS (
                             SELECT 1 FROM process_visual_media_tags t
                             WHERE t.media_id = m.id
                               AND t.project_id = ?
                               AND t.scenario_id = ?
                         )
                     )
                 )
               ORDER BY m.sequence, m.created_at, m.id""",
            (
                project_id, scenario_id,
                scenario_id, project_id, scenario_id, project_id, normalized_pitch_id,
                project_id, scenario_id, normalized_pitch_id, str(pitch_number or ""),
                normalized_pitch_id, project_id, scenario_id,
            ),
        ).fetchall()
        if not media_rows:
            return []

        media_ids = [str(r["id"]) for r in media_rows]
        placeholders = ",".join("?" for _ in media_ids)
        tags_rows = conn.execute(
            f"""SELECT t.media_id, t.work_element_id, COALESCE(NULLIF(TRIM(y.description), ''), work.operation) AS operation, work.sequence AS work_sequence,
                       COALESCE(y.pitch_id, yp_station.id) AS element_pitch_id,
                       COALESCE(yp.pitch_number, yp_station.pitch_number, work.station) AS element_pitch_number
                FROM process_visual_media_tags t
                JOIN work_elements work ON work.id=t.work_element_id
                LEFT JOIN yamazumi_elements y ON (
                    y.process_element_id = t.work_element_id
                    OR (y.process_element_id IS NULL AND y.id = t.work_element_id)
                ) AND y.project_id=t.project_id
                LEFT JOIN yamazumi_pitches yp ON yp.id=y.pitch_id AND yp.project_id=t.project_id
                LEFT JOIN yamazumi_pitches yp_station
                  ON yp_station.id=?
                 AND LOWER(TRIM(COALESCE(work.station, ''))) = LOWER(TRIM(COALESCE(yp_station.pitch_number, '')))
                WHERE t.project_id=? AND t.scenario_id=? AND t.media_id IN ({placeholders})
                ORDER BY work.sequence, work.id""",
            (normalized_pitch_id, project_id, scenario_id, *media_ids),
        ).fetchall()
        tags_by_media: dict[str, list[dict]] = {mid: [] for mid in media_ids}
        seen_media_tags: set[tuple[str, str]] = set()
        for tr in tags_rows:
            mid_key = str(tr["media_id"])
            we_key = str(tr["work_element_id"])
            if (mid_key, we_key) in seen_media_tags:
                continue
            seen_media_tags.add((mid_key, we_key))
            tags_by_media[mid_key].append(dict(tr))

        results: list[dict] = []
        for mr in media_rows:
            row_dict = dict(mr)
            row_dict["pitch_number"] = pitch_number
            row_dict["pitch_name"] = pitch_name
            row_tags = tags_by_media.get(str(mr["id"]), [])
            row_dict["tagged_work_element_ids"] = [t["work_element_id"] for t in row_tags]
            row_dict["tagged_work_elements"] = row_tags
            results.append(row_dict)
        return results


@cached_store_read
def scenario_pitch_visual_coverage(
    project_id: str, scenario_id: str
) -> dict[str, dict]:
    """Return per-pitch visual-aid coverage status ('green', 'yellow', 'white') for a scenario."""
    if not str(project_id or "").strip() or not str(scenario_id or "").strip():
        return {}
    with connection() as conn:
        def _has_table(name: str) -> bool:
            return (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (name,),
                ).fetchone()
                is not None
            )

        if not _has_table("yamazumi_pitches") or not _has_table("yamazumi_areas"):
            return {}

        pitch_rows = conn.execute(
            """SELECT p.id, p.pitch_number
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id = p.area_id AND a.project_id = p.project_id
               WHERE p.project_id = ? AND a.scenario_id = ?""",
            (project_id, scenario_id),
        ).fetchall()
        if not pitch_rows:
            return {}

        pitch_elements: dict[str, set[str]] = {}
        pitch_id_by_number: dict[str, str] = {}
        for pr in pitch_rows:
            pid = str(pr["id"] or "").strip()
            if not pid:
                continue
            pitch_elements[pid] = set()
            pnum = str(pr["pitch_number"] or "").strip().casefold()
            if pnum:
                pitch_id_by_number[pnum] = pid

        if _has_table("yamazumi_elements"):
            ye_rows = conn.execute(
                """SELECT y.id AS yamazumi_id, y.pitch_id, y.process_element_id, y.description,
                          w.id AS valid_work_element_id
                   FROM yamazumi_elements y
                   JOIN yamazumi_areas a ON a.id = y.area_id AND a.project_id = y.project_id
                   LEFT JOIN work_elements w
                     ON w.id = y.process_element_id
                    AND w.project_id = y.project_id
                    AND w.scenario_id = a.scenario_id
                   WHERE y.project_id = ? AND a.scenario_id = ? AND y.pitch_id IS NOT NULL""",
                (project_id, scenario_id),
            ).fetchall()
            unlinked_station_we_by_pitch_desc: dict[tuple[str, str], list[str]] = {}
            if _has_table("work_elements"):
                unlinked_we_rows = conn.execute(
                    """SELECT w.id, w.station, w.operation
                       FROM work_elements w
                       WHERE w.project_id = ? AND w.scenario_id = ?
                         AND NOT EXISTS (
                             SELECT 1 FROM yamazumi_elements y2
                             JOIN yamazumi_areas a2 ON a2.id = y2.area_id AND a2.project_id = y2.project_id
                             WHERE y2.project_id = w.project_id
                               AND a2.scenario_id = w.scenario_id
                               AND y2.process_element_id = w.id
                         )
                       ORDER BY w.sequence, w.id""",
                    (project_id, scenario_id),
                ).fetchall()
                for uw in unlinked_we_rows:
                    st_key = str(uw["station"] or "").strip().casefold()
                    op_key = str(uw["operation"] or "").strip().casefold()
                    pid_match = pitch_id_by_number.get(st_key)
                    if pid_match and op_key:
                        unlinked_station_we_by_pitch_desc.setdefault((pid_match, op_key), []).append(str(uw["id"]))
            unlinked_by_pitch: dict[str, list[tuple[str, str]]] = {pid: [] for pid in pitch_elements}
            linked_descs_by_pitch: dict[str, set[str]] = {pid: set() for pid in pitch_elements}
            for yr in ye_rows:
                pid = str(yr["pitch_id"] or "").strip()
                if pid not in pitch_elements:
                    continue
                valid_wid = str(yr["valid_work_element_id"] or "").strip()
                desc_key = str(yr["description"] or "").strip().casefold()
                if valid_wid:
                    pitch_elements[pid].add(valid_wid)
                    if desc_key:
                        linked_descs_by_pitch[pid].add(desc_key)
                else:
                    yid = str(yr["yamazumi_id"] or "").strip()
                    unlinked_by_pitch[pid].append((desc_key, yid))
            for pid, unlinked_items in unlinked_by_pitch.items():
                for desc_key, yid in unlinked_items:
                    if desc_key and desc_key in linked_descs_by_pitch.get(pid, set()):
                        continue
                    station_candidates = unlinked_station_we_by_pitch_desc.get((pid, desc_key), []) if desc_key else []
                    if station_candidates:
                        matched_wid = station_candidates.pop(0)
                        pitch_elements[pid].add(matched_wid)
                        if desc_key:
                            linked_descs_by_pitch[pid].add(desc_key)
                        continue
                    pitch_elements[pid].add(f"__unlinked__:{desc_key or yid}")

        media_rows = (
            conn.execute(
                """SELECT id, pitch_id
                   FROM process_visual_media
                   WHERE project_id = ? AND scenario_id = ?""",
                (project_id, scenario_id),
            ).fetchall()
            if _has_table("process_visual_media")
            else []
        )
        tag_rows = (
            conn.execute(
                """SELECT t.media_id, t.work_element_id
                   FROM process_visual_media_tags t
                   JOIN process_visual_media m ON m.id = t.media_id
                   WHERE t.project_id = ? AND t.scenario_id = ?
                     AND m.project_id = ? AND m.scenario_id = ?""",
                (project_id, scenario_id, project_id, scenario_id),
            ).fetchall()
            if _has_table("process_visual_media") and _has_table("process_visual_media_tags")
            else []
        )

        tags_by_media: dict[str, set[str]] = {}
        all_tagged_work_ids: set[str] = set()
        for tr in tag_rows:
            mid = str(tr["media_id"] or "").strip()
            wid = str(tr["work_element_id"] or "").strip()
            if mid and wid:
                tags_by_media.setdefault(mid, set()).add(wid)
                all_tagged_work_ids.add(wid)

        all_media_by_pitch: dict[str, set[str]] = {pid: set() for pid in pitch_elements}
        for mr in media_rows:
            mid = str(mr["id"] or "").strip()
            mpid = str(mr["pitch_id"] or "").strip()
            if not mid:
                continue
            m_tags = tags_by_media.get(mid, set())
            if not m_tags:
                if mpid in all_media_by_pitch:
                    all_media_by_pitch[mpid].add(mid)
            else:
                if mpid in all_media_by_pitch:
                    all_media_by_pitch[mpid].add(mid)
                for pid, el_set in pitch_elements.items():
                    if el_set & m_tags:
                        all_media_by_pitch[pid].add(mid)

        coverage: dict[str, dict] = {}
        for pid, el_set in pitch_elements.items():
            total_elements = len(el_set)
            covered_elements = len(el_set & all_tagged_work_ids)
            media_count = len(all_media_by_pitch.get(pid, set()))
            if media_count == 0 and covered_elements == 0:
                status = "white"
            elif total_elements > 0 and (
                covered_elements >= total_elements
                or (total_elements == 1 and media_count > 0)
            ):
                status = "green"
            else:
                status = "yellow"
            coverage[pid] = {
                "status": status,
                "total_elements": total_elements,
                "covered_elements": covered_elements,
                "media_count": media_count,
            }
        return coverage


MAX_VISUAL_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_VISUAL_VIDEO_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_CAD_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_CAD_FILE_SIZE_MB = 50


def _resolve_visual_media_tag_work_element_ids(
    conn: sqlite3.Connection,
    project_id: str,
    scenario_id: str,
    tagged_work_element_ids: list[str] | None,
    timestamp: str,
    pitch_id: str | None = None,
) -> list[str]:
    """Resolve tagged step IDs (including unlinked Yamazumi element IDs) to valid work_elements IDs."""
    if not tagged_work_element_ids:
        return []
    resolved_ids: list[str] = []
    seen_resolved: set[str] = set()
    normalized_pitch_id = str(pitch_id or "").strip()

    for raw_id in tagged_work_element_ids:
        cleaned = str(raw_id or "").strip()
        if not cleaned:
            continue
        is_explicit_yam = cleaned.startswith("yam::")
        candidate_id = cleaned[5:].strip() if is_explicit_yam else cleaned
        if not candidate_id:
            continue

        resolved_we_id = ""
        if not is_explicit_yam:
            we_row = conn.execute(
                """SELECT id, station, operation
                   FROM work_elements
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (candidate_id, project_id, scenario_id),
            ).fetchone()
            if we_row:
                resolved_we_id = str(we_row["id"])
                we_station = str(we_row["station"] or "").strip()
                we_op = str(we_row["operation"] or "").strip()
                if we_op:
                    if normalized_pitch_id:
                        conn.execute(
                            """UPDATE yamazumi_elements
                               SET process_element_id=?, process_sync_status='Synced', updated_at=?
                               WHERE project_id=? AND pitch_id=?
                                 AND (process_element_id IS NULL OR TRIM(process_element_id) = '')
                                 AND LOWER(TRIM(COALESCE(description, ''))) = LOWER(TRIM(?))""",
                            (resolved_we_id, timestamp, project_id, normalized_pitch_id, we_op),
                        )
                    elif we_station:
                        conn.execute(
                            """UPDATE yamazumi_elements
                               SET process_element_id=?, process_sync_status='Synced', updated_at=?
                               WHERE project_id=?
                                 AND (process_element_id IS NULL OR TRIM(process_element_id) = '')
                                 AND LOWER(TRIM(COALESCE(description, ''))) = LOWER(TRIM(?))
                                 AND pitch_id IN (
                                     SELECT p.id
                                     FROM yamazumi_pitches p
                                     JOIN yamazumi_areas a ON a.id = p.area_id AND a.project_id = p.project_id
                                     WHERE p.project_id=? AND a.scenario_id=?
                                       AND LOWER(TRIM(COALESCE(p.pitch_number, ''))) = LOWER(TRIM(?))
                                 )""",
                            (resolved_we_id, timestamp, project_id, we_op, project_id, scenario_id, we_station),
                        )

        if not resolved_we_id:
            group = _find_same_pitch_yamazumi_group_for_element(
                conn, project_id, scenario_id, candidate_id
            )
            if group:
                member_ids = [
                    str(mid)
                    for mid in (group.get("_member_ids") or [candidate_id])
                    if str(mid).strip()
                ]
                station = str(group.get("pitch_number") or "Unassigned")
                model_variants = list(
                    group.get("_variants")
                    or parse_yamazumi_model_variants(
                        group.get("model_variants"), group.get("model_variant")
                    )
                )
                model_applicability = (
                    "All"
                    if any(
                        value.casefold() in {"base", "all", "all models"}
                        for value in model_variants
                    )
                    else ", ".join(model_variants)
                )
                existing_proc_id = str(group.get("process_element_id") or "").strip()
                if existing_proc_id:
                    exists = conn.execute(
                        "SELECT id FROM work_elements WHERE id=? AND project_id=? AND scenario_id=?",
                        (existing_proc_id, project_id, scenario_id),
                    ).fetchone()
                else:
                    exists = None

                if not exists and station and station != "Unassigned":
                    desc_str = str(group.get("description") or "").strip()
                    if desc_str:
                        candidate_we = conn.execute(
                            """SELECT w.id
                               FROM work_elements w
                               WHERE w.project_id=? AND w.scenario_id=?
                                 AND LOWER(TRIM(COALESCE(w.station, ''))) = LOWER(TRIM(?))
                                 AND LOWER(TRIM(COALESCE(w.operation, ''))) = LOWER(TRIM(?))
                                 AND NOT EXISTS (
                                     SELECT 1 FROM yamazumi_elements y
                                     JOIN yamazumi_areas a ON a.id = y.area_id AND a.project_id = y.project_id
                                     WHERE y.project_id = w.project_id
                                       AND a.scenario_id = w.scenario_id
                                       AND y.process_element_id = w.id
                                 )
                               ORDER BY w.sequence, w.id
                               LIMIT 1""",
                            (project_id, scenario_id, station, desc_str),
                        ).fetchone()
                        if candidate_we:
                            existing_proc_id = str(candidate_we["id"])
                            exists = candidate_we

                if exists:
                    resolved_we_id = existing_proc_id
                else:
                    next_sequence = conn.execute(
                        """SELECT COALESCE(MAX(sequence), 0) + 10 FROM work_elements
                           WHERE project_id=? AND scenario_id=?""",
                        (project_id, scenario_id),
                    ).fetchone()[0]
                    resolved_we_id = _create_work_element_with_started_ergonomics_review(
                        conn,
                        project_id,
                        scenario_id,
                        {
                            "sequence": next_sequence,
                            "station": station,
                            "operation": str(group.get("description") or ""),
                            "description": f"Yamazumi area: {group.get('area_name') or ''}",
                            "cycle_time_s": float(group.get("time_s") or 0),
                            "part_number": "",
                            "tool": "",
                            "torque": "",
                            "quality_requirement": "",
                            "ergo_requirement": "",
                            "location": station,
                            "conveyor_height_in": None,
                            "platform_height_in": None,
                            "pit_depth_in": None,
                            "model_applicability": model_applicability,
                            "status": "Draft",
                        },
                        timestamp,
                    )
                if member_ids and resolved_we_id:
                    member_placeholders = ",".join("?" for _ in member_ids)
                    conn.execute(
                        f"""UPDATE yamazumi_elements
                            SET process_element_id=?, process_sync_status='Synced', updated_at=?
                            WHERE project_id=? AND id IN ({member_placeholders})""",
                        (resolved_we_id, timestamp, project_id, *member_ids),
                    )

        if resolved_we_id and resolved_we_id not in seen_resolved:
            seen_resolved.add(resolved_we_id)
            resolved_ids.append(resolved_we_id)

    return resolved_ids


def save_pitch_visual_media(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
    filename: str,
    file_bytes: bytes,
    media_type: str | None = None,
    caption: str = "",
    tagged_work_element_ids: list[str] | None = None,
    sequence: int = 10,
    current_editor: str = "Collaborator",
    annotations_json: str = "",
    original_file_bytes: bytes | None = None,
    source_part_id: str = "",
    source_view_id: str = "",
) -> dict:
    """Save an uploaded image, video, or 3D CAD visual aid, attach element tags, and record audit."""
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        raise ValueError("Choose a Yamazumi pitch.")
    if not file_bytes:
        raise ValueError("No file content provided.")

    suffix = Path(str(filename or "")).suffix.lower()
    image_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    video_suffixes = {".mp4", ".mov", ".webm"}
    cad_suffixes = {".step", ".stp"}
    if suffix in image_suffixes:
        detected_type = "image"
        if len(file_bytes) > MAX_VISUAL_IMAGE_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            raise ValueError(
                f"Image is {size_mb:.1f} MB. Photos and screenshots must be under 10 MB for fast slide rendering."
            )
    elif suffix in video_suffixes:
        detected_type = "video"
        if len(file_bytes) > MAX_VISUAL_VIDEO_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            raise ValueError(
                f"Video is {size_mb:.1f} MB. For fast slide loading and smooth presentation playback, please trim or compress clips under 25 MB."
            )
    elif suffix in cad_suffixes:
        detected_type = "cad"
        if len(file_bytes) > MAX_CAD_FILE_SIZE_BYTES:
            size_mb = len(file_bytes) / (1024 * 1024)
            raise ValueError(
                f"3D CAD model is {size_mb:.1f} MB. STEP files must be under {MAX_CAD_FILE_SIZE_MB} MB. For large assemblies, please attach a PLM/CAD web link instead."
            )
    else:
        raise ValueError(
            f"Unsupported file format '{suffix}'. Supported formats: PNG, JPG, JPEG, WEBP (max 10 MB), MP4, MOV, WEBM (max 25 MB), STEP/STP (max {MAX_CAD_FILE_SIZE_MB} MB)."
        )

    resolved_media_type = media_type or detected_type
    if resolved_media_type not in {"image", "video", "cad"}:
        raise ValueError("Media type must be 'image', 'video', or 'cad'.")

    timestamp = now_iso()
    media_id = str(uuid4())
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_path = UPLOAD_DIR / f"process_visual_{normalized_pitch_id}_{media_id}{suffix}"
    target_path.write_bytes(file_bytes)

    orig_path_str = ""
    if resolved_media_type == "image":
        if original_file_bytes and original_file_bytes != file_bytes:
            orig_target_path = UPLOAD_DIR / f"process_visual_{normalized_pitch_id}_{media_id}_orig{suffix}"
            orig_target_path.write_bytes(original_file_bytes)
            orig_path_str = str(orig_target_path)
        else:
            orig_path_str = str(target_path)

    with connection() as conn:
        pitch = conn.execute(
            """SELECT pitch.id, pitch.pitch_number
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area ON area.id=pitch.area_id
               WHERE pitch.id=? AND pitch.project_id=? AND area.scenario_id=?""",
            (normalized_pitch_id, project_id, scenario_id),
        ).fetchone()
        if not pitch:
            target_path.unlink(missing_ok=True)
            if orig_path_str and orig_path_str != str(target_path):
                Path(orig_path_str).unlink(missing_ok=True)
            raise ValueError("The selected pitch does not exist in the active planning scenario.")

        conn.execute(
            """INSERT INTO process_visual_media
               (id, project_id, scenario_id, pitch_id, media_type, file_path, original_file_path,
                annotations_json, caption, sequence, created_at, created_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (media_id, project_id, scenario_id, normalized_pitch_id, resolved_media_type, str(target_path), orig_path_str, str(annotations_json or "").strip(), str(caption or "").strip(), int(sequence or 10), timestamp, str(current_editor or "").strip(), timestamp)); conn.execute("UPDATE process_visual_media SET source_part_id=?, source_view_id=? WHERE id=?", (str(source_part_id or "").strip(), str(source_view_id or "").strip(), media_id)); (lambda *a: None)(
            (
                media_id,
                project_id,
                scenario_id,
                normalized_pitch_id,
                resolved_media_type,
                str(target_path),
                orig_path_str,
                str(annotations_json or "").strip(),
                str(caption or "").strip(),
                int(sequence or 10),
                timestamp,
                str(current_editor or "").strip(),
                timestamp,
            ),
        )

        valid_tags = _resolve_visual_media_tag_work_element_ids(
            conn,
            project_id,
            scenario_id,
            tagged_work_element_ids,
            timestamp,
            pitch_id=normalized_pitch_id,
        )
        for cleaned_we_id in valid_tags:
            tag_id = str(uuid4())
            conn.execute(
                """INSERT OR IGNORE INTO process_visual_media_tags
                   (id, media_id, work_element_id, project_id, scenario_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tag_id, media_id, cleaned_we_id, project_id, scenario_id, timestamp),
            )

    record_audit_event(
        project_id,
        "process_visual_media",
        "Add visual aid",
        1,
        str(current_editor or "").strip(),
        {"summary": f"Added {resolved_media_type} to pitch {pitch['pitch_number']}: '{caption or filename}'"},
    )
    return {
        "id": media_id,
        "project_id": project_id,
        "scenario_id": scenario_id,
        "pitch_id": normalized_pitch_id,
        "media_type": resolved_media_type,
        "file_path": str(target_path),
        "original_file_path": orig_path_str,
        "annotations_json": str(annotations_json or "").strip(),
        "caption": str(caption or "").strip(),
        "sequence": int(sequence or 10),
        "tagged_work_element_ids": valid_tags,
        "created_at": timestamp,
        "created_by": str(current_editor or "").strip(),
    }


def save_pitch_visual_media_url(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
    url: str,
    caption: str = "",
    tagged_work_element_ids: list[str] | None = None,
    sequence: int = 10,
    current_editor: str = "Collaborator",
) -> dict:
    """Save an external web link or URL visual aid, attach element tags, and record audit."""
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        raise ValueError("Choose a Yamazumi pitch.")
    clean_url = str(url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        raise ValueError("Web link URL must start with http:// or https://")

    lower_url = clean_url.lower()
    if any(lower_url.endswith(ext) or (ext + "?") in lower_url for ext in [".png", ".jpg", ".jpeg", ".webp"]):
        resolved_media_type = "image"
    elif any(lower_url.endswith(ext) or (ext + "?") in lower_url for ext in [".mp4", ".mov", ".webm"]):
        resolved_media_type = "video"
    elif any(lower_url.endswith(ext) or (ext + "?") in lower_url for ext in [".step", ".stp"]):
        resolved_media_type = "cad"
    else:
        resolved_media_type = "link"

    timestamp = now_iso()
    media_id = str(uuid4())

    with connection() as conn:
        pitch = conn.execute(
            """SELECT pitch.id, pitch.pitch_number
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area ON area.id=pitch.area_id
               WHERE pitch.id=? AND pitch.project_id=? AND area.scenario_id=?""",
            (normalized_pitch_id, project_id, scenario_id),
        ).fetchone()
        if not pitch:
            raise ValueError("The selected pitch does not exist in the active planning scenario.")

        conn.execute(
            """INSERT INTO process_visual_media
               (id, project_id, scenario_id, pitch_id, media_type, file_path, original_file_path,
                annotations_json, caption, sequence, created_at, created_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)""",
            (
                media_id,
                project_id,
                scenario_id,
                normalized_pitch_id,
                resolved_media_type,
                clean_url,
                clean_url,
                str(caption or "").strip(),
                int(sequence or 10),
                timestamp,
                str(current_editor or "").strip(),
                timestamp,
            ),
        )

        valid_tags = _resolve_visual_media_tag_work_element_ids(
            conn,
            project_id,
            scenario_id,
            tagged_work_element_ids,
            timestamp,
            pitch_id=normalized_pitch_id,
        )
        for cleaned_we_id in valid_tags:
            tag_id = str(uuid4())
            conn.execute(
                """INSERT OR IGNORE INTO process_visual_media_tags
                   (id, media_id, work_element_id, project_id, scenario_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tag_id, media_id, cleaned_we_id, project_id, scenario_id, timestamp),
            )

    record_audit_event(
        project_id,
        "process_visual_media",
        "Add visual aid link",
        1,
        str(current_editor or "").strip(),
        {
            "summary": f"Added visual aid link on pitch {pitch['pitch_number']}: '{clean_url}'",
            "media_id": media_id,
            "pitch_id": normalized_pitch_id,
            "media_type": resolved_media_type,
            "url": clean_url,
            "caption": str(caption or "").strip(),
            "tagged_work_element_ids": valid_tags,
        },
    )

    return {
        "id": media_id,
        "project_id": project_id,
        "scenario_id": scenario_id,
        "pitch_id": normalized_pitch_id,
        "media_type": resolved_media_type,
        "file_path": clean_url,
        "original_file_path": clean_url,
        "annotations_json": "",
        "caption": str(caption or "").strip(),
        "sequence": int(sequence or 10),
        "tagged_work_element_ids": valid_tags,
        "created_at": timestamp,
        "created_by": str(current_editor or "").strip(),
    }


@cached_store_read
def catalog_part_photos_for_pitch(
    project_id: str,
    scenario_id: str,
    pitch_id: str | None = None,
) -> list[dict]:
    """Return active Parts Catalog parts that have one or more valid photo views (Primary or Additional views)."""
    if not project_id or not scenario_id:
        return []
    normalized_pitch_id = str(pitch_id or "").strip()
    valid_img_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

    def _is_valid_photo_path(raw_path: str) -> bool:
        cleaned = str(raw_path or "").strip()
        if not cleaned:
            return False
        lower_p = cleaned.lower()
        if lower_p.endswith((".step", ".stp")):
            return False
        if cleaned.startswith(("http://", "https://")):
            return True
        path_obj = Path(rebase_upload_path_str(cleaned, UPLOAD_DIR))
        return (
            path_obj.suffix.lower() in valid_img_exts
            and path_obj.exists()
            and path_obj.is_file()
        )

    with connection() as conn:
        pitch_work_ids_by_part: dict[str, set[str]] = {}
        if normalized_pitch_id:
            pitch_part_rows = conn.execute(
                """SELECT option.part_id, group_row.work_element_id
                   FROM process_part_groups group_row
                   JOIN process_part_options option ON option.group_id=group_row.id
                   JOIN yamazumi_elements yam
                     ON yam.process_element_id=group_row.work_element_id
                    AND yam.project_id=group_row.project_id
                   JOIN yamazumi_areas area
                     ON area.id=yam.area_id
                    AND area.project_id=yam.project_id
                    AND area.scenario_id=group_row.scenario_id
                   WHERE group_row.project_id=? AND group_row.scenario_id=?
                     AND yam.pitch_id=?""",
                (project_id, scenario_id, normalized_pitch_id),
            ).fetchall()
            for r in pitch_part_rows:
                p_id = str(r["part_id"] or "").strip()
                w_id = str(r["work_element_id"] or "").strip()
                if p_id:
                    pitch_work_ids_by_part.setdefault(p_id, set())
                    if w_id:
                        pitch_work_ids_by_part[p_id].add(w_id)

        part_rows = conn.execute(
            """SELECT part.id, part.part_number, part.description,
                      part.factory_nickname, part.subsystem,
                      part.image_path, part.original_image_path,
                      part.annotations_json, part.image_caption
               FROM parts part
               LEFT JOIN part_scenario_activity activity
                 ON activity.project_id=part.project_id
                AND activity.scenario_id=?
                AND activity.part_id=part.id
               WHERE part.project_id=?
                 AND COALESCE(activity.active, 1)=1
               ORDER BY part.part_number COLLATE NOCASE""",
            (scenario_id, project_id),
        ).fetchall()

        supp_rows = conn.execute(
            """SELECT pi.id, pi.part_id, pi.image_path, pi.original_image_path,
                      pi.annotations_json, pi.image_type, pi.caption
               FROM part_images pi
               JOIN parts part ON part.id=pi.part_id
               WHERE part.project_id=?
               ORDER BY pi.created_at, pi.id""",
            (project_id,),
        ).fetchall()

        supp_by_part: dict[str, list[dict]] = {}
        for sr in supp_rows:
            s_pid = str(sr["part_id"] or "").strip()
            if s_pid:
                supp_by_part.setdefault(s_pid, []).append(dict(sr))

        results: list[dict] = []
        for pr in part_rows:
            p_id = str(pr["id"] or "").strip()
            p_num = str(pr["part_number"] or "").strip()
            p_desc = str(pr["description"] or "").strip()
            p_nick = str(pr["factory_nickname"] or "").strip()
            p_sub = str(pr["subsystem"] or "").strip()
            default_part_label = f"{p_num} — {p_desc or p_nick}".strip(" —")

            views: list[dict] = []
            prim_path = str(pr["image_path"] or "").strip()
            if _is_valid_photo_path(prim_path):
                prim_cap = str(pr["image_caption"] or "").strip()
                views.append({
                    "view_id": f"primary::{p_id}",
                    "view_label": f"Primary Image — {prim_cap}" if prim_cap else "Primary Image",
                    "image_path": prim_path,
                    "original_image_path": str(pr["original_image_path"] or prim_path).strip(),
                    "annotations_json": str(pr["annotations_json"] or "").strip(),
                    "caption": prim_cap or default_part_label,
                    "is_primary": True,
                })

            for sr in supp_by_part.get(p_id, []):
                s_path = str(sr.get("image_path") or "").strip()
                s_type = str(sr.get("image_type") or "").strip()
                if s_type == "3D CAD Model (STEP)" or not _is_valid_photo_path(s_path):
                    continue
                s_cap = str(sr.get("caption") or "").strip()
                type_label = s_type or "Additional view"
                views.append({
                    "view_id": f"supp::{sr['id']}",
                    "view_label": f"{type_label} — {s_cap}" if s_cap else type_label,
                    "image_path": s_path,
                    "original_image_path": str(sr.get("original_image_path") or s_path).strip(),
                    "annotations_json": str(sr.get("annotations_json") or "").strip(),
                    "caption": s_cap or f"{default_part_label} ({type_label})",
                    "is_primary": False,
                })

            if not views:
                continue

            on_pitch = p_id in pitch_work_ids_by_part
            results.append({
                "part_id": p_id,
                "part_number": p_num,
                "description": p_desc,
                "factory_nickname": p_nick,
                "subsystem": p_sub,
                "on_pitch": on_pitch,
                "linked_work_element_ids": sorted(pitch_work_ids_by_part.get(p_id, set())),
                "views": views,
            })

        results.sort(
            key=lambda item: (
                0 if item.get("on_pitch") else 1,
                str(item.get("part_number") or "").casefold(),
                str(item.get("description") or "").casefold(),
            )
        )
        return results


def copy_part_photo_to_pitch_visual_media(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
    part_id: str,
    view_id: str = "",
    caption: str = "",
    tagged_work_element_ids: list[str] | None = None,
    sequence: int = 10,
    current_editor: str = "Collaborator",
) -> dict:
    """Copy a photo from the Parts Catalog into a pitch's visual aids as an independent visual media item."""
    normalized_pitch_id = str(pitch_id or "").strip()
    normalized_part_id = str(part_id or "").strip()
    if not normalized_pitch_id:
        raise ValueError("Choose a Yamazumi pitch.")
    if not normalized_part_id:
        raise ValueError("Choose a part from the Parts Catalog.")

    catalog_items = catalog_part_photos_for_pitch(
        project_id, scenario_id, normalized_pitch_id
    )
    matched_part = next(
        (item for item in catalog_items if item["part_id"] == normalized_part_id),
        None,
    )
    if not matched_part or not matched_part.get("views"):
        raise ValueError("The selected part does not have an available photo in the Parts Catalog.")

    views = matched_part["views"]
    target_view = next(
        (v for v in views if v["view_id"] == str(view_id or "").strip()),
        views[0],
    )
    img_path_str = str(target_view.get("image_path") or "").strip()
    orig_path_str = str(target_view.get("original_image_path") or img_path_str).strip()
    annotations_json = str(target_view.get("annotations_json") or "").strip()
    resolved_caption = (
        str(caption or "").strip()
        or str(target_view.get("caption") or "").strip()
        or f"{matched_part['part_number']} — {matched_part['description']}".strip(" —")
    )

    if img_path_str.startswith(("http://", "https://")):
        return save_pitch_visual_media_url(
            project_id=project_id,
            scenario_id=scenario_id,
            pitch_id=normalized_pitch_id,
            url=img_path_str,
            caption=resolved_caption,
            tagged_work_element_ids=tagged_work_element_ids or [],
            sequence=int(sequence or 10),
            current_editor=current_editor,
        )

    img_path = Path(rebase_upload_path_str(img_path_str, UPLOAD_DIR))
    if not img_path.exists() or not img_path.is_file():
        raise ValueError("The selected Parts Catalog photo file could not be found on disk.")
    file_bytes = img_path.read_bytes()
    orig_bytes: bytes | None = None
    if orig_path_str and not orig_path_str.startswith(("http://", "https://")):
        orig_path = Path(rebase_upload_path_str(orig_path_str, UPLOAD_DIR))
        if orig_path.exists() and orig_path.is_file():
            orig_bytes = orig_path.read_bytes()

    return save_pitch_visual_media(
        project_id=project_id,
        scenario_id=scenario_id,
        pitch_id=normalized_pitch_id,
        filename=img_path.name,
        file_bytes=file_bytes,
        original_file_bytes=orig_bytes,
        source_part_id=normalized_part_id,
        source_view_id=str(target_view.get("view_id") or ""),
        annotations_json=annotations_json,
        caption=resolved_caption,
        tagged_work_element_ids=tagged_work_element_ids or [],
        sequence=int(sequence or 10),
        current_editor=current_editor,
    )


def copy_pitch_visual_media(
    project_id: str,
    scenario_id: str,
    media_id: str,
    target_pitch_id: str | None = None,
    caption: str | None = None,
    tagged_work_element_ids: list[str] | None = None,
    sequence: int | None = None,
    current_editor: str = "Collaborator",
) -> dict:
    """Duplicate an existing visual aid onto the same pitch or another pitch in the scenario."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to copy.")

    with connection() as conn:
        source = conn.execute(
            """SELECT m.id, m.pitch_id, m.media_type, m.file_path, m.original_file_path,
                      m.annotations_json, m.caption, m.sequence, m.source_part_id, m.source_view_id, pitch.pitch_number
               FROM process_visual_media m
               JOIN yamazumi_pitches pitch ON pitch.id=m.pitch_id
               WHERE m.id=? AND m.project_id=? AND m.scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not source:
            raise ValueError("Visual aid not found in this scenario.")

        existing_tag_rows = conn.execute(
            """SELECT work_element_id
               FROM process_visual_media_tags
               WHERE media_id=? AND project_id=? AND scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchall()
        existing_tag_ids = [
            str(r["work_element_id"])
            for r in existing_tag_rows
            if r["work_element_id"]
        ]

    resolved_pitch_id = str(target_pitch_id or source["pitch_id"] or "").strip()
    if not resolved_pitch_id:
        raise ValueError("Choose a destination Yamazumi pitch.")

    resolved_caption = (
        str(caption).strip()
        if caption is not None
        else str(source["caption"] or "").strip()
    )
    resolved_sequence = (
        int(sequence)
        if sequence is not None
        else int(source["sequence"] or 10)
    )
    if tagged_work_element_ids is not None:
        resolved_tags = list(tagged_work_element_ids)
    elif resolved_pitch_id == str(source["pitch_id"] or "").strip():
        resolved_tags = existing_tag_ids
    else:
        resolved_tags = []

    file_path_str = str(source["file_path"] or "").strip()
    orig_path_str = str(source["original_file_path"] or "").strip()
    m_type = str(source["media_type"] or "image").strip()
    annotations_json = str(source["annotations_json"] or "").strip()

    if m_type == "link" or file_path_str.startswith(("http://", "https://")):
        copied = save_pitch_visual_media_url(
            project_id=project_id,
            scenario_id=scenario_id,
            pitch_id=resolved_pitch_id,
            url=file_path_str,
            caption=resolved_caption,
            tagged_work_element_ids=resolved_tags,
            sequence=resolved_sequence,
            current_editor=current_editor,
        )
    else:
        src_path = Path(rebase_upload_path_str(file_path_str, UPLOAD_DIR))
        if not src_path.exists() or not src_path.is_file():
            raise ValueError("The source visual aid file could not be found on disk.")
        file_bytes = src_path.read_bytes()
        orig_bytes: bytes | None = None
        if orig_path_str and not orig_path_str.startswith(("http://", "https://")):
            orig_path = Path(rebase_upload_path_str(orig_path_str, UPLOAD_DIR))
            if orig_path.exists() and orig_path.is_file():
                orig_bytes = orig_path.read_bytes()
        copied = save_pitch_visual_media(
            project_id=project_id,
            scenario_id=scenario_id,
            pitch_id=resolved_pitch_id,
            filename=src_path.name,
            file_bytes=file_bytes,
            media_type=m_type if m_type in {"image", "video", "cad"} else None,
            caption=resolved_caption,
            tagged_work_element_ids=resolved_tags,
            sequence=resolved_sequence,
            current_editor=current_editor,
            annotations_json=annotations_json,
            original_file_bytes=orig_bytes,
            source_part_id=str(source["source_part_id"] or "").strip(),
            source_view_id=str(source["source_view_id"] or "").strip(),
        )

    record_audit_event(
        project_id,
        "process_visual_media",
        "Copy visual aid",
        1,
        str(current_editor or "").strip(),
        {
            "summary": f"Copied {m_type} visual aid from pitch {source['pitch_number']}: '{resolved_caption or normalized_media_id}'",
            "source_media_id": normalized_media_id,
            "new_media_id": copied.get("id", ""),
            "target_pitch_id": resolved_pitch_id,
        },
    )
    return copied


def update_pitch_visual_media(
    project_id: str,
    scenario_id: str,
    media_id: str,
    caption: str,
    tagged_work_element_ids: list[str] | None = None,
    sequence: int | None = None,
    current_editor: str = "Collaborator",
    url: str | None = None,
) -> None:
    """Update caption, sequence, url, and tagged elements for a visual aid."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to update.")

    timestamp = now_iso()
    with connection() as conn:
        existing = conn.execute(
            """SELECT m.id, m.pitch_id, m.media_type, pitch.pitch_number
               FROM process_visual_media m
               JOIN yamazumi_pitches pitch ON pitch.id=m.pitch_id
               WHERE m.id=? AND m.project_id=? AND m.scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not existing:
            raise ValueError("Visual aid not found in this scenario.")

        clean_url = str(url or "").strip() if url is not None else None
        if clean_url:
            if not clean_url.startswith(("http://", "https://")):
                raise ValueError("Web link URL must start with http:// or https://")
            lower_u = clean_url.lower()
            if any(lower_u.endswith(ext) or (ext + "?") in lower_u for ext in [".png", ".jpg", ".jpeg", ".webp"]):
                new_m_type = "image"
            elif any(lower_u.endswith(ext) or (ext + "?") in lower_u for ext in [".mp4", ".mov", ".webm"]):
                new_m_type = "video"
            elif any(lower_u.endswith(ext) or (ext + "?") in lower_u for ext in [".step", ".stp"]):
                new_m_type = "cad"
            else:
                new_m_type = "link"
            conn.execute(
                """UPDATE process_visual_media
                   SET file_path=?, original_file_path=?, media_type=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (clean_url, clean_url, new_m_type, normalized_media_id, project_id, scenario_id),
            )

        if sequence is not None:
            conn.execute(
                """UPDATE process_visual_media
                   SET caption=?, sequence=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (str(caption or "").strip(), int(sequence), timestamp, normalized_media_id, project_id, scenario_id),
            )
        else:
            conn.execute(
                """UPDATE process_visual_media
                   SET caption=?, updated_at=?
                   WHERE id=? AND project_id=? AND scenario_id=?""",
                (str(caption or "").strip(), timestamp, normalized_media_id, project_id, scenario_id),
            )

        if tagged_work_element_ids is not None:
            conn.execute(
                "DELETE FROM process_visual_media_tags WHERE media_id=? AND project_id=? AND scenario_id=?",
                (normalized_media_id, project_id, scenario_id),
            )
            resolved_tags = _resolve_visual_media_tag_work_element_ids(
                conn,
                project_id,
                scenario_id,
                tagged_work_element_ids,
                timestamp,
                pitch_id=str(existing["pitch_id"] or ""),
            )
            for cleaned_we_id in resolved_tags:
                tag_id = str(uuid4())
                conn.execute(
                    """INSERT OR IGNORE INTO process_visual_media_tags
                       (id, media_id, work_element_id, project_id, scenario_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (tag_id, normalized_media_id, cleaned_we_id, project_id, scenario_id, timestamp),
                )

    record_audit_event(
        project_id,
        "process_visual_media",
        "Update visual aid",
        1,
        str(current_editor or "").strip(),
        {"summary": f"Updated visual aid on pitch {existing['pitch_number']}: '{caption}'"},
    )


def update_pitch_visual_annotations(
    project_id: str,
    scenario_id: str,
    media_id: str,
    annotations_json: str,
    composite_image_bytes: bytes | None = None,
    current_editor: str = "Collaborator",
) -> None:
    """Update annotations vector JSON and composite display image for an existing visual aid."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to annotate.")

    timestamp = now_iso()
    target_written: Path | None = None
    with connection() as conn:
        row = conn.execute(
            """SELECT m.id, m.file_path, m.original_file_path, m.caption, m.pitch_id,
                      COALESCE(pitch.pitch_number, '') AS pitch_number
               FROM process_visual_media m
               LEFT JOIN yamazumi_pitches pitch ON pitch.id=m.pitch_id
               WHERE m.id=? AND m.project_id=? AND m.scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("Visual aid not found.")

        file_path_str = str(row["file_path"] or "").strip()
        orig_path_str = str(row["original_file_path"] or file_path_str).strip()
        pitch_number = row["pitch_number"] or row["pitch_id"]
        caption = row["caption"]

        curr_path = Path(file_path_str) if file_path_str else None
        if curr_path is not None and (not curr_path.exists() or not curr_path.is_file()):
            rebased_curr = resolve_upload_path(file_path_str, UPLOAD_DIR)
            if rebased_curr is not None and rebased_curr.exists() and rebased_curr.is_file():
                curr_path = rebased_curr
                file_path_str = str(curr_path)

        orig_check = Path(orig_path_str) if orig_path_str else None
        if orig_check is not None and (not orig_check.exists() or not orig_check.is_file()):
            rebased_orig = resolve_upload_path(orig_path_str, UPLOAD_DIR)
            if rebased_orig is not None and rebased_orig.exists() and rebased_orig.is_file():
                orig_path_str = str(rebased_orig)

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # Ensure original_file_path exists and is backed up so we never lose original source photo
        if (
            not row["original_file_path"]
            or str(row["original_file_path"]).strip() == str(row["file_path"]).strip()
            or not Path(orig_path_str).exists()
        ):
            if curr_path is not None and curr_path.exists() and curr_path.is_file():
                suffix = curr_path.suffix or ".png"
                new_orig_target = UPLOAD_DIR / f"process_visual_{row['pitch_id']}_{normalized_media_id}_orig{suffix}"
                if not new_orig_target.exists():
                    new_orig_target.write_bytes(curr_path.read_bytes())
                orig_path_str = str(new_orig_target)
                conn.execute(
                    "UPDATE process_visual_media SET original_file_path=? WHERE id=?",
                    (orig_path_str, normalized_media_id),
                )

        if composite_image_bytes:
            target = curr_path if (curr_path is not None and curr_path.parent.exists()) else (
                UPLOAD_DIR / (Path(file_path_str).name or f"process_visual_{row['pitch_id']}_{normalized_media_id}.png")
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(composite_image_bytes)
            file_path_str = str(target)
            target_written = target

        conn.execute(
            """UPDATE process_visual_media
               SET file_path=?, annotations_json=?, updated_at=?
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (file_path_str, str(annotations_json or "").strip(), timestamp, normalized_media_id, project_id, scenario_id),
        )

    if target_written is not None:
        try:
            from utils.media_cache import prewarm_image_cache

            prewarm_image_cache(target_written)
        except Exception:
            pass

    record_audit_event(
        project_id,
        "process_visual_media",
        "Annotate visual aid",
        1,
        str(current_editor or "").strip(),
        {"summary": f"Annotated visual aid on pitch {pitch_number}: '{caption or normalized_media_id}'"},
    )


def delete_pitch_visual_media(
    project_id: str,
    scenario_id: str,
    media_id: str,
    current_editor: str = "Collaborator",
) -> None:
    """Delete a visual aid, its tags, and underlying media files on disk."""
    normalized_media_id = str(media_id or "").strip()
    if not normalized_media_id:
        raise ValueError("Choose a visual aid to delete.")

    with connection() as conn:
        row = conn.execute(
            """SELECT m.id, m.file_path, m.original_file_path, m.caption, pitch.pitch_number
               FROM process_visual_media m
               JOIN yamazumi_pitches pitch ON pitch.id=m.pitch_id
               WHERE m.id=? AND m.project_id=? AND m.scenario_id=?""",
            (normalized_media_id, project_id, scenario_id),
        ).fetchone()
        if not row:
            raise ValueError("Visual aid not found.")

        file_path_str = row["file_path"]
        orig_path_str = row["original_file_path"] or ""
        pitch_number = row["pitch_number"]
        caption = row["caption"]

        with capture_deletion_to_recycle_bin(
            conn,
            project_id=project_id,
            scenario_id=scenario_id,
            entity_type="Pitch Visual Aid",
            entity_table="process_visual_media",
            entity_id=normalized_media_id,
            entity_label=f"Pitch {pitch_number}: {caption or 'Visual aid'}",
            deleted_by=str(current_editor or "").strip(),
            extra_file_paths=[file_path_str, orig_path_str],
        ):
            conn.execute(
                "DELETE FROM process_visual_media WHERE id=? AND project_id=? AND scenario_id=?",
                (normalized_media_id, project_id, scenario_id),
            )

    if file_path_str and not file_path_str.startswith(("http://", "https://")):
        safe_unlink_upload_path(file_path_str)

    if orig_path_str and orig_path_str != file_path_str and not orig_path_str.startswith(("http://", "https://")):
        safe_unlink_upload_path(orig_path_str)

    record_audit_event(
        project_id,
        "process_visual_media",
        "Delete visual aid",
        1,
        str(current_editor or "").strip(),
        {"summary": f"Deleted visual aid from pitch {pitch_number}: '{caption}'"},
    )


def _enrich_parts_with_minibom(
    conn: sqlite3.Connection,
    project_id: str,
    aggregated_parts_map: dict[str, dict],
) -> None:
    """Enrich aggregated parts with mini-BOM components and assembly group flags."""
    if not aggregated_parts_map:
        return

    import re

    part_ids = [p["part_id"] for p in aggregated_parts_map.values() if p.get("part_id")]
    part_numbers = [p_num for p_num in aggregated_parts_map.keys() if p_num]
    tracker_numbers = [
        str(p.get("pits_tracker_number") or "").strip()
        for p in aggregated_parts_map.values()
        if str(p.get("pits_tracker_number") or "").strip()
    ]

    mfg_components_by_pnum: dict[str, list[dict]] = {}
    mfg_assembly_numbers: set[str] = set()

    # 1. Check manufacturing_assemblies
    if part_ids or part_numbers:
        params: list = [project_id]
        where_clauses: list[str] = []
        if part_ids:
            p_id_placeholders = ",".join("?" for _ in part_ids)
            where_clauses.append(f"a.catalog_part_id IN ({p_id_placeholders})")
            params.extend(part_ids)
        if part_numbers:
            p_num_placeholders = ",".join("?" for _ in part_numbers)
            where_clauses.append(f"a.assembly_number IN ({p_num_placeholders})")
            params.extend(part_numbers)

        if where_clauses:
            asm_rows = conn.execute(
                f"""SELECT a.id AS assembly_id, a.assembly_number, a.name AS assembly_name,
                           a.catalog_part_id,
                           p_main.part_number AS main_part_number,
                           c.quantity,
                           p_comp.part_number AS component_part_number,
                           p_comp.description AS component_description,
                           p_comp.factory_nickname AS component_factory_nickname,
                           p_comp.design_engineer AS component_design_engineer,
                           p_comp.technology_engineer AS component_technology_engineer
                    FROM manufacturing_assemblies a
                    LEFT JOIN parts p_main ON p_main.id = a.catalog_part_id
                    LEFT JOIN manufacturing_assembly_components c ON c.assembly_id = a.id
                    LEFT JOIN fishbone_part_assignments f ON f.id = c.fishbone_assignment_id
                    LEFT JOIN parts p_comp ON p_comp.id = f.part_id
                    WHERE a.project_id = ?
                      AND ({' OR '.join(where_clauses)})
                    ORDER BY p_comp.part_number""",
                params,
            ).fetchall()

            for r in asm_rows:
                asm_num = str(r["assembly_number"] or "").strip()
                main_pnum = str(r["main_part_number"] or "").strip()
                if asm_num:
                    mfg_assembly_numbers.add(asm_num)
                if main_pnum:
                    mfg_assembly_numbers.add(main_pnum)

                key_pnum = None
                if main_pnum and main_pnum in aggregated_parts_map:
                    key_pnum = main_pnum
                elif asm_num and asm_num in aggregated_parts_map:
                    key_pnum = asm_num
                elif r["catalog_part_id"]:
                    for k, val in aggregated_parts_map.items():
                        if str(val.get("part_id") or "") == str(r["catalog_part_id"]):
                            key_pnum = k
                            break

                comp_pnum = str(r["component_part_number"] or "").strip()
                if comp_pnum and key_pnum:
                    mfg_components_by_pnum.setdefault(key_pnum, []).append({
                        "part_number": comp_pnum,
                        "description": str(r["component_description"] or ""),
                        "factory_nickname": str(r["component_factory_nickname"] or ""),
                        "quantity": float(r["quantity"] or 1.0),
                        "design_engineer": str(r["component_design_engineer"] or r["component_technology_engineer"] or ""),
                        "source": "assembly",
                    })

    # 2. Check pits_bom_occurrences for child occurrences
    pits_components_by_pnum: dict[str, list[dict]] = {}
    if part_ids or tracker_numbers or part_numbers:
        params = [project_id]
        where_clauses = []
        if part_ids:
            p_id_placeholders = ",".join("?" for _ in part_ids)
            where_clauses.append(f"o.parent_part_id IN ({p_id_placeholders})")
            params.extend(part_ids)
        if tracker_numbers:
            trk_placeholders = ",".join("?" for _ in tracker_numbers)
            where_clauses.append(f"o.parent_tracker_number IN ({trk_placeholders})")
            params.extend(tracker_numbers)
        if part_numbers:
            p_num_placeholders = ",".join("?" for _ in part_numbers)
            where_clauses.append(f"parent_p.part_number IN ({p_num_placeholders})")
            params.extend(part_numbers)

        if where_clauses:
            pits_rows = conn.execute(
                f"""SELECT o.parent_part_id, o.parent_tracker_number,
                           parent_p.part_number AS parent_part_number,
                           o.proposed_quantity,
                           child_p.part_number AS component_part_number,
                           child_p.description AS component_description,
                           child_p.factory_nickname AS component_factory_nickname,
                           child_p.design_engineer AS component_design_engineer,
                           child_p.technology_engineer AS component_technology_engineer
                    FROM pits_bom_occurrences o
                    LEFT JOIN parts parent_p ON parent_p.id = o.parent_part_id
                    JOIN parts child_p ON child_p.id = o.child_part_id
                    WHERE o.project_id = ?
                      AND ({' OR '.join(where_clauses)})
                    ORDER BY o.source_row""",
                params,
            ).fetchall()

            for r in pits_rows:
                parent_pnum = str(r["parent_part_number"] or "").strip()
                if parent_pnum not in aggregated_parts_map:
                    matched_key = None
                    if r["parent_part_id"]:
                        for k, val in aggregated_parts_map.items():
                            if str(val.get("part_id") or "") == str(r["parent_part_id"]):
                                matched_key = k
                                break
                    if not matched_key and r["parent_tracker_number"]:
                        for k, val in aggregated_parts_map.items():
                            if str(val.get("pits_tracker_number") or "").strip() == str(r["parent_tracker_number"]).strip():
                                matched_key = k
                                break
                    if matched_key:
                        parent_pnum = matched_key

                comp_pnum = str(r["component_part_number"] or "").strip()
                if parent_pnum and parent_pnum in aggregated_parts_map and comp_pnum:
                    pits_components_by_pnum.setdefault(parent_pnum, []).append({
                        "part_number": comp_pnum,
                        "description": str(r["component_description"] or ""),
                        "factory_nickname": str(r["component_factory_nickname"] or ""),
                        "quantity": float(r["proposed_quantity"] or 1.0),
                        "design_engineer": str(r["component_design_engineer"] or r["component_technology_engineer"] or ""),
                        "source": "pits",
                    })

    # 3. Populate each part in aggregated_parts_map
    for p_num, p_data in aggregated_parts_map.items():
        comps = mfg_components_by_pnum.get(p_num) or []
        if not comps and p_num in pits_components_by_pnum:
            aggregated_pits: dict[str, dict] = {}
            for item in pits_components_by_pnum[p_num]:
                cp = item["part_number"]
                if cp in aggregated_pits:
                    aggregated_pits[cp]["quantity"] += item["quantity"]
                else:
                    aggregated_pits[cp] = dict(item)
            comps = list(aggregated_pits.values())

        is_asm = (
            bool(comps)
            or (p_num in mfg_assembly_numbers)
            or bool(re.search(r"G\d{2,}", p_num, re.IGNORECASE))
            or str(p_data.get("make_buy") or "").strip().casefold() in {"make", "asm", "subassembly"}
            or str(p_data.get("source_code") or "").strip() in {"+1", "5", "6"}
        )
        p_data["is_assembly_group"] = is_asm
        p_data["mini_bom"] = comps


@cached_store_read
def process_pitch_visual_summary(
    project_id: str, scenario_id: str, pitch_id: str
) -> dict:
    """Return one scenario-owned pitch and its Process-linked visual-summary rows."""
    normalized_pitch_id = str(pitch_id or "").strip()
    if not normalized_pitch_id:
        raise ValueError("Choose a Yamazumi pitch.")

    with connection() as conn:
        project_row = conn.execute(
            "SELECT name, COALESCE(building_location, '') AS building_location FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        project_name = project_row["name"] if project_row else ""
        building_location = str(project_row["building_location"] or "").strip() if project_row else ""

        scenario = conn.execute(
            "SELECT id, name, takt_time_s, takt_time_unit, yamazumi_time_unit FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone()
        if not scenario:
            raise ValueError("The active planning scenario no longer exists in this project.")
        scenario_name = scenario["name"]
        scenario_takt_s = float(scenario["takt_time_s"] or 0)
        scenario_takt_unit = scenario["takt_time_unit"] or "seconds"

        pitch = conn.execute(
            """SELECT pitch.id, pitch.pitch_number, pitch.pitch_name, pitch.sequence,
                      COALESCE(pitch.platform_height_in, 0.0) AS platform_height_in,
                      COALESCE(pitch.pit_depth_in, 0.0) AS pit_depth_in,
                      pitch.conveyor_zone_id,
                      COALESCE(zone.name, '') AS conveyor_zone_name,
                      COALESCE(zone.conveyor_height_in, 0.0) AS conveyor_height_in,
                      COALESCE(zone.conveyor_width_in, 0.0) AS conveyor_width_in,
                      COALESCE(zone.unit_orientation, '') AS unit_orientation,
                      area.id AS area_id, area.section_id, area.name AS area_name,
                      sec.name AS section_name
               FROM yamazumi_pitches pitch
               JOIN yamazumi_areas area
                 ON area.id=pitch.area_id AND area.project_id=pitch.project_id
               LEFT JOIN assembly_sections sec
                 ON sec.id=area.section_id AND sec.project_id=pitch.project_id
               LEFT JOIN conveyor_zones zone
                 ON zone.id=pitch.conveyor_zone_id AND zone.project_id=pitch.project_id AND zone.scenario_id=area.scenario_id
               WHERE pitch.id=? AND pitch.project_id=? AND area.scenario_id=?""",
            (normalized_pitch_id, project_id, scenario_id),
        ).fetchone()
        if not pitch:
            raise ValueError("The selected pitch no longer exists in the active planning scenario.")

        raw_yamazumi_rows = conn.execute(
            """SELECT yamazumi.id AS yamazumi_element_id,
                      yamazumi.id,
                      yamazumi.area_id,
                      yamazumi.pitch_id,
                      yamazumi.process_element_id,
                      yamazumi.description,
                      yamazumi.description AS yamazumi_description,
                      yamazumi.time_s,
                      yamazumi.sequence,
                      yamazumi.sequence AS stack_sequence,
                      yamazumi.model_variant,
                      yamazumi.model_variants,
                      COALESCE(NULLIF(TRIM(yamazumi.work_type), ''), 'Cycle') AS work_type,
                      work.id AS linked_work_element_id,
                      work.operation AS linked_operation,
                      work.model_applicability AS linked_model_applicability,
                      work.sequence AS linked_process_sequence,
                      work.tool AS linked_tool,
                      work.resource_type AS linked_resource_type,
                      work.resource_detail AS linked_resource_detail
               FROM yamazumi_elements yamazumi
               JOIN yamazumi_areas area
                 ON area.id=yamazumi.area_id
                AND area.project_id=yamazumi.project_id
                AND area.scenario_id=?
               LEFT JOIN work_elements work
                 ON work.id=yamazumi.process_element_id
                AND work.project_id=yamazumi.project_id
                AND work.scenario_id=area.scenario_id
               WHERE yamazumi.project_id=? AND yamazumi.pitch_id=?
               ORDER BY yamazumi.sequence,
                        yamazumi.description COLLATE NOCASE,
                        yamazumi.id""",
            (scenario_id, project_id, normalized_pitch_id),
        ).fetchall()

        pitch_number_str = str(pitch["pitch_number"] or "").strip()
        unlinked_station_work_rows = (
            [
                dict(r)
                for r in conn.execute(
                    """SELECT we.id AS work_element_id,
                              we.operation,
                              we.model_applicability,
                              we.sequence AS process_sequence,
                              we.tool,
                              we.resource_type,
                              we.resource_detail
                       FROM work_elements we
                       WHERE we.project_id=? AND we.scenario_id=?
                         AND (
                             LOWER(TRIM(COALESCE(we.station, ''))) = LOWER(?)
                             OR LOWER(TRIM(COALESCE(we.station, ''))) LIKE LOWER(?) || ' —%'
                             OR LOWER(TRIM(COALESCE(we.station, ''))) LIKE LOWER(?) || ' -%'
                         )
                         AND NOT EXISTS (
                             SELECT 1
                             FROM yamazumi_elements ye
                             JOIN yamazumi_areas ya
                               ON ya.id=ye.area_id AND ya.project_id=ye.project_id
                             WHERE ye.project_id=we.project_id
                               AND ya.scenario_id=we.scenario_id
                               AND ye.process_element_id=we.id
                         )
                       ORDER BY we.sequence, we.operation COLLATE NOCASE, we.id""",
                    (
                        project_id,
                        scenario_id,
                        pitch_number_str,
                        pitch_number_str,
                        pitch_number_str,
                    ),
                ).fetchall()
            ]
            if pitch_number_str
            else []
        )

        grouped_yamazumi = _group_same_pitch_yamazumi_rows(
            raw_yamazumi_rows, keep_private_fields=True
        )
        seen_work_ids: set[str] = set()
        seen_card_ids: set[str] = set()
        work_ids: list[str] = []
        cards: list[dict] = []
        resolved_we_by_yam_id: dict[str, str] = {}

        for group in grouped_yamazumi:
            yam_id_str = str(group.get("yamazumi_element_id") or group.get("id") or "").strip()
            member_ids = [
                str(mid).strip()
                for mid in (group.get("_member_ids") or ([yam_id_str] if yam_id_str else []))
                if str(mid).strip()
            ]
            linked_wid = str(group.get("linked_work_element_id") or "").strip()
            if linked_wid:
                for mid in member_ids:
                    resolved_we_by_yam_id[mid] = linked_wid
                if linked_wid in seen_work_ids:
                    continue
                seen_work_ids.add(linked_wid)
                seen_card_ids.add(linked_wid)
                work_ids.append(linked_wid)
                cards.append({
                    "work_element_id": linked_wid,
                    "operation": group["yamazumi_description"] or group["linked_operation"],
                    "model_applicability": group["linked_model_applicability"],
                    "process_sequence": group["linked_process_sequence"],
                    "tool": group["linked_tool"],
                    "resource_type": group["linked_resource_type"],
                    "resource_detail": group["linked_resource_detail"],
                    "yamazumi_element_id": yam_id_str,
                    "yamazumi_member_ids": member_ids,
                    "yamazumi_description": group["yamazumi_description"],
                    "time_s": group["time_s"],
                    "stack_sequence": group["stack_sequence"],
                })
                continue

            desc_key = str(group.get("yamazumi_description") or group.get("description") or "").strip().casefold()
            matched_we: dict | None = None
            if desc_key:
                for candidate_we in unlinked_station_work_rows:
                    cand_wid = str(candidate_we.get("work_element_id") or "").strip()
                    if not cand_wid or cand_wid in seen_work_ids:
                        continue
                    if str(candidate_we.get("operation") or "").strip().casefold() == desc_key:
                        matched_we = candidate_we
                        break
            if matched_we is not None:
                matched_wid = str(matched_we["work_element_id"])
                for mid in member_ids:
                    resolved_we_by_yam_id[mid] = matched_wid
                seen_work_ids.add(matched_wid)
                seen_card_ids.add(matched_wid)
                work_ids.append(matched_wid)
                cards.append({
                    "work_element_id": matched_wid,
                    "operation": matched_we["operation"],
                    "model_applicability": matched_we["model_applicability"],
                    "process_sequence": matched_we["process_sequence"],
                    "tool": matched_we["tool"],
                    "resource_type": matched_we["resource_type"],
                    "resource_detail": matched_we["resource_detail"],
                    "yamazumi_element_id": yam_id_str,
                    "yamazumi_member_ids": member_ids,
                    "yamazumi_description": group["yamazumi_description"],
                    "time_s": group["time_s"],
                    "stack_sequence": group["stack_sequence"],
                })
                continue

            if not yam_id_str:
                continue
            synthetic_wid = f"yam::{yam_id_str}"
            for mid in member_ids:
                resolved_we_by_yam_id[mid] = synthetic_wid
            if synthetic_wid in seen_card_ids:
                continue
            seen_card_ids.add(synthetic_wid)
            group_variants = parse_yamazumi_model_variants(
                group.get("model_variants"), group.get("model_variant")
            )
            model_app = (
                "All"
                if any(v.casefold() in {"base", "all", "all models"} for v in group_variants)
                else ", ".join(group_variants)
            )
            cards.append({
                "work_element_id": synthetic_wid,
                "operation": str(group.get("yamazumi_description") or group.get("description") or ""),
                "model_applicability": model_app,
                "process_sequence": group.get("stack_sequence"),
                "tool": "",
                "resource_type": "Human",
                "resource_detail": "",
                "yamazumi_element_id": yam_id_str,
                "yamazumi_member_ids": member_ids,
                "yamazumi_description": str(group.get("yamazumi_description") or group.get("description") or ""),
                "time_s": float(group.get("time_s") or 0.0),
                "stack_sequence": group.get("stack_sequence"),
            })

        for rem_we in ():  # Unlinked (Yamazumi link required) rows are excluded from PAAG slides
            rem_wid = str(rem_we.get("work_element_id") or "").strip()
            if not rem_wid or rem_wid in seen_work_ids:
                continue
            seen_work_ids.add(rem_wid)
            seen_card_ids.add(rem_wid)
            work_ids.append(rem_wid)
            cards.append({
                "work_element_id": rem_wid,
                "operation": rem_we["operation"],
                "model_applicability": rem_we["model_applicability"],
                "process_sequence": rem_we["process_sequence"],
                "tool": rem_we["tool"],
                "resource_type": rem_we["resource_type"],
                "resource_detail": rem_we["resource_detail"],
                "yamazumi_element_id": "",
                "yamazumi_member_ids": [],
                "yamazumi_description": rem_we["operation"],
                "time_s": 0.0,
                "stack_sequence": rem_we["process_sequence"],
            })

        parts_by_work: dict[str, list[dict]] = {work_id: [] for work_id in work_ids}
        handling_by_work: dict[str, list[str | None]] = {
            work_id: [] for work_id in work_ids
        }
        torque_by_work: dict[str, list[dict]] = {work_id: [] for work_id in work_ids}
        aggregated_parts_map: dict[str, dict] = {}

        if work_ids:
            _ensure_process_part_options_model_variant_column(conn)
            placeholders = ",".join("?" for _ in work_ids)
            part_rows = conn.execute(
                f"""SELECT group_row.id AS group_id,
                           group_row.name AS group_name,
                           group_row.selection_rule,
                           group_row.work_element_id,
                           COALESCE(option.is_model_variant, 0) AS is_model_variant,
                           option.handling_type,
                           COALESCE(option.quantity, group_row.quantity) AS quantity,
                           part.id AS part_id, part.part_number,
                           part.description AS part_description,
                           part.factory_nickname,
                           part.official_windchill_part_name,
                           part.revision,
                           part.subsystem,
                           part.make_buy,
                           part.source_code,
                           part.model_applicability,
                           part.weight_lb,
                           part.notes,
                           part.technology_engineer,
                           part.design_engineer,
                           part.pits_tracker_number,
                           part.buyer_gcl,
                           part.pmqe_aqe,
                           part.ame_tooling_engineer,
                           part.part_code,
                           part.ppm,
                           COALESCE(NULLIF(TRIM(part.image_path), ''), (
                               SELECT image.image_path FROM part_images image
                               WHERE image.part_id=part.id
                               ORDER BY image.created_at, image.id LIMIT 1
                           ), '') AS image_path
                    FROM process_part_groups group_row
                    JOIN process_part_options option ON option.group_id=group_row.id
                    JOIN parts part
                      ON part.id=option.part_id AND part.project_id=group_row.project_id
                    LEFT JOIN part_scenario_activity activity
                      ON activity.project_id=group_row.project_id
                     AND activity.scenario_id=group_row.scenario_id
                     AND activity.part_id=part.id
                    WHERE group_row.project_id=? AND group_row.scenario_id=?
                      AND group_row.work_element_id IN ({placeholders})
                      AND COALESCE(activity.active, 1)=1
                    ORDER BY group_row.work_element_id, group_row.name,
                             group_row.id, part.part_number""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            rows_by_group: dict[str, list[dict]] = {}
            group_order: list[str] = []
            for raw_row in part_rows:
                r_dict = dict(raw_row)
                gid = str(r_dict.get("group_id") or "")
                if gid not in rows_by_group:
                    rows_by_group[gid] = []
                    group_order.append(gid)
                rows_by_group[gid].append(r_dict)

            ordered_part_rows: list[dict] = []
            for gid in group_order:
                g_rows = rows_by_group[gid]
                sel_rule = str(g_rows[0].get("selection_rule") or "").strip()
                is_mc_rule = sel_rule in {"Model choice", "Choose one"}
                if not is_mc_rule:
                    for r_dict in g_rows:
                        r_dict["_resolved_is_model_variant"] = False
                        ordered_part_rows.append(r_dict)
                    continue
                has_explicit_mv = any(bool(int(r.get("is_model_variant") or 0)) for r in g_rows)
                if has_explicit_mv:
                    for r_dict in g_rows:
                        r_dict["_resolved_is_model_variant"] = bool(int(r_dict.get("is_model_variant") or 0))
                else:
                    non_base_flags = [
                        _normalize_variant_tokens(_extract_raw_variant_items(r.get("model_applicability")), {}) != {"__all__"}
                        for r in g_rows
                    ]
                    use_non_base = any(non_base_flags)
                    for r_dict, nb_flag in zip(g_rows, non_base_flags):
                        r_dict["_resolved_is_model_variant"] = bool(nb_flag) if use_non_base else True

                emitted_mv = False
                mv_rows = [r for r in g_rows if r.get("_resolved_is_model_variant")]
                for r_dict in g_rows:
                    if r_dict.get("_resolved_is_model_variant"):
                        if not emitted_mv:
                            emitted_mv = True
                            ordered_part_rows.extend(mv_rows)
                    else:
                        ordered_part_rows.append(r_dict)

            for row in ordered_part_rows:
                work_id = str(row["work_element_id"])
                group_id = str(row.get("group_id") or "")
                is_mv = bool(row.pop("_resolved_is_model_variant", False))
                mc_group_id = f"{work_id}::{group_id}" if is_mv else ""
                part = dict(row)
                h_type = part.pop("handling_type")
                h_norm = str(h_type or "").strip().casefold()
                is_consume = h_norm in {"consume", "c"}
                is_handle = h_norm in {"handle", "h"}
                part["handling_type"] = h_type
                if is_handle:
                    part["quantity"] = None
                handling_by_work[work_id].append(h_type)
                part.pop("work_element_id", None)
                part.pop("group_name", None)
                part["is_model_variant"] = is_mv
                part["model_choice_group_id"] = mc_group_id
                parts_by_work[work_id].append(part)

                p_num = str(row["part_number"] or "").strip()
                if p_num:
                    qty = float(row["quantity"] or 1.0)
                    if p_num not in aggregated_parts_map:
                        aggregated_parts_map[p_num] = {
                            "part_id": str(row["part_id"]),
                            "part_number": p_num,
                            "description": row["part_description"] or "",
                            "factory_nickname": row["factory_nickname"] or "",
                            "official_windchill_part_name": row["official_windchill_part_name"] or "",
                            "revision": row["revision"] or "",
                            "subsystem": row["subsystem"] or "",
                            "make_buy": row["make_buy"] or "",
                            "source_code": row["source_code"] or "",
                            "model_applicability": row["model_applicability"] or "",
                            "weight_lb": row["weight_lb"],
                            "notes": row["notes"] or "",
                            "technology_engineer": row["technology_engineer"] or "",
                            "design_engineer": row["design_engineer"] or "",
                            "pits_tracker_number": row["pits_tracker_number"] or "",
                            "buyer_gcl": row["buyer_gcl"] or "",
                            "pmqe_aqe": row["pmqe_aqe"] or "",
                            "ame_tooling_engineer": row["ame_tooling_engineer"] or "",
                            "part_code": row["part_code"] or "",
                            "ppm": row["ppm"] or "",
                            "image_path": row["image_path"] or "",
                            "quantity": qty if is_consume else (None if is_handle else qty),
                            "_consume_qty": qty if is_consume else 0.0,
                            "_has_consume": is_consume,
                            "_has_handle": is_handle,
                            "_unclassified_qty": qty if (not is_consume and not is_handle) else 0.0,
                            "handling_types": {h_type} if h_type else set(),
                            "work_element_ids": {work_id},
                            "is_model_variant": is_mv,
                            "model_choice_group_id": mc_group_id,
                        }
                    else:
                        if is_consume:
                            aggregated_parts_map[p_num]["_consume_qty"] += qty
                            aggregated_parts_map[p_num]["_has_consume"] = True
                        elif is_handle:
                            aggregated_parts_map[p_num]["_has_handle"] = True
                        else:
                            aggregated_parts_map[p_num]["_unclassified_qty"] += qty
                        if aggregated_parts_map[p_num]["_has_consume"]:
                            aggregated_parts_map[p_num]["quantity"] = aggregated_parts_map[p_num]["_consume_qty"]
                        elif aggregated_parts_map[p_num]["_has_handle"]:
                            aggregated_parts_map[p_num]["quantity"] = None
                        else:
                            aggregated_parts_map[p_num]["quantity"] = aggregated_parts_map[p_num]["_unclassified_qty"]
                        if h_type:
                            aggregated_parts_map[p_num]["handling_types"].add(h_type)
                        aggregated_parts_map[p_num]["work_element_ids"].add(work_id)
                        if is_mv and not aggregated_parts_map[p_num].get("is_model_variant"):
                            aggregated_parts_map[p_num]["is_model_variant"] = True
                            aggregated_parts_map[p_num]["model_choice_group_id"] = mc_group_id

            torque_rows = conn.execute(
                f"""SELECT assignment.work_element_id, assignment.unique_identifier,
                           assignment.target_value, assignment.tolerances,
                           assignment.unit
                    FROM quality_requirement_assignments assignment
                    JOIN quality_requirement_torque_details detail
                      ON detail.quality_requirement_id=assignment.quality_requirement_id
                     AND detail.project_id=assignment.project_id
                    WHERE assignment.project_id=? AND assignment.scenario_id=?
                      AND assignment.requirement_type='Torque'
                      AND assignment.work_element_id IN ({placeholders})
                    ORDER BY assignment.work_element_id,
                             assignment.unique_identifier COLLATE NOCASE,
                             assignment.id""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for row in torque_rows:
                torque = dict(row)
                work_id = str(torque.pop("work_element_id"))
                torque_by_work[work_id].append(torque)

        # Equipment / Tools placed on pitch or linked to any work element on this pitch address
        pitch_number_str = str(pitch["pitch_number"] or "").strip()
        extra_work_rows = conn.execute(
            """SELECT DISTINCT we.id
               FROM work_elements we
               WHERE we.project_id=? AND we.scenario_id=?
                 AND (
                     1=0 AND LOWER(TRIM(COALESCE(we.station, ''))) = LOWER(?)
                     OR (1=0 AND LOWER(TRIM(COALESCE(we.station, ''))) LIKE LOWER(?) || ' —%')
                     OR (1=0 AND LOWER(TRIM(COALESCE(we.station, ''))) LIKE LOWER(?) || ' -%')
                     OR we.id IN (
                         SELECT ye.process_element_id
                         FROM yamazumi_elements ye
                         JOIN yamazumi_areas ya ON ya.id=ye.area_id AND ya.project_id=ye.project_id
                         JOIN yamazumi_pitches yp ON yp.id=ye.pitch_id AND yp.project_id=ye.project_id
                         WHERE ye.project_id=? AND ya.scenario_id=?
                           AND (yp.id=? OR LOWER(TRIM(COALESCE(yp.pitch_number, ''))) = LOWER(?))
                           AND ye.process_element_id IS NOT NULL
                           AND TRIM(ye.process_element_id) != ''
                     )
                 )""",
            (
                project_id,
                scenario_id,
                pitch_number_str,
                pitch_number_str,
                pitch_number_str,
                project_id,
                scenario_id,
                normalized_pitch_id,
                pitch_number_str,
            ),
        ).fetchall()
        pitch_tool_work_ids = list(
            dict.fromkeys([*work_ids, *(str(r["id"]) for r in extra_work_rows if r["id"])])
        )
        tool_placeholders = ",".join("?" for _ in pitch_tool_work_ids) if pitch_tool_work_ids else "''"
        equipment_rows = conn.execute(
            f"""SELECT DISTINCT
                   asset.id AS equipment_id,
                   asset.name,
                   COALESCE(eq_type.label, '') AS type_name,
                   COALESCE(eq_type.tier, 'Handheld Tools') AS tier,
                   asset.manufacturer,
                   asset.model,
                   asset.description,
                   asset.notes,
                   asset.image_path,
                   placement.pitch_id
               FROM equipment_assets asset
               LEFT JOIN equipment_types eq_type ON eq_type.id=asset.equipment_type_id
               JOIN equipment_placements placement ON placement.equipment_id=asset.id AND placement.scenario_id=?
               LEFT JOIN yamazumi_pitches p_match ON p_match.id=placement.pitch_id AND p_match.project_id=asset.project_id
               LEFT JOIN equipment_process_links link ON link.placement_id=placement.id
               WHERE asset.project_id=?
                 AND (
                     placement.pitch_id=?
                     OR LOWER(TRIM(COALESCE(p_match.pitch_number, ''))) = LOWER(?)
                     OR (link.work_element_id IN ({tool_placeholders}))
                 )
               ORDER BY asset.name COLLATE NOCASE""",
            (
                (scenario_id, project_id, normalized_pitch_id, pitch_number_str, *pitch_tool_work_ids)
                if pitch_tool_work_ids
                else (scenario_id, project_id, normalized_pitch_id, pitch_number_str)
            ),
        ).fetchall()
        tools_list: list[dict] = []
        seen_eq_ids: set[str] = set()
        for eq in equipment_rows:
            eq_id_str = str(eq["equipment_id"] or "").strip()
            if eq_id_str and eq_id_str in seen_eq_ids:
                continue
            if eq_id_str:
                seen_eq_ids.add(eq_id_str)
            tool_title = f"{eq['name']} ({eq['type_name']})" if eq["type_name"] else eq["name"]
            pieces = [p for p in [eq["manufacturer"], eq["model"], eq["description"]] if p]
            summary_line = f"{tool_title}: {' '.join(pieces)}" if pieces else tool_title
            is_ppe = any(k in f"{eq['name']} {eq['type_name']} {eq['description']}".upper() for k in ["PPE", "PROTECTIVE", "GLOVE", "GLASSES", "EARPLUG", "SHIELD"])
            tools_list.append({
                "equipment_id": eq_id_str,
                "name": eq["name"],
                "type_name": eq["type_name"],
                "tier": str(eq["tier"] or "Handheld Tools"),
                "manufacturer": eq["manufacturer"] or "",
                "model": eq["model"] or "",
                "description": eq["description"] or "",
                "notes": eq["notes"] or "",
                "image_path": eq["image_path"] or "",
                "is_ppe": is_ppe,
                "summary_line": summary_line,
            })

        pitch_ppe_rollup: dict = resolve_pitch_ppe_rollup([])
        existing_names = {t["name"].casefold() for t in tools_list if t.get("name")}
        if pitch_tool_work_ids:
            we_tools = conn.execute(
                f"""SELECT tool FROM work_elements
                    WHERE id IN ({tool_placeholders})
                      AND tool IS NOT NULL AND TRIM(tool) != ''
                    ORDER BY sequence, id""",
                pitch_tool_work_ids,
            ).fetchall()
            for row in we_tools:
                tool_val = str(row["tool"]).strip()
                if tool_val and tool_val.casefold() not in existing_names:
                    tools_list.append({
                        "equipment_id": tool_val,
                        "name": tool_val,
                        "type_name": "Tool",
                        "manufacturer": "",
                        "model": "",
                        "description": "",
                        "notes": "",
                        "image_path": "",
                        "is_ppe": False,
                        "summary_line": tool_val,
                    })
                    existing_names.add(tool_val.casefold())

            # Include assigned PPE from Safety Review in Tools & PPE required list
            # (deduplicated per pitch with category hierarchy overrides applied)
            assigned_ppe_rows = conn.execute(
                f"""SELECT ppe FROM safety_requirements
                    WHERE project_id=? AND scenario_id=? AND active=1
                      AND work_element_id IN ({tool_placeholders})
                      AND ppe IS NOT NULL AND TRIM(ppe) != ''
                    ORDER BY created_at, id""",
                (project_id, scenario_id, *pitch_tool_work_ids),
            ).fetchall()
            pitch_ppe_rollup = resolve_pitch_ppe_rollup(
                [row["ppe"] for row in assigned_ppe_rows]
            )
            overridden_by_winner: dict[str, list[str]] = {}
            for ov in pitch_ppe_rollup.get("overridden_items", []):
                overridden_by_winner.setdefault(
                    str(ov.get("overridden_by") or "").casefold(), []
                ).append(str(ov.get("item") or ""))

            for eff_item in pitch_ppe_rollup.get("effective_items", []):
                item_name = str(eff_item.get("name") or "").strip()
                if not item_name or item_name.casefold() in existing_names:
                    continue
                canon_key = str(eff_item.get("canonical_name") or item_name).casefold()
                ov_list = overridden_by_winner.get(canon_key, [])
                ov_note = (
                    f"Overrides {', '.join(ov_list)} on this pitch."
                    if ov_list
                    else ""
                )
                haz = str(eff_item.get("hazard") or "").strip()
                mit = str(eff_item.get("mitigation") or "").strip()
                desc_text = f"Hazard: {haz} | Mitigation: {mit}" if (haz and mit) else "Required Safety PPE"
                tools_list.append({
                    "equipment_id": f"ppe_{item_name}",
                    "name": item_name,
                    "type_name": "PPE",
                    "manufacturer": "",
                    "model": "",
                    "description": desc_text,
                    "hazard": haz,
                    "mitigation": mit,
                    "notes": ov_note,
                    "image_path": str(eff_item.get("image_path") or ""),
                    "is_ppe": True,
                    "summary_line": f"PPE: {item_name}",
                })
                existing_names.add(item_name.casefold())

        # Mini Yamazumi pitch stack
        yamazumi_pitch_elements = conn.execute(
            """SELECT yamazumi.id, yamazumi.description, yamazumi.time_s, yamazumi.sequence,
                      yamazumi.model_variants, COALESCE(yamazumi.work_type, 'Cycle') AS work_type,
                      yamazumi.process_element_id
               FROM yamazumi_elements yamazumi
               WHERE yamazumi.project_id=? AND yamazumi.pitch_id=?
               ORDER BY yamazumi.sequence, yamazumi.id""",
            (project_id, normalized_pitch_id),
        ).fetchall()

        # Functional Alerts
        alerts: dict[str, list[dict]] = {
            "quality": [],
            "ergo": [],
            "safety": [],
            "materials": [],
            "equipment": [],
        }
        if work_ids:
            # Quality torque alerts
            for t_list in torque_by_work.values():
                for t in t_list:
                    uid = t.get("unique_identifier", "Torque")
                    val = t.get("target_value", "")
                    tol = t.get("tolerances", "")
                    unit = t.get("unit", "")
                    spec = " ".join(str(p) for p in [val, tol, unit] if p)
                    alerts["quality"].append({
                        "label": f"Torque: {uid} ({spec})",
                        "detail": f"Work Element Torque Specification: {uid} target {spec}",
                    })

            # PFMEA alerts
            pfmea_rows = conn.execute(
                f"""SELECT pfmea.potential_failure_mode, effect.severity, risk.rpn, work.operation
                    FROM pfmea_entries pfmea
                    JOIN work_elements work ON work.id=pfmea.work_element_id
                    LEFT JOIN pfmea_effects effect ON effect.pfmea_entry_id=pfmea.id
                    LEFT JOIN pfmea_risk_rows risk ON risk.pfmea_entry_id=pfmea.id
                    WHERE pfmea.project_id=? AND pfmea.scenario_id=?
                      AND pfmea.work_element_id IN ({placeholders})
                      AND (COALESCE(effect.severity, 0) >= 8 OR COALESCE(risk.rpn, 0) >= 100)""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for pfr in pfmea_rows:
                sev_text = f"Sev {int(pfr['severity'])}" if pfr['severity'] is not None else ""
                rpn_text = f"RPN {int(pfr['rpn'])}" if pfr['rpn'] is not None else ""
                score_str = ", ".join(p for p in [sev_text, rpn_text] if p)
                alerts["quality"].append({
                    "label": f"PFMEA: {pfr['potential_failure_mode']} ({score_str})" if score_str else f"PFMEA: {pfr['potential_failure_mode']}",
                    "detail": f"Step '{pfr['operation']}' has PFMEA Failure Mode '{pfr['potential_failure_mode']}' ({score_str})",
                })

            # Ergo alerts
            ergo_rows = conn.execute(
                f"""SELECT review.risk_classification, review.reviewer, review.notes, work.operation
                    FROM ergonomics_reviews review
                    JOIN work_elements work ON work.id=review.work_element_id
                    WHERE review.project_id=? AND review.scenario_id=?
                      AND review.work_element_id IN ({placeholders})
                      AND review.risk_classification IN ('Red', 'Favorable Red', 'Yellow')
                      AND review.status IN ('Started', 'Open', 'Pending', 'Validation')""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for er in ergo_rows:
                alerts["ergo"].append({
                    "label": f"Ergo Risk ({er['risk_classification']}): {er['operation']}",
                    "detail": f"Ergonomics review marked as {er['risk_classification']}. Reviewer notes: {er['notes'] or 'None'}",
                })

            # Safety alerts
            safety_rows = conn.execute(
                f"""SELECT safety.requirement_description, safety.ppe,
                           work.id AS work_element_id, work.operation
                    FROM safety_requirements safety
                    JOIN work_elements work ON work.id=safety.work_element_id
                    WHERE safety.project_id=? AND safety.scenario_id=?
                      AND safety.active=1
                      AND safety.work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            work_ids_with_ppe: set[str] = set()
            for sr in safety_rows:
                raw_ppe = sr["ppe"] if "ppe" in sr.keys() else ""
                ppe_items = parse_ppe(raw_ppe)
                if ppe_items:
                    work_ids_with_ppe.add(str(sr["work_element_id"]))
                alerts["safety"].append({
                    "label": f"Safety: {sr['requirement_description']}",
                    "detail": f"Safety requirement for step '{sr['operation']}': {sr['requirement_description']}",
                })

            # Check if any equipment linked to work elements has functional_area='Safety'
            safety_eq_rows = conn.execute(
                f"""SELECT link.work_element_id
                    FROM equipment_process_links link
                    JOIN equipment_placements placement ON placement.id=link.placement_id
                    JOIN equipment_function_links func ON func.equipment_id=placement.equipment_id
                    WHERE link.project_id=? AND link.scenario_id=?
                      AND func.functional_area='Safety'
                      AND link.work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *work_ids),
            ).fetchall()
            for eqr in safety_eq_rows:
                work_ids_with_ppe.add(str(eqr["work_element_id"]))

            # Alert for each individual work element without assigned PPE
            for idx, card in enumerate(cards):
                c_wid = str(card["work_element_id"])
                if c_wid not in work_ids_with_ppe:
                    s_num = idx + 1
                    s_desc = str(card.get("yamazumi_description") or card.get("operation") or "").strip()
                    label = f"No PPE Assigned: Step {s_num} ({s_desc})" if s_desc else f"No PPE Assigned: Step {s_num}"
                    alerts["safety"].append({
                        "label": label,
                        "detail": f"Step {s_num} ('{s_desc}') on this pitch has no PPE assigned in Safety Functional Review.",
                    })

        # Enrich parts with mini-BOM makeup and assembly group indicators
        _enrich_parts_with_minibom(conn, project_id, aggregated_parts_map)
        for w_parts in parts_by_work.values():
            for pt in w_parts:
                pnum = str(pt.get("part_number") or "").strip()
                if pnum in aggregated_parts_map:
                    pt["is_assembly_group"] = aggregated_parts_map[pnum].get("is_assembly_group", False)
                    pt["mini_bom"] = aggregated_parts_map[pnum].get("mini_bom", [])

        # Materials alerts
        for p in aggregated_parts_map.values():
            if not p["handling_types"]:
                alerts["materials"].append({
                    "label": f"Part {p['part_number']}: Unclassified Handling",
                    "detail": f"Part {p['part_number']} ({p['description']}) is neither marked Consume nor Handle on this pitch.",
                })

    op_ids = work_element_op_ids(project_id, scenario_id, work_ids) if work_ids else {}
    risk_ids = process_ergonomics_risk_work_element_ids(project_id, scenario_id)
    card_motion_map: dict[str, tuple[str, str]] = {}
    for card in cards:
        work_id = str(card["work_element_id"])
        handling_values = handling_by_work.get(work_id, [])
        normalized_handling = {
            str(value).strip() for value in handling_values if str(value or "").strip()
        }
        has_null = any(not str(value or "").strip() for value in handling_values)
        if normalized_handling == {"Consume"} and not has_null:
            classification = "Value-Added (VA)"
            color = "green"
        elif normalized_handling == {"Handle"} and not has_null:
            classification = "Non-Value-Added but Necessary (NVAN)"
            color = "orange"
        else:
            classification = "Unclassified"
            color = "gray"
        card_motion_map[work_id] = (classification, color)
        card.update(
            op_id=op_ids.get(work_id, "Yamazumi link required"),
            parts=parts_by_work.get(work_id, []),
            motion_classification=classification,
            motion_color=color,
            ergonomics_risk=work_id in risk_ids,
            torque_requirements=torque_by_work.get(work_id, []),
        )

    # Build Mini Yamazumi Variant Stacks
    variant_stacks: dict[str, list[dict]] = {}
    for yel in yamazumi_pitch_elements:
        wid = str(yel["process_element_id"] or "").strip() or resolved_we_by_yam_id.get(str(yel["id"] or "").strip(), "")
        w_type = str(yel["work_type"] or "Cycle").strip()
        w_type_lower = w_type.lower()
        if w_type_lower == "periodic":
            m_class = "Periodic"
            m_color = "orange"
        elif w_type_lower == "fluctuation":
            m_class = "Fluctuation"
            m_color = "gray"
        else:
            # Cycle work on Yamazumi: keep it green, no orange or gray classifications
            m_class = "Cycle"
            m_color = "green"
        variants = ["All models" if v.casefold() == "base" else v for v in parse_yamazumi_model_variants(yel["model_variants"], fallback="All models")]
        item_data = {
            "id": yel["id"],
            "work_element_id": wid,
            "process_element_id": wid,
            "description": yel["description"],
            "time_s": float(yel["time_s"] or 0),
            "sequence": yel["sequence"],
            "motion_classification": m_class,
            "motion_color": m_color,
            "work_type": w_type,
        }
        for v in variants:
            if v not in variant_stacks:
                variant_stacks[v] = []
            variant_stacks[v].append(item_data)
    if not variant_stacks:
        variant_stacks["All models"] = []

    stack_step_by_wid: dict[str, int] = {}
    for v_items in variant_stacks.values():
        for s_idx, v_item in enumerate(v_items):
            v_wid = str(v_item.get("work_element_id") or v_item.get("process_element_id") or "").strip()
            if v_wid and v_wid not in stack_step_by_wid:
                stack_step_by_wid[v_wid] = s_idx + 1

    # Aggregated parts list with sorted handling types and linked pitch steps
    ordered_agg_parts: list[dict] = []
    emitted_mc_groups: set[str] = set()
    agg_values = list(aggregated_parts_map.values())
    for p_item in agg_values:
        mc_gid = (
            str(p_item.get("model_choice_group_id") or "").strip()
            if p_item.get("is_model_variant")
            else ""
        )
        if not mc_gid:
            ordered_agg_parts.append(p_item)
        elif mc_gid not in emitted_mc_groups:
            emitted_mc_groups.add(mc_gid)
            for peer in agg_values:
                peer_gid = (
                    str(peer.get("model_choice_group_id") or "").strip()
                    if peer.get("is_model_variant")
                    else ""
                )
                if peer_gid == mc_gid:
                    ordered_agg_parts.append(peer)

    final_parts: list[dict] = []
    for p in ordered_agg_parts:
        p_work_ids = set(p.get("work_element_ids") or set())
        linked_step_labels: list[str] = []
        for idx, card in enumerate(cards):
            c_wid = str(card.get("work_element_id") or "")
            if c_wid in p_work_ids:
                s_num = stack_step_by_wid.get(c_wid, idx + 1)
                op_name = card.get("operation") or card.get("yamazumi_description") or f"Step {s_num}"
                linked_step_labels.append(f"Step {s_num} ({op_name})")
        final_parts.append({
            **p,
            "handling_types": sorted(p["handling_types"]),
            "linked_steps": linked_step_labels,
        })

    # Fetch and sequence visual media
    visual_media_items = get_pitch_visual_media(project_id, scenario_id, normalized_pitch_id)
    work_seq_map = {card["work_element_id"]: idx for idx, card in enumerate(cards)}
    def _media_sort_key(item: dict) -> tuple:
        tagged = item.get("tagged_work_element_ids", [])
        indices = [work_seq_map[wid] for wid in tagged if wid in work_seq_map]
        min_idx = min(indices) if indices else 999999
        return (min_idx, int(item.get("sequence", 10)), str(item.get("created_at", "")))
    sorted_visual_media = sorted(visual_media_items, key=_media_sort_key)
    slide_count = max(1, (len(sorted_visual_media) + 5) // 6)

    # Op ID range summary
    op_id_vals = [c.get("op_id") for c in cards if c.get("op_id") and c.get("op_id") != "Yamazumi link required"]
    op_id_summary = f"{op_id_vals[0]} – {op_id_vals[-1]}" if len(op_id_vals) > 1 else (op_id_vals[0] if op_id_vals else "N/A")

    return {
        **dict(pitch),
        "project_name": project_name,
        "building_location": building_location,
        "building": building_location,
        "scenario_name": scenario_name,
        "scenario_takt_s": scenario_takt_s,
        "scenario_takt_unit": scenario_takt_unit,
        "op_id_summary": op_id_summary,
        "elements": cards,
        "yamazumi_elements": [dict(yel) for yel in yamazumi_pitch_elements],
        "tools": tools_list,
        "ppe_rollup": pitch_ppe_rollup,
        "parts": final_parts,
        "yamazumi_stacks": variant_stacks,
        "visual_media": sorted_visual_media,
        "raw_visual_media": visual_media_items,
        "alerts": alerts,
        "slide_count": slide_count,
    }


def update_work_element_tool_and_resource(
    project_id: str,
    scenario_id: str,
    work_element_id: str,
    tool: str = "",
    resource_type: str = "Human",
    resource_detail: str = "",
    editor_name: str = "",
) -> None:
    """Update tool, resource type, and resource detail on a work element."""
    timestamp = now_iso()
    with connection() as conn:
        conn.execute(
            """UPDATE work_elements
               SET tool=?, resource_type=?, resource_detail=?, updated_at=?
               WHERE id=? AND project_id=? AND scenario_id=?""",
            (tool, resource_type, resource_detail, timestamp, work_element_id, project_id, scenario_id),
        )


def replace_work_elements(project_id: str, scenario_id: str, edited: pd.DataFrame) -> None:
    fields = [
        "sequence", "station", "operation", "description", "cycle_time_s", "part_number", "tool", "torque",
        "quality_requirement", "ergo_requirement", "location", "unit_orientation", "conveyor_height_in", "platform_height_in",
        "pit_depth_in", "model_applicability", "status", "output_assembly_number",
        "output_assembly_name", "resource_type", "resource_detail",
    ]
    records: list[tuple[str, list]] = []
    assembly_numbers: set[str] = set()
    for _, row in edited.iterrows():
        if not str(row.get("operation", "")).strip():
            continue
        element_id = (
            str(row.get("id"))
            if row.get("id") is not None and not pd.isna(row.get("id")) and str(row.get("id")).strip()
            else str(uuid4())
        )
        values = []
        for field in fields:
            value = row.get(field, "")
            if value is None or pd.isna(value):
                value = None if field.endswith("_in") else (0 if field in {"sequence", "cycle_time_s"} else "")
            elif field == "tool" and str(value).strip().casefold() == "(no tool required)":
                value = ""
            values.append(value)
        output_number = str(values[fields.index("output_assembly_number")] or "").strip()
        if output_number:
            normalized = output_number.casefold()
            if normalized in assembly_numbers:
                raise ValueError("Each made-assembly output number can be completed only once in a scenario.")
            assembly_numbers.add(normalized)
        records.append((element_id, values))

    with connection() as conn:
        existing_status_by_id = {
            str(row[0]): str(row[1] or "Draft")
            for row in conn.execute(
                "SELECT id, status FROM work_elements WHERE project_id=? AND scenario_id=?",
                (project_id, scenario_id),
            ).fetchall()
        }
        existing_ids = set(existing_status_by_id.keys())
        saved_ids = {element_id for element_id, _ in records}
        status_idx = fields.index("status")
        op_idx = fields.index("operation")
        newly_validated_ids = [
            element_id
            for element_id, values in records
            if str(values[status_idx] or "").strip() == "Validated"
            and existing_status_by_id.get(element_id) != "Validated"
        ]
        if newly_validated_ids:
            op_ctxs = work_element_op_contexts(project_id, scenario_id, newly_validated_ids)
            placeholders_nv = ",".join("?" for _ in newly_validated_ids)
            unc_by_id = {
                str(r[0]): int(r[1] or 0)
                for r in conn.execute(
                    f"""SELECT g.work_element_id, COUNT(*)
                        FROM process_part_groups g
                        JOIN process_part_options o ON o.group_id = g.id
                        LEFT JOIN part_scenario_activity a
                          ON a.project_id = g.project_id
                         AND a.scenario_id = g.scenario_id
                         AND a.part_id = o.part_id
                        WHERE g.project_id=? AND g.scenario_id=?
                          AND g.work_element_id IN ({placeholders_nv})
                          AND COALESCE(a.active, 1) = 1
                          AND (o.handling_type IS NULL OR TRIM(o.handling_type) = '')
                        GROUP BY g.work_element_id""",
                    (project_id, scenario_id, *newly_validated_ids),
                ).fetchall()
            }
            op_name_by_id = {
                element_id: str(values[op_idx] or "").strip()
                for element_id, values in records
            }
            for nv_id in newly_validated_ids:
                ctx = op_ctxs.get(nv_id) or {"op_id": "Yamazumi link required", "complete": False}
                reasons: list[str] = []
                if not bool(ctx.get("complete")):
                    reasons.append(f"Op ID is incomplete ({ctx.get('op_id')})")
                if not op_name_by_id.get(nv_id):
                    reasons.append("Operation name is blank")
                if unc_by_id.get(nv_id, 0) > 0:
                    reasons.append(f"{unc_by_id[nv_id]} paired part handling(s) are still Unclassified")
                if reasons:
                    step_label = op_name_by_id.get(nv_id) or nv_id
                    raise ValueError(
                        f"Cannot mark PAAG step '{step_label}' as Validated until it is technically complete: "
                        + "; ".join(reasons)
                        + "."
                    )
        existing_rows = conn.execute(
            "SELECT id, model_applicability, station, operation FROM work_elements WHERE project_id=? AND scenario_id=?",
            (project_id, scenario_id),
        ).fetchall()
        existing_models = {
            str(r[0]): str(r[1] or "")
            for r in existing_rows
        }
        existing_stations = {
            str(r[0]): str(r[2] or "")
            for r in existing_rows
        }
        existing_operations = {
            str(r[0]): str(r[3] or "")
            for r in existing_rows
        }
        scenario_pitches_by_num = {
            str(r[0] or "").strip().casefold(): (str(r[1]), str(r[2]))
            for r in conn.execute(
                """SELECT p.pitch_number, p.id, p.area_id
                   FROM yamazumi_pitches p
                   JOIN yamazumi_areas a ON a.id = p.area_id
                   WHERE p.project_id = ? AND a.scenario_id = ?""",
                (project_id, scenario_id),
            ).fetchall()
            if str(r[0] or "").strip()
        }
        model_idx = fields.index("model_applicability")
        station_idx = fields.index("station")
        operation_idx = fields.index("operation")
        assignments = ", ".join(f"{field}=?" for field in fields)
        for element_id, values in records:
            if element_id in existing_operations:
                new_op_val = str(values[operation_idx] or "").strip()
                old_op_val = existing_operations[element_id].strip()
                if new_op_val and new_op_val != old_op_val:
                    linked_yam_ops = conn.execute(
                        """SELECT e.id
                           FROM yamazumi_elements e
                           JOIN yamazumi_areas a ON a.id = e.area_id
                           WHERE e.project_id = ? AND a.scenario_id = ? AND e.process_element_id = ?""",
                        (project_id, scenario_id, element_id),
                    ).fetchall()
                    for yam_op_row in linked_yam_ops:
                        conn.execute(
                            """UPDATE yamazumi_elements
                               SET description = ?, updated_at = ?
                               WHERE id = ? AND project_id = ?""",
                            (new_op_val, now_iso(), str(yam_op_row[0]), project_id),
                        )
                    if old_op_val:
                        conn.execute(
                            """UPDATE process_part_groups
                               SET name = ?, updated_at = ?
                               WHERE project_id = ? AND scenario_id = ? AND work_element_id = ?
                                 AND LOWER(TRIM(COALESCE(name, ''))) = LOWER(TRIM(?))""",
                            (new_op_val, now_iso(), project_id, scenario_id, element_id, old_op_val),
                        )
            if element_id in existing_stations:
                new_station_val = str(values[station_idx] or "").strip()
                if (
                    new_station_val
                    and new_station_val.casefold() != existing_stations[element_id].strip().casefold()
                ):
                    target_pitch_info = scenario_pitches_by_num.get(new_station_val.casefold())
                    if target_pitch_info:
                        target_pitch_id, target_area_id = target_pitch_info
                        linked_yam_rows = conn.execute(
                            """SELECT e.id
                               FROM yamazumi_elements e
                               JOIN yamazumi_areas a ON a.id = e.area_id
                               WHERE e.project_id = ? AND a.scenario_id = ? AND e.process_element_id = ?""",
                            (project_id, scenario_id, element_id),
                        ).fetchall()
                        for yam_row in linked_yam_rows:
                            conn.execute(
                                """UPDATE yamazumi_elements
                                   SET pitch_id = ?, area_id = ?, updated_at = ?
                                   WHERE id = ? AND project_id = ?""",
                                (
                                    target_pitch_id,
                                    target_area_id,
                                    now_iso(),
                                    str(yam_row[0]),
                                    project_id,
                                ),
                            )
            if element_id in existing_models:
                new_model_app = str(values[model_idx] or "").strip()
                if new_model_app != existing_models[element_id].strip():
                    linked_yam = conn.execute(
                        """SELECT e.id
                           FROM yamazumi_elements e
                           JOIN yamazumi_areas a ON a.id = e.area_id
                           WHERE e.project_id = ? AND a.scenario_id = ? AND e.process_element_id = ?""",
                        (project_id, scenario_id, element_id),
                    ).fetchall()
                    if len(linked_yam) == 1:
                        raw_parts = [
                            p.strip()
                            for p in new_model_app.split(",")
                            if p.strip()
                        ]
                        if not raw_parts or any(
                            p.casefold() in {"all", "all models", "base"}
                            for p in raw_parts
                        ):
                            new_yam_variants = ["All models"]
                        else:
                            new_yam_variants = raw_parts
                        conn.execute(
                            """UPDATE yamazumi_elements
                               SET model_variant = ?, model_variants = ?, updated_at = ?
                               WHERE id = ? AND project_id = ?""",
                            (
                                new_yam_variants[0],
                                json.dumps(new_yam_variants),
                                now_iso(),
                                str(linked_yam[0][0]),
                                project_id,
                            ),
                        )
        for element_id, values in records:
            timestamp = now_iso()
            if element_id in existing_ids:
                conn.execute(
                    f"""UPDATE work_elements
                        SET {assignments}, updated_at=?
                        WHERE id=? AND project_id=? AND scenario_id=?""",
                    (*values, timestamp, element_id, project_id, scenario_id),
                )
            else:
                _create_work_element_with_started_ergonomics_review(
                    conn,
                    project_id,
                    scenario_id,
                    dict(zip(fields, values)),
                    timestamp,
                    work_element_id=element_id,
                )
        removed = existing_ids - saved_ids
        if removed:
            placeholders = ",".join("?" for _ in removed)
            removed_rows = conn.execute(
                f"""SELECT id, operation, description, station, sequence, location
                    FROM work_elements
                    WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
                (project_id, scenario_id, *removed),
            ).fetchall()
            now_str = now_iso()
            labels = [
                f"{str(r[1] or '').strip()} — {str(r[2] or '').strip()}".strip(" —")
                for r in removed_rows
            ]
            label = labels[0] if len(labels) == 1 else f"{len(removed)} process work elements ({', '.join(labels[:3])})"
            with capture_deletion_to_recycle_bin(
                conn,
                project_id=project_id,
                scenario_id=scenario_id,
                entity_type="Process Work Element",
                entity_table="work_elements",
                entity_id=next(iter(removed)) if len(removed) == 1 else "",
                entity_label=label,
            ):
                for r in removed_rows:
                    elem_id = r[0]
                    op_val = str(r[1] or "")
                    desc_val = str(r[2] or "")
                    pitch_val = str(r[3] or "")
                    seq_val = int(r[4] or 0)
                    loc_val = str(r[5] or "")

                    conn.execute(
                        """UPDATE quality_requirement_assignments
                           SET process_operation_snapshot = CASE WHEN process_operation_snapshot = '' THEN ? ELSE process_operation_snapshot END,
                               process_description_snapshot = CASE WHEN process_description_snapshot = '' THEN ? ELSE process_description_snapshot END,
                               station_pitch_snapshot = CASE WHEN station_pitch_snapshot = '' THEN ? ELSE station_pitch_snapshot END,
                               unlinked_at = CASE WHEN unlinked_at = '' THEN ? ELSE unlinked_at END,
                               work_element_id = NULL,
                               updated_at = ?
                           WHERE project_id=? AND scenario_id=? AND work_element_id=?""",
                        (op_val, desc_val, pitch_val, now_str, now_str, project_id, scenario_id, elem_id),
                    )

                    conn.execute(
                        """UPDATE equipment_process_links
                           SET process_operation_snapshot = CASE WHEN process_operation_snapshot = '' THEN ? ELSE process_operation_snapshot END,
                               process_description_snapshot = CASE WHEN process_description_snapshot = '' THEN ? ELSE process_description_snapshot END,
                               station_pitch_snapshot = CASE WHEN station_pitch_snapshot = '' THEN ? ELSE station_pitch_snapshot END,
                               unlinked_at = CASE WHEN unlinked_at = '' THEN ? ELSE unlinked_at END,
                               work_element_id = NULL,
                               updated_at = ?
                           WHERE project_id=? AND scenario_id=? AND work_element_id=?""",
                        (op_val, desc_val, pitch_val, now_str, now_str, project_id, scenario_id, elem_id),
                    )

                    conn.execute(
                        """UPDATE pfmea_entries
                           SET process_operation_snapshot = CASE WHEN process_operation_snapshot = '' THEN ? ELSE process_operation_snapshot END,
                               process_description_snapshot = CASE WHEN process_description_snapshot = '' THEN ? ELSE process_description_snapshot END,
                               process_pitch_snapshot = CASE WHEN process_pitch_snapshot = '' THEN ? ELSE process_pitch_snapshot END,
                               process_location_snapshot = CASE WHEN process_location_snapshot = '' THEN ? ELSE process_location_snapshot END,
                               process_sequence_snapshot = CASE WHEN process_sequence_snapshot = 0 THEN ? ELSE process_sequence_snapshot END,
                               work_element_id = NULL,
                               updated_at = ?
                           WHERE project_id=? AND scenario_id=? AND work_element_id=?""",
                        (op_val, desc_val, pitch_val, loc_val, seq_val, now_str, project_id, scenario_id, elem_id),
                    )

                conn.execute(
                    f"""UPDATE yamazumi_elements
                        SET process_element_id=NULL, process_sync_status='Needs IE review', updated_at=?
                        WHERE project_id=? AND process_element_id IN ({placeholders})""",
                    (now_str, project_id, *removed),
                )
                conn.execute(
                    f"""DELETE FROM work_elements WHERE project_id=? AND scenario_id=?
                        AND id IN ({placeholders})""",
                    (project_id, scenario_id, *removed),
                )

@cached_store_read
def get_pitch_unclassified_part_options(
    project_id: str,
    scenario_id: str,
    pitch_id: str,
) -> list[dict]:
    """Return unclassified process_part_options rows for work elements on this pitch."""
    if not project_id or not scenario_id or not pitch_id:
        return []
    with connection() as conn:
        y_rows = conn.execute(
            """SELECT e.process_element_id
               FROM yamazumi_elements e
               JOIN yamazumi_areas a ON a.id=e.area_id
               WHERE e.project_id=? AND a.scenario_id=? AND e.pitch_id=?
                 AND e.process_element_id IS NOT NULL AND TRIM(e.process_element_id) != ''""",
            (project_id, scenario_id, pitch_id),
        ).fetchall()
        work_ids = [str(r["process_element_id"]) for r in y_rows]
        if not work_ids:
            return []
        placeholders = ",".join("?" for _ in work_ids)
        rows = conn.execute(
            f"""SELECT option.id AS option_id, option.part_id, option.handling_type,
                       option.fishbone_assignment_id,
                       group_row.id AS group_id, group_row.name AS group_name,
                       group_row.section_id, group_row.work_element_id,
                       part.part_number, part.description AS part_description,
                       we.operation, we.station,
                       sec.name AS section_name
                FROM process_part_groups group_row
                JOIN process_part_options option ON option.group_id=group_row.id
                JOIN parts part ON part.id=option.part_id
                JOIN work_elements we ON we.id=group_row.work_element_id
                LEFT JOIN assembly_sections sec ON sec.id=group_row.section_id
                WHERE group_row.project_id=? AND group_row.scenario_id=?
                  AND group_row.work_element_id IN ({placeholders})
                  AND (option.handling_type IS NULL OR TRIM(option.handling_type) = '')
                ORDER BY we.sequence, we.id, part.part_number""",
            (project_id, scenario_id, *work_ids),
        ).fetchall()
        
        result = []
        for r in rows:
            opt = dict(r)
            sec_id = str(r["section_id"] or "")
            part_id = str(r["part_id"] or "")
            if sec_id and part_id:
                p_opts = process_part_placement_options(
                    project_id, scenario_id, sec_id, part_id
                )
                opt["placements"] = p_opts.to_dict(orient="records") if not p_opts.empty else []
            else:
                opt["placements"] = []
            result.append(opt)
        return result

@cached_store_read
def get_scenario_part_handling_options(
    project_id: str,
    scenario_id: str,
    unclassified_only: bool = False,
) -> list[dict]:
    """Return part options with handling status across the scenario for Materials Review."""
    if not project_id or not scenario_id:
        return []
    with connection() as conn:
        condition = "AND (option.handling_type IS NULL OR TRIM(option.handling_type) = '')" if unclassified_only else ""
        rows = conn.execute(
            f"""SELECT option.id AS option_id, option.part_id, option.handling_type,
                       option.fishbone_assignment_id,
                       COALESCE(option.source_snapshot_json, '') AS source_snapshot_json,
                       COALESCE(option.source_acknowledged_at, '') AS source_acknowledged_at,
                       group_row.id AS group_id, group_row.name AS group_name,
                       group_row.selection_rule,
                       COALESCE(option.quantity, group_row.quantity) AS quantity,
                       COALESCE(group_row.notes, '') AS group_notes,
                       group_row.section_id, group_row.work_element_id,
                       part.part_number, part.description AS part_description,
                       we.operation, we.station,
                       COALESCE(
                           (SELECT NULLIF(TRIM(yamazumi.description), '')
                            FROM yamazumi_elements yamazumi
                            WHERE yamazumi.project_id=group_row.project_id
                              AND yamazumi.process_element_id=we.id
                            ORDER BY yamazumi.sequence, yamazumi.id LIMIT 1),
                           NULLIF(TRIM(we.operation), ''),
                           ''
                       ) AS work_element_label,
                       sec.name AS section_name,
                       fba.use_description AS fishbone_use_description
                FROM process_part_groups group_row
                JOIN process_part_options option ON option.group_id=group_row.id
                JOIN parts part ON part.id=option.part_id
                JOIN work_elements we ON we.id=group_row.work_element_id
                LEFT JOIN assembly_sections sec ON sec.id=group_row.section_id
                LEFT JOIN fishbone_part_assignments fba ON fba.id=option.fishbone_assignment_id
                WHERE group_row.project_id=? AND group_row.scenario_id=?
                  {condition}
                ORDER BY we.station, we.sequence, part.part_number""",
            (project_id, scenario_id),
        ).fetchall()
        
        result = []
        for r in rows:
            opt = dict(r)
            sec_id = str(r["section_id"] or "")
            part_id = str(r["part_id"] or "")
            if sec_id and part_id:
                p_opts = process_part_placement_options(
                    project_id, scenario_id, sec_id, part_id
                )
                opt["placements"] = p_opts.to_dict(orient="records") if not p_opts.empty else []
            else:
                opt["placements"] = []
            ht = str(opt.get("handling_type") or "").strip()
            if ht:
                live_snap = build_materials_process_snapshot(opt)
                diffs = format_process_snapshot_diff(opt.get("source_snapshot_json"), live_snap)
                opt["upstream_changed"] = bool(diffs)
                opt["upstream_diff_summary"] = " · ".join(diffs)
                opt["sync_status"] = "⚠️ Upstream change" if diffs else "Synced"
            else:
                opt["upstream_changed"] = False
                opt["upstream_diff_summary"] = ""
                opt["sync_status"] = "Unclassified"
            result.append(opt)
        return result


def acknowledge_materials_upstream_changes(
    project_id: str,
    scenario_id: str,
    option_ids: list[str],
    editor_name: str = "Collaborator",
) -> dict:
    """Refresh stored upstream Process snapshots for selected Materials part options and log history."""
    editor = str(editor_name or "").strip() or "Collaborator"
    ids = list(dict.fromkeys(str(v).strip() for v in option_ids if str(v).strip()))
    timestamp = now_iso()
    if not ids:
        return {"row_count": 0, "acknowledged_ids": [], "timestamp": timestamp}
    placeholders = ",".join("?" for _ in ids)
    acknowledged_ids: list[str] = []
    with connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM planning_scenarios WHERE id=? AND project_id=?",
            (scenario_id, project_id),
        ).fetchone():
            raise ValueError("The active planning scenario no longer exists.")
        opt_inputs = _fetch_part_option_snapshot_inputs(
            conn, project_id, scenario_id, ids
        )
        for oid in ids:
            if oid not in opt_inputs:
                continue
            snap_json = json.dumps(
                build_materials_process_snapshot(opt_inputs[oid]), sort_keys=True
            )
            conn.execute(
                """UPDATE process_part_options
                   SET source_snapshot_json=?, source_acknowledged_at=?, updated_at=?
                   WHERE id=?""",
                (snap_json, timestamp, timestamp, oid),
            )
            acknowledged_ids.append(oid)
        if acknowledged_ids:
            record_audit_event(
                project_id,
                "Process part options",
                "Acknowledge upstream change",
                len(acknowledged_ids),
                editor,
                {
                    "scenario_id": scenario_id,
                    "acknowledged_option_ids": acknowledged_ids,
                },
                _conn=conn,
            )
    return {
        "row_count": len(acknowledged_ids),
        "acknowledged_ids": acknowledged_ids,
        "timestamp": timestamp,
    }


def work_element_downstream_impact(
    project_id: str,
    scenario_id: str,
    work_element_ids: list[str] | set[str] | tuple[str, ...],
) -> dict:
    """Calculate the downstream impact across Quality, PFMEA, Equipment, and Safety before deleting work elements."""
    ids = [str(x) for x in work_element_ids if str(x).strip()]
    if not ids:
        return {
            "total_impact": 0,
            "has_impact": False,
            "quality_count": 0,
            "pfmea_count": 0,
            "equipment_count": 0,
            "safety_count": 0,
            "quality_records": [],
            "pfmea_records": [],
            "equipment_records": [],
            "safety_records": [],
            "operations_affected": [],
        }
    with _db_core.connection() as conn:
        placeholders = ",".join("?" for _ in ids)

        op_rows = conn.execute(
            f"""SELECT id, operation, description, station FROM work_elements
                WHERE project_id=? AND scenario_id=? AND id IN ({placeholders})""",
            (project_id, scenario_id, *ids),
        ).fetchall()
        op_map = {row[0]: {"operation": row[1] or "", "description": row[2] or "", "station": row[3] or ""} for row in op_rows}

        def _has_table(tbl: str) -> bool:
            return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone() is not None

        quality_records = []
        if _has_table("quality_requirement_assignments"):
            q_rows = conn.execute(
                f"""SELECT id, quality_requirement_id, requirement_type, description, unique_identifier, work_element_id
                    FROM quality_requirement_assignments
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            ).fetchall()
            quality_records = [
                {
                    "id": r[0],
                    "quality_requirement_id": r[1],
                    "requirement_type": r[2],
                    "description": r[3],
                    "unique_identifier": r[4],
                    "work_element_id": r[5],
                    "operation": op_map.get(r[5], {}).get("operation", ""),
                    "station": op_map.get(r[5], {}).get("station", ""),
                }
                for r in q_rows
            ]

        pfmea_records = []
        if _has_table("pfmea_entries"):
            pfmea_rows = conn.execute(
                f"""SELECT id, potential_failure_mode, class_code, work_element_id
                    FROM pfmea_entries
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            ).fetchall()
            pfmea_records = [
                {
                    "id": r[0],
                    "potential_failure_mode": r[1],
                    "class_code": r[2],
                    "work_element_id": r[3],
                    "operation": op_map.get(r[3], {}).get("operation", ""),
                    "station": op_map.get(r[3], {}).get("station", ""),
                }
                for r in pfmea_rows
            ]

        equipment_records = []
        if _has_table("equipment_process_links"):
            eq_rows = conn.execute(
                f"""SELECT id, placement_id, work_element_id
                    FROM equipment_process_links
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders})""",
                (project_id, scenario_id, *ids),
            ).fetchall()
            equipment_records = [
                {
                    "id": r[0],
                    "placement_id": r[1],
                    "work_element_id": r[2],
                    "operation": op_map.get(r[2], {}).get("operation", ""),
                    "station": op_map.get(r[2], {}).get("station", ""),
                }
                for r in eq_rows
            ]

        safety_records = []
        if _has_table("safety_requirements"):
            safe_rows = conn.execute(
                f"""SELECT id, requirement_description, work_element_id
                    FROM safety_requirements
                    WHERE project_id=? AND scenario_id=? AND work_element_id IN ({placeholders}) AND active=1""",
                (project_id, scenario_id, *ids),
            ).fetchall()
            safety_records = [
                {
                    "id": r[0],
                    "requirement_description": r[1],
                    "work_element_id": r[2],
                    "operation": op_map.get(r[2], {}).get("operation", ""),
                    "station": op_map.get(r[2], {}).get("station", ""),
                }
                for r in safe_rows
            ]

        ops_affected = sorted({
            op_map[w_id]["operation"]
            for w_id in (
                [r["work_element_id"] for r in quality_records]
                + [r["work_element_id"] for r in pfmea_records]
                + [r["work_element_id"] for r in equipment_records]
                + [r["work_element_id"] for r in safety_records]
            )
            if w_id in op_map and op_map[w_id]["operation"]
        })

        total = len(quality_records) + len(pfmea_records) + len(equipment_records) + len(safety_records)
        return {
            "total_impact": total,
            "has_impact": total > 0,
            "quality_count": len(quality_records),
            "pfmea_count": len(pfmea_records),
            "equipment_count": len(equipment_records),
            "safety_count": len(safety_records),
            "quality_records": quality_records,
            "pfmea_records": pfmea_records,
            "equipment_records": equipment_records,
            "safety_records": safety_records,
            "operations_affected": ops_affected,
        }


@cached_store_read
def process_readiness_metrics(project_id: str, scenario_id: str) -> dict:
    """Compute scenario-wide Process at a Glance readiness metrics and functional alert counts."""
    with connection() as conn:
        def _has_table(tbl: str) -> bool:
            return (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (tbl,),
                ).fetchone()
                is not None
            )

        # 1. Process steps and Yamazumi sync
        work_rows = conn.execute(
            "SELECT id FROM work_elements WHERE project_id=? AND scenario_id=?",
            (project_id, scenario_id),
        ).fetchall()
        work_ids = [str(r["id"]) for r in work_rows]
        work_id_set = set(work_ids)
        total_steps = len(work_ids)

        yamazumi_rows = conn.execute(
            """SELECT e.id, e.process_element_id, e.area_id, e.pitch_id,
                      COALESCE(NULLIF(TRIM(e.work_type), ''), 'Cycle') AS work_type,
                      e.description, e.time_s, e.model_variant, e.model_variants
               FROM yamazumi_elements e
               JOIN yamazumi_areas a ON a.id=e.area_id
               WHERE e.project_id=? AND a.scenario_id=?
               ORDER BY e.sequence, e.id""",
            (project_id, scenario_id),
        ).fetchall()
        grouped_yamazumi_rows = _group_same_pitch_yamazumi_rows(yamazumi_rows)
        total_yamazumi_elements = len(grouped_yamazumi_rows)
        linked_process_ids: set[str] = set()
        synced_yamazumi_elements = 0
        for yr in grouped_yamazumi_rows:
            pid = str(yr.get("process_element_id") or "").strip()
            if pid and pid in work_id_set:
                synced_yamazumi_elements += 1
                linked_process_ids.add(pid)
        unlinked_process_steps = len(work_id_set - linked_process_ids)
        unsynced_yamazumi_elements = total_yamazumi_elements - synced_yamazumi_elements

        # 2. Part consumption coverage
        fb_rows = conn.execute(
            """SELECT DISTINCT assignment.part_id
               FROM fishbone_part_assignments assignment
               JOIN parts part
                 ON part.id=assignment.part_id AND part.project_id=assignment.project_id
               JOIN assembly_sections section
                 ON section.id=assignment.section_id AND section.project_id=assignment.project_id
               LEFT JOIN part_scenario_activity activity
                 ON activity.project_id=assignment.project_id
                AND activity.scenario_id=?
                AND activity.part_id=assignment.part_id
               WHERE assignment.project_id=?
                 AND section.active=1
                 AND COALESCE(activity.active, 1)=1""",
            (scenario_id, project_id),
        ).fetchall()
        active_fb_part_ids = {str(r[0]) for r in fb_rows if r[0]}
        total_fishbone_parts = len(active_fb_part_ids)

        opt_rows = conn.execute(
            """SELECT option.part_id, option.handling_type
               FROM process_part_options option
               JOIN process_part_groups group_row ON group_row.id=option.group_id
               JOIN work_elements we
                 ON we.id=group_row.work_element_id
                AND we.project_id=group_row.project_id
                AND we.scenario_id=group_row.scenario_id
               JOIN parts part
                 ON part.id=option.part_id AND part.project_id=group_row.project_id
               LEFT JOIN part_scenario_activity activity
                 ON activity.project_id=group_row.project_id
                AND activity.scenario_id=group_row.scenario_id
                AND activity.part_id=option.part_id
               WHERE group_row.project_id=? AND group_row.scenario_id=?
                 AND COALESCE(activity.active, 1)=1""",
            (project_id, scenario_id),
        ).fetchall()
        consumed_fb_part_ids = {
            str(r["part_id"])
            for r in opt_rows
            if str(r["handling_type"] or "").strip() == "Consume"
            and str(r["part_id"]) in active_fb_part_ids
        }
        consumed_parts = len(consumed_fb_part_ids)
        unclassified_pairings = sum(
            1 for r in opt_rows if not str(r["handling_type"] or "").strip()
        )

        # 3. Pitch visual aids
        pitch_rows = conn.execute(
            """SELECT p.id, COALESCE(p.status, 'Active') AS status
               FROM yamazumi_pitches p
               JOIN yamazumi_areas a ON a.id=p.area_id
               WHERE p.project_id=? AND a.scenario_id=?""",
            (project_id, scenario_id),
        ).fetchall()
        all_pitch_ids = {str(r["id"]) for r in pitch_rows if r["id"]}
        active_pitch_ids = {
            str(r["id"])
            for r in pitch_rows
            if r["id"] and str(r["status"] or "Active").strip() == "Active"
        }
        target_pitch_ids = active_pitch_ids if active_pitch_ids else all_pitch_ids
        total_active_pitches = len(target_pitch_ids)

        media_rows = (
            conn.execute(
                """SELECT id, pitch_id
                   FROM process_visual_media
                   WHERE project_id=? AND scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
            if _has_table("process_visual_media")
            else []
        )
        total_visual_media = len(media_rows)
        tagged_rows = (
            conn.execute(
                """SELECT t.media_id, y.pitch_id
                   FROM process_visual_media_tags t
                   LEFT JOIN yamazumi_elements y ON (
                       y.process_element_id = t.work_element_id
                       OR (y.process_element_id IS NULL AND y.id = t.work_element_id)
                   ) AND y.project_id = t.project_id
                   LEFT JOIN yamazumi_areas a ON a.id = y.area_id AND a.scenario_id = t.scenario_id
                   WHERE t.project_id=? AND t.scenario_id=?""",
                (project_id, scenario_id),
            ).fetchall()
            if _has_table("process_visual_media_tags")
            else []
        )
        tagged_media_ids: set[str] = set()
        pitches_with_media_ids: set[str] = set()
        for tr in tagged_rows:
            mid = str(tr["media_id"] or "").strip()
            if mid:
                tagged_media_ids.add(mid)
            t_pid = str(tr["pitch_id"] or "").strip()
            if t_pid in target_pitch_ids:
                pitches_with_media_ids.add(t_pid)
        untagged_visual_media = 0
        for mr in media_rows:
            mid = str(mr["id"] or "").strip()
            m_pid = str(mr["pitch_id"] or "").strip()
            if mid not in tagged_media_ids:
                untagged_visual_media += 1
                if m_pid in target_pitch_ids:
                    pitches_with_media_ids.add(m_pid)
        pitches_with_media = len(pitches_with_media_ids)

        # 4. Functional alerts (Quality, Materials, Ergo, Safety)
        torque_alert_count = 0
        pfmea_alert_count = 0
        ergo_alert_count = 0
        safety_req_count = 0
        steps_missing_ppe = 0

        if work_ids:
            if (
                _has_table("quality_requirement_assignments")
                and _has_table("quality_requirement_torque_details")
            ):
                torque_alert_count = int(
                    conn.execute(
                        """SELECT COUNT(*)
                           FROM quality_requirement_assignments assignment
                           JOIN quality_requirement_torque_details detail
                             ON detail.quality_requirement_id=assignment.quality_requirement_id
                            AND detail.project_id=assignment.project_id
                           JOIN work_elements work
                             ON work.id=assignment.work_element_id
                            AND work.project_id=assignment.project_id
                            AND work.scenario_id=assignment.scenario_id
                           WHERE assignment.project_id=? AND assignment.scenario_id=?
                             AND assignment.requirement_type='Torque'""",
                        (project_id, scenario_id),
                    ).fetchone()[0]
                )

            if _has_table("pfmea_entries"):
                pfmea_alert_count = int(
                    conn.execute(
                        """SELECT COUNT(*)
                           FROM pfmea_entries pfmea
                           JOIN work_elements work
                             ON work.id=pfmea.work_element_id
                            AND work.project_id=pfmea.project_id
                            AND work.scenario_id=pfmea.scenario_id
                           LEFT JOIN pfmea_effects effect ON effect.pfmea_entry_id=pfmea.id
                           LEFT JOIN pfmea_risk_rows risk ON risk.pfmea_entry_id=pfmea.id
                           WHERE pfmea.project_id=? AND pfmea.scenario_id=?
                             AND (COALESCE(effect.severity, 0) >= 8 OR COALESCE(risk.rpn, 0) >= 100)""",
                        (project_id, scenario_id),
                    ).fetchone()[0]
                )

            if _has_table("ergonomics_reviews"):
                ergo_alert_count = int(
                    conn.execute(
                        """SELECT COUNT(*)
                           FROM ergonomics_reviews review
                           JOIN work_elements work
                             ON work.id=review.work_element_id
                            AND work.project_id=review.project_id
                            AND work.scenario_id=review.scenario_id
                           WHERE review.project_id=? AND review.scenario_id=?
                             AND review.risk_classification IN ('Red', 'Favorable Red', 'Yellow')
                             AND review.status IN ('Started', 'Open', 'Pending', 'Validation')""",
                        (project_id, scenario_id),
                    ).fetchone()[0]
                )

            work_ids_with_ppe: set[str] = set()
            if _has_table("safety_requirements"):
                s_rows = conn.execute(
                    """SELECT safety.ppe, safety.work_element_id
                       FROM safety_requirements safety
                       JOIN work_elements work
                         ON work.id=safety.work_element_id
                        AND work.project_id=safety.project_id
                        AND work.scenario_id=safety.scenario_id
                       WHERE safety.project_id=? AND safety.scenario_id=?
                         AND safety.active=1""",
                    (project_id, scenario_id),
                ).fetchall()
                safety_req_count = len(s_rows)
                for sr in s_rows:
                    raw_ppe = sr["ppe"] if "ppe" in sr.keys() else ""
                    if parse_ppe(raw_ppe):
                        work_ids_with_ppe.add(str(sr["work_element_id"]))

            if (
                _has_table("equipment_process_links")
                and _has_table("equipment_placements")
                and _has_table("equipment_function_links")
            ):
                s_eq_rows = conn.execute(
                    """SELECT link.work_element_id
                       FROM equipment_process_links link
                       JOIN equipment_placements placement ON placement.id=link.placement_id
                       JOIN equipment_function_links func ON func.equipment_id=placement.equipment_id
                       WHERE link.project_id=? AND link.scenario_id=?
                         AND func.functional_area='Safety'""",
                    (project_id, scenario_id),
                ).fetchall()
                for eqr in s_eq_rows:
                    if eqr["work_element_id"]:
                        work_ids_with_ppe.add(str(eqr["work_element_id"]))

            steps_missing_ppe = len(work_id_set - work_ids_with_ppe)

        quality_alerts = torque_alert_count + pfmea_alert_count
        materials_alerts = unclassified_pairings
        ergo_alerts = ergo_alert_count
        safety_alerts = safety_req_count + steps_missing_ppe
        total_alerts = quality_alerts + materials_alerts + ergo_alerts + safety_alerts

        return {
            "total_steps": total_steps,
            "total_yamazumi_elements": total_yamazumi_elements,
            "synced_yamazumi_elements": synced_yamazumi_elements,
            "unsynced_yamazumi_elements": unsynced_yamazumi_elements,
            "unlinked_process_steps": unlinked_process_steps,
            "total_fishbone_parts": total_fishbone_parts,
            "consumed_parts": consumed_parts,
            "unclassified_pairings": unclassified_pairings,
            "total_active_pitches": total_active_pitches,
            "pitches_with_media": pitches_with_media,
            "total_visual_media": total_visual_media,
            "untagged_visual_media": untagged_visual_media,
            "quality_alerts": quality_alerts,
            "torque_alert_count": torque_alert_count,
            "pfmea_alert_count": pfmea_alert_count,
            "materials_alerts": materials_alerts,
            "ergo_alerts": ergo_alerts,
            "safety_alerts": safety_alerts,
            "safety_req_count": safety_req_count,
            "steps_missing_ppe": steps_missing_ppe,
            "total_alerts": total_alerts,
        }


_PROCESS_STORE_REV_20261102 = 20
__domain_exports__ = ['part_has_model_variants', 'sync_model_variant_placement_selections', 'catalog_part_photos_for_pitch', 'copy_part_photo_to_pitch_visual_media', 'copy_pitch_visual_media', '_YAMAZUMI_PITCH_ADDRESS_PATTERN', '_normalize_handling_type', '_normalize_fishbone_assignment_id', '_process_part_assignment_consume_count', '_validate_process_part_option_handling', 'process_part_placement_options', 'validate_process_part_option_pairings', 'yamazumi_elements_for_section', 'yamazumi_context_for_process', 'process_element_id_for_yamazumi', 'process_part_groups', 'save_process_part_group', 'set_part_weight_lb', 'set_process_part_option_handling_type', 'get_pitch_unclassified_part_options', 'get_scenario_part_handling_options', 'acknowledge_materials_upstream_changes', 'work_element_criticality', 'delete_process_part_groups', 'delete_process_part_group', 'unlink_part_from_process_group', 'pin_map_for_scenario', 'reconcile_yamazumi_to_process', '_op_id_depth_letter', 'parse_yamazumi_pitch_address', 'work_element_op_contexts', 'work_element_op_ids', 'work_element_op_id', 'work_element_validation_contexts', 'process_pitch_visual_summary', 'process_readiness_metrics', 'scenario_pitch_visual_coverage', 'update_work_element_tool_and_resource', 'replace_work_elements', 'get_pitch_visual_media', 'save_pitch_visual_media', 'save_pitch_visual_media_url', 'update_pitch_visual_media', 'update_pitch_visual_annotations', 'delete_pitch_visual_media', 'MAX_VISUAL_IMAGE_BYTES', 'MAX_VISUAL_VIDEO_BYTES', 'MAX_CAD_FILE_SIZE_BYTES', 'MAX_CAD_FILE_SIZE_MB', 'work_element_downstream_impact']
for _export_name in __domain_exports__:
    if callable(globals()[_export_name]):
        globals()[_export_name] = _db_core.domain_entrypoint(globals()[_export_name])
_db_core.register_domain_module(_sys.modules[__name__], __domain_exports__)
