"""Bounded inspection and a restored string-index edit of the captured USB object."""

COMPOSITE = 0x0030D180
HEAP_START, HEAP_END = 0x00300000, 0x00314000


def checked_heap(address, size):
    if address & 3 or not HEAP_START <= address < address + size <= HEAP_END:
        raise RuntimeError(f"Object at 0x{address:08x} is outside the captured heap")
    return address


def read_descriptor(read_word, address):
    first = read_word(address)
    if len(first) != 4 or first[:2] != b"\x12\x01":
        raise RuntimeError(f"Device descriptor header absent at 0x{address:08x}")
    words = [first] + [read_word(address + offset) for offset in (4, 8, 12, 16)]
    if any(len(word) != 4 for word in words):
        raise RuntimeError("Incomplete descriptor word")
    return b"".join(words)[:18]


def inspect_heap_descriptor(read_word, standard, report):
    """Check the snapshot's composite/driver/template relationship, 12 words."""
    if (len(standard) != 18 or standard[:2] != b"\x12\x01"
            or standard[8:12] != bytes.fromhex("05 0b 70 1d")):
        raise RuntimeError("Unexpected standard BT600 device descriptor")
    address = COMPOSITE + 0x0C
    report["composite_address"] = f"0x{COMPOSITE:08x}"
    report["descriptor_address"] = f"0x{address:08x}"
    descriptor = read_descriptor(read_word, address)
    report["descriptor"] = {"raw": descriptor.hex(" ")}
    if descriptor != standard:
        raise RuntimeError("Captured composite descriptor differs from current EP0 response")
    driver = checked_heap(int.from_bytes(read_word(COMPOSITE + 0x30), "little"), 0x38)
    report["driver_address"] = f"0x{driver:08x}"
    template = checked_heap(int.from_bytes(read_word(driver + 4), "little"), 20)
    report["template_address"] = f"0x{template:08x}"
    raw = read_descriptor(read_word, template)
    report["template_descriptor"] = raw.hex(" ")
    if raw[:7] + raw[8:] != standard[:7] + standard[8:] or raw[7] not in (8, 16, 32, 64):
        raise RuntimeError("Template/composite relationship changed")
    if template == address:
        raise RuntimeError("Template and composite unexpectedly alias")
    return address


def inspect_setup_handler(read_word, standard, report, code_bytes=32):
    """Read a bounded prefix of the validated driver's actual setup callback."""
    if code_bytes not in (32, 1024):
        raise ValueError("Setup capture is limited to 32 or 1024 bytes")
    inspect_heap_descriptor(read_word, standard, report)
    driver = int(report["driver_address"], 16)
    callback = int.from_bytes(read_word(driver + 0x34), "little")
    report["setup_callback"] = f"0x{callback:08x}"
    if not callback & 1 or not 0x02000000 <= callback < 0x021FFFE0:
        raise RuntimeError("Setup callback is outside the ROM driver's first flash region")
    start = callback & ~3
    if (start & ~0xFFF) != ((start + code_bytes - 1) & ~0xFFF):
        raise RuntimeError("Setup capture would cross its validated flash page")
    report["setup_code_address"] = f"0x{start:08x}"
    code = bytearray()
    for offset in range(0, code_bytes, 4):
        code.extend(read_word(start + offset))
        report["setup_code"] = code.hex(" ")


def test_product_string(read_word, write_word, get_descriptor, report, checkpoint,
                        template=False):
    """Change only iProduct to the existing iManufacturer index, then restore.

    Save the original word before touching RAM. A write may have applied even
    when its acknowledgment fails, so restoration starts after every attempt.
    """
    baseline = get_descriptor()
    report["baseline_device_descriptor"] = baseline.hex(" ")
    address = inspect_heap_descriptor(read_word, baseline, report)
    if baseline[14:16] != b"\x01\x02":
        raise RuntimeError("Expected existing manufacturer/product indexes 1 and 2")
    target = (int(report["template_address"], 16) if template else address) + 12
    original = read_word(target)
    if original != baseline[12:16]:
        raise RuntimeError("Descriptor changed before the edit")
    replacement = original[:3] + baseline[14:15]
    expected = baseline[:15] + baseline[14:15] + baseline[16:]
    edit = report["edit"] = {
        "address": f"0x{target:08x}", "original_word": original.hex(" "),
        "temporary_word": replacement.hex(" "), "stage": "prepared",
        "restore_required": True,
    }
    checkpoint()
    try:
        edit["stage"] = "write_attempted"
        write_word(target, replacement)
        readback = read_word(target)
        edit["temporary_readback"] = readback.hex(" ")
        if readback != replacement:
            raise RuntimeError("Temporary descriptor write did not read back")
        observed = get_descriptor()
        edit["temporary_usb_descriptor"] = observed.hex(" ")
        edit["word_after_usb_request"] = read_word(target).hex(" ")
        edit["composite_word_after_usb_request"] = read_word(address + 12).hex(" ")
        edit["usb_changed_as_expected"] = observed == expected
        edit["usb_differing_offsets"] = [
            index for index, pair in enumerate(zip(baseline, observed)) if pair[0] != pair[1]
        ]
        if len(observed) != 18 or observed not in (baseline, expected):
            raise RuntimeError("USB descriptor changed beyond the intended string index")
    except (Exception, KeyboardInterrupt) as error:
        edit["experiment_error"] = str(error) or "Interrupted"
        raise
    finally:
        try:
            edit["stage"] = "restoring"
            write_word(target, original)
            restored = read_word(target)
            edit["restored_word"] = restored.hex(" ")
            if restored != original:
                raise RuntimeError("Original descriptor word failed restoration")
            observed = get_descriptor()
            edit["restored_usb_descriptor"] = observed.hex(" ")
            if observed != baseline:
                raise RuntimeError("Restored USB descriptor differs from baseline")
            edit.update(stage="restored", restore_required=False)
        except (Exception, KeyboardInterrupt) as error:
            edit["restore_error"] = str(error) or "Interrupted during restoration"
            raise
        finally:
            checkpoint()
