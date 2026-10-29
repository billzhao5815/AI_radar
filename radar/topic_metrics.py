"""Sample-relative topic metrics; no raw counts are compared across platforms."""
from copy import deepcopy
import math
from . import score, db


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def platform(item):
    return {'douyin_hot': 'douyin', 'bili_hot': 'bili'}.get(item.get('source'), item.get('source')) or ''


def signals(items, now=None):
    unique = {}
    for item in items:
        unique[item['id']] = db.merge_item(unique.get(item['id'], {}), deepcopy(item))
    rows = list(unique.values())
    for row in rows:
        row['source'] = platform(row)
        row['kind'] = row.get('kind') or ''
        row['published_at'] = row.get('published_at') if numeric(row.get('published_at')) else None
        row['metrics'] = {k: v for k, v in (row.get('metrics') or {}).items() if numeric(v) and v >= 0}
        if row['source'] in ('douyin', 'xhs'):
            row['metrics'].pop('views', None)
    score.annotate(rows, now=now)
    # Fall back to available primary counters when age or followers are absent.
    # Re-rank only within one platform, using the existing percentile function.
    by_source = {}
    for row in rows: by_source.setdefault(row['source'], []).append(row)
    for src, group in by_source.items():
        keys = (('likes',) if src in ('douyin', 'xhs') else ('views',) if src in ('bili', 'youtube', 'tiktok')
                else ('views', 'likes', 'bookmarks') if src == 'x' else ('stars', 'stars_today') if src == 'github'
                else ('rank', 'points', 'likes', 'views', 'comments'))
        fallback = [next((-r['metrics'][k] if k == 'rank' else r['metrics'][k] for k in keys if k in r['metrics']), None) for r in group]
        ranks = score._pct_ranks(fallback)
        derived = ('lph', 'lsr') if src in ('douyin', 'xhs') else ('vph', 'vsr') if src in ('bili', 'youtube', 'tiktok') else ('stars_per_day', 'stars_today') if src == 'github' else keys
        for row, value, rank in zip(group, fallback, ranks):
            if value is None:
                row['signals']['heat'] = None
            elif not any(row['signals'].get(k) is not None for k in derived):
                row['signals']['heat'] = round(rank, 1)
    return {r['id']: r for r in rows}


def account(row):
    identity = row.get('author_id') or row.get('author')
    return (row['source'], str(identity).strip()) if identity and str(identity).strip() else None


def enrich(groups, items, now=None):
    by_id = signals(items, now=now)
    result = []
    for group in groups:
        ids = sorted(set(group['item_ids']))
        members = [by_id[i] for i in ids]
        heats = sorted((i['signals']['heat'] for i in members if i['signals']['heat'] is not None), reverse=True)
        dates = [i['published_at'] for i in members if i.get('published_at') is not None]
        platforms = sorted({i['source'] for i in members if i['source']})
        metrics = dict(item_count=len(ids), author_count=len({account(i) for i in members if account(i)}),
                       platforms=platforms, platform_count=len(platforms),
                       earliest_published_at=min(dates) if dates else None,
                       latest_published_at=max(dates) if dates else None,
                       max_heat=max(heats) if heats else None,
                       avg_top_heat=round(sum(heats[:3])/len(heats[:3]), 2) if heats else None,
                       low_fans_hot_count=sum((i.get('extra') or {}).get('low_fans_hot') is True for i in members))
        # First choose strongest content, then prefer unseen platforms/accounts.
        representatives, authors, sources = [], set(), set()
        remaining = list(members)
        while remaining and len(representatives) < 6:
            remaining.sort(key=lambda i: (i['signals']['heat'] is None,
                i['source'] in sources, account(i) is None or account(i) in authors,
                -(i['signals']['heat'] or 0), -(i.get('published_at') or 0), i['id']))
            chosen = remaining.pop(0)
            representatives.append(chosen['id']); sources.add(chosen['source']); authors.add(account(chosen))
        result.append(dict(group, item_ids=ids, metrics=metrics, representative_item_ids=representatives))
    result.sort(key=lambda g: (g['metrics']['max_heat'] is None,
        -(g['metrics']['max_heat'] or 0), -(g['metrics']['avg_top_heat'] or 0),
        -g['metrics']['author_count'], -g['metrics']['platform_count'], -g['metrics']['item_count'],
        g['title'], g['type'], tuple(g['item_ids'])))
    return result
