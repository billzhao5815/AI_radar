"""The finite, executable menu offered to the configuration agent."""
from __future__ import annotations

from . import config, net
from .sources import bilibili, feeds, github, misc, shortvideo, xtw, youtube

NAMES = {'bili': 'B站', 'youtube': 'YouTube', 'douyin': '抖音', 'tiktok': 'TikTok',
         'xhs': '小红书', 'x': 'X', 'github': 'GitHub', 'hf': 'Hugging Face',
         'hn': 'Hacker News', 'news': '资讯 RSS'}
PAID = {'youtube', 'douyin', 'tiktok', 'xhs', 'x'}
# Only parameter values already exercised by the existing adapters are offered.
MENU = {
    'bili_search': ('bili', '关键词搜索', True, {'days': [7, 14, 30], 'pages': [1, 2], 'order': ['click', 'pubdate']}, 0),
    'bili_rank': ('bili', '分区排行榜', False, {'rid': config.BILI_RANK_RIDS}, 0),
    'bili_popular': ('bili', '热门视频', False, {'pages': [1, 2, 3]}, 0),
    'bili_hot': ('bili', '热搜词', False, {}, 0),
    'youtube': ('youtube', '视频搜索', True, {'upload_date': ['this_week', 'this_year'], 'duration': ['', 'short']}, .002),
    'douyin': ('douyin', '视频搜索', True, {'days': [7, 0], 'label': [0, 1]}, .01),
    'douyin_hot': ('douyin', '热搜榜', False, {}, .001),
    'tiktok': ('tiktok', '视频搜索', True, {'days': [7, 0]}, .001),
    'xhs': ('xhs', '一周热门视频笔记搜索', True, {}, .01),
    'x': ('x', '推文搜索', True, {'pages': [1, 2], 'days': [2, 7, 14], 'sort': ['Top', 'Latest']}, .001),
    'github_search': ('github', '仓库搜索', True, {'days': [7, 14, 30], 'time_field': ['pushed', 'created']}, 0),
    'github_trending': ('github', '热门仓库', False, {'since': ['daily', 'weekly', 'monthly']}, 0),
    'hf': ('hf', '热门模型与 Spaces', False, {'limit': [10, 20, 30]}, 0),
    'hn': ('hn', '近期讨论', False, {'hours': [36, 72, 168], 'min_points': [0, 20, 80]}, 0),
    'news': ('news', '已接入资讯订阅', False, {'hours': [48, 168]}, 0),
}


def menu():
    return [dict(id=k, source=v[0], name=v[1], query_required=v[2], options=v[3],
                 usd_per_call=v[4], available=v[0] not in PAID or bool(config.TIKHUB_API_KEY))
            for k, v in MENU.items()]


def estimate(tasks):
    calls = sum((t['options'].get('pages', 1) * 3) for t in tasks if MENU[t['capability_id']][4])
    usd = sum(MENU[t['capability_id']][4] * t['options'].get('pages', 1) * 3 for t in tasks)
    return {'max_calls_with_retries': calls, 'max_usd_est': round(usd, 4)}


def execute(task):
    """Run exactly one frozen task; collect adapter warnings instead of treating errors as empty."""
    c, q, o = task['capability_id'], task.get('query'), task['options']
    if c == 'bili_search':
        rows = bilibili.search([q], days=o.get('days', 7), pages=o.get('pages', 1), order=o.get('order', 'click'))
    elif c == 'bili_rank': rows = bilibili.rank_partitions([o.get('rid', config.BILI_RANK_RIDS[0])], generic=True)
    elif c == 'bili_popular': rows = bilibili.popular(o.get('pages', 1), generic=True)
    elif c == 'bili_hot': rows = bilibili.hot_words()
    elif c == 'youtube': rows = youtube.search([q], o.get('upload_date', 'this_week'), o.get('duration') or None)
    elif c == 'douyin': rows = shortvideo.douyin([(q, o.get('label', 0))], task['result_limit'], o.get('days', 7))
    elif c == 'douyin_hot': rows = misc.douyin_hot()
    elif c == 'tiktok': rows = shortvideo.tiktok([q], o.get('days', 7), generic=True)
    elif c == 'xhs': rows = shortvideo.xhs([q])
    elif c == 'x': rows = xtw.search([('plan', q)], o.get('pages', 1), days=o.get('days', 2), sort=o.get('sort', 'Top'), enforce_window=True)
    elif c == 'github_search': rows = github.search(o.get('days', 14), queries=[q], time_field=o.get('time_field', 'pushed'))
    elif c == 'github_trending': rows = github.trending(o.get('since', 'daily'))
    elif c == 'hf': rows = misc.hf_trending(o.get('limit', 20))
    elif c == 'hn': rows = misc.hn(o.get('hours', 36), o.get('min_points', 0), generic=True)
    elif c == 'news': rows = feeds.news(hours=o.get('hours', 48))
    else: raise ValueError('未实现的采集能力')
    return rows[:task['result_limit']]
