import base64
import os
from typing import Annotated, Optional

import numpy as np
import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse

from keenchic.api.deps import require_api_key
from keenchic.core.config import settings
from keenchic.core.inspection_manager import inspection_manager
from keenchic.inspections.registry import get_adapter_class
from keenchic.schemas.response import InspectResponse

log = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64_png(img: np.ndarray) -> str:
    import cv2  # lazy import to avoid failures in environments without OpenCV

    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Failed to encode diagnostic image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


async def _decode_upload(upload: UploadFile, field_name: str) -> np.ndarray:
    """Read an uploaded file and decode it to a BGR numpy array."""
    try:
        data = await upload.read()
        if not data:
            raise ValueError("empty file")
        arr = np.frombuffer(data, dtype=np.uint8)
        import cv2

        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("unable to decode image")
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid image for '{field_name}': {exc}"
        ) from exc

    _save_upload_if_configured(data, upload)
    return image


def _save_upload_if_configured(data: bytes, upload: UploadFile) -> None:
    """Persist raw upload to disk if KEENCHIC_UPLOAD_DIR is configured."""
    upload_dir = (settings.KEENCHIC_UPLOAD_DIR or "").strip() or None
    if not upload_dir:
        return
    try:
        import uuid
        from datetime import datetime

        os.makedirs(upload_dir, exist_ok=True)
        base = os.path.basename(upload.filename or "")
        name, ext = os.path.splitext(base)
        if not ext:
            ctype = getattr(upload, "content_type", "") or ""
            ext = (
                ("." + ctype.split("/", 1)[1].lower())
                if ctype.startswith("image/")
                else ".jpg"
            )
        dt = datetime.utcnow()
        ts = dt.strftime("%Y%m%d-%H%M%S") + f"-{int(dt.microsecond / 1000):03d}"
        safe = (
            "".join(c for c in name if c.isalnum() or c in ("-", "_")).strip()[:50]
        ) or "upload"
        filename = f"{ts}-{uuid.uuid4().hex[:8]}-{safe}{ext}"
        with open(os.path.join(upload_dir, filename), "wb") as f:
            f.write(data)
    except Exception as exc:
        log.warning("upload.save_failed", filename=upload.filename, error=str(exc))


def _normalize_ymd_option(raw: Optional[str]) -> int:
    try:
        value = int(raw)  # type: ignore[arg-type]
        return value if value in (1, 2) else 1
    except (TypeError, ValueError):
        return 1


def _finalize_diag(payload: dict, result: dict, include_diag: bool) -> None:
    if include_diag and "diag_img" in result:
        try:
            payload["diag_img"] = _b64_png(result["diag_img"])
        except Exception:
            payload["diag_img"] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health")
def health() -> JSONResponse:
    """Health check — returns current load state. No auth required."""
    status = inspection_manager.get_status()
    return JSONResponse({"status": "ok", **status})


@router.post(
    "/api/v1/inspect",
    dependencies=[Depends(require_api_key)],
    response_model=InspectResponse,
)
async def inspect(
    x_inspection_name: Annotated[
        Optional[str], Header(alias="X-Inspection-Name")
    ] = None,
    image: Optional[UploadFile] = File(None),
    date_image: Optional[UploadFile] = File(
        None, description="Date image for ocr/datecode-num inspection"
    ),
    include_diag: bool = Query(False),
    YMD_option: Optional[str] = Form(None, description="1=D/M/Y (default), 2=M/D/Y"),
    input_coords: Optional[str] = Form(
        None, description="Cell position '[row,col]' or 'row,col' (ocr/meter-table)"
    ),
    table_size: Optional[str] = Form(
        None, description="Grid dimensions '[rows,cols]' or 'rows,cols' (ocr/meter-table)"
    ),
    permit_image: Optional[UploadFile] = File(
        None, description="Optional permit code image (v2)"
    ),
) -> JSONResponse:
    """Route an image inspection request to the adapter named in X-Inspection-Name."""
    if not x_inspection_name:
        raise HTTPException(
            status_code=422, detail="X-Inspection-Name header is required"
        )

    if x_inspection_name == "ocr/datecode-num":
        if date_image is not None:
            img = await _decode_upload(date_image, "date_image")
        elif image is not None:
            img = await _decode_upload(image, "image")
        else:
            raise HTTPException(
                status_code=422,
                detail="date_image or image field is required for ocr/datecode-num",
            )
    else:
        if image is None:
            raise HTTPException(status_code=422, detail="image field is required")
        img = await _decode_upload(image, "image")

    kwargs: dict = {"include_diag": include_diag}

    if YMD_option is not None:
        kwargs["YMD_option"] = _normalize_ymd_option(YMD_option)

    if input_coords is not None:
        kwargs["input_coords"] = input_coords

    if table_size is not None:
        kwargs["table_size"] = table_size

    if permit_image is not None:
        kwargs["permit_image"] = await _decode_upload(permit_image, "permit_image")

    adapter_class = get_adapter_class(x_inspection_name)
    if adapter_class is not None:
        unexpected = set(kwargs) - adapter_class.accepted_kwargs()
        if unexpected:
            raise HTTPException(
                status_code=422,
                detail=f"Fields not accepted by '{x_inspection_name}': {sorted(unexpected)}",
            )

    try:
        result = await inspection_manager.run(x_inspection_name, img, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(result)
