"""The installed-package smoke gate enforces Redis as the sole durable Inbox store."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('uchat_smoke', Path(__file__).resolve().parents[1] / 'scripts/verify_uchat_install.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class DurableRedisTests(unittest.TestCase):
    def test_runtime_uses_strict_durable_redis(self):
        args = smoke.redis_command(Path('/fixture'))
        self.assertEqual(args[args.index('--appendonly') + 1], 'yes')
        self.assertEqual(args[args.index('--appendfsync') + 1], 'always')
        self.assertEqual(args[args.index('--aof-load-truncated') + 1], 'no')
        self.assertEqual(args[args.index('--save') + 1], '')

    def test_redis_aof_required_and_sqlite_forbidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(AssertionError):
                smoke.verify_durable_store(root)
            aof = root / 'appendonlydir' / 'appendonly.aof.1.incr.aof'
            aof.parent.mkdir()
            aof.touch()
            smoke.verify_durable_store(root)
            sqlite = root / 'inbox.sqlite3'
            sqlite.touch()
            with self.assertRaises(AssertionError):
                smoke.verify_durable_store(root)


if __name__ == '__main__':
    unittest.main()
