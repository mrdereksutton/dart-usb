/* Read one checked flash header via the native SPI API; restore setup first. */
.syntax unified
.thumb
.text
.global dart_flash_map_read_helper
.thumb_func
dart_flash_map_read_helper:
    push {r0-r5, r12, lr}
    mrs r4, apsr
    ldr r0, [r1]
    ldr r2, =0x01010680
    cmp r0, r2
    bne finished
    ldr r0, =0x0030d164
    ldr r1, =0x020be8a1
    str r1, [r0]
    ldr r5, =0x00211f00
    ldr r0, [r5, #-4]
    ldr r1, =0x02046110
    cmp r0, r1
    beq read_header
    ldr r1, =0x02097110
    cmp r0, r1
    bne finished
read_header:
    ldr r1, =0x00211ec0
    movs r2, #16
    ldr r3, =0x0000cbb5
    blx r3
    str r0, [r5, #4]
    ldr r0, =0xd47a6001
    str r0, [r5]
finished:
    msr apsr_nzcvq, r4
    pop {r0-r5, r12, lr}
    ldr.w pc, original_callback
    .balign 4
original_callback:
    .word 0x020be8a1
    .ltorg
