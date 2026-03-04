from typing import Annotated, Optional

from fastapi import Header, HTTPException

from keenchic.core.config import settings


async def require_api_key(x_api_key: Annotated[Optional[str], Header(alias="X-API-KEY")] = None) -> None:
    """FastAPI Dependency that validates the X-API-KEY request header.

    Raises:
        HTTPException 500: if KEENCHIC_API_KEY env var is not configured.
        HTTPException 401: if the header is missing or does not match.
    """
    if not settings.KEENCHIC_API_KEY:
        raise HTTPException(status_code=500, detail="API not configured: KEENCHIC_API_KEY not set")
    if x_api_key is None or x_api_key != settings.KEENCHIC_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
