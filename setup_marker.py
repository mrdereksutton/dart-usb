"""Temporarily route the live USB setup callback through a marker trampoline."""

import struct

from descriptor_edit import inspect_heap_descriptor

CODE_ADDRESS = 0x00211F20
MARKER_ADDRESS = 0x00211F00
MARKER_VALUE = 0xD47A6001


def marker_trampoline(callback):
    if not callback & 1 or not 0x02000000 <= callback < 0x02200000:
        raise RuntimeError("Unexpected original setup callback")
    # Preserve r0/r1 and SP; no flags or argument registers change. Tail-call the
    # original handler through a PC literal so LR and all stacked args survive.
    instructions = bytes.fromhex("03 b4 03 48 03 49 08 60 03 bc 00 bf df f8 08 f0")
    return instructions + struct.pack("<III", MARKER_VALUE, MARKER_ADDRESS, callback)


def test_setup_marker(read_word, write_word, get_descriptor, report, checkpoint):
    baseline = get_descriptor()
    inspect_heap_descriptor(read_word, baseline, report)
    driver = int(report["driver_address"], 16)
    callback_address = driver + 0x34
    original_callback = read_word(callback_address)
    callback = int.from_bytes(original_callback, "little")
    code = marker_trampoline(callback)
    original_code = b"".join(read_word(CODE_ADDRESS + offset)
                             for offset in range(0, len(code), 4))
    original_marker = read_word(MARKER_ADDRESS)
    if original_code != bytes(len(code)) or original_marker != bytes(4):
        raise RuntimeError("Borrowed scratch words are in use; no callback change attempted")
    hook = report["marker_hook"] = {
        "callback_address": f"0x{callback_address:08x}",
        "original_callback": original_callback.hex(" "),
        "code_address": f"0x{CODE_ADDRESS:08x}",
        "original_code": original_code.hex(" "), "helper_code": code.hex(" "),
        "marker_address": f"0x{MARKER_ADDRESS:08x}",
        "original_marker": original_marker.hex(" "),
        "expected_marker": f"0x{MARKER_VALUE:08x}",
        "restore_required": True, "stage": "prepared",
    }
    checkpoint()
    callback_attempted = False
    try:
        hook["stage"] = "writing_helper"
        for offset in range(0, len(code), 4):
            data = code[offset:offset + 4]
            write_word(CODE_ADDRESS + offset, data)
            if read_word(CODE_ADDRESS + offset) != data:
                raise RuntimeError("RAM helper failed readback")
        if read_word(callback_address) != original_callback:
            raise RuntimeError("Setup callback changed before installation")
        callback_attempted = True
        hook["stage"] = "installing_callback"
        write_word(callback_address, (CODE_ADDRESS | 1).to_bytes(4, "little"))
        hook["stage"] = "triggering"
        observed = get_descriptor()
        hook["trigger_descriptor"] = observed.hex(" ")
        marker = read_word(MARKER_ADDRESS)
        hook["observed_marker"] = marker.hex(" ")
        hook["marker_matched"] = int.from_bytes(marker, "little") == MARKER_VALUE
        if observed != baseline:
            raise RuntimeError("Original setup handler no longer returns its baseline descriptor")
        if not hook["marker_matched"]:
            raise RuntimeError("USB callback returned, but the RAM execution marker was absent")
    except (Exception, KeyboardInterrupt) as error:
        hook["experiment_error"] = str(error) or "Interrupted"
        raise
    finally:
        try:
            hook["stage"] = "restoring"
            # Never remove the helper while a callback may still point to it.
            if callback_attempted:
                write_word(callback_address, original_callback)
                if read_word(callback_address) != original_callback:
                    raise RuntimeError("Original callback failed restoration; helper left intact")
            for offset in range(0, len(original_code), 4):
                data = original_code[offset:offset + 4]
                write_word(CODE_ADDRESS + offset, data)
                if read_word(CODE_ADDRESS + offset) != data:
                    raise RuntimeError("Original scratch word failed restoration")
            write_word(MARKER_ADDRESS, original_marker)
            if read_word(MARKER_ADDRESS) != original_marker:
                raise RuntimeError("Original marker word failed restoration")
            if get_descriptor() != baseline:
                raise RuntimeError("USB baseline changed after callback restoration")
            hook.update(stage="restored", restore_required=False)
        except (Exception, KeyboardInterrupt) as error:
            hook["restore_error"] = str(error) or "Interrupted during restoration"
            raise
        finally:
            checkpoint()
