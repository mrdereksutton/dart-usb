/* One read-only call into the ROM flash API, then retain the original USB path. */
.syntax unified
.thumb
.text
.global dart_flash_read_helper
.thumb_func
dart_flash_read_helper:
    push {r0-r5, r12, lr}
    mrs r4, apsr
    ldr r5, =0x00211f00
    ldr r0, [r5]
    ldr r1, =0xd47a6001
    cmp r0, r1
    beq finished
    ldr r0, =0x020be8a0
    ldr r1, =0x00211e90
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
    .word ORIGINAL_CALLBACK
    .ltorg
