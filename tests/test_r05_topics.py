"""Offline contract scenarios. Model semantics are scripted, never inferred by keywords in production."""
import json
from unittest.mock import patch
import unittest
import test_workflow as fixtures
from radar import workflow as w, topic_metrics as tm
from radar.analysis_rules import guard_groups


def topic(ids, title='检查点回放', kind='玩法与方法'):
    return dict(title=title, type=kind, summary='来源描述了共同的具体做法', item_ids=ids)


class TopicContract(unittest.TestCase):
    def test_three_monitoring_directions_and_release(self):
        scenarios = [
            ('AI短剧', '打工人穿越古代用现代职场规则破局', '题材与内容形式', ['douyin:1','bili:2']),
            ('AI Agent', '持久化检查点与失败回放', '玩法与方法', ['github:a','github:b']),
            ('AI商业化', '面向小商家的按月商品图订阅服务', '商业模式与机会', ['x:1','x:2']),
            ('AI模型', 'Acme模型正式发布', '事件与热点', ['x:1','bili:2']),
            ('AI模型', 'Acme模型正式发布', '产品与项目', ['x:1']),
        ]
        for goal, title, kind, ids in scenarios:
            with self.subTest(goal=goal, ids=ids):
                raw=dict(topics=[topic(ids,title,kind)],ungrouped_item_ids=[])
                result=w.validate_groups(raw, ids)
                self.assertEqual(guard_groups(result['topics'],[dict(id=i) for i in ids])[0],raw['topics'])

    def test_multiple_topics_and_unrelated_tools(self):
        raw=dict(topics=[topic(['a','b']),topic(['a'],'按月托管收费','商业模式与机会')],ungrouped_item_ids=['c','d'])
        self.assertEqual(w.validate_groups(raw, ['a','b','c','d']),raw)
        self.assertIn('不得仅因同属宽泛领域而合并',w.R05)

    def test_invalid_contracts(self):
        for ids, ungrouped in [(['a','a'],['b']), (['a','z'],['b']), (['a'],[]), (['a'],['a','b']), (['a'],['b','b'])]:
            with self.subTest(ids=ids,ungrouped=ungrouped), self.assertRaises(ValueError):
                w.validate_groups(dict(topics=[topic(ids)],ungrouped_item_ids=ungrouped),['a','b'])
        with self.assertRaises(ValueError):
            w.validate_groups(dict(topics=[topic(['a'],kind='AI工具')],ungrouped_item_ids=[]),['a'])

    def test_platform_metrics_unknown_dedup_and_stable_sort(self):
        rows=[]
        for n, source, kind, metrics in [
            (1,'bili','video',{'views':1000,'followers':10}),
            (2,'douyin','video',{'views':999999,'likes':100,'followers':10}),
            (3,'x','tweet',{'views':200,'likes':10,'bookmarks':4}),
            (4,'github','repo',{'stars':50}),
            (5,'feed','article',{}),
            (6,'xhs','video',{'likes':50})]:
            rows.append(dict(fixtures.item(n,source=source),kind=kind,metrics=metrics,published_at=None,author_id=None,author=None))
        rows[0]['extra']['low_fans_hot']=True
        with patch.object(tm.score.time,'time',return_value=10000):
            signal=tm.signals(rows)
            self.assertIsNone(signal['feed:5']['signals']['heat'])
            self.assertNotIn('views',signal['douyin:2']['metrics'])
            self.assertTrue(all(signal[r['id']]['signals']['heat'] is not None for r in rows if r['source']!='feed'))
            groups=[topic([r['id'] for r in rows]),topic(['feed:5'],'没有传播数据','产品与项目')]
            result=tm.enrich(groups,rows+[rows[0]])
            self.assertEqual(result,tm.enrich(groups,list(reversed(rows))))
        m=result[0]['metrics']
        self.assertEqual((m['item_count'],m['author_count'],m['platform_count']),(6,0,6))
        self.assertEqual(m['low_fans_hot_count'],1)
        self.assertIsNone(m['earliest_published_at'])
        self.assertIsNone(result[1]['metrics']['max_heat'])
        self.assertEqual(len(result[0]['representative_item_ids']),6)

    def test_author_identity_uses_platform_and_id(self):
        rows=[fixtures.item(1),fixtures.item(2),fixtures.item(3,source='x')]
        self.assertEqual(tm.enrich([topic([r['id'] for r in rows])],rows)[0]['metrics']['author_count'],2)


