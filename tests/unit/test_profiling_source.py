"""Tests for the profiling-source (pprof_scrape) provider."""

import json
from unittest.mock import patch

from ops import testing

_ALL = ["process_cpu", "godeltaprof_memory", "goroutine", "godeltaprof_mutex", "godeltaprof_block"]


def _rel():
    return testing.SubordinateRelation("profiling-source", remote_app_name="alloy-sub")


def _installed(g):
    g["installed_version"].side_effect = None
    g["installed_version"].return_value = "v0.1.0"


def _payload(state, rel) -> dict:
    """Return the published payload, or {} when withdrawn."""
    data = state.get_relation(rel.id).local_unit_data
    return json.loads(data["profiling_source"]) if "profiling_source" in data else {}


def test_publishes_gotodo_payload(ctx, g):
    _installed(g)
    rel = _rel()
    state = ctx.run(ctx.on.config_changed(), testing.State(relations=[rel]))
    p = _payload(state, rel)
    assert p["service_name"] == "gotodo"
    assert p["targets"] == ["127.0.0.1:6060"]
    assert p["profile_types"] == _ALL


def test_zero_fraction_and_rate_drop_mutex_and_block(ctx, g):
    _installed(g)
    rel = _rel()
    state = ctx.run(
        ctx.on.config_changed(),
        testing.State(
            relations=[rel], config={"mutex-profile-fraction": 0, "block-profile-rate": 0}
        ),
    )
    assert _payload(state, rel)["profile_types"] == _ALL[:3]


def test_profiling_withdrawn_while_stopped(ctx, g):
    _installed(g)
    rel = _rel()
    state = ctx.run(ctx.on.config_changed(), testing.State(relations=[rel]))
    assert _payload(state, rel)
    with patch("charm.gotodo.stop"):
        state = ctx.run(ctx.on.action("stop"), state)
    assert _payload(state, rel) == {}
    state = ctx.run(ctx.on.config_changed(), state)
    assert _payload(state, rel) == {}


def test_withdrawn_while_not_installed(ctx, g):
    g["installed_version"].side_effect = None
    g["installed_version"].return_value = None
    rel = _rel()
    state = ctx.run(ctx.on.relation_joined(rel), testing.State(relations=[rel]))
    assert _payload(state, rel) == {}


def test_target_follows_ops_port(ctx, g):
    _installed(g)
    rel = _rel()
    state = ctx.run(
        ctx.on.config_changed(), testing.State(relations=[rel], config={"ops-port": 7070})
    )
    assert _payload(state, rel)["targets"] == ["127.0.0.1:7070"]


def test_invalid_config_withdraws_without_raising(ctx, g):
    _installed(g)
    rel = _rel()
    state = ctx.run(
        ctx.on.config_changed(), testing.State(relations=[rel], config={"ops-port": 0})
    )
    assert _payload(state, rel) == {}
