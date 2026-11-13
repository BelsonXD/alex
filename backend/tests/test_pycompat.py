from alex.pycompat import explain, is_supported


def test_supported_versions_are_only_311_through_313():
    assert is_supported((3, 12, 10))
    assert is_supported((3, 13, 1))
    assert is_supported((3, 11, 9))
    assert not is_supported((3, 15, 0))
    assert not is_supported((3, 14, 0))
    assert not is_supported((3, 10, 11))


def test_too_new_python_mentions_visual_cpp_and_the_312_download():
    text = explain((3, 15, 0))
    assert "3.15.0" in text
    assert "Visual C++" in text
    assert "https://www.python.org/downloads/windows/" in text
    assert "py -3.12" in text


def test_requirements_do_not_pull_pyyaml_via_uvicorn_standard():
    from pathlib import Path

    lines = Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    packages = [line.strip().lower() for line in lines if line.strip() and not line.strip().startswith("#")]
    assert not any(item.startswith("uvicorn[") for item in packages)
    assert not any(item.startswith("pyyaml") for item in packages)
