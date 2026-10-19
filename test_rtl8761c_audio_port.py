"""Execute the compiled C adapter against captured native ARM routines offline."""
from pathlib import Path
import importlib.util
import os
import struct
import tempfile
import unittest

import native_usb_offline as native
from validate_native_audio import build_objects, complete, replay, DISABLE, DEQUEUE


class NativeAudioPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        available = importlib.util.find_spec("unicorn") is not None and all(p.is_file() for p in native.default_images())
        if not available:
            if os.environ.get("DART_REQUIRE_NATIVE_REPLAY") == "1":
                raise RuntimeError("Required ARM replay needs Unicorn and the pinned local captures")
            raise unittest.SkipTest("Unicorn and local BT600 captures are required for native replay")
        cls.folder = tempfile.TemporaryDirectory(prefix="dart-native-arm-tests-")
        cls.addClassCleanup(cls.folder.cleanup)
        cls.objects = build_objects(cls.folder.name)

    def model(self, rate=48000, intercepted_queue=True):
        machine, symbols, _ = replay(self.objects, rate)
        if intercepted_queue:
            machine.iso_result = 0
        machine.result_overrides.update({DISABLE: 0, DEQUEUE: 0})
        return machine, symbols

    def invoke(self, machine, symbols, name, *args):
        return machine.call(symbols["fixture_" + name], *args)

    def offer(self, machine, symbols, first=100, frames=48):
        self.assertEqual(self.invoke(machine, symbols, "push", frames, first), frames)
        self.assertEqual(self.invoke(machine, symbols, "service"), 1)
        call = machine.calls[-1]
        self.assertEqual(call["entry"], native.ISO_QUEUE)
        return call["arguments"][6]

    def test_compiled_32_bit_abi_and_real_native_queue(self):
        machine, symbols = self.model(intercepted_queue=False)
        self.assertEqual([self.invoke(machine, symbols, "size", i) for i in range(4)], [44, 552, 244, 4168])
        self.assertEqual(self.invoke(machine, symbols, "push", 48, 100), 48)
        self.assertEqual(self.invoke(machine, symbols, "service"), 1)
        self.assertEqual(machine.word(native.EP3 + 24), 192)
        self.assertEqual((machine.word(machine.ep3_state + 20) >> 18) & 2047, 192)
        queued = machine.word(machine.ep3_state + 4)
        request = machine.word(queued)
        self.assertEqual(machine.word(request + 4), 192)
        self.assertEqual(machine.word(request + 28), 0xffffff8d)
        packet = bytes(machine.machine.mem_read(machine.word(request), 192))
        self.assertEqual(struct.unpack("<96h", packet), tuple(v for i in range(100, 148) for v in (i, -i)))
        self.assertTrue(any(c["entry"] == 0x0020B6F6 for c in machine.calls))

    def test_native_wrapper_passes_complete_request_arguments(self):
        machine, symbols = self.model()
        request = self.offer(machine, symbols)
        driver, endpoint, buffer, dma, length, zero, saved_request, transfer = machine.calls[-1]["arguments"]
        self.assertEqual((driver, endpoint, dma, length, zero, saved_request, transfer),
                         (machine.pcd, native.EP3, buffer, 192, 0, request, 1))
        self.assertNotEqual(machine.word(request + 12), 0)
        complete(machine, request)
        self.assertEqual(self.invoke(machine, symbols, "stat", 1), 1)

    def test_44100_packet_cadence_and_sample_continuity(self):
        machine, symbols = self.model(44100)
        frames_sent = 0; histogram = {}
        for ms in range(100):
            frames = (ms + 1) * 44100 // 1000 - ms * 44100 // 1000
            request = self.offer(machine, symbols, frames_sent, frames)
            arguments = machine.calls[-1]["arguments"]
            length, buffer = arguments[4], arguments[2]
            packet = bytes(machine.machine.mem_read(buffer, length))
            self.assertEqual(struct.unpack("<" + str(frames * 2) + "h", packet),
                             tuple(v for i in range(frames_sent, frames_sent + frames) for v in (i, -i)))
            histogram[length] = histogram.get(length, 0) + 1
            complete(machine, request)
            frames_sent += frames
        self.assertEqual(histogram, {176: 90, 180: 10})
        self.assertEqual(frames_sent, 4410)
        self.assertEqual(self.invoke(machine, symbols, "stat", 1), 100)

    def test_two_owned_buffers_apply_backpressure_without_consuming_more_audio(self):
        machine, symbols = self.model()
        first = self.offer(machine, symbols, 100)
        second = self.offer(machine, symbols, 200)
        self.assertNotEqual(first, second)
        first_data = bytes(machine.machine.mem_read(machine.word(first), 192))
        second_data = bytes(machine.machine.mem_read(machine.word(second), 192))
        self.assertEqual(self.invoke(machine, symbols, "push", 48, 300), 48)
        self.assertEqual(self.invoke(machine, symbols, "service"), 0)
        self.assertEqual(self.invoke(machine, symbols, "stat", 4), 48)
        self.assertEqual(self.invoke(machine, symbols, "stat", 5), 2)
        self.assertEqual(bytes(machine.machine.mem_read(machine.word(first), 192)), first_data)
        self.assertEqual(bytes(machine.machine.mem_read(machine.word(second), 192)), second_data)
        complete(machine, first)
        self.assertEqual(self.invoke(machine, symbols, "service"), 1)
        self.assertEqual(self.invoke(machine, symbols, "stat", 4), 0)

    def test_actual_full_native_ring_stops_submissions_and_retains_rejected_packet(self):
        machine, symbols = self.model(intercepted_queue=False)
        machine.machine.mem_write(machine.pcd + 0x998, b"\0\x0f")
        self.assertEqual(self.invoke(machine, symbols, "push", 48, 100), 48)
        self.assertEqual(self.invoke(machine, symbols, "service"), -22)
        self.assertEqual(self.invoke(machine, symbols, "stat", 2), 1)
        self.assertEqual(self.invoke(machine, symbols, "stat", 7), 1)
        request = symbols["fixture_port"] + 24
        packet = bytes(machine.machine.mem_read(machine.word(request), 192))
        self.assertEqual(self.invoke(machine, symbols, "push", 48, 200), 48)
        self.assertEqual(self.invoke(machine, symbols, "service"), -22)
        self.assertEqual(self.invoke(machine, symbols, "stat", 5), 1)
        self.assertEqual(bytes(machine.machine.mem_read(machine.word(request), 192)), packet)
        self.assertEqual(self.invoke(machine, symbols, "stop"), 0)
        self.assertEqual(self.invoke(machine, symbols, "stat", 6), 1)
        self.assertEqual(machine.word(native.EP3 + 20), 0)

    def test_transfer_error_stops_further_submissions(self):
        machine, symbols = self.model()
        request = self.offer(machine, symbols)
        complete(machine, request, status=-5, actual=0)
        self.assertEqual(self.invoke(machine, symbols, "stat", 3), 1)
        self.assertEqual(self.invoke(machine, symbols, "stat", 1), 0)
        self.assertEqual(self.invoke(machine, symbols, "service"), -5)
        self.assertEqual(self.invoke(machine, symbols, "stop"), 0)

    def test_stop_waits_for_late_cancellations_before_restoring_or_reusing_buffers(self):
        machine, symbols = self.model()
        first = self.offer(machine, symbols, 100)
        second = self.offer(machine, symbols, 200)
        data = bytes(machine.machine.mem_read(machine.word(first), 192))
        self.assertEqual(self.invoke(machine, symbols, "stop"), 1)
        self.assertNotEqual(machine.word(native.EP3 + 20), 0)
        self.assertEqual(self.invoke(machine, symbols, "start"), -22)
        self.assertEqual(self.invoke(machine, symbols, "service"), -22)
        self.assertEqual(bytes(machine.machine.mem_read(machine.word(first), 192)), data)
        complete(machine, first, status=-104, actual=0)
        self.assertEqual(self.invoke(machine, symbols, "stop"), 1)
        complete(machine, second, status=-104, actual=0)
        self.assertEqual(self.invoke(machine, symbols, "stop"), 0)
        self.assertEqual(machine.word(native.EP3 + 20), 0)
        self.assertEqual(machine.word(native.EP3 + 24), 2048)
        self.assertEqual(self.invoke(machine, symbols, "stat", 3), 0)
        self.assertEqual(sum(c["entry"] == DEQUEUE for c in machine.calls), 2)
        self.assertEqual(sum(c["entry"] == DISABLE for c in machine.calls), 1)
        self.assertEqual(self.invoke(machine, symbols, "start"), 0)

    def test_enable_failure_requires_explicit_cleanup(self):
        machine, symbols = self.model()
        self.assertEqual(self.invoke(machine, symbols, "stop"), 0)
        machine.result_overrides.update({native.ENABLE: -1, DISABLE: 0})
        self.assertEqual(self.invoke(machine, symbols, "start"), -1)
        self.assertEqual(self.invoke(machine, symbols, "service"), -22)
        self.assertNotEqual(machine.word(native.EP3 + 20), 0)
        self.assertEqual(self.invoke(machine, symbols, "stop"), 0)
        self.assertEqual(machine.word(native.EP3 + 20), 0)

    def test_invalid_dma_mapping_consumes_no_pcm(self):
        machine, symbols = self.model()
        self.assertEqual(self.invoke(machine, symbols, "push", 48, 100), 48)
        self.invoke(machine, symbols, "bad_dma", 1)
        self.assertEqual(self.invoke(machine, symbols, "service"), -22)
        self.assertEqual(self.invoke(machine, symbols, "stat", 4), 48)
        self.assertEqual(self.invoke(machine, symbols, "stat", 5), 0)

    def test_changed_vtable_is_rejected_before_any_native_operation(self):
        machine, symbols = self.model()
        self.assertEqual(self.invoke(machine, symbols, "stop"), 0)
        machine.put_word(0x0030cf58 + 0x18, 0x0020c7b3)
        before = len(machine.calls)
        self.assertEqual(self.invoke(machine, symbols, "init", 48000), -22)
        self.assertEqual(len(machine.calls), before)

    def test_start_rechecks_endpoint_ownership_after_initialization(self):
        machine, symbols = self.model()
        self.assertEqual(self.invoke(machine, symbols, "stop"), 0)
        machine.put_word(native.EP3 + 20, native.DESCRIPTOR)
        before = len(machine.calls)
        self.assertEqual(self.invoke(machine, symbols, "start"), -22)
        self.assertEqual(machine.word(native.EP3 + 20), native.DESCRIPTOR)
        self.assertEqual(len(machine.calls), before)

    def test_changed_packet_size_stops_before_consuming_audio(self):
        machine, symbols = self.model()
        self.assertEqual(self.invoke(machine, symbols, "push", 48, 100), 48)
        machine.put_word(native.EP3 + 24, 63)
        self.assertEqual(self.invoke(machine, symbols, "service"), -22)
        self.assertEqual(self.invoke(machine, symbols, "stat", 4), 48)
        self.assertEqual(self.invoke(machine, symbols, "stat", 5), 0)


if __name__ == "__main__":
    unittest.main()
