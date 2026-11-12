"""Unit tests for the start, stop and restart actions."""

import pytest
from ops import testing

import gotodo

_STOPPED = testing.ActiveStatus("stopped by action; run the start action")
_STATE = {"active-state": "active", "sub-state": "running", "main-pid": "42"}


@pytest.fixture(autouse=True)
def _installed(g):
    g["installed_version"].side_effect = None
    g["installed_version"].return_value = "v0.1.0"
    g["write_file_if_changed"].return_value = False


def _stopped(value=True):
    return testing.StoredState(
        owner_path="GotodoOperatorCharm", content={"intended_stopped": value}
    )


def test_stop_action_stops_and_sets_intent(ctx, g):
    state = ctx.run(ctx.on.action("stop"), testing.State())
    g["disable_now"].assert_called_once()
    g["stop"].assert_not_called()
    assert state.unit_status == _STOPPED
    assert ctx.action_results == _STATE


def test_start_action_clears_intent_and_waits_healthy(ctx, g):
    state = ctx.run(ctx.on.action("start"), testing.State(stored_states=[_stopped()]))
    g["start"].assert_called_once()
    g["enable"].assert_called_once()
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
    g["enable"].assert_called_once()
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
    g["is_active"].return_value = False
    state = ctx.run(getattr(ctx.on, event)(), testing.State(stored_states=[_stopped()]))
    g["restart"].assert_not_called()
    g["start"].assert_not_called()
    g["disable_now"].assert_not_called()
    assert state.unit_status == _STOPPED


@pytest.mark.parametrize("event", ["config_changed", "start", "update_status"])
def test_intended_stopped_and_active_is_stopped_again(ctx, g, event):
    state = ctx.run(getattr(ctx.on, event)(), testing.State(stored_states=[_stopped()]))
    g["disable_now"].assert_called_once()
    g["restart"].assert_not_called()
    assert state.unit_status == _STOPPED


def test_intended_stopped_unit_change_does_not_reenable(ctx, g):
    g["write_file_if_changed"].return_value = True
    g["is_active"].return_value = False
    ctx.run(ctx.on.config_changed(), testing.State(stored_states=[_stopped()]))
    g["enable"].assert_not_called()


@pytest.mark.parametrize("action", ["start", "restart"])
def test_action_retries_install_then_proceeds(ctx, g, action):
    g["installed_version"].side_effect = [None, None] + ["v0.1.0"] * 10
    ctx.run(ctx.on.action(action), testing.State())
    g["install_release"].assert_called_once()
    g["restart"].assert_called()


@pytest.mark.parametrize("action", ["start", "restart"])
def test_action_fails_when_still_not_installed(ctx, g, action):
    g["installed_version"].return_value = None
    g["install_release"].side_effect = gotodo.DownloadError("boom")
    with pytest.raises(testing.ActionFailed, match="gotodo is not installed; see juju debug-log"):
        ctx.run(ctx.on.action(action), testing.State())
    g["install_release"].assert_called_once()
    g["start"].assert_not_called()
    g["restart"].assert_not_called()
    g["enable"].assert_not_called()


def test_stop_action_fails_when_never_installed(ctx, g):
    g["installed_version"].return_value = None
    with pytest.raises(testing.ActionFailed, match="gotodo is not installed; see juju debug-log"):
        ctx.run(ctx.on.action("stop"), testing.State())
    g["disable_now"].assert_not_called()


def test_update_status_blocks_when_not_installed(ctx, g):
    g["installed_version"].return_value = None
    state = ctx.run(ctx.on.update_status(), testing.State())
    assert state.unit_status == testing.BlockedStatus(
        "gotodo v0.1.0 is not installed; run the restart action to retry"
    )
    g["install_release"].assert_not_called()
    g["wait_healthy"].assert_not_called()
