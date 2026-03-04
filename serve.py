import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Keenchic API Gateway")
    parser.add_argument(
        "--backend",
        choices=["gpu", "cpu", "auto"],
        default=None,
        help=(
            "Inference backend: gpu (TensorRT with OV fallback), "
            "cpu (OpenVINO only), auto. "
            "Overrides KEENCHIC_BACKEND env var."
        ),
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.backend is not None:
        os.environ["KEENCHIC_BACKEND"] = args.backend.upper()

    uvicorn.run("main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
