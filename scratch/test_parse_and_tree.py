import sys
sys.path.insert(0, '.')
import json
import pandas as pd
from utils.excel_io import _detect_header_row, _clean_excel_header, _clean_tracker_number, _clean_value

def test_parse_and_tree():
    raw_df = pd.read_excel("scratch/pits_sample.xlsm", sheet_name="BOM", header=None, dtype=object)
    header_row = _detect_header_row(raw_df, {"intracker", "partnumber", "level1", "level2"})
    assert header_row == 7, f"Expected header_row=7, got {header_row}"

    # Detect model columns
    model_columns = {}
    for col_idx in range(14, raw_df.shape[1]):
        for r_check in range(header_row):
            val = raw_df.iat[r_check, col_idx]
            if val is not None:
                s_val = str(val).strip()
                if len(s_val) >= 4 and not any(kw in s_val.lower() for kw in ("pick cost", "standard", "engineering manager", "po")):
                    try:
                        float(s_val)
                    except ValueError:
                        model_columns[col_idx] = s_val
                        break

    print(f"Detected {len(model_columns)} model columns.")
    assert len(model_columns) >= 90, f"Expected >= 90 models, got {len(model_columns)}"

    header = raw_df.iloc[header_row].tolist()
    data = raw_df.iloc[header_row + 1:].copy().reset_index(drop=True)
    
    occurrences = []
    for source_index, row in data.iterrows():
        source_row = int(source_index) + int(header_row) + 2
        child_tracker = _clean_tracker_number(row.iloc[0] if len(row) else "")
        part_number = _clean_tracker_number(row.iloc[1] if len(row) > 1 else "")
        description = _clean_tracker_number(row.iloc[2] if len(row) > 2 else "")
        level_values = [row.iloc[index] if index < len(row) else None for index in range(3, 14)]
        populated_levels = [
            index + 1
            for index, value in enumerate(level_values)
            if value is not None and not pd.isna(value) and str(value).strip()
        ]
        if not child_tracker and not part_number and not description and not populated_levels:
            continue
        if not populated_levels:
            continue
            
        depth = populated_levels[0]
        
        # Model usages
        model_usages = {}
        for col_idx, m_name in model_columns.items():
            if col_idx < len(row):
                u_val = row.iloc[col_idx]
                if u_val is not None:
                    try:
                        qty = float(u_val)
                        if qty > 0:
                            model_usages[m_name] = qty
                    except (ValueError, TypeError):
                        pass

        raw_levels = {
            f"Level {index + 1}": _clean_value(value)
            for index, value in enumerate(level_values)
            if value is not None and not pd.isna(value) and str(value).strip()
        }
        if model_usages:
            raw_levels["model_usages"] = model_usages
            
        occurrences.append({
            "source_row": source_row,
            "child_tracker": child_tracker,
            "part_number": part_number,
            "description": description,
            "depth": depth,
            "model_usages": model_usages,
            "raw_levels_json": json.dumps(raw_levels),
        })

    print(f"Parsed {len(occurrences)} occurrences.")

    # Now simulate model tree for HPS15BTHRWW
    target_model = "HPS15BTHRWW"
    model_nodes = []
    stack = {}
    
    for occ in occurrences:
        usages = occ["model_usages"]
        if target_model not in usages:
            continue
        qty = usages[target_model]
        depth = occ["depth"]
        
        node = {
            "source_row": occ["source_row"],
            "tracker": occ["child_tracker"],
            "part": occ["part_number"],
            "desc": occ["description"],
            "depth": depth,
            "qty": qty,
            "children": [],
        }
        
        parent = stack.get(depth - 1)
        if parent:
            parent["children"].append(node)
            
        stack[depth] = node
        stack = {k: v for k, v in stack.items() if k <= depth}
        model_nodes.append(node)
        
    roots = [n for n in model_nodes if n["depth"] == 1]
    print(f"Model {target_model}: Total {len(model_nodes)} parts, {len(roots)} roots")
    assert len(model_nodes) == 319, f"Expected 319 parts for {target_model}, got {len(model_nodes)}"
    
    # Check L2 and L3 children
    active_root = [r for r in roots if len(r["children"]) > 0][0]
    print(f"Active Root: {active_root['part']} with {len(active_root['children'])} L2 children")
    assert len(active_root["children"]) == 80, f"Expected 80 L2 children, got {len(active_root['children'])}"
    
    # Check LOW SIDE ASM
    low_side = [c for c in active_root["children"] if "LOW SIDE ASM" in c["desc"]][0]
    print(f"LOW SIDE ASM children: {len(low_side['children'])}")
    assert len(low_side["children"]) == 4, f"Expected 4 L3 children under LOW SIDE ASM, got {len(low_side['children'])}"
    
    print("ALL ASSERTIONS PASSED PERFECTLY!")

if __name__ == "__main__":
    test_parse_and_tree()
