from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_bridge import build_view_model


REPO = Path(__file__).resolve().parents[1]
TEMPLATE = Path(os.environ["SHORT_VIDEO_OPS_TEMPLATE"]) if os.environ.get("SHORT_VIDEO_OPS_TEMPLATE") else None


def hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


class AgentBridgeReadOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        if TEMPLATE is None:
            self.skipTest("set SHORT_VIDEO_OPS_TEMPLATE to an approved read-only template path")
        if not TEMPLATE.is_dir():
            self.fail("SHORT_VIDEO_OPS_TEMPLATE must point to templates/project-workspace")
        self.temp = tempfile.TemporaryDirectory(prefix="ice-agent-wallboard-")
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        shutil.copytree(TEMPLATE, self.workspace)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_template_read_is_read_only_and_missing_counts_are_not_zero(self) -> None:
        before = hashes(self.workspace)
        model = build_view_model(self.workspace, fixture=True)
        after = hashes(self.workspace)

        self.assertEqual(before, after)
        self.assertTrue(model["workspace"]["connected"])
        self.assertEqual(model["workspace"]["label"], "合成演示数据")
        self.assertTrue(all(item["value"] is None for item in model["dashboard"]["kpis"]))
        self.assertTrue(any(item["title"] == "运营总览资料尚未生成"
                            for item in model["dashboard"]["alerts"]))
        self.assertTrue(all("source" in item and "updated_at" in item
                            for item in model["dashboard"]["kpis"]))
        self.assertTrue(all("source" in item and "updated_at" in item
                            for item in model["dashboard"]["pipeline"]))

    def test_cli_writes_only_outside_workspace_and_preserves_explicit_zero(self) -> None:
        dashboard_path = self.workspace / "presentation" / "ops-dashboard.json"
        dashboard_path.parent.mkdir(parents=True, exist_ok=True)
        dashboard_path.write_text(json.dumps({
            "kpis": [{"id": "todo", "value": 0, "source": "test.fixture", "updated_at": "2026-10-26"}],
            "pipeline": [{"id": "topic", "value": 0, "state": "ready"}],
            "alerts": [],
            "recent": [],
        }), encoding="utf-8")
        before = hashes(self.workspace)
        output = self.base / "view-model.json"
        result = subprocess.run([
            str(Path(__import__("sys").executable)), str(REPO / "agent_bridge.py"),
            "--workspace", str(self.workspace), "--out", str(output), "--fixture",
        ], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, hashes(self.workspace))
        model = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(next(row["value"] for row in model["dashboard"]["kpis"] if row["id"] == "todo"), 0)
        self.assertTrue(model["dashboard"]["alerts_complete"])

        inside = self.workspace / "presentation" / "should-not-write.json"
        refused = subprocess.run([
            str(Path(__import__("sys").executable)), str(REPO / "agent_bridge.py"),
            "--workspace", str(self.workspace), "--out", str(inside),
        ], capture_output=True, text=True, check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertFalse(inside.exists())


if __name__ == "__main__":
    unittest.main()
