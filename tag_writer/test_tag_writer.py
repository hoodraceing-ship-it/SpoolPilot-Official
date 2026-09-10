import importlib.machinery
import importlib.util
import re
import sys
import tempfile
from pathlib import Path


SOURCE = Path(__file__).with_name("SpoolPilotTagWriter.pyw")
loader = importlib.machinery.SourceFileLoader("spoolpilot_tag_writer", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = module
loader.exec_module(module)


def test_key_file_layout_and_trailer():
    dump = bytearray(1024)
    dump[0:5] = bytes.fromhex("064729CEA6")
    dump[7 * 16 + 6 : 7 * 16 + 10] = bytes.fromhex("87878769")
    keys = bytes(range(192))
    entry = module.FilamentEntry("x", "PETG", "Basic", "Black", "064729CE", "d", "k")
    image = module.TagImage(entry, bytes(dump), keys, Path("d"), Path("k"))
    assert image.key_a(1) == "060708090A0B"
    assert image.key_b(1) == "666768696A6B"
    assert image.trailer(1) == "060708090A0B87878769666768696A6B"


def test_block_parser():
    output = "[=]  10 | 00 00 00 00 AB 0F 00 00 00 00 00 00 00 00 00 00 | ................"
    rows = module.parse_block_rows(output)
    assert rows[10] == {"00000000AB0F00000000000000000000"}


def test_command_shapes():
    assert module.read_command(10, "FFFFFFFFFFFF") == "hf mf rdbl --blk 10 -k FFFFFFFFFFFF"
    assert module.read_command(10, "123456789ABC", "B") == "hf mf rdbl --blk 10 -b -k 123456789ABC"
    assert module.write_command(3, "00" * 16, "FFFFFFFFFFFF").startswith("hf mf wrbl --blk 3")
    assert module.write_command(0, "00" * 16, "FFFFFFFFFFFF", force=True).endswith(" --force")


def test_event_and_auth_parser_handles_script_prompt():
    output = """[usb|script] pm3 --> hf mf rdbl --blk 4 -b -k 560E992E4C49
[=]   # | sector 01 / 0x01                                | ascii
[=] ----+-------------------------------------------------+-----------------
[=]   4 | 54 47 54 47 00 00 00 00 00 00 00 00 00 00 00 00 | TGTG............
[usb|script] pm3 --> hf mf rdbl --blk 8 -k FFFFFFFFFFFF
[#] Auth error
"""
    events = module.parse_events(output)
    assert len(events) == 2
    reads = module.successful_block_reads(events, 4, "F7575566FA09", "560E992E4C49")
    assert reads == [("target", "B", "560E992E4C49", "54475447000000000000000000000000")]


def test_blank_sector_auth_does_not_require_target_data():
    output = """[usb|script] pm3 --> hf mf rdbl --blk 4 -k FFFFFFFFFFFF
[=]   # | sector 01 / 0x01                                | ascii
[=] ----+-------------------------------------------------+-----------------
[=]   4 | 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 | ................
"""
    reads = module.successful_block_reads(
        module.parse_events(output), 4, "F7575566FA09", "560E992E4C49"
    )
    assert reads == [("default", "A", "FFFFFFFFFFFF", "0" * 32)]


def make_image():
    dump = bytearray(1024)
    uid = bytes.fromhex("064729CE")
    dump[0:4] = uid
    dump[4] = module.xor_bcc(uid)
    dump[5:8] = bytes.fromhex("080400")
    keys = bytearray(192)
    for sector in range(16):
        key_a = bytes(((sector * 13 + offset + 1) % 255) for offset in range(6))
        key_b = bytes(((sector * 17 + offset + 101) % 255) for offset in range(6))
        keys[sector * 6 : sector * 6 + 6] = key_a
        keys[96 + sector * 6 : 102 + sector * 6] = key_b
        for offset in range(3):
            block = sector * 4 + offset
            if block != 0:
                dump[block * 16 : (block + 1) * 16] = bytes([block]) * 16
        trailer = sector * 4 + 3
        dump[trailer * 16 : (trailer + 1) * 16] = (
            key_a + bytes.fromhex("87878769") + key_b
        )
    entry = module.FilamentEntry(
        "PETG • Basic • Black", "PETG", "Basic", "Black", "064729CE", "d", "k"
    )
    return module.TagImage(entry, bytes(dump), bytes(keys), Path("d"), Path("k"))


class FakeRunner:
    def __init__(self, image, directory, presealed=()):
        self.image = image
        self.port = "COM9"
        self.client_directory = directory
        self.run_id = "test"
        self.log_file = directory / "fake.log"
        self.uid = module.FACTORY_UID
        self.blocks = {block: "0" * 32 for block in range(64)}
        self.blocks[0] = module.FACTORY_UID + "AA080400" + "0" * 16
        self.mode = {sector: "default" for sector in range(16)}
        self.writes = []
        for sector in presealed:
            self.mode[sector] = "target"
            for offset in range(3):
                block = sector * 4 + offset
                if block:
                    self.blocks[block] = image.block(block).hex().upper()
            trailer = sector * 4 + 3
            self.blocks[trailer] = image.block(trailer).hex().upper()

    def _auth_ok(self, command, sector):
        key_match = re.search(r"-k\s+([0-9A-F]{12})", command)
        if not key_match:
            return False
        key = key_match.group(1)
        key_type = "B" if re.search(r"(?:^|\s)-b(?:\s|$)", command) else "A"
        if self.mode[sector] == "default":
            return key == module.DEFAULT_KEY
        expected = self.image.key_b(sector) if key_type == "B" else self.image.key_a(sector)
        return key == expected

    def run(self, commands, phase, timeout=300):
        output = []
        for command in commands:
            output.append(f"[usb|script] pm3 --> {command}")
            if command == "hf 14a reader":
                output.extend([
                    "[+]  UID: " + " ".join(self.uid[i:i+2] for i in range(0, 8, 2)),
                    "[+]  SAK: 08 [2]",
                    "[+]    MIFARE Classic 1K",
                ])
            elif command == "hf mf info":
                output.append("[+] Magic capabilities... Write Once / FUID")
            elif command.startswith("hf mf rdbl"):
                block = int(re.search(r"--blk\s+(\d+)", command).group(1))
                if self._auth_ok(command, block // 4):
                    spaced = " ".join(
                        self.blocks[block][i:i+2] for i in range(0, 32, 2)
                    )
                    output.append(f"[=]  {block:2d} | {spaced} | ................")
                else:
                    output.append("[#] Auth error")
            elif command.startswith("hf mf wrbl"):
                block = int(re.search(r"--blk\s+(\d+)", command).group(1))
                data = re.search(r"-d\s+([0-9A-F]{32})", command).group(1)
                sector = block // 4
                if self._auth_ok(command, sector):
                    if block == 0:
                        assert "--force" in command
                        assert self.uid == module.FACTORY_UID
                        self.uid = data[:8]
                    self.blocks[block] = data
                    if block % 4 == 3:
                        self.mode[sector] = "target"
                    self.writes.append(block)
                    output.append("[+] Write ( ok )")
                else:
                    output.append("[-] Write ( fail )")
        return module.Pm3Result("\n".join(output) + "\n", 0, self.log_file)


def test_full_safe_writer_flow_and_resume():
    image = make_image()
    with tempfile.TemporaryDirectory() as folder:
        old_recovery = module.RECOVERY_DIR
        module.RECOVERY_DIR = Path(folder) / "recovery"
        try:
            runner = FakeRunner(image, Path(folder), presealed=(1,))
            # Simulate the user's recoverable state: data is present and sector 1 is sealed.
            for block in range(1, 63):
                if block % 4 != 3:
                    runner.blocks[block] = image.block(block).hex().upper()
            writer = module.SafeWriter(runner, image, lambda _message: None, lambda *_: None)
            writer.execute()
            assert runner.uid == image.target_uid
            assert all(mode == "target" for mode in runner.mode.values())
            assert runner.blocks == {
                block: image.block(block).hex().upper() for block in range(64)
            }
            # A resumed, already-complete tag is verification-only and writes nothing.
            runner.writes.clear()
            writer = module.SafeWriter(runner, image, lambda _message: None, lambda *_: None)
            writer.execute()
            assert runner.writes == []
        finally:
            module.RECOVERY_DIR = old_recovery


def test_mismatched_protected_sector_stops_before_any_write():
    image = make_image()
    with tempfile.TemporaryDirectory() as folder:
        old_recovery = module.RECOVERY_DIR
        module.RECOVERY_DIR = Path(folder) / "recovery"
        try:
            runner = FakeRunner(image, Path(folder), presealed=(1,))
            runner.blocks[4] = "DE" * 16
            writer = module.SafeWriter(runner, image, lambda _message: None, lambda *_: None)
            try:
                writer.execute()
            except RuntimeError as exc:
                assert "Protected sector 1 contains different data" in str(exc)
            else:
                raise AssertionError("A mismatched protected sector was accepted")
            assert runner.writes == []
            assert runner.uid == module.FACTORY_UID
        finally:
            module.RECOVERY_DIR = old_recovery


if __name__ == "__main__":
    test_key_file_layout_and_trailer()
    test_block_parser()
    test_command_shapes()
    test_event_and_auth_parser_handles_script_prompt()
    test_blank_sector_auth_does_not_require_target_data()
    test_full_safe_writer_flow_and_resume()
    test_mismatched_protected_sector_stops_before_any_write()
    print("All tests passed")
