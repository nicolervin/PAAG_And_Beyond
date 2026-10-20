from __future__ import annotations

import unittest
from unittest.mock import patch

from utils.split_workspace import build_page_url


class SplitWorkspaceUrlTests(unittest.TestCase):
    def test_build_page_url_with_explicit_page_and_context(self) -> None:
        url = build_page_url(
            "process",
            project_id="proj-123",
            scenario_id="scen-456",
            query_params={"paag_tab": "PAAG slides"},
        )
        self.assertIn("process?", url)
        self.assertIn("page=process", url)
        self.assertIn("project_id=proj-123", url)
        self.assertIn("scenario_id=scen-456", url)
        self.assertIn("paag_tab=PAAG+slides", url)

    def test_build_page_url_from_session_state(self) -> None:
        session = {
            "project_id": "proj-999",
            "scenario_id": "scen-888",
            "current_url_path": "parts",
        }
        with patch("utils.split_workspace.st.session_state", session):
            url = build_page_url()
            self.assertIn("parts?", url)
            self.assertIn("page=parts", url)
            self.assertIn("project_id=proj-999", url)
            self.assertIn("scenario_id=scen-888", url)

    def test_build_page_url_omits_none_context(self) -> None:
        session = {
            "project_id": None,
            "scenario_id": None,
            "current_url_path": "",
        }
        with patch("utils.split_workspace.st.session_state", session):
            url = build_page_url("overview")
            self.assertEqual(url, "./overview?page=overview")
