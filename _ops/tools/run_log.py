"""运行记录（可观测性 v1）。

每次 run 写一条结构化记录到 runs/run_log.jsonl：
run_id / task / status / input / output_summary / duration_ms / error / created_at
"""
import json
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def record(task, input_data, status, output_summary, duration_ms, error=None, runs_dir=None, meta=None):
    directory = Path(runs_dir) if runs_dir else RUNS
    directory.mkdir(parents=True, exist_ok=True)
    entry = {
        "run_id": uuid.uuid4().hex[:12],
        "task": task,
        "status": status,
        "input": input_data,
        "output_summary": output_summary,
        "duration_ms": duration_ms,
        "error": error,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if meta:
        entry.update(meta)
    with open(directory / "run_log.jsonl", "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def observe(task, input_data, fn, runs_dir=None):
    """计时执行 fn，按结果写一条 run 记录。异常也记录后抛出。"""
    start = time.time()
    try:
        result = fn()
    except Exception as exc:
        duration = int((time.time() - start) * 1000)
        record(task, input_data, "error", None, duration, str(exc), runs_dir)
        raise
    duration = int((time.time() - start) * 1000)
    status = result.get("status", "unknown") if isinstance(result, dict) else "unknown"
    record(task, input_data, status, _summarize(result), duration, None, runs_dir, meta=_meta(result))
    return result


def _summarize(result):
    if not isinstance(result, dict):
        return None
    outputs = result.get("outputs") or {}
    if "candidates" in outputs:
        return {"candidates": len(outputs["candidates"])}
    if "script" in outputs:
        return {"beats": len(outputs["script"].get("beats") or [])}
    return None


def _meta(result):
    if not isinstance(result, dict):
        return {}
    outputs = result.get("outputs") or {}
    meta = {"source": outputs.get("source"), "llm_error": outputs.get("llm_error")}
    script = outputs.get("script")
    if isinstance(script, dict):
        meta["model"] = script.get("model")
        meta["usage"] = script.get("usage")
        meta["llm_duration_ms"] = script.get("duration_ms")
    return meta
