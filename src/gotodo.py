"""Workload logic for GoTodo (installation, configuration and service control)."""

import hashlib
import io
import logging
import os
import secrets
import shutil
import tarfile
import tempfile
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
    except (urllib.error.URLError, OSError, ValueError) as e:
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
