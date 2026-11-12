"""Unit tests for user, ownership, systemd and health helpers."""

import stat
import subprocess
from unittest.mock import MagicMock, patch

import gotodo


def _cp(rc=0, stdout=""):
    return subprocess.CompletedProcess([], rc, stdout=stdout, stderr="")


def test_ensure_user_creates_when_missing():
    with patch("gotodo._run", side_effect=[_cp(2), _cp(0)]) as run:
        gotodo.ensure_user()
    assert run.call_args_list[0].args[0] == ["getent", "passwd", "gotodo"]
    assert run.call_args_list[1].args[0] == [
        "useradd", "--system", "--user-group", "--home-dir", "/opt/gotodo",
        "--no-create-home", "--shell", "/usr/sbin/nologin", "gotodo",
    ]  # fmt: skip


def test_ensure_user_noop_when_present():
    with patch("gotodo._run", return_value=_cp(0)) as run:
        gotodo.ensure_user()
    run.assert_called_once_with(["getent", "passwd", "gotodo"])


def test_ensure_dirs_modes_and_chown(tmp_path):
    opt, data = tmp_path / "opt", tmp_path / "data"
    with patch("gotodo._run", return_value=_cp(0)) as run:
        gotodo.ensure_dirs(opt_dir=opt, data_dir=data)
    assert stat.S_IMODE(opt.stat().st_mode) == 0o755
    assert stat.S_IMODE(data.stat().st_mode) == 0o750
    assert [c.args[0] for c in run.call_args_list] == [
        ["chown", "-R", "gotodo:gotodo", str(opt)],
        ["chown", "-R", "gotodo:gotodo", str(data)],
    ]


def test_systemctl_verbs():
    for fn, argv in [
        (gotodo.daemon_reload, ["systemctl", "daemon-reload"]),
        (gotodo.enable, ["systemctl", "enable", "gotodo"]),
        (gotodo.start, ["systemctl", "start", "gotodo"]),
        (gotodo.stop, ["systemctl", "stop", "gotodo"]),
        (gotodo.restart, ["systemctl", "restart", "gotodo"]),
        (gotodo.disable, ["systemctl", "disable", "gotodo"]),
    ]:
        with patch("gotodo._run", return_value=_cp(0)) as run:
            fn()
        run.assert_called_once_with(argv)


def test_systemctl_failure_raises():
    with patch("gotodo._run", return_value=_cp(1)):
        try:
            gotodo.start()
        except subprocess.CalledProcessError:
            return
    raise AssertionError("expected CalledProcessError")


def test_is_active():
    with patch("gotodo._run", return_value=_cp(0)) as run:
        assert gotodo.is_active() is True
    run.assert_called_once_with(["systemctl", "is-active", "--quiet", "gotodo"])
    with patch("gotodo._run", return_value=_cp(3)):
        assert gotodo.is_active() is False


def test_service_state_parses_show_output():
    out = "ActiveState=active\nSubState=running\nMainPID=42\n"
    with patch("gotodo._run", return_value=_cp(0, out)) as run:
        assert gotodo.service_state() == {
            "active-state": "active",
            "sub-state": "running",
            "main-pid": "42",
        }
    run.assert_called_once_with(
        ["systemctl", "show", "gotodo", "--property=ActiveState,SubState,MainPID"]
    )


def test_wait_healthy_true_after_retries():
    codes = iter([0, 0, 200])
    sleep = MagicMock()
    assert gotodo.wait_healthy(8080, probe=lambda _u: next(codes), sleep=sleep) is True
    assert sleep.call_count == 2


def test_wait_healthy_times_out():
    probe = MagicMock(return_value=503)
    assert (
        gotodo.wait_healthy(8080, timeout=5, interval=1, probe=probe, sleep=lambda _s: None)
        is False
    )
    assert probe.call_count <= 6


def test_wait_healthy_probes_expected_url():
    probe = MagicMock(return_value=200)
    gotodo.wait_healthy(9090, probe=probe, sleep=lambda _s: None)
    probe.assert_called_with("http://127.0.0.1:9090/api/health")


def test_http_status_returns_zero_on_connection_error():
    with patch("urllib.request.urlopen", side_effect=OSError("refused")):
        assert gotodo.http_status("http://127.0.0.1:1/x") == 0


def test_http_status_returns_http_error_code():
    import urllib.error

    err = urllib.error.HTTPError("u", 503, "x", None, None)  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err):
        assert gotodo.http_status("http://127.0.0.1:1/x") == 503


def test_remove_service_deletes_files_and_tolerates_stop_failure(tmp_path):
    unit, env = tmp_path / "u.service", tmp_path / "e.env"
    unit.write_text("x")
    env.write_text("y")
    results = iter([_cp(1), _cp(1), _cp(0)])
    with patch("gotodo._run", side_effect=lambda _argv: next(results)) as run:
        gotodo.remove_service(unit_path=unit, env_path=env)
    assert not unit.exists() and not env.exists()
    assert [c.args[0] for c in run.call_args_list] == [
        ["systemctl", "stop", "gotodo"],
        ["systemctl", "disable", "gotodo"],
        ["systemctl", "daemon-reload"],
    ]
