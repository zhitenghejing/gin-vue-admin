import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify', ROOT / 'scripts/verify.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def isolated_env():
    env = os.environ.copy()
    names = subprocess.check_output(['git', 'rev-parse', '--local-env-vars'], cwd=ROOT, text=True).splitlines()
    for name in names:
        env.pop(name, None)
    return env


class TestTestReporting(unittest.TestCase):
    def test_failure_and_skip_are_preserved(self):
        events = [dict(Action='pass', Test='passed'), dict(Action='skip', Test='external'),
                  dict(Action='output', Output='missing external fixture\n'),
                  dict(Action='fail', Test='failed')]
        command = [sys.executable, '-c', 'import sys; print(' + repr('\n'.join(json.dumps(e) for e in events)) + '); sys.exit(7)']
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = verify.go_tests(command)
        self.assertEqual(code, 7)
        self.assertIn('1 passed, 1 failed, 1 skipped', output.getvalue())
        self.assertIn('missing external fixture', output.getvalue())


class TestGitHooks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gva-hook-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'checkout'
        self.root.mkdir()
        self.env = isolated_env()
        for name in ['.githooks', 'scripts']:
            (self.root / name).mkdir()
        for file in ['.githooks/pre-push', 'scripts/install-git-hooks.sh']:
            shutil.copy2(ROOT / file, self.root / file)
        self.git('init', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')

    def git(self, *args, check=True):
        return subprocess.run(['git', *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True, check=check)

    def install(self, check=True):
        return subprocess.run(['bash', 'scripts/install-git-hooks.sh'], cwd=self.root,
                              env=self.env, capture_output=True, text=True, check=check)

    def test_real_push_passes_then_failure_blocks_remote(self):
        # Reproduce a hook's inherited Git environment; it must not escape this fixture.
        (self.root / 'Makefile').write_text('verify:\n\t@echo fixture-verified\n')
        self.git('add', '.')
        self.git('commit', '-m', 'passing fixture')
        remote = Path(self.temporary.name) / 'remote.git'
        self.git('init', '--bare', str(remote))
        self.git('remote', 'add', 'origin', str(remote))
        self.install()
        self.env['GIT_DIR'] = str(self.root / '.git')
        self.env['GIT_WORK_TREE'] = str(self.root)
        first = self.git('push', 'origin', 'main')
        self.assertIn('fixture-verified', first.stderr + first.stdout)
        accepted = self.git('ls-remote', 'origin', 'refs/heads/main').stdout.split()[0]
        (self.root / 'Makefile').write_text('verify:\n\t@echo intentional-verification-failure\n\t@exit 1\n')
        self.git('add', 'Makefile')
        self.git('commit', '-m', 'failing fixture')
        rejected = self.git('push', 'origin', 'main', check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('intentional-verification-failure', rejected.stderr + rejected.stdout)
        self.assertEqual(self.git('ls-remote', 'origin', 'refs/heads/main').stdout.split()[0], accepted)

    def test_existing_custom_hook_is_preserved(self):
        self.git('config', 'core.hooksPath', 'custom-hooks')
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git('config', '--get', 'core.hooksPath').stdout.strip(), 'custom-hooks')

    def test_existing_default_hook_is_preserved(self):
        hook = self.root / '.git/hooks/pre-push'
        hook.write_text('#!/bin/sh\necho existing-hook\n')
        result = self.install(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(hook.read_text(), '#!/bin/sh\necho existing-hook\n')
        self.assertNotEqual(self.git('config', '--get', 'core.hooksPath', check=False).returncode, 0)

    def test_parent_git_state_is_unchanged(self):
        def state():
            return [subprocess.check_output(['git', *args], cwd=ROOT) for args in
                    [('rev-parse', 'HEAD'), ('show-ref',), ('status', '--porcelain'), ('diff', '--binary'), ('diff', '--cached'), ('config', '--local', '--list')]]
        before = state()
        self.test_real_push_passes_then_failure_blocks_remote()
        self.assertEqual(state(), before)


if __name__ == '__main__':
    unittest.main()
