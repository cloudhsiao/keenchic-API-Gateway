from abc import ABC, abstractmethod

import numpy as np


class InspectionAdapter(ABC):
    """Abstract base class for all inspection module adapters.

    Concrete adapters wrap a specific inference engine (e.g. datecode_num_st)
    and are registered in keenchic/inspections/registry.py.
    """

    @classmethod
    def accepted_kwargs(cls) -> set[str]:
        """Return the set of kwargs accepted by this adapter's run() method.

        Override in subclasses to declare inspection-specific fields.
        The router uses this to reject unexpected fields with HTTP 422.
        """
        return {"include_diag"}

    @abstractmethod
    def load_models(self, backend: str) -> None:
        """Load all required model weights for the given backend.

        Args:
            backend: "openvino" for CPU inference, "tensorrt" for GPU inference.
        """

    @abstractmethod
    def unload_models(self) -> None:
        """Release all loaded model objects and free memory."""

    @abstractmethod
    def run(self, image: np.ndarray, **kwargs) -> dict:
        """Execute inference on the given image.

        Args:
            image: BGR numpy array (HxWx3, uint8) decoded from the upload.
            **kwargs: adapter-specific parameters (e.g. YMD_option, include_diag).

        Returns:
            dict with at minimum {"result": int}. Additional fields depend on
            the adapter (pred_text, YMD, pcode, diag_img, etc.).
        """
