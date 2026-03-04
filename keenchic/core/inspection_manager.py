from __future__ import annotations

import asyncio

import numpy as np
import structlog

from keenchic.core.config import settings
from keenchic.inspections.registry import get_adapter_class

log = structlog.get_logger(__name__)


class InspectionManager:
    """Singleton that manages dynamic loading and caching of inspection adapters.

    Only one adapter is kept in memory at a time. Switching inspection names
    triggers unload of the current adapter before loading the new one.
    All load/unload operations are serialised with asyncio.Lock.
    """

    def __init__(self) -> None:
        self._current_name: str | None = None
        self._current_adapter = None
        self._current_backend: str | None = None
        self._lock = asyncio.Lock()

    def _resolve_backend(self) -> str:
        raw = settings.KEENCHIC_BACKEND.strip().lower()
        if raw in ("gpu", "trt", "tensorrt"):
            return "tensorrt"
        if raw in ("cpu", "openvino"):
            return "openvino"
        return "auto"

    def _load_models_with_failover(self, adapter, inspection_name: str, preferred: str) -> str:
        """Load models with the preferred backend; fall back to openvino on failure.

        Returns the backend that was actually used.
        Raises RuntimeError if all backends fail.
        """
        try:
            adapter.load_models(preferred)
            return preferred
        except Exception as exc:
            if preferred == "openvino":
                raise RuntimeError(
                    f"Failed to load models for '{inspection_name}': {exc}"
                ) from exc

            log.warning(
                "model.load_failed_fallback",
                inspection_name=inspection_name,
                attempted_backend=preferred,
                error=str(exc),
                fallback_backend="openvino",
            )
            try:
                adapter.load_models("openvino")
                return "openvino"
            except Exception as exc2:
                raise RuntimeError(
                    f"Failed to load models for '{inspection_name}' "
                    f"(tried {preferred} and openvino): {exc2}"
                ) from exc2

    async def run(self, inspection_name: str, image: np.ndarray, **kwargs) -> dict:
        """Route an image to the correct adapter, loading/switching as needed.

        Args:
            inspection_name: e.g. "ocr/datecode-num"
            image: BGR numpy array decoded from upload.
            **kwargs: forwarded to adapter.run().

        Raises:
            ValueError: if inspection_name is not registered.
            RuntimeError: if model loading fails.
        """
        adapter_class = get_adapter_class(inspection_name)
        if adapter_class is None:
            raise ValueError(f"Unknown inspection: '{inspection_name}'")

        async with self._lock:
            if self._current_name != inspection_name:
                if self._current_adapter is not None:
                    try:
                        self._current_adapter.unload_models()
                        log.info("model.unload", inspection_name=self._current_name)
                    except Exception as exc:
                        log.warning(
                            "model.unload_failed",
                            inspection_name=self._current_name,
                            error=str(exc),
                        )
                    finally:
                        self._current_adapter = None
                        self._current_name = None

                new_adapter = adapter_class()
                preferred = self._resolve_backend()
                try:
                    actual_backend = self._load_models_with_failover(
                        new_adapter, inspection_name, preferred
                    )
                except RuntimeError as exc:
                    log.error(
                        "model.load_failed",
                        inspection_name=inspection_name,
                        backend=preferred,
                        error=str(exc),
                    )
                    raise

                log.info(
                    "model.load",
                    inspection_name=inspection_name,
                    backend=actual_backend,
                    configured_backend=preferred,
                )
                self._current_adapter = new_adapter
                self._current_name = inspection_name
                self._current_backend = actual_backend

            return self._current_adapter.run(image, **kwargs)

    def get_status(self) -> dict:
        """Return current load state for the health endpoint."""
        return {
            "loaded_inspection": self._current_name,
            "backend": self._current_backend,
            "backend_config": settings.KEENCHIC_BACKEND,
        }


# Module-level singleton shared across the FastAPI application.
inspection_manager = InspectionManager()
