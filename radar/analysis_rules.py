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


def guard_groups(groups, items):
    """Invalid semantic merges are split, never dropped. Schema/coverage validated separately."""
    by_id = {i['id']: i for i in items}
    out, warnings = [], []
    for group in groups:
        ids = group['item_ids']
        if len(ids) == 1:
            out.append(group); continue
        anchor = group.get('merge_anchor', '')
        evidence = group.get('evidence', {})
        # Broad shared labels cannot identify a concrete object or event.
        broad = bool(re.fullmatch(r'(?:ai|人工智能|大模型)?(?:副业|赚钱|搞钱|变现|商业化|工具|方法|案例|项目|应用|内容|开发|工程|实践|模板|教程|技术|产品|服务|视频|创业|收入|与|和|及|\s)+', anchor, re.I))
        generic_words = {'ai', 'agent', 'agents', 'tools', 'tool', 'side', 'hustle', 'income', 'money', 'monetization', 'payment', 'payments', 'sdk', 'app', 'apps', 'development', 'template', 'templates', 'business', 'methods', 'method'}
        words = re.findall(r'[a-z]+', anchor.lower()) if isinstance(anchor, str) else []
        broad = broad or bool(words and set(words) <= generic_words)
        repos = {iid for iid in ids if by_id[iid].get('source') == 'github' or iid.startswith('github:')}
        valid = isinstance(evidence, dict) and len(norm(anchor)) >= 4 and not broad and len(repos) <= 1
        # Distinct repositories are distinct projects unless an explicit shared object is in their descriptions.
        for iid in ids:
            item = by_id[iid]
            quote = evidence.get(iid, '') if isinstance(evidence, dict) else ''
            valid = valid and grounded(quote, item) and norm(anchor) in norm(quote)
        if valid:
            out.append(group)
        else:
            warnings.append('缺少共同具体对象的原文证据，已拆为独立条目：' + group['title'])
            out.extend(singleton(by_id[iid], group['category']) for iid in ids)
    return out, warnings


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
