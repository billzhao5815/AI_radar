"""Regression fixtures from paid run #9. No external model or collection calls."""
import json
from pathlib import Path
from unittest.mock import patch

import test_workflow as fixtures
from test_workflow import plan, item, model
from radar import workflow as w, capabilities as cap
from radar.analysis_rules import guard_groups
from radar.sources import github, xtw


class AnalysisRegressions(fixtures.WorkflowTest):
    # Inherits the temporary SQLite setup; inherited acceptance tests also exercise v2.
    def fixture(self):
        return json.loads((Path(__file__).parents[1]/'docs/test-results/ai-money-run-9.json').read_text())['result']

    def test_actual_22_item_broad_merge_is_split_without_loss(self):
        r=self.fixture();g=r['state']['group_batches'][0]
        self.assertEqual(len(g['item_ids']),22)
        out,warnings=guard_groups([g],r['items'])
        self.assertEqual(len(out),22);self.assertTrue(warnings)
        self.assertEqual({i for x in out for i in x['item_ids']},set(g['item_ids']))

    def test_valid_same_object_merge_and_invalid_evidence(self):
        rows=[item(1,'AcmePay launch provides AI usage billing',source='x'),item(2,'AcmePay launch adds payment tools',source='youtube')]
        g=dict(title='AcmePay发布',category='支付工具',summary='两条报道',item_ids=[x['id'] for x in rows],
               merge_anchor='AcmePay',evidence={i['id']:i['text'] for i in rows})
        out,warnings=guard_groups([g],rows);self.assertEqual(len(out),1);self.assertFalse(warnings)
        g['evidence'][rows[1]['id']]='made up AcmePay claim'
        self.assertEqual(len(guard_groups([g],rows)[0]),2)

    def test_r04_legacy_quotes_do_not_gate_passage(self):
        row=next(i for i in self.fixture()['items'] if i['id']=='douyin:7698755273242853370')
        for quote in ('#AI搞钱','AI接单实现商业收入'):
            raw={'items':[dict(item_id=row['id'],status='relevant',relation='direct',evidence_role='main',reason='标签命中',evidence=quote,target_evidence=quote)]}
            self.assertEqual(w.validate_r04(raw,[row])[row['id']]['status'],'relevant')
        valid=item(1,'AcmePay is an AI billing product with paying customers')
        raw={'items':[dict(item_id=valid['id'],status='relevant',relation='direct',evidence_role='main',reason='AI产品商业应用',
                           evidence='billing product with paying customers',target_evidence='AcmePay is an AI billing product')]}
        self.assertEqual(w.validate_r04(raw,[valid])[valid['id']]['status'],'relevant')

    def test_real_candidate_pool_does_not_crowd_out_repositories(self):
        r=self.fixture();p=plan();p['terms']=['AI搞钱','make money with AI']
        selected=w.candidates(r['items'],p)[:160]
        # Channel rotation guarantees early access; the full queue now has no 160-item cap.
        self.assertIn('github', {i['source'] for i in selected[:10]})
        self.assertEqual({i['id'] for i in w.candidates(r['items'],p)}, {i['id'] for i in r['items']})
        self.assertLess(sum(i['source']=='douyin_hot' for i in selected),40)
        self.assertEqual(len(w.candidates(r['items'],p)),len(r['items']))

    def test_time_constraints_are_sent_even_without_placeholders(self):
        with patch.object(xtw.net,'tikhub',return_value={'timeline':[]}) as api:
            cap.execute(dict(capability_id='x',query='make money with AI',options={'days':7},result_limit=20))
            self.assertIn('since:',api.call_args.args[1]['keyword'])
        with patch.object(github.net,'get_json',return_value={'items':[]}) as api,patch.object(github,'_headers',return_value={}),patch.object(github.time,'sleep'):
            cap.execute(dict(capability_id='github_search',query='AI monetization',options={'days':30},result_limit=20))
            self.assertIn('pushed:>',api.call_args.kwargs['params']['q'])
            cap.execute(dict(capability_id='github_search',query='AI created:>2000-01-01',options={'days':7,'time_field':'created'},result_limit=20))
            q=api.call_args.kwargs['params']['q'];self.assertEqual(q.count('created:'),1);self.assertNotIn('2000',q)

    def test_uniform_merge_contract_and_one_schema_repair(self):
        self.activate();seen=[]
        def provider(prompt,system,max_tokens):
            payload=json.loads(prompt)
            if system==w.R05 and 'groups' in payload:
                seen.append(payload)
                if 'correction' not in payload:
                    return json.dumps({'groups':[{'title':'oops','category':'x','summary':'x','member_groups':['b1']}]}),dict(prompt_tokens=50,completion_tokens=50)
            return model(prompt,system,max_tokens)
        with patch.object(cap,'execute',return_value=[item(n) for n in range(45)]),patch.object(w.llm,'complete_once',side_effect=provider):
            rid=w.new_run(self.con);w.execute_run(rid)
        r=w.result(self.con,rid)
        self.assertEqual(r['state']['status'],'ok');self.assertEqual(len(seen),2)
        self.assertTrue(all('item_ids' in g for g in seen[0]['groups']))
        self.assertEqual(len({iid for g in r['state']['groups'] for iid in g['item_ids']}),45)

    def test_failed_merge_shows_saved_groups_and_resume_uses_batch_cache(self):
        self.activate()
        def provider(prompt,system,max_tokens):
            if system==w.R05 and 'groups' in json.loads(prompt):return '{"groups":[]}',dict(prompt_tokens=50,completion_tokens=50)
            return model(prompt,system,max_tokens)
        with patch.object(cap,'execute',return_value=[item(n) for n in range(45)]),patch.object(w.llm,'complete_once',side_effect=provider):
            rid=w.new_run(self.con);w.execute_run(rid)
        r=w.result(self.con,rid)
        self.assertFalse(r['state']['r05_complete']);self.assertEqual(len(r['state']['groups']),45)
        self.assertEqual(r['state']['status'],'partial')
        called=[]
        def recover(prompt,system,max_tokens):called.append(system);return model(prompt,system,max_tokens)
        with patch.object(cap,'execute') as fetch,patch.object(w.llm,'complete_once',side_effect=recover):w.execute_run(rid);fetch.assert_not_called()
        self.assertEqual(called,[w.R05]);self.assertTrue(w.result(self.con,rid)['state']['r05_complete'])

    def test_old_run_r04_status_is_not_reused_under_new_rules(self):
        self.activate();rid,r=self.run_with([item(1)])
        s,_,_=w.load_run(self.con,rid);s.pop('analysis_revision');w.save_state(self.con,rid,s)
        self.con.execute('DELETE FROM wf_cache');self.con.commit()
        with patch.object(cap,'execute') as fetch,patch.object(w.llm,'complete_once',side_effect=model) as call:w.execute_run(rid);fetch.assert_not_called()
        self.assertEqual(call.call_count,2)


def load_tests(loader, tests, pattern):
    import unittest
    return unittest.TestSuite(AnalysisRegressions(name) for name in AnalysisRegressions.__dict__ if name.startswith("test_"))
