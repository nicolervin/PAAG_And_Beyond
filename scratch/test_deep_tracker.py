import sys
sys.path.insert(0, '.')
from utils.store import pits_bom_model_tree, connection

# Check which root has the deepest subassemblies
with connection() as conn:
    rows = conn.execute("""
        SELECT parent_tracker_number, count(*) as cnt
        FROM pits_bom_occurrences
        WHERE project_id = 'a6dfafea-aa9a-46c6-ba99-9fe40cd600b3' AND parent_tracker_number != ''
        GROUP BY parent_tracker_number
        ORDER BY cnt DESC
        LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"Parent tracker {r['parent_tracker_number']} has {r['cnt']} children")
