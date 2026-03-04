from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keenchic.inspections.base import InspectionAdapter


def _build_registry() -> dict[str, type[InspectionAdapter]]:
    """Lazily import adapter classes to avoid circular imports at module load."""
    from keenchic.inspections.adapters.ocr.datecode_num import DatecodeNumAdapter
    from keenchic.inspections.adapters.ocr.holo_num import HoloNumAdapter
    from keenchic.inspections.adapters.ocr.pill_count import PillCountAdapter
    from keenchic.inspections.adapters.ocr.temper_num import TemperNumAdapter

    return {
        "ocr/datecode-num": DatecodeNumAdapter,
        "ocr/holo-num": HoloNumAdapter,
        "ocr/pill-count": PillCountAdapter,
        "ocr/temper-num": TemperNumAdapter,
    }


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
