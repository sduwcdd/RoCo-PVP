import unittest

from scripts.publish_cnb_updates import Publisher, windows_feed


class CnbPublicationTests(unittest.TestCase):
    def test_windows_feed_binds_both_download_paths_and_keeps_integrity(self):
        text = 'version: 1.1.10\nfiles:\n  - url: RocoPVP-Setup-1.1.10.exe\n    sha512: unchanged\n    size: 100\npath: RocoPVP-Setup-1.1.10.exe\nsha512: unchanged\n'
        address = 'https://cnb.cool/sduwcgg/roco-pvp/-/releases/download/v1.1.10/RocoPVP-Setup-1.1.10.exe'
        result = windows_feed(text, '1.1.10', address)
        self.assertEqual(result.count(address), 2)
        self.assertEqual(result.count('sha512: unchanged'), 2)
        with self.assertRaisesRegex(ValueError, 'version'):
            windows_feed(text, '1.1.11', address)
        with self.assertRaisesRegex(ValueError, 'layout'):
            windows_feed(text.replace('url: RocoPVP-', 'url: other-'), '1.1.10', address)

    def test_existing_asset_requires_matching_size_and_sha256(self):
        from pathlib import Path
        file = Path(__file__)
        wanted = 'a' * 64
        asset = {'size': file.stat().st_size, 'hash_algo': 'SHA-256', 'hash_value': wanted}
        Publisher.verify_asset(asset, file, wanted)
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            Publisher.verify_asset({**asset, 'hash_value': 'b' * 64}, file, wanted)
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            Publisher.verify_asset({**asset, 'size': asset['size'] + 1}, file, wanted)


if __name__ == '__main__':
    unittest.main()
