"""Portable Windows desktop entry point. Build dependencies stay outside the app."""
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os
import sys
import threading
import traceback

from app import create_server


def portable_home():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


def message(text):
    ctypes.windll.user32.MessageBoxW(None, text, 'ice运营台', 0x10)


def main(edition='owner'):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=portable_home() / 'data')
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    server, thread, lock = None, None, None
    session = data_dir / 'desktop-session.json'
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        import msvcrt
        lock = (data_dir / 'desktop.lock').open('a+b')
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            message('这份ice运营台已经在运行，请切回已打开的窗口。')
            return
        handler = RotatingFileHandler(str(data_dir / 'desktop.log'), maxBytes=1000000, backupCount=2, encoding='utf-8')
        logging.basicConfig(level=logging.WARNING, handlers=[handler])
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w')
        window = None
        closing = threading.Event()
        def request_exit():
            if window is None:
                raise ValueError('桌面窗口尚未就绪，请稍后退出')
            if not closing.is_set():
                closing.set()
                threading.Timer(.2, window.destroy).start()
        server = create_server(0, data_dir, data_dir.parent / 'downloads', edition=edition, on_exit=request_exit)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        session.write_text(json.dumps({'pid': os.getpid(), 'port': port}), encoding='utf-8')
        import webview
        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.settings['ALLOW_FILE_URLS'] = False
        window = webview.create_window('ice运营台', 'http://127.0.0.1:' + str(port), width=1280, height=900,
                              min_size=(900, 600), text_select=True, background_color='#e9eded')
        webview.start(gui='edgechromium', private_mode=False, storage_path=str(data_dir / 'webview'),
                      icon=str(Path(__file__).resolve().parent / 'radar.ico'))
    except Exception:
        try:
            (data_dir / 'desktop-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        except OSError:
            pass
        message('软件启动失败。请将整个文件夹解压到可写目录，并确认Windows已安装Microsoft Edge WebView2运行时。\n\n错误详情：' + str(data_dir / 'desktop-error.log'))
    finally:
        if server:
            if thread and thread.is_alive():
                server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=3)
        if session.exists() and server:
            session.unlink()
        if lock:
            lock.close()


if __name__ == '__main__':
    main()
