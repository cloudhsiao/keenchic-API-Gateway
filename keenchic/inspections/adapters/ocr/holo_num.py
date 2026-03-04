from __future__ import annotations

import base64
import os
import sys
from typing import Any, Optional

import numpy as np

from keenchic.inspections.base import InspectionAdapter
from keenchic.inspections.result_codes import InspectionResultCode

# Absolute path to holo_num_st_lol package inside the submodule.
_SUBMODULE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ocr", "holo_num_st_lol")
)


def _ensure_submodule_on_path() -> None:
    # Remove any existing submodule paths that might cause collisions
    ocr_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "ocr"))
    sys.path = [p for p in sys.path if not (p.startswith(ocr_root) and p != _SUBMODULE_DIR)]
    
    if _SUBMODULE_DIR not in sys.path:
        sys.path.insert(0, _SUBMODULE_DIR)

    # Clear modules that are commonly named across different submodules
    # to force re-import from the new sys.path entry.
    for mod_name in ["model_detect_openvino", "model_detect_trt", "utils", "procd_date", "procd_holo", "procd_temper"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]


def _b64_png(img: np.ndarray) -> str:
    import cv2

    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Failed to encode diagnostic image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


class HoloNumAdapter(InspectionAdapter):
    """Adapter wrapping the holo_num_st_lol inference engine.

    Pipeline: low-light enhancement → display area crop → character detection.
    Supports OpenVINO (CPU) and TensorRT (GPU) backends.
    """

    @classmethod
    def accepted_kwargs(cls) -> set[str]:
        return {"include_diag"}

    def __init__(self) -> None:
        self._proc: Any = None
        self._detect_crop: Any = None
        self._detect_num: Any = None
        self._detect_enhance: Any = None
        self._get_crop_model: Any = None
        self._get_num_model: Any = None
        self._get_enhance_model: Any = None
        self._model_crop: Any = None
        self._model_num: Any = None
        self._model_enhance: Any = None
        self._cuda_context: Any = None
        self._backend_active: str | None = None

    # ------------------------------------------------------------------
    # InspectionAdapter interface
    # ------------------------------------------------------------------

    def load_models(self, backend: str) -> None:
        _ensure_submodule_on_path()

        desired = backend.strip().lower()
        try_order = (
            ["tensorrt", "openvino"] if desired in ("auto", "tensorrt") else ["openvino", "tensorrt"]
        )

        last_exc: Optional[Exception] = None
        for choice in try_order:
            try:
                imports = self._import_trt() if choice == "tensorrt" else self._import_openvino()
                self._activate(imports)
                last_exc = None
                break
            except Exception as exc:
                print(f"HoloNumAdapter: skipping {choice} backend: {exc}")
                last_exc = exc

        if last_exc is not None:
            raise RuntimeError(f"All backends failed for holo-num: {last_exc}") from last_exc

        try:
            self._model_crop = self._get_crop_model()
            self._model_num = self._get_num_model()
            # OpenVINO: pre-load enhance weights (returns a tuple).
            # TRT: store the factory function; procd_holo calls it with new_shape at inference time.
            if self._backend_active == "openvino":
                self._model_enhance = self._get_enhance_model()
            else:
                self._model_enhance = self._get_enhance_model
        except Exception as exc:
            self.unload_models()
            raise RuntimeError(f"Model weight loading failed: {exc}") from exc

    def unload_models(self) -> None:
        self._model_crop = None
        self._model_num = None
        self._model_enhance = None
        self._proc = None
        self._detect_crop = None
        self._detect_num = None
        self._detect_enhance = None
        self._get_crop_model = None  # type: ignore[assignment]
        self._get_num_model = None   # type: ignore[assignment]
        self._get_enhance_model = None  # type: ignore[assignment]
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
        debug: bool = bool(kwargs.get("debug", False))

        cuda_pushed = False
        if self._cuda_context is not None and self._backend_active == "tensorrt":
            self._cuda_context.push()
            cuda_pushed = True

        try:
            result = self._proc(
                image=image,
                detection_args="",
                models=[
                    self._detect_crop,
                    self._model_crop,
                    self._detect_num,
                    self._model_num,
                    self._detect_enhance,
                    self._model_enhance,
                ],
                debug=debug,
            )
        finally:
            if cuda_pushed:
                self._cuda_context.pop()

        return self._build_payload(result, include_diag)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _import_openvino(self) -> dict:
        from model_detect_openvino import (  # type: ignore[import]
            detect_cdet,
            detect_smp,
            get_smp_model,
            get_yolo_model,
        )
        from model_enhance_openvino import detect_ov, get_model_ov  # type: ignore[import]
        from procd_holo_ov import proc  # type: ignore[import]

        return {
            "backend": "openvino",
            "get_crop_model": get_smp_model,
            "detect_crop": detect_smp,
            "get_num_model": get_yolo_model,
            "detect_num": detect_cdet,
            "get_enhance_model": get_model_ov,
            "detect_enhance": detect_ov,
            "proc": proc,
            "cuda_context": None,
        }

    def _import_trt(self) -> dict:
        import pycuda.driver as cuda  # type: ignore[import]

        cuda.init()
        ctx = cuda.Device(0).make_context()

        from model_detect_trt import (  # type: ignore[import]
            detect_cdet,
            detect_smp,
            get_smp_model,
            get_yolo_model,
        )
        from model_enhance_trt import detect_trt, get_model_trt  # type: ignore[import]
        from procd_holo import proc  # type: ignore[import]

        return {
            "backend": "tensorrt",
            "get_crop_model": get_smp_model,
            "detect_crop": detect_smp,
            "get_num_model": get_yolo_model,
            "detect_num": detect_cdet,
            "get_enhance_model": get_model_trt,
            "detect_enhance": detect_trt,
            "proc": proc,
            "cuda_context": ctx,
        }

    def _activate(self, imports: dict) -> None:
        self._detect_crop = imports["detect_crop"]
        self._detect_num = imports["detect_num"]
        self._detect_enhance = imports["detect_enhance"]
        self._get_crop_model = imports["get_crop_model"]
        self._get_num_model = imports["get_num_model"]
        self._get_enhance_model = imports["get_enhance_model"]
        self._proc = imports["proc"]
        self._cuda_context = imports["cuda_context"]
        self._backend_active = imports["backend"]

    def _build_payload(self, result: dict, include_diag: bool) -> dict:
        payload: dict = {
            "result": int(result.get("result", InspectionResultCode.DETECTION_FAILED)),
            "pred_text": result.get("pred_text", ""),
        }
        if include_diag:
            for key in ("diag_img", "diag_img_en"):
                if result.get(key) is not None:
                    try:
                        payload[key] = _b64_png(result[key])
                    except Exception:
                        payload[key] = None
        return payload
