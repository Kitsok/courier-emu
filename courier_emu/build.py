"""Explicit build and dependency checks for the native analog runtime."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig


def packaged_library(filename: str) -> Path | None:
    """Installed packages contain prebuilt cores, never compiler inputs."""
    root = Path(__file__).resolve().parent.parent
    marker = root / "runtime.json"
    if not marker.exists():
        return None
    metadata = json.loads(marker.read_text())
    if metadata.get("python_abi") != sys.implementation.cache_tag:
        raise RuntimeError("packaged runtime uses a different Python ABI; rebuild the Debian package")
    library = root / "lib" / filename
    if not library.is_file():
        raise RuntimeError(f"packaged native component is missing: {library}; reinstall the package")
    return library


def require_build_allowed(path: Path) -> None:
    if os.environ.get("COURIER_EMU_NO_BUILD") == "1":
        raise RuntimeError(f"native component is missing or stale: {path}; run ./build.sh")


def missing_dependencies() -> list[str]:
    missing = []
    if sys.version_info < (3, 10):
        missing.append("Python 3.10 or later (Debian: python3)")
    if shutil.which("c++") is None:
        missing.append("C++17 compiler (Debian: g++ or build-essential)")
    if not Path(sysconfig.get_path("include"), "Python.h").is_file():
        missing.append("headers for the selected Python interpreter (Debian: python3-dev)")
    return missing


def check_firmware() -> None:
    from .boot_rom import mask_rom
    from .cli import build_parser
    from .profiles import resolve_run_profile

    args = build_parser().parse_args(["run", "--profile", "analog403"])
    resolve_run_profile(args)
    mask_rom()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="check prerequisites and firmware without building")
    args = parser.parse_args(argv)
    missing = missing_dependencies()
    if missing:
        print("Missing build prerequisites:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        return 1
    try:
        check_firmware()
        if args.check_only:
            print("Analog Courier build prerequisites and firmware: OK")
            return 0
        # The build command, unlike the service, explicitly permits compilation.
        os.environ.pop("COURIER_EMU_NO_BUILD", None)
        if os.environ.get("COURIER_C5X_LIBRARY"):
            raise ValueError("unset COURIER_C5X_LIBRARY to build the project runtime")
        from . import dsp, x86_native

        print("Building the native 80186 interpreter...", flush=True)
        path = x86_native.build_library()
        spec = importlib.util.spec_from_file_location("_x86_native", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print("Building the native C5x DSP library...", flush=True)
        dsp.load_library()
        print("Analog Courier build complete; native libraries loaded successfully.")
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.CalledProcessError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
