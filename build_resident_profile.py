"""Build a small relocated RAM trial using descriptors from the existing core."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from arm_object_loader import load_arm_objects
from native_flash_read import elf_text

ROOT = Path(__file__).resolve().parent


def build(directory, base=0x00312280):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    extractor = directory / "extract.c"
    extractor.write_text('#include <stdio.h>\n#include "usb_bridge.c"\n'
        'int main(void) { uint8_t report[96]; dart_iap_report_descriptor(report,96); '
        'fwrite(device_descriptor,1,sizeof(device_descriptor),stdout); '
        'fwrite(configuration_descriptor,1,sizeof(configuration_descriptor),stdout); '
        'fwrite(report,1,96,stdout); return ferror(stdout); }\n')
    subprocess.run(["xcrun", "clang", "-std=c11", "-Os", "-I", str(ROOT / "firmware"),
        str(extractor), str(ROOT / "firmware/usb_audio_source.c"), str(ROOT / "firmware/iap_hid.c"),
        "-o", str(directory / "extract")], check=True, capture_output=True)
    descriptors = subprocess.check_output([str(directory / "extract")])
    if len(descriptors) != 242:
        raise RuntimeError("Unexpected portable descriptor sizes")
    arrays = {"resident_device": descriptors[:18], "resident_configuration": descriptors[18:146],
              "resident_report": descriptors[146:]}
    (directory / "resident_profile_descriptors.h").write_text("\n".join(
        f"static const uint8_t {name}[] = {{" + ",".join(str(b) for b in data) + "};"
        for name, data in arrays.items()) + "\n")
    objects = []
    for source in ("resident_profile_trial.c", "resident_heap_helper.S"):
        target = directory / (Path(source).stem + ".o")
        subprocess.run(["xcrun", "clang", "-target", "armv8m.main-none-eabi", "-mcpu=cortex-m33+nodsp",
            "-mthumb", "-mno-unaligned-access", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-Os",
            "-Wall", "-Wextra", "-Werror", "-I", str(directory), "-I", str(ROOT / "firmware"),
            "-c", str(ROOT / "firmware" / source), "-o", str(target)], check=True, capture_output=True)
        objects.append(target)

    class MemoryImage:
        def mem_map(self, address, size):
            if address != base or size > 4096:
                raise RuntimeError("Resident image exceeds its allocated block")

        def mem_write(self, address, data):
            self.image = data

    memory = MemoryImage()
    symbols, layout = load_arm_objects(memory, objects[:1], base=base)
    used = (len(memory.image.rstrip(b"\0")) + 3) & ~3
    image = memory.image[:used]  # native allocator already zeroed the BSS/tail
    (directory / "resident-profile.bin").write_bytes(image)
    helper = elf_text(objects[1].read_bytes())
    if not helper or len(helper) > 192 or len(helper) % 4:
        raise RuntimeError("Invalid resident allocator helper")
    (directory / "resident-heap-helper.bin").write_bytes(helper)
    manifest = {"base": base, "allocation_bytes": 4096, "upload_bytes": len(image),
        "image_hex": image.hex(" "), "sha256": hashlib.sha256(image).hexdigest(),
        "helper_sha256": hashlib.sha256(helper).hexdigest(), "symbols": symbols,
        "descriptors": {name: data.hex(" ") for name, data in arrays.items()}, "arm_image": layout,
        "source_sha256": {name: hashlib.sha256((ROOT / "firmware" / name).read_bytes()).hexdigest()
            for name in ("resident_profile_trial.c", "resident_heap_helper.S", "usb_bridge.c", "iap_hid.c")}}
    (directory / "resident-profile.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest, objects[:1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=lambda text: int(text, 0), default=0x00312280)
    parser.add_argument("--output", type=Path, default=ROOT / "results/native-host-build/resident")
    args = parser.parse_args()
    manifest, _ = build(args.output, args.base)
    print(json.dumps({k: manifest[k] for k in ("base", "upload_bytes", "sha256", "symbols")}, indent=2))
