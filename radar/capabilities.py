"""Fixed collection menu and deterministic R03 planning rules."""
from __future__ import annotations

from . import config, net
from .sources import bilibili, feeds, github, misc, shortvideo, wechat, xtw, youtube

NAMES = {'bili': 'B站', 'youtube': 'YouTube', 'douyin': '抖音', 'tiktok': 'TikTok',
         'xhs': '小红书', 'x': 'X', 'github': 'GitHub', 'hf': 'Hugging Face',
         'hn': 'Hacker News', 'news': '资讯 RSS', 'wechat': '微信'}
PAID = {'youtube', 'douyin', 'tiktok', 'xhs', 'x', 'wechat'}
# The first value of each option is the fixed default for new R03 plans.
# Remaining values document supported legacy plans; the agent never selects them.
MENU = {
    'bili_search': ('bili', '关键词搜索', True, {'days': [7, 14, 30], 'pages': [1, 2], 'order': ['click', 'pubdate']}, 0),
    'youtube': ('youtube', '视频搜索', True, {'upload_date': ['this_week', 'this_year'], 'duration': ['', 'short']}, .002),
    'douyin': ('douyin', '普通视频搜索', True, {'days': [7, 0], 'label': [0]}, .01),
    'douyin_low_followers': ('douyin', '低粉爆款搜索', True, {'days': [7, 0], 'label': [1]}, .01),
    'tiktok': ('tiktok', '视频搜索', True, {'days': [7, 0]}, .001),
    'xhs': ('xhs', '一周热门视频笔记搜索', True, {}, .01),
    'x': ('x', '推文搜索', True, {'pages': [1, 2], 'days': [2, 7, 14], 'sort': ['Top', 'Latest']}, .001),
    'wechat_article_search': ('wechat', '微信公众号文章搜索', True, {'days': [7], 'sort': ['latest']}, .01),
    'wechat_video_search': ('wechat', '微信视频号视频搜索', True, {'days': [7], 'sort': ['hot']}, .01),
    'github_search': ('github', '仓库搜索', True, {'days': [7, 14, 30], 'time_field': ['pushed', 'created']}, 0),
    'github_trending': ('github', '热门仓库', False, {'since': ['daily', 'weekly', 'monthly']}, 0),
    'hf': ('hf', '热门模型与 Spaces', False, {'limit': [10, 20, 30]}, 0),
    'hn': ('hn', '近期讨论', False, {'hours': [36, 72, 168], 'min_points': [0, 20, 80]}, 0),
    'news': ('news', '已接入资讯订阅', False, {'hours': [48, 168]}, 0),
}

MAX_KEYWORDS = 4
MAX_TASKS = 30
RESULT_LIMIT = 40


def menu():
    return [dict(
        id=k,
        source=v[0],
        name=v[1],
        query_required=v[2],
        options=v[3],
        usd_per_call=v[4],
        available=v[0] not in PAID or bool(config.TIKHUB_API_KEY),
    ) for k, v in MENU.items()]



def estimate(tasks):
    calls = sum((t['options'].get('pages', 1) * 3) for t in tasks if MENU[t['capability_id']][4])
    usd = sum(MENU[t['capability_id']][4] * t['options'].get('pages', 1) * 3 for t in tasks)
    return {'max_calls_with_retries': calls, 'max_usd_est': round(usd, 4)}


