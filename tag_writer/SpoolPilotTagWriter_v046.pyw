"""SpoolPilot Tag Writer 0.4.6 release entrypoint.

Fixes Classic 1K detection for current Proxmark output while preserving the
managed Proxmark client, safe updater, and explicit Tkinter packaging fixes.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Explicit imports are required because the UI core is dynamically loaded.
import tkinter as tk  # noqa: F401
from tkinter import filedialog, messagebox, ttk  # noqa: F401

from client_support import (
    direct_client_command,
    ensure_client_directory,
    managed_client_root,
    missing_client_items,
)


RELEASE_VERSION = "0.4.6"


def _load_core():
    source = Path(__file__).with_name("SpoolPilotTagWriter.pyw")
    loader = importlib.machinery.SourceFileLoader("spoolpilot_tag_writer_core", str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("Could not load the SpoolPilot Tag Writer core")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


core = _load_core()
core.APP_VERSION = RELEASE_VERSION


# PyInstaller 6.9+ requires restart processes to explicitly reset the frozen
# application environment before launching the replacement executable.
core.UPDATE_HELPER_SCRIPT = core.UPDATE_HELPER_SCRIPT.replace(
    "$newProcess = Start-Process -FilePath $Target -PassThru",
    "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'\n"
    "        $newProcess = Start-Process -FilePath $Target -PassThru",
).replace(
    "Start-Process -FilePath $Target | Out-Null",
    "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'\n"
    "            Start-Process -FilePath $Target | Out-Null",
)


def _validate_runner(self) -> None:
    if not re.fullmatch(r"COM\d+", self.port, re.IGNORECASE):
        raise ValueError(f"Invalid serial port: {self.port}")
    missing = missing_client_items(self.client_directory)
    if missing:
        raise FileNotFoundError("Proxmark client is incomplete: " + ", ".join(missing))


def _run_native(self, commands, phase: str, timeout: int = 300):
    command_list = [command.strip() for command in commands if command.strip()]
    if not command_list:
        raise ValueError("No Proxmark commands were supplied")

    repaired = ensure_client_directory(self.client_directory, core.APP_DIR, self.output)
    if repaired != self.client_directory:
        self.client_directory = repaired
        core.save_settings(str(repaired), self.port)

    _validate_runner(self)
    argv, environment = direct_client_command(self.client_directory, self.port, command_list)

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    self.output(f"{phase} ({len(command_list)} commands)…")
    cleaned = ""
    process = None
    for attempt in range(1, 5):
        started = time.monotonic()
        process = subprocess.Popen(
            argv,
            cwd=str(self.client_directory),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
            env=environment,
        )
        try:
            raw_output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            raw_output, _ = process.communicate()
            raise TimeoutError(f"{phase} timed out after {timeout} seconds")

        cleaned = core.ANSI_RE.sub("", raw_output or "")
        elapsed = time.monotonic() - started
        with self.log_file.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n===== {phase} | native client | attempt {attempt}/4 | "
                f"{core.utc_now()} | {elapsed:.1f}s =====\n"
            )
            handle.write(cleaned)
            handle.write("\n")

        lowered = cleaned.lower()
        if "invalid serial port" not in lowered and "could not find proxmark3 on" not in lowered:
            break
        if attempt == 4:
            raise RuntimeError(
                f"Windows could not open {self.port} after four attempts. Close every "
                "Proxmark window, reconnect the USB cable, and click Refresh."
            )
        delay = 2 + attempt
        self.output(f"{self.port} is still being released by Windows; retrying in {delay} seconds")
        time.sleep(delay)

    time.sleep(1.0)
    assert process is not None
    return core.Pm3Result(cleaned, process.returncode, self.log_file)


core.Pm3Runner.validate = _validate_runner
core.Pm3Runner.run = _run_native


def _validate_reader_selection(self):
    client_text = self.client_var.get().strip()
    if not client_text:
        client = managed_client_root(core.APP_DIR) or (core.APP_DIR / "proxmark")
    else:
        client = Path(client_text)
    port = self.port_var.get().strip().upper()
    if not re.fullmatch(r"COM\d+", port, re.IGNORECASE):
        raise ValueError("Select a valid Proxmark COM port")

    if not missing_client_items(client):
        core.save_settings(str(client), port)
    else:
        self._set_status(
            "Proxmark client is incomplete; SpoolPilot will repair it automatically when the test starts"
        )
    return client, port


core.TagWriterApp._validate_reader_selection = _validate_reader_selection


def _discover_client_directory():
    configured = core.load_settings().get("client_directory", "")
    if configured:
        configured_path = Path(configured)
        if not missing_client_items(configured_path):
            return configured_path

    managed = managed_client_root(core.APP_DIR)
    if managed is not None:
        return managed

    downloads = Path.home() / "Downloads"
    candidates = []
    for setup_file in downloads.glob("rrg_other-*/client/setup.bat"):
        candidate = setup_file.parent
        if not missing_client_items(candidate):
            candidates.append(candidate)
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


core.discover_client_directory = _discover_client_directory


# Current Iceman `hf 14a reader` output reports the ISO14443A identifiers but
# does not print the literal words "MIFARE Classic 1K".  ATQA 00 04 + SAK 08
# is the signature we need here; the later `hf mf info`, FUID capability check,
# and per-sector read preflight still provide the destructive-write safeguards.
_base_parse_events = core.parse_events
ATQA_0004_RE = re.compile(r"ATQA:\s*00\s+04\b", re.IGNORECASE)
SAK_VALUE_RE = re.compile(r"SAK:\s*([0-9A-Fa-f]{2})\b", re.IGNORECASE)
ATQA_VALUE_RE = re.compile(r"ATQA:\s*([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\b", re.IGNORECASE)


def _parse_events_with_classic_signature(output: str):
    events = _base_parse_events(output)
    normalized = []
    for command, body in events:
        if (
            command == "hf 14a reader"
            and core.UID_RE.search(body)
            and core.SAK08_RE.search(body)
            and ATQA_0004_RE.search(body)
            and "MIFARE Classic 1K" not in body
        ):
            body = body + "\n[SpoolPilot] MIFARE Classic 1K signature: ATQA 00 04 / SAK 08\n"
        normalized.append((command, body))
    return normalized


core.parse_events = _parse_events_with_classic_signature


_base_analyze_reader_diagnostic = core.analyze_reader_diagnostic


def _analyze_reader_diagnostic(result, expected_scans: int = 10):
    report = _base_analyze_reader_diagnostic(result, expected_scans)
    reader_bodies = [
        body
        for command, body in _base_parse_events(result.output)
        if command == "hf 14a reader"
    ]
    sak_values = sorted(
        {match.group(1).upper() for body in reader_bodies for match in SAK_VALUE_RE.finditer(body)}
    )
    atqa_values = sorted(
        {
            f"{match.group(1).upper()} {match.group(2).upper()}"
            for body in reader_bodies
            for match in ATQA_VALUE_RE.finditer(body)
        }
    )
    extra = [
        "Detected SAK: " + (", ".join(sak_values) if sak_values else "not reported"),
        "Detected ATQA: " + (", ".join(atqa_values) if atqa_values else "not reported"),
    ]
    lines = report.details.splitlines()
    insert_at = next((i for i, line in enumerate(lines) if line.startswith("BCC/collision errors:")), 3)
    lines[insert_at:insert_at] = extra
    return core.DiagnosticReport(report.summary, "\n".join(lines), report.log_file)


core.analyze_reader_diagnostic = _analyze_reader_diagnostic


def _main() -> None:
    if "--self-test" in sys.argv:
        if core.APP_VERSION != RELEASE_VERSION:
            raise RuntimeError("Packaged application version mismatch")
        if tk.TkVersion <= 0:
            raise RuntimeError("Tk runtime did not load")

        # Regression-test the exact Proxmark output format that previously gave
        # a false 0/10 Classic result.
        sample = (
            "[usb|script] pm3 --> hf 14a reader\n"
            "[+] UID: AA 55 C3 96\n"
            "[+] ATQA: 00 04\n"
            "[+] SAK: 08 [2]\n"
        )
        parsed = core.parse_events(sample)
        if len(parsed) != 1 or "MIFARE Classic 1K" not in parsed[0][1]:
            raise RuntimeError("Classic 1K SAK/ATQA parser regression")
        return

    os.environ.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
    core.main()


if __name__ == "__main__":
    _main()
