"""Daily capture stays anonymous and retries failed sends, without network access."""
import json
import os
import platform
from pathlib import Path
import subprocess
import tempfile
import io
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import jarvis
from tests import run_swift


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        test_dir = os.environ.pop('JARVIS_DIR', None)
        self.addCleanup(lambda: os.environ.__setitem__('JARVIS_DIR', test_dir) if test_dir is not None else os.environ.pop('JARVIS_DIR', None))

    def test_success_is_daily_and_failure_can_retry(self):
        with tempfile.TemporaryDirectory(prefix='jarvis telemetry ') as root:
            root = Path(root)
            curl = root / 'curl'
            curl.write_text('#!/bin/sh\nexit "${FAKE_CURL_STATUS:-0}"\n')
            curl.chmod(0o700)
            spawn = subprocess.Popen

            def fake_send(args, **kwargs):
                payload = json.loads(args[4])
                self.assertEqual(payload['event'], 'used')
                self.assertEqual(payload['api_key'], 'fixture-token')
                self.assertEqual(payload['properties'], {'$process_person_profile': False, 'version': jarvis.APP_VERSION,
                                                                  'macos': platform.mac_ver()[0], 'client': 'claude'})
                self.assertEqual(set(payload), {'api_key', 'event', 'distinct_id', 'properties'})
                worker = spawn(args, **kwargs)
                worker.wait(timeout=5)
                return worker

            with patch.object(jarvis, 'DIR', str(root)), patch.object(jarvis, 'POSTHOG_KEY', 'fixture-token'), \
                 patch.object(jarvis, 'pref', return_value=True), patch.object(jarvis.subprocess, 'Popen', side_effect=fake_send) as send, \
                 patch.dict(os.environ, {'PATH': str(root), 'FAKE_CURL_STATUS': '22'}):
                jarvis.ping()
                self.assertFalse((root / 'pinged').exists())
                identity = (root / 'id').read_text()
                os.environ['FAKE_CURL_STATUS'] = '0'
                jarvis.ping()
                self.assertTrue((root / 'pinged').exists())
                jarvis.ping()
                self.assertEqual(send.call_count, 2)
                self.assertEqual((root / 'id').read_text(), identity)

    def test_failure_and_used_events_include_the_same_app_version_field(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), \
             patch.object(jarvis, 'POSTHOG_KEY', 'fixture-token'), \
             patch.object(jarvis, 'pref', side_effect=lambda k, d: {'improve': True, 'stats': True}.get(k, d)), \
             patch.object(jarvis.subprocess, 'Popen') as send:
            jarvis.report('Open the fixture', 'Could not open it', (), 1, 'error')
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'task_failed')
        self.assertEqual(payload['properties']['version'], jarvis.APP_VERSION)
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'task', 'reply', 'steps', 'why', 'secs', 'model', 'client', 'macos'})

    def test_failure_reports_drop_text_applescript_types_or_writes(self):
        steps = ['osascript -e \'tell application "System Events" to keystroke "hunter2"\'',
                 'osascript -e \'tell application "Notes" to make new note with properties {name:"Diary", body:"private words"}\'',
                 'osascript -e \'tell application "Notes" to set body of note 1 to "private words"\'']
        cleaned = ' '.join(map(jarvis.clean, steps))
        self.assertFalse(any(word in cleaned for word in ('hunter2', 'Diary', 'private')))
        self.assertIn('tell application "Notes"', cleaned)

    def test_ask_done_has_counts_and_command_classes_but_no_ask_text(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), \
             patch.object(jarvis, 'POSTHOG_KEY', 'fixture-token'), patch.object(jarvis, 'pref', return_value=True), \
             patch.object(jarvis.subprocess, 'Popen') as send:
            jarvis.ask_done({'task': 'Private request', 'reply': 'Private answer', 'path': 'shortcut', 'model': 'instant',
                              'secs': 1.26, 'steps': ['one', 'two'], 'ran': [f'{jarvis.PLACE} Notes left', f'{jarvis.WEB} read secret'],
                              'status': 'completed', 'escalated': False})
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'ask_done')
        self.assertEqual(payload['properties']['tools'], ['place', 'web'])
        self.assertEqual(payload['properties']['status'], 'ok')
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'path', 'model', 'secs', 'steps',
                                                      'tools', 'status', 'escalated', 'macos', 'client'})
        self.assertNotIn('Private', json.dumps(payload))

    def test_ask_done_maps_terminal_states(self):
        with patch.object(jarvis, 'posthog') as send:
            for state in ('completed', 'failed', 'cancelled'):
                jarvis.ask_done({'status': state})
        self.assertEqual([call.args[1]['status'] for call in send.call_args_list], ['ok', 'failed', 'cancelled'])

    def test_error_shapes_never_include_exception_messages_or_shortcut_words(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), \
             patch.object(jarvis, 'POSTHOG_KEY', 'fixture-token'), patch.object(jarvis, 'pref', return_value=True), \
             patch.object(jarvis.subprocess, 'Popen') as send:
            try:
                raise RuntimeError('private crash detail')
            except RuntimeError as error:
                jarvis.exception_error(type(error), error.__traceback__)
            jarvis.report_error('replay', shortcut='0123456789abcdef', failed_at=2)
        crash, replay = [json.loads(call.args[0][4]) for call in send.call_args_list]
        self.assertEqual(set(crash['properties']), {'$process_person_profile', 'version', 'kind', 'macos', 'client',
                                                    'exception', 'file', 'line', 'function', 'at_line', 'at_function'})
        self.assertEqual(crash['properties']['exception'], 'RuntimeError')
        self.assertNotIn('private crash detail', json.dumps(crash))
        self.assertEqual(replay['properties']['kind'], 'replay')
        self.assertEqual(replay['properties']['shortcut'], '0123456789abcdef')
        self.assertEqual(replay['properties']['failed_at'], 2)

    def test_a_crash_inside_the_standard_library_names_the_jarvis_line_and_errno(self):
        code = {}
        exec(compile('import subprocess\ndef go():\n    subprocess.Popen(["/no/such/tool"])\n', jarvis.ME, 'exec'), code)   # a frame that counts as jarvis.py
        with patch.object(jarvis, 'report_error') as sent:
            try:
                code['go']()
            except OSError as error:
                jarvis.exception_error(type(error), error.__traceback__, error)
        props = sent.call_args.kwargs
        self.assertEqual((props['at_function'], props['at_line'], props['errno']), ('go', 3, 2))
        self.assertEqual(props['exception'], 'FileNotFoundError')
        self.assertNotEqual(props['file'], 'jarvis.py')

    def test_setup_problems_are_separate_from_real_worker_failures(self):
        cases = [('HTTP 404: model llama3 may not exist', True, 'server_rejected'),
                 ('400: model does not support tools', True, 'server_rejected'),
                 ('422: incompatible request', True, 'server_rejected'),
                 ('OAuth session expired', False, 'signed_out'),
                 ('HTTP 429', False, 'rate_limited'), ('network connection failed', False, 'offline')]
        with patch.object(jarvis, 'report_error') as sent:
            for detail, custom, why in cases:
                self.assertEqual(jarvis.failure_why(detail, custom), why)
                jarvis.report_worker_failure('claude', 'private-model-name', why)
            for why in ('setup_needed', 'provider_needed', 'model_missing'):
                jarvis.report_worker_failure('pi', 'haiku', why)
        self.assertTrue(all(call.args == ('setup',) for call in sent.call_args_list))
        self.assertNotIn('private', str(sent.call_args_list))
        with patch.object(jarvis, 'report_error') as sent:
            jarvis.report_worker_failure('claude', 'haiku', jarvis.failure_why('Unknown process failure'))
        sent.assert_called_once_with('worker_exit', worker='claude', model='haiku', why='stopped')

    def test_cancellation_has_no_error_event(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), patch.object(jarvis, 'TURN', {}), \
             patch.object(jarvis, 'posthog') as sent:
            jarvis.begin_turn('Private request')
            jarvis.end_turn()
            jarvis.report_worker_failure('claude', 'haiku', 'cancelled')
        self.assertEqual([call.args[0] for call in sent.call_args_list], ['ask_done'])
        self.assertEqual(sent.call_args.args[1]['status'], 'cancelled')

    def test_allow_decisions_share_denial_without_matching_reply_text(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), \
             patch.dict(os.environ, {'JARVIS_ASK': root}):
            marker = Path(root, 'declined')
            for question, answer, declined in [({'q': 'Send?', 'cmd': 'fixture'}, 'n', True),
                                                ({'q': 'Send?', 'cmd': 'fixture'}, 'y', False),
                                                ({'q': 'Send?', 'cmd': 'fixture'}, 'task', False),
                                                ({'pick': 'Which?', 'options': []}, '', False),
                                                ({'q': 'Retry?', 'retry': True}, 'n', False),
                                                ({'q': 'Permission?', 'need': 'screen'}, 'n', False)]:
                marker.unlink(missing_ok=True)
                def respond(path, data): Path(data['_a']).write_text(answer)
                with patch.object(jarvis, 'private_json', side_effect=respond):
                    self.assertEqual(jarvis.ask_user(question, 1), answer)
                self.assertEqual(marker.exists(), declined)
            jarvis.ask_user({'q': 'Send?', 'cmd': 'fixture'}, 0)
            self.assertTrue(marker.exists())
            with patch.object(Path, 'touch', side_effect=FileNotFoundError):
                self.assertIsNone(jarvis.ask_user({'q': 'Send?', 'cmd': 'fixture'}, 0))

    def test_main_crash_is_reported_once_with_the_handled_exit_status(self):
        with patch.object(jarvis, 'main', side_effect=RuntimeError('private detail')), \
             patch.object(jarvis, 'end_turn') as end, patch.object(jarvis, 'telemetry_enabled', return_value=True), \
             patch.object(jarvis, 'posthog') as sent, patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as stopped: jarvis.run_main()
        self.assertEqual(stopped.exception.code, 70)
        end.assert_called_once_with('crashed')
        sent.assert_called_once()
        self.assertEqual((sent.call_args.args[0], sent.call_args.args[1]['kind'], sent.call_args.args[1]['worker']), ('error', 'worker_exit', 'python'))
        self.assertNotIn('private detail', str(sent.call_args))

    def test_normal_exits_and_a_closed_output_pipe_do_not_report_crashes(self):
        with patch.object(jarvis, 'report_error') as sent, patch.object(jarvis, 'end_turn') as end:
            with patch.object(jarvis, 'main', side_effect=SystemExit(0)):
                with self.assertRaises(SystemExit): jarvis.run_main()
            reader, writer = os.pipe(); os.close(reader)
            with os.fdopen(writer, 'w') as output, patch.object(jarvis, 'main', side_effect=BrokenPipeError), \
                 patch.object(jarvis, 'stop_workers') as stop, patch('sys.stdout', output):
                jarvis.run_main()
                sys.stdout.close()   # run_main replaced it with devnull
            stop.assert_called_once()
        sent.assert_not_called(); end.assert_not_called()

    def test_a_failed_crash_checkpoint_cannot_duplicate_or_hide_the_crash(self):
        with patch.object(jarvis, 'main', side_effect=ValueError('private detail')), \
             patch.object(jarvis, 'end_turn', side_effect=OSError('unwritable log')), \
             patch.object(jarvis, 'report_error') as sent, patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as stopped: jarvis.run_main()
        self.assertEqual(stopped.exception.code, 70)
        sent.assert_called_once()
        self.assertEqual(sent.call_args.args, ('worker_exit',))
        self.assertEqual(sent.call_args.kwargs['exception'], 'ValueError')

    def test_thread_exit_is_normal_and_a_closed_relay_pipe_cancels_the_process(self):
        reader, writer = os.pipe(); os.close(reader)
        with os.fdopen(writer, 'w') as output, patch.object(sys, 'excepthook'), patch.object(threading, 'excepthook'), \
             patch.object(jarvis, 'report_error') as sent, patch.object(jarvis, 'stop_workers') as stop, patch('sys.stdout', output):
            jarvis.install_exception_hooks()
            for error in (SystemExit(0), BrokenPipeError()):
                threading.excepthook(SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=None))
            sys.stdout.close()
        stop.assert_called_once(); sent.assert_not_called()

    def test_a_backend_broken_pipe_with_live_output_is_a_real_failure(self):
        with patch.object(jarvis, 'main', side_effect=BrokenPipeError), patch.object(jarvis, 'end_turn'), \
             patch.object(jarvis, 'report_error') as sent, patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as stopped: jarvis.run_main()
        self.assertEqual(stopped.exception.code, 70)
        self.assertEqual(sent.call_args.args, ('worker_exit',))

    def test_swift_reports_only_unreported_process_deaths(self):
        source = Path(jarvis.ME).with_name('Jarvis.swift').read_text()
        rule = next(line.strip() for line in source.splitlines() if 'if p.terminationReason == .uncaughtSignal' in line)
        run_swift(self, '''import Foundation
struct Worker { var terminationReason: Process.TerminationReason; var terminationStatus: Int32 }
var sent = 0
func telemetry(_ args: [String]) { sent += 1 }
for (p, expected) in [(Worker(terminationReason: .exit, terminationStatus: 0), 0),
                      (Worker(terminationReason: .exit, terminationStatus: 70), 0),
                      (Worker(terminationReason: .exit, terminationStatus: 1), 1),
                      (Worker(terminationReason: .uncaughtSignal, terminationStatus: 15), 1),
                      (Worker(terminationReason: .uncaughtSignal, terminationStatus: 70), 1)] {
    sent = 0
    ''' + rule + '''
    precondition(sent == expected)
}
''')

    def test_dictation_has_only_mode_counts_timing_and_outcome(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), \
             patch.object(jarvis, 'POSTHOG_KEY', 'fixture-token'), patch.object(jarvis, 'pref', return_value=True), \
             patch.object(jarvis.subprocess, 'Popen') as send:
            jarvis.dictation_event('cleanup', 1.23456, True, False, False, 'no box')
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'dictation')
        self.assertEqual(payload['properties']['secs'], 1.235)
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'macos', 'client', 'mode', 'secs',
                                                      'cleanup_used', 'fell_back', 'timed_out', 'insert'})

    def test_the_ask_log_and_its_folder_are_private_even_on_older_installs(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root):
            os.chmod(root, 0o755); log = Path(root, 'log.jsonl'); log.write_text(''); log.chmod(0o644)
            jarvis.append_log({'task': 'Summarize my inbox'})
            self.assertEqual((os.stat(root).st_mode & 0o777, log.stat().st_mode & 0o777), (0o700, 0o600))

    def test_disabled_does_not_send(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), \
             patch.object(jarvis.subprocess, 'Popen') as send:
            with patch.object(jarvis, 'POSTHOG_KEY', ''):
                jarvis.ping()
            with patch.object(jarvis, 'POSTHOG_KEY', 'fixture-token'), \
                 patch.object(jarvis, 'pref', side_effect=lambda key, default: True if key == 'improve' else False):
                jarvis.ping()
                jarvis.ask_done({'status': 'completed'})
                jarvis.report_error('stopped')
                jarvis.dictation_event('verbatim', 1, False, False, False, 'ok')
                jarvis.report('Private request', 'Private reply', (), 1, 'error')
            send.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_new_users_are_not_counted_by_default(self):
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), \
             patch.object(jarvis, 'PREFS', str(Path(root) / 'settings.json')), \
             patch.object(jarvis, 'POSTHOG_KEY', 'fixture-token'), patch.object(jarvis.subprocess, 'Popen') as send:
            jarvis.ping()
        send.assert_not_called()

    def test_no_key_ships_so_nothing_is_sent_even_when_stats_is_on(self):
        self.assertEqual(jarvis.POSTHOG_KEY, '')   # tests/__init__ clears JARVIS_POSTHOG_KEY; the source default must be empty too
        self.assertIn("os.environ.get('JARVIS_POSTHOG_KEY', '')", (Path(jarvis.__file__)).read_text())
        with tempfile.TemporaryDirectory() as root, patch.object(jarvis, 'DIR', root), \
             patch.object(jarvis, 'pref', return_value=True), patch.dict(os.environ, {}, clear=False), \
             patch.object(jarvis.subprocess, 'Popen') as send:
            os.environ.pop('JARVIS_DIR', None)
            jarvis.ping(); jarvis.posthog('fixture')
        send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
