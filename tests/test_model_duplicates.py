from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

from utils import store


class ModelDuplicateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = store.DATA_DIR / f"test_model_duplicates_{uuid4()}.db"
        self.database_patch = patch.object(store, "DB_PATH", self.database_path)
        self.database_patch.start()
        store.init_db()
        self.project_id = str(store.query("SELECT id FROM projects LIMIT 1")[0]["id"])
        with store.connection() as conn:
            conn.execute(
                "DELETE FROM manufacturing_assembly_feature_rules WHERE project_id=?",
                (self.project_id,),
            )
            conn.execute("DELETE FROM part_feature_rules WHERE project_id=?", (self.project_id,))
            conn.execute("DELETE FROM model_feature_values WHERE project_id=?", (self.project_id,))
            conn.execute("DELETE FROM complexity_features WHERE project_id=?", (self.project_id,))
            conn.execute("DELETE FROM project_models WHERE project_id=?", (self.project_id,))

        self.feature_one = str(uuid4())
        self.feature_two = str(uuid4())
        self.inactive_feature = str(uuid4())
        self.model_ids = {
            name: str(uuid4())
            for name in ("A", "B", "C_INACTIVE", "D", "E")
        }
        timestamp = store.now_iso()
        with store.connection() as conn:
            conn.executemany(
                """INSERT INTO complexity_features
                   (id, project_id, category, name, allowed_values, active, updated_at)
                   VALUES (?, ?, 'Product', ?, ?, ?, ?)""",
                [
                    (self.feature_one, self.project_id, "Feature one", json.dumps(["X", "Z"]), 1, timestamp),
                    (self.feature_two, self.project_id, "Feature two", json.dumps(["Y", "Q"]), 1, timestamp),
                    (self.inactive_feature, self.project_id, "Inactive feature", json.dumps(["Old"]), 0, timestamp),
                ],
            )
            conn.executemany(
                """INSERT INTO project_models
                   (id, project_id, model_number, display_name, source_payload, active, updated_at)
                   VALUES (?, ?, ?, ?, '{}', ?, ?)""",
                [
                    (self.model_ids["A"], self.project_id, "MODEL-A", "Alpha", 1, timestamp),
                    (self.model_ids["B"], self.project_id, "MODEL-B", "Bravo", 1, timestamp),
                    (self.model_ids["C_INACTIVE"], self.project_id, "MODEL-C", "Charlie", 0, timestamp),
                    (self.model_ids["D"], self.project_id, "MODEL-D", "Delta", 1, timestamp),
                    (self.model_ids["E"], self.project_id, "MODEL-E", "Echo", 1, timestamp),
                ],
            )

    def tearDown(self) -> None:
        self.database_patch.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_active_pairs_use_only_mutually_assigned_active_features(self) -> None:
        edited = pd.DataFrame(
            [
                {"model_id": self.model_ids["A"], self.feature_one: "X", self.feature_two: None},
                {"model_id": self.model_ids["B"], self.feature_one: "X", self.feature_two: "Y"},
                {"model_id": self.model_ids["C_INACTIVE"], self.feature_one: "X", self.feature_two: "Y"},
                {"model_id": self.model_ids["D"], self.feature_one: None, self.feature_two: "Y"},
                {"model_id": self.model_ids["E"], self.feature_one: "Z", self.feature_two: None},
            ]
        )

        conflicts = store.potential_duplicate_models(self.project_id, edited)

        pairs = {
            frozenset((row["left_official_model_number"], row["right_official_model_number"]))
            for row in conflicts
        }
        self.assertEqual(
            pairs,
            {
                frozenset(("MODEL-A", "MODEL-B")),
                frozenset(("MODEL-B", "MODEL-D")),
            },
        )
        self.assertNotIn("MODEL-C", {number for pair in pairs for number in pair})

    def test_zero_mutual_features_and_one_mismatch_are_not_duplicates(self) -> None:
        edited = pd.DataFrame(
            [
                {"model_id": self.model_ids["A"], self.feature_one: "X", self.feature_two: None},
                {"model_id": self.model_ids["D"], self.feature_one: None, self.feature_two: "Y"},
                {"model_id": self.model_ids["E"], self.feature_one: "Z", self.feature_two: "Q"},
            ]
        )

        self.assertEqual(store.potential_duplicate_models(self.project_id, edited), [])

    def test_invalid_active_feature_value_is_rejected_before_warning(self) -> None:
        edited = pd.DataFrame(
            [{"model_id": self.model_ids["A"], self.feature_one: "Not allowed"}]
        )
        with self.assertRaisesRegex(ValueError, "Feature definitions"):
            store.potential_duplicate_models(self.project_id, edited)


if __name__ == "__main__":
    unittest.main()
