#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import glob
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

REQUIRED_MODULES = [
    "omniclaw/__init__.py",
    "omniclaw/cli/__init__.py",
    "omniclaw/cli/app.py",
    "omniclaw/cli_agent.py",
]

EXPECTED_ENTRYPOINTS = {
    "omniclaw": "omniclaw.cli:main",
    "omniclaw-cli": "omniclaw.cli:main",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def verify_wheel_contents(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as zf:
        names = set(zf.namelist())
        missing = [name for name in REQUIRED_MODULES if name not in names]
        if missing:
            fail(f"{wheel_path.name} is missing required files: {', '.join(missing)}")

        entry_points_name = next(
            (name for name in names if name.endswith(".dist-info/entry_points.txt")),
            None,
        )
        if not entry_points_name:
            fail(f"{wheel_path.name} has no entry_points.txt")

        parser = configparser.ConfigParser()
        parser.read_string(zf.read(entry_points_name).decode())
        scripts = (
            dict(parser.items("console_scripts")) if parser.has_section("console_scripts") else {}
        )

        for script_name, target in EXPECTED_ENTRYPOINTS.items():
            actual = scripts.get(script_name)
            if actual != target:
                fail(
                    f"{wheel_path.name} has wrong entrypoint for {script_name}: "
                    f"expected {target!r}, got {actual!r}"
                )

    print(f"OK: wheel structure verified: {wheel_path}")


def smoke_install(wheel_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="omniclaw-wheel-smoke-") as tmpdir:
        venv_dir = Path(tmpdir) / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python_bin = venv_dir / "bin" / "python"
        if not python_bin.exists():
            python_bin = venv_dir / "Scripts" / "python.exe"

        subprocess.run(
            [str(python_bin), "-m", "pip", "install", "--quiet", "--no-deps", str(wheel_path)],
            check=True,
        )
        subprocess.run(
            [
                str(python_bin),
                "-c",
                "import pathlib, sysconfig; "
                "site = pathlib.Path(sysconfig.get_paths()['purelib']); "
                "required = [site / 'omniclaw' / '__init__.py', "
                "site / 'omniclaw' / 'cli' / '__init__.py', "
                "site / 'omniclaw' / 'cli' / 'app.py', "
                "site / 'omniclaw' / 'cli_agent.py']; "
                "missing = [str(p) for p in required if not p.exists()]; "
                "assert not missing, f'missing installed files: {missing}'; "
                "print('install-layout-ok')",
            ],
            check=True,
        )

    print(f"OK: smoke install verified: {wheel_path}")


def download_from_pypi(version: str) -> Path:
    with tempfile.TemporaryDirectory(prefix="omniclaw-pypi-download-") as tmpdir:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "-d",
                tmpdir,
                f"omniclaw=={version}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        candidates = [Path(p) for p in glob.glob(os.path.join(tmpdir, f"omniclaw-{version}*.whl"))]
        if not candidates:
            fail(f"Could not download omniclaw=={version} from PyPI")
        target = Path(tempfile.mkdtemp(prefix="omniclaw-pypi-wheel-")) / candidates[0].name
        target.write_bytes(candidates[0].read_bytes())
        return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify OmniClaw release artifacts.")
    parser.add_argument("wheel", nargs="?", help="Path to a wheel file to verify")
    parser.add_argument(
        "--download-version",
        help="Download omniclaw==VERSION from PyPI and verify that exact published wheel",
    )
    parser.add_argument(
        "--skip-smoke-install",
        action="store_true",
        help="Skip clean-room installation/import verification",
    )
    args = parser.parse_args()

    if bool(args.wheel) == bool(args.download_version):
        fail("Provide exactly one of: WHEEL_PATH or --download-version VERSION")

    if args.download_version:
        wheel_path = download_from_pypi(args.download_version)
    else:
        wheel_path = Path(args.wheel).resolve()
        if not wheel_path.is_file():
            fail(f"Wheel not found: {wheel_path}")

    verify_wheel_contents(wheel_path)
    if not args.skip_smoke_install:
        smoke_install(wheel_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
