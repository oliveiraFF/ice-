"""Copy the approved project template to a disposable folder and add labeled test rows."""
import json
import shutil
import sys
from pathlib import Path

source, target = map(Path, sys.argv[1:3])
shutil.copytree(source, target)
presentation = target / "presentation"
presentation.mkdir(exist_ok=True)
(presentation / "ops-dashboard.json").write_text(json.dumps({
    "generated_at": "2026-10-26T12:00:00Z",
    "kpis": [
        {"id": "todo", "value": 0, "source": "presentation/ops-dashboard.json", "updated_at": "2026-10-26T12:00:00Z"},
        {"id": "in_progress", "value": 3, "source": "presentation/ops-dashboard.json", "updated_at": "2026-10-26T12:00:00Z"},
        {"id": "review", "value": 2, "source": "presentation/ops-dashboard.json", "updated_at": "2026-10-26T12:00:00Z"},
        {"id": "blocked", "value": 0, "source": "presentation/ops-dashboard.json", "updated_at": "2026-10-26T12:00:00Z"},
    ],
    "pipeline": [
        {"id": "topic", "value": 4, "state": "ready"},
        {"id": "research", "value": 3, "state": "ready"},
        {"id": "draft", "value": 2, "state": "ready"},
        {"id": "published", "value": 1, "state": "ready"},
        {"id": "reviewed", "value": 0, "state": "ready"},
    ],
    "alerts": [],
    "recent": [{
        "time": "2026-10-26T11:55:00Z",
        "title": "合成验收记录",
        "status": "completed",
        "source": "presentation/ops-dashboard.json",
        "workflow_id": "topic-candidates",
    }],
    "meta": {"sourceStatus": {}},
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
