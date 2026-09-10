"""SpoolPilot Tag Writer managed-client entrypoint.

Adds automatic Proxmark client repair and uses the native proxmark3 executable directly,
which avoids the MSYS script-path quoting problem seen with client folders under Program Files.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from . import client_support
except ImportError:
    import client_support


SOURCE = Path(__file__).with_name("SpoolPilotTagWriter.pyw")
loader = importlib.machinery.SourceFileLoader("spoolpilot_tag_writer_base", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
base = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = base
loader.exec_module(base)

base.APP_VERSION = "0.4.3"


def _runner_validate(self) -> None:
    missing = client_support.missing_client_items(self.client_directory)
    if missing:
        raise FileNotFoundError("Incomplete Proxmark client: " + ", ".join(missing))
    if not re.fullmatch(r"COM\d+", self.port, re.IGNORECASE):
        raise ValueError(f"Invalid serial port: {self.port}")


def _runner_run(self, commands, phase: str, timeout: int = 300):
    self.validate()
    command_list = [command.strip() for command in commands if command.strip()]
    if not command_list:
        raise ValueError("No Proxmark commands were supplied")

    argv, environment = client_support.direct_client_command(
        self.client_directory,
        self.port,
        command_list,
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    self.output(f"{phase} ({len(command_list)} commands)…")
    cleaned = ""
    process = None
    try:
        for attempt in range(1, 5):
            started = time.monotonic()
            process = subprocess.Popen(
                argv,
                cwd=str(self.client_directory),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
            try:
                raw_output, _ = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                raw_output, _ = process.communicate()
                raise TimeoutError(f"{phase} timed out after {timeout} seconds")

            cleaned = base.ANSI_RE.sub("", raw_output or "")
            elapsed = time.monotonic() - started
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"\n===== {phase} | attempt {attempt}/4 | {base.utc_now()} | "
                    f"{elapsed:.1f}s =====\n"
                )
                handle.write(cleaned)
                handle.write("\n")

            if "invalid serial port" not in cleaned.lower():
                break
            if attempt == 4:
                raise RuntimeError(
                    f"Windows could not open {self.port} after four attempts. Close every "
                    "Proxmark window, reconnect the USB cable, and refresh the port list."
                )
            delay = 2 + attempt
            self.output(
                f"{self.port} is still being released by Windows; retrying in {delay} seconds"
            )
            time.sleep(delay)
    finally:
        time.sleep(1.5)

    return base.Pm3Result(cleaned, process.returncode if process else 1, self.log_file)


def _discover_client_directory():
    configured = base.load_settings().get("client_directory", "")
    if configured and not client_support.missing_client_items(Path(configured)):
        return Path(configured)
    managed = client_support.managed_client_root(base.APP_DIR)
    if managed is not None:
        return managed
    downloads = Path.home() / "Downloads"
    matches = list(downloads.glob("rrg_other-*/client/setup.bat"))
    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for setup in matches:
        candidate = setup.parent
        if not client_support.missing_client_items(candidate):
            return candidate
    return Path(configured) if configured else None


def _validate_reader_selection(self):
    selected = Path(self.client_var.get().strip()) if self.client_var.get().strip() else Path()
    port = self.port_var.get().strip().upper()

    try:
        client = client_support.ensure_client_directory(selected, base.APP_DIR, self._post_status)
    except Exception as exc:
        raise RuntimeError(
            "SpoolPilot could not repair the Proxmark client automatically. "
            f"{exc}"
        ) from exc

    if str(client) != self.client_var.get().strip():
        self.client_var.set(str(client))
    runner = base.Pm3Runner(client, port, self._post_log)
    runner.validate()
    base.save_settings(str(client), port)
    return client, port


base.Pm3Runner.validate = _runner_validate
base.Pm3Runner.run = _runner_run
base.discover_client_directory = _discover_client_directory
base.TagWriterApp._validate_reader_selection = _validate_reader_selection


def main() -> None:
    for directory in (base.APP_DIR, base.CACHE_DIR, base.LOG_DIR, base.RECOVERY_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    app = base.TagWriterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
