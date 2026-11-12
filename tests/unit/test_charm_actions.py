"""Unit tests for the start, stop and restart actions."""

import pytest
from ops import testing

_STOPPED = testing.ActiveStatus("stopped by action; run the start action")
_STATE = {"active-state": "active", "sub-state": "running", "main-pid": "42"}


@pytest.fixture(autouse=True)
def service_state(g, monkeypatch):
    from unittest.mock import MagicMock, patch

    m = MagicMock(return_value=dict(_STATE))
    p = patch("charm.gotodo.service_state", m)
    p.start()
    g["service_state"] = m
    g["start"] = MagicMock()
    g["stop"] = MagicMock()
    p1 = patch("charm.gotodo.start", g["start"])
    p2 = patch("charm.gotodo.stop", g["stop"])
    p1.start()
    p2.start()
    yield
    p.stop()
    p1.stop()
    p2.stop()


def _stopped(value=True):
    return testing.StoredState(
        owner_path="GotodoOperatorCharm", content={"intended_stopped": value}
    )


def test_stop_action_stops_and_sets_intent(ctx, g):
    state = ctx.run(ctx.on.action("stop"), testing.State())
    g["stop"].assert_called_once()
    assert state.unit_status == _STOPPED
    assert ctx.action_results == _STATE


def test_start_action_clears_intent_and_waits_healthy(ctx, g):
    state = ctx.run(ctx.on.action("start"), testing.State(stored_states=[_stopped()]))
    g["start"].assert_called_once()
    g["wait_healthy"].assert_called_once()
    assert state.unit_status == testing.ActiveStatus("")
    assert ctx.action_results == _STATE


def test_start_action_restarts_when_restart_pending(ctx, g):
    gm = g["marker"]
    gm.parent.mkdir(parents=True)
    gm.touch()
    ctx.run(ctx.on.action("start"), testing.State(stored_states=[_stopped()]))
    g["restart"].assert_called_once()
    g["start"].assert_not_called()
    assert not gm.exists()


def test_restart_action_restarts(ctx, g):
    state = ctx.run(ctx.on.action("restart"), testing.State())
    g["restart"].assert_called_once()
    g["wait_healthy"].assert_called_once()
    assert state.unit_status == testing.ActiveStatus("")
    assert ctx.action_results == _STATE


def test_restart_action_clears_marker(ctx, g):
    gm = g["marker"]
    gm.parent.mkdir(parents=True)
    gm.touch()
    ctx.run(ctx.on.action("restart"), testing.State())
    assert not gm.exists()


def test_start_action_fails_when_unhealthy(ctx, g):
    g["wait_healthy"].return_value = False
    with pytest.raises(testing.ActionFailed, match="did not become healthy"):
        ctx.run(ctx.on.action("start"), testing.State())


def test_restart_action_fails_when_unhealthy(ctx, g):
    g["wait_healthy"].return_value = False
    with pytest.raises(testing.ActionFailed, match="did not become healthy"):
        ctx.run(ctx.on.action("restart"), testing.State())


@pytest.mark.parametrize("action", ["start", "restart"])
def test_action_fails_on_invalid_config(ctx, g, action):
    with pytest.raises(testing.ActionFailed, match="invalid config"):
        ctx.run(ctx.on.action(action), testing.State(config={"port": 0}))
    g["start"].assert_not_called()
    g["restart"].assert_not_called()


@pytest.mark.parametrize("event", ["config_changed", "upgrade_charm", "update_status", "start"])
def test_intended_stopped_survives_hooks(ctx, g, event):
    state = ctx.run(getattr(ctx.on, event)(), testing.State(stored_states=[_stopped()]))
    g["restart"].assert_not_called()
    g["start"].assert_not_called()
    assert state.unit_status == _STOPPED
