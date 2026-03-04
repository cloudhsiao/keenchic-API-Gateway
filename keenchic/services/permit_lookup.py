import json
from io import BytesIO
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

DATA_URL = (
    "https://data.fda.gov.tw/opendata/exportDataList.do"
    "?method=ExportData&InfoId=39&logType=5"
)

_permit_cache: List[Dict[str, Optional[str]]] = []


def _load_permit_data() -> List[Dict[str, Optional[str]]]:
    """Download permit data from FDA open data and return simplified dicts."""
    try:
        with urlopen(DATA_URL) as response:
            content = response.read()
    except (URLError, HTTPError) as exc:
        print(f"Failed to load permit data: {exc}")
        return []

    try:
        with ZipFile(BytesIO(content)) as zf:
            json_name = next((name for name in zf.namelist() if name.endswith(".json")), None)
            if not json_name:
                print("Permit data zip does not contain a JSON file.")
                return []
            text = zf.read(json_name).decode("utf-8", errors="replace")
    except BadZipFile:
        text = content.decode("utf-8", errors="replace")

    try:
        raw_data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"Failed to parse permit data: {exc}")
        return []

    cache: List[Dict[str, Optional[str]]] = []
    for record in raw_data:
        if not isinstance(record, dict):
            continue
        cache.append(
            {
                "license_number": record.get("許可證字號"),
                "product_name_en": record.get("英文品名"),
                "product_name_zh": record.get("中文品名"),
            }
        )

    return cache


def get_product_by_pcode(pcode: str) -> Optional[Dict[str, Optional[str]]]:
    """Return permit details for a given pcode from the in-memory cache.

    Performs a lazy reload if the cache is empty (e.g. first call after a
    failed startup download).

    Args:
        pcode: partial or full permit code string to search for.

    Returns:
        First matching record dict, or None if not found.
    """
    if not _permit_cache:
        _permit_cache[:] = _load_permit_data()

    for record in _permit_cache:
        license_number = record.get("license_number") or ""
        if pcode in license_number:
            return record

    return None


# Pre-warm the cache when the module is first imported.
_permit_cache[:] = _load_permit_data()
