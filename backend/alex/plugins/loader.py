"""Import plugins/*/register(registry) so new tools can be added without editing the core."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from alex.tools.registry import Registry

log = logging.getLogger("alex.plugins")


def load_plugins(registry: Registry, folder: Path) -> list[str]:
    loaded: list[str] = []
    if not folder.exists():
        return loaded
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"alex_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            register = getattr(module, "register", None)
            if register is None:
                log.warning("plugin %s has no register()", path.name)
                continue
            register(registry)
            loaded.append(path.name)
        except Exception:
            log.exception("failed to load plugin %s", path.name)
    return loaded
