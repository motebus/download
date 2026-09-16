"""The installed-package smoke gate must recover from an empty Redis cache."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('uchat_smoke', Path(__file__).resolve().parents[1] / 'scripts/verify_uchat_install.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class RamCacheTests(unittest.TestCase):
    def test_current_and_historical_cache_modes_are_distinct(self):
        for ram, expected in ((True, 'no'), (False, 'yes')):
            args = smoke.redis_command(Path('/fixture'), ram)
            self.assertEqual(args[args.index('--appendonly') + 1], expected)
            self.assertEqual(args[args.index('--save') + 1], '')

    def test_sqlite_required_and_redis_files_forbidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(AssertionError):
                smoke.verify_durable_store(root)
            with sqlite3.connect(root / 'inbox.sqlite3') as db:
                db.executescript("CREATE TABLE metadata(key,value); INSERT INTO metadata VALUES('initialized','yes'); CREATE TABLE records(key); INSERT INTO records VALUES('item:fixture');")
            smoke.verify_durable_store(root)
            for name in ('dump.rdb', 'appendonly.aof.1.incr.aof'):
                path = root / name
                path.touch()
                with self.assertRaises(AssertionError):
                    smoke.verify_durable_store(root)
                path.unlink()
