"""Video Editor v2 editorial review, localhost only; no service or autostart."""
import json
import mimetypes
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit, parse_qs
import budget
import editorial as ed

ROOT = ed.ROOT
PORT = 8765
MAX_SOURCE_RANGE = 8*1024*1024
JOB = {'running': False, 'stage': 'Ready for a bounded editorial test; no real judgment yet', 'error': None}
JOB_LOCK = threading.Lock()
REVIEW_LOCK = threading.Lock()

def progress(message):
    JOB['stage'] = message

def launch_job(function):
    with JOB_LOCK:
        if JOB['running']:
            raise RuntimeError('A job is already running')
        JOB.update(running=True, stage='Starting', error=None)
    def work():
        try:
            function()
        except Exception as exc:
            # Only local validation messages are shown; SDK exception payloads never leave the gateway.
            message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__ + '; processing stopped'
            JOB.update(error=message, stage='Stopped; check local status and ledger')
        finally:
            JOB['running'] = False
    threading.Thread(target=work, daemon=True).start()

def state(mode='real'):
    report = ed.load_report() if mode == 'real' else ed.fixture_report(mode)
    return {'job': JOB.copy(), 'budget': budget.summary(), 'report': report,
            'environment_key_present': bool(os.environ.get('OPENAI_API_KEY')),
            'source_available': ed.SOURCE.is_file(), 'root': str(ROOT),
            'prepared_audio_tracks': [i for i in range(3) if (ROOT/f'DERIVED_sample_source_02m00s-08m00s_audio{i+1}_mono16k.mp3').is_file()],
            'outputs': [{'name': p.name, 'path': 'outputs/' + p.name, 'bytes': p.stat().st_size}
                        for p in sorted((ROOT / 'outputs').glob('*.mp4'))],
            'models': {'vision': 'gpt-5.4-mini', 'transcription': 'gpt-transcribe', 'pricing_checked': '2026-10-23'}}

