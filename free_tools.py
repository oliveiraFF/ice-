"""Free local imports and cached-media downloads. No supplier API calls."""
import ipaddress
import re
import socket
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_VIDEO_BYTES = 120 * 1024 * 1024
MEDIA_DOMAINS = ('douyin.com','douyinvod.com','bytecdn.cn','bytecdntp.com','byteoversea.com',
                 'ibytedtos.com','byteimg.com','pstatp.com','snssdk.com','tiktokcdn.com',
                 'tiktokcdn-us.com','tiktokv.com','xhscdn.com','xiaohongshu.com')


def validate_media_url(url, check_dns=False):
    if not isinstance(url, str) or len(url) > 12000:
        raise ValueError('没有可用的缓存视频直链')
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443)
            or not any(host == domain or host.endswith('.'+domain) for domain in MEDIA_DOMAINS)):
        raise ValueError('仅支持已缓存的抖音、小红书及对应媒体CDN的HTTPS直链；不请求解析接口')
    if check_dns:
        try:
            addresses = socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise ValueError('媒体地址不能指向本机或内网')
        except socket.gaierror:
            raise ValueError('媒体域名暂时无法解析')
    return url


class MediaRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        validate_media_url(newurl,check_dns=True)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def open_media(request):
    validate_media_url(request.full_url,check_dns=True)
    return build_opener(MediaRedirects()).open(request,timeout=15)


def download_cached_video(post, directory, opener=open_media):
    url = validate_media_url(post.get('video_url'))
    directory = Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    name = 'video-{}-{}'.format(int(post['id']),uuid.uuid4().hex[:8])
    temporary, target = directory/(name+'.part'), directory/(name+'.mp4')
    if temporary.resolve().parent != directory or target.resolve().parent != directory:
        raise ValueError('下载位置无效')
    request = Request(url,headers={'User-Agent':'Mozilla/5.0 LocalRadar/Free', 'Referer':'https://www.douyin.com/'})
    size, started = 0, time.monotonic()
    try:
        with opener(request) as response:
            content_type = response.headers.get('Content-Type','').split(';')[0].lower()
            if not (content_type.startswith('video/') or content_type == 'application/octet-stream'):
                raise ValueError('直链没有返回视频，可能已过期或被平台限制；未重新解析')
            length = response.headers.get('Content-Length')
            if length and int(length) > MAX_VIDEO_BYTES:
                raise ValueError('视频超过本次120MB下载上限')
            first = response.read(65536)
            if len(first)<12 or (first[4:8] != b'ftyp' and first[:4] != b'\x1aE\xdf\xa3' and first[:1] != b'G'):
                raise ValueError('响应不是可识别的视频文件；未保存')
            extension = '.webm' if first[:4] == b'\x1aE\xdf\xa3' else '.ts' if first[:1] == b'G' else '.mp4'
            target = directory/(name+extension)
            with temporary.open('xb') as output:
                chunk = first
                while chunk:
                    size += len(chunk)
                    if size > MAX_VIDEO_BYTES or time.monotonic()-started > 90:
                        raise ValueError('下载超过大小或时间上限，未保留不完整文件')
                    output.write(chunk)
                    chunk = response.read(65536)
            if length and size != int(length):
                raise ValueError('视频下载不完整，未保留文件')
        temporary.replace(target)
    except HTTPError as exc:
        raise ValueError('视频直链 HTTP {}，可能已过期或被平台限制；未调用解析接口'.format(exc.code))
    except (URLError, TimeoutError, OSError):
        raise ValueError('视频下载失败或媒体服务器不可达；未调用解析接口')
    finally:
        if temporary.exists():
            temporary.unlink()
    return dict(filename=target.name,bytes=size,url='/api/downloads/'+target.name,directory=str(directory))


def imported_posts(payload):
    rows = payload.get('posts') if isinstance(payload,dict) else payload
    if not isinstance(rows,list) or not 1 <= len(rows) <= 500:
        raise ValueError('视频JSON需为1～500条对象的数组，或包含posts数组的对象')
    posts = []
    for offset,row in enumerate(rows,1):
        if not isinstance(row,dict):
            raise ValueError('第{}条不是视频对象'.format(offset))
        platform = {'douyin':'dy','xiaohongshu':'xhs'}.get(row.get('platform'),row.get('platform'))
        ident = str(row.get('external_id') or '').strip()
        if platform not in ('dy','xhs') or not re.match(r'^[A-Za-z0-9_-]{1,100}$',ident):
            raise ValueError('第{}条需要platform（dy/xhs）和external_id（作品ID）'.format(offset))
        post = dict(platform=platform,external_id=ident,title=str(row.get('title') or '无标题视频')[:1000],
                    author=str(row.get('author') or '未知作者')[:100],cover=None,artwork='clean',tags=[],
                    source='本地文件导入 · 用户提供，未经平台核验',plays_source='用户导入',plays_checked_at=None)
        for key in ('plays','likes','saves','comments','followers','duration','published_at'):
            value = row.get(key)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float))
                                      or not 0 <= value <= 9007199254740991):
                raise ValueError('第{}条{}需为非负数或null'.format(offset,key))
            post[key] = int(value) if value is not None else None
        url = row.get('url')
        parsed = urlsplit(url) if isinstance(url,str) else None
        post['url'] = url if parsed and parsed.scheme=='https' and parsed.hostname in ('www.douyin.com','www.xiaohongshu.com') else None
        media = row.get('video_url')
        post['video_url'] = validate_media_url(media) if media else None
        posts.append(post)
    if len({(p['platform'],p['external_id']) for p in posts}) != len(posts):
        raise ValueError('同一文件含重复平台与作品ID，请先去重')
    return posts
