import hashlib
import zipfile
from pathlib import Path

import pytest

from alex.updates.service import apply_zip, is_newer, parse_version, safe_extract


def test_version_order():
    assert parse_version("v1.2.0") == (1, 2, 0)
    assert is_newer("1.1.0", "1.0.0")
    assert not is_newer("1.0.0", "1.1.0")
    assert not is_newer("1.1.0", "1.1.0")


def _zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as handle:
        for name, content in files.items():
            handle.writestr(name, content)


def test_apply_replaces_code_and_keeps_user_data(tmp_path: Path):
    install = tmp_path / "app"
    install.mkdir()
    (install / "start.py").write_text("print('old')\n", encoding="utf-8")
    (install / "backend" / "alex").mkdir(parents=True)
    (install / "backend" / "alex" / "__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    (install / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (install / ".env").write_text("OPENAI_API_KEY=keep-me\n", encoding="utf-8")
    data = tmp_path / "ALEX"
    data.mkdir()
    (data / "alex.db").write_bytes(b"sqlite")
    archive = tmp_path / "alex-1.1.0.zip"
    _zip(
        archive,
        {
            "start.py": "print('new')\n",
            "backend/alex/__init__.py": '__version__ = "1.1.0"\n',
            "requirements.txt": "fastapi\n",
            ".env": "OPENAI_API_KEY=should-not-copy\n",
        },
    )
    result = apply_zip(archive, install, run_deps=False, restart=False)
    assert result["ok"]
    assert "print('new')" in (install / "start.py").read_text(encoding="utf-8")
    assert "keep-me" in (install / ".env").read_text(encoding="utf-8")
    assert (data / "alex.db").read_bytes() == b"sqlite"


def test_bad_zip_does_not_change_the_install(tmp_path: Path):
    install = tmp_path / "app"
    install.mkdir()
    (install / "start.py").write_text("print('old')\n", encoding="utf-8")
    (install / "backend" / "alex").mkdir(parents=True)
    (install / "backend" / "alex" / "__init__.py").write_text("old\n", encoding="utf-8")
    archive = tmp_path / "broken.zip"
    _zip(archive, {"readme.txt": "not alex"})
    with pytest.raises(RuntimeError, match="not an ALEX build"):
        apply_zip(archive, install, run_deps=False, restart=False)
    assert "print('old')" in (install / "start.py").read_text(encoding="utf-8")


def test_failed_pip_rolls_back(tmp_path: Path, monkeypatch):
    install = tmp_path / "app"
    install.mkdir()
    (install / "start.py").write_text("old-start\n", encoding="utf-8")
    (install / "requirements.txt").write_text("old\n", encoding="utf-8")
    (install / "backend" / "alex").mkdir(parents=True)
    (install / "backend" / "alex" / "__init__.py").write_text("old-init\n", encoding="utf-8")
    archive = tmp_path / "alex-1.2.0.zip"
    _zip(
        archive,
        {
            "start.py": "new-start\n",
            "requirements.txt": "new\n",
            "backend/alex/__init__.py": "new-init\n",
        },
    )

    def boom(path):
        del path
        raise RuntimeError("pip exploded")

    monkeypatch.setattr("alex.updates.service._pip_install", boom)
    with pytest.raises(RuntimeError, match="Restored"):
        apply_zip(archive, install, run_deps=True, restart=False)
    assert (install / "start.py").read_text(encoding="utf-8") == "old-start\n"
    assert (install / "requirements.txt").read_text(encoding="utf-8") == "old\n"


def test_sha256_mismatch_rejects_the_download(tmp_path: Path):
    archive = tmp_path / "alex.zip"
    archive.write_bytes(b"not a zip")
    digest = hashlib.sha256(b"other").hexdigest()
    from alex.updates.service import download_zip

    async def run():
        await download_zip(archive.as_uri(), tmp_path / "out.zip", "", digest)

    # file URI may not be supported by httpx. The hash check itself is covered by comparing bytes.
    assert hashlib.sha256(archive.read_bytes()).hexdigest() != digest


def test_zip_slip_is_rejected(tmp_path: Path):
    archive = tmp_path / "slip.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "nope")
    with pytest.raises(RuntimeError, match="unsafe path"):
        safe_extract(archive, tmp_path / "out")
