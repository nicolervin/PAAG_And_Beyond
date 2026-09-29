import sys
sys.path.insert(0, ".")
import json
import pandas as pd
from utils.excel_io import _parse_pits_bom_sheet
from utils.store import connection

def backfill_db():
    project_id = "a6dfafea-aa9a-46c6-ba99-9fe40cd600b3"
    print("Reading scratch/pits_sample.xlsm...")
    raw_df = pd.read_excel("scratch/pits_sample.xlsm", sheet_name="BOM", header=None, dtype=object)
    result = _parse_pits_bom_sheet(raw_df, "BOM")
    occs = result["occurrences"]
    print(f"Parsed {len(occs)} occurrences from Excel.")
    
    updated_count = 0
    with connection() as conn:
        for occ in occs:
            s_row = occ["source_row"]
            raw_levels_json = json.dumps(occ["raw_levels"], ensure_ascii=False, sort_keys=True, default=str)
            prop_qty = occ["proposed_quantity"]
            raw_qty_text = occ["raw_quantity_text"]
            
            cur = conn.execute(
                """
                UPDATE pits_bom_occurrences
                SET raw_levels_json = ?,
                    proposed_quantity = ?,
                    raw_quantity_text = ?
                WHERE project_id = ? AND source_row = ?
                """,
                (raw_levels_json, prop_qty, raw_qty_text, project_id, s_row),
            )
            updated_count += cur.rowcount

    print(f"Successfully updated {updated_count} occurrence rows in paag.db!")

if __name__ == "__main__":
    backfill_db()
