import unittest
import build_release


class AgentBundleTests(unittest.TestCase):
    def test_source_bundle_contains_new_runtime_dependency(self):
        self.assertIn('agent_tasks.py', build_release.RADAR_MODULES)
        self.assertIn('agent_bridge.py', build_release.RADAR_MODULES)
