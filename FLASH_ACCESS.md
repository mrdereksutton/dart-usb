# Storage access and address mapping

## Working USB read path

The ROM classifier at 0x560c places the first flash address region at
**0x02000000**. The actual USB setup callback at 0x020be8a0 was read successfully
through fc61, followed by a complete 1 KiB handler capture. The region's first
256 bytes also read successfully. A full selected-chip capture is in progress;
see SESSION_NOTES.md and its live result before issuing another USB command.

This is distinct from CPU-memory file flash-20261017T023847Z.bin, which was read
at 0x00200000..0x00400000 and includes writable RAM. That older file cannot be
used as a physical SPI restore image by subtracting 0x00200000 from addresses.

The selected geometry record at 0x00280734 and ROM capacity record indicate a
Winbond-compatible 2 MiB configuration. The physical layout, possible aliases,
image headers, and any decryption between CPU reads and raw SPI remain mapping
questions. Retain source hashes and distinguish CPU captures from raw chip reads.

## RAM helper path

A prepared volatile callback trampoline writes a marker and tail-calls the
original USB handler. Once that runs, it supplies a controlled path into resident
routines without depending on the fc20 loader entry. Start with reads and status.
A persistent write plan needs correct arguments/offsets, erase/program sequencing,
original bytes for the actual storage sector, and a recovery method.

## Physical alternatives

Realtek documents programming UART RX/TX on pins 19/20. Using it requires board
pad identification, the programming entry sequence, tool and image format.

Direct SPI is conditional on identifying an accessible chip or pads on the
actual ASUS board. A geometry record alone does not reveal packaging. If a chip
is accessible, two matching reads provide a chip-level image; correlate that
image with CPU addresses before making modifications. Flash storage also need
not contain every CPU ROM/RAM bank. Choose a programmer's voltage and connection
from the identified part and board wiring, rather than assuming a SOIC-8 clip.

No permanent write is part of the current probe. The active development route
continues over USB; physical inspection can be added when it answers a specific
remaining question.
