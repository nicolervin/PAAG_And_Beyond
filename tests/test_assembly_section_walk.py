from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from utils import store


class AssemblySectionWalkOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        connection_patcher = patch.object(store, "connection", self._connection)
        connection_patcher.start()
        self.addCleanup(connection_patcher.stop)
        self.addCleanup(self.conn.close)
        store.init_db()

        self.project_id = "walk-project"
        self.other_project_id = "walk-other-project"
        self.empty_project_id = "walk-empty-project"
        timestamp = store.now_iso()
        with store.connection() as conn:
            for project_id in (
                self.project_id, self.other_project_id, self.empty_project_id
            ):
                conn.execute(
                    """INSERT INTO projects
                       (id, name, revision, status, takt_time_s, created_at, updated_at)
                       VALUES (?, ?, 'A', 'Draft', 60, ?, ?)""",
                    (project_id, project_id, timestamp, timestamp),
                )

    @contextmanager
    def _connection(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def add_section(
        self,
        section_id: str,
        name: str,
        section_type: str,
        parent_id: str | None,
        sequence: int,
        *,
        project_id: str | None = None,
    ) -> None:
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.execute(
                """INSERT INTO assembly_sections
                   (id, project_id, name, section_type, parent_id, sequence,
                    description, active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, '', 1, ?, ?)""",
                (
                    section_id, project_id or self.project_id, name,
                    section_type, parent_id, sequence, timestamp, timestamp,
                ),
            )

    @staticmethod
    def previous_page_walk(sections: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
        """Frozen copy of the former app_pages/fishbone.py traversal."""
        def normalized_parent_id(value) -> str:
            if value is None or pd.isna(value):
                return ""
            return str(value).strip()

        records = {
            str(row["id"]): row.to_dict() for _, row in sections.iterrows()
        }
        children: dict[str, list[str]] = {}
        for section_id, row in records.items():
            parent_id = normalized_parent_id(row.get("parent_id"))
            children.setdefault(parent_id, []).append(section_id)
        for child_ids in children.values():
            child_ids.sort(
                key=lambda child_id: (
                    int(records[child_id]["sequence"]),
                    records[child_id]["name"],
                )
            )

        order: list[str] = []
        depth: dict[str, int] = {}

        def add_framework_branch(section_id: str, branch_depth: int) -> None:
            if section_id in depth:
                return
            depth[section_id] = branch_depth
            order.append(section_id)
            for child_id in children.get(section_id, []):
                add_framework_branch(child_id, branch_depth + 1)

        root_ids = [
            section_id
            for section_id, row in records.items()
            if not normalized_parent_id(row.get("parent_id"))
            or row["section_type"] == "Main spine"
        ]
        root_ids.sort(
            key=lambda section_id: (
                int(records[section_id]["sequence"]),
                records[section_id]["name"],
            )
        )
        for root_id in root_ids:
            add_framework_branch(root_id, 0)
        for section_id in records:
            add_framework_branch(section_id, 0)
        ordered = (
            sections.set_index(sections["id"].astype(str), drop=False)
            .loc[order]
            .reset_index(drop=True)
        )
        return ordered, depth

    def build_nested_fixture(self) -> None:
        self.add_section("main-b", "Main B", "Main spine", None, 20)
        self.add_section("main-a", "Main A", "Main spine", None, 10)
        self.add_section("child-a2", "Child A2", "Subassembly", "main-a", 20)
        self.add_section("child-a1", "Child A1", "Subassembly", "main-a", 10)
        self.add_section("grandchild", "Grandchild", "Subassembly", "child-a1", 5)

    def test_matches_previous_page_local_traversal_exactly(self) -> None:
        self.build_nested_fixture()
        flat = store.assembly_sections(self.project_id)
        expected_rows, expected_depth = self.previous_page_walk(flat)
        actual = store.assembly_section_walk_order(self.project_id)

        pd.testing.assert_frame_equal(
            actual.drop(columns=["depth"]), expected_rows
        )
        self.assertEqual(
            dict(zip(actual["id"].astype(str), actual["depth"].astype(int))),
            expected_depth,
        )

    def test_nested_subassemblies_are_inserted_at_their_parent(self) -> None:
        self.build_nested_fixture()
        walk = store.assembly_section_walk_order(self.project_id)
        self.assertEqual(
            walk["id"].astype(str).tolist(),
            ["main-a", "child-a1", "grandchild", "child-a2", "main-b"],
        )
        self.assertEqual(walk["depth"].astype(int).tolist(), [0, 1, 2, 1, 0])

    def test_orphaned_branch_uses_the_existing_fallback_pass(self) -> None:
        self.add_section(
            "external-parent", "External parent", "Main spine", None, 10,
            project_id=self.other_project_id,
        )
        self.add_section("main", "Main", "Main spine", None, 20)
        self.add_section(
            "orphan", "Orphan", "Subassembly", "external-parent", 5
        )
        self.add_section("orphan-child", "Orphan child", "Subassembly", "orphan", 10)

        walk = store.assembly_section_walk_order(self.project_id)
        self.assertEqual(
            walk["id"].astype(str).tolist(),
            ["main", "orphan", "orphan-child"],
        )
        self.assertEqual(walk["depth"].astype(int).tolist(), [0, 0, 1])

    def test_empty_and_single_section_projects(self) -> None:
        empty = store.assembly_section_walk_order(self.empty_project_id)
        self.assertTrue(empty.empty)
        self.assertIn("depth", empty.columns)

        self.add_section("only", "Only", "Main spine", None, 10)
        single = store.assembly_section_walk_order(self.project_id)
        self.assertEqual(single["id"].astype(str).tolist(), ["only"])
        self.assertEqual(single["depth"].astype(int).tolist(), [0])


if __name__ == "__main__":
    unittest.main()
