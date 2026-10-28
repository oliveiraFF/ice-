"""Explicit localhost fixture harness. Never bundled; cannot call a real provider."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from catalog import Catalog
from test_large_response import fixture_catalog, large_payload, KEY, LIMIT, ROUTE


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);args=parser.parse_args()
    args.data_dir.mkdir(parents=True,exist_ok=True)
    business=[]
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            parsed=urlsplit(self.path)
            if parsed.path=='/status':value=dict(business=business,synthetic=True,real_provider_calls=0)
            elif parsed.path.endswith('get_endpoint_info'):value=dict(code=200,data=dict(endpoint_uri=ROUTE,endpoint_cost='0'))
            elif parsed.path==ROUTE:
                business.append(parsed.path)
                value=dict(code=200,data='x'*(LIMIT+1000)) if 'oversize' in parse_qs(parsed.query).get('share_url',[''])[0] else large_payload()
            else:self.send_error(404);return
            raw=json.dumps(value,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
    fixture=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=fixture.serve_forever,daemon=True).start()
    def local_only(request,**kwargs):
        parsed=urlsplit(request.full_url if hasattr(request,'full_url') else request)
        if parsed.hostname!='api.tikhub.io':raise AssertionError('No external network is authorized')
        target='http://127.0.0.1:'+str(fixture.server_address[1])+parsed.path+('?' + parsed.query if parsed.query else '')
        return urlopen(Request(target),**kwargs)
    app.urlopen=local_only
    snapshot=fixture_catalog();snapshot['items'][0]['title']='合成技术验收 · 大响应视频资料'
    def catalog(path,database,**kwargs):
        instance=Catalog(snapshot,database,**kwargs);instance.manage('GET '+ROUTE,'enable');return instance
    app.Catalog=catalog
    os.environ.update(TIKHUB_API_KEY=KEY,SHORT_VIDEO_OPS_WORKSPACE='',LLM_ALLOW_PAID='0')
    server=app.create_server(0,args.data_dir)
    (args.data_dir/'acceptance-session.json').write_text(json.dumps(dict(port=server.server_address[1],fixture_port=fixture.server_address[1],pid=os.getpid())),encoding='utf-8')
    try:server.serve_forever()
    finally:server.server_close();fixture.shutdown();fixture.server_close()


if __name__=='__main__':main()
