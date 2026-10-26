from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_bridge import _timestamp, build_view_model


REPO = Path(__file__).resolve().parents[1]
TEMPLATE = Path(os.environ["SHORT_VIDEO_OPS_TEMPLATE"]) if os.environ.get("SHORT_VIDEO_OPS_TEMPLATE") else None


class AgentTimestampTests(unittest.TestCase):
    def test_epoch_placeholder_dates_are_unknown_and_real_source_dates_are_preserved(self) -> None:
        self.assertIsNone(_timestamp(None, {"generated_at": "1970-01-01T00:00:00Z"}))
        self.assertIsNone(_timestamp(None, {"selection_date": "1900-01-01"}))
        self.assertIsNone(_timestamp(None, {"confirmed_at": "0001-01-01T00:00:00"}))
        self.assertEqual(_timestamp(None, {"generated_at": "2026-10-26T12:30:00Z"}),
                         "2026-10-26T12:30:00Z")


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

    def _write_current(self, key: str, value: dict) -> Path:
        manifest = json.loads((self.workspace / "project.manifest.json").read_text(encoding="utf-8"))
        path = self.workspace / manifest["current"][key]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_unconfirmed_account_only_returns_gaps_and_reads_workbench_runs(self) -> None:
        self._write_current("account_profile", {"account_id": "synthetic-account", "positioning": "not for display"})
        self._write_current("audience_profile", {"audience": "synthetic audience"})
        self._write_current("offer_profile", {"offer": "synthetic offer"})
        self._write_current("strategy_brief", {"status": "draft", "confirmed_by_user": False})
        self._write_current("account_snapshot", {"source_refs": []})
        self._write_current("post_metrics", {"posts": []})
        self._write_current("strategy_assessment", {
            "decision": "propose_strategy_adjustment",
            "conclusion": "this conclusion must stay hidden",
            "evidence_window": {"comparable_post_count": 0, "execution_variant_count": 0},
            "evidence": [{"evidence_id": "synthetic-evidence", "source_ref": "data/feedback/raw/post-metrics.json"}],
        })
        self._write_current("topic_discovery_policy", {
            "policy_id": "synthetic-policy", "version": "1",
            "strategy_assessment": {"minimum_adjustment_evidence": {
                "comparable_public_posts": 3, "execution_variants": 2,
                "requires_persistent_weak_target_response": True,
            }},
        })
        self._write_current("topic_selection", {"status": "ready", "selected": [{"topic_id": "synthetic-topic"}]})
        self._write_current("daily_plan", {"status": "blocked", "plans": [], "research_summary": {"missing_or_blocked": ["synthetic blocker"]}})
        self._write_current("reference_bank", {"references": [{"reference_id": "synthetic-reference"}]})
        self._write_current("pain_bank", {"pains": [{"pain_id": "synthetic-pain"}]})

        run_root = self.workspace / "runs" / "synthetic-copy-run"
        output = run_root / "outputs" / "copy-reference-match.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({
            "original_draft": "Synthetic saved draft.",
            "selected_references": [{"reference_id": "synthetic-reference", "title": "Synthetic ref",
                                     "score": 4.5, "match_reasons": ["fixture reason"]}],
        }), encoding="utf-8")
        (run_root / "run.manifest.json").write_text(json.dumps({
            "run_id": "synthetic-copy-run", "workflow_id": "copy-optimization-reference-match",
            "status": "completed", "generated_at": "2026-10-26T12:00:00Z",
            "outputs": ["runs/synthetic-copy-run/outputs/copy-reference-match.json"],
        }), encoding="utf-8")

        before = hashes(self.workspace)
        model = build_view_model(self.workspace, fixture=True)
        self.assertEqual(before, hashes(self.workspace))
        self.assertEqual(model["account"]["state"], "blocked")
        self.assertIsNone(model["account"]["assessment"]["conclusion"])
        self.assertNotIn("this conclusion must stay hidden", json.dumps(model, ensure_ascii=False))
        self.assertTrue(any(item["id"] == "strategy_confirmation" for item in model["account"]["blockers"]))
        self.assertEqual(model["account"]["strategy_adjustment_gate"]["minimum_comparable_public_posts"], 3)
        self.assertEqual(model["account"]["strategy_adjustment_gate"]["minimum_execution_variants"], 2)
        self.assertEqual(model["workbench"]["draft"]["text"], "Synthetic saved draft.")
        self.assertEqual(model["workbench"]["reference_matches"][0]["reference_id"], "synthetic-reference")
        materials = {item["id"]: item["value"] for item in model["workbench"]["materials"]}
        self.assertEqual(materials["references"], 1)
        self.assertEqual(materials["pain_points"], 1)
        self.assertEqual(model["history"]["runs"][0]["run_id"], "synthetic-copy-run")

    def test_confirmed_account_requires_versioned_evidence_gates_before_showing_assessment(self) -> None:
        confirmation = {"confirmed_by_user": True, "confirmed_at": "2026-10-26", "confirmation_quote": "confirmed"}
        for key, value in (
            ("account_profile", {"account_id": "synthetic-account", **confirmation}),
            ("audience_profile", {"audience": "synthetic audience", **confirmation}),
            ("offer_profile", {"offer": "synthetic offer", **confirmation}),
        ):
            self._write_current(key, value)
        self._write_current("strategy_brief", {
            "status": "confirmed", "confirmed_by_user": True, "decision_log_refs": ["decision-log.md#1"],
        })
        metrics_path = self._write_current("post_metrics", {"posts": [{"post_id": str(index)} for index in range(3)]})
        self._write_current("account_snapshot", {"source_refs": ["data/feedback/raw/post-metrics.json"]})
        self._write_current("strategy_assessment", {
            "decision": "propose_strategy_adjustment", "conclusion": "Synthetic evidence-backed assessment.",
            "persistent_weak_target_response": True,
            "evidence_window": {"public_post_count": 3, "comparable_post_count": 3, "execution_variant_count": 2},
            "evidence": [{"evidence_id": "synthetic-evidence", "source_ref": metrics_path.relative_to(self.workspace).as_posix()}],
        })
        self._write_current("topic_discovery_policy", {
            "policy_id": "synthetic-policy", "version": "2",
            "strategy_assessment": {"minimum_adjustment_evidence": {
                "comparable_public_posts": 3, "execution_variants": 2,
                "requires_persistent_weak_target_response": True,
            }},
        })

        before = hashes(self.workspace)
        model = build_view_model(self.workspace, fixture=True)
        self.assertEqual(before, hashes(self.workspace))
        self.assertEqual(model["account"]["state"], "ready")
        self.assertEqual(model["account"]["assessment"]["state"], "ready")
        self.assertEqual(model["account"]["assessment"]["conclusion"], "Synthetic evidence-backed assessment.")
        self.assertEqual(model["account"]["assessment"]["evidence"][0]["source_ref"], metrics_path.relative_to(self.workspace).as_posix())


if __name__ == "__main__":
    unittest.main()
