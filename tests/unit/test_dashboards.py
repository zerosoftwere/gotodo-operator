"""Tests for the bundled Grafana dashboards and the grafana-dashboard relation."""

import json
from pathlib import Path

import pytest
from ops import testing

import dashboards

_ROOT = Path(__file__).parents[2] / "src" / "grafana_dashboards"

# From docs/superpowers/spikes/2026-11-12-alloy-pyroscope-spike.md, "Profile type IDs".
_SPIKE_PROFILE_TYPE_IDS = {
    "block:contentions:count:contentions:count",
    "block:delay:nanoseconds:contentions:count",
    "goroutine:goroutine:count:goroutine:count",
    "memory:alloc_objects:count:space:bytes",
    "memory:alloc_space:bytes:space:bytes",
    "memory:inuse_objects:count:space:bytes",
    "memory:inuse_space:bytes:space:bytes",
    "mutex:contentions:count:contentions:count",
    "mutex:delay:nanoseconds:contentions:count",
    "process_cpu:cpu:nanoseconds:cpu:nanoseconds",
    "process_cpu:samples:count:cpu:nanoseconds",
}


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_metrics_dashboard_has_no_datasource_variable():
    text = (_ROOT / "gotodo-dashboard.json").read_text()
    assert "${datasource}" not in text
    assert 'instance=~"$instance"' not in text
    dash = json.loads(text)
    names = [v["name"] for v in dash["templating"]["list"]]
    assert "juju_unit" in names and "route" in names
    assert "datasource" not in names and "instance" not in names
    prom = [
        n
        for n in _walk(dash)
        if isinstance(n, dict) and n.get("type") == "prometheus" and "uid" in n
    ]
    assert prom
    assert all(n["uid"] == "${prometheusds}" for n in prom)


def test_profiles_dashboard_keeps_pyroscope_datasource_variable():
    dash = json.loads((_ROOT / "gotodo-profiles-dashboard.json").read_text())
    variables = {v["name"]: v for v in dash["templating"]["list"]}
    assert variables["datasource"]["type"] == "datasource"
    assert variables["datasource"]["query"] == "grafana-pyroscope-datasource"
    assert variables["instance"]["query"]["labelName"] == "instance"
    ids = {n["profileTypeId"] for n in _walk(dash) if isinstance(n, dict) and "profileTypeId" in n}
    assert ids and ids <= _SPIKE_PROFILE_TYPE_IDS


def test_load_dashboards_sets_distinct_stable_uids():
    first = [json.loads(d)["uid"] for d in dashboards.load_dashboards("uuid-1", "gotodo")]
    again = [json.loads(d)["uid"] for d in dashboards.load_dashboards("uuid-1", "gotodo")]
    other = [json.loads(d)["uid"] for d in dashboards.load_dashboards("uuid-2", "gotodo")]
    assert len(first) == 2 and len(set(first)) == 2
    assert first == again
    assert set(first).isdisjoint(other)


@pytest.mark.parametrize("leader", [True, False])
def test_grafana_dashboard_relation_carries_two_dashboards(ctx, g, leader):
    rel = testing.Relation("grafana-dashboard", remote_app_name="grafana")
    state = ctx.run(ctx.on.config_changed(), testing.State(relations=[rel], leader=leader))
    app_data = state.get_relation(rel.id).local_app_data
    if not leader:
        assert "dashboards" not in app_data
        return
    payload = json.loads(app_data["dashboards"])
    assert len(payload["templates"]) == 2
