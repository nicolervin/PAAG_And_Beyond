import streamlit as st
from streamlit.testing.v1 import AppTest

script = """
import streamlit as st

def render_node(node):
    has_children = bool(node.get('children'))
    if has_children:
        with st.expander(f"📁 L{node['depth']} {node['part_number']} — {node['desc']}", expanded=False):
            st.button('Inspect', key=f"btn_{node['id']}")
            for child in node['children']:
                render_node(child)
    else:
        st.write(f"📄 L{node['depth']} {node['part_number']} — {node['desc']}")

tree = [
    {'id': '1', 'depth': 1, 'part_number': '245D1###G19_22', 'desc': 'AASM REFRIG', 'children': [
        {'id': '2', 'depth': 2, 'part_number': '197D2373G006', 'desc': 'DOOR ASM FZ', 'children': [
            {'id': '3', 'depth': 3, 'part_number': '100085P018', 'desc': 'SCREW', 'children': []}
        ]}
    ]}
]

for root in tree:
    render_node(root)
"""

at = AppTest.from_string(script).run()
print('Exceptions:', at.exception)
print('Expanders found:', len(at.expander))
