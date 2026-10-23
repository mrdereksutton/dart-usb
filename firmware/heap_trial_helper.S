/* Allocate/free one receiver-sized SRAM block, then retain stock USB setup. */
.syntax unified
.thumb
.text
.global dart_heap_trial_helper
.thumb_func
dart_heap_trial_helper:
    push {r0-r5, r12, lr}
    mrs r4, apsr
    ldr r0, [r1]
    ldr r2, =0x01010680 /* GET_DESCRIPTOR device index 1 only */
    cmp r0, r2
    bne finished
    ldr r5, =0x00211f00
    ldr r0, [r5]
    cmp r0, #0
    bne finished
    ldr r0, =0xd47a5010
    str r0, [r5]
    movs r0, #5
    mov.w r1, #4096
    ldr r2, =0x08812424
    movs r3, #0
    ldr r12, =0x00281308
    ldr r12, [r12]
    blx r12
    str r0, [r5, #4]
    cbz r0, allocated
    ldr r12, =0x00281310
    ldr r12, [r12]
    blx r12
allocated:
    ldr r0, =0xd47a5011
    str r0, [r5]
    ldr r0, =0x0030d164
    ldr r1, =0x020be8a1
    str r1, [r0]
finished:
    msr apsr_nzcvq, r4
    pop {r0-r5, r12, lr}
    ldr.w pc, original_callback
    .balign 4
original_callback:
    .word 0x020be8a1
    .ltorg
