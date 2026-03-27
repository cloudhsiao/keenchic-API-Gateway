#!/usr/bin/env python3
"""Build keenchic-API-Gateway wheel with Cython-compiled .so files.

Compiles Python source to C++ shared libraries using Cython, then packages
everything (compiled .so, kept .py, model weights) into a .whl file.

Usage (on Jetson Orin):
    pip install cython setuptools wheel numpy
    python3 build_wheel.py

Output:
    dist/keenchic_api_gateway-<version>-cp3<minor>-cp3<minor>-linux_aarch64.whl
"""

import os
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
BUILD_DIR = PROJECT_ROOT / "_build"
DIST_DIR = PROJECT_ROOT / "dist"

VERSION = "0.1.0"
PACKAGE_NAME = "keenchic-api-gateway"

# keenchic.* modules to Cython compile (dotted name -> source path)
KEENCHIC_CYTHON = {
    "keenchic.core.inspection_manager": "keenchic/core/inspection_manager.py",
    "keenchic.core.logging": "keenchic/core/logging.py",
    "keenchic.inspections.base": "keenchic/inspections/base.py",
    "keenchic.inspections.registry": "keenchic/inspections/registry.py",
    "keenchic.inspections.result_codes": "keenchic/inspections/result_codes.py",
    "keenchic.inspections.adapters.ocr.datecode_num": "keenchic/inspections/adapters/ocr/datecode_num.py",
    "keenchic.inspections.adapters.ocr.pill_count": "keenchic/inspections/adapters/ocr/pill_count.py",
    "keenchic.api.deps": "keenchic/api/deps.py",
    "keenchic.services.permit_lookup": "keenchic/services/permit_lookup.py",
}

# Submodule files compiled as dotted modules (adapter uses: from datecode_num_st.xxx import ...)
# These are compiled from the ocr/ directory so setuptools places .so in datecode_num_st/
SUBMODULE_DOTTED = {
    "cwd": "keenchic/inspections/ocr",
    "extensions": {
        "datecode_num_st.procd_date": "datecode_num_st/procd_date.py",
        "datecode_num_st.model_detect_trt": "datecode_num_st/model_detect_trt.py",
    },
}

# Submodule files compiled with bare module names
# - datecode_num_st/utils.py: only bare-imported internally (from utils import *)
# - pill_count_st/*: adapter uses bare imports (import procd_pill, from model_trt_yolo import ...)
SUBMODULE_BARE = [
    {
        "cwd": "keenchic/inspections/ocr/datecode_num_st",
        "extensions": {
            "utils": "utils.py",
        },
    },
    {
        "cwd": "keenchic/inspections/ocr/pill_count_st",
        "extensions": {
            "procd_pill": "procd_pill.py",
            "model_trt_yolo": "model_trt_yolo.py",
            "utils": "utils.py",
        },
    },
]

# .py files kept as-is (not compiled)
KEEP_PY = [
    "main.py",
    "serve.py",
    "keenchic/__init__.py",
    "keenchic/core/__init__.py",
    "keenchic/core/config.py",
    "keenchic/api/__init__.py",
    "keenchic/api/router.py",
    "keenchic/schemas/__init__.py",
    "keenchic/schemas/response.py",
    "keenchic/inspections/__init__.py",
    "keenchic/inspections/adapters/__init__.py",
    "keenchic/inspections/adapters/ocr/__init__.py",
    "keenchic/services/__init__.py",
]

# Weight directories to include
WEIGHT_DIRS = [
    "keenchic/inspections/ocr/datecode_num_st/weights",
    "keenchic/inspections/ocr/pill_count_st/weights",
]

# Runtime dependencies (excluding openvino — not supported on aarch64)
# Pre-installed on Jetson (JetPack 6.x), NOT listed here:
#   matplotlib, opencv-python, tensorrt
INSTALL_REQUIRES = [
    "fastapi>=0.119.0",
    "numpy<2.0.0",
    "pycuda>=2026.1",
    "pydantic-settings>=2.0.0",
    "python-multipart>=0.0.9",
    "scikit-image>=0.25.0",
    "scikit-learn>=1.4.0",
    "structlog>=24.0.0",
    "uvicorn[standard]>=0.37.0",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(cmd: list[str], **kwargs) -> None:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True, **kwargs)


