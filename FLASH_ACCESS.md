# Dongle flash access plan (direct SPI, bypasses the USB wall)

The USB path is walled: fc61 cannot read the 0x100000..0x200000 code bank or the
patch-RAM, and no vendor command reaches them. But the dongle's firmware lives in
a **discrete external SPI flash chip**, which can be read and written directly,
with no RTL8761 cooperation. This bypasses fc61 entirely.

## Evidence the flash is a discrete, accessible chip

- The ROM's flash geometry table (read live at 0x00280734) holds JEDEC ID
  `EF 40 15` = **Winbond W25Q16** (2 MB, 16 Mbit). That ID is returned by the
  flash chip's RDID command, so a real chip is present and was probed at init.
- Winbond W25Qxx parts are standalone SPI NOR chips in SOIC-8 (209 mil) or USON-8
  packages, separate from the Realtek controller.
- fc61 reads a coherent firmware image mapped at 0x200000 (Thumb code plus a
  ">>> Platform Ext" string), consistent with flash-resident firmware.

## Why this is the way in

A SOIC-8/USON-8 SPI flash can be dumped and reprogrammed with an $5 USB
programmer and a clip, giving:
- A COMPLETE flash image (the whole firmware, including the 0x100000..0x200000
  content fc61 can't read), readable offline with no controller limits.
- A write path that actually persists (the car reads the flash at every power-on,
  so a flash change is the car-facing change) and is reversible (restore the
  backup image).

## Hardware needed (cheap, standard)

- A CH341A USB programmer (~$5) **modified/used at 3.3V** (important: many CH341A
  boards drive 5V on the SPI lines, which can damage a 3.3V flash; use a 3.3V mod
  or a 3.3V-safe programmer).
- A SOIC-8 test clip (Pomona 5250 or a cheap equivalent), or solder flying leads.
- `flashrom` on the Mac/PC.

## Procedure

1. **Open the BT600** and identify the 8-pin SPI flash near the RTL8761CU
   (silkscreen likely "25Q16" / Winbond "W"). Note pin 1 (dot).
2. **Clip on** (in-circuit read often works; if the controller fights the bus,
   hold the RTL8761 in reset or desolder the flash). 8 lines: VCC(3V3), GND, CS,
   CLK, MOSI(DI), MISO(DO), plus WP/HOLD pulled high.
3. **Read twice and compare** to confirm a stable dump:
   `flashrom -p ch341a_spi -r dump1.bin && flashrom -p ch341a_spi -r dump2.bin`
   then `cmp dump1.bin dump2.bin`. Chip should detect as W25Q16 (2 MB).
4. **Back up** the verified image. This is the real full firmware; analyze it
   offline (the 0x100000.. code and the descriptor builder are now all readable).
5. **Modify + write back** when a change is ready:
   `flashrom -p ch341a_spi -w modified.bin`, then re-read to verify.

## What this unblocks

- Full offline RE of the firmware (no fc61 region limits), so the descriptor
  builder and the patch-apply mechanism can finally be read and understood.
- A persistent, reversible write path for the car (restore from the backup if a
  change misbehaves).

## Open risks to confirm on teardown

- The flash could be an internal/stacked die rather than a discrete chip; the
  teardown photo settles it. If discrete W25Q16 (expected), the clip works.
- In-circuit reads can be disturbed by the controller; reset-hold or desolder if
  the dump is unstable.
