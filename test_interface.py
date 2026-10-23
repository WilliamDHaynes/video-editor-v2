"""Bounded localhost tests. No model calls, media playback or source writes."""
import hashlib
import http.client
import json
import os
import threading
import tempfile
import shutil
from pathlib import Path
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import app
import budget
import editorial as ed


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_root = ed.ROOT
        cls.temp = tempfile.TemporaryDirectory(prefix='interface-test-', dir=cls.original_root)
        cls.root = Path(cls.temp.name)
        for name in ('index.html', 'app.js', 'style.css'):
            shutil.copyfile(cls.original_root/name, cls.root/name)
        shutil.copytree(cls.original_root/'fixtures', cls.root/'fixtures')
        (cls.root/'sample-frames').mkdir()
        from PIL import Image
        Image.new('RGB',(640,360),(20,30,40)).save(cls.root/'sample-frames'/'source_0120s.jpg')
        (cls.root/'DERIVED_sample_source_02m00s-08m00s_audio1_mono16k.mp3').write_bytes(b'synthetic-header-only'*5)
        (cls.root/'outputs').mkdir()
        (cls.root/'outputs'/'OFFLINE_REVIEW_short_02_9x16.mp4').write_bytes(b'synthetic-header-only'*5)
        source = cls.root/'synthetic-source.mp4'
        source.write_bytes(b'local-http-byte-range-test'*(400000))
        cls.patches = [patch.object(ed,'ROOT',cls.root),patch.object(ed,'SOURCE',source),
                       patch.object(ed,'REPORT',cls.root/'editorial'/'review.json'),
                       patch.object(app,'ROOT',cls.root),patch.object(budget,'ROOT',cls.root),
                       patch.object(budget,'LEDGER',cls.root/'ledger.json')]
        for item in cls.patches: item.start()
        budget.summary()
        cls.ledger_before = budget.LEDGER.read_bytes()
        cls.source_before = source.stat()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3)
        assert budget.LEDGER.read_bytes() == cls.ledger_before
        assert ed.SOURCE.stat().st_size == cls.source_before.st_size
        assert ed.SOURCE.stat().st_mtime_ns == cls.source_before.st_mtime_ns
        for item in reversed(cls.patches): item.stop()
        assert cls.root.resolve().parent == cls.original_root.resolve()
        cls.temp.cleanup()

    def request(self, path, data=None, headers=None, method=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        body = None if data is None else json.dumps(data).encode()
        headers = dict(headers or {})
        if data is not None:
            headers.setdefault('Content-Type', 'application/json')
            headers.setdefault('X-Local-Trial', '1')
            headers.setdefault('Origin', f'http://127.0.0.1:{self.port}')
        conn.request(method or ('POST' if data is not None else 'GET'), path, body, headers)
        response = conn.getresponse()
        status, response_headers, body = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, response_headers, body

    def test_real_state_does_not_invent_transcripts(self):
        status, headers, body = self.request('/api/state')
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertEqual(state['report']['mode'], 'real')
        self.assertTrue(all(t['text'] is None for t in state['report']['transcript']))
        self.assertEqual(state['report']['candidates'], [])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_fixtures_are_explicit_and_have_no_source(self):
        for kind in ('candidates', 'reject_all', 'uncertain'):
            status, _, body = self.request('/api/state?mode='+kind)
            self.assertEqual(status, 200)
            report = json.loads(body)['report']
            self.assertEqual(report['mode'], 'fixture')
            self.assertIsNone(report['source_url'])
            self.assertEqual(report['verdict'], kind)

    def test_fixture_actions_cannot_start_paid_jobs(self):
        with patch.object(app, 'launch_job') as launch:
            status, _, _ = self.request('/api/analyze', {'mode': 'candidates'})
            self.assertEqual(status, 400)
            launch.assert_not_called()

    def test_missing_key_stops_before_call_or_reservation(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}), patch.object(app, 'launch_job') as launch:
            status, _, _ = self.request('/api/analyze', {'mode': 'real', 'api_key': '', 'audio_track': 0})
            self.assertEqual(status, 409)
            launch.assert_not_called()

    def test_original_small_range_matches_exact_source_bytes(self):
        status, headers, body = self.request('/source-video', headers={'Range': 'bytes=0-63'})
        self.assertEqual(status, 206); self.assertEqual(len(body), 64)
        with ed.SOURCE.open('rb') as handle: expected = handle.read(64)
        self.assertEqual(hashlib.sha256(body).digest(), hashlib.sha256(expected).digest())
        self.assertTrue(headers['Content-Range'].startswith('bytes 0-63/'))

    def test_source_download_bounded_and_suffix_supported(self):
        status, _, body = self.request('/source-video', headers={'Range': 'bytes=0-'})
        self.assertEqual(status, 206); self.assertEqual(len(body), app.MAX_SOURCE_RANGE)
        status, _, body = self.request('/source-video', headers={'Range': 'bytes=-32'})
        self.assertEqual(status, 206); self.assertEqual(len(body), 32)
        with ed.SOURCE.open('rb') as handle:
            handle.seek(-32, 2); self.assertEqual(body, handle.read())
        self.assertEqual(self.request('/source-video')[0], 416)
        self.assertEqual(self.request('/source-video', headers={'Range':'bytes=999999999999-'})[0], 416)

    def test_head_describes_source_without_body(self):
        status, headers, body = self.request('/source-video', method='HEAD')
        self.assertEqual(status, 200); self.assertEqual(body, b'')
        self.assertEqual(int(headers['Content-Length']), ed.SOURCE.stat().st_size)

    def test_foreign_origin_host_and_unsafe_paths_rejected(self):
        self.assertEqual(self.request('/api/state', headers={'Origin':'https://untrusted.example'})[0], 403)
        self.assertEqual(self.request('/api/state', headers={'Host':'untrusted.example'})[0], 403)
        self.assertEqual(self.request('/media/../app.py')[0], 404)
        self.assertEqual(self.request('/media/%2e%2e/api-cost-ledger.json')[0], 404)
        self.assertEqual(self.request('/api/analyze', {}, {'X-Local-Trial':'0'})[0], 403)

    def test_prepared_assets_and_existing_outputs_remain_available(self):
        for path in ('/media/sample-frames/source_0120s.jpg', '/media/fixtures/frame-door.svg',
                     '/media/DERIVED_sample_source_02m00s-08m00s_audio1_mono16k.mp3',
                     '/media/outputs/OFFLINE_REVIEW_short_02_9x16.mp4'):
            self.assertEqual(self.request(path, headers={'Range':'bytes=0-15'})[0], 206)

    def test_no_automatic_render_and_no_unreviewed_exports(self):
        self.assertEqual(self.request('/api/render-ai', {'mode':'real', 'reviewed':True})[0], 409)
        status, _, body = self.request('/api/selection')
        self.assertEqual(status, 200); self.assertEqual(json.loads(body)['ranges'], [])
        status, _, _ = self.request('/api/review', {'mode':'real', 'run_id':None, 'candidate_id':'c01',
                                                     'decision':'keep','start':120,'end':150,'source_reviewed':True})
        self.assertEqual(status, 400)

    def test_page_is_local_without_autoplay_or_external_assets(self):
        from html.parser import HTMLParser
        class Assets(HTMLParser):
            def handle_starttag(inner, tag, attrs):
                values = dict(attrs)
                self.assertNotIn('autoplay', values)
                if tag in ('video', 'audio'): self.assertEqual(values.get('preload'), 'none')
                if tag in ('script', 'link', 'img'):
                    self.assertFalse(values.get('src', values.get('href','')).startswith(('https:', 'http:')))
        status, _, body = self.request('/')
        self.assertEqual(status, 200); Assets().feed(body.decode('utf-8-sig'))


if __name__ == '__main__': unittest.main(verbosity=2)
