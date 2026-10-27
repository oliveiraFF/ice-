"""Offline Whisper CLI transcription. No HTTP client, provider key or automatic retry."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import wave


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            value.update(chunk)
    return value.hexdigest()


def parse_segments(stdout, duration):
    pattern = re.compile(r'^\s*\[(\d{2}):(\d{2}):(\d{2}\.\d{3}) --> (\d{2}):(\d{2}):(\d{2}\.\d{3})\]\s*(.+?)\s*$')
    rows = []
    for line in stdout.splitlines():
        if not re.match(r'\s*\[\d{2}:', line):
            continue
        match = pattern.fullmatch(line)
        if not match:
            raise ValueError('本地引擎时间码无效，未采用；可人工粘贴逐字稿')
        start = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])
        end = int(match[4]) * 3600 + int(match[5]) * 60 + float(match[6])
        if not 0 <= start < end <= duration + .02 or rows and start < rows[-1]['end']:
            raise ValueError('本地字幕时间轴越界或重叠，未采用；可人工粘贴逐字稿')
        rows.append(dict(start=start, end=min(end, duration), text=match[7]))
    if not rows or len(rows) > 500 or sum(len(r['text']) for r in rows) > 29000:
        raise ValueError('未取得可用的带时间码语音，请检查音轨或改用人工逐字稿；未调用外部模型')
    return rows


class LocalASR:
    def __init__(self, data_dir):
        self.folder = Path(data_dir) / 'local-asr'

    def paths(self, value):
        result = {}
        for key, basename in [('ffmpeg', 'ffmpeg.exe'), ('whisper', 'whisper-cli.exe'), ('model', None)]:
            raw = value.get(key)
            if not isinstance(raw, str) or not raw or len(raw) > 2000 or any(ord(c) < 32 for c in raw):
                raise ValueError('请填写本机音视频程序、语音识别程序和模型的完整路径')
            path = Path(raw).expanduser()
            if not path.is_absolute() or not path.is_file() or not path.stat().st_size:
                raise ValueError('本地字幕配置文件不存在或不可用，请重新选择')
            if basename and path.name.lower() != basename or not basename and path.suffix.lower() != '.bin':
                raise ValueError('请选择 ffmpeg.exe、whisper-cli.exe 和 Whisper .bin 模型')
            result[key] = str(path.resolve())
        return result

    def config(self):
        value = {}
        try:
            path = self.folder / 'config.json'
            if path.exists():
                if path.stat().st_size > 16000:
                    raise ValueError('本地字幕配置过大，请重新保存')
                value = json.loads(path.read_text('utf-8'))
                if not isinstance(value, dict):
                    raise ValueError('本地字幕配置无效，请重新保存')
            paths = self.paths(value)
            return dict(paths, configured=True, message='本地字幕引擎已配置；提取字幕不联网、不收费')
        except (ValueError, OSError, UnicodeError) as exc:
            return dict({key: value.get(key, '') for key in ('ffmpeg', 'whisper', 'model')} if isinstance(value, dict) else {},
                        configured=False, message=str(exc) if value else '尚未配置本地字幕引擎')

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def configure(self, value):
        self.write(self.folder / 'config.json', self.paths(value))
        return self.config()

    def transcribe(self, media, mime, confirmed):
        if confirmed is not True:
            raise ValueError('请先确认在本机提取字幕；不会发送视频到外部服务')
        valid = mime == 'video/mp4' and media[4:8] == b'ftyp' or mime == 'video/webm' and media[:4] == b'\x1aE\xdf\xa3'
        if not valid or not 12 <= len(media) <= 20 * 1024 * 1024:
            raise ValueError('请选择20MB以内的MP4或WebM视频')
        config = self.config()
        if not config['configured']:
            raise ValueError(config['message'])
        startup = None
        if os.name == 'nt':
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
        with tempfile.TemporaryDirectory(prefix='ice-asr-') as temporary:
            folder = Path(temporary)
            if not str(folder).isascii():
                raise ValueError('当前语音引擎需要英文临时目录，请把系统TEMP设为可写英文路径后再试')
            source = 'input.mp4' if mime == 'video/mp4' else 'input.webm'
            (folder / source).write_bytes(media)
            # Stage model/media under ASCII names; the installed CLI crashes on Chinese model paths.
            try:
                shutil.copyfile(config['model'], folder / 'model.bin')
            except OSError:
                raise ValueError('无法准备本地语音模型，请检查模型读取权限及临时磁盘空间') from None
            model_hash = digest(folder / 'model.bin')
            engine_hash = digest(config['whisper'])
            def run(args, timeout):
                try:
                    result = subprocess.run(args, cwd=folder, timeout=timeout, startupinfo=startup,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                except (OSError, subprocess.TimeoutExpired):
                    raise ValueError('本地字幕程序无法运行或已超时；请核对程序和模型，不会自动重试') from None
                if result.returncode:
                    raise ValueError('本地字幕程序执行失败；请检查音轨、程序和模型兼容性，不会自动重试')
                return result.stdout
            run([config['ffmpeg'], '-v', 'error', '-i', source, '-t', '180.1', '-vn', '-ac', '1',
                 '-ar', '16000', '-c:a', 'pcm_s16le', 'audio.wav'], 30)
            try:
                with wave.open(str(folder / 'audio.wav'), 'rb') as f:
                    duration = f.getnframes() / f.getframerate()
                    signal = f.readframes(f.getnframes())
            except (OSError, wave.Error):
                raise ValueError('未取得有效音轨，可人工粘贴逐字稿继续') from None
            if not 0 < duration <= 180 or not any(signal):
                raise ValueError('音轨静音或超出3分钟，请改用有效音轨或人工逐字稿')
            raw = run([config['whisper'], '-m', 'model.bin', '-f', 'audio.wav', '-l', 'auto', '-t', '4', '-ng'], 300)
            try:
                segments = parse_segments(raw.decode('utf-8'), duration)
            except UnicodeError:
                raise ValueError('本地引擎未返回有效中文编码，请更换兼容引擎或人工粘贴逐字稿') from None
        metadata = dict(receipt_id=uuid.uuid4().hex, engine='whisper.cpp',
                        engine_sha256=engine_hash, model_sha256=model_hash,
                        media_sha256=hashlib.sha256(media).hexdigest(), duration=duration,
                        created_at=time.time(), reviewed=False, timing='ASR估计，需人工校对')
        result = dict(text=' '.join(r['text'] for r in segments), segments=segments, metadata=metadata)
        self.write(self.folder / 'results' / (metadata['receipt_id'] + '.json'), result)
        return result

    def verify(self, inputs, media_id):
        metadata = inputs.get('transcript_asr') or {}
        ident = metadata.get('receipt_id') if isinstance(metadata, dict) else None
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
            raise ValueError('缺少本地转写凭证，请重新提取或将文字作为人工逐字稿保存')
        try:
            path = self.folder / 'results' / (ident + '.json')
            if path.stat().st_size > 262144:
                raise ValueError('receipt too large')
            result = json.loads(path.read_text('utf-8'))
            if not isinstance(result, dict) or not all(k in result for k in ('metadata', 'text', 'segments')):
                raise ValueError('invalid receipt')
        except (OSError, ValueError, UnicodeError):
            raise ValueError('本地转写凭证不可读，原版本仍保留；可改为人工逐字稿继续') from None
        if (result['metadata'] != metadata or metadata['media_sha256'] != media_id
                or result['text'] != inputs.get('transcript') or result['segments'] != inputs.get('transcript_segments')):
            raise ValueError('字幕或素材已改变，请将修改稿标为人工逐字稿；不能沿用原ASR时间轴')
