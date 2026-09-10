"""SpoolPilot Tag Writer - safe desktop writer for Bambu-compatible FUID tags."""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_NAME = "SpoolPilot Tag Writer"
APP_VERSION = "0.3.0"
FACTORY_UID = "AA55C396"
DEFAULT_KEY = "FFFFFFFFFFFF"
LIBRARY_REPOSITORY = "queengooborg/Bambu-Lab-RFID-Library"
LIBRARY_TREE_URL = (
    "https://api.github.com/repos/queengooborg/"
    "Bambu-Lab-RFID-Library/git/trees/main?recursive=1"
)
RAW_LIBRARY_URL = (
    "https://raw.githubusercontent.com/queengooborg/"
    "Bambu-Lab-RFID-Library/main/"
)

LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", Path.home()))
APP_DIR = LOCAL_APPDATA / "SpoolPilotTagWriter"
CACHE_DIR = APP_DIR / "cache"
LOG_DIR = APP_DIR / "logs"
RECOVERY_DIR = APP_DIR / "recovery"
CATALOG_FILE = CACHE_DIR / "catalog.json"
SETTINGS_FILE = APP_DIR / "settings.json"

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
UID_RE = re.compile(r"UID:\s*((?:[0-9A-Fa-f]{2}\s+){3}[0-9A-Fa-f]{2})")
SAK08_RE = re.compile(r"SAK:\s*08\b", re.IGNORECASE)
BLOCK_ROW_RE = re.compile(
    r"^\[[^\]]+\]\s*(\d+)\s+\|\s*"
    r"((?:[0-9A-Fa-f]{2}\s+){15}[0-9A-Fa-f]{2})\s+\|",
    re.MULTILINE,
)
EVENT_RE = re.compile(
    r"\[[^\]\r\n]+\]\s+pm3\s+-->\s*([^\r\n]+)\r?\n"
    r"(.*?)(?=\[[^\]\r\n]+\]\s+pm3\s+-->|\Z)",
    re.DOTALL,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_hex(value: str) -> str:
    return re.sub(r"[^0-9A-Fa-f]", "", value).upper()


def xor_bcc(uid: bytes) -> int:
    result = 0
    for value in uid:
        result ^= value
    return result


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class FilamentEntry:
    label: str
    material: str
    product: str
    color: str
    uid: str
    dump_path: str
    key_path: str

    @property
    def search_text(self) -> str:
        return f"{self.material} {self.product} {self.color} {self.uid} {self.label}".lower()


@dataclass
class TagImage:
    entry: FilamentEntry
    dump: bytes
    keys: bytes
    dump_file: Path
    key_file: Path

    @property
    def target_uid(self) -> str:
        return self.dump[:4].hex().upper()

    def block(self, block_number: int) -> bytes:
        start = block_number * 16
        return self.dump[start : start + 16]

    def key_a(self, sector: int) -> str:
        start = sector * 6
        return self.keys[start : start + 6].hex().upper()

    def key_b(self, sector: int) -> str:
        start = 96 + sector * 6
        return self.keys[start : start + 6].hex().upper()

    def trailer(self, sector: int) -> str:
        trailer_block = sector * 4 + 3
        access = self.block(trailer_block)[6:10].hex().upper()
        return self.key_a(sector) + access + self.key_b(sector)

    def validate(self) -> None:
        if len(self.dump) != 1024:
            raise ValueError(f"Dump must be 1024 bytes, found {len(self.dump)}")
        if len(self.keys) != 192:
            raise ValueError(f"Key file must be 192 bytes, found {len(self.keys)}")
        if self.dump[4] != xor_bcc(self.dump[:4]):
            raise ValueError("Selected dump has an invalid manufacturer-block checksum")
        if self.target_uid != self.entry.uid.upper():
            raise ValueError(
                f"Catalog UID {self.entry.uid} does not match dump UID {self.target_uid}"
            )


class CatalogService:
    def __init__(self, status: Callable[[str], None]):
        self.status = status

    def load_cached(self) -> list[FilamentEntry]:
        if not CATALOG_FILE.exists():
            return []
        payload = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        return [FilamentEntry(**item) for item in payload.get("entries", [])]

    def update(self) -> list[FilamentEntry]:
        self.status("Downloading the current Bambu RFID library index…")
        request = urllib.request.Request(
            LIBRARY_TREE_URL,
            headers={"User-Agent": f"SpoolPilotTagWriter/{APP_VERSION}"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            tree_payload = json.load(response)

        tree = tree_payload.get("tree", [])
        files = {
            item["path"]: int(item.get("size", -1))
            for item in tree
            if item.get("type") == "blob"
        }
        folders: dict[str, list[str]] = {}
        for path in files:
            folders.setdefault(path.rsplit("/", 1)[0] if "/" in path else "", []).append(path)

        grouped: dict[tuple[str, str, str], FilamentEntry] = {}
        for dump_path, size in files.items():
            if size != 1024 or not dump_path.lower().endswith("-dump.bin"):
                continue
            folder, filename = dump_path.rsplit("/", 1)
            key_path = dump_path[:-9] + "-key.bin"
            if files.get(key_path) != 192:
                alternatives = [
                    item
                    for item in folders.get(folder, [])
                    if item.lower().endswith("-key.bin") and files.get(item) == 192
                ]
                if len(alternatives) != 1:
                    continue
                key_path = alternatives[0]

            uid_match = re.search(r"([0-9A-Fa-f]{8})-dump\.bin$", filename)
            if not uid_match:
                parent_uid = folder.rsplit("/", 1)[-1]
                uid_match = re.fullmatch(r"([0-9A-Fa-f]{8})", parent_uid)
            if not uid_match:
                continue
            uid = uid_match.group(1).upper()

            parts = folder.split("/")
            if parts and re.fullmatch(r"[0-9A-Fa-f]{8}", parts[-1]):
                parts = parts[:-1]
            if len(parts) < 2:
                continue
            material = parts[0]
            color = parts[-1]
            product = " / ".join(parts[1:-1]) or material
            label = " • ".join((material, product, color))
            group_key = (material.casefold(), product.casefold(), color.casefold())
            candidate = FilamentEntry(
                label=label,
                material=material,
                product=product,
                color=color,
                uid=uid,
                dump_path=dump_path,
                key_path=key_path,
            )
            previous = grouped.get(group_key)
            if previous is None or candidate.uid < previous.uid:
                grouped[group_key] = candidate

        entries = sorted(
            grouped.values(),
            key=lambda item: (item.material.casefold(), item.product.casefold(), item.color.casefold()),
        )
        if not entries:
            raise RuntimeError("The library index contained no usable dump/key pairs")

        atomic_write_json(
            CATALOG_FILE,
            {
                "updated_at": utc_now(),
                "tree_sha": tree_payload.get("sha"),
                "repository": LIBRARY_REPOSITORY,
                "entries": [asdict(entry) for entry in entries],
            },
        )
        self.status(f"Library ready: {len(entries)} material/color choices")
        return entries

    def download(self, entry: FilamentEntry) -> TagImage:
        destination = CACHE_DIR / "tags" / entry.uid
        destination.mkdir(parents=True, exist_ok=True)
        dump_file = destination / "dump.bin"
        key_file = destination / "keys.bin"
        self._download_file(entry.dump_path, dump_file)
        self._download_file(entry.key_path, key_file)
        image = TagImage(
            entry=entry,
            dump=dump_file.read_bytes(),
            keys=key_file.read_bytes(),
            dump_file=dump_file,
            key_file=key_file,
        )
        image.validate()
        return image

    def _download_file(self, repository_path: str, destination: Path) -> None:
        url = RAW_LIBRARY_URL + urllib.parse.quote(repository_path, safe="/")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"SpoolPilotTagWriter/{APP_VERSION}"},
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            data = response.read()
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)


@dataclass
class Pm3Result:
    output: str
    return_code: int
    log_file: Path


@dataclass(frozen=True)
class DiagnosticReport:
    summary: str
    details: str
    log_file: Path

    @property
    def display_text(self) -> str:
        return f"{self.summary}\n\n{self.details}\n\nRaw diagnostic log:\n{self.log_file}"


class Pm3Runner:
    def __init__(
        self,
        client_directory: Path,
        port: str,
        output: Callable[[str], None],
    ):
        self.client_directory = client_directory
        self.port = port.upper()
        self.output = output
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_file = LOG_DIR / f"writer-{self.run_id}.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        if not (self.client_directory / "setup.bat").is_file():
            raise FileNotFoundError("Selected folder does not contain setup.bat")
        if not (self.client_directory / "pm3").is_file():
            raise FileNotFoundError("Selected folder does not contain the RRG pm3 launcher")
        if not re.fullmatch(r"COM\d+", self.port, re.IGNORECASE):
            raise ValueError(f"Invalid serial port: {self.port}")

    def run(self, commands: Iterable[str], phase: str, timeout: int = 300) -> Pm3Result:
        self.validate()
        command_list = [command.strip() for command in commands if command.strip()]
        if not command_list:
            raise ValueError("No Proxmark commands were supplied")
        # Proxmark's -s loader accepts .cmd and appends that suffix when absent.
        command_file = APP_DIR / f"pm3-{uuid.uuid4().hex}.cmd"
        command_file.parent.mkdir(parents=True, exist_ok=True)
        command_file.write_text("\n".join(command_list) + "\n", encoding="utf-8", newline="\n")
        posix_command_file = command_file.as_posix()
        launcher = (
            f'call setup.bat && bash pm3 -f -p {self.port} '
            f'-s "{posix_command_file}"'
        )
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.output(f"{phase} ({len(command_list)} commands)…")
        try:
            for attempt in range(1, 5):
                started = time.monotonic()
                process = subprocess.Popen(
                    [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", launcher],
                    cwd=str(self.client_directory),
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

                cleaned = ANSI_RE.sub("", raw_output or "")
                elapsed = time.monotonic() - started
                with self.log_file.open("a", encoding="utf-8") as handle:
                    handle.write(
                        f"\n===== {phase} | attempt {attempt}/4 | {utc_now()} | "
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
            command_file.unlink(missing_ok=True)
        time.sleep(1.5)
        return Pm3Result(cleaned, process.returncode, self.log_file)


def parse_events(output: str) -> list[tuple[str, str]]:
    return [(match.group(1).strip(), match.group(2)) for match in EVENT_RE.finditer(output)]


def parse_block_rows(output: str) -> dict[int, set[str]]:
    rows: dict[int, set[str]] = {}
    for match in BLOCK_ROW_RE.finditer(output):
        block = int(match.group(1))
        value = normalize_hex(match.group(2))
        rows.setdefault(block, set()).add(value)
    return rows


def read_command(block: int, key: str, key_type: str = "A") -> str:
    key_option = " -b" if key_type.upper() == "B" else ""
    return f"hf mf rdbl --blk {block}{key_option} -k {key}"


def write_command(
    block: int,
    data: str,
    key: str,
    key_type: str = "A",
    force: bool = False,
) -> str:
    key_option = " -b" if key_type.upper() == "B" else ""
    force_option = " --force" if force else ""
    return f"hf mf wrbl --blk {block}{key_option} -k {key} -d {data}{force_option}"


def command_auth(command: str, target_a: str, target_b: str) -> tuple[str, str, str]:
    """Return (mode, key type, key) for one generated read command."""
    key_match = re.search(r"(?:^|\s)-k\s+([0-9A-Fa-f]{12})(?:\s|$)", command)
    key = key_match.group(1).upper() if key_match else ""
    key_type = "B" if re.search(r"(?:^|\s)-b(?:\s|$)", command) else "A"
    if key_type == "A" and key == target_a.upper() and key != DEFAULT_KEY:
        return ("target", key_type, key)
    if key_type == "B" and key == target_b.upper() and key != DEFAULT_KEY:
        return ("target", key_type, key)
    if key == DEFAULT_KEY:
        return ("default", key_type, key)
    return ("unknown", key_type, key)


def successful_block_reads(
    events: Iterable[tuple[str, str]],
    block: int,
    target_a: str,
    target_b: str,
) -> list[tuple[str, str, str, str]]:
    """Return (mode, key type, key, data) for successful reads of one block."""
    successful: list[tuple[str, str, str, str]] = []
    for command, body in events:
        if not re.search(rf"(?:^|\s)--blk\s+{block}(?:\s|$)", command):
            continue
        values = parse_block_rows(body).get(block, set())
        mode, key_type, key = command_auth(command, target_a, target_b)
        for value in values:
            successful.append((mode, key_type, key, value))
    return successful


def analyze_reader_diagnostic(result: Pm3Result, expected_scans: int = 10) -> DiagnosticReport:
    """Turn a read-only PM3 diagnostic session into plain-English guidance."""
    output = result.output
    lowered = output.lower()
    events = parse_events(output)
    reader_events = [body for command, body in events if command == "hf 14a reader"]
    detected_uids = [
        normalize_hex(matches[0])
        for body in reader_events
        if (matches := UID_RE.findall(body))
    ]
    classic_reads = sum(
        1
        for body in reader_events
        if UID_RE.search(body) and SAK08_RE.search(body) and "MIFARE Classic 1K" in body
    )
    bcc_errors = output.count("BCC0 incorrect")
    unique_uids = sorted(set(detected_uids))
    communicated = (
        "communicating with pm3" in lowered
        or any(command == "hw version" for command, _body in events)
    )

    lines = [
        f"Proxmark communication: {'PASS' if communicated else 'FAIL'}",
        f"Tag detections: {len(detected_uids)}/{expected_scans}",
        f"MIFARE Classic 1K / SAK 08 reads: {classic_reads}/{expected_scans}",
        f"BCC/collision errors: {bcc_errors}",
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
            "Verify that the selected folder contains setup.bat and the pm3 launcher. "
            "Reinstall or move the complete RRG client to a folder without spaces if this repeats."
        )
    elif bcc_errors or len(unique_uids) > 1:
        summary = "RF INTERFERENCE — The reader is seeing a collision or unstable response"
        advice = (
            "Keep only one sticker on the HF antenna. Move the tag roll, phones, cards, metal, "
            "and every other RFID tag at least 3 feet away, then reposition the sticker and rerun "
            "Diagnosis. Do not write this tag yet."
        )
    elif not detected_uids:
        summary = "TAG NOT DETECTED — The Proxmark is connected, but the tag never answered"
        advice = (
            "Center one tag flat on the HF antenna and slowly try different positions. Test a known "
            "untouched tag. If an untouched tag works but this one does not, this tag is likely bad. "
            "If no tags work, reconnect USB and inspect the HF antenna connection."
        )
    elif len(detected_uids) < expected_scans:
        summary = "UNSTABLE TAG — It was detected only some of the time"
        advice = (
            "Do not write yet. Keep the tag still and flat, remove nearby tags or metal, and rerun "
            "Diagnosis. A safe write needs the same tag to be read consistently."
        )
    elif classic_reads != expected_scans:
        summary = "WRONG OR UNSTABLE TAG TYPE — It is not consistently Classic 1K / SAK 08"
        advice = (
            "Do not write it. This app requires a compatible MIFARE Classic 1K CUID/FUID tag that "
            "reports SAK 08 on every scan."
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
        advice = f"{capability} You can proceed to Check Tag."

    lines.extend(("", advice, "", "Diagnosis is read-only; no tag data was changed."))
    return DiagnosticReport(summary, "\n".join(lines), result.log_file)


@dataclass
class SectorState:
    sector: int
    mode: str
    auth_key: str
    auth_type: str


class SafeWriter:
    def __init__(
        self,
        runner: Pm3Runner,
        image: TagImage,
        status: Callable[[str], None],
        progress: Callable[[int, int], None],
    ):
        self.runner = runner
        self.image = image
        self.status = status
        self.progress = progress
        self.recovery_file = RECOVERY_DIR / f"{image.target_uid}-{runner.run_id}.json"
        self.recovery: dict = {
            "version": APP_VERSION,
            "created_at": utc_now(),
            "target_uid": image.target_uid,
            "filament": asdict(image.entry),
            "port": runner.port,
            "client_directory": str(runner.client_directory),
            "stage": "created",
            "sealed_sectors": [],
            "log_file": str(runner.log_file),
        }
        self.sectors: dict[int, SectorState] = {}
        self._save_recovery()

    def _save_recovery(self) -> None:
        atomic_write_json(self.recovery_file, self.recovery)

    def _set_stage(self, stage: str) -> None:
        self.recovery["stage"] = stage
        self.recovery["updated_at"] = utc_now()
        self._save_recovery()
        self.status(stage)

    def execute(self) -> None:
        self.image.validate()
        self._set_stage("Preflight: checking tag stability and every sector")
        self._preflight()
        self.progress(5, 100)
        self._set_stage("Writing and verifying ordinary data")
        self._write_data()
        self._set_stage("Compatibility test: protecting sector 15")
        if self.sectors[15].mode == "default":
            self._seal_sector(15)
        self.progress(60, 100)
        self._set_stage("Protecting sectors 1-14")
        for index, sector in enumerate(range(1, 15), start=1):
            if self.sectors[sector].mode == "default":
                self._seal_sector(sector)
            self.progress(60 + index * 2, 100)
        self._set_stage("Writing and verifying permanent UID")
        self._write_uid()
        self.progress(91, 100)
        self._set_stage("Protecting sector 0")
        if self.sectors[0].mode == "default":
            self._seal_sector(0)
        self.progress(95, 100)
        self._set_stage("Final verification")
        self._final_verify()
        self.recovery["stage"] = "complete"
        self.recovery["completed_at"] = utc_now()
        self._save_recovery()
        self.progress(100, 100)
        self.status(f"SUCCESS — tag {self.image.target_uid} is fully verified")

    def inspect(self) -> str:
        """Run the complete read-only compatibility and recovery preflight."""
        self.image.validate()
        self._set_stage("Inspection: checking stability, UID, and all 16 sectors")
        self._preflight()
        target_sectors = sorted(
            sector for sector, state in self.sectors.items() if state.mode == "target"
        )
        starting_uid = self.recovery.get("starting_uid")
        if starting_uid == FACTORY_UID and not target_sectors:
            description = "Fresh compatible tag — ready to write"
        elif starting_uid == self.image.target_uid and len(target_sectors) == 16:
            description = "Selected filament is already fully programmed; Write will verify it"
        else:
            sector_list = ", ".join(str(value) for value in target_sectors) or "none"
            description = (
                "Recoverable partial tag for this exact filament profile "
                f"(protected sectors: {sector_list})"
            )
        self.recovery["stage"] = "inspected"
        self.recovery["inspection_result"] = description
        self._save_recovery()
        self.status(description)
        return description

    def _preflight(self) -> None:
        commands = ["hf 14a reader"] * 5 + ["hf mf info"]
        test_blocks = [1] + [sector * 4 for sector in range(1, 16)]
        for block in test_blocks:
            sector = block // 4
            commands.extend(
                [
                    read_command(block, DEFAULT_KEY, "A"),
                    read_command(block, DEFAULT_KEY, "B"),
                    read_command(block, self.image.key_a(sector), "A"),
                    read_command(block, self.image.key_b(sector), "B"),
                ]
            )
        commands.extend(
            [
                read_command(0, DEFAULT_KEY, "A"),
                read_command(0, self.image.key_a(0), "A"),
                read_command(0, self.image.key_b(0), "B"),
            ]
        )
        result = self.runner.run(commands, "Preflight", timeout=240)

        events = parse_events(result.output)
        reader_events = [body for command, body in events if command == "hf 14a reader"]
        reader_uids = [
            normalize_hex(match)
            for body in reader_events
            for match in UID_RE.findall(body)
        ]
        if len(reader_events) != 5 or len(reader_uids) != 5:
            raise RuntimeError("The tag was not detected in all five stability checks")
        if any("MIFARE Classic 1K" not in body or not SAK08_RE.search(body) for body in reader_events):
            raise RuntimeError("Tag is not consistently reporting MIFARE Classic 1K / SAK 08")
        if len(set(reader_uids)) != 1:
            raise RuntimeError("More than one UID was seen. Move every other RFID tag farther away")
        if any("BCC0 incorrect" in body for body in reader_events):
            raise RuntimeError(
                "RFID collision or unstable coupling detected. Isolate one sticker and reposition it."
            )
        stable_uid = reader_uids[0]
        if stable_uid not in (FACTORY_UID, self.image.target_uid):
            raise RuntimeError(
                f"Tag UID {stable_uid} is neither blank nor the selected profile UID"
            )
        if stable_uid == FACTORY_UID and "Write Once / FUID" not in result.output:
            raise RuntimeError("Tag does not report the required write-once FUID capability")

        for block in test_blocks:
            sector = block // 4
            expected = self.image.block(block).hex().upper()
            successful = successful_block_reads(
                events,
                block,
                self.image.key_a(sector),
                self.image.key_b(sector),
            )
            target = next((item for item in successful if item[0] == "target"), None)
            default = next((item for item in successful if item[0] == "default"), None)
            selected = target or default
            if selected is None:
                raise RuntimeError(
                    f"Sector {sector} cannot be read with blank or selected-filament keys. "
                    "Use a fresh tag."
                )
            mode, key_type, key, data = selected
            if mode == "target" and data != expected:
                raise RuntimeError(
                    f"Protected sector {sector} contains different data. "
                    "It cannot be changed safely; use a fresh tag."
                )
            self.sectors[sector] = SectorState(sector, mode, key, key_type)

        block_zero_values = parse_block_rows(result.output).get(0, set())
        factory_block = next((value for value in block_zero_values if value.startswith(FACTORY_UID)), None)
        target_block = self.image.block(0).hex().upper()
        if target_block in block_zero_values and stable_uid == self.image.target_uid:
            current_uid = self.image.target_uid
        elif factory_block and stable_uid == FACTORY_UID:
            current_uid = FACTORY_UID
        else:
            raise RuntimeError(
                "Manufacturer block and over-the-air UID do not agree with a blank tag "
                "or the selected filament"
            )
        self.recovery["starting_uid"] = current_uid
        self.recovery["sector_modes"] = {
            str(sector): state.mode for sector, state in self.sectors.items()
        }
        self._save_recovery()

    def _write_data(self) -> None:
        total = 47
        complete = 0
        for sector in range(16):
            state = self.sectors[sector]
            blocks = [sector * 4 + offset for offset in range(3)]
            if sector == 0:
                blocks = [1, 2]
            commands: list[str] = []
            for block in blocks:
                expected = self.image.block(block).hex().upper()
                if state.mode == "default":
                    commands.append(write_command(block, expected, state.auth_key, state.auth_type))
                commands.extend([read_command(block, state.auth_key, state.auth_type)] * 2)
            result = self.runner.run(commands, f"Data sector {sector}", timeout=180)
            rows = parse_block_rows(result.output)
            for block in blocks:
                expected = self.image.block(block).hex().upper()
                if expected not in rows.get(block, set()):
                    if state.mode == "target":
                        raise RuntimeError(
                            f"Protected sector {sector} block {block} does not match; tag is unrecoverable"
                        )
                    self._retry_data_block(block, state, expected)
                complete += 1
                self.progress(5 + int(complete * 50 / total), 100)

    def _retry_data_block(self, block: int, state: SectorState, expected: str) -> None:
        for attempt in range(1, 4):
            commands = [
                write_command(block, expected, state.auth_key, state.auth_type),
                read_command(block, state.auth_key, state.auth_type),
                read_command(block, state.auth_key, state.auth_type),
            ]
            result = self.runner.run(commands, f"Retry block {block} ({attempt}/3)")
            if expected in parse_block_rows(result.output).get(block, set()):
                return
        raise RuntimeError(f"Block {block} could not be written and verified; tag was not locked")

    def _seal_sector(self, sector: int) -> None:
        block = 1 if sector == 0 else sector * 4
        trailer_block = sector * 4 + 3
        expected = self.image.block(block).hex().upper()
        target_a = self.image.key_a(sector)
        target_b = self.image.key_b(sector)
        trailer = self.image.trailer(sector)
        commands: list[str] = []
        for _ in range(3):
            commands.extend(
                [
                    read_command(block, target_a, "A"),
                    read_command(block, target_b, "B"),
                    write_command(trailer_block, trailer, DEFAULT_KEY, "A"),
                    read_command(block, target_a, "A"),
                    read_command(block, target_b, "B"),
                ]
            )
        result = self.runner.run(commands, f"Protect sector {sector}", timeout=180)
        successful = successful_block_reads(
            parse_events(result.output), block, target_a, target_b
        )
        confirmed = next(
            (item for item in successful if item[0] == "target" and item[3] == expected),
            None,
        )
        if confirmed is None:
            raise RuntimeError(
                f"Sector {sector} trailer state is ambiguous. Recovery record: {self.recovery_file}"
            )
        _, key_type, key, _ = confirmed
        self.sectors[sector] = SectorState(sector, "target", key, key_type)
        sealed = set(self.recovery.get("sealed_sectors", []))
        sealed.add(sector)
        self.recovery["sealed_sectors"] = sorted(sealed)
        self._save_recovery()
        self.status(f"Sector {sector} protected and verified")

    def _write_uid(self) -> None:
        target_block = self.image.block(0).hex().upper()
        target_uid = self.image.target_uid
        if self.recovery.get("starting_uid") == target_uid:
            state = self.sectors[0]
            commands = [
                read_command(0, state.auth_key, state.auth_type),
                "hf 14a reader",
                "hf 14a reader",
            ]
            result = self.runner.run(commands, "Confirm existing UID", timeout=180)
            rows = parse_block_rows(result.output).get(0, set())
            uids = {normalize_hex(value) for value in UID_RE.findall(result.output)}
            if target_block not in rows or uids != {target_uid}:
                raise RuntimeError("Existing target UID could not be confirmed safely")
            self.recovery["uid_written"] = True
            self._save_recovery()
            return
        commands = [
            read_command(0, DEFAULT_KEY, "A"),
            write_command(0, target_block, DEFAULT_KEY, "A", force=True),
            read_command(0, DEFAULT_KEY, "A"),
            read_command(0, DEFAULT_KEY, "A"),
            "hf 14a reader",
            "hf 14a reader",
        ]
        result = self.runner.run(commands, "Permanent UID", timeout=180)
        rows = parse_block_rows(result.output).get(0, set())
        uids = {normalize_hex(value) for value in UID_RE.findall(result.output)}
        if target_block not in rows or target_uid not in uids:
            raise RuntimeError(
                f"UID write could not be verified. Recovery record: {self.recovery_file}"
            )
        self.recovery["uid_written"] = True
        self._save_recovery()

    def _final_verify(self) -> None:
        commands = ["hf 14a reader", "hf 14a reader"]
        expected_blocks = [0, 1, 2]
        for sector in range(16):
            blocks = [sector * 4 + offset for offset in range(3)]
            if sector == 0:
                blocks = [0, 1, 2]
            for block in blocks:
                commands.append(read_command(block, self.image.key_a(sector), "A"))
                commands.append(read_command(block, self.image.key_b(sector), "B"))
                if block not in expected_blocks:
                    expected_blocks.append(block)
        result = self.runner.run(commands, "Full verification", timeout=300)
        if "BCC0 incorrect" in result.output:
            raise RuntimeError("Final RF stability check failed with a BCC error")
        rows = parse_block_rows(result.output)
        for block in expected_blocks:
            expected = self.image.block(block).hex().upper()
            if expected not in rows.get(block, set()):
                raise RuntimeError(f"Final verification failed at block {block}")
        uids = {normalize_hex(value) for value in UID_RE.findall(result.output)}
        if self.image.target_uid not in uids:
            raise RuntimeError("Final UID verification failed")


def discover_client_directory() -> Path | None:
    configured = load_settings().get("client_directory", "")
    if configured and (Path(configured) / "setup.bat").is_file():
        return Path(configured)
    downloads = Path.home() / "Downloads"
    matches = list(downloads.glob("rrg_other-*/client/setup.bat"))
    matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return matches[0].parent if matches else None


def discover_ports() -> list[str]:
    command = (
        "Get-CimInstance Win32_SerialPort | "
        "Where-Object {$_.Name -like '*USB Serial*'} | "
        "Select-Object -ExpandProperty DeviceID"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
        timeout=15,
    )
    return sorted(set(re.findall(r"COM\d+", result.stdout, re.IGNORECASE)))


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_settings(client_directory: str, port: str) -> None:
    atomic_write_json(
        SETTINGS_FILE,
        {"client_directory": client_directory, "port": port, "updated_at": utc_now()},
    )


class TagWriterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1080x720")
        self.minsize(900, 620)
        self.configure(bg="#10151c")
        self.entries: list[FilamentEntry] = []
        self.filtered_entries: list[FilamentEntry] = []
        self.selected_entry: FilamentEntry | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self._build_style()
        self._build_ui()
        self.after(100, self._drain_events)
        self.after(250, self._initial_load)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background="#10151c", foreground="#edf2f7", font=("Segoe UI", 10))
        style.configure("TFrame", background="#10151c")
        style.configure("Card.TFrame", background="#18212c")
        style.configure("TLabel", background="#10151c", foreground="#edf2f7")
        style.configure("Card.TLabel", background="#18212c", foreground="#edf2f7")
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 22), foreground="#45d483")
        style.configure("Sub.TLabel", foreground="#9fb0c3")
        style.configure(
            "Input.TEntry",
            fieldbackground="#ffffff",
            foreground="#101820",
            insertcolor="#101820",
            selectbackground="#1c9b5f",
            selectforeground="#ffffff",
            padding=(8, 6),
        )
        style.map(
            "Input.TEntry",
            fieldbackground=[("disabled", "#e5e7eb"), ("!disabled", "#ffffff")],
            foreground=[("disabled", "#374151"), ("!disabled", "#101820")],
        )
        style.configure(
            "Input.TCombobox",
            fieldbackground="#ffffff",
            background="#ffffff",
            foreground="#101820",
            arrowcolor="#101820",
            selectbackground="#1c9b5f",
            selectforeground="#ffffff",
            padding=(6, 4),
        )
        style.map(
            "Input.TCombobox",
            fieldbackground=[("readonly", "#ffffff"), ("disabled", "#e5e7eb")],
            foreground=[("readonly", "#101820"), ("disabled", "#374151")],
            arrowcolor=[("readonly", "#101820"), ("disabled", "#6b7280")],
        )
        self.option_add("*TCombobox*Listbox.background", "#ffffff")
        self.option_add("*TCombobox*Listbox.foreground", "#101820")
        self.option_add("*TCombobox*Listbox.selectBackground", "#1c9b5f")
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        style.configure("TButton", padding=(12, 8))
        style.configure("Write.TButton", font=("Segoe UI Semibold", 12), padding=(18, 12))
        style.map("Write.TButton", background=[("!disabled", "#1c9b5f"), ("active", "#24b872")])
        style.configure("Treeview", rowheight=30, background="#18212c", fieldbackground="#18212c")
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(22, 18))
        header.pack(fill="x")
        ttk.Label(header, text="SpoolPilot Tag Writer", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Choose filament → check one isolated tag → write and verify",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        connection = ttk.Frame(self, style="Card.TFrame", padding=14)
        connection.pack(fill="x", padx=22, pady=(0, 12))
        ttk.Label(connection, text="Proxmark folder", style="Card.TLabel").grid(row=0, column=0, sticky="w")
        self.client_var = tk.StringVar()
        ttk.Entry(connection, textvariable=self.client_var, style="Input.TEntry").grid(
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(connection, text="Browse", command=self._browse_client).grid(row=1, column=1, padx=(0, 16))
        ttk.Label(connection, text="Port", style="Card.TLabel").grid(row=0, column=2, sticky="w")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            connection,
            textvariable=self.port_var,
            width=10,
            state="readonly",
            style="Input.TCombobox",
        )
        self.port_combo.grid(row=1, column=2, padx=(0, 8))
        ttk.Button(connection, text="Refresh", command=self._refresh_ports).grid(row=1, column=3)
        connection.columnconfigure(0, weight=1)

        body = ttk.Frame(self, padding=(22, 0, 22, 0))
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="Card.TFrame", padding=14)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = ttk.Frame(body, style="Card.TFrame", padding=14, width=340)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        search_row = ttk.Frame(left, style="Card.TFrame")
        search_row.pack(fill="x", pady=(0, 10))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter_entries())
        ttk.Entry(search_row, textvariable=self.search_var, style="Input.TEntry").pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        self.update_button = ttk.Button(search_row, text="Update Library", command=self._update_catalog)
        self.update_button.pack(side="right")

        columns = ("material", "product", "color", "uid")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        for name, width in (("material", 95), ("product", 210), ("color", 150), ("uid", 95)):
            self.tree.heading(name, text=name.title())
            self.tree.column(name, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        ttk.Label(right, text="Selected filament", style="Card.TLabel", font=("Segoe UI Semibold", 12)).pack(anchor="w")
        self.selection_label = ttk.Label(
            right,
            text="Choose a filament from the list",
            style="Card.TLabel",
            wraplength=305,
            justify="left",
        )
        self.selection_label.pack(fill="x", pady=(8, 16))

        self.diagnose_button = ttk.Button(
            right,
            text="Diagnose Reader / Tag",
            command=self._diagnose_reader,
        )
        self.diagnose_button.pack(fill="x", pady=(0, 8))
        self.check_button = ttk.Button(right, text="Check Tag", command=self._check_tag)
        self.check_button.pack(fill="x", pady=(0, 8))
        self.write_button = ttk.Button(right, text="WRITE TAG", style="Write.TButton", command=self._write_tag)
        self.write_button.pack(fill="x", pady=(0, 14))

        self.progress = ttk.Progressbar(right, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 8))
        self.status_var = tk.StringVar(value="Starting…")
        ttk.Label(right, textvariable=self.status_var, style="Card.TLabel", wraplength=305).pack(fill="x")

        ttk.Label(right, text="Activity", style="Card.TLabel", font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(18, 6))
        self.log = tk.Text(
            right,
            height=15,
            bg="#0d1218",
            fg="#c9d6e2",
            insertbackground="white",
            relief="flat",
            wrap="word",
            font=("Consolas", 9),
        )
        self.log.pack(fill="both", expand=True)

        footer = ttk.Label(
            self,
            text="Only one tag may be near the Proxmark. The app verifies before permanent UID locking.",
            style="Sub.TLabel",
            padding=(22, 10),
        )
        footer.pack(fill="x")

    def _initial_load(self) -> None:
        client = discover_client_directory()
        if client:
            self.client_var.set(str(client))
        settings = load_settings()
        self._refresh_ports()
        if settings.get("port") in self.port_combo["values"]:
            self.port_var.set(settings["port"])
        cached = CatalogService(self._post_status).load_cached()
        if cached:
            self.entries = cached
            self._filter_entries()
            self._set_status(f"Library ready: {len(cached)} choices")
        else:
            self._update_catalog()

    def _browse_client(self) -> None:
        folder = filedialog.askdirectory(title="Select the RRG client folder containing setup.bat")
        if folder:
            self.client_var.set(folder)

    def _refresh_ports(self) -> None:
        try:
            ports = discover_ports()
            self.port_combo["values"] = ports
            if ports and self.port_var.get() not in ports:
                self.port_var.set(ports[0])
            self._set_status("Proxmark port detected" if ports else "No USB serial Proxmark detected")
        except Exception as exc:
            self._set_status(f"Port detection failed: {exc}")

    def _update_catalog(self) -> None:
        if self.busy:
            return
        self._start_task("catalog", lambda: CatalogService(self._post_status).update())

    def _filter_entries(self) -> None:
        query = self.search_var.get().strip().lower()
        words = query.split()
        self.filtered_entries = [
            entry for entry in self.entries if all(word in entry.search_text for word in words)
        ]
        self.tree.delete(*self.tree.get_children())
        for index, entry in enumerate(self.filtered_entries[:1500]):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(entry.material, entry.product, entry.color, entry.uid),
            )

    def _on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        self.selected_entry = self.filtered_entries[index]
        entry = self.selected_entry
        self.selection_label.configure(
            text=f"{entry.material}\n{entry.product}\n{entry.color}\nTarget UID: {entry.uid}"
        )

    def _validate_selection(self) -> tuple[FilamentEntry, Path, str]:
        if self.selected_entry is None:
            raise ValueError("Select a filament first")
        client, port = self._validate_reader_selection()
        return self.selected_entry, client, port

    def _validate_reader_selection(self) -> tuple[Path, str]:
        client = Path(self.client_var.get().strip())
        port = self.port_var.get().strip().upper()
        runner = Pm3Runner(client, port, self._post_log)
        runner.validate()
        save_settings(str(client), port)
        return client, port

    def _diagnose_reader(self) -> None:
        try:
            client, port = self._validate_reader_selection()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            return
        ready = messagebox.askokcancel(
            "Read-only reader/tag diagnosis",
            "This test will not write anything.\n\n"
            "1. Move every other RFID tag, the tag roll, cards, phones, and metal at least 3 feet away.\n"
            "2. Put exactly one tag flat and centered on the Proxmark HF antenna.\n"
            "3. Keep the tag still until the test finishes.\n\n"
            "Start diagnosis?",
            parent=self,
        )
        if not ready:
            return

        def task():
            runner = Pm3Runner(client, port, self._post_log)
            commands = ["hw version"] + ["hf 14a reader"] * 10 + ["hf mf info"]
            result = runner.run(commands, "Read-only diagnosis", timeout=180)
            return analyze_reader_diagnostic(result, expected_scans=10)

        self._start_task("diagnose", task)

    def _check_tag(self) -> None:
        try:
            entry, client, port = self._validate_selection()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            return

        def task():
            image = CatalogService(self._post_status).download(entry)
            runner = Pm3Runner(client, port, self._post_log)
            writer = SafeWriter(runner, image, self._post_status, self._post_progress)
            return writer.inspect()

        self._start_task("check", task)

    def _write_tag(self) -> None:
        try:
            entry, client, port = self._validate_selection()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            return
        confirmed = messagebox.askyesno(
            "Write one-time tag",
            f"Write {entry.label}?\n\n"
            "Use exactly one isolated tag. The UID lock is permanent and occurs only after "
            "all ordinary data verifies.\n\nContinue?",
            icon="warning",
            parent=self,
        )
        if not confirmed:
            return

        def task():
            image = CatalogService(self._post_status).download(entry)
            runner = Pm3Runner(client, port, self._post_log)
            writer = SafeWriter(runner, image, self._post_status, self._post_progress)
            writer.execute()
            return f"SUCCESS — {entry.label}\nUID {image.target_uid}\n\nThe tag is ready to test in the AMS."

        self._start_task("write", task)

    def _start_task(self, kind: str, function: Callable[[], object]) -> None:
        if self.busy:
            return
        self.busy = True
        self._set_controls(False)
        self.progress["value"] = 0

        def worker():
            try:
                result = function()
                self.events.put((f"{kind}_done", result))
            except Exception as exc:
                details = traceback.format_exc()
                self.events.put(("error", (str(exc), details)))

        threading.Thread(target=worker, daemon=True).start()

    def _set_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (
            self.update_button,
            self.diagnose_button,
            self.check_button,
            self.write_button,
        ):
            widget.configure(state=state)

    def _show_diagnostic_report(self, report: DiagnosticReport) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("SpoolPilot Reader / Tag Diagnosis")
        dialog.geometry("760x520")
        dialog.minsize(620, 420)
        dialog.configure(bg="#10151c")
        dialog.transient(self)

        heading_color = "#45d483" if report.summary.startswith("PASS") else "#ffb454"
        tk.Label(
            dialog,
            text=report.summary,
            bg="#10151c",
            fg=heading_color,
            font=("Segoe UI Semibold", 15),
            wraplength=700,
            justify="left",
        ).pack(fill="x", padx=20, pady=(18, 10))

        report_box = tk.Text(
            dialog,
            bg="#ffffff",
            fg="#101820",
            selectbackground="#1c9b5f",
            selectforeground="#ffffff",
            insertbackground="#101820",
            wrap="word",
            relief="flat",
            font=("Segoe UI", 10),
            padx=12,
            pady=12,
        )
        report_box.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        report_box.insert("1.0", report.display_text)
        report_box.configure(state="disabled")

        buttons = ttk.Frame(dialog, padding=(20, 0, 20, 18))
        buttons.pack(fill="x")

        def copy_report() -> None:
            dialog.clipboard_clear()
            dialog.clipboard_append(report.display_text)

        ttk.Button(buttons, text="Copy Report", command=copy_report).pack(side="left")
        if hasattr(os, "startfile"):
            ttk.Button(
                buttons,
                text="Open Logs Folder",
                command=lambda: os.startfile(str(report.log_file.parent)),
            ).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="right")
        dialog.grab_set()

    def _post_status(self, message: str) -> None:
        self.events.put(("status", message))

    def _post_log(self, message: str) -> None:
        self.events.put(("log", message))

    def _post_progress(self, value: int, maximum: int) -> None:
        self.events.put(("progress", (value, maximum)))

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)
        self.log.insert("end", f"{datetime.now().strftime('%H:%M:%S')}  {message}\n")
        self.log.see("end")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self._set_status(str(payload))
                elif kind == "log":
                    self._set_status(str(payload))
                elif kind == "progress":
                    value, maximum = payload
                    self.progress["maximum"] = maximum
                    self.progress["value"] = value
                elif kind == "catalog_done":
                    self.entries = payload
                    self._filter_entries()
                    self._set_status(f"Library ready: {len(self.entries)} choices")
                    self.busy = False
                    self._set_controls(True)
                elif kind in ("check_done", "write_done"):
                    self.busy = False
                    self._set_controls(True)
                    self._set_status(str(payload))
                    messagebox.showinfo(APP_NAME, str(payload), parent=self)
                elif kind == "diagnose_done":
                    self.busy = False
                    self._set_controls(True)
                    report = payload
                    self._set_status(report.summary)
                    self._show_diagnostic_report(report)
                elif kind == "error":
                    message, details = payload
                    self.busy = False
                    self._set_controls(True)
                    self._set_status(f"STOPPED — {message}")
                    error_file = LOG_DIR / f"error-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
                    error_file.parent.mkdir(parents=True, exist_ok=True)
                    error_file.write_text(details, encoding="utf-8")
                    messagebox.showerror(
                        APP_NAME,
                        f"{message}\n\nNothing further was attempted.\nDiagnostic: {error_file}",
                        parent=self,
                    )
        except queue.Empty:
            pass
        self.after(100, self._drain_events)


def main() -> None:
    for directory in (APP_DIR, CACHE_DIR, LOG_DIR, RECOVERY_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    app = TagWriterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
