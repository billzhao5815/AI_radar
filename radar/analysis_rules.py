"""Conservative evidence checks shared by both analysis stages (no topic-specific prompts)."""
import re


def prose(item):
    # Hashtags and search metadata are discovery hints, never evidence of relevance.
    text = '\n'.join(str(item.get(k) or '') for k in ('title', 'text'))
    return re.sub(r'#[^\s#]+', '', text).strip()


def norm(text):
    return re.sub(r'\s+', '', text).casefold()


def grounded(quote, item):
    return isinstance(quote, str) and len(norm(quote)) >= 4 and norm(quote) in norm(prose(item))


def singleton(item, category='待进一步整理'):
    return dict(title=item.get('title') or item['id'], category=category,
                summary=(prose(item)[:240] or '缺少可用文本'), item_ids=[item['id']],
                merge_anchor='', evidence={})


TOPIC_TYPES = ('题材与内容形式', '玩法与方法', '事件与热点', '产品与项目', '商业模式与机会', '其他具体现象')


def guard_groups(groups, items):
    """Protect provenance and structure; semantic agreement belongs to R05."""
    allowed = {i['id'] for i in items}
    for g in groups:
        ids = g.get('item_ids')
        if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids)
                or len(ids) != len(set(ids)) or not set(ids) <= allowed
                or g.get('type') not in TOPIC_TYPES
                or any(not isinstance(g.get(k), str) or not g[k].strip() for k in ('title', 'summary'))):
            raise ValueError('R05 主题结构或来源引用不合法')
    return groups, []


# Formatting normalization only: never remove words, negation or numeric signs.
def _indexed_text(text):
    import unicodedata
    chars, positions = [], []
    for index, original in enumerate(text):
        for char in unicodedata.normalize('NFKC', original).casefold():
            if char in '.,' and index > 0 and index+1 < len(text) and text[index-1].isdigit() and text[index+1].isdigit():
                chars.append(char); positions.append(index); continue
            if char.isspace() or char in ',.，。:：;；!?！？\"\'“”‘’•':
                continue
            if char in '-‐‑–—' and index > 0 and index + 1 < len(text) and text[index-1].isalpha() and text[index+1].isalpha():
                continue
            chars.append(char); positions.append(index)
    return ''.join(chars), positions


def evidence_spans(value, item):
    """Locate every quoted fragment in one actual field; return original text and offsets.

    Legacy ellipsis strings are treated as multiple quotes, never as a continuous quote.
    No fuzzy similarity, translation or synonym matching is accepted.
    """
    if isinstance(value, str):
        value = [s.strip() for s in re.split(r'\.{3,}|…+', value) if s.strip()]
    if not isinstance(value, list) or not 1 <= len(value) <= 6:
        return None
    found = []
    for entry in value:
        field = entry.get('field') if isinstance(entry, dict) else None
        quote = entry.get('quote') if isinstance(entry, dict) else entry
        if field not in (None, 'title', 'text') or not isinstance(quote, str) or len(quote) > 600:
            return None
        needle, _ = _indexed_text(quote)
        if len(needle) < 4:
            return None
        match = None
        for key in ([field] if field else ['title', 'text']):
            original = str(item.get(key) or '')
            # Replace hashtags with spaces to preserve character offsets into original content.
            clean = re.sub(r'#[^\s#]+', lambda m: ' ' * len(m.group()), original)
            haystack, offsets = _indexed_text(clean)
            start = haystack.find(needle)
            if start >= 0:
                a, b = offsets[start], offsets[start+len(needle)-1]+1
                match = dict(field=key, start=a, end=b, quote=original[a:b])
                break
        if match is None:
            return None
        found.append(match)
    return found
