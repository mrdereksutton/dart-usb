"""Build and run one restored, read-only call into the resident ROM flash API."""

from pathlib import Path
import struct
import subprocess
import tempfile

import setup_marker

SOURCE_ADDRESS = 0x020BE8A0
CODE_ADDRESS = 0x00211E30
RESULT_ADDRESS = 0x00211E90
STATUS_ADDRESS = 0x00211F04


def elf_text(data):
    if data[:7] != b"\x7fELF\x01\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 40:
        raise RuntimeError("Expected a little-endian ARM ELF32 object")
    offset = struct.unpack_from("<I", data, 32)[0]
    stride, count, strings_index = struct.unpack_from("<HHH", data, 46)
    if stride != 40 or offset + stride * count > len(data) or strings_index >= count:
        raise RuntimeError("Malformed ELF section table")
    sections = [struct.unpack_from("<10I", data, offset + stride * index) for index in range(count)]
    table = sections[strings_index]
    names = data[table[4]:table[4] + table[5]]
    for index, section in enumerate(sections):
        name = names[section[0]:].split(b"\0", 1)[0]
        if name == b".text":
            if any(s[1] in (4, 9) and s[7] == index and s[5] for s in sections):
                raise RuntimeError("RAM helper contains unresolved text relocations")
            start, size = section[4:6]
            if start + size > len(data):
                raise RuntimeError("Truncated helper code")
            return data[start:start + size]
    raise RuntimeError("RAM helper has no text section")


def build_helper(callback):
    setup_marker.marker_trampoline(callback)  # Apply the same callback bound.
    source = Path(__file__).resolve().parent / "firmware/flash_read_helper.S"
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "helper.o"
        subprocess.run(["xcrun", "clang", "-target", "armv8m.main-none-eabi", "-mcpu=cortex-m33",
                        "-mthumb", "-c", f"-DORIGINAL_CALLBACK=0x{callback:08x}", str(source),
                        "-o", str(target)], check=True, capture_output=True)
        return elf_text(target.read_bytes())


def test_native_flash_read(read_word, write_word, get_descriptor, report, checkpoint):
    pointer = int.from_bytes(read_word(0x0002018C), "little")
    if pointer != 0x0000CBB5:
        raise RuntimeError("ROM flash-read vtable entry changed")
    expected = b"".join(read_word(SOURCE_ADDRESS + offset) for offset in range(0, 16, 4))
    report["native_flash_read"] = {"entry": "0x0000cbb5", "source": f"0x{SOURCE_ADDRESS:08x}",
                                    "expected_bytes": expected.hex(" ")}

    def validate(reader, hook):
        status = int.from_bytes(reader(STATUS_ADDRESS), "little")
        data = b"".join(reader(RESULT_ADDRESS + offset) for offset in range(0, 16, 4))
        hook["native_status"] = f"0x{status:08x}"
        hook["native_read_bytes"] = data.hex(" ")
        hook["native_read_matches"] = data == expected
        if status != 0x18 or data != expected:
            raise RuntimeError("Native flash read returned different status or bytes")

    extra = (STATUS_ADDRESS,) + tuple(RESULT_ADDRESS + offset for offset in range(0, 16, 4))
    setup_marker.test_setup_marker(read_word, write_word, get_descriptor, report, checkpoint,
                                  helper_factory=build_helper, extra_addresses=extra,
                                  validate_result=validate, code_address=CODE_ADDRESS)
