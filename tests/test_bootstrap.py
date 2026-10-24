import importlib.util
from pathlib import Path
import tempfile
import subprocess
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

    def test_exported_and_indented_settings_keep_their_effective_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text((ROOT / ".env.example").read_text())
            (root / ".env").write_text('export POSTGRES_PASSWORD=existing-secret\n Authentication__Google__ClientId=custom-client\nexport Authentication__Google__ClientSecret=custom-secret\n')
            self.assertTrue(init_env.initialize(root))
            result = subprocess.run(["sh", "-c", '. "$1"; test "$POSTGRES_PASSWORD" = existing-secret && test "$Authentication__Google__ClientId" = custom-client && test "$Authentication__Google__ClientSecret" = custom-secret',
                                     "sh", str(root / ".env")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_env_gains_separate_roles_without_replacing_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text((ROOT / ".env.example").read_text())
            old = 'POSTGRES_PASSWORD=existing-secret\nAI_SERVICE_TOKEN=existing-ai-token\nConnectionStrings__Database="Host=127.0.0.1;Port=${POSTGRES_PORT};Database=${POSTGRES_DB};Username=${POSTGRES_USER};Password=${POSTGRES_PASSWORD};Timeout=5"\n'
            (root / ".env").write_text(old)
            self.assertTrue(init_env.initialize(root))
            updated = (root / ".env").read_text()
            self.assertIn("POSTGRES_PASSWORD=existing-secret\n", updated)
            self.assertIn("AI_SERVICE_TOKEN=existing-ai-token\n", updated)
            self.assertIn("Username=${POSTGRES_APP_USER};Password=${POSTGRES_APP_PASSWORD}", updated)
            self.assertLess(updated.index("POSTGRES_APP_PASSWORD="), updated.index("ConnectionStrings__Database="))
            self.assertNotIn("GENERATE_", updated)
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)
            self.assertFalse(init_env.initialize(root))


if __name__ == "__main__":
    unittest.main()
