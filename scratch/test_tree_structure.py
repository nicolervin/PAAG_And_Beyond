import sys
sys.path.insert(0, '.')
from utils.store import pits_bom_model_tree

tree_data = pits_bom_model_tree('a6dfafea-aa9a-46c6-ba99-9fe40cd600b3')
roots = tree_data['roots']
print(f"Total roots: {len(roots)}")

# Find root 406
root_406 = next((r for r in roots if r['child_tracker'] == '406'), None)
if root_406:
    print(f"Root 406: {root_406['part_number']} - {root_406['description']}")
    print(f"Immediate children of 406: {len(root_406['children'])}")
    for i, c in enumerate(root_406['children'][:10]):
        num_sub = len(c['children'])
        print(f"  Child {i+1}: L{c['depth']} [Trk {c['child_tracker']}] {c['part_number']} - {c['description']} (sub-children: {num_sub})")
