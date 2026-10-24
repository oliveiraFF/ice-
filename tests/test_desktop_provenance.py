import tempfile
import unittest
from pathlib import Path

import build_desktop


class DesktopProvenanceTests(unittest.TestCase):
    def test_fresh_input_hashes_and_secret_exclusion(self):
        root = Path(build_desktop.__file__).parent
        inputs = build_desktop.collect_inputs(root)
        names = {row['file'] for row in inputs}
        self.assertIn('agent_tasks.py', names)
        self.assertIn('client_credentials.py', names)
        self.assertIn('desktop.py', names)
        self.assertFalse(any('/data/' in '/' + name or name.endswith('credential.bin') for name in names))
        row = next(x for x in inputs if x['file'] == 'app.py')
        self.assertEqual(row['sha256'], build_desktop.sha256(root / 'app.py'))

    def test_missing_input_stops_build(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                build_desktop.collect_inputs(Path(folder))
