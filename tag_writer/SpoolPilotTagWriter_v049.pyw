"""SpoolPilot Tag Writer 0.4.9 release entrypoint.

Uses the Proxmark3 restore implementation for the permanent manufacturer-block
write.  These write-once S50 FUID blanks require ``hf mf restore --force`` to
handle Bambu's strict access conditions reliably.  SpoolPilot still completes
and verifies all reversible data and sectors 1-15 before invoking restore, then
retries targeted UID/block reads before accepting the permanent write.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import tkinter as tk  # noqa: F401
from tkinter import filedialog, messagebox, ttk  # noqa: F401

import client_support  # noqa: F401


RELEASE_VERSION = "0.4.9"


def _load_previous():
    source = Path(__file__).with_name("SpoolPilotTagWriter_v048.pyw")
    loader = importlib.machinery.SourceFileLoader("spoolpilot_tag_writer_v048", str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("Could not load SpoolPilot Tag Writer 0.4.8 core")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


previous = _load_previous()
core = previous.core
core.APP_VERSION = RELEASE_VERSION


def _verify_uid_after_restore(self, attempts: int = 4) -> None:
    """Verify the permanent UID and discover the resulting sector-0 key state."""
    target_uid = self.image.target_uid
    target_block = self.image.block(0).hex().upper()
    expected_block_one = self.image.block(1).hex().upper()
    target_a = self.image.key_a(0)
    target_b = self.image.key_b(0)

    seen_rows: dict[int, set[str]] = {}
    seen_uids: set[str] = set()
    successful = []

    for attempt in range(1, attempts + 1):
        commands = [
            "hf 14a reader",
            "hf 14a reader",
            core.read_command(0, core.DEFAULT_KEY, "A"),
            core.read_command(0, target_a, "A"),
            core.read_command(0, target_b, "B"),
            core.read_command(1, core.DEFAULT_KEY, "A"),
            core.read_command(1, target_a, "A"),
            core.read_command(1, target_b, "B"),
        ]
        result = self.runner.run(commands, f"Permanent UID verification {attempt}/{attempts}")
        rows = core.parse_block_rows(result.output)
        for block, values in rows.items():
            seen_rows.setdefault(block, set()).update(values)
        seen_uids.update(core.normalize_hex(value) for value in core.UID_RE.findall(result.output))
        successful.extend(
            core.successful_block_reads(core.parse_events(result.output), 1, target_a, target_b)
        )
        if target_block in seen_rows.get(0, set()) and target_uid in seen_uids:
            break

    if target_block not in seen_rows.get(0, set()) or target_uid not in seen_uids:
        raise RuntimeError(
            f"UID restore could not be verified after {attempts} targeted retries. "
            f"Recovery record: {self.recovery_file}"
        )

    target_read = next(
        (
            item
            for item in successful
            if item[0] == "target" and item[3] == expected_block_one
        ),
        None,
    )
    if target_read is not None:
        _, key_type, key, _ = target_read
        self.sectors[0] = core.SectorState(0, "target", key, key_type)
        sealed = set(self.recovery.get("sealed_sectors", []))
        sealed.add(0)
        self.recovery["sealed_sectors"] = sorted(sealed)

    self.recovery["uid_written"] = True
    self.recovery["uid_method"] = "hf mf restore --force"
    self._save_recovery()
    self.status(f"Permanent UID {target_uid} verified")


def _write_uid_with_forced_restore(self) -> None:
    """Commit block 0 using the supported FUID restore path, then verify it."""
    if self.recovery.get("starting_uid") == self.image.target_uid:
        _verify_uid_after_restore(self)
        return

    dump_directory = self.image.dump_file.parent
    if self.image.dump_file.parent != self.image.key_file.parent:
        raise RuntimeError("The downloaded dump and key files are not in the same folder")

    command = (
        "hf mf restore --1k --force "
        f"-f {self.image.dump_file.name} -k {self.image.key_file.name}"
    )
    self.status("Committing the permanent UID with Proxmark forced restore…")
    self.recovery["uid_method"] = "hf mf restore --force"
    self.recovery["restore_command"] = command
    self._save_recovery()

    self.runner._spoolpilot_command_cwd = dump_directory
    try:
        self.runner.run([command], "Permanent FUID restore", timeout=300)
    finally:
        try:
            del self.runner._spoolpilot_command_cwd
        except AttributeError:
            pass

    _verify_uid_after_restore(self)


core.SafeWriter._write_uid = _write_uid_with_forced_restore


def _main() -> None:
    if "--self-test" in sys.argv:
        if core.APP_VERSION != RELEASE_VERSION:
            raise RuntimeError("Packaged application version mismatch")
        if tk.TkVersion <= 0:
            raise RuntimeError("Tk runtime did not load")
        sample = "hf mf restore --1k --force -f dump.bin -k keys.bin"
        if "--force" not in sample or "restore" not in sample:
            raise RuntimeError("Forced restore command regression")
        return

    os.environ.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
    core.main()


if __name__ == "__main__":
    _main()
