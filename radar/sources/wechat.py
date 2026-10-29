"""WeChat article / Channels search via TikHub's flattened raw=false responses.

One page per task, no detail calls or media downloads. API errors and unexpected
response shapes propagate to the existing resumable workflow task error handler.
"""
from __future__ import annotations

import hashlib
import html
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .. import net
from .common import count, relative_ts

ARTICLE_SEARCH = '/api/v1/wechat_search/v2/fetch_search'
VIDEO_SEARCH = '/api/v1/wechat_search/v2/fetch_search_videos'
BJ = timezone(timedelta(hours=8))


def _text(value):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ''
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', str(value)))).strip()


def _url(value):
    if not isinstance(value, str):
        return ''
    value = html.unescape(value.strip())
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ('http', 'https') and parsed.hostname else ''
    except ValueError:
        return ''


def _article_identity(url):
    """Discard share/tracking parameters without merging different article issues."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    if parts.hostname == 'mp.weixin.qq.com':
        if all(query.get(k) for k in ('__biz', 'mid', 'idx')):
            return urlencode({k: query[k][0] for k in ('__biz', 'mid', 'idx')})
        if parts.path.startswith('/s/'):
            return parts.path
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ''))


def _published(value, now):
    value = _text(value)
    if not value:
        return None
    try:
        timestamp = float(value)
        if timestamp > 1e12:
            timestamp /= 1000
        return timestamp if timestamp > 0 else None
    except ValueError:
        pass
    relative = relative_ts(value, now)
    if relative is not None:
        return relative
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=BJ)).timestamp()
    except ValueError:
        return None


def _item(row, kind, keyword, now):
    jump = row.get('jumpInfo') if isinstance(row.get('jumpInfo'), dict) else {}
    ext = jump.get('extInfo') if isinstance(jump.get('extInfo'), dict) else {}
    url = next((v for v in (_url(row.get('url')), _url(row.get('content_url')),
                           _url(jump.get('url')), _url(jump.get('jumpUrl'))) if v), '')
    # Python keeps 64-bit JSON integers intact; stringify before storing or displaying.
    doc_id = _text(row.get('docID') or row.get('doc_id'))
    export_id = _text(row.get('exportId'))
    feed_id = _text(ext.get('feedNonceId'))
    if kind == 'article' and url:
        identity = 'url:' + _article_identity(url)
    else:
        identity = doc_id or feed_id or export_id or url
    if not identity:
        raise ValueError('微信搜索结果缺少稳定 ID 或链接')
    title = _text(row.get('title'))
    description = _text(row.get('desc') or row.get('description') or row.get('digest'))
    published = _published(row.get('publish_time') or row.get('publishTime') or
                           row.get('createTime') or row.get('timestamp'), now)
    return dict(
        id='wechat:' + kind + ':' + hashlib.sha256(identity.encode()).hexdigest(),
        source='wechat', kind=kind, title=(title or description)[:200], text=description,
        url=url, thumb=_url(row.get('thumb_url') or row.get('thumbUrl') or row.get('coverUrl')),
        author=_text(row.get('nickname') or row.get('nickName') or jump.get('nickName')),
        author_id=_text(row.get('username') or jump.get('userName')),
        published_at=published,
        metrics={'views': count(row.get('readCount') if kind == 'article' else row.get('playCount')),
                 'likes': count(row.get('likeCount')), 'comments': count(row.get('commentCount'))},
        extra={'wechat_type': kind, 'doc_id': doc_id, 'export_id': export_id,
               'feed_nonce_id': feed_id},
        query='wechat:' + kind + ':' + keyword,
    )


def search(keyword: str, kind: str, days: int = 7, sort: str | None = None) -> list[dict]:
    if kind not in ('article', 'video') or days != 7:
        raise ValueError('微信采集仅支持文章或视频、最近7天')
    sort = sort or ('latest' if kind == 'article' else 'hot')
    if sort not in ('latest', 'hot'):
        raise ValueError('微信搜索排序无效')
    params = dict(keyword=keyword, publish_time='week', sort=sort, offset=0, raw=False)
    if kind == 'article':
        params['business_type'] = 'article'
    else:
        params['duration'] = 'all'
    data = net.tikhub(ARTICLE_SEARCH if kind == 'article' else VIDEO_SEARCH, params, post=True)
    if not isinstance(data, dict):
        raise net.FetchError('微信搜索响应不是对象')
    rows = data.get('items')
    if rows is None and data.get('no_more'):
        return []
    if not isinstance(rows, list):
        raise net.FetchError('微信搜索响应缺少 items 列表')
    now, result, errors = time.time(), {}, []
    for row in rows:
        try:
            if not isinstance(row, dict):
                raise ValueError('微信搜索条目不是对象')
            item = _item(row, kind, keyword, now)
            # The server applies the time filter; additionally reject known stale dates.
            if item['published_at'] is not None and item['published_at'] < now - days * 86400:
                continue
            result.setdefault(item['id'], item)
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append(str(exc))
    if errors:
        warning = f'微信{kind}搜索有 {len(errors)} 条结果解析失败：{errors[0]}'
        if not result:
            raise net.FetchError(warning)
        warnings = net.collection_errors.get()
        if warnings is not None:
            warnings.append(warning)
    return list(result.values())
