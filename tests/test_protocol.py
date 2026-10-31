import unittest

import lz4.block

from nightfall.protocol import decompress_lz4_tolerant


class DecompressLz4Tests(unittest.TestCase):
    def test_small_body_is_decompressed(self):
        payload = b"gacha" * 100
        compressed = lz4.block.compress(payload, store_size=False)

        self.assertEqual(decompress_lz4_tolerant(b"\x01" + compressed), payload)

    def test_body_larger_than_one_megabyte_is_decompressed(self):
        # 分页拿全量记录时响应体会超过 1 MB，固定上限会让整页解压失败
        payload = bytes(range(256)) * 8192      # 2 MB
        compressed = lz4.block.compress(payload, store_size=False)

        self.assertEqual(len(decompress_lz4_tolerant(b"\x01" + compressed)), len(payload))


if __name__ == "__main__":
    unittest.main()
