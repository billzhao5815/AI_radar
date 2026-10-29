"""Read saved real-run output; no API calls."""
import json
from collections import Counter
from pathlib import Path

root=Path(__file__).resolve().parent
r=json.loads((root/'result.json').read_text());s=r['state'];by_id={i['id']:i for i in r['items']}
passed={i['id'] for i in r['items'] if i['r04_status'] in ('relevant','uncertain')}
covered={i for g in s['groups'] for i in g['item_ids']};ungrouped=set(s.get('ungrouped_item_ids',[]))
assert covered|ungrouped==passed
assert not covered&ungrouped
assert all(len(g['item_ids'])==len(set(g['item_ids'])) for g in s['groups'])
assert all(len(g['representative_item_ids'])<=6 and set(g['representative_item_ids'])<=set(g['item_ids']) for g in s['groups'])
assert all(set(i['group_ids'])=={g['group_id'] for g in s['groups'] if i['id'] in g['item_ids']} for i in r['items'])
calls=json.loads((root/'calls.json').read_text())
summary=dict(candidate_count=len(r['items']),platforms=dict(Counter(i['source'] for i in r['items'])),r04=r['counts'],
             r05_input_count=len(passed),r05_batches=len(s['group_batches']),topics=len(s['groups']),
             grouped_unique=len(covered),ungrouped=len(ungrouped),ungrouped_percent=round(100*len(ungrouped)/len(passed),2),
             ungrouped_percent_all_candidates=round(100*len(ungrouped)/len(r['items']),2),
             multi_topic_items=sum(len(i['group_ids'])>1 for i in r['items']),
             cross_account_topics=sum(g['metrics']['author_count']>1 for g in s['groups']),
             cross_platform_topics=sum(g['metrics']['platform_count']>1 for g in s['groups']),
             complete=s['r05_complete'],status=s['status'],calls=len(calls),
             reported_model_cost_cny=round(sum(c['cost'] or 0 for c in calls),6),
             unknown_cost_calls=sum(c['cost'] is None for c in calls),
             errors=s['errors'],warnings=s.get('analysis_warnings',[]),costs=r['costs'])
(root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
lines=['# 真实样本主题与成员审阅清单','', '全部判断仅依据接口返回的标题和摘要，没有观看视频或增加视频识别。','']
for g in s['groups']:
    lines += [f"## {g['group_id']} · {g['title']}", '', f"类型：{g['type']}；信息 {g['metrics']['item_count']}；账号 {g['metrics']['author_count']}；平台 {g['metrics']['platform_count']}。", '', g['summary'], '']
    for iid in g['item_ids']:
        i=by_id[iid]
        lines += [f"- [{i['title']}]({i['url']}) — {i['source']} / {i['author']} / `{iid}`",f"  摘要：{i.get('text') or '无'}"]
    lines.append('')
lines += ['## 未聚合信息','']
for iid in sorted(ungrouped):
    i=by_id[iid];lines += [f"- [{i['title']}]({i['url']}) — {i['source']} / {i['author']} / `{iid}`；{i.get('text') or '无摘要'}"]
lines+=['','## R04 排除内容','']
for i in r['items']:
    if i['r04_status']=='irrelevant':lines += [f"- [{i['title']}]({i['url']}) — {i['r04_reason']}"]
(root/'topic-review.md').write_text('\n'.join(lines)+'\n')
print(json.dumps(summary,ensure_ascii=False,indent=2))
