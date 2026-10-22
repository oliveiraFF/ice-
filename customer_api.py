"""Fixed business operations for the local customer edition; no general API proxy."""
import json
import re
import sqlite3
from contextlib import closing
from decimal import Decimal
from client_credentials import CredentialVault

UNIT = Decimal('0.001')
POST_FIELDS = ('id', 'platform', 'external_id', 'title', 'author', 'plays', 'likes', 'saves', 'comments',
               'followers', 'published_at', 'duration', 'cover', 'url', 'video_url', 'artwork', 'description',
               'first_seen', 'updated_at', 'plays_checked_at', 'keyword_ids')


class ClientAPI:
    def __init__(self, folder, store, catalog):
        self.store, self.catalog = store, catalog
        self.vault, self.key, self.restore_error = CredentialVault(folder), '', False
        with closing(store.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS client_identity(id INTEGER PRIMARY KEY CHECK(id=1), customer TEXT NOT NULL)')
            db.commit()
            row = db.execute('SELECT customer FROM client_identity WHERE id=1').fetchone()
        self.customer = row[0] if row else ''
        try:
            customer, key = self.vault.load()
            if key and customer != self.customer: raise ValueError()
            self.key = key
        except ValueError:
            self.restore_error = True

    def config(self):
        return dict(customer=self.customer, connected=bool(self.key), remembered=self.vault.path.exists(),
                    restore_error=self.restore_error, access=self.access())

    def access(self):
        access = self.catalog.access_state()
        return dict(enabled=access['enabled'], active=access['active'],
                    limit=int(Decimal(access['limit']) / UNIT), spent=int(Decimal(access['spent']) / UNIT),
                    remaining=int(Decimal(access['remaining']) / UNIT), expires_at=access['expires_at'])

    def configure(self, body):
        customer, key = body.get('customer'), body.get('key', '')
        calls, days = body.get('calls'), body.get('days')
        remember, enabled = body.get('remember'), body.get('enabled')
        if not isinstance(customer, str) or not 1 <= len(customer.strip()) <= 60 or re.search(r'[\x00-\x1f]', customer):
            raise ValueError('请填写有效客户标识（最多60字）')
        customer = customer.strip()
        if self.customer and customer != self.customer:
            raise ValueError('此数据目录已绑定其他客户；请使用独立的软件文件夹')
        if (not isinstance(key, str) or len(key) > 500 or re.search(r'[\x00-\x20\x7f-\uffff]', key)
                or not (key or self.key)):
            raise ValueError('请填写有效的专属访问密钥')
        if (type(calls) is not int or not 0 <= calls <= 1000000 or type(remember) is not bool
                or type(enabled) is not bool or days is not None and (type(days) is not int or not 1 <= days <= 3650)):
            raise ValueError('调用次数、开关或有效天数无效')
        key = key or self.key
        if remember: self.vault.save(customer, key)
        else: self.vault.forget()
        with closing(self.store.connect()) as db:
            db.execute('INSERT OR IGNORE INTO client_identity VALUES(1,?)', (customer,)); db.commit()
        self.customer, self.key, self.restore_error = customer, key, False
        self.catalog.configure_access(enabled, str(UNIT*calls), days)
        return self.config()

    def forget(self):
        self.vault.forget(); self.key = ''; self.restore_error = False
        return self.config()

    def public_state(self, state):
        result = dict(state, last_scan=None)
        result['posts'] = [dict({k:p[k] for k in POST_FIELDS if k in p},
                               source='本地演示样本' if p.get('source') == 'demo' else '已收录视频',
                               plays_source='实际返回字段' if p.get('plays') is not None else '未返回播放量') for p in state['posts']]
        return result

    def search(self, body, call, extract):
        keyword, kind = body.get('keyword', ''), body.get('kind', 'search')
        if kind not in ('search','hot') or not isinstance(keyword,str) or len(keyword.strip()) > 40:
            raise ValueError('检索条件无效')
        keyword = keyword.strip()
        if kind == 'search' and not keyword: raise ValueError('请输入关键词')
        if not self.key: raise ValueError('请先配置专属访问密钥')
        if not self.access()['active']: raise ValueError('调用未开启、次数预算不足或已到期，请检查连接设置')
        ident = 'discover.search' if kind == 'search' else 'discover.hot'
        if kind == 'search':
            query, request_body = dict(keyword=keyword,offset=0,count=20,sort_type=0,publish_time=0), None
        else:
            query, request_body = {}, dict(page=1,page_size=10,date_window=168,sub_type=1001,keyword=keyword,tags=[])
        self.catalog.manage(ident, 'enable')
        try:
            result = self.catalog.run(ident, self.key, query, request_body, call)
        except ValueError:
            raise ValueError('检索服务未完成：请检查密钥、赠送额度及次数设置（S01）；未自动重试') from None
        if not result['ok'] or result['truncated']:
            raise ValueError('本次检索未获得完整结果（S02）；可能已消耗一次预算，未自动重试')
        posts = extract(json.loads(result['result']), 'dy')
        keyword_id = None
        if posts:
            keyword_id = self.store.add_keyword(keyword or '抖音热门')
            for post in posts:
                post['source'] = '关键词检索' if kind == 'search' else '热门榜单'
                post['plays_source'] = '实际返回字段' if post.get('plays') is not None else '未返回播放量'
            self.store.put_posts(keyword_id,posts,'live')
        return dict(count=len(posts),keyword_id=keyword_id,access=self.access(),
                    message='已收录 {} 条视频；播放量未返回时显示未知。'.format(len(posts)) if posts else '本次未返回可识别的视频，未自动重试。')
