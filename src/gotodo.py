"""Workload logic for GoTodo (installation, configuration and service control)."""

import hashlib
import http.client
import io
import logging
import os
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

OPT_DIR = Path("/opt/gotodo")
DATA_DIR = Path("/var/gotodo")
ENV_PATH = Path("/etc/gotodo/gotodo.env")
UNIT_PATH = Path("/etc/systemd/system/gotodo.service")
SERVICE = "gotodo"
RESTART_MARKER = Path("/etc/gotodo/.restart-pending")

_RELEASE_BASE = "https://github.com/ibrahim-dwellir/gotodo/releases/download"
_FETCH_TIMEOUT = 60


class InstallError(Exception):
    """Base class for release installation failures."""


class DownloadError(InstallError):
    """A release asset could not be downloaded."""


class ChecksumError(InstallError):
    """The checksum is missing or does not match."""


class ArchiveError(InstallError):
    """The release archive is malformed or unsafe."""


def release_urls(version: str) -> tuple[str, str]:
    """Return the (tarball URL, checksums URL) for a release version."""
    base = f"{_RELEASE_BASE}/{version}"
    return f"{base}/gotodo_{version}_linux_amd64.tar.gz", f"{base}/checksums.txt"


def fetch_url(url: str) -> bytes:
    """Download a URL, raising DownloadError on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT) as response:  # noqa: S310
            return response.read()
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise DownloadError(f"failed to download {url}: {e}") from e


def parse_checksum(checksums_text: str, asset_name: str) -> str:
    """Return the sha256 listed for asset_name in sha256sum-format text."""
    for line in checksums_text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset_name:
            return parts[0].lower()
    raise ChecksumError(f"no checksum listed for {asset_name}")


def installed_version(opt_dir: Path = OPT_DIR) -> str | None:
    """Return the installed release version, or None if not installed."""
    try:
        return (opt_dir / ".version").read_text().strip() or None
    except OSError:
        return None


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def _extract_members(tarball: bytes, prefix: str, dest: Path) -> None:
    """Extract the binary (required) and README (optional) into dest."""
    wanted = {f"{prefix}/gotodo": "gotodo", f"{prefix}/README.md": "README.md"}
    found: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
            members = tar.getmembers()
            for member in members:
                if not _safe_member_name(member.name):
                    raise ArchiveError(f"unsafe path in archive: {member.name}")
            for member in members:
                target = wanted.get(PurePosixPath(member.name).as_posix())
                if target is None:
                    continue
                if not member.isfile():
                    raise ArchiveError(f"{member.name} is not a regular file")
                src = tar.extractfile(member)
                if src is None:
                    raise ArchiveError(f"cannot read {member.name}")
                with src, open(dest / target, "wb") as out:
                    shutil.copyfileobj(src, out)
                found.add(target)
    except (tarfile.TarError, EOFError, OSError) as e:
        raise ArchiveError(f"invalid release archive: {e}") from e
    if "gotodo" not in found:
        raise ArchiveError(f"{prefix}/gotodo not found in archive")


def install_release(
    version: str,
    *,
    opt_dir: Path = OPT_DIR,
    fetch: Callable[[str], bytes] = fetch_url,
) -> None:
    """Download, verify and atomically install a gotodo release into opt_dir."""
    tar_url, sums_url = release_urls(version)
    asset = tar_url.rsplit("/", 1)[1]
    tarball = fetch(tar_url)
    expected = parse_checksum(fetch(sums_url).decode(errors="replace"), asset)
    actual = hashlib.sha256(tarball).hexdigest()
    if actual != expected:
        raise ChecksumError(f"sha256 mismatch for {asset}: expected {expected}, got {actual}")

    opt_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=opt_dir.parent) as staging_name:
        staging = Path(staging_name)
        _extract_members(tarball, asset.removesuffix(".tar.gz"), staging)
        (staging / "gotodo").chmod(0o755)
        (staging / ".version").write_text(version)
        for name in ("gotodo", "README.md", ".version"):
            if (staging / name).exists():
                os.replace(staging / name, opt_dir / name)
    logger.info("installed gotodo %s", version)


@dataclass(frozen=True)
class Settings:
    """Runtime settings rendered into the environment file."""

    port: int
    ops_port: int
    token_ttl: str
    mutex_profile_fraction: int
    block_profile_rate: int


def render_env(settings: Settings, jwt_secret: str) -> str:
    """Render the environment file content."""
    lines = [
        f"ADDR=:{settings.port}",
        f"OPS_ADDR=127.0.0.1:{settings.ops_port}",
        f"DB_PATH={DATA_DIR / 'gotodo.db'}",
        f"JWT_SECRET={jwt_secret}",
        f"TOKEN_TTL={settings.token_ttl}",
        f"MUTEX_PROFILE_FRACTION={settings.mutex_profile_fraction}",
        f"BLOCK_PROFILE_RATE={settings.block_profile_rate}",
    ]
    return "\n".join(lines) + "\n"


def read_env(env_path: Path = ENV_PATH) -> dict[str, str]:
    """Parse the env file into a dict; empty if it does not exist."""
    try:
        text = env_path.read_text()
    except FileNotFoundError:
        return {}
    result: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.startswith("#"):
            result[key.strip()] = value
    return result


def load_or_create_jwt_secret(env_path: Path = ENV_PATH) -> str:
    """Return the existing JWT secret from the env file, or generate a new one."""
    return read_env(env_path).get("JWT_SECRET") or secrets.token_hex(32)


def write_file_if_changed(path: Path, content: str, *, mode: int) -> bool:
    """Write content to path (atomically) with mode; return True if anything changed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        unchanged = path.read_text() == content and path.stat().st_mode & 0o777 == mode
    except FileNotFoundError:
        unchanged = False
    if unchanged:
        return False
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return True


