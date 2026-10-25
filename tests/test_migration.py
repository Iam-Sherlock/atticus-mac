"""build.sh's move from Atticus: data kept, shortcuts repointed, the old app's jobs gone, safe to run again."""
import json, os, re, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = re.search(r'(# Coming from Atticus:.*?\n)AGENT=', (ROOT / 'build.sh').read_text(), re.S).group(1)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(); self.addCleanup(scratch.cleanup)
        self.home = Path(scratch.name, 'home'); self.agents = self.home / 'Library' / 'LaunchAgents'; self.agents.mkdir(parents=True)
        stubs = Path(scratch.name, 'bin'); stubs.mkdir(); self.calls = Path(scratch.name, 'calls')
        for name in ('launchctl', 'pkill'):   # launchd and the old app are the Mac's; record what the script asks of them
            (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{self.calls}"\nexit 1\n'); os.chmod(stubs / name, 0o755)
        self.old_me = f'{self.home}/Applications/Atticus.app/Contents/Resources/atticus.py'
        self.new_me = f'{self.home}/Applications/Jarvis.app/Contents/Resources/jarvis.py'
        self.env = {**os.environ, 'HOME': str(self.home), 'PATH': f'{stubs}:{os.environ["PATH"]}', 'APP': f'{self.home}/Applications/Jarvis.app'}

    def run_script(self):
        result = subprocess.run(['bash', '-c', 'set -e\n' + SCRIPT], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_atticus_data_moves_with_its_shortcuts_pointed_at_jarvis(self):
        old = self.home / '.config' / 'atticus'; (old / 'agents' / 'a1').mkdir(parents=True)
        skills = {'open my notes': {'cmds': [f'{self.old_me} --place Notes left current'], 'reply': 'Done.'}}
        (old / 'skills.json').write_text(json.dumps(skills)); os.chmod(old / 'skills.json', 0o600)
        (old / 'memory.md').write_text('Call me Sam.\n')
        (old / 'agents' / 'a1' / 'state.json').write_text(json.dumps({'directory': str(old / 'agents' / 'a1')}))
        for name in ('com.atticus.app.plist', 'com.atticus.routine.r1.plist', 'com.other.app.plist'): (self.agents / name).write_text('<plist/>')
        self.assertIn('Moved your Atticus settings', self.run_script())
        new = self.home / '.config' / 'jarvis'
        self.assertTrue(old.is_symlink()); self.assertEqual(old.resolve(), new.resolve())
        saved = (new / 'skills.json').read_text()
        self.assertNotIn(self.old_me, saved); self.assertEqual(json.loads(saved)['open my notes']['cmds'], [f'{self.new_me} --place Notes left current'])
        self.assertEqual(os.stat(new / 'skills.json').st_mode & 0o777, 0o600)
        self.assertEqual((new / 'memory.md').read_text(), 'Call me Sam.\n')
        directory = json.loads((new / 'agents' / 'a1' / 'state.json').read_text())['directory']
        self.assertTrue(Path(directory, 'state.json').exists())   # agent folders saved under the old path still resolve (their Claude sessions key on it)
        self.assertEqual(sorted(p.name for p in self.agents.iterdir()), ['com.other.app.plist'])
        calls = self.calls.read_text()
        self.assertIn('com.atticus.app.plist', calls); self.assertIn('com.atticus.routine.r1.plist', calls); self.assertIn('pkill', calls)
        self.assertEqual(list(new.rglob('*.migrating')), [])
        self.run_script()   # every update runs build.sh again: nothing moves twice
        self.assertTrue(old.is_symlink()); self.assertEqual((new / 'skills.json').read_text(), saved)

    def test_existing_jarvis_data_is_never_replaced(self):
        old, new = self.home / '.config' / 'atticus', self.home / '.config' / 'jarvis'
        old.mkdir(parents=True); new.mkdir(); (old / 'memory.md').write_text('old'); (new / 'memory.md').write_text('new')
        self.run_script()
        self.assertFalse(old.is_symlink()); self.assertEqual((old / 'memory.md').read_text(), 'old'); self.assertEqual((new / 'memory.md').read_text(), 'new')

    def test_a_fresh_install_has_nothing_to_move(self):
        self.assertEqual(self.run_script(), '')
        self.assertFalse((self.home / '.config').exists())


if __name__ == '__main__':
    unittest.main()
