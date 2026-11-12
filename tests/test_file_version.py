from __future__ import annotations

import os

from ase2sprkkr.execution import FileState, FileVersion


def test_file_version_ignores_metadata_only_changes_when_digest_matches(tmp_path):
    path = tmp_path / "result.dat"
    path.write_bytes(b"same contents")
    version = FileVersion.capture(path)
    original = path.stat()

    os.utime(
        path,
        ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000),
    )

    cheap_current = FileVersion.capture(path, digest=False)
    assert cheap_current.fingerprint != version.fingerprint
    assert cheap_current.digest is None
    assert version.current() == version
    assert version.state() is FileState.CURRENT


def test_file_version_detects_content_change_after_metadata_change(tmp_path):
    path = tmp_path / "result.dat"
    path.write_bytes(b"old contents")
    version = FileVersion.capture(path)

    path.write_bytes(b"new contents")

    current = version.current()
    assert current != version
    assert current.digest is not None
    assert version.state() is FileState.OVERWRITTEN


def test_file_version_accepts_identical_replacement_file(tmp_path):
    path = tmp_path / "result.dat"
    path.write_bytes(b"same contents")
    version = FileVersion.capture(path)

    replacement = tmp_path / "replacement.dat"
    replacement.write_bytes(b"same contents")
    os.replace(replacement, path)

    assert FileVersion.capture(path, digest=False).fingerprint != version.fingerprint
    assert version.current() == version
    assert version.state() is FileState.CURRENT
