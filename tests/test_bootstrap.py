import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("init_env", ROOT / "scripts/init_env.py")
init_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(init_env)


class BootstrapTest(unittest.TestCase):
    def test_env_has_private_unique_secrets_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text((ROOT / ".env.example").read_text())
            self.assertTrue(init_env.initialize(root))
            first = (root / ".env").read_text()
            self.assertNotIn("GENERATE_", first)
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)
            self.assertFalse(init_env.initialize(root))
            self.assertEqual((root / ".env").read_text(), first)


if __name__ == "__main__":
    unittest.main()
