# Copyright 2026 Alhassan Ibrahim
# See LICENSE file for licensing details.

import hashlib
import pathlib

LIB = pathlib.Path(__file__).parents[2] / "lib"


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_machine_observability_matches_canonical_source():
    path = LIB / "charms/dwellir_observability/v0/machine_observability.py"
    assert _sha256(path) == "f93196c38bbd8343b1d72173e860e1adf5ddf04ce728fae36d6e57fc3916e679"


def test_grafana_dashboard_matches_canonical_source():
    path = LIB / "charms/grafana_k8s/v0/grafana_dashboard.py"
    assert _sha256(path) == "4873a60692d88f5fc0c871f97e55bf50d5c638baf8527943341057fea0b753da"
