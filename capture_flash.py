"""Capture a bounded prefix from the actual 0x02000000 flash address region."""

import hashlib
import os

FLASH_BASE = 0x02000000
FLASH_BYTES = 0x200000
ALLOWED_LENGTHS = (256, 4096, 65536, FLASH_BYTES)


def capture_flash(read_word, path, length, report, checkpoint):
    if length not in ALLOWED_LENGTHS:
        raise ValueError("Flash capture length must be 256, 4096, 65536 or 2097152")
    report.update(start_address=f"0x{FLASH_BASE:08x}", requested_bytes=length,
                  bytes_read=0, binary_file=path.name, capture_status="in_progress")
    digest = hashlib.sha256()
    with path.open("xb") as saved:
        try:
            for offset in range(0, length, 4):
                address = FLASH_BASE + offset
                report["last_attempted_address"] = f"0x{address:08x}"
                data = read_word(address)
                if len(data) != 4:
                    raise RuntimeError(f"Short flash read at 0x{address:08x}")
                saved.write(data)
                digest.update(data)
                report["bytes_read"] += 4
                if report["bytes_read"] % 4096 == 0:
                    saved.flush()
                    os.fsync(saved.fileno())
                    report["binary_sha256"] = digest.hexdigest()
                    checkpoint()
                if report["bytes_read"] % 65536 == 0:
                    print(f"Flash captured: {report['bytes_read']}/{length} bytes", flush=True)
            report["capture_status"] = "complete"
        except (Exception, KeyboardInterrupt) as error:
            report.update(capture_status="partial", capture_error=str(error) or "Interrupted")
            raise
        finally:
            saved.flush()
            os.fsync(saved.fileno())
            report["binary_sha256"] = digest.hexdigest()
            checkpoint()
