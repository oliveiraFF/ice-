"""Validate user-confirmed visible-page captures; no network access."""
import time
from urllib.parse import urlsplit, unquote
from free_tools import imported_posts


def browser_posts(body):
    keyword = str(body.get('keyword') or '').strip()
    source = body.get('source_url')
    parsed = urlsplit(source) if isinstance(source, str) and len(source) <= 3000 else None
    if (not keyword or len(keyword) > 40 or not parsed or parsed.scheme != 'https'
            or parsed.netloc != 'www.douyin.com'
            or unquote(parsed.path).rstrip('/') not in ('/search/' + keyword, '/jingxuan/search/' + keyword)):
        raise ValueError('请选择抖音关键词搜索结果页，并保留对应的关键词')
    captured = body.get('captured_at')
    if (isinstance(captured, bool) or not isinstance(captured, (int, float))
            or not 946684800 < captured <= time.time() + 300):
        raise ValueError('网页采集时间无效，请重新采集')
    rows = body.get('posts')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError('每次确认收录1～20条网页视频')
    posts = imported_posts(rows)
    for post, raw in zip(posts, rows):
        if post['platform'] != 'dy' or not post['external_id'].isdigit():
            raise ValueError('网页采集只接受抖音数字作品ID')
        cover = raw.get('cover')
        image = urlsplit(cover) if isinstance(cover, str) and len(cover) <= 6000 else None
        host = image.hostname if image else ''
        allowed = ('douyinpic.com', 'byteimg.com', 'pstatp.com')
        post['cover'] = cover if image and image.scheme == 'https' and image.netloc == host and any(
            host == domain or host.endswith('.' + domain) for domain in allowed) else None
        post['url'] = 'https://www.douyin.com/video/' + post['external_id']
        post['source'] = 'Chrome可见页面采集 · 用户确认，未经独立核验'
        post['plays_source'] = '网页明确标注的播放量' if post['plays'] is not None else '网页未提供播放量'
        post['plays_checked_at'] = captured if post['plays'] is not None else None
        post['captured_at'] = captured
        post['source_url'] = 'https://www.douyin.com/search/' + keyword
    return keyword, posts