class TopicWorkflow(fixtures.WorkflowTest):
    def test_three_goals_end_to_end_with_scripted_model(self):
        scenarios = [('AI短剧', '古代职场反转短剧', '题材与内容形式', 'douyin', 'video'),
                     ('AI Agent', '持久化检查点回放', '玩法与方法', 'github', 'repo'),
                     ('AI商业化', '小店商品图按月订阅', '商业模式与机会', 'x', 'tweet')]
        for goal, title, kind, source, content_kind in scenarios:
            with self.subTest(goal=goal):
                self.activate(fixtures.plan(goal=goal))
                rows=[dict(fixtures.item(n, title, source),kind=content_kind,author_id=str(n)) for n in (1,2)]
                def provider(prompt,system,tokens):
                    if system!=w.R05: return fixtures.model(prompt,system,tokens)
                    payload=json.loads(prompt)
                    self.assertEqual(payload['monitoring_goal'],goal)
                    self.assertEqual({i['source'] for i in payload['items']},{source})
                    raw=dict(topics=[topic([i['item_id'] for i in payload['items']],title,kind)],ungrouped_item_ids=[])
                    return json.dumps(raw),dict(prompt_tokens=100,completion_tokens=100)
                with patch.object(w.llm,'complete_once',side_effect=provider),patch.object(w.cap,'execute',return_value=rows):
                    rid=w.new_run(self.con);w.execute_run(rid)
                result=w.result(self.con,rid)
                self.assertEqual(result['state']['status'],'ok',result['state']['errors'])
                self.assertEqual(result['state']['groups'][0]['metrics']['author_count'],2)
                self.assertEqual(result['state']['groups'][0]['title'],title)

    def test_interrupted_later_merge_reuses_successful_pages(self):
        self.activate();seen=[]
        def provider(prompt,system,tokens):
            payload=json.loads(prompt)
            if system==w.R05 and 'units' in payload:
                seen.append(payload)
                if len(seen)==3: raise RuntimeError('interruption')
            return fixtures.model(prompt,system,tokens)
        with patch.object(w.llm,'complete_once',side_effect=provider),patch.object(w.cap,'execute',return_value=[fixtures.item(n) for n in range(45)]):
            rid=w.new_run(self.con);w.execute_run(rid)
        self.assertFalse(w.result(self.con,rid)['state']['r05_complete'])
        recovered=[]
        def provider2(prompt,system,tokens):
            recovered.append(json.loads(prompt));return fixtures.model(prompt,system,tokens)
        with patch.object(w.llm,'complete_once',side_effect=provider2):w.execute_run(rid)
        self.assertEqual(len(recovered),1)
        self.assertEqual(recovered[0],seen[-1])
        self.assertTrue(w.result(self.con,rid)['state']['r05_complete'])

    def test_r05_revision_does_not_repeat_r04(self):
        self.activate();rid,_=self.run_with([fixtures.item(1)])
        called=[]
        original=w.R05
        def provider(prompt,system,tokens):
            called.append(system)
            return fixtures.model(prompt,system,tokens)
        with patch.object(w,'R05',original+'\n新版提示'),patch.object(w.llm,'complete_once',side_effect=provider):
            w.execute_run(rid)
        self.assertEqual(called,[original+'\n新版提示'])

    def test_cross_batch_ungrouped_form_topic_with_overlap_and_bounded_payload(self):
        self.activate();requests=[]
        def provider(prompt,system,tokens):
            p=json.loads(prompt)
            if system!=w.R05:return fixtures.model(prompt,system,tokens)
            requests.append(p)
            if 'items' in p:
                self.assertLessEqual(len(p['items']),40)
                self.assertIn('monitoring_goal',p)
                self.assertTrue(all('metrics' not in i and 'signals' not in i for i in p['items']))
                raw=dict(topics=[],ungrouped_item_ids=[i['item_id'] for i in p['items']])
            else:
                self.assertLessEqual(len(p['units']),40)
                self.assertTrue(all(len(u['representatives'])<=2 for u in p['units']))
                refs=[u['ref_id'] for u in p['units']]
                raw=dict(topics=[dict(title='持久化回放',type='玩法与方法',summary='相同方法',ref_ids=refs),
                                 dict(title='托管订阅',type='商业模式与机会',summary='相同模式',ref_ids=refs)],ungrouped_ref_ids=[])
            return json.dumps(raw),dict(prompt_tokens=100,completion_tokens=100)
        with patch.object(w.cap,'execute',return_value=[fixtures.item(n) for n in range(85)]),patch.object(w.llm,'complete_once',side_effect=provider):
            rid=w.new_run(self.con);w.execute_run(rid)
        result=w.result(self.con,rid)
        self.assertTrue(result['state']['r05_complete'],result['state']['errors'])
        self.assertEqual(len(result['state']['groups']),2)
        self.assertTrue(all(len(g['item_ids'])==85 for g in result['state']['groups']))
        self.assertTrue(all(len(i['group_ids'])==2 for i in result['items']))

    def test_invalid_ids_repair_then_ungrouped(self):
        self.activate();attempts=[]
        def provider(prompt,system,tokens):
            if system!=w.R05:return fixtures.model(prompt,system,tokens)
            attempts.append(json.loads(prompt))
            raw=dict(topics=[],ungrouped_item_ids=['bad' if len(attempts)==1 else 'github:1'])
            return json.dumps(raw),dict(prompt_tokens=1,completion_tokens=1)
        with patch.object(w.llm,'complete_once',side_effect=provider),patch.object(w.cap,'execute',return_value=[fixtures.item(1)]):
            rid=w.new_run(self.con);w.execute_run(rid)
        r=w.result(self.con,rid)
        self.assertEqual(len(attempts),2);self.assertIn('correction',attempts[1])
        self.assertEqual(r['items'][0]['r05_status'],'ungrouped');self.assertEqual(r['r05_pending'],0)

    def test_budget_failure_keeps_leaf_batches_and_resume(self):
        self.activate();real=w.call_model
        def call(con,owner,stage,system,payload,*args,**kwargs):
            if system==w.R05 and 'units' in payload: raise w.BudgetStop('test budget')
            return real(con,owner,stage,system,payload,*args,**kwargs)
        with patch.object(w,'call_model',side_effect=call),patch.object(w.llm,'complete_once',side_effect=fixtures.model),patch.object(w.cap,'execute',return_value=[fixtures.item(n) for n in range(45)]):
            rid=w.new_run(self.con);w.execute_run(rid)
        r=w.result(self.con,rid)
        self.assertFalse(r['state']['r05_complete']);self.assertEqual(len(r['state']['group_batches']),2)
        before=r['costs']['r04']['calls'];calls=[]
        def provider(prompt,system,tokens):
            calls.append(json.loads(prompt));return fixtures.model(prompt,system,tokens)
        with patch.object(w.llm,'complete_once',side_effect=provider):w.execute_run(rid)
        self.assertTrue(all('units' in p for p in calls))
        self.assertEqual(w.result(self.con,rid)['costs']['r04']['calls'],before)
        self.assertTrue(w.result(self.con,rid)['state']['r05_complete'])


def load_tests(loader, tests, pattern):
    suite=loader.loadTestsFromTestCase(TopicContract)
    suite.addTests(TopicWorkflow(n) for n in TopicWorkflow.__dict__ if n.startswith('test_'))
    return suite
