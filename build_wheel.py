#!/usr/bin/env python3
"""Build keenchic-API-Gateway wheel with Cython-compiled .so files.

Compiles Python source to C++ shared libraries using Cython, then packages
everything (compiled .so, kept .py, model weights) into a .whl file.

Algorithm selection is driven by *.build.toml descriptor files co-located
with each adapter. Adding a new algorithm requires only a new descriptor —
this file needs no modification.

Usage (on Jetson Orin):
    pip install cython setuptools wheel numpy
    python3 build_wheel.py                              # all algorithms
    python3 build_wheel.py --list                       # list available
    python3 build_wheel.py -a ocr/datecode-num          # single algorithm
    python3 build_wheel.py -a ocr/datecode-num -a ocr/pill-count  # subset

Output:
    dist/keenchic_api_gateway-<version>-cp3<minor>-cp3<minor>-linux_aarch64.whl
    dist/keenchic_api_gateway-<version>+<algo_tag>-...-linux_aarch64.whl  (subset)
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
BUILD_DIR = PROJECT_ROOT / "_build"
DIST_DIR = PROJECT_ROOT / "dist"

VERSION = "0.1.0"
BASE_PACKAGE_NAME = "keenchic-api-gateway"

DESCRIPTOR_GLOB = "keenchic/inspections/adapters/**/*.build.toml"

# Core modules always included regardless of algorithm selection
CORE_CYTHON: dict[str, str] = {
    "keenchic.core.inspection_manager": "keenchic/core/inspection_manager.py",
    "keenchic.core.logging":            "keenchic/core/logging.py",
    "keenchic.inspections.base":        "keenchic/inspections/base.py",
    "keenchic.inspections.registry":    "keenchic/inspections/registry.py",
    "keenchic.inspections.result_codes": "keenchic/inspections/result_codes.py",
    "keenchic.api.deps":                "keenchic/api/deps.py",
    "keenchic.services.permit_lookup":  "keenchic/services/permit_lookup.py",
}

CORE_KEEP_PY: list[str] = [
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

# Runtime dependencies (excluding openvino — not supported on aarch64)
# Pre-installed on Jetson (JetPack 6.x), NOT listed here:
#   matplotlib, opencv-python, tensorrt
INSTALL_REQUIRES: list[str] = [
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
# Descriptor data model
# ---------------------------------------------------------------------------

@dataclass
class SubmoduleEntry:
    name: str
    src: str


@dataclass
class SubmoduleSpec:
    dir: Path
    dotted: list[SubmoduleEntry] = field(default_factory=list)
    bare: list[SubmoduleEntry] = field(default_factory=list)
    weights_subdir: str | None = None

    @property
    def weights_path(self) -> Path | None:
        if self.weights_subdir:
            return self.dir / self.weights_subdir
        return None


@dataclass
class AlgoSpec:
    inspection_name: str
    adapter_source: str
    cython: bool
    submodules: list[SubmoduleSpec]


# ---------------------------------------------------------------------------
# Build plan
# ---------------------------------------------------------------------------

@dataclass
class CompilePlan:
    keenchic_cython: dict[str, str]
    dotted_groups: list[dict]
    bare_groups: list[dict]
    keep_py: list[str]
    weight_dirs: list[str]
    init_dirs: list[str]


# ---------------------------------------------------------------------------
# Discovery and selection
# ---------------------------------------------------------------------------

def discover_descriptors() -> dict[str, AlgoSpec]:
    """Load all *.build.toml descriptors; return {inspection_name: AlgoSpec}."""
    specs: dict[str, AlgoSpec] = {}
    for toml_path in sorted(PROJECT_ROOT.glob(DESCRIPTOR_GLOB)):
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)

        name: str = data.get("inspection_name", "")
        if not name:
            print(f"ERROR: {toml_path} is missing 'inspection_name'")
            sys.exit(1)

        adapter_cfg = data.get("adapter", {})
        adapter_src: str = adapter_cfg.get("source", "")
        cython: bool = adapter_cfg.get("cython", True)

        if not adapter_src or not (PROJECT_ROOT / adapter_src).exists():
            print(f"ERROR: [{name}] adapter source not found: {adapter_src!r}")
            sys.exit(1)

        submodules: list[SubmoduleSpec] = []
        for sm in data.get("submodule", []):
            sm_dir = PROJECT_ROOT / sm["dir"]
            if not sm_dir.is_dir():
                print(f"ERROR: [{name}] submodule dir not found: {sm['dir']!r}")
                sys.exit(1)
            submodules.append(SubmoduleSpec(
                dir=sm_dir,
                dotted=[SubmoduleEntry(e["name"], e["src"]) for e in sm.get("dotted", [])],
                bare=[SubmoduleEntry(e["name"], e["src"]) for e in sm.get("bare", [])],
                weights_subdir=sm.get("weights_subdir"),
            ))

        specs[name] = AlgoSpec(
            inspection_name=name,
            adapter_source=adapter_src,
            cython=cython,
            submodules=submodules,
        )

    if not specs:
        print(f"ERROR: no descriptors found matching {DESCRIPTOR_GLOB!r}")
        sys.exit(1)

    return specs


def select_algorithms(specs: dict[str, AlgoSpec], cli_names: list[str]) -> dict[str, AlgoSpec]:
    """Filter specs by CLI names; empty list returns all."""
    if not cli_names:
        return specs

    invalid = [n for n in cli_names if n not in specs]
    if invalid:
        print(f"ERROR: Unknown algorithm(s): {', '.join(invalid)}")
        print(f"Available: {', '.join(sorted(specs))}")
        sys.exit(1)

    return {n: specs[n] for n in cli_names}


def compile_plan(selected: dict[str, AlgoSpec]) -> CompilePlan:
    """Derive a CompilePlan from the selected AlgoSpecs."""
    keenchic_cython = dict(CORE_CYTHON)
    keep_py = list(CORE_KEEP_PY)
    weight_dirs: list[str] = []

    dotted_seen: set[tuple[str, str]] = set()
    bare_seen: set[tuple[str, str]] = set()
    dotted_by_cwd: dict[str, dict[str, str]] = {}
    bare_by_cwd: dict[str, dict[str, str]] = {}
    init_dirs_set: set[str] = set()

    for spec in selected.values():
        dotted_module_name = spec.adapter_source.replace("/", ".").removesuffix(".py")
        if spec.cython:
            keenchic_cython[dotted_module_name] = spec.adapter_source
        else:
            keep_py.append(spec.adapter_source)

        for sm in spec.submodules:
            dir_rel = sm.dir.relative_to(PROJECT_ROOT)
            dir_str = str(dir_rel)
            parent_str = str(dir_rel.parent)

            init_dirs_set.add(parent_str)
            init_dirs_set.add(dir_str)

            # Dotted modules: compiled from parent dir (e.g. ocr/) so the
            # .so lands inside the submodule package dir.
            for entry in sm.dotted:
                key = (parent_str, entry.name)
                if key not in dotted_seen:
                    dotted_seen.add(key)
                    src_from_parent = dir_rel.name + "/" + entry.src
                    dotted_by_cwd.setdefault(parent_str, {})[entry.name] = src_from_parent

            # Bare modules: compiled from the submodule dir itself.
            for entry in sm.bare:
                key = (dir_str, entry.name)
                if key not in bare_seen:
                    bare_seen.add(key)
                    bare_by_cwd.setdefault(dir_str, {})[entry.name] = entry.src

            if sm.weights_path and sm.weights_path.is_dir():
                w_rel = str(sm.weights_path.relative_to(PROJECT_ROOT))
                if w_rel not in weight_dirs:
                    weight_dirs.append(w_rel)

    return CompilePlan(
        keenchic_cython=keenchic_cython,
        dotted_groups=[{"cwd": cwd, "extensions": exts} for cwd, exts in dotted_by_cwd.items()],
        bare_groups=[{"cwd": cwd, "extensions": exts} for cwd, exts in bare_by_cwd.items()],
        keep_py=keep_py,
        weight_dirs=weight_dirs,
        init_dirs=sorted(init_dirs_set),
    )


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
    run(
        [sys.executable, setup_file.name, "build_ext", "--inplace"],
        cwd=cwd,
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

    for pkg in ("Cython", "setuptools", "wheel", "numpy"):
        try:
            __import__(pkg)
        except ImportError:
            print(f"ERROR: {pkg} not installed. Run: pip install cython setuptools wheel numpy")
            sys.exit(1)


def copy_to_staging(plan: CompilePlan) -> None:
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

    for src_rel in plan.keenchic_cython.values():
        _copy(src_rel)

    for src_rel in plan.keep_py:
        _copy(src_rel)

    for group in plan.dotted_groups:
        cwd = group["cwd"]
        for src_rel in group["extensions"].values():
            _copy(os.path.join(cwd, src_rel))

    for group in plan.bare_groups:
        cwd = group["cwd"]
        for src_rel in group["extensions"].values():
            _copy(os.path.join(cwd, src_rel))

    for weight_dir in plan.weight_dirs:
        src_dir = PROJECT_ROOT / weight_dir
        dst_dir = BUILD_DIR / weight_dir
        if src_dir.exists():
            shutil.copytree(src_dir, dst_dir)

    for init_dir in plan.init_dirs:
        init_path = BUILD_DIR / init_dir / "__init__.py"
        init_path.parent.mkdir(parents=True, exist_ok=True)
        if not init_path.exists():
            init_path.write_text("")

    print(f"  Staging directory: {BUILD_DIR}")


def compile_keenchic_modules(plan: CompilePlan) -> None:
    """Compile keenchic.* modules with Cython (dotted module names)."""
    print("\n[2/6] Compiling keenchic.* modules...")
    setup_file = _write_compile_setup(BUILD_DIR, plan.keenchic_cython)
    _run_build_ext(setup_file, BUILD_DIR)


def compile_submodule_dotted(plan: CompilePlan) -> None:
    """Compile submodule files imported with dotted names."""
    if not plan.dotted_groups:
        print("\n[3/6] No dotted submodule modules to compile, skipping.")
        return

    print("\n[3/6] Compiling submodule dotted modules...")
    for group in plan.dotted_groups:
        cwd = BUILD_DIR / group["cwd"]
        print(f"  Directory: {group['cwd']}")
        setup_file = _write_compile_setup(cwd, group["extensions"])
        _run_build_ext(setup_file, cwd)


def compile_submodule_bare(plan: CompilePlan) -> None:
    """Compile submodule files imported with bare names."""
    if not plan.bare_groups:
        print("\n[4/6] No bare submodule modules to compile, skipping.")
        return

    print("\n[4/6] Compiling submodule bare modules...")
    for group in plan.bare_groups:
        cwd = BUILD_DIR / group["cwd"]
        print(f"  Directory: {group['cwd']}")
        setup_file = _write_compile_setup(cwd, group["extensions"])
        _run_build_ext(setup_file, cwd)


def cleanup_staging(plan: CompilePlan) -> None:
    """Remove .py source for compiled modules and build intermediates."""
    print("\n[5/6] Cleaning staging directory...")
    removed = 0

    for src_rel in plan.keenchic_cython.values():
        py_file = BUILD_DIR / src_rel
        if py_file.exists():
            py_file.unlink()
            removed += 1

    for group in plan.dotted_groups:
        cwd = group["cwd"]
        for src_rel in group["extensions"].values():
            py_file = BUILD_DIR / cwd / src_rel
            if py_file.exists():
                py_file.unlink()
                removed += 1

    for group in plan.bare_groups:
        cwd = group["cwd"]
        for src_rel in group["extensions"].values():
            py_file = BUILD_DIR / cwd / src_rel
            if py_file.exists():
                py_file.unlink()
                removed += 1

    for pattern in ("**/*.c", "**/*.cpp", "**/*.html"):
        for f in BUILD_DIR.glob(pattern):
            f.unlink()
            removed += 1

    print(f"  Removed {removed} files")


def _version_tag(selected_names: list[str], all_names: set[str]) -> str:
    """Return version string; adds PEP 440 local tag for subset builds."""
    if set(selected_names) == all_names:
        return VERSION

    def slugify(n: str) -> str:
        return n.replace("/", "_").replace("-", "_")

    local = ".".join(slugify(n) for n in sorted(selected_names))
    return f"{VERSION}+{local}"


def build_wheel(plan: CompilePlan, selected_names: list[str], all_names: set[str]) -> None:
    """Generate setup.py for packaging and build the wheel."""
    print("\n[6/6] Building wheel...")

    version = _version_tag(selected_names, all_names)

    packages = sorted(
        str(init.parent.relative_to(BUILD_DIR)).replace(os.sep, ".")
        for init in BUILD_DIR.glob("**/__init__.py")
    )

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
            name="{BASE_PACKAGE_NAME}",
            version="{version}",
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
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build keenchic-API-Gateway wheel (descriptor-driven, Cython + weights).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              python3 build_wheel.py                          # all algorithms
              python3 build_wheel.py --list                   # list available
              python3 build_wheel.py -a ocr/datecode-num      # single algorithm
              python3 build_wheel.py -a ocr/datecode-num \\
                                     -a ocr/pill-count        # subset
        """),
    )
    p.add_argument(
        "-a", "--algorithm",
        action="append",
        default=[],
        metavar="NAME",
        help="Inspection name to include (repeatable). Default: all discovered.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List discovered algorithms and exit.",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    specs = discover_descriptors()

    if args.list:
        print("Available algorithms:")
        for name in sorted(specs):
            print(f"  {name}")
        return

    selected = select_algorithms(specs, args.algorithm)
    validate_env()

    print(f"\nBuilding {BASE_PACKAGE_NAME} v{VERSION}")
    print(f"Algorithms ({len(selected)}): {', '.join(sorted(selected))}")
    print("=" * 60)

    plan = compile_plan(selected)
    copy_to_staging(plan)
    compile_keenchic_modules(plan)
    compile_submodule_dotted(plan)
    compile_submodule_bare(plan)
    cleanup_staging(plan)
    build_wheel(plan, list(selected), set(specs))

    shutil.rmtree(BUILD_DIR)

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
