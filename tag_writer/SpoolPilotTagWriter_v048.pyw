"""SpoolPilot Tag Writer 0.4.8 release entrypoint.

Builds on 0.4.7 and fixes two over-strict RF checks:
- Diagnosis now judges BCC/collision errors only from the ten explicit
  ``hf 14a reader`` scans.  BCC warnings emitted by the supplemental
  ``hf mf info`` probe are shown separately and do not turn a stable 10/10
  reader result into a false RF-interference failure.
- Final verification no longer fails merely because one command in the large
  verification batch emitted a transient BCC warning.  Every expected block
  and the target UID still have to be read back correctly; missing reads are
  retried in small targeted batches before the write is accepted.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import re
import sys
from pathlib import Path

import tkinter as tk  # noqa: F401
from tkinter import filedialog, messagebox, ttk  # noqa: F401

# Ensure this dependency is frozen even though 0.4.7 is loaded dynamically.
import client_support  # noqa: F401


RELEASE_VERSION = "0.4.8"


def _load_previous():
    source = Path(__file__).with_name("SpoolPilotTagWriter_v047.pyw")
    loader = importlib.machinery.SourceFileLoader("spoolpilot_tag_writer_v047", str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("Could not load SpoolPilot Tag Writer 0.4.7 core")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


previous = _load_previous()
core = previous.core
core.APP_VERSION = RELEASE_VERSION


SAK_VALUE_RE = re.compile(r"SAK:\s*([0-9A-Fa-f]{2})\b", re.IGNORECASE)
ATQA_VALUE_RE = re.compile(
    r"ATQA:\s*([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\b", re.IGNORECASE
)


def _analyze_reader_diagnostic(result, expected_scans: int = 10):
    """Assess RF stability from the explicit reader scans, not helper probes."""
    output = result.output
    lowered = output.lower()
    events = core.parse_events(output)
    reader_events = [body for command, body in events if command == "hf 14a reader"]

    detected_uids = [
        core.normalize_hex(matches[0])
        for body in reader_events
        if (matches := core.UID_RE.findall(body))
    ]
    classic_reads = sum(
        1
        for body in reader_events
        if core.UID_RE.search(body)
        and core.SAK08_RE.search(body)
        and "MIFARE Classic 1K" in body
    )
    reader_bcc_errors = sum(body.count("BCC0 incorrect") for body in reader_events)
    total_bcc_errors = output.count("BCC0 incorrect")
    supplemental_bcc_errors = max(0, total_bcc_errors - reader_bcc_errors)
    unique_uids = sorted(set(detected_uids))
    communicated = (
        "communicating with pm3" in lowered
        or any(command == "hw version" for command, _body in events)
    )

    sak_values = sorted(
        {
            match.group(1).upper()
            for body in reader_events
            for match in SAK_VALUE_RE.finditer(body)
        }
    )
    atqa_values = sorted(
        {
            f"{match.group(1).upper()} {match.group(2).upper()}"
            for body in reader_events
            for match in ATQA_VALUE_RE.finditer(body)
        }
    )

    lines = [
        f"Proxmark communication: {'PASS' if communicated else 'FAIL'}",
        f"Tag detections: {len(detected_uids)}/{expected_scans}",
        f"MIFARE Classic 1K / SAK 08 reads: {classic_reads}/{expected_scans}",
        "Detected SAK: " + (", ".join(sak_values) if sak_values else "not reported"),
        "Detected ATQA: " + (", ".join(atqa_values) if atqa_values else "not reported"),
        f"Reader BCC/collision errors: {reader_bcc_errors}",
        f"Supplemental-probe BCC warnings: {supplemental_bcc_errors}",
        "UIDs detected: " + (", ".join(unique_uids) if unique_uids else "none"),
    ]

    if not communicated:
        summary = "CONNECTION PROBLEM — The app could not communicate with the Proxmark"
        advice = (
            "Close other Proxmark windows, reconnect its USB cable, click Refresh, and verify "
            "the selected COM port. The tag was not written."
        )
    elif not reader_events:
        summary = "CLIENT PROBLEM — The Proxmark commands did not run correctly"
        advice = (
            "Verify the selected Proxmark client or let SpoolPilot repair its managed client, "
            "then rerun Diagnosis."
        )
    elif reader_bcc_errors or len(unique_uids) > 1:
        summary = "RF INTERFERENCE — The reader scans saw a collision or unstable response"
        advice = (
            "Keep only one sticker on the HF antenna. Move the tag roll, phones, cards, metal, "
            "and every other RFID tag away, then reposition the sticker and rerun Diagnosis. "
            "Do not write this tag yet."
        )
    elif not detected_uids:
        summary = "TAG NOT DETECTED — The Proxmark is connected, but the tag never answered"
        advice = (
            "Center one tag flat on the HF antenna and slowly try different positions. Test a "
            "known untouched tag if needed."
        )
    elif len(detected_uids) < expected_scans:
        summary = "UNSTABLE TAG — It was detected only some of the time"
        advice = (
            "Do not write yet. Keep the tag still and flat, remove nearby tags or metal, and "
            "rerun Diagnosis."
        )
    elif classic_reads != expected_scans:
        summary = "WRONG OR UNSTABLE TAG TYPE — It is not consistently Classic 1K / SAK 08"
        advice = (
            "Do not write it. This app requires a compatible MIFARE Classic 1K CUID/FUID tag "
            "that reports ATQA 00 04 / SAK 08 on every scan."
        )
    else:
        info_body = "\n".join(body for command, body in events if command == "hf mf info")
        if "Write Once / FUID" in info_body or "Gen 2 / CUID" in info_body:
            capability = "Compatible CUID/FUID capability was reported."
        else:
            capability = (
                "The tag was stable, but compatible CUID/FUID capability was not confirmed; "
                "use Check Tag before writing."
            )
        summary = "PASS — The Proxmark and tag detection are stable"
        if supplemental_bcc_errors:
            advice = (
                f"{capability} The supplemental info probe reported {supplemental_bcc_errors} "
                "BCC warning(s), but all ten dedicated reader scans were stable. Check Tag is "
                "still required before writing."
            )
        else:
            advice = f"{capability} You can proceed to Check Tag."

    lines.extend(("", advice, "", "Diagnosis is read-only; no tag data was changed."))
    return core.DiagnosticReport(summary, "\n".join(lines), result.log_file)


core.analyze_reader_diagnostic = _analyze_reader_diagnostic


def _final_verify_resilient(self) -> None:
    """Require exact readback while tolerating unrelated transient BCC warnings."""
    commands = ["hf 14a reader", "hf 14a reader"]
    expected_blocks = [0, 1, 2]
    for sector in range(16):
        blocks = [sector * 4 + offset for offset in range(3)]
        if sector == 0:
            blocks = [0, 1, 2]
        for block in blocks:
            commands.append(core.read_command(block, self.image.key_a(sector), "A"))
            commands.append(core.read_command(block, self.image.key_b(sector), "B"))
            if block not in expected_blocks:
                expected_blocks.append(block)

    result = self.runner.run(commands, "Full verification", timeout=300)
    rows = core.parse_block_rows(result.output)
    uids = {core.normalize_hex(value) for value in core.UID_RE.findall(result.output)}

    def missing_blocks_now():
        missing = []
        for block in expected_blocks:
            expected = self.image.block(block).hex().upper()
            if expected not in rows.get(block, set()):
                missing.append(block)
        return missing

    missing = missing_blocks_now()
    uid_missing = self.image.target_uid not in uids

    # A 98-command verification burst can occasionally contain an unrelated
    # BCC warning. Retry only the evidence that is actually missing instead of
    # failing a tag whose complete expected contents were already read back.
    for attempt in range(1, 4):
        if not missing and not uid_missing:
            break
        retry_commands = []
        if uid_missing:
            retry_commands.extend(["hf 14a reader", "hf 14a reader"])
        for block in missing:
            sector = block // 4
            retry_commands.append(core.read_command(block, self.image.key_a(sector), "A"))
            retry_commands.append(core.read_command(block, self.image.key_b(sector), "B"))
            retry_commands.append(core.read_command(block, self.image.key_a(sector), "A"))
        retry = self.runner.run(
            retry_commands,
            f"Final verification retry {attempt}",
            timeout=180,
        )
        retry_rows = core.parse_block_rows(retry.output)
        for block, values in retry_rows.items():
            rows.setdefault(block, set()).update(values)
        uids.update(core.normalize_hex(value) for value in core.UID_RE.findall(retry.output))
        missing = missing_blocks_now()
        uid_missing = self.image.target_uid not in uids

    if missing:
        raise RuntimeError(
            "Final verification could not read the expected data from block(s): "
            + ", ".join(str(block) for block in missing)
        )
    if uid_missing:
        raise RuntimeError("Final UID verification failed")

    bcc_count = result.output.count("BCC0 incorrect")
    if bcc_count:
        self.status(
            f"Final verification passed; {bcc_count} transient BCC warning(s) occurred in the "
            "large read batch, but every expected block and the UID were verified"
        )


core.SafeWriter._final_verify = _final_verify_resilient


def _main() -> None:
    if "--self-test" in sys.argv:
        if core.APP_VERSION != RELEASE_VERSION:
            raise RuntimeError("Packaged application version mismatch")
        if tk.TkVersion <= 0:
            raise RuntimeError("Tk runtime did not load")

        # Regression: stable reader scans must not fail solely because the
        # supplemental hf mf info probe emits BCC warnings.
        reader = (
            "[usb|script] pm3 --> hf 14a reader\n"
            "[+] UID: AA 55 C3 96\n"
            "[+] ATQA: 00 04\n"
            "[+] SAK: 08 [2]\n"
        )
        sample = reader * 10 + (
            "[usb|script] pm3 --> hf mf info\n"
            "[+] Magic capabilities... Gen 2 / CUID\n"
            "[#] BCC0 incorrect, got 0x00, expected 0xaa\n"
            "[#] BCC0 incorrect, got 0x00, expected 0xbb\n"
        )
        fake = core.Pm3Result(sample, 0, Path("self-test.log"))
        report = core.analyze_reader_diagnostic(fake, 10)
        if not report.summary.startswith("PASS"):
            raise RuntimeError("Supplemental BCC diagnostic regression")
        if "Reader BCC/collision errors: 0" not in report.details:
            raise RuntimeError("Reader-only BCC counter regression")
        return

    os.environ.pop("PYINSTALLER_RESET_ENVIRONMENT", None)
    core.main()


if __name__ == "__main__":
    _main()
