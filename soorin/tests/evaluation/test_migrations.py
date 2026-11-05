from pathlib import Path
import tempfile
import unittest
from soorin.ops.migrations import manifest, compare


class MigrationTests(unittest.TestCase):
    def test_applied_migration_names_are_not_the_checksum_authority(self):
        local = {111: {"name": "0111_soorin.sql", "sha384": "abc"}}
        upstream = {111: {"name": "0111_original.sql", "sha384": "def"}}
        self.assertEqual(compare(local, upstream)[0]["version"], 111)
        self.assertFalse(compare(local, local))

    def test_duplicate_versions_fail_even_when_filenames_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "0111_first.sql"
            second = Path(directory) / "0111_second.sql"
            first.touch()
            second.touch()
            with self.assertRaises(ValueError):
                manifest(Path(directory))
