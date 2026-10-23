"""Replay host enumeration and controls through the captured native CU stack."""
import importlib.util
import os
import struct
import tempfile
import unittest

import native_usb_offline as native
from arm_object_loader import load_arm_objects
from native_control_offline import (NativeControlEmulator, build_control_objects,
    control_replay, EP0, DISABLE, DEQUEUE, HALT)

IDLE, DRAIN, READY, IN, OUT, APPLY, STATUS, FAULT = range(8)


def setup(kind, request, value=0, index=0, length=0):
    return struct.pack("<BBHHH", kind, request, value, index, length)


class NativeControlPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if importlib.util.find_spec("unicorn") is None or not all(p.is_file() for p in native.default_images()):
            if os.environ.get("DART_REQUIRE_NATIVE_REPLAY") == "1":
                raise RuntimeError("Required ARM control replay needs Unicorn and pinned captures")
            raise unittest.SkipTest("Unicorn and local captures are required for native control replay")
        cls.folder = tempfile.TemporaryDirectory(prefix="dart-native-control-tests-")
        cls.addClassCleanup(cls.folder.cleanup)
        cls.objects = build_control_objects(cls.folder.name)

    def model(self):
        machine, symbols, _ = control_replay(self.objects)
        return machine, symbols

    def get(self, m, s, index): return m.call(s["control_get"], index)
    def invoke(self, m, s, name, *args): return m.call(s["control_" + name], *args)

    def configure(self, m, s, stream=False):
        self.assertEqual(m.setup(setup(0, 9, 2)), 0)
        m.finish_control()
        if stream:
            self.assertEqual(m.setup(setup(1, 11, 1, 1)), 0)
            m.finish_control()

    def request_bytes(self, m, s):
        req = self.get(m, s, 0)
        return bytes(m.machine.mem_read(m.word(req), m.word(req + 4)))

    def audio_offer(self, m, s, first=100, frames=48):
        m.iso_result = 0
        self.assertEqual(self.invoke(m, s, "push", first, frames), frames)
        self.assertEqual(self.invoke(m, s, "audio_service"), 1)
        call = next(c for c in reversed(m.calls) if c["entry"] == native.ISO_QUEUE)
        return call["arguments"][6]

    def audio_complete(self, m, request, status=0):
        m.call(0x020BD7D8, m.pcd, native.EP3, request, status, m.word(request + 4) if not status else 0)

    def test_enumeration_uses_native_dispatcher_and_control_queue(self):
        m, s = self.model()
        self.assertEqual(m.setup(setup(0x80, 6, 0x100, length=18)), 0)
        device = self.request_bytes(m, s)
        self.assertEqual(device, bytes.fromhex("12 01 10 01 00 00 00 40 05 0b 70 1d 00 02 01 02 00 01"))
        self.assertNotEqual(m.word(m.ep0_state + 4), m.ep0_state + 4)
        m.finish_control()
        self.assertEqual(m.setup(setup(0x80, 6, 0x200, length=255)), 0)
        config = self.request_bytes(m, s)
        self.assertEqual(len(config), 128)
        self.assertEqual(config[:9], bytes.fromhex("09 02 80 00 03 02 00 80 32"))
        self.assertIn(bytes.fromhex("09 05 83 01 c0 00 01 00 00"), config)
        self.assertEqual(m.byte(self.get(m, s, 0) + 0x28) & 2, 2)
        m.finish_control()
        self.assertEqual(self.get(m, s, 4), IDLE)
        self.assertTrue(m.allocations)

    def test_set_address_remains_owned_by_native_pcd(self):
        m, s = self.model()
        before = self.get(m, s, 13)
        self.assertIsNone(m.setup(setup(0, 5, 7)))
        self.assertEqual((m.word(0x400C0800) >> 4) & 127, 7)
        self.assertEqual(self.get(m, s, 13), before)
        self.assertEqual(self.get(m, s, 5), 0)
        self.assertEqual(m.byte(m.pcd + 12), 4)  # native status IN state

    def test_host_stream_selection_reaches_full_native_iso_queue(self):
        m, s = self.model()
        self.configure(m, s, True)
        self.assertEqual([self.get(m, s, n) for n in (1, 2, 9)], [2, 1, 1])
        self.assertEqual(m.word(native.EP3 + 24), 192)
        self.assertEqual(self.invoke(m, s, "push", 100, 48), 48)
        self.assertEqual(self.invoke(m, s, "audio_service"), 1)
        entry = m.word(m.ep3_state + 4)
        request = m.word(entry)
        self.assertEqual(m.word(request + 4), 192)
        packet = bytes(m.machine.mem_read(m.word(request), 192))
        self.assertEqual(struct.unpack("<96h", packet), tuple(v for i in range(100, 148) for v in (i, -i)))

    def test_rate_change_drains_requests_before_applying_data_and_delayed_status(self):
        m, s = self.model()
        self.configure(m, s, True)
        first = self.audio_offer(m, s)
        second = self.audio_offer(m, s, 200)
        old_packet = bytes(m.machine.mem_read(m.word(first), 192))
        self.assertEqual(m.setup(setup(0x22, 1, 0x100, 0x83, 3)), 1255)
        self.assertEqual(self.get(m, s, 4), OUT)
        self.assertEqual(self.get(m, s, 5), 1)
        m.finish_control(bytes.fromhex("44 ac 00"))
        self.assertEqual(self.get(m, s, 4), APPLY)
        self.assertEqual(self.get(m, s, 3), 48000)
        self.assertEqual(self.invoke(m, s, "service"), 1)
        self.audio_complete(m, first, -108)
        self.assertEqual(self.invoke(m, s, "service"), 1)
        self.assertEqual(bytes(m.machine.mem_read(m.word(first), 192)), old_packet)
        self.audio_complete(m, second, -108)
        self.assertEqual(self.invoke(m, s, "service"), 0)
        self.assertEqual([self.get(m, s, n) for n in (3, 4, 9)], [44100, STATUS, 1])
        self.assertEqual(m.byte(m.pcd + 12), 4)
        m.finish_control()
        request = self.audio_offer(m, s, 300, 44)
        self.assertEqual(m.word(request + 4), 176)

    def test_hid_out_validates_payload_before_status(self):
        m, s = self.model()
        self.configure(m, s)
        report = bytes.fromhex("05 00 55 04 00 38 12 34 7e")
        self.assertEqual(m.setup(setup(0x21, 9, 0x205, 2, len(report))), 1255)
        m.finish_control(report)
        self.assertEqual(self.get(m, s, 14), 0)
        self.assertEqual(self.invoke(m, s, "service"), 0)
        self.assertEqual(self.get(m, s, 14), 1)
        self.assertEqual(self.get(m, s, 4), STATUS)
        m.finish_control()

    def test_bad_hid_checksum_stalls_without_queuing_status(self):
        m, s = self.model()
        self.configure(m, s)
        self.assertEqual(m.setup(setup(0x21, 9, 0x205, 2, 9)), 1255)
        m.finish_control(bytes.fromhex("05 00 55 04 00 38 12 34 00"))
        self.assertEqual(self.invoke(m, s, "service"), -22)
        self.assertEqual(self.get(m, s, 14), 0)
        self.assertEqual(self.get(m, s, 5), 0)
        self.assertEqual(m.calls[-1]["entry"], HALT)

    def test_short_rate_data_keeps_old_rate_and_stalls(self):
        m, s = self.model()
        self.configure(m, s, True)
        self.assertEqual(m.setup(setup(0x22, 1, 0x100, 0x83, 3)), 1255)
        m.finish_control(bytes.fromhex("44 ac"))
        self.assertEqual(self.invoke(m, s, "service"), -5)
        self.assertEqual(self.get(m, s, 3), 48000)
        self.assertEqual(self.get(m, s, 5), 0)
        self.assertTrue(any(c["entry"] == HALT for c in m.calls))
        self.assertEqual(m.setup(setup(1, 11, 1, 1)), 0)
        m.finish_control()
        self.assertEqual(self.get(m, s, 9), 1)

    def test_new_setup_native_abort_releases_old_request_before_reuse(self):
        m, s = self.model()
        self.assertEqual(m.setup(setup(0x80, 6, 0x200, length=128)), 0)
        self.assertEqual(m.setup(setup(0x80, 6, 0x100, length=8)), 0)
        self.assertEqual(self.request_bytes(m, s), bytes.fromhex("12 01 10 01 00 00 00 40"))
        m.finish_control()
        self.assertEqual(self.get(m, s, 4), IDLE)
        self.assertEqual(self.get(m, s, 8), 1)

    def test_disconnect_waits_for_control_and_audio_cancellations(self):
        m, s = self.model()
        self.configure(m, s, True)
        request = self.audio_offer(m, s)
        self.assertEqual(m.setup(setup(0x80, 6, 0x100, length=18)), 0)
        before = self.request_bytes(m, s)
        m.call(0x020BD87A, m.pcd)
        self.assertEqual(self.get(m, s, 7), 1)
        self.assertEqual(self.request_bytes(m, s), before)
        self.assertEqual(self.get(m, s, 1), 2)
        m.finish_control(status=-108)
        self.audio_complete(m, request, -108)
        self.assertEqual(self.invoke(m, s, "service"), 0)
        self.assertEqual([self.get(m, s, n) for n in (1, 2, 5, 6, 7)], [0, 0, 0, 1, 0])
        self.assertEqual(self.get(m, s, 18), 1)

    def test_unbind_restores_callbacks_only_after_all_requests_complete(self):
        m, s = self.model()
        self.configure(m, s, True)
        request = self.audio_offer(m, s)
        self.assertEqual(m.setup(setup(0x80, 6, 0x100, length=18)), 0)
        current = m.word(0x0030D164)
        self.assertEqual(self.invoke(m, s, "unbind"), 1)
        self.assertEqual(m.word(0x0030D164), current)
        m.finish_control(status=-108)
        self.audio_complete(m, request, -108)
        self.assertEqual(self.invoke(m, s, "unbind"), 0)
        self.assertEqual(m.word(0x0030D164), 0x020BE8A1)
        self.assertEqual(m.word(0x0030D168), 0x020BE7E3)
        self.assertEqual(m.word(EP0 + 20), 0)
        self.assertEqual(self.get(m, s, 6), 0)

    def test_native_enable_failure_rolls_back_stream_selection(self):
        m, s = self.model()
        self.configure(m, s)
        m.result_overrides[native.ENABLE] = -1
        self.assertEqual(m.setup(setup(1, 11, 1, 1)), -1)
        self.assertEqual(self.get(m, s, 2), 0)
        self.assertEqual(self.get(m, s, 5), 0)
        self.assertEqual(self.invoke(m, s, "service"), -1)
        self.assertEqual(m.word(native.EP3 + 20), 0)
        del m.result_overrides[native.ENABLE]
        self.assertEqual(m.setup(setup(1, 11, 1, 1)), 0)
        m.finish_control()
        self.assertEqual(self.get(m, s, 9), 1)

    def test_oversized_out_request_is_rejected_without_draining_audio(self):
        m, s = self.model()
        self.configure(m, s, True)
        self.assertEqual(self.invoke(m, s, "push", 100, 48), 48)
        self.assertEqual(m.setup(setup(0x22, 1, 0x100, 0x83, 65535)), -22)
        self.assertEqual(self.get(m, s, 5), 0)
        self.assertEqual(self.get(m, s, 9), 1)
        self.assertEqual(self.get(m, s, 10), 48)

    def test_binding_rejects_an_active_stock_configuration(self):
        m = NativeControlEmulator()
        symbols, _ = load_arm_objects(m.machine, self.objects)
        m.put_word(0x0030D188, 0x0030D3C8)
        self.assertEqual(m.call(symbols["control_init"]), -22)
        self.assertEqual(m.word(0x0030D164), 0x020BE8A1)
        self.assertEqual(m.word(EP0 + 20), 0)

    def test_idle_selection_defers_status_until_audio_cancels(self):
        m, s = self.model()
        self.configure(m, s, True)
        request = self.audio_offer(m, s)
        self.assertEqual(m.setup(setup(1, 11, 0, 1)), 1255)
        self.assertEqual(self.get(m, s, 4), DRAIN)
        self.assertEqual(self.get(m, s, 2), 1)
        self.assertEqual(self.get(m, s, 5), 0)
        self.audio_complete(m, request, -108)
        self.assertEqual(self.invoke(m, s, "service"), 0)
        self.assertEqual([self.get(m, s, n) for n in (2, 4, 5, 9)], [0, STATUS, 1, 0])
        m.finish_control()

    def test_new_descriptor_query_aborts_pending_idle_change_and_resumes_old_stream(self):
        m, s = self.model()
        self.configure(m, s, True)
        request = self.audio_offer(m, s)
        self.assertEqual(m.setup(setup(1, 11, 0, 1)), 1255)
        self.assertEqual(m.setup(setup(0x80, 6, 0x100, length=18)), 0)
        self.assertEqual(len(self.request_bytes(m, s)), 18)
        m.finish_control()
        self.assertEqual(self.invoke(m, s, "service"), 1)
        self.audio_complete(m, request, -108)
        self.assertEqual(self.invoke(m, s, "service"), 0)
        self.assertEqual([self.get(m, s, n) for n in (2, 4, 5, 9)], [1, IDLE, 0, 1])

    def test_tick_holds_new_format_audio_until_control_status_completes(self):
        m, s = self.model()
        self.configure(m, s, True)
        m.iso_result = 0
        self.assertEqual(m.setup(setup(0x22, 1, 0x100, 0x83, 3)), 1255)
        m.finish_control(bytes.fromhex("44 ac 00"))
        self.assertEqual(self.invoke(m, s, "service"), 0)
        self.assertEqual(self.invoke(m, s, "push", 100, 44), 44)
        self.assertEqual(self.invoke(m, s, "audio_service"), 0)
        self.assertEqual(self.get(m, s, 10), 44)
        self.assertEqual(self.get(m, s, 19), 0)
        m.finish_control()
        self.assertEqual(self.invoke(m, s, "audio_service"), 1)
        self.assertEqual(self.get(m, s, 10), 0)


if __name__ == "__main__":
    unittest.main()
