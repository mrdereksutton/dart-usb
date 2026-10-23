import unittest

import usb_inspect as insp


class ParseConfigTests(unittest.TestCase):
    def test_parses_interface_and_endpoint(self):
        config = bytes([9, 2, 0, 0, 1, 1, 0, 0x80, 50])          # config header
        iface = bytes([9, 4, 0, 0, 1, 0x01, 0x02, 0x00, 0])      # audio class, subclass 2
        ep = bytes([7, 5, 0x81, 0x01, 192 & 0xFF, 192 >> 8, 1])  # IN, isochronous, 192 bytes
        parsed = insp.parse_config(config + iface + ep)
        self.assertEqual(len(parsed), 1)
        self.assertEqual((parsed[0]["class"], parsed[0]["subclass"]), (0x01, 0x02))
        self.assertEqual(
            parsed[0]["endpoints"][0],
            {"address": 0x81, "dir": "IN", "type": "isochronous", "max_packet": 192},
        )

    def test_two_interfaces_each_keep_their_endpoints(self):
        config = bytes([9, 2, 0, 0, 2, 1, 0, 0x80, 50])
        hid = bytes([9, 4, 0, 0, 1, 0x03, 0x00, 0x00, 0])        # HID
        hid_ep = bytes([7, 5, 0x82, 0x03, 8, 0, 10])             # IN, interrupt, 8
        blob = config + hid + hid_ep
        parsed = insp.parse_config(blob)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["class"], 0x03)
        self.assertEqual(parsed[0]["endpoints"][0]["type"], "interrupt")

    def test_empty_and_truncated(self):
        self.assertEqual(insp.parse_config(b""), [])
        self.assertEqual(insp.parse_config(bytes([9, 2, 0, 0])), [])

    def test_captures_interface_number_and_hid_report_length(self):
        config = bytes([9, 2, 0, 0, 1, 1, 0, 0x80, 50])
        iface = bytes([9, 4, 2, 0, 1, 0x03, 0x00, 0x00, 0])            # interface number 2, HID
        hid = bytes([9, 0x21, 0x11, 0x01, 0x00, 0x01, 0x22, 0x3F, 0])  # report length 0x3f
        ep = bytes([7, 5, 0x84, 0x03, 64, 0, 1])
        parsed = insp.parse_config(config + iface + hid + ep)
        self.assertEqual(parsed[0]["number"], 2)
        self.assertEqual(parsed[0]["report_len"], 0x3F)


class HidDecodeTests(unittest.TestCase):
    def test_usage_pages_one_and_two_byte(self):
        report = bytes([0x05, 0x01, 0x09, 0x02, 0x06, 0x00, 0xFF, 0x09, 0x01])
        self.assertEqual(insp.hid_usage_pages(report), [0x01, 0xFF00])

    def test_labels_flag_vendor_defined(self):
        self.assertEqual(insp.usage_page_label(0x01), "0x0001 Generic Desktop")
        self.assertEqual(insp.usage_page_label(0xFF00), "0xff00 vendor-defined")


if __name__ == "__main__":
    unittest.main()
