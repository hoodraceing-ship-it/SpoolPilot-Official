"""Windows Proxmark client discovery, self-repair, and launch helpers for SpoolPilot."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
from pathlib import Path
from typing import Callable, Iterable


PROXMARK_BUILD_URL = "https://www.proxmarkbuilds.org/latest/rrg_other.php"
USER_AGENT = "SpoolPilotTagWriter-client-repair"
_ENV_CACHE: dict[str, dict[str, str]] = {}


def find_client_executable(client_directory: Path) -> Path | None:
    """Find the native Proxmark3 client executable in a selected client folder."""
    directory = Path(client_directory)
    for candidate in (
        directory / "proxmark3.exe",
        directory / "proxmark3",
        directory / "client" / "proxmark3.exe",
        directory / "client" / "proxmark3",
    ):
        if candidate.is_file():
            return candidate
    return None


def missing_client_items(client_directory: Path) -> list[str]:
    """Return the pieces SpoolPilot needs from an RRG Windows client folder."""
    directory = Path(client_directory)
    if not directory.is_dir():
        return ["client folder"]

    missing: list[str] = []
    if not (directory / "setup.bat").is_file():
        missing.append("setup.bat")
    if not (directory / "pm3").is_file():
        missing.append("pm3 launcher")
    if find_client_executable(directory) is None:
        missing.append("proxmark3.exe")
    return missing


def find_client_root(root: Path) -> Path | None:
    """Locate the usable client directory inside an extracted RRG package."""
    root = Path(root)
    if not missing_client_items(root):
        return root
    if not root.exists():
        return None

    candidates: list[Path] = []
    try:
        setup_files = list(root.rglob("setup.bat"))
    except OSError:
        setup_files = []
    for setup_file in setup_files:
        parent = setup_file.parent
        if not missing_client_items(parent):
            candidates.append(parent)
    if not candidates:
        return None
    candidates.sort(key=lambda value: (len(value.parts), str(value).casefold()))
    return candidates[0]


def managed_client_root(app_dir: Path) -> Path | None:
    return find_client_root(Path(app_dir) / "proxmark")


def _download(url: str, destination: Path, status: Callable[[str], None]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    downloaded = 0
    next_report = 25 * 1024 * 1024
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with temporary.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= next_report:
                        status(f"Downloading Proxmark client… {downloaded // (1024 * 1024)} MB")
                        next_report += 25 * 1024 * 1024
        if downloaded < 1024:
            raise RuntimeError("The Proxmark client download was unexpectedly small")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def install_managed_client(app_dir: Path, status: Callable[[str], None]) -> Path:
    """Install a clean RRG generic Windows client under SpoolPilot AppData.

    The RRG Windows documentation points users to proxmarkbuilds.org for current
    precompiled binaries.  SpoolPilot installs the package into its own writable,
    no-admin application-data directory instead of modifying Program Files.
    """
    try:
        import py7zr
    except ImportError as exc:  # pragma: no cover - bundled in the Windows build
        raise RuntimeError(
            "Automatic Proxmark repair support is missing from this SpoolPilot build"
        ) from exc

    app_dir = Path(app_dir)
    download_dir = app_dir / "downloads"
    managed_dir = app_dir / "proxmark"
    archive = download_dir / "rrg_other-latest.7z"
    staging = app_dir / f"proxmark-staging-{uuid.uuid4().hex}"
    replacement = app_dir / f"proxmark-new-{uuid.uuid4().hex}"
    backup = app_dir / "proxmark.previous"

    status("Proxmark client files are missing; repairing automatically…")
    _download(PROXMARK_BUILD_URL, archive, status)

    staging.mkdir(parents=True, exist_ok=False)
    try:
        status("Extracting the RRG Proxmark client…")
        with py7zr.SevenZipFile(archive, mode="r") as package:
            package.extractall(path=staging)

        extracted_client = find_client_root(staging)
        if extracted_client is None:
            raise RuntimeError(
                "The downloaded RRG package did not contain setup.bat, pm3, and proxmark3.exe"
            )

        # Preserve the package around the client directory because setup.bat and
        # client resources can reference sibling directories in precompiled builds.
        package_root = extracted_client.parent if extracted_client.name.casefold() == "client" else extracted_client
        shutil.copytree(package_root, replacement)
        replacement_client = find_client_root(replacement)
        if replacement_client is None:
            raise RuntimeError("The extracted Proxmark client failed SpoolPilot validation")

        status("Installing the repaired Proxmark client…")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if managed_dir.exists():
            managed_dir.replace(backup)
        try:
            replacement.replace(managed_dir)
        except Exception:
            if backup.exists() and not managed_dir.exists():
                backup.replace(managed_dir)
            raise

        installed_client = find_client_root(managed_dir)
        if installed_client is None:
            if managed_dir.exists():
                shutil.rmtree(managed_dir, ignore_errors=True)
            if backup.exists():
                backup.replace(managed_dir)
            raise RuntimeError("The installed Proxmark client did not pass validation")

        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        _ENV_CACHE.clear()
        status(f"Proxmark client repaired automatically: {installed_client}")
        return installed_client
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(replacement, ignore_errors=True)
        archive.unlink(missing_ok=True)


def ensure_client_directory(
    client_directory: Path,
    app_dir: Path,
    status: Callable[[str], None],
) -> Path:
    """Return a complete client folder, installing a managed copy when needed."""
    candidate = Path(client_directory)
    missing = missing_client_items(candidate)
    if not missing:
        return candidate

    status("Incomplete Proxmark folder: " + ", ".join(missing))
    existing_managed = managed_client_root(app_dir)
    if existing_managed is not None:
        status(f"Using SpoolPilot's managed Proxmark client: {existing_managed}")
        return existing_managed
    return install_managed_client(app_dir, status)


def load_client_environment(client_directory: Path) -> dict[str, str]:
    """Capture the environment produced by setup.bat without relying on MSYS path quoting."""
    directory = Path(client_directory).resolve()
    cache_key = str(directory).casefold()
    cached = _ENV_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    setup_file = directory / "setup.bat"
    if not setup_file.is_file():
        raise FileNotFoundError(f"Missing Proxmark setup file: {setup_file}")

    probe = Path(tempfile.gettempdir()) / f"spoolpilot-pm3-env-{uuid.uuid4().hex}.bat"
    probe.write_text(
        "@echo off\r\n"
        f'call "{setup_file}" >nul 2>&1\r\n'
        "if errorlevel 1 exit /b %errorlevel%\r\n"
        "set\r\n",
        encoding="utf-8",
        newline="",
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(probe)],
            cwd=str(directory),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
            timeout=60,
        )
    finally:
        probe.unlink(missing_ok=True)

    if result.returncode != 0:
        details = (result.stdout or "") + (result.stderr or "")
        raise RuntimeError(
            "Proxmark setup.bat failed while preparing the client environment"
            + (f": {details.strip()}" if details.strip() else "")
        )

    environment = os.environ.copy()
    for line in result.stdout.splitlines():
        if "=" not in line or line.startswith("="):
            continue
        key, value = line.split("=", 1)
        if key:
            environment[key] = value
    _ENV_CACHE[cache_key] = environment.copy()
    return environment


def direct_client_command(
    client_directory: Path,
    port: str,
    commands: Iterable[str],
) -> tuple[list[str], dict[str, str]]:
    """Build a native proxmark3.exe command line for one or many PM3 commands."""
    executable = find_client_executable(client_directory)
    if executable is None:
        raise FileNotFoundError("The Proxmark client executable is missing")
    command_list = [command.strip() for command in commands if command.strip()]
    if not command_list:
        raise ValueError("No Proxmark commands were supplied")
    command_text = ";".join(command_list)
    return (
        [str(executable), "-f", "-p", port.upper(), "-c", command_text],
        load_client_environment(client_directory),
    )
