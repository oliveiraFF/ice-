"""Read-only adapter from a Short Video Ops workspace to the ICE UI view model."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_JSON_BYTES = 5 * 1024 * 1024
WORKSPACE_CONFIG_NAME = "agent-workspace.json"
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
            "timezone": None,
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
        "workbench": {"state": state, "draft": None, "template": None, "reference_matches": [],
                       "last_run": None, "plan": {"status": "not_connected", "count": None,
                       "blockers": [], "source": None, "updated_at": None}, "materials": []},
        "account": {
            "state": state,
            "profiles": [],
            "strategy": {"state": "not_connected", "status": None, "confirmed_by_user": False,
                         "source": None, "updated_at": None},
            "samples": [],
            "strategy_adjustment_gate": None,
            "assessment": {"state": "blocked", "decision": None, "conclusion": None,
                            "evidence": [], "source": None, "updated_at": None},
            "blockers": [{"id": "workspace", "message": message, "required": "选择并确认正确的 Agent workspace 目录。",
                          "current": None, "minimum": None, "source": None}],
        },
        "video": {"source": None, "transcript": None, "analysis": None, "shots": [], "prompts": []},
        "history": {"runs": []},
        "meta": {"generated_at": _now(), "refresh_interval_seconds": 60},
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def workspace_config_file(data_dir: Path) -> Path:
    return Path(data_dir).expanduser().resolve() / WORKSPACE_CONFIG_NAME


def read_workspace_config(data_dir: Path) -> tuple[str | None, str | None]:
    path = workspace_config_file(data_dir)
    if not path.is_file():
        return None, None
    try:
        if path.stat().st_size > 32 * 1024:
            return None, "本机 Agent workspace 配置文件过大"
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        raw = value.get("workspace_path") if isinstance(value, dict) else None
        if not isinstance(raw, str) or not raw.strip():
            return None, "本机 Agent workspace 配置格式无效"
        return raw.strip(), None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "无法读取本机 Agent workspace 配置"


def validate_workspace(workspace: str | Path) -> Path:
    if not isinstance(workspace, (str, Path)) or not str(workspace).strip():
        raise ValueError("请选择 Agent workspace 目录")
    candidate = Path(workspace).expanduser()
    if not candidate.is_absolute():
        raise ValueError("请选择绝对路径的 Agent workspace 目录")
    try:
        root = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ValueError("所选目录不存在或无法访问") from None
    if not root.is_dir():
        raise ValueError("所选路径不是目录")
    errors: list[str] = []
    manifest, _ = _read_json(root, "project.manifest.json", errors)
    if not isinstance(manifest, dict):
        raise ValueError("该目录没有有效的 project.manifest.json，不是可识别的 Agent workspace")
    return root


def save_workspace_config(data_dir: Path, workspace: str | Path) -> Path:
    root = validate_workspace(workspace)
    directory = Path(data_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / WORKSPACE_CONFIG_NAME
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=str(directory), prefix=".agent-workspace-",
                suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"workspace_path": str(root), "updated_at": _now()}, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(destination))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return root


def clear_workspace_config(data_dir: Path) -> None:
    try:
        workspace_config_file(data_dir).unlink()
    except FileNotFoundError:
        pass


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


def _manifest_pointer(manifest: Any, section: str, key: str) -> str | None:
    if not isinstance(manifest, dict):
        return None
    container = manifest.get(section)
    value = container.get(key) if isinstance(container, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _read_manifest_json(root: Path, manifest: Any, section: str, key: str,
                        errors: list[str]) -> tuple[Any, Path | None, str | None]:
    relative = _manifest_pointer(manifest, section, key)
    if relative is None:
        return None, None, None
    data, path = _read_json(root, relative, errors)
    source = path.relative_to(root).as_posix() if path is not None else None
    return data, path, source


def _source_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized[:10] in {"0001-01-01", "1900-01-01", "1970-01-01"}:
        return None
    return normalized


def _timestamp(path: Path | None, value: Any = None) -> str | None:
    if isinstance(value, dict):
        date_keys = ("updated_at", "updatedAt", "generated_at", "generatedAt", "as_of", "asOf",
                     "selection_date", "run_date", "evidenceDate", "sourceDate", "confirmed_at",
                     "confirmedAt", "published_at", "posted_at", "date")
        containers = [value]
        containers.extend(value.get(key) for key in ("meta", "period", "evidence_window")
                          if isinstance(value.get(key), dict))
        for container in containers:
            for key in date_keys:
                raw = container.get(key)
                normalized = _source_timestamp(raw)
                if normalized:
                    return normalized
        period = value.get("period")
        if isinstance(period, dict):
            end = period.get("end") or period.get("to")
            normalized = _source_timestamp(end)
            if normalized:
                return normalized
    # File modification time is not business freshness. Missing source dates stay unknown.
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
            "updated_at": (_source_timestamp(item.get("updated_at")) or updated) if item else updated,
            "state": "ready" if value is not None else "not_connected",
        })
    return result


def _pipeline(root: Path, selection: Any, selection_path: Path | None,
              reference_bank: Any, reference_path: Path | None,
              daily_plan: Any, plan_path: Path | None,
              published: Any, published_path: Path | None,
              learning: Any, learning_path: Path | None,
              canonical: Any) -> list[dict[str, Any]]:
    raw = canonical.get("pipeline") if isinstance(canonical, dict) else None
    direct = {str(item.get("id") or item.get("key") or ""): item
              for item in raw if isinstance(item, dict)} if isinstance(raw, list) else {}
    definitions = (
        ("topic", "选题", selection, selection_path, "selected"),
        ("research", "研究", reference_bank, reference_path, "references"),
        ("draft", "成稿", daily_plan, plan_path, "plans"),
        ("published", "发布", published, published_path, "posted"),
        ("reviewed", "复盘", learning, learning_path, "entries"),
    )
    hrefs = {"topic": "/", "research": "/research", "draft": "/draft",
             "published": "/feedback", "reviewed": "/feedback"}
    result = []
    for key, label, source_data, source_path, list_key in definitions:
        item = direct.get(key)
        if item:
            raw_value = item.get("value", item.get("count"))
            value = raw_value if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool) and math.isfinite(raw_value) else None
            source = item.get("source") or ("presentation/ops-dashboard.json" if source_path else None)
            updated = _source_timestamp(item.get("updated_at")) or _timestamp(source_path, source_data)
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
            source = source_path.relative_to(root).as_posix() if source_path else None
            updated = _timestamp(source_path, source_data)
        result.append({"id": key, "label": label, "value": value,
                       "source": source, "updated_at": updated, "state": state,
                       "href": hrefs[key]})
    return result


def _time_sort_value(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _run_records(root: Path, errors: list[str]) -> list[dict[str, Any]]:
    try:
        runs_path = _inside(root, "runs")
    except ValueError:
        errors.append("runs/: path escapes the selected root")
        return []
    if not runs_path.is_dir():
        return []
    records = []
    for path in runs_path.glob("*/run.manifest.json"):
        relative = path.relative_to(root).as_posix()
        run, safe_path = _read_json(root, relative, errors)
        if not isinstance(run, dict):
            continue
        run_id = run.get("run_id") or path.parent.name
        workflow = run.get("workflow_id") or ""
        records.append({
            "manifest": run,
            "run_id": str(run_id),
            "workflow_id": str(workflow),
            "status": str(run.get("status") or "已记录"),
            "updated_at": _timestamp(safe_path, run),
            "source": relative,
            "href": _safe_run_href(str(workflow)),
        })
    records.sort(key=lambda item: _time_sort_value(item.get("updated_at")), reverse=True)
    return records


def _run_history(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: item[key] for key in ("run_id", "workflow_id", "status", "updated_at", "source", "href")}
            for item in records[:10]]


def _latest_copy_optimization(root: Path, records: list[dict[str, Any]], errors: list[str]) -> dict[str, Any] | None:
    for record in records:
        if record.get("workflow_id") != "copy-optimization-reference-match":
            continue
        outputs = record["manifest"].get("outputs")
        if not isinstance(outputs, list):
            continue
        for output in outputs:
            if not isinstance(output, str) or Path(output).name != "copy-reference-match.json":
                continue
            payload, path = _read_json(root, output, errors)
            if not isinstance(payload, dict) or path is None:
                continue
            source = path.relative_to(root).as_posix()
            updated_at = _timestamp(path, payload) or record.get("updated_at")
            draft = payload.get("original_draft")
            if not isinstance(draft, str):
                draft = None
            refs = payload.get("selected_references")
            normalized_refs = []
            if isinstance(refs, list):
                for item in refs[:10]:
                    if not isinstance(item, dict):
                        continue
                    score = item.get("score")
                    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                        score = None
                    normalized_refs.append({
                        "reference_id": str(item.get("reference_id") or ""),
                        "title": str(item.get("title") or ""),
                        "creator": str(item.get("creator") or ""),
                        "platform": str(item.get("platform") or ""),
                        "score": score,
                        "match_reasons": [str(value) for value in item.get("match_reasons", [])[:5]
                                          if isinstance(value, str)] if isinstance(item.get("match_reasons"), list) else [],
                        "source": source,
                        "updated_at": updated_at,
                    })
            return {
                "draft": {"text": draft, "source": source, "updated_at": updated_at} if draft else None,
                "reference_matches": normalized_refs,
                "last_run": {key: record[key] for key in
                             ("run_id", "workflow_id", "status", "updated_at", "source", "href")},
            }
    return None


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
                    "updated_at": _source_timestamp(item.get("updated_at")) or _timestamp(status_path, status),
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
            timestamp = _source_timestamp(item.get("time")) or _source_timestamp(item.get("updated_at"))
            result.append({
                "time": timestamp or "",
                "title": str(item.get("title") or item.get("label") or "运营记录"),
                "status": str(item.get("status") or "已记录"),
                "source": str(item.get("source") or "presentation/ops-dashboard.json"),
                "href": _safe_run_href(str(item.get("workflow_id") or item.get("kind") or "")),
                "updated_at": _source_timestamp(item.get("updated_at")),
            })
    return result


def _explicit_user_confirmation(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    confirmation = value.get("confirmation")
    if not isinstance(confirmation, dict):
        confirmation = {}
    confirmed = (value.get("confirmed_by_user") is True or
                 confirmation.get("confirmed_by_user") is True or
                 str(value.get("confirmation_status") or confirmation.get("status") or "").lower()
                 in ("confirmed", "user_confirmed"))
    timestamp = value.get("confirmed_at") or value.get("confirmation_date") or confirmation.get("confirmed_at")
    quote = value.get("confirmation_quote") or confirmation.get("confirmation_quote")
    return bool(confirmed and _source_timestamp(timestamp) and
                isinstance(quote, str) and quote.strip())


def _profile_display_items(profile_id: str, value: Any, source: str | None,
                           updated_at: str | None) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    fields = {
        "account": (("account_id", "账号标识"), ("platform", "平台"), ("industry", "领域"),
                    ("positioning", "账号定位")),
        "audience": (("audience", "目标受众"), ("needs", "受众需求"),
                     ("primary_audience", "核心受众"), ("audience_segments", "受众分组")),
        "offer": (("offer", "产品/服务"), ("value_proposition", "价值承诺"),
                  ("conversion_path", "承接方式"), ("business_goal", "业务目标")),
    }
    result = []
    for key, label in fields.get(profile_id, ()):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            display = item.strip()
        elif isinstance(item, list):
            values = [entry.strip() for entry in item if isinstance(entry, str) and entry.strip()]
            display = "、".join(values[:8]) if values else ""
        else:
            display = ""
        if display:
            result.append({"label": label, "value": display, "source": source, "updated_at": updated_at})
    return result


def _account_readout(root: Path, manifest: Any, errors: list[str]) -> dict[str, Any]:
    profile_specs = (
        ("account", "账号画像", "account_profile"),
        ("audience", "受众画像", "audience_profile"),
        ("offer", "产品与承接", "offer_profile"),
    )
    profiles = []
    for profile_id, label, pointer in profile_specs:
        data, path, source = _read_manifest_json(root, manifest, "current", pointer, errors)
        confirmed = _explicit_user_confirmation(data)
        profiles.append({
            "id": profile_id,
            "label": label,
            "state": "confirmed" if confirmed else ("needs_confirmation" if isinstance(data, dict) else "missing"),
            "items": _profile_display_items(profile_id, data, source, _timestamp(path, data)) if confirmed else [],
            "source": source,
            "updated_at": _timestamp(path, data),
        })
    profile_confirmed = bool(profiles) and all(item["state"] == "confirmed" for item in profiles)

    strategy, strategy_path, strategy_source = _read_manifest_json(
        root, manifest, "current", "strategy_brief", errors)
    strategy_confirmation_evidence = (strategy.get("decision_log_refs") if isinstance(strategy, dict) else None)
    strategy_confirmation_evidence = strategy_confirmation_evidence if isinstance(strategy_confirmation_evidence, list) else []
    strategy_confirmation_time = strategy.get("confirmed_at") if isinstance(strategy, dict) else None
    strategy_confirmation_quote = strategy.get("confirmation_quote") if isinstance(strategy, dict) else None
    strategy_has_provenance = (any(isinstance(item, str) and item.strip() for item in strategy_confirmation_evidence) or
                               (_source_timestamp(strategy_confirmation_time) and
                                isinstance(strategy_confirmation_quote, str) and strategy_confirmation_quote.strip()))
    strategy_confirmed = (isinstance(strategy, dict) and strategy.get("confirmed_by_user") is True and
                          str(strategy.get("status") or "").lower() in ("confirmed", "user_confirmed") and
                          strategy_has_provenance)
    strategy_state = ("confirmed" if strategy_confirmed else
                      "needs_confirmation" if isinstance(strategy, dict) else "missing")
    strategy_items = []
    if strategy_confirmed:
        for key, label in (("stage_goal", "阶段目标"), ("primary_strategy", "主策略"),
                           ("conversion_path", "转化路径")):
            value = strategy.get(key)
            if isinstance(value, str) and value.strip():
                strategy_items.append({"label": label, "value": value.strip(),
                                       "source": strategy_source, "updated_at": _timestamp(strategy_path, strategy)})
        pillars = strategy.get("content_pillars")
        if isinstance(pillars, list):
            values = [item.strip() for item in pillars if isinstance(item, str) and item.strip()]
            if values:
                strategy_items.append({"label": "内容支柱", "value": "、".join(values[:8]),
                                       "source": strategy_source, "updated_at": _timestamp(strategy_path, strategy)})

    snapshot, snapshot_path, snapshot_source = _read_manifest_json(
        root, manifest, "current", "account_snapshot", errors)
    post_metrics, metrics_path, metrics_source = _read_manifest_json(
        root, manifest, "current", "post_metrics", errors)
    assessment, assessment_path, assessment_source = _read_manifest_json(
        root, manifest, "current", "strategy_assessment", errors)
    policy, policy_path, policy_source = _read_manifest_json(
        root, manifest, "current", "topic_discovery_policy", errors)

    posts = _list_value(post_metrics, "posts")
    snapshot_refs = _list_value(snapshot, "source_refs")
    evidence_window = assessment.get("evidence_window") if isinstance(assessment, dict) else None
    evidence_window = evidence_window if isinstance(evidence_window, dict) else {}
    evidence = assessment.get("evidence") if isinstance(assessment, dict) else None
    evidence = evidence if isinstance(evidence, list) else []
    adjustment_policy = policy.get("strategy_assessment") if isinstance(policy, dict) else None
    adjustment_policy = adjustment_policy if isinstance(adjustment_policy, dict) else {}
    minimums = adjustment_policy.get("minimum_adjustment_evidence")
    minimums = minimums if isinstance(minimums, dict) else {}
    comparable_minimum = minimums.get("comparable_public_posts")
    variants_minimum = minimums.get("execution_variants")

    sample_counts = [
        {"id": "published_posts", "label": "已登记发布作品", "value": len(posts) if posts is not None else None,
         "source": metrics_source, "updated_at": _timestamp(metrics_path, post_metrics)},
        {"id": "snapshot_source_refs", "label": "账号快照来源引用", "value": len(snapshot_refs) if snapshot_refs is not None else None,
         "source": snapshot_source, "updated_at": _timestamp(snapshot_path, snapshot)},
        {"id": "comparable_public_posts", "label": "可比公开作品", "value": evidence_window.get("comparable_post_count"),
         "source": assessment_source, "updated_at": _timestamp(assessment_path, assessment)},
        {"id": "execution_variants", "label": "执行版本数", "value": evidence_window.get("execution_variant_count"),
         "source": assessment_source, "updated_at": _timestamp(assessment_path, assessment)},
    ]
    for item in sample_counts:
        value = item["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            item["value"] = None

    blockers = []
    if not profile_confirmed:
        blockers.append({
            "id": "profile_confirmation",
            "message": "账号、受众或产品画像缺少可追溯的人工确认记录。",
            "required": "在 Agent workspace 中确认画像，并保存确认时间与确认来源。",
            "current": None,
            "minimum": None,
            "source": next((item["source"] for item in profiles if item["state"] != "confirmed"), None),
        })
    if not strategy_confirmed:
        blockers.append({
            "id": "strategy_confirmation",
            "message": "当前策略尚未标记为用户确认。",
            "required": "确认账号策略后再读取下游诊断和选题结论。",
            "current": None,
            "minimum": None,
            "source": strategy_source,
        })
    if not posts:
        blockers.append({
            "id": "published_metrics",
            "message": "没有可用于表现分析的已登记作品指标。",
            "required": "补充真实作品的作品 ID、平台、发布日期、指标值和来源引用。",
            "current": len(posts) if posts is not None else None,
            "minimum": None,
            "source": metrics_source,
        })
    if not snapshot_refs:
        blockers.append({
            "id": "snapshot_evidence",
            "message": "账号快照没有可回查的来源引用。",
            "required": "为快照中的每条表现摘要补充原始作品或指标文件引用。",
            "current": len(snapshot_refs) if snapshot_refs is not None else None,
            "minimum": None,
            "source": snapshot_source,
        })

    if not isinstance(assessment, dict):
        blockers.append({
            "id": "assessment_missing",
            "message": "workspace 尚无当前 Agent 账号评估。",
            "required": "资料确认并满足 Agent 门槛后，再由 Agent 生成评估；ICE 只读取结果，不会代跑。",
            "current": None,
            "minimum": None,
            "source": assessment_source,
        })

    decision = assessment.get("decision") if isinstance(assessment, dict) else None
    assessment_evidence = [item for item in evidence if isinstance(item, dict)]
    if isinstance(assessment, dict) and not (isinstance(decision, str) and decision.strip()):
        blockers.append({
            "id": "assessment_decision_missing",
            "message": "Agent 评估没有记录结论类型。",
            "required": "按 Agent 规则版本写明评估类型，再由桥按该类型应用已配置门槛。",
            "current": None,
            "minimum": None,
            "source": assessment_source,
        })
    def source_ref_exists(item: dict[str, Any]) -> bool:
        reference = item.get("source_ref")
        if not isinstance(reference, str) or not reference.strip():
            return False
        try:
            return _inside(root, reference.strip()).is_file()
        except (OSError, RuntimeError, ValueError):
            return False

    valid_evidence_count = sum(1 for item in assessment_evidence if source_ref_exists(item))
    has_traceable_evidence = bool(assessment_evidence) and valid_evidence_count == len(assessment_evidence)
    if isinstance(assessment, dict) and not has_traceable_evidence:
        blockers.append({
            "id": "assessment_evidence_refs",
            "message": "当前账号评估缺少可在 workspace 中回查的证据来源。",
            "required": "为每条评估证据填写存在于 workspace 内的原始指标或作品文件路径。",
            "current": valid_evidence_count,
            "minimum": 1,
            "source": assessment_source,
        })
    decision_thresholds = adjustment_policy.get("minimum_evidence_by_decision")
    decision_thresholds = decision_thresholds if isinstance(decision_thresholds, dict) else {}
    threshold_spec = minimums if decision == "propose_strategy_adjustment" else decision_thresholds.get(decision)
    if isinstance(decision, str) and decision:
        threshold_sample_specs = {
            "comparable_public_posts": ("comparable_public_posts", "可比公开作品"),
            "execution_variants": ("execution_variants", "执行版本"),
            "published_posts": ("published_posts", "已登记发布作品"),
        }
        numeric_thresholds = 0
        for threshold_key, minimum in (threshold_spec.items() if isinstance(threshold_spec, dict) else ()):
            if threshold_key == "requires_persistent_weak_target_response":
                continue
            spec = threshold_sample_specs.get(str(threshold_key))
            if spec is None:
                blockers.append({
                    "id": "unsupported_threshold_" + str(threshold_key),
                    "message": "Agent 规则包含当前桥尚未映射的结论样本指标。",
                    "required": "先扩展桥的只读字段映射，并验证该指标来源；当前不展示表现结论。",
                    "current": None,
                    "minimum": minimum if isinstance(minimum, (int, float)) and not isinstance(minimum, bool) else None,
                    "source": policy_source,
                })
                continue
            numeric_thresholds += 1
            sample_id, label = spec
            current = next((row["value"] for row in sample_counts if row["id"] == sample_id), None)
            if (not isinstance(minimum, (int, float)) or isinstance(minimum, bool) or
                    not math.isfinite(minimum)):
                blockers.append({
                    "id": "conclusion_threshold_missing_" + sample_id,
                    "message": f"workspace 未配置当前结论类型所需的{label}门槛。",
                    "required": "先在 Agent 规则中明确并版本化该项最低样本数。",
                    "current": current,
                    "minimum": None,
                    "source": policy_source or assessment_source,
                    "updated_at": _timestamp(policy_path, policy),
                })
                continue
            if current is None or current < minimum:
                blockers.append({
                    "id": "conclusion_sample_" + sample_id,
                    "message": f"当前评估至少需要 {minimum:g} 项{label}，目前记录 {current if current is not None else '未知'}。",
                    "required": f"还需补足到至少 {minimum:g} 项{label}，并保留来源引用。",
                    "current": current,
                    "minimum": minimum,
                    "source": policy_source or assessment_source,
                    "updated_at": _timestamp(policy_path, policy),
                })
        if numeric_thresholds == 0:
            blockers.append({
                "id": "conclusion_threshold_missing",
                "message": "Agent 规则没有为当前评估类型配置可验证的最低样本数。",
                "required": "先在 Agent 规则中按结论类型明确并版本化门槛；当前只显示资料缺口。",
                "current": None,
                "minimum": None,
                "source": policy_source,
            })
        if (decision == "propose_strategy_adjustment" and
                minimums.get("requires_persistent_weak_target_response") is True and
                assessment.get("persistent_weak_target_response") is not True):
            blockers.append({
                "id": "persistent_weak_target_response",
                "message": "策略调整还要求有持续偏弱的目标反馈证据；当前评估没有该项明确记录。",
                "required": "补充带来源的持续目标反馈记录，并由 Agent 规则写入评估结果。",
                "current": None,
                "minimum": None,
                "source": assessment_source,
                "updated_at": _timestamp(assessment_path, assessment),
            })
    allow_assessment = (profile_confirmed and strategy_confirmed and bool(posts) and
                        has_traceable_evidence and not blockers)
    if not isinstance(assessment, dict):
        assessment_state = "missing"
    elif allow_assessment:
        assessment_state = "ready"
    else:
        assessment_state = "blocked"

    strategy_gate = None
    if minimums:
        strategy_gate = {
            "minimum_comparable_public_posts": comparable_minimum,
            "minimum_execution_variants": variants_minimum,
            "requires_persistent_weak_target_response": minimums.get("requires_persistent_weak_target_response"),
            "policy_id": policy.get("policy_id") if isinstance(policy, dict) else None,
            "policy_version": policy.get("version") if isinstance(policy, dict) else None,
            "source": policy_source,
            "updated_at": _timestamp(policy_path, policy),
        }
    return {
        "state": "ready" if allow_assessment else ("blocked" if blockers else "not_connected"),
        "profiles": profiles,
        "strategy": {
            "state": strategy_state,
            "status": strategy.get("status") if isinstance(strategy, dict) else None,
            "confirmed_by_user": strategy.get("confirmed_by_user") is True if isinstance(strategy, dict) else False,
            "items": strategy_items,
            "source": strategy_source,
            "updated_at": _timestamp(strategy_path, strategy),
        },
        "samples": sample_counts,
        "strategy_adjustment_gate": strategy_gate,
        "assessment": {
            "state": assessment_state,
            "decision": decision if allow_assessment else None,
            "conclusion": assessment.get("conclusion") if allow_assessment else None,
            "evidence": [{"evidence_id": item.get("evidence_id"), "source_ref": item.get("source_ref")}
                         for item in assessment_evidence if allow_assessment],
            "source": assessment_source,
            "updated_at": _timestamp(assessment_path, assessment),
        },
        "blockers": blockers,
    }


def _workbench_readout(root: Path, records: list[dict[str, Any]], errors: list[str],
                       selection: Any, selection_path: Path | None, plan: Any, plan_path: Path | None,
                       reference_bank: Any, reference_path: Path | None,
                       pain_bank: Any, pain_path: Path | None) -> dict[str, Any]:
    latest = _latest_copy_optimization(root, records, errors)
    materials = []
    for item_id, label, data, path, list_key in (
        ("selected_topics", "今日选题", selection, selection_path, "selected"),
        ("daily_plans", "内容计划", plan, plan_path, "plans"),
        ("references", "参考库", reference_bank, reference_path, "references"),
        ("pain_points", "痛点资料", pain_bank, pain_path, "pains"),
    ):
        rows = _list_value(data, list_key)
        materials.append({
            "id": item_id,
            "label": label,
            "value": len(rows) if rows is not None else None,
            "state": "ready" if rows is not None else "not_connected",
            "source": path.relative_to(root).as_posix() if path else None,
            "updated_at": _timestamp(path, data),
        })
    summary = plan.get("research_summary") if isinstance(plan, dict) else None
    missing = summary.get("missing_or_blocked") if isinstance(summary, dict) else None
    return {
        "state": "ready" if latest or any(item["value"] is not None for item in materials) else "not_connected",
        "draft": latest.get("draft") if latest else None,
        "template": None,
        "reference_matches": latest.get("reference_matches", []) if latest else [],
        "last_run": latest.get("last_run") if latest else None,
        "plan": {
            "status": str(plan.get("status") or "unknown") if isinstance(plan, dict) else "not_connected",
            "count": len(_list_value(plan, "plans") or []) if _list_value(plan, "plans") is not None else None,
            "blockers": [str(value) for value in missing[:10] if isinstance(value, str)] if isinstance(missing, list) else [],
            "source": plan_path.relative_to(root).as_posix() if plan_path else None,
            "updated_at": _timestamp(plan_path, plan),
        },
        "materials": materials,
    }


def build_view_model(workspace: Path, fixture: bool = False) -> dict[str, Any]:
    root = workspace.expanduser().resolve()
    if not root.is_dir():
        return empty_view_model("not_connected", "本地运营资料不可用")
    errors: list[str] = []
    manifest, manifest_path = _read_json(root, "project.manifest.json", errors)
    if not isinstance(manifest, dict):
        return empty_view_model("not_connected", "本地运营资料尚未完成初始化")
    contract_pointer = manifest.get("data_contract")
    contract, _ = _read_json(root, contract_pointer, errors) if isinstance(contract_pointer, str) else (None, None)
    status, status_path, _ = _read_manifest_json(root, manifest, "artifacts", "dashboard_status", errors)
    canonical, canonical_path, _ = _read_manifest_json(root, manifest, "artifacts", "dashboard_data", errors)
    selection, selection_path, _ = _read_manifest_json(root, manifest, "current", "topic_selection", errors)
    reference_bank, reference_path, _ = _read_manifest_json(root, manifest, "current", "reference_bank", errors)
    daily_plan, plan_path, _ = _read_manifest_json(root, manifest, "current", "daily_plan", errors)
    published, published_path, _ = _read_manifest_json(root, manifest, "current", "published_posts", errors)
    learning, learning_path, _ = _read_manifest_json(root, manifest, "current", "feedback_learning", errors)
    pain_bank, pain_path, _ = _read_manifest_json(root, manifest, "current", "pain_bank", errors)
    records = _run_records(root, errors)
    history = _run_history(records)
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
                        "updated_at": _source_timestamp(item.get("updatedAt") or item.get("updated_at")),
                    })
    freshness = {
        "state": "ready" if canonical_path and isinstance(canonical, dict) else "incomplete",
        "updated_at": _timestamp(canonical_path, canonical),
        "sources": source_status,
        "errors": errors[:10],
    }
    kpis = _direct_kpis(canonical, canonical_path)
    pipeline = _pipeline(root, selection, selection_path, reference_bank, reference_path,
                         daily_plan, plan_path, published, published_path,
                         learning, learning_path, canonical)
    recent = _recent(canonical, history)
    workbench = _workbench_readout(root, records, errors, selection, selection_path,
                                   daily_plan, plan_path, reference_bank, reference_path,
                                   pain_bank, pain_path)
    return {
        "workspace": {
            "id": manifest.get("project_id") or None,
            "mode": "template" if fixture else str(manifest.get("operating_mode") or "personal"),
            "timezone": contract.get("timezone") if isinstance(contract, dict) else None,
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
        "account": _account_readout(root, manifest, errors),
        "workbench": workbench,
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
