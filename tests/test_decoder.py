import io
import unittest

from market.decoder import decode, get_freqs, make_tree, read, unpack


SAMPLE_RESPONSE = bytes.fromhex(
    "81 00 00 00 00 00 00 00 0B 00 00 00 06 00 00 00 "
    "2D 00 00 00 09 00 00 00 30 00 00 00 03 00 00 00 "
    "31 00 00 00 03 00 00 00 32 00 00 00 02 00 00 00 "
    "33 00 00 00 02 00 00 00 34 00 00 00 06 00 00 00 "
    "35 00 00 00 03 00 00 00 37 00 00 00 04 00 00 00 "
    "38 00 00 00 01 00 00 00 39 00 00 00 02 00 00 00 "
    "7C 00 00 00 85 00 00 00 11 00 00 00 29 00 00 00 "
    "D3 0C 78 90 FB 1D 0E 6E 4B 4C 35 DF 17 75 BD AA 90"
)
SAMPLE_DECODED = "53801-198-55428-4050|53802-0-17725-70000|"


class DecoderTests(unittest.TestCase):
    def test_unpack_decodes_marketplace_response(self):
        self.assertEqual(unpack(SAMPLE_RESPONSE), SAMPLE_DECODED)

    def test_unpack_accepts_bytes_like_inputs(self):
        self.assertEqual(unpack(bytearray(SAMPLE_RESPONSE)), SAMPLE_DECODED)
        self.assertEqual(unpack(memoryview(SAMPLE_RESPONSE)), SAMPLE_DECODED)

    def test_decode_check_stats_validates_header_frequencies(self):
        file = io.BytesIO(SAMPLE_RESPONSE)
        freqs = get_freqs(file)
        tree = make_tree(freqs)
        packed_bits, packed_bytes, _unpacked_bytes = read(file, "III")
        packed = file.read(packed_bytes)

        self.assertEqual(decode(tree, freqs, packed, packed_bits, check_stats=True), SAMPLE_DECODED)


if __name__ == "__main__":
    unittest.main()