def byte_range(value, size, limit=None):
    if not value:
        if limit:
            raise ValueError('Source video requires a byte range; full-file downloads are disabled here')
        return 0, size-1, 200
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
    if not match or not (match[1] or match[2]):
        raise ValueError('Unsupported byte range')
    if match[1]:
        start = int(match[1])
        end = min(int(match[2]) if match[2] else size-1, size-1)
    else:
        count = int(match[2])
        if count <= 0:
            raise ValueError('Invalid byte range')
        start, end = max(0, size-count), size-1
    if start > end or start >= size:
        raise ValueError('Invalid byte range')
    if limit:
        end = min(end, start+limit-1)
    return start, end, 206

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def allowed(self, write=False):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        origin = self.headers.get('Origin')
        return (self.headers.get('Host', '') in hosts and
                (not origin or origin in {f'http://{h}' for h in hosts}) and
                (not write or self.headers.get('X-Local-Trial') == '1'))

    def response_headers(self, status, mime, length):
        self.send_response(status)
        for key, value in {'Content-Type': mime, 'Content-Length': str(length), 'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items():
            self.send_header(key, value)

    def json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.response_headers(status, 'application/json; charset=utf-8', len(raw))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.allowed():
            return self.json({'error': 'Local origin required'}, 403)
        route = urlsplit(self.path)
        if route.path == '/api/state':
            mode = parse_qs(route.query).get('mode', ['real'])[0]
            if mode not in ('real', 'candidates', 'reject_all', 'uncertain'):
                return self.json({'error': 'Unknown review mode'}, 400)
            return self.json(state(mode))
        if route.path == '/api/selection':
            report = ed.load_report()
            return self.json({'run_id': report['run_id'], 'source': str(ed.SOURCE),
                              'status': 'reviewed_ranges_only_not_rendered', 'ranges': ed.reviewed_ranges(report)})
        fixed = {'/': ROOT/'index.html', '/app.js': ROOT/'app.js', '/style.css': ROOT/'style.css'}
        is_source = route.path == '/source-video'
        if is_source:
            target = ed.SOURCE
        elif route.path in fixed:
            target = fixed[route.path]
        elif route.path.startswith('/media/'):
            target = (ROOT/unquote(route.path[7:])).resolve()
            if not target.is_relative_to(ROOT) or target.suffix.lower() not in ('.mp4', '.mp3', '.jpg', '.svg'):
                return self.json({'error': 'Not available'}, 404)
        else:
            return self.json({'error': 'Not found'}, 404)
        if not target.is_file():
            return self.json({'error': 'Not found'}, 404)
        size = target.stat().st_size
        if self.command == 'HEAD':
            start, end, status = 0, size-1, 200
        else:
            try:
                start, end, status = byte_range(self.headers.get('Range'), size, MAX_SOURCE_RANGE if is_source else None)
            except ValueError as exc:
                return self.json({'error': str(exc)}, 416)
        self.response_headers(status, mimetypes.guess_type(target.name)[0] or 'application/octet-stream', end-start+1)
        self.send_header('Accept-Ranges', 'bytes')
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        try:
            with target.open('rb') as handle:
                handle.seek(start)
                remaining = end-start+1
                while remaining > 0:
                    chunk = handle.read(min(262144, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def do_POST(self):
        if not self.allowed(write=True):
            return self.json({'error': 'Local origin required'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Expected a request object')
            route = urlsplit(self.path).path
            if data.get('mode') != 'real':
                raise ValueError('Synthetic fixtures are read-only and cannot trigger real actions')
            if route == '/api/analyze':
                key = data.pop('api_key', '') or os.environ.get('OPENAI_API_KEY', '')
                if not key or not key.strip():
                    return self.json({'error': 'OpenAI key missing. Enter it locally for this run. No request made.'}, 409)
                if not isinstance(key, str) or len(key) > 512:
                    raise ValueError('Invalid credential format')
                track = data.get('audio_track', 0)
                if isinstance(track, bool) or track not in (0, 1, 2):
                    raise ValueError('Invalid audio track')
                if budget.summary()['uncertain_requests']:
                    raise RuntimeError('An uncertain paid request blocks new calls; review ledger')
                if ed.REPORT.exists():
                    raise RuntimeError('An editorial run exists. Review it first; no duplicate paid run started.')
                from analyze_openai import analyze
                launch_job(lambda: analyze(key, track, progress, data.get('audio_role_verified') is True))
                return self.json({'started': True})
            if route == '/api/render-ai':
                return self.json({'error': 'This milestone saves reviewed candidates only. Rendering is not enabled.'}, 409)
            if route == '/api/review':
                with REVIEW_LOCK:
                    if JOB['running']:
                        raise RuntimeError('Wait for the analysis to finish')
                    report = ed.load_report()
                    if data.get('run_id') != report['run_id']:
                        raise ValueError('Review belongs to a different run; refresh first')
                    ed.set_review(report, data.get('candidate_id'), data.get('decision'), data.get('start'),
                                  data.get('end'), data.get('note', ''), data.get('source_reviewed'))
                    ed.save_report(report)
                    ed.save_report(report, ROOT/'editorial'/'runs'/report['run_id']/'review.json')
                    ed.save_report({'run_id': report['run_id'], 'source': str(ed.SOURCE),
                        'audio_track': report['audio_track'], 'status': 'reviewed_ranges_only_not_rendered',
                        'ranges': ed.reviewed_ranges(report)}, ROOT/'editorial'/'reviewed-ranges.json')
                return self.json({'saved': True})
            return self.json({'error': 'Not found'}, 404)
        except (ValueError, RuntimeError) as exc:
            return self.json({'error': str(exc)}, 400)
        except Exception:
            return self.json({'error': 'Request rejected; inspect local setup'}, 500)

if __name__ == '__main__':
    budget.summary()
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Video Editor v2: http://127.0.0.1:{PORT} | Ctrl+C stops it. No autostart.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
