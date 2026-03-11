from typing import Optional

from pydantic import BaseModel


class InspectResponse(BaseModel):
    """Unified response schema for POST /api/v1/inspect.

    All string fields default to "" rather than None so callers can safely
    check falsy without None-guards. Fields only relevant to specific adapters
    (pcode, pname_*, diag_img) are Optional and default to None.
    """

    # Top-level result code — see InspectionResultCode:
    #   0 = SUCCESS, 1 = INVALID_INPUT, 2 = DETECTION_FAILED
    result: int

    # Primary datecode OCR results
    pred_text: str = ""
    pred_text_b: str = ""
    pred_text_b2: str = ""

    # Formatted date strings (day/month/year components)
    YMD: str = ""
    YMD_b: str = ""
    YMD_b2: str = ""

    # Post-processed / padded text variants
    pred_text_p: str = ""
    pred_text_b_p: str = ""
    pred_text_b2_p: str = ""

    # Permit code (pcode) results — populated when permit_image is provided
    pcode: Optional[str] = None
    pcode_b: Optional[str] = None
    pcode_b2: Optional[str] = None

    # Product name lookup results (v2 only)
    pname_en: Optional[str] = None
    pname_zh: Optional[str] = None

    # Pill-count results
    pill_counts: Optional[int] = None
    centers: Optional[list] = None

    # Diagnostic image: base64-encoded PNG, included when include_diag=true
    diag_img: Optional[str] = None