def _write_compile_setup(dest: Path, extensions: dict[str, str]) -> Path:
    """Write a temporary setup.py for Cython compilation."""
    ext_lines = []
    for mod_name, src_path in extensions.items():
        ext_lines.append(
            f'        Extension("{mod_name}", ["{src_path}"], language="c++"),'
        )
    ext_block = "\n".join(ext_lines)

    content = (
        "from setuptools import setup, Extension\n"
        "from Cython.Build import cythonize\n"
        "\n"
        "setup(\n"
        "    ext_modules=cythonize([\n"
        f"{ext_block}\n"
        '    ], compiler_directives={"language_level": "3"}),\n'
        ")\n"
    )
    setup_file = dest / "_cython_build.py"
    setup_file.write_text(content)
    return setup_file


def _run_build_ext(setup_file: Path, cwd: Path) -> None:
    """Run build_ext --inplace and clean up build artifacts."""
    env = {**os.environ, "SETUPTOOLS_USE_DISTUTILS": "stdlib"}
    run(
        [sys.executable, setup_file.name, "build_ext", "--inplace"],
        cwd=cwd,
        env=env,
    )
    setup_file.unlink()
    shutil.rmtree(cwd / "build", ignore_errors=True)


# ---------------------------------------------------------------------------
# Build stages
# ---------------------------------------------------------------------------


def validate_env() -> None:
    """Check the build environment."""
    arch = platform.machine()
    if arch != "aarch64":
        print(f"WARNING: expected aarch64, got {arch}. Wheel tag will reflect this platform.")

    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(f"Python {py} on {arch}")

    # Check required build tools
    for pkg in ("Cython", "setuptools", "wheel", "numpy"):
        try:
            __import__(pkg)
        except ImportError:
            print(f"ERROR: {pkg} not installed. Run: pip install cython setuptools wheel numpy")
            sys.exit(1)


def copy_to_staging() -> None:
    """Copy needed source files to the staging directory."""
    print("\n[1/6] Copying source files to staging directory...")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir()

    def _copy(src_rel: str) -> None:
        src = PROJECT_ROOT / src_rel
        dst = BUILD_DIR / src_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # keenchic.* modules to compile
    for src_rel in KEENCHIC_CYTHON.values():
        _copy(src_rel)

    # .py files to keep
    for src_rel in KEEP_PY:
        _copy(src_rel)

    # Submodule dotted modules
    for src_rel in SUBMODULE_DOTTED["extensions"].values():
        _copy(os.path.join(SUBMODULE_DOTTED["cwd"], src_rel))

    # Submodule bare modules
    for group in SUBMODULE_BARE:
        for src_rel in group["extensions"].values():
            _copy(os.path.join(group["cwd"], src_rel))

    # Weight files
    for weight_dir in WEIGHT_DIRS:
        src_dir = PROJECT_ROOT / weight_dir
        dst_dir = BUILD_DIR / weight_dir
        if src_dir.exists():
            shutil.copytree(src_dir, dst_dir)

    # Create __init__.py for submodule dirs (required for packaging)
    for init_dir in [
        "keenchic/inspections/ocr",
        "keenchic/inspections/ocr/datecode_num_st",
        "keenchic/inspections/ocr/pill_count_st",
    ]:
        init_path = BUILD_DIR / init_dir / "__init__.py"
        init_path.parent.mkdir(parents=True, exist_ok=True)
        if not init_path.exists():
            init_path.write_text("")

    print(f"  Staging directory: {BUILD_DIR}")


def compile_keenchic_modules() -> None:
    """Compile keenchic.* modules with Cython (dotted module names)."""
    print("\n[2/6] Compiling keenchic.* modules...")
    setup_file = _write_compile_setup(BUILD_DIR, KEENCHIC_CYTHON)
    _run_build_ext(setup_file, BUILD_DIR)


def compile_submodule_dotted() -> None:
    """Compile submodule files imported with dotted names (from datecode_num_st.xxx import ...)."""
    print("\n[3/6] Compiling submodule dotted modules (datecode_num_st.*)...")
    cwd = BUILD_DIR / SUBMODULE_DOTTED["cwd"]
    setup_file = _write_compile_setup(cwd, SUBMODULE_DOTTED["extensions"])
    _run_build_ext(setup_file, cwd)


def compile_submodule_bare() -> None:
    """Compile submodule files imported with bare names (import procd_pill, from utils import *)."""
    print("\n[4/6] Compiling submodule bare modules...")
    for group in SUBMODULE_BARE:
        cwd = BUILD_DIR / group["cwd"]
        print(f"  Directory: {group['cwd']}")
        setup_file = _write_compile_setup(cwd, group["extensions"])
        _run_build_ext(setup_file, cwd)


