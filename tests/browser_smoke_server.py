"""Isolated browser fixture. Model traffic stays on localhost; never use business data."""
import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop('TIKHUB_API_KEY', None)
os.environ.pop('LLM_ALLOW_PAID', None)
import app
from ai_directions import AIDirections
from video_creative import DIMENSIONS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18765)
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    calls = args.data_dir / 'fixture-calls.jsonl'

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            data = json.loads(payload['messages'][1]['content'][0]['text'])
            report = dict(summary='离线合成响应：仅验证状态、保存与界面，不代表真实模型质量。',
                observations=[dict(frame=1, evidence='合成测试画面', inference='待人工核对', advice='补充真实素材')],
                evaluations=[dict(dimension=d, verdict='无法判断', reason='仅作机制测试', frames=[]) for d in DIMENSIONS],
                adaptation=dict(reuse=[], adjust=[], avoid=[]), missing=['真实素材及人工质量评审'],
                deliverables={k:'离线合成成果：' + k for k in data['outputs']})
            text = json.dumps(report, ensure_ascii=False)
            if (args.data_dir / 'fail-next').exists():
                (args.data_dir / 'fail-next').unlink()
                text = '{invalid fixture'
            raw = json.dumps({'choices': [{'message': {'content': text}}]}, ensure_ascii=False).encode()
            with calls.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'model': payload['model'], 'max_tokens': payload.get('max_tokens'),
                    'frame_count': len(data['frames'])}) + '\n')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    model = HTTPServer(('127.0.0.1', 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    server = app.create_server(args.port, args.data_dir)
    stop = args.data_dir / 'stop-fixture'
    stop.unlink(missing_ok=True)
    def stop_when_requested():
        while not stop.exists():
            time.sleep(.2)
        server.shutdown()
    threading.Thread(target=stop_when_requested, daemon=True).start()
    AIDirections(args.data_dir / 'radar.sqlite3').configure(
        'http://127.0.0.1:' + str(model.server_address[1]) + '/v1', 'offline-browser-fixture')
    print('Isolated UI: http://127.0.0.1:' + str(server.server_address[1]) + '/creative', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        model.shutdown()
        model.server_close()
        (args.data_dir / 'closed-cleanly').write_text('HTTP servers closed normally', encoding='utf-8')


if __name__ == '__main__':
    main()
