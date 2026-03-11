from __future__ import annotations

import base64
import os
import sys
from typing import Any, Optional

import numpy as np

from keenchic.inspections.base import InspectionAdapter
from keenchic.inspections.result_codes import InspectionResultCode

# Absolute path to the submodule root (keenchic/inspections/ocr/).
# datecode_num_st lives directly here (not inside datecode_num_api/).
_SUBMODULE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ocr")
)


_DATECODE_PKG_DIR = os.path.join(_SUBMODULE_DIR, "datecode_num_st")


def _ensure_submodule_on_path() -> None:
    # Remove any existing submodule paths that might cause collisions
    ocr_root = _SUBMODULE_DIR
    sys.path = [p for p in sys.path if not (p.startswith(ocr_root) and p not in (_SUBMODULE_DIR, _DATECODE_PKG_DIR))]

    # datecode_num_st uses bare `from utils import ...` internally,
    # so the package directory itself must also be on sys.path.
    for path in (_SUBMODULE_DIR, _DATECODE_PKG_DIR):
        if path not in sys.path:
            sys.path.insert(0, path)

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


class DatecodeNumAdapter(InspectionAdapter):
    """Adapter wrapping the datecode_num_st inference engine.

    Supports:
    - v1: single date image → OCR result
    - v2: date image + permit image → OCR + permit code + product lookup
    """

    @classmethod
    def accepted_kwargs(cls) -> set[str]:
        return {"include_diag", "YMD_option", "permit_image"}

    def __init__(self) -> None:
        self._proc: Any = None
        self._detect_smp: Any = None
        self._detect_yolo12: Any = None
        self._model_smp: Any = None
        self._model_smp_pcode: Any = None
        self._model_yolo: Any = None
        self._cuda_context: Any = None
        self._backend_active: str | None = None

    # ------------------------------------------------------------------
    # InspectionAdapter interface
    # ------------------------------------------------------------------

    def load_models(self, backend: str) -> None:
        _ensure_submodule_on_path()

        desired = backend.strip().lower()
        try_order = ["tensorrt", "openvino"] if desired in ("auto", "tensorrt") else ["openvino", "tensorrt"]

        last_exc: Optional[Exception] = None
        for choice in try_order:
            try:
                if choice == "tensorrt":
                    imports = self._import_trt()
                else:
                    imports = self._import_openvino()
                self._activate(imports)
                last_exc = None
                break
            except Exception as exc:
                print(f"DatecodeNumAdapter: skipping {choice} backend: {exc}")
                last_exc = exc
                continue

        if last_exc is not None:
            raise RuntimeError(f"All backends failed for datecode-num: {last_exc}") from last_exc

        try:
            self._model_smp = self._get_smp_model()
            self._model_smp_pcode = self._get_smp_model_pcode()
            self._model_yolo = self._get_yolo_model()
        except Exception as exc:
            self.unload_models()
            raise RuntimeError(f"Model weight loading failed: {exc}") from exc

    def unload_models(self) -> None:
        self._model_smp = None
        self._model_smp_pcode = None
        self._model_yolo = None
        self._proc = None
        self._detect_smp = None
        self._detect_yolo12 = None
        self._get_smp_model = None       # type: ignore[assignment]
        self._get_smp_model_pcode = None  # type: ignore[assignment]
        self._get_yolo_model = None      # type: ignore[assignment]
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

        ymd_option: int = int(kwargs.get("YMD_option", 1))
        include_diag: bool = bool(kwargs.get("include_diag", False))
        permit_image: Optional[np.ndarray] = kwargs.get("permit_image")

        cuda_pushed = False
        if self._cuda_context is not None and self._backend_active == "tensorrt":
            self._cuda_context.push()
            cuda_pushed = True

        try:
            result = self._proc(
                image=image,
                image_pcode=permit_image,
                detection_args={"settings": {"YMD_option": ymd_option}},
                models=[self._detect_smp, self._model_smp, self._detect_yolo12, self._model_yolo],
                model_pcode=[self._detect_smp, self._model_smp_pcode, self._detect_yolo12, self._model_yolo],
                debug=False,
            )
        finally:
            if cuda_pushed:
                self._cuda_context.pop()

        payload = self._build_payload(result, include_diag)

        if permit_image is not None:
            payload = self._enrich_with_product(payload)

        return payload

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _import_openvino(self) -> dict:
        from datecode_num_st.model_detect_openvino import (  # type: ignore[import]
            detect_smp,
            detect_yolo12,
            get_smp_model,
            get_smp_model_pcode,
            get_yolo12_model,
        )
        from datecode_num_st.procd_date import proc  # type: ignore[import]

        return {
            "backend": "openvino",
            "detect_smp": detect_smp,
            "detect_yolo12": detect_yolo12,
            "get_smp_model": get_smp_model,
            "get_smp_model_pcode": get_smp_model_pcode,
            "get_yolo_model": get_yolo12_model,
            "proc": proc,
            "cuda_context": None,
        }

    def _import_trt(self) -> dict:
        import pycuda.driver as cuda  # type: ignore[import]

        cuda.init()
        ctx = cuda.Device(0).make_context()

        from datecode_num_st.model_detect_trt import (  # type: ignore[import]
            detect_smp,
            detect_yolo12,
            get_smp_model,
            get_smp_model_pcode,
            get_yolo12_model,
        )
        from datecode_num_st.procd_date import proc  # type: ignore[import]

        return {
            "backend": "tensorrt",
            "detect_smp": detect_smp,
            "detect_yolo12": detect_yolo12,
            "get_smp_model": get_smp_model,
            "get_smp_model_pcode": get_smp_model_pcode,
            "get_yolo_model": get_yolo12_model,
            "proc": proc,
            "cuda_context": ctx,
        }

    def _activate(self, imports: dict) -> None:
        self._detect_smp = imports["detect_smp"]
        self._detect_yolo12 = imports["detect_yolo12"]
        self._get_smp_model = imports["get_smp_model"]
        self._get_smp_model_pcode = imports["get_smp_model_pcode"]
        self._get_yolo_model = imports["get_yolo_model"]
        self._proc = imports["proc"]
        self._cuda_context = imports["cuda_context"]
        self._backend_active = imports["backend"]

    def _build_payload(self, result: dict, include_diag: bool) -> dict:
        payload: dict = {
            "result": int(result.get("result", InspectionResultCode.DETECTION_FAILED)),
            "pred_text": result.get("pred_text", ""),
            "pred_text_b": result.get("pred_text_b", ""),
            "pred_text_b2": result.get("pred_text_b2", ""),
            "YMD": result.get("YMD", ""),
            "YMD_b": result.get("YMD_b", ""),
            "YMD_b2": result.get("YMD_b2", ""),
            "pred_text_p": result.get("pred_text_p", ""),
            "pred_text_b_p": result.get("pred_text_b_p", ""),
            "pred_text_b2_p": result.get("pred_text_b2_p", ""),
            "pcode": result.get("pcode", ""),
            "pcode_b": result.get("pcode_b", ""),
            "pcode_b2": result.get("pcode_b2", ""),
        }
        if include_diag and "diag_img" in result:
            try:
                payload["diag_img"] = _b64_png(result["diag_img"])
            except Exception:
                payload["diag_img"] = None
        return payload

    def _enrich_with_product(self, payload: dict) -> dict:
        from keenchic.services.permit_lookup import get_product_by_pcode

        pcode = (payload.get("pcode") or "").strip()
        if not pcode:
            payload["pname_en"] = None
            payload["pname_zh"] = None
            return payload

        stripped = pcode.lstrip("0")
        lookup = get_product_by_pcode(stripped) if stripped != pcode else None
        if not lookup:
            lookup = get_product_by_pcode(pcode)

        payload["pname_en"] = lookup.get("product_name_en") if lookup else None
        payload["pname_zh"] = lookup.get("product_name_zh") if lookup else None
        return payload