def cleanup_staging() -> None:
    """Remove .py source for compiled modules and build intermediates."""
    print("\n[5/6] Cleaning staging directory...")
    removed = 0

    # Remove .py for compiled keenchic.* modules
    for src_rel in KEENCHIC_CYTHON.values():
        py_file = BUILD_DIR / src_rel
        if py_file.exists():
            py_file.unlink()
            removed += 1

    # Remove .py for compiled submodule dotted modules
    for src_rel in SUBMODULE_DOTTED["extensions"].values():
        py_file = BUILD_DIR / SUBMODULE_DOTTED["cwd"] / src_rel
        if py_file.exists():
            py_file.unlink()
            removed += 1

    # Remove .py for compiled submodule bare modules
    for group in SUBMODULE_BARE:
        for src_rel in group["extensions"].values():
            py_file = BUILD_DIR / group["cwd"] / src_rel
            if py_file.exists():
                py_file.unlink()
                removed += 1

    # Remove C/C++ intermediates and Cython annotation HTML
    for pattern in ("**/*.c", "**/*.cpp", "**/*.html"):
        for f in BUILD_DIR.glob(pattern):
            f.unlink()
            removed += 1

    print(f"  Removed {removed} files")


def build_wheel() -> None:
    """Generate setup.py for packaging and build the wheel."""
    print("\n[6/6] Building wheel...")

    # Discover all packages (directories with __init__.py)
    packages = sorted(
        str(init.parent.relative_to(BUILD_DIR)).replace(os.sep, ".")
        for init in BUILD_DIR.glob("**/__init__.py")
    )

    # Build package_data: .so files and weight files per package
    package_data: dict[str, list[str]] = {}
    for pkg in packages:
        pkg_dir = BUILD_DIR / pkg.replace(".", os.sep)
        patterns = []
        if any(pkg_dir.glob("*.so")):
            patterns.append("*.so")
        if (pkg_dir / "weights").is_dir():
            patterns.append("weights/*")
        if patterns:
            package_data[pkg] = patterns

    setup_content = textwrap.dedent(f"""\
        from setuptools import setup
        from setuptools.dist import Distribution as _Distribution


        class BinaryDistribution(_Distribution):
            \"\"\"Force platform-specific wheel (not pure-python).\"\"\"
            def has_ext_modules(self):
                return True


        setup(
            name="{PACKAGE_NAME}",
            version="{VERSION}",
            python_requires=">=3.10",
            py_modules=["main", "serve"],
            packages={packages!r},
            package_data={package_data!r},
            install_requires={INSTALL_REQUIRES!r},
            entry_points={{
                "console_scripts": ["keenchic-serve=serve:main"],
            }},
            distclass=BinaryDistribution,
        )
    """)
    (BUILD_DIR / "setup.py").write_text(setup_content)

    # Minimal pyproject.toml so pip uses setuptools
    (BUILD_DIR / "pyproject.toml").write_text(textwrap.dedent("""\
        [build-system]
        requires = ["setuptools", "wheel"]
        build-backend = "setuptools.build_meta"
    """))

    DIST_DIR.mkdir(exist_ok=True)
    run(
        [
            sys.executable, "-m", "pip", "wheel",
            "--no-deps", "--no-build-isolation",
            "-w", str(DIST_DIR), ".",
        ],
        cwd=BUILD_DIR,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    validate_env()
    print(f"\nBuilding {PACKAGE_NAME} v{VERSION}")
    print("=" * 60)

    copy_to_staging()
    compile_keenchic_modules()
    compile_submodule_dotted()
    compile_submodule_bare()
    cleanup_staging()
    build_wheel()

    # Clean up staging
    shutil.rmtree(BUILD_DIR)

    # Report
    print("\n" + "=" * 60)
    wheels = sorted(DIST_DIR.glob("keenchic_api_gateway-*.whl"))
    if wheels:
        whl = wheels[-1]
        size_mb = whl.stat().st_size / 1024 / 1024
        print(f"Wheel built: {whl.name}")
        print(f"Size: {size_mb:.1f} MB")
        print(f"Location: {whl}")
    else:
        print("ERROR: no wheel file found in dist/")
        sys.exit(1)


if __name__ == "__main__":
    main()
