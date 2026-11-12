"""Unit tests for the charm lifecycle and reconcile."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from ops import testing

import gotodo
from charm import GotodoOperatorCharm

_FUNCS = [
    "ensure_user",
    "ensure_dirs",
    "install_release",
    "installed_version",
    "load_or_create_jwt_secret",
    "render_env",
    "render_unit",
    "write_file_if_changed",
    "daemon_reload",
    "enable",
    "restart",
    "is_active",
    "wait_healthy",
    "remove_service",
]


@pytest.fixture
def g():
    mocks = {}
    patchers = []
    for name in _FUNCS:
        p = patch(f"charm.gotodo.{name}", MagicMock())
        mocks[name] = p.start()
        patchers.append(p)
    mocks["installed_version"].side_effect = [None, "v0.1.0"]
    mocks["is_active"].return_value = True
    mocks["wait_healthy"].return_value = True
    mocks["write_file_if_changed"].return_value = True
    mocks["load_or_create_jwt_secret"].return_value = "s3cret"
    mocks["render_env"].return_value = "ENV"
    mocks["render_unit"].return_value = "UNIT"
    yield mocks
    for p in patchers:
        p.stop()


@pytest.fixture
def ctx():
    return testing.Context(GotodoOperatorCharm)


def test_install_installs_and_becomes_active(ctx, g):
    state = ctx.run(ctx.on.install(), testing.State())
    g["install_release"].assert_called_once()
    assert g["install_release"].call_args.args[0] == "v0.1.0"
    g["restart"].assert_called_once()
    assert state.unit_status == testing.ActiveStatus("")
    assert state.workload_version == "v0.1.0"
    assert state.opened_ports == frozenset({testing.TCPPort(8080)})


def test_reconcile_is_idempotent_without_changes(ctx, g):
    g["installed_version"].side_effect = None
    g["installed_version"].return_value = "v0.1.0"
    g["write_file_if_changed"].return_value = False
    state = ctx.run(ctx.on.config_changed(), testing.State())
    g["install_release"].assert_not_called()
    g["restart"].assert_not_called()
    assert state.unit_status == testing.ActiveStatus("")


def test_inactive_service_is_restarted(ctx, g):
    g["installed_version"].side_effect = None
    g["installed_version"].return_value = "v0.1.0"
    g["write_file_if_changed"].return_value = False
    g["is_active"].return_value = False
    ctx.run(ctx.on.config_changed(), testing.State())
    g["restart"].assert_called_once()


def test_version_change_reinstalls_and_restarts(ctx, g):
    g["installed_version"].side_effect = ["v0.1.0", "v0.2.0"]
    ctx.run(ctx.on.config_changed(), testing.State(config={"version": "v0.2.0"}))
    assert g["install_release"].call_args.args[0] == "v0.2.0"
    g["restart"].assert_called_once()


def test_download_failure_blocks_and_does_not_restart(ctx, g):
    g["install_release"].side_effect = gotodo.DownloadError("boom")
    state = ctx.run(ctx.on.install(), testing.State())
    assert state.unit_status == testing.BlockedStatus(
        "download of gotodo v0.1.0 failed; see juju debug-log"
    )
    g["restart"].assert_not_called()


def test_checksum_failure_blocks(ctx, g):
    g["install_release"].side_effect = gotodo.ChecksumError("bad")
    state = ctx.run(ctx.on.install(), testing.State())
    assert state.unit_status == testing.BlockedStatus("checksum mismatch for gotodo v0.1.0")
    g["restart"].assert_not_called()


def test_unhealthy_after_restart_blocks(ctx, g):
    g["wait_healthy"].return_value = False
    state = ctx.run(ctx.on.install(), testing.State())
    assert state.unit_status == testing.BlockedStatus(
        "gotodo did not become healthy; see journalctl -u gotodo"
    )


def test_port_change_restarts_and_moves_open_port(ctx, g):
    state = ctx.run(
        ctx.on.config_changed(),
        testing.State(config={"port": 9090}, opened_ports={testing.TCPPort(8080)}),
    )
    assert state.opened_ports == frozenset({testing.TCPPort(9090)})
    g["restart"].assert_called_once()
    assert g["wait_healthy"].call_args.args[0] == 9090


def test_config_change_keeps_jwt_secret(ctx, g, caplog):
    caplog.set_level(logging.DEBUG)
    ctx.run(ctx.on.config_changed(), testing.State())
    assert g["render_env"].call_args.args[1] == "s3cret"
    assert "s3cret" not in caplog.text


def test_update_status_never_restarts(ctx, g):
    state = ctx.run(ctx.on.update_status(), testing.State())
    assert state.unit_status == testing.ActiveStatus("")
    g["is_active"].return_value = False
    state = ctx.run(ctx.on.update_status(), testing.State())
    assert state.unit_status == testing.BlockedStatus(
        "gotodo is not running; run the restart action"
    )
    g["restart"].assert_not_called()


def test_update_status_unhealthy_blocks(ctx, g):
    g["wait_healthy"].return_value = False
    state = ctx.run(ctx.on.update_status(), testing.State())
    assert state.unit_status == testing.BlockedStatus(
        "gotodo did not become healthy; see journalctl -u gotodo"
    )
    assert g["wait_healthy"].call_args.kwargs == {"timeout": 5}


def test_update_status_intended_stopped(ctx, g):
    stored = testing.StoredState(
        owner_path="GotodoOperatorCharm", content={"intended_stopped": True}
    )
    state = ctx.run(ctx.on.update_status(), testing.State(stored_states=[stored]))
    assert state.unit_status == testing.ActiveStatus("stopped by action; run the start action")


def test_reconcile_intended_stopped_does_not_restart(ctx, g):
    stored = testing.StoredState(
        owner_path="GotodoOperatorCharm", content={"intended_stopped": True}
    )
    state = ctx.run(ctx.on.config_changed(), testing.State(stored_states=[stored]))
    g["restart"].assert_not_called()
    assert state.unit_status == testing.ActiveStatus("stopped by action; run the start action")


def test_remove_calls_remove_service(ctx, g):
    ctx.run(ctx.on.remove(), testing.State())
    g["remove_service"].assert_called_once()


def test_invalid_version_blocks_without_install(ctx, g):
    state = ctx.run(ctx.on.install(), testing.State(config={"version": "v1/../x"}))
    assert isinstance(state.unit_status, testing.BlockedStatus)
    assert state.unit_status.message.startswith("invalid config:")
    g["ensure_user"].assert_not_called()
    g["install_release"].assert_not_called()
    g["restart"].assert_not_called()


def test_token_ttl_with_newline_blocks(ctx, g):
    state = ctx.run(ctx.on.config_changed(), testing.State(config={"token-ttl": "24h\nX=1"}))
    assert state.unit_status.message.startswith("invalid config:")
    g["write_file_if_changed"].assert_not_called()


def test_port_equal_ops_port_blocks(ctx, g):
    state = ctx.run(ctx.on.config_changed(), testing.State(config={"port": 6060}))
    assert state.unit_status.message.startswith("invalid config:")
    g["restart"].assert_not_called()


def test_update_status_invalid_config_blocks(ctx, g):
    state = ctx.run(ctx.on.update_status(), testing.State(config={"port": 70000}))
    assert state.unit_status.message.startswith("invalid config:")
    g["wait_healthy"].assert_not_called()
