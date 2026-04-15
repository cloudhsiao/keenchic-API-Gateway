from __future__ import annotations

import base64
import os
import sys
from typing import Any

import numpy as np

from keenchic.inspections.base import InspectionAdapter
from keenchic.inspections.result_codes import InspectionResultCode

# Absolute path to temper_num_st package inside the submodule.
_SUBMODULE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ocr", "temper_num_st")
)


def _ensure_submodule_on_path() -> None:
    # Remove any existing submodule paths that might cause collisions
    ocr_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "ocr"))
    sys.path = [p for p in sys.path if not (p.startswith(ocr_root) and p != _SUBMODULE_DIR)]
    
    if _SUBMODULE_DIR not in sys.path:
        sys.path.insert(0, _SUBMODULE_DIR)

    # Clear modules that are commonly named across different submodules
    # to force re-import from the new sys.path entry.
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


class TemperNumAdapter(InspectionAdapter):
    """Adapter wrapping the temper_num_st inference engine.

    Performs OCR on temperature/expiry number panels.
    Only OpenVINO (CPU) backend is available; TRT weights are not provided.
    """

    @classmethod
    def accepted_kwargs(cls) -> set[str]:
        return {"include_diag"}

    def __init__(self) -> None:
        self._proc: Any = None
        self._detect_crop: Any = None
        self._detect_num: Any = None
        self._get_crop_model: Any = None
        self._get_num_model: Any = None
        self._model_crop: Any = None
        self._model_num: Any = None

    # ------------------------------------------------------------------
    # InspectionAdapter interface
    # ------------------------------------------------------------------

    def load_models(self, backend: str) -> None:
        _ensure_submodule_on_path()

        # temper_num_st only ships OpenVINO weights; ignore backend preference.
        try:
            imports = self._import_openvino()
            self._activate(imports)
        except Exception as exc:
            raise RuntimeError(f"Failed to load temper-num OpenVINO backend: {exc}") from exc

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
        self._get_crop_model = None  # type: ignore[assignment]
        self._get_num_model = None   # type: ignore[assignment]

    def run(self, image: np.ndarray, **kwargs) -> dict:
        if self._proc is None:
            raise RuntimeError("Models not loaded — call load_models() first")

        include_diag: bool = bool(kwargs.get("include_diag", False))
        debug: bool = bool(kwargs.get("debug", False))

        result = self._proc(
            image=image,
            detection_args="",
            models=[self._detect_crop, self._model_crop, self._detect_num, self._model_num],
            debug=debug,
        )

        return self._build_payload(result, include_diag)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _import_openvino(self) -> dict:
        from model_detect_openvino import (  # type: ignore[import]
            detect_smp,
            detect_yolo12,
            get_smp_model,
            get_yolo12_model,
        )
        from procd_temper import proc  # type: ignore[import]

        return {
            "get_crop_model": get_smp_model,
            "detect_crop": detect_smp,
            "get_num_model": get_yolo12_model,
            "detect_num": detect_yolo12,
            "proc": proc,
        }

    def _activate(self, imports: dict) -> None:
        self._detect_crop = imports["detect_crop"]
        self._detect_num = imports["detect_num"]
        self._get_crop_model = imports["get_crop_model"]
        self._get_num_model = imports["get_num_model"]
        self._proc = imports["proc"]

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
