import re
from pathlib import Path

import gotodo


def test_render_env_contains_exact_keys():
    text = gotodo.render_env(gotodo.Settings(8080, 6060, "24h", 5, 5), "s")
    assert text.splitlines() == [
        "ADDR=:8080",
        "OPS_ADDR=127.0.0.1:6060",
        "DB_PATH=/var/gotodo/gotodo.db",
        "JWT_SECRET=s",
        "TOKEN_TTL=24h",
        "MUTEX_PROFILE_FRACTION=5",
        "BLOCK_PROFILE_RATE=5",
    ]


def test_read_env_missing_returns_empty(tmp_path: Path):
    assert gotodo.read_env(tmp_path / "none.env") == {}


def test_load_or_create_jwt_secret_generates_64_hex(tmp_path: Path):
    secret = gotodo.load_or_create_jwt_secret(tmp_path / "gotodo.env")
    assert re.fullmatch(r"[0-9a-f]{64}", secret)


def test_env_rerender_preserves_jwt_secret(tmp_path: Path):
    env = tmp_path / "gotodo.env"
    settings = gotodo.Settings(8080, 6060, "24h", 5, 5)
    first = gotodo.load_or_create_jwt_secret(env)
    gotodo.write_file_if_changed(env, gotodo.render_env(settings, first), mode=0o600)
    assert gotodo.read_env(env)["JWT_SECRET"] == first
    assert gotodo.load_or_create_jwt_secret(env) == first


def test_write_file_if_changed_sets_mode_and_reports_change(tmp_path: Path):
    path = tmp_path / "sub" / "f"
    assert gotodo.write_file_if_changed(path, "a", mode=0o600) is True
    assert path.stat().st_mode & 0o777 == 0o600
    assert gotodo.write_file_if_changed(path, "a", mode=0o600) is False
    assert gotodo.write_file_if_changed(path, "b", mode=0o600) is True


def test_render_unit_runs_as_gotodo():
    unit = gotodo.render_unit()
    for line in (
        "User=gotodo",
        "Group=gotodo",
        "EnvironmentFile=/etc/gotodo/gotodo.env",
        "ExecStart=/opt/gotodo/gotodo",
        "ReadWritePaths=/var/gotodo",
        "WantedBy=multi-user.target",
    ):
        assert line in unit.splitlines()


def test_read_env_value_containing_equals(tmp_path: Path):
    env = tmp_path / "e"
    env.write_text("JWT_SECRET=a=b==\nX=1\n")
    assert gotodo.read_env(env) == {"JWT_SECRET": "a=b==", "X": "1"}


def test_restart_marker_roundtrip(tmp_path: Path):
    marker = tmp_path / "sub" / ".restart-pending"
    assert gotodo.restart_pending(marker) is False
    gotodo.mark_restart_pending(marker)
    assert gotodo.restart_pending(marker) is True
    assert marker.stat().st_mode & 0o777 == 0o600
    gotodo.clear_restart_pending(marker)
    assert gotodo.restart_pending(marker) is False
    gotodo.clear_restart_pending(marker)  # missing is fine
