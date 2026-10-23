"""Block legacy USB paths; allow only explicitly recorded scoped operations."""

from pathlib import Path
import json

BLOCK_FILE = Path(__file__).resolve().with_name("USB_ACCESS_DISABLED")
RESUME_FILE = Path(__file__).resolve().parent / "results/hardware-resume.json"
SCOPED_OPERATIONS = frozenset({"device_descriptor_read"})


def require_usb_access(operation=None):
    if BLOCK_FILE.exists():
        if operation in SCOPED_OPERATIONS and RESUME_FILE.is_file():
            try:
                approval = json.loads(RESUME_FILE.read_text())
            except (OSError, ValueError):
                approval = {}
            if (isinstance(approval, dict) and approval.get("user_authorized_hardware") is True
                    and isinstance(approval.get("operations"), list)
                    and operation in approval["operations"]):
                return
        raise SystemExit(
            "This USB entry point remains blocked after macOS kernel panics. "
            f"Pause file: {BLOCK_FILE}. Offline analysis remains available. "
            "Use the authorized native IOUSBHost flow described in HARDWARE_RESUME.md."
        )
