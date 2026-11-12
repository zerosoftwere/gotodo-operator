"""Shared fixtures for charm unit tests."""

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
_REAL_MARKER_FUNCS = {
    "mark_restart_pending": gotodo.mark_restart_pending,
    "restart_pending": gotodo.restart_pending,
    "clear_restart_pending": gotodo.clear_restart_pending,
}


@pytest.fixture
def g(tmp_path):
    mocks = {}
    patchers = []
    marker = tmp_path / "etc" / ".restart-pending"
    mocks["marker"] = marker
    for name, real in _REAL_MARKER_FUNCS.items():
        p = patch(f"charm.gotodo.{name}", lambda real=real: real(marker))
        p.start()
        patchers.append(p)
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
