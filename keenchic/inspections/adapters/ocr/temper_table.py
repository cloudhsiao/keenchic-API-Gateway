from __future__ import annotations

import base64
import os
import sys
from typing import Any, Optional

import numpy as np

from keenchic.inspections.base import InspectionAdapter
from keenchic.inspections.result_codes import InspectionResultCode

# Absolute path to temper_num_st package inside the submodule.
# temper_table shares the same submodule directory as temper_num.
_SUBMODULE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ocr", "temper_num_st")
)


def _ensure_submodule_on_path() -> None:
    ocr_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "ocr"))
    sys.path = [p for p in sys.path if not (p.startswith(ocr_root) and p != _SUBMODULE_DIR)]

    if _SUBMODULE_DIR not in sys.path:
        sys.path.insert(0, _SUBMODULE_DIR)

    # np.unicode_ was removed in NumPy 2.0; the submodule (read-only) still uses it.
    if not hasattr(np, "unicode_"):
        np.unicode_ = np.str_  # type: ignore[attr-defined]

    # Clear all modules from both temper_num and temper_table to prevent
    # cross-contamination when the active adapter switches between the two.
    for mod_name in [
        "model_detect_openvino",
        "model_detect_openvino_512",
        "model_detect_trt",
        "model_detect_trt_512",
        "utils",
        "procd_date",
        "procd_holo",
        "procd_temper",
        "procd_table",
    ]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]


def _b64_png(img: np.ndarray) -> str:
    import cv2

    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Failed to encode diagnostic image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _parse_coords(raw: str, field_name: str) -> list[int]:
    """Parse a coordinate pair from either JSON '[r,c]' or CSV 'r,c' format."""
    import json

    s = raw.strip()
    if s.startswith("["):
        try:
            val = json.loads(s)
            if isinstance(val, list) and len(val) == 2:
                return [int(val[0]), int(val[1])]
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    try:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) == 2:
            return [int(parts[0]), int(parts[1])]
    except ValueError:
        pass
    raise ValueError(
        f"invalid {field_name}: expected '[r,c]' or 'r,c', got {raw!r}"
    )


class TemperTableAdapter(InspectionAdapter):
    """Adapter wrapping the temper_table inference engine (procd_table.py).

    Performs multi-channel temperature probe table OCR.
    Supports both TensorRT (primary on GPU edge server) and OpenVINO (fallback).
    """

    @classmethod
    def accepted_kwargs(cls) -> set[str]:
        return {"include_diag", "input_coords", "table_size"}

    def __init__(self) -> None:
        self._proc: Any = None
        self._detect_crop: Any = None
        self._detect_num: Any = None
        self._get_crop_model: Any = None
        self._get_num_model: Any = None
        self._model_crop: Any = None
        self._model_num: Any = None
        self._cuda_context: Any = None
        self._backend_active: str | None = None

    # ------------------------------------------------------------------
    # InspectionAdapter interface
    # ------------------------------------------------------------------

    def load_models(self, backend: str) -> None:
        _ensure_submodule_on_path()

        desired = backend.strip().lower()
        try_order = (
            ["tensorrt", "openvino"] if desired in ("auto", "tensorrt", "gpu", "trt")
            else ["openvino", "tensorrt"]
        )

        last_exc: Optional[Exception] = None
        for choice in try_order:
            try:
                imports = self._import_trt() if choice == "tensorrt" else self._import_openvino()
                self._activate(imports)
                last_exc = None
                break
            except Exception as exc:
                print(f"TemperTableAdapter: skipping {choice} backend: {exc}")
                last_exc = exc
                continue

        if last_exc is not None:
            raise RuntimeError(f"All backends failed for temper-table: {last_exc}") from last_exc

        try:
            self._model_crop = self._get_crop_model()
            self._model_num = self._get_num_model()
        except Exception as exc:
            self.unload_models()
            raise RuntimeError(f"Model weight loading failed: {exc}") from exc

    def unload_models(self) -> None:
        self._model_crop = None
        self._model_num = None
        self._proc = None
        self._detect_crop = None
        self._detect_num = None
        self._get_crop_model = None   # type: ignore[assignment]
        self._get_num_model = None    # type: ignore[assignment]
        if self._cuda_context is not None:
            try:
                self._cuda_context.pop()
            except Exception:
                pass
            self._cuda_context = None
        self._backend_active = None

    def run(self, image: np.ndarray, **kwargs) -> dict:
        if self._proc is None:
            raise RuntimeError("Models not loaded — call load_models() first")

        include_diag: bool = bool(kwargs.get("include_diag", False))

        raw_coords = kwargs.get("input_coords")
        input_coords: list[int] = (
            _parse_coords(raw_coords, "input_coords") if raw_coords else [1, 1]
        )

        raw_table = kwargs.get("table_size")
        table_size: list[int] = (
            _parse_coords(raw_table, "table_size") if raw_table else [2, 2]
        )

        detection_args = {
            "settings": {
                "input_coords": input_coords,
                "table_size": table_size,
            }
        }

        cuda_pushed = False
        if self._cuda_context is not None and self._backend_active == "tensorrt":
            self._cuda_context.push()
            cuda_pushed = True

        try:
            result = self._proc(
                image=image,
                detection_args=detection_args,
                models=[self._detect_crop, self._model_crop, self._detect_num, self._model_num],
                debug=False,
            )
        except (IndexError, ValueError) as exc:
            result = {
                "result": InspectionResultCode.DETECTION_FAILED,
                "pred_text": "",
                "_error": str(exc),
            }
        finally:
            if cuda_pushed:
                self._cuda_context.pop()

        return self._build_payload(result, include_diag)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _import_openvino(self) -> dict:
        from model_detect_openvino_512 import (  # type: ignore[import]
            detect_smp,
            detect_yolo12,
            get_smp_model,
            get_yolo12_model,
        )
        from procd_table import proc  # type: ignore[import]

        return {
            "backend": "openvino",
            "get_crop_model": get_smp_model,
            "detect_crop": detect_smp,
            "get_num_model": get_yolo12_model,
            "detect_num": detect_yolo12,
            "proc": proc,
            "cuda_context": None,
        }

    def _import_trt(self) -> dict:
        import pycuda.driver as cuda  # type: ignore[import]

        cuda.init()
        ctx = cuda.Device(0).make_context()

        from model_detect_trt_512 import (  # type: ignore[import]
            detect_smp,
            detect_yolo12,
            get_smp_model,
            get_yolo12_model,
        )
        from procd_table import proc  # type: ignore[import]

        return {
            "backend": "tensorrt",
            "get_crop_model": get_smp_model,
            "detect_crop": detect_smp,
            "get_num_model": get_yolo12_model,
            "detect_num": detect_yolo12,
            "proc": proc,
            "cuda_context": ctx,
        }

    def _activate(self, imports: dict) -> None:
        self._detect_crop = imports["detect_crop"]
        self._detect_num = imports["detect_num"]
        self._get_crop_model = imports["get_crop_model"]
        self._get_num_model = imports["get_num_model"]
        self._proc = imports["proc"]
        self._cuda_context = imports["cuda_context"]
        self._backend_active = imports["backend"]

    def _build_payload(self, result: dict, include_diag: bool) -> dict:
        payload: dict = {
            "result": int(result.get("result", InspectionResultCode.DETECTION_FAILED)),
            "pred_text": result.get("pred_text", ""),
        }
        if include_diag and result.get("diag_img") is not None:
            try:
                payload["diag_img"] = _b64_png(result["diag_img"])
            except Exception:
                payload["diag_img"] = None
        return payload
