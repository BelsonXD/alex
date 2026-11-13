"""Python versions ALEX will actually install on Windows.

3.14 and 3.15 (including pre-releases) are rejected. Wheels for PyYAML and
similar packages are not published for them, so pip tries to compile and
asks for Microsoft Visual C++. 3.12 is the version we point people to.
"""

from __future__ import annotations

import sys

SUPPORTED = ((3, 11), (3, 12), (3, 13))
DOWNLOAD = "https://www.python.org/downloads/windows/"


def is_supported(version: tuple[int, int] | tuple[int, int, int] | sys._version_info) -> bool:
    pair = (int(version[0]), int(version[1]))
    return pair in SUPPORTED


def explain(version: tuple[int, int, int] | None = None) -> str:
    found = ""
    if version is not None:
        found = f" This interpreter is Python {version[0]}.{version[1]}.{version[2]}."
    too_new = version is not None and (version[0] > 3 or (version[0] == 3 and version[1] >= 14))
    compile_note = ""
    if too_new:
        compile_note = (
            " Python 3.14 and 3.15 do not have Windows wheels for every library ALEX uses. "
            "pip then tries to build PyYAML from source and stops with "
            "'Microsoft Visual C++ 14.0 or greater is required'. "
            "You do not need Visual C++."
        )
    return (
        "ALEX supports Python 3.12, 3.13, and 3.11."
        + found
        + compile_note
        + " Install Python 3.12 from "
        + DOWNLOAD
        + " The py launcher can keep it next to any newer Python. "
        + "Then run start.bat again. It selects py -3.12, then py -3.13, then py -3.11."
    )


def ensure_supported_or_exit() -> None:
    if is_supported(sys.version_info):
        return
    print(explain((sys.version_info[0], sys.version_info[1], sys.version_info[2])))
    raise SystemExit(1)
