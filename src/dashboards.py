# Copyright 2026 Alhassan Ibrahim
# See LICENSE file for licensing details.

"""Load the bundled Grafana dashboards with stable, topology-scoped UIDs."""

import json
from pathlib import Path

from cosl import DashboardPath40UID

DASHBOARDS_ROOT = Path(__file__).parent / "grafana_dashboards"


def load_dashboards(model_uuid: str, app_name: str, *, root: Path = DASHBOARDS_ROOT) -> list[str]:
    """Return each bundled dashboard as a JSON string with a deterministic UID."""
    result = []
    for path in sorted(root.glob("*.json")):
        dashboard = json.loads(path.read_text())
        dashboard["uid"] = DashboardPath40UID.generate(model_uuid, f"{app_name}/{path.stem}")
        result.append(json.dumps(dashboard, sort_keys=True, separators=(",", ":")))
    return result
