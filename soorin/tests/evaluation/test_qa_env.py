"""Only temporary files; never reads or replaces .env.qa or any Docker data."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[3]


@unittest.skipUnless(shutil.which('make') and shutil.which('openssl'), 'installed make/openssl required')
class QaEnvironmentTests(unittest.TestCase):
    def invoke(self, target, **kwargs):
        return subprocess.run(['make','qa-env-init',f'QA_ENV_FILE={target}'],cwd=ROOT,
                              capture_output=True,timeout=5,**kwargs)

    def test_random_secret_mode_and_existing_file_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'qa.env'
            self.assertEqual(self.invoke(target).returncode,0)
            original = target.read_bytes()
            self.assertRegex(original,rb'(?m)^SOORIN_DEV_DB_PASSWORD=[0-9a-f]{48}$')
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
            self.assertNotEqual(self.invoke(target).returncode,0)
            self.assertEqual(target.read_bytes(),original)

    def test_rng_failure_never_creates_empty_secret_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'qa.env'
            fake = Path(directory)/'openssl'
            fake.write_text('#!/bin/sh\nexit 1\n')
            fake.chmod(0o700)
            result = self.invoke(target,env={**os.environ,'PATH':directory+os.pathsep+os.environ['PATH']})
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(target.exists())
