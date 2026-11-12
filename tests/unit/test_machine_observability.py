"""Tests for the machine-observability provider."""

import json

from ops import testing


def _rel():
    return testing.SubordinateRelation("machine-observability", remote_app_name="alloy-sub")


def _payload(state, rel):
    out = state.get_relation(rel.id)
    return json.loads(out.local_app_data["payload"])


def test_leader_publishes_v3_payload(ctx, g):
    rel = _rel()
    state = ctx.run(
        ctx.on.config_changed(), testing.State(leader=True, relations=[rel], config={})
    )
    p = _payload(state, rel)
    assert p["schema_version"] == 3
    assert p["metrics_endpoints"][0]["targets"] == ["localhost:6060"]
    assert p["metrics_endpoints"][0]["path"] == "/metrics"
    assert p["systemd_units"] == ["gotodo.service"]
    assert p["source_topology"]["application"] == "gotodo-operator"


def test_payload_follows_ops_port(ctx, g):
    rel = _rel()
    state = ctx.run(
        ctx.on.config_changed(),
        testing.State(leader=True, relations=[rel], config={"ops-port": 7070}),
    )
    assert _payload(state, rel)["metrics_endpoints"][0]["targets"] == ["localhost:7070"]


def test_non_leader_does_not_publish_machine_observability(ctx, g):
    rel = _rel()
    state = ctx.run(ctx.on.config_changed(), testing.State(leader=False, relations=[rel]))
    assert not state.get_relation(rel.id).local_app_data


def test_leader_elected_republishes(ctx, g):
    rel = _rel()
    state = ctx.run(ctx.on.leader_elected(), testing.State(leader=True, relations=[rel]))
    assert _payload(state, rel)["schema_version"] == 3


def test_invalid_config_skips_publish(ctx, g):
    rel = _rel()
    state = ctx.run(
        ctx.on.config_changed(),
        testing.State(leader=True, relations=[rel], config={"ops-port": 0}),
    )
    assert not state.get_relation(rel.id).local_app_data
