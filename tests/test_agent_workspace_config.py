from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import app
from agent_bridge import WORKSPACE_CONFIG_NAME


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


class AgentWorkspaceConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ice-agent-workspace-settings-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data_dir = self.base / "ice-data"
        self.data_dir.mkdir()
        self.workspace = self.base / "agent-workspace"
        (self.workspace / "presentation").mkdir(parents=True)
        (self.workspace / "project.manifest.json").write_text(
            json.dumps({"project_id": "synthetic-workspace", "operating_mode": "personal"}),
            encoding="utf-8")
        (self.workspace / "presentation" / "status.json").write_text(
            json.dumps({"status": "not_generated", "reason": "synthetic acceptance fixture"}),
            encoding="utf-8")
        self.override_workspace = self.base / "environment-workspace"
        self.override_workspace.mkdir()
        (self.override_workspace / "project.manifest.json").write_text(
            json.dumps({"project_id": "environment-override", "operating_mode": "personal"}),
            encoding="utf-8")
        (self.override_workspace / "presentation").mkdir()
        self.environment = patch.dict(os.environ, {"SHORT_VIDEO_OPS_WORKSPACE": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.start_server()
        self.addCleanup(self.stop_server)

    def start_server(self) -> None:
        self.server = app.create_server(port=0, data_dir=self.data_dir)
        port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:" + str(port)
        self.token = self.request("/api/state?mode=live")["token"]

    def stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def request(self, path: str, body: dict | None = None, *, authorized: bool = True) -> dict:
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers = {"Origin": self.base_url, "Content-Type": "application/json"}
            if authorized:
                headers["X-Radar-Token"] = self.token
        try:
            with urlopen(Request(self.base_url + path, data=data, headers=headers), timeout=5) as response:
                return json.loads(response.read())
        except HTTPError as exc:
            with exc:
                exc.payload = json.loads(exc.read())
            raise

    def post_config(self, body: dict, *, authorized: bool = True) -> dict:
        return self.request("/api/agent/workspace-config", body, authorized=authorized)

    def test_setting_persists_across_server_restart_and_workspace_stays_read_only(self) -> None:
        before = tree_hashes(self.workspace)
        saved = self.post_config({"workspace_path": str(self.workspace)})
        self.assertTrue(saved["configured"])
        config_path = self.data_dir / WORKSPACE_CONFIG_NAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["workspace_path"], str(self.workspace.resolve()))
        self.assertNotIn("api_key", config)
        model = self.request("/api/agent/view-model")
        self.assertTrue(model["workspace"]["connected"])
        self.assertEqual(model["workspace"]["id"], "synthetic-workspace")
        self.assertNotIn("api_key", json.dumps(model).lower())
        self.assertEqual(before, tree_hashes(self.workspace))

        self.stop_server()
        self.start_server()
        state = self.request("/api/agent/workspace-config")
        self.assertTrue(state["valid"])
        self.assertEqual(state["configured_path"], str(self.workspace.resolve()))
        restored = self.request("/api/agent/view-model")
        self.assertEqual(restored["workspace"]["id"], "synthetic-workspace")
        self.assertEqual(before, tree_hashes(self.workspace))

    def test_invalid_workspace_does_not_replace_a_valid_saved_path(self) -> None:
        self.post_config({"workspace_path": str(self.workspace)})
        invalid = self.base / "not-a-workspace"
        invalid.mkdir()
        with self.assertRaises(HTTPError) as error:
            self.post_config({"workspace_path": str(invalid)})
        self.assertEqual(error.exception.code, 400)
        self.assertIn("project.manifest.json", error.exception.payload["error"])
        state = self.request("/api/agent/workspace-config")
        self.assertEqual(state["configured_path"], str(self.workspace.resolve()))

    def test_only_absolute_existing_workspace_with_valid_manifest_is_saved(self) -> None:
        with self.assertRaises(HTTPError) as relative:
            self.post_config({"workspace_path": "."})
        self.assertEqual(relative.exception.code, 400)
        with self.assertRaises(HTTPError) as missing:
            self.post_config({"workspace_path": str(self.base / "missing")})
        self.assertEqual(missing.exception.code, 400)
        self.assertFalse((self.data_dir / WORKSPACE_CONFIG_NAME).exists())

    def test_environment_variable_overrides_saved_path_for_development(self) -> None:
        self.post_config({"workspace_path": str(self.workspace)})
        with patch.dict(os.environ, {"SHORT_VIDEO_OPS_WORKSPACE": str(self.override_workspace)}):
            state = self.request("/api/agent/workspace-config")
            model = self.request("/api/agent/view-model")
        self.assertTrue(state["environment_override"])
        self.assertEqual(state["configured_path"], str(self.workspace.resolve()))
        self.assertEqual(state["effective_path"], str(self.override_workspace.resolve()))
        self.assertEqual(model["workspace"]["id"], "environment-override")

    def test_clear_unbinds_path_without_deleting_workspace_and_requires_local_token(self) -> None:
        self.post_config({"workspace_path": str(self.workspace)})
        with self.assertRaises(HTTPError) as denied:
            self.post_config({"clear": True}, authorized=False)
        self.assertEqual(denied.exception.code, 403)
        self.post_config({"clear": True})
        self.assertFalse((self.data_dir / WORKSPACE_CONFIG_NAME).exists())
        self.assertTrue((self.workspace / "project.manifest.json").is_file())
        self.assertFalse(self.request("/api/agent/workspace-config")["valid"])


if __name__ == "__main__":
    unittest.main()
