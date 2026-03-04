from enum import IntEnum


class InspectionResultCode(IntEnum):
    SUCCESS = 0           # Inference succeeded
    INVALID_INPUT = 1     # Invalid/missing input (null image, etc.)
    DETECTION_FAILED = 2  # Could not detect/recognize target in image
