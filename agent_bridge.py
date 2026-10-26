"""Read-only adapter from a Short Video Ops workspace to the ICE UI view model."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_JSON_BYTES = 5 * 1024 * 1024
KPI_SPECS = (
    ("todo", "今日待办"),
    ("in_progress", "内容进行中"),
    ("review", "待复盘"),
    ("blocked", "异常 / 阻塞"),
)
PIPELINE_SPECS = (
    ("topic", "选题", "work/topics/selections/daily.json", "selected"),
    ("research", "研究", "data/benchmarks/current/reference-bank.json", "references"),
    ("draft", "成稿", "work/plans/daily.json", "plans"),
    ("published", "发布", "data/feedback/raw/published-posts.json", "posts"),
    ("reviewed", "复盘", "data/feedback/current/learning.json", "entries"),
)


def empty_view_model(state: str = "not_connected", message: str = "尚未配置本地运营资料") -> dict[str, Any]:
    """Return a truthful empty contract; absent data is always None, never zero."""
    return {
        "workspace": {
            "id": None,
            "mode": None,
            "connected": False,
            "label": "未连接",
            "state": state,
            "message": message,
        },
        "dashboard": {
            "kpis": [
                {"id": key, "label": label, "value": None, "source": None,
                 "updated_at": None, "state": "not_connected"}
                for key, label in KPI_SPECS
            ],
            "pipeline": [
                {"id": key, "label": label, "value": None, "source": None,
                 "updated_at": None, "state": "not_connected", "href": None}
                for key, label, _path, _key in PIPELINE_SPECS
            ],
            "alerts": [],
            "recent": [],
            "freshness": {"state": state, "updated_at": None, "sources": []},
        },
        "workbench": {"draft": None, "template": None, "reference_matches": [], "last_run": None},
        "video": {"source": None, "transcript": None, "analysis": None, "shots": [], "prompts": []},
        "history": {"runs": []},
        "meta": {"generated_at": _now(), "refresh_interval_seconds": 60},
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("workspace path escapes the selected root")
    return candidate


def _read_json(root: Path, relative: str, errors: list[str]) -> tuple[Any, Path | None]:
    try:
        path = _inside(root, relative)
        if not path.is_file():
            return None, path
        if path.stat().st_size > MAX_JSON_BYTES:
            errors.append(relative + ": file exceeds read limit")
            return None, path
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        return value, path
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        errors.append(relative + ": " + type(error).__name__)
        return None, None


def _timestamp(path: Path | None, value: Any = None) -> str | None:
    if isinstance(value, dict):
        for key in ("updated_at", "updatedAt", "generated_at", "generatedAt", "as_of", "selection_date", "date"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    except OSError:
        return None


def _list_value(data: Any, key: str) -> list[Any] | None:
    if not isinstance(data, dict):
        return None
    value = data.get(key)
    return value if isinstance(value, list) else None


def _direct_kpis(data: Any, path: Path | None) -> list[dict[str, Any]]:
    raw: Any = data.get("kpis") if isinstance(data, dict) else None
    if isinstance(data, dict) and not isinstance(raw, list):
        dashboard = data.get("dashboard")
        raw = dashboard.get("kpis") if isinstance(dashboard, dict) else None
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                key = str(item.get("id") or item.get("key") or "")
                if key:
                    by_id[key] = item
    source = "presentation/ops-dashboard.json" if path else None
    updated = _timestamp(path, data)
    result = []
    for key, label in KPI_SPECS:
        item = by_id.get(key)
        value = item.get("value") if item else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            value = None
        result.append({
            "id": key,
            "label": label,
            "value": value,
            "source": item.get("source") if item and item.get("source") else source,
            "updated_at": item.get("updated_at") if item and item.get("updated_at") else updated,
            "state": "ready" if value is not None else "not_connected",
        })
    return result


def _pipeline(selection: Any, selection_path: Path | None,
              reference_bank: Any, reference_path: Path | None,
              daily_plan: Any, plan_path: Path | None,
              published: Any, published_path: Path | None,
              learning: Any, learning_path: Path | None,
              canonical: Any) -> list[dict[str, Any]]:
    raw = canonical.get("pipeline") if isinstance(canonical, dict) else None
    direct = {str(item.get("id") or item.get("key") or ""): item
              for item in raw if isinstance(item, dict)} if isinstance(raw, list) else {}
    definitions = (
        ("topic", "选题", selection, selection_path, "work/topics/selections/daily.json", "selected"),
        ("research", "研究", reference_bank, reference_path, "data/benchmarks/current/reference-bank.json", "references"),
        ("draft", "成稿", daily_plan, plan_path, "work/plans/daily.json", "plans"),
        ("published", "发布", published, published_path, "data/feedback/raw/published-posts.json", "posts"),
        ("reviewed", "复盘", learning, learning_path, "data/feedback/current/learning.json", "entries"),
    )
    hrefs = {"topic": "/", "research": "/research", "draft": "/draft",
             "published": "/feedback", "reviewed": "/feedback"}
    result = []
    for key, label, source_data, source_path, source_name, list_key in definitions:
        item = direct.get(key)
        if item:
            raw_value = item.get("value", item.get("count"))
            value = raw_value if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool) and math.isfinite(raw_value) else None
            source = item.get("source") or ("presentation/ops-dashboard.json" if source_path else None)
            updated = item.get("updated_at") or _timestamp(source_path, source_data)
            state = item.get("state") or ("ready" if value is not None else "not_connected")
        else:
            rows = _list_value(source_data, list_key)
            status = source_data.get("status") if isinstance(source_data, dict) else None
            if rows:
                value, state = len(rows), "ready"
            elif rows is not None and str(status).lower() in ("ready", "complete", "completed", "published"):
                value, state = 0, "ready"
            else:
                value = None
                state = "blocked" if str(status).lower() in ("blocked", "failed", "not_generated") else "not_connected"
            source = source_name if source_path else None
            updated = _timestamp(source_path, source_data)
        result.append({"id": key, "label": label, "value": value,
                       "source": source, "updated_at": updated, "state": state,
                       "href": hrefs[key]})
    return result


def _run_history(root: Path, errors: list[str]) -> list[dict[str, Any]]:
    try:
        runs_path = _inside(root, "runs")
    except ValueError:
        errors.append("runs/: path escapes the selected root")
        return []
    if not runs_path.is_dir():
        return []
    manifests = sorted(runs_path.glob("*/run.manifest.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:10]
    result = []
    for path in manifests:
        relative = path.relative_to(root).as_posix()
        run, safe_path = _read_json(root, relative, errors)
        if not isinstance(run, dict):
            continue
        run_id = run.get("run_id") or path.parent.name
        workflow = run.get("workflow_id") or ""
        result.append({
            "run_id": str(run_id),
            "workflow_id": str(workflow),
            "status": str(run.get("status") or "已记录"),
            "updated_at": _timestamp(safe_path, run),
            "source": relative,
            "href": _safe_run_href(workflow),
        })
    return result


def _safe_run_href(workflow: str) -> str | None:
    routes = {
        "topic-candidates": "/",
        "copy-optimization-reference-match": "/draft",
        "reference-strategy-deconstruction": "/research",
        "daily-ops-loop": "/dashboard",
        "feedback-learning": "/feedback",
    }
    return routes.get(workflow)


def _alerts(status: Any, canonical: Any, freshness: Any, status_path: Path | None) -> list[dict[str, Any]]:
    raw: Any = canonical.get("alerts") if isinstance(canonical, dict) else None
    if isinstance(raw, list):
        result = []
        for item in raw[:5]:
            if isinstance(item, dict):
                result.append({
                    "title": str(item.get("title") or item.get("label") or "状态提醒"),
                    "detail": str(item.get("detail") or item.get("message") or ""),
                    "state": str(item.get("state") or item.get("status") or "needs_attention"),
                    "source": item.get("source") or "presentation/ops-dashboard.json",
                    "updated_at": item.get("updated_at") or _timestamp(status_path, status),
                    "href": None,
                })
        return result
    if isinstance(status, dict) and status.get("status") in ("not_generated", "blocked", "failed"):
        reason = status.get("reason") or status.get("next_action")
        if reason == "No ready plan has passed the finalizer.":
            reason = "尚无通过审核、可用于运营总览的计划。"
        return [{
            "title": "运营总览资料尚未生成",
            "detail": str(reason or "请先完成每日运营流程。"),
            "state": "not_connected",
            "source": "presentation/status.json",
            "updated_at": _timestamp(status_path, status),
            "href": "/dashboard",
        }]
    sources = freshness.get("sources") if isinstance(freshness, dict) else None
    if isinstance(sources, list):
        return [dict(item, href=None) for item in sources if item.get("state") in ("missing", "stale")][:5]
    return []


def _recent(canonical: Any, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = canonical.get("recent") if isinstance(canonical, dict) else None
    if not isinstance(raw, list):
        return runs[:8]
    result = []
    for item in raw[:10]:
        if isinstance(item, dict):
            result.append({
                "time": str(item.get("time") or item.get("updated_at") or ""),
                "title": str(item.get("title") or item.get("label") or "运营记录"),
                "status": str(item.get("status") or "已记录"),
                "source": str(item.get("source") or "presentation/ops-dashboard.json"),
                "href": _safe_run_href(str(item.get("workflow_id") or item.get("kind") or "")),
                "updated_at": item.get("updated_at") or None,
            })
    return result


def build_view_model(workspace: Path, fixture: bool = False) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    if not root.is_dir():
        return empty_view_model("not_connected", "本地运营资料不可用")
    errors: list[str] = []
    manifest, manifest_path = _read_json(root, "project.manifest.json", errors)
    if not isinstance(manifest, dict):
        return empty_view_model("not_connected", "本地运营资料尚未完成初始化")
    status, status_path = _read_json(root, "presentation/status.json", errors)
    canonical, canonical_path = _read_json(root, "presentation/ops-dashboard.json", errors)
    selection, selection_path = _read_json(root, "work/topics/selections/daily.json", errors)
    reference_bank, reference_path = _read_json(root, "data/benchmarks/current/reference-bank.json", errors)
    daily_plan, plan_path = _read_json(root, "work/plans/daily.json", errors)
    published, published_path = _read_json(root, "data/feedback/raw/published-posts.json", errors)
    learning, learning_path = _read_json(root, "data/feedback/current/learning.json", errors)
    history = _run_history(root, errors)
    source_status = []
    if canonical_path and isinstance(canonical, dict):
        meta = canonical.get("meta") or {}
        raw = meta.get("sourceStatus") or meta.get("source_status") or {}
        if isinstance(raw, dict):
            for key, item in list(raw.items())[:20]:
                if isinstance(item, dict):
                    source_status.append({
                        "id": str(key), "label": str(item.get("label") or key),
                        "state": str(item.get("state") or "unknown"),
                        "source": str(item.get("path") or "presentation/ops-dashboard.json"),
                        "updated_at": item.get("updatedAt") or item.get("updated_at"),
                    })
    freshness = {
        "state": "ready" if canonical_path and isinstance(canonical, dict) else "incomplete",
        "updated_at": _timestamp(canonical_path, canonical),
        "sources": source_status,
        "errors": errors[:10],
    }
    kpis = _direct_kpis(canonical, canonical_path)
    pipeline = _pipeline(selection, selection_path, reference_bank, reference_path,
                         daily_plan, plan_path, published, published_path,
                         learning, learning_path, canonical)
    recent = _recent(canonical, history)
    return {
        "workspace": {
            "id": manifest.get("project_id") or None,
            "mode": "template" if fixture else str(manifest.get("operating_mode") or "personal"),
            "connected": True,
            "label": "合成演示数据" if fixture else "本地运营资料",
            "state": "ready" if isinstance(canonical, dict) else "incomplete",
            "message": None if isinstance(canonical, dict) else "运营指标尚未生成；缺少的数据会标记为“待接入”。",
        },
        "dashboard": {
            "kpis": kpis,
            "pipeline": pipeline,
            "alerts": _alerts(status, canonical, freshness, status_path),
            "alerts_complete": isinstance(canonical, dict) and isinstance(canonical.get("alerts"), list),
            "recent": recent,
            "freshness": freshness,
        },
        "workbench": {"draft": None, "template": None, "reference_matches": [],
                       "last_run": history[0] if history else None},
        "video": {"source": None, "transcript": None, "analysis": None, "shots": [], "prompts": []},
        "history": {"runs": history},
        "meta": {"generated_at": _now(), "refresh_interval_seconds": 60},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fixture", action="store_true", help="Mark this output as synthetic fixture data.")
    args = parser.parse_args()
    root = args.workspace.expanduser().resolve()
    output = args.out.expanduser().resolve()
    if output.is_relative_to(root):
        raise SystemExit("refusing to write the view model inside the workspace")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(build_view_model(root, fixture=args.fixture), ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    temporary.replace(output)


if __name__ == "__main__":
    main()