def build_tasks(sources, keywords):
    """Cover every selected capability, then add keywords in stable MENU order."""
    selected = [(c, v) for c, v in MENU.items() if v[0] in sources]
    if {v[0] for _, v in selected} != set(sources):
        raise ValueError('所选平台没有可用的采集能力')
    search_sources = list(dict.fromkeys(v[0] for _, v in selected if v[2]))
    for source in search_sources:
        if not keywords.get(source): raise ValueError(NAMES[source] + '缺少搜索关键词')

    def task(c, v, query=''):
        return dict(source=v[0], capability_id=c, query=query,
                    options={k: values[0] for k, values in v[3].items()}, result_limit=RESULT_LIMIT)

    def fits(tasks):
        budget = estimate(tasks)
        return (len(tasks) <= MAX_TASKS and budget['max_calls_with_retries'] <= config.TIKHUB_MAX_CALLS
                and budget['max_usd_est'] <= config.TIKHUB_MAX_USD)

    tasks = [task(c, v, keywords[v[0]][0] if v[2] else '') for c, v in selected]
    if not fits(tasks):
        raise ValueError('采集预算不足以覆盖所选渠道的全部固定能力（每项搜索能力仅用一个关键词）。'
                         '请减少所选渠道，或调整 .env 中 TIKHUB_MAX_CALLS / TIKHUB_MAX_USD 后重启服务')
    used = {source: keywords[source][:1] if source in search_sources else [] for source in sources}
    # One extra keyword always applies to ALL keyword-based capabilities of that source.
    blocked = set()
    for index in range(1, MAX_KEYWORDS):
        for source in search_sources:
            if source in blocked or index >= len(keywords[source]): continue
            extra = [task(c, v, keywords[source][index]) for c, v in selected if v[0] == source and v[2]]
            if fits(tasks + extra):
                tasks.extend(extra)
                used[source].append(keywords[source][index])
            else:
                blocked.add(source)
    for index, t in enumerate(tasks, 1): t['id'] = f't{index}'
    notes = [f'{NAMES[s]}：受任务数量或采集预算限制，使用前 {len(used[s])} 个关键词（共 {len(keywords[s])} 个），保留全部固定能力。'
             for s in search_sources if len(used[s]) < len(keywords[s])]
    return tasks, used, notes


def execute(task):
    """Run exactly one frozen task; collect adapter warnings instead of treating errors as empty."""
    c, q, o = task['capability_id'], task.get('query'), task['options']
    if c == 'bili_search':
        rows = bilibili.search([q], days=o.get('days', 7), pages=o.get('pages', 1), order=o.get('order', 'click'))
    elif c == 'bili_rank': rows = bilibili.rank_partitions([o.get('rid', config.BILI_RANK_RIDS[0])], generic=True)
    elif c == 'bili_popular': rows = bilibili.popular(o.get('pages', 1), generic=True)
    elif c == 'bili_hot': rows = bilibili.hot_words()
    elif c == 'youtube': rows = youtube.search([q], o.get('upload_date', 'this_week'), o.get('duration') or None)
    elif c in ('douyin', 'douyin_low_followers'):
        rows = shortvideo.douyin([(q, o.get('label', 1 if c == 'douyin_low_followers' else 0))], task['result_limit'], o.get('days', 7))
    elif c == 'douyin_hot': rows = misc.douyin_hot()
    elif c == 'tiktok': rows = shortvideo.tiktok([q], o.get('days', 7), generic=True)
    elif c == 'xhs': rows = shortvideo.xhs([q])
    elif c == 'x': rows = xtw.search([('plan', q)], o.get('pages', 1), days=o.get('days', 2), sort=o.get('sort', 'Top'), enforce_window=True)
    elif c == 'wechat_article_search': rows = wechat.search(q, 'article', o.get('days', 7), o.get('sort', 'latest'))
    elif c == 'wechat_video_search': rows = wechat.search(q, 'video', o.get('days', 7), o.get('sort', 'hot'))
    elif c == 'github_search': rows = github.search(o.get('days', 14), queries=[q], time_field=o.get('time_field', 'pushed'))
    elif c == 'github_trending': rows = github.trending(o.get('since', 'daily'))
    elif c == 'hf': rows = misc.hf_trending(o.get('limit', 20))
    elif c == 'hn': rows = misc.hn(o.get('hours', 36), o.get('min_points', 0), generic=True)
    elif c == 'news': rows = feeds.news(hours=o.get('hours', 48))
    else: raise ValueError('未实现的采集能力')
    return rows[:task['result_limit']]