def render_unit() -> str:
    """Render the systemd unit file content."""
    return f"""[Unit]
Description=GoTodo
After=network-online.target
Wants=network-online.target

[Service]
User=gotodo
Group=gotodo
EnvironmentFile={ENV_PATH}
WorkingDirectory={DATA_DIR}
ExecStart={OPT_DIR / "gotodo"}
Restart=on-failure
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths={DATA_DIR}
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
"""


_USER = "gotodo"
_HEALTH_TIMEOUT = 2


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    """Run a command without raising on a non-zero exit."""
    return subprocess.run(argv, check=False, capture_output=True, text=True)  # noqa: S603


def _run_checked(argv: list[str]) -> subprocess.CompletedProcess:
    result = _run(argv)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, argv, output=result.stdout, stderr=result.stderr
        )
    return result


def ensure_user() -> None:
    """Create the gotodo system user and group if missing."""
    if _run(["getent", "passwd", _USER]).returncode == 0:
        return
    _run_checked(
        [
            "useradd",
            "--system",
            "--user-group",
            "--home-dir",
            str(OPT_DIR),
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            _USER,
        ]
    )


def ensure_dirs(*, opt_dir: Path = OPT_DIR, data_dir: Path = DATA_DIR) -> None:
    """Create the install and data directories with the expected modes and owner."""
    for path, mode in ((opt_dir, 0o755), (data_dir, 0o750)):
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, mode)
        _run_checked(["chown", "-R", f"{_USER}:{_USER}", str(path)])


def _systemctl(*args: str) -> None:
    _run_checked(["systemctl", *args])


def daemon_reload() -> None:
    """Reload systemd units."""
    _systemctl("daemon-reload")


def enable() -> None:
    """Enable the service at boot."""
    _systemctl("enable", SERVICE)


def start() -> None:
    """Start the service."""
    _systemctl("start", SERVICE)


def stop() -> None:
    """Stop the service."""
    _systemctl("stop", SERVICE)


def disable_now() -> None:
    """Disable the service at boot and stop it now."""
    _systemctl("disable", "--now", SERVICE)


def restart() -> None:
    """Restart the service."""
    _systemctl("restart", SERVICE)


def disable() -> None:
    """Disable the service at boot."""
    _systemctl("disable", SERVICE)


def is_active() -> bool:
    """Return True if the service is active."""
    return _run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0


def service_state() -> dict[str, str]:
    """Return the systemd active state, sub state and main PID."""
    result = _run_checked(
        ["systemctl", "show", SERVICE, "--property=ActiveState,SubState,MainPID"]
    )
    props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return {
        "active-state": props.get("ActiveState", ""),
        "sub-state": props.get("SubState", ""),
        "main-pid": props.get("MainPID", ""),
    }


def http_status(url: str) -> int:
    """Return the HTTP status of a GET, or 0 on a connection error or timeout."""
    try:
        with urllib.request.urlopen(url, timeout=_HEALTH_TIMEOUT) as response:  # noqa: S310
            return response.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        return 0


def wait_healthy(
    port: int,
    *,
    timeout: float = 30.0,
    interval: float = 1.0,
    probe: Callable[[str], int] = http_status,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll the health endpoint until it returns 200 or the timeout elapses."""
    url = f"http://127.0.0.1:{port}/api/health"
    attempts = int(timeout / interval) + 1
    for attempt in range(attempts):
        if probe(url) == 200:
            return True
        if attempt < attempts - 1:
            sleep(interval)
    return False


def mark_restart_pending(path: Path = RESTART_MARKER) -> None:
    """Durably record that the workload needs a restart."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)


def restart_pending(path: Path = RESTART_MARKER) -> bool:
    """Return True when a restart has been recorded and not yet completed."""
    return path.exists()


def clear_restart_pending(path: Path = RESTART_MARKER) -> None:
    """Remove the restart marker."""
    path.unlink(missing_ok=True)


def remove_service(*, unit_path: Path = UNIT_PATH, env_path: Path = ENV_PATH) -> None:
    """Stop and disable the service, delete its unit and env files, reload systemd."""
    _run(["systemctl", "stop", SERVICE])
    _run(["systemctl", "disable", SERVICE])
    unit_path.unlink(missing_ok=True)
    env_path.unlink(missing_ok=True)
    daemon_reload()
