from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keenchic.inspections.base import InspectionAdapter

_log = logging.getLogger(__name__)

# All known adapters: (inspection_name, module_path, class_name)
_ADAPTER_ENTRIES: list[tuple[str, str, str]] = [
    ("ocr/datecode-num", "keenchic.inspections.adapters.ocr.datecode_num", "DatecodeNumAdapter"),
    ("ocr/holo-num", "keenchic.inspections.adapters.ocr.holo_num", "HoloNumAdapter"),
    ("ocr/pill-count", "keenchic.inspections.adapters.ocr.pill_count", "PillCountAdapter"),
    ("ocr/temper-num", "keenchic.inspections.adapters.ocr.temper_num", "TemperNumAdapter"),
]


def _build_registry() -> dict[str, type[InspectionAdapter]]:
    """Lazily import adapter classes; skip adapters whose module is not installed."""
    import importlib

    registry: dict[str, type[InspectionAdapter]] = {}
    for name, module_path, class_name in _ADAPTER_ENTRIES:
        try:
            mod = importlib.import_module(module_path)
            registry[name] = getattr(mod, class_name)
        except (ImportError, ModuleNotFoundError):
            _log.info("Adapter %s not available (module %s not found), skipping", name, module_path)
    return registry


# Registry is built on first access via get_adapter_class().
_registry: dict[str, type[InspectionAdapter]] | None = None


def get_adapter_class(name: str) -> type[InspectionAdapter] | None:
    """Return the adapter class for the given inspection name, or None if not found.

    Args:
        name: inspection name string, e.g. "ocr/datecode-num".
    """
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry.get(name)
