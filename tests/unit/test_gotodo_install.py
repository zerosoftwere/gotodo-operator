import hashlib
import io
import tarfile
from pathlib import Path

import pytest

import gotodo

VERSION = "v0.1.0"
ASSET = f"gotodo_{VERSION}_linux_amd64.tar.gz"
PREFIX = f"gotodo_{VERSION}_linux_amd64"


def make_tarball(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def make_fetch(tarball: bytes, digest: str | None = None):
    digest = digest or hashlib.sha256(tarball).hexdigest()
    tar_url, sums_url = gotodo.release_urls(VERSION)

    def fetch(url: str) -> bytes:
        if url == tar_url:
            return tarball
        if url == sums_url:
            return f"{digest}  {ASSET}\n".encode()
        raise AssertionError(url)

    return fetch


def good_tarball() -> bytes:
    return make_tarball({f"{PREFIX}/gotodo": b"binary", f"{PREFIX}/README.md": b"readme"})


def test_release_urls_v0_1_0():
    base = "https://github.com/ibrahim-dwellir/gotodo/releases/download/v0.1.0"
    assert gotodo.release_urls("v0.1.0") == (
        f"{base}/gotodo_v0.1.0_linux_amd64.tar.gz",
        f"{base}/checksums.txt",
    )


def test_parse_checksum_finds_asset():
    digest = "342bcab0e4d3cef60c229525045cb467ba068cd10a2465875f4fd21539eb5449"
    text = f"{digest}  gotodo_v0.1.0_linux_amd64.tar.gz\n"
    assert gotodo.parse_checksum(text, "gotodo_v0.1.0_linux_amd64.tar.gz") == digest


def test_parse_checksum_missing_asset_raises():
    with pytest.raises(gotodo.ChecksumError):
        gotodo.parse_checksum("abc  other.tar.gz\n", "gotodo_v0.1.0_linux_amd64.tar.gz")


def test_install_release_writes_binary_and_version(tmp_path: Path):
    opt = tmp_path / "opt"
    gotodo.install_release(VERSION, opt_dir=opt, fetch=make_fetch(good_tarball()))
    assert (opt / "gotodo").read_bytes() == b"binary"
    assert (opt / "gotodo").stat().st_mode & 0o777 == 0o755
    assert (opt / "README.md").read_bytes() == b"readme"
    assert gotodo.installed_version(opt) == VERSION


def test_installed_version_none_when_missing(tmp_path: Path):
    assert gotodo.installed_version(tmp_path / "nope") is None


def test_install_release_checksum_mismatch_keeps_old_binary(tmp_path: Path):
    opt = tmp_path / "opt"
    opt.mkdir()
    (opt / "gotodo").write_bytes(b"old")
    with pytest.raises(gotodo.ChecksumError):
        gotodo.install_release(VERSION, opt_dir=opt, fetch=make_fetch(good_tarball(), "0" * 64))
    assert (opt / "gotodo").read_bytes() == b"old"


@pytest.mark.parametrize("bad", ["../evil", "/abs"])
def test_install_release_rejects_path_traversal(tmp_path: Path, bad: str):
    opt = tmp_path / "opt"
    tarball = make_tarball({f"{PREFIX}/gotodo": b"binary", bad: b"x"})
    with pytest.raises(gotodo.ArchiveError):
        gotodo.install_release(VERSION, opt_dir=opt, fetch=make_fetch(tarball))
    assert not (tmp_path / "evil").exists()
    assert not (opt / "gotodo").exists()


def test_install_release_missing_binary_member_raises_archive_error(tmp_path: Path):
    tarball = make_tarball({f"{PREFIX}/README.md": b"readme"})
    with pytest.raises(gotodo.ArchiveError):
        gotodo.install_release(VERSION, opt_dir=tmp_path / "opt", fetch=make_fetch(tarball))


def test_install_release_not_a_tarball_raises_archive_error(tmp_path: Path):
    with pytest.raises(gotodo.ArchiveError):
        gotodo.install_release(VERSION, opt_dir=tmp_path / "opt", fetch=make_fetch(b"junk"))


def test_fetch_error_propagates_as_download_error(tmp_path: Path):
    def fetch(url: str) -> bytes:
        raise gotodo.DownloadError("boom")

    with pytest.raises(gotodo.DownloadError):
        gotodo.install_release(VERSION, opt_dir=tmp_path / "opt", fetch=fetch)
