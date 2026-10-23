import unittest
from unittest.mock import Mock

import descriptor_edit as edit

DEVICE = bytes.fromhex("12 01 10 01 e0 01 01 40 05 0b 70 1d 00 02 01 02 00 01")
D, T = 0x0030D130, 0x0030D110
ADDRESS = edit.COMPOSITE + 12


class DescriptorEditTests(unittest.TestCase):
    def fixture(self, usb_follows=True, write_failure=None):
        memory = {edit.COMPOSITE + 0x30: D.to_bytes(4, "little"),
                  D + 4: T.to_bytes(4, "little")}
        template = DEVICE[:7] + b"\x08" + DEVICE[8:]
        for address, raw in ((ADDRESS, DEVICE), (T, template)):
            padded = raw + b"\x00\x00"
            memory.update({address + i: padded[i:i + 4] for i in range(0, 20, 4)})
        read = Mock(side_effect=memory.__getitem__)
        attempts = []

        def write(address, data):
            attempts.append((address, data))
            memory[address] = data
            if write_failure and len(attempts) == 1:
                raise write_failure

        def usb():
            return (b"".join(memory[ADDRESS + i] for i in range(0, 20, 4))[:18]
                    if usb_follows else DEVICE)

        return memory, read, Mock(side_effect=write), Mock(side_effect=usb), Mock()

    def run_test(self, fixture, report):
        memory, read, write, usb, checkpoint = fixture
        edit.test_product_string(read, write, usb, report, checkpoint)

    def test_changes_one_usb_byte_then_restores(self):
        fixture, report = self.fixture(), {}
        self.run_test(fixture, report)
        memory, read, write, usb, checkpoint = fixture
        self.assertEqual(write.call_count, 2)
        self.assertEqual(write.call_args_list[0].args,
                         (ADDRESS + 12, bytes.fromhex("00 02 01 01")))
        self.assertEqual(memory[ADDRESS + 12], DEVICE[12:16])
        self.assertTrue(report["edit"]["usb_changed_as_expected"])
        self.assertEqual(report["edit"]["usb_differing_offsets"], [15])
        self.assertFalse(report["edit"]["restore_required"])
        self.assertEqual(checkpoint.call_count, 2)

    def test_no_ep0_effect_is_recorded_and_restored(self):
        fixture, report = self.fixture(usb_follows=False), {}
        self.run_test(fixture, report)
        self.assertFalse(report["edit"]["usb_changed_as_expected"])
        self.assertEqual(report["edit"]["stage"], "restored")

    def test_template_change_and_restore_are_reflected_by_usb_rebuild(self):
        fixture, report = self.fixture(), {}
        memory, read, write, usb, checkpoint = fixture

        def rebuild():
            memory[ADDRESS + 12] = memory[T + 12]
            return b"".join(memory[ADDRESS + i] for i in range(0, 20, 4))[:18]

        usb.side_effect = rebuild
        edit.test_product_string(read, write, usb, report, checkpoint, template=True)
        self.assertEqual(write.call_args_list[0].args[0], T + 12)
        self.assertTrue(report["edit"]["usb_changed_as_expected"])
        self.assertEqual(memory[T + 12], DEVICE[12:16])
        self.assertEqual(memory[ADDRESS + 12], DEVICE[12:16])

    def test_failed_write_ack_still_restores_applied_write(self):
        fixture, report = self.fixture(write_failure=RuntimeError("lost ack")), {}
        with self.assertRaisesRegex(RuntimeError, "lost ack"):
            self.run_test(fixture, report)
        self.assertEqual(fixture[2].call_count, 2)
        self.assertEqual(fixture[0][ADDRESS + 12], DEVICE[12:16])
        self.assertFalse(report["edit"]["restore_required"])

    def test_interrupt_after_write_still_restores(self):
        fixture, report = self.fixture(write_failure=KeyboardInterrupt()), {}
        with self.assertRaises(KeyboardInterrupt):
            self.run_test(fixture, report)
        self.assertEqual(fixture[0][ADDRESS + 12], DEVICE[12:16])
        self.assertFalse(report["edit"]["restore_required"])

    def test_checkpoint_failure_prevents_write(self):
        fixture, report = self.fixture(), {}
        fixture[4].side_effect = OSError("cannot save original")
        with self.assertRaisesRegex(OSError, "cannot save"):
            self.run_test(fixture, report)
        fixture[2].assert_not_called()

    def test_stale_composite_prevents_write(self):
        fixture, report = self.fixture(usb_follows=False), {}
        fixture[0][ADDRESS] = b"\x00" * 4
        with self.assertRaisesRegex(RuntimeError, "header absent"):
            self.run_test(fixture, report)
        fixture[2].assert_not_called()
        self.assertEqual(fixture[1].call_count, 1)

    def test_bad_driver_pointer_is_not_followed(self):
        fixture, report = self.fixture(), {}
        fixture[0][edit.COMPOSITE + 0x30] = (0x0880A0A8).to_bytes(4, "little")
        with self.assertRaisesRegex(RuntimeError, "outside"):
            self.run_test(fixture, report)
        self.assertEqual(fixture[1].call_count, 6)
        fixture[2].assert_not_called()

    def test_reads_only_the_actual_setup_callback(self):
        fixture, report = self.fixture(), {}
        memory, read, _, _, _ = fixture
        memory[D + 0x34] = (0x020BE8A1).to_bytes(4, "little")
        for offset in range(0, 32, 4):
            memory[0x020BE8A0 + offset] = bytes((offset, 0, 0, 0))
        edit.inspect_setup_handler(read, DEVICE, report)
        self.assertEqual(read.call_count, 21)
        self.assertEqual(report["setup_callback"], "0x020be8a1")
        self.assertEqual(len(bytes.fromhex(report["setup_code"])), 32)

    def test_fault_bank_callback_is_not_followed(self):
        fixture, report = self.fixture(), {}
        fixture[0][D + 0x34] = (0x0010F89D).to_bytes(4, "little")
        with self.assertRaisesRegex(RuntimeError, "outside"):
            edit.inspect_setup_handler(fixture[1], DEVICE, report)
        self.assertEqual(fixture[1].call_count, 13)

    def test_template_mismatch_prevents_write(self):
        fixture, report = self.fixture(), {}
        fixture[0][T + 8] = b"\x00" * 4
        with self.assertRaisesRegex(RuntimeError, "relationship changed"):
            self.run_test(fixture, report)
        fixture[2].assert_not_called()

    def test_unexpected_usb_change_still_restores(self):
        fixture, report = self.fixture(), {}
        fixture[3].side_effect = [DEVICE, bytes(18), DEVICE]
        with self.assertRaisesRegex(RuntimeError, "beyond"):
            self.run_test(fixture, report)
        self.assertFalse(report["edit"]["restore_required"])

    def test_restore_failure_is_recorded_and_raised(self):
        fixture, report = self.fixture(), {}
        real_write = fixture[2].side_effect

        def write(address, data):
            if data == DEVICE[12:16]:
                raise RuntimeError("restore transfer failed")
            real_write(address, data)

        fixture[2].side_effect = write
        with self.assertRaisesRegex(RuntimeError, "restore transfer failed"):
            self.run_test(fixture, report)
        self.assertTrue(report["edit"]["restore_required"])
        self.assertIn("restore_error", report["edit"])


if __name__ == "__main__":
    unittest.main()
