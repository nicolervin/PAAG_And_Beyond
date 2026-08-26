from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from utils import store


class SectionQualifyingConditionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = store.ROOT / "section_conditions_test.db"
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.db_path}{suffix}")
            if candidate.exists():
                candidate.unlink()
        self.db_patch = patch.object(
            store, "DB_PATH", self.db_path
        )
        self.db_patch.start()
        store.init_db()
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO projects
                   (id, name, program, product_line, owner, revision, status,
                    takt_time_s, notes, created_at, updated_at)
                   VALUES ('project-test', 'Test project', '', '', '', 'A', 'Draft',
                           60, '', ?, ?)""",
                (timestamp, timestamp),
            )
            conn.execute(
                """INSERT INTO planning_scenarios
                   (id, project_id, name, revision_label, revision_sequence, status,
                    takt_time_s, created_at, updated_at)
                   VALUES ('scenario-test', 'project-test', 'Current', '1', 1,
                           'Working', 60, ?, ?)""",
                (timestamp, timestamp),
            )
            conn.executemany(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, description,
                    sequence, active, updated_at)
                   VALUES (?, 'project-test', 'Product', ?, ?, '', ?, 1, ?)""",
                [
                    ('feature-brand', 'Brand', json.dumps(['Acme', 'Other']), 10, timestamp),
                    ('feature-line', 'Product line', json.dumps(['Commercial']), 20, timestamp),
                ],
            )
            conn.executemany(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, parent_id, sequence,
                    description, active, created_at, updated_at)
                   VALUES (?, 'project-test', ?, ?, ?, ?, '', 1, ?, ?)""",
                [
                    ('section-parent', 'Parent', 'Main spine', None, 10, timestamp, timestamp),
                    ('section-child', 'Child', 'Subassembly', 'section-parent', 10, timestamp, timestamp),
                    ('section-open', 'Open', 'Main spine', None, 20, timestamp, timestamp),
                ],
            )
            conn.executemany(
                """INSERT INTO parts
                   (id, project_id, part_number, description, quantity, revision,
                    source, image_path, model_applicability, notes, updated_at)
                   VALUES (?, 'project-test', ?, '', 1, '0', 'Manual', '', 'All', '', ?)""",
                [
                    ('part-ruled', 'P-1', timestamp),
                    ('part-open', 'P-2', timestamp),
                ],
            )
            conn.executemany(
                """INSERT INTO fishbone_part_assignments
                   (id, project_id, part_id, section_id, sequence, quantity,
                    use_description, notes, updated_at)
                   VALUES (?, 'project-test', ?, ?, 10, 1, '', '', ?)""",
                [
                    ('use-parent-ruled', 'part-ruled', 'section-parent', timestamp),
                    ('use-parent-open', 'part-open', 'section-parent', timestamp),
                    ('use-open-ruled', 'part-ruled', 'section-open', timestamp),
                    ('use-child-open', 'part-open', 'section-child', timestamp),
                ],
            )
            conn.execute(
                """INSERT INTO part_feature_rules
                   (project_id, part_id, feature_id, value, updated_at)
                   VALUES ('project-test', 'part-ruled', 'feature-line', 'Commercial', ?)""",
                (timestamp,),
            )
            conn.execute(
                """INSERT INTO fishbone_nodes
                   (id, project_id, sequence, depth, part_number, description,
                    source, updated_at)
                   VALUES ('blocked-node', 'project-test', 10, 0, 'BLOCKED',
                           'Must remain untouched', 'Test', ?)""",
                (timestamp,),
            )

    def tearDown(self) -> None:
        self.db_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.db_path}{suffix}")
            if candidate.exists():
                candidate.unlink()

    def save_condition(self, section_id: str, feature_id: str, value: str) -> None:
        store.save_assembly_section_feature_conditions(
            'project-test',
            section_id,
            pd.DataFrame([{'id': '', 'feature_id': feature_id, 'value': value}]),
        )

    def test_validation_stale_preservation_and_fail_open_lookup(self) -> None:
        empty = store.assembly_section_feature_conditions(
            'project-test', 'section-parent'
        )
        self.assertTrue(empty.empty)
        self.assertEqual(str(empty['feature_name'].dtype), 'string')
        self.assertEqual(str(empty['is_stale'].dtype), 'bool')

        self.save_condition('section-parent', 'feature-brand', 'Acme')
        conditions = store.assembly_section_feature_conditions(
            'project-test', 'section-parent'
        )
        self.assertEqual(len(conditions), 1)
        self.assertFalse(bool(conditions.iloc[0]['is_stale']))

        brand_matches = store.fishbone_visual_feature_matches(
            'project-test', [('feature-brand', 'Acme')]
        )
        self.assertEqual(brand_matches, {'use-parent-open', 'use-child-open'})
        line_matches = store.fishbone_visual_feature_matches(
            'project-test', [('feature-line', 'Commercial')]
        )
        self.assertEqual(line_matches, {'use-open-ruled', 'use-child-open'})

        edited_features = store.complexity_features('project-test')
        edited_features.loc[
            edited_features['id'].astype(str) == 'feature-brand', 'allowed_choices'
        ] = 'Other'
        store.update_complexity_features('project-test', edited_features)
        stale = store.assembly_section_feature_conditions(
            'project-test', 'section-parent'
        )
        self.assertTrue(bool(stale.iloc[0]['is_stale']))
        self.assertIn('removed choice', str(stale.iloc[0]['stale_reason']))

        # An unchanged stale row remains saveable, while a new stale row is rejected.
        store.save_assembly_section_feature_conditions(
            'project-test',
            'section-parent',
            stale[['id', 'feature_id', 'value']],
        )
        with self.assertRaisesRegex(ValueError, 'no longer an allowed choice'):
            self.save_condition('section-open', 'feature-brand', 'Acme')

        fail_open_matches = store.fishbone_visual_feature_matches(
            'project-test', [('feature-line', 'Commercial')]
        )
        self.assertEqual(
            fail_open_matches,
            {
                'use-parent-ruled', 'use-parent-open', 'use-open-ruled',
                'use-child-open',
            },
        )
        node_count = store.query(
            "SELECT COUNT(*) AS count FROM fishbone_nodes WHERE id='blocked-node'"
        )[0]['count']
        self.assertEqual(node_count, 1)

    def test_section_delete_discloses_and_applies_all_relationship_effects(self) -> None:
        self.save_condition('section-parent', 'feature-brand', 'Acme')
        self.save_condition('section-child', 'feature-line', 'Commercial')
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO yamazumi_areas
                   (id, project_id, scenario_id, section_id, name, updated_at)
                   VALUES ('area-child', 'project-test', 'scenario-test',
                           'section-child', 'Child area', ?)""",
                (timestamp,),
            )
            conn.execute(
                """INSERT INTO work_elements
                   (id, project_id, scenario_id, sequence, operation, updated_at)
                   VALUES ('work-1', 'project-test', 'scenario-test', 10, 'Install', ?)""",
                (timestamp,),
            )
            conn.execute(
                """INSERT INTO process_part_groups
                   (id, project_id, scenario_id, work_element_id, section_id,
                    name, updated_at)
                   VALUES ('group-1', 'project-test', 'scenario-test', 'work-1',
                           'section-child', 'Parts', ?)""",
                (timestamp,),
            )

        impact = store.assembly_section_delete_impact(
            'project-test', ['section-parent']
        )
        self.assertEqual(impact['affected_section_count'], 2)
        self.assertEqual(impact['descendant_section_count'], 1)
        self.assertEqual(impact['fishbone_use_count'], 3)
        self.assertEqual(impact['condition_count'], 2)
        self.assertEqual(impact['yamazumi_area_count'], 1)
        self.assertEqual(impact['process_link_count'], 1)

        deleted = store.delete_assembly_sections(
            'project-test', ['section-parent']
        )
        self.assertEqual(deleted['affected_section_count'], 2)
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM assembly_sections WHERE id IN ('section-parent', 'section-child')"
            )[0]['count'],
            0,
        )
        self.assertEqual(
            store.query(
                "SELECT COUNT(*) AS count FROM assembly_section_feature_conditions"
            )[0]['count'],
            0,
        )
        self.assertIsNone(
            store.query("SELECT section_id FROM yamazumi_areas WHERE id='area-child'")[0][
                'section_id'
            ]
        )
        self.assertIsNone(
            store.query("SELECT section_id FROM process_part_groups WHERE id='group-1'")[0][
                'section_id'
            ]
        )
        self.assertEqual(
            store.query("SELECT COUNT(*) AS count FROM fishbone_nodes WHERE id='blocked-node'")[0][
                'count'
            ],
            1,
        )

    def test_feature_delete_is_restricted_while_condition_exists(self) -> None:
        self.save_condition('section-parent', 'feature-brand', 'Acme')
        retained_features = store.complexity_features('project-test')
        retained_features = retained_features.loc[
            retained_features['id'].astype(str) != 'feature-brand'
        ]
        with self.assertRaisesRegex(ValueError, 'referenced by 1 Fishbone section'):
            store.update_complexity_features('project-test', retained_features)
        with self.assertRaises(sqlite3.IntegrityError):
            with store.connection() as conn:
                conn.execute(
                    "DELETE FROM complexity_features WHERE id='feature-brand'"
                )


if __name__ == '__main__':
    unittest.main()
