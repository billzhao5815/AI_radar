"""Offline R03 retention and R04 queue/input regressions."""
import copy
import json
import unittest
from unittest.mock import patch

from test_workflow import WorkflowTest, item, plan, model
from radar import db, workflow as w
from radar.sources import shortvideo


class RetentionTests(WorkflowTest):
    def test_douyin_description_and_optional_metadata(self):
        rows = [dict(itemId='1', desc='简介'*250, description='fallback', tags=['AI'], topics=['视频']),
                dict(itemId='2', description='备用简介'), dict(itemId='3')]
        with patch.object(shortvideo.net, 'tikhub', return_value={'data': rows}) as api:
            result = shortvideo.douyin([('AI', 1)])
        api.assert_called_once()
        self.assertEqual([r['text'] for r in result], [('简介'*250)[:400], '备用简介', ''])
        self.assertEqual(result[0]['extra']['tags'], ['AI'])
        self.assertEqual(result[0]['extra']['topics'], ['视频'])
        self.assertNotIn('tags', result[2]['extra'])
        self.assertEqual(result[0]['query'], 'douyin:AI:低粉爆款')

    def test_duplicate_merge_updates_content_and_preserves_snapshots(self):
        self.activate(); rid = w.new_run(self.con)
        first = item(1); first.update(extra={'tags': ['a'], 'nested': {'known': 1}, 'low_fans_hot': True})
        with patch.object(db.time, 'time', return_value=1000):
            w.store_rows(self.con, rid, 't1', [first])
        old_hash = self.con.execute('SELECT hash FROM wf_items').fetchone()[0]
        second = dict(first, query='second', text='', author='', author_id=None,
                      metrics={'stars': 0, 'likes': 5}, extra={'tags': ['b'], 'nested': {'known': None, 'new': 2}, 'low_fans_hot': False})
        with patch.object(db.time, 'time', return_value=2000):
            w.store_rows(self.con, rid, 't2', [second])
        with patch.object(db.time, 'time', return_value=3000):
            w.store_rows(self.con, rid, 't2', [dict(second, metrics={'stars': None}, extra={})])
        rows = w.run_items(self.con, rid)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r['queries'], ['Agent', 'second'])
        self.assertEqual(r['query'], 'Agent')
        self.assertEqual(r['task_ids'], ['t1', 't2'])
        self.assertEqual((r['text'], r['author'], r['author_id']), (first['text'], 'a', 'a'))
        self.assertEqual(r['metrics'], {'stars': 0, 'likes': 5})
        self.assertEqual(r['extra']['tags'], ['a', 'b'])
        self.assertEqual(r['extra']['nested'], {'known': 1, 'new': 2})
        self.assertTrue(r['extra']['low_fans_hot'])
        self.assertNotEqual(old_hash, self.con.execute('SELECT hash FROM wf_items').fetchone()[0])
        stored = db.load_recent(self.con, 0)[0]
        for field in ('text', 'author', 'metrics', 'extra', 'queries'):
            self.assertEqual(stored[field], r[field])
        snaps = self.con.execute('SELECT metrics FROM snaps ORDER BY ts').fetchall()
        self.assertEqual([json.loads(s[0]) for s in snaps], [first['metrics'], second['metrics'], {'stars': None}])

    def test_all_candidates_budget_stop_resume_and_metadata_payload(self):
        self.activate(); rid = w.new_run(self.con)
        rows = [item(n, 'irrelevant' if n % 3 == 0 else 'unknown' if n % 3 == 1 else 'Agent') for n in range(181)]
        rows[0].update(queries=['Agent', 'second'], extra={'tags': ['AI'], 'made_by_ai': False})
        w.store_rows(self.con, rid, 't1', rows)
        state, p, _ = w.load_run(self.con, rid)
        captured = []
        def call(con, owner, stage, system, payload, tokens, limit):
            if stage == 'r04':
                if len(captured) == 2: raise w.BudgetStop()
                captured.append(payload)
            return json.loads(model(json.dumps(payload), system, tokens)[0])
        with patch.object(w, 'call_model', side_effect=call): w.analysis(self.con, rid, state, p)
        self.assertEqual(sum(i['r04_status'] == 'pending' for i in w.run_items(self.con, rid)), 141)
        done = {i['id'] for i in w.run_items(self.con, rid) if i['r04_status'] != 'pending'}
        resumed = []
        def resume(con, owner, stage, system, payload, tokens, limit):
            if stage == 'r04': resumed.extend(payload['items'])
            return json.loads(model(json.dumps(payload), system, tokens)[0])
        with patch.object(w, 'call_model', side_effect=resume): w.analysis(self.con, rid, state, p)
        self.assertEqual(len(resumed), 141)
        self.assertFalse(done & {r['item_id'] for r in resumed})
        self.assertFalse(any(i['r04_status'] == 'pending' for i in w.run_items(self.con, rid)))
        submitted = [i for batch in captured for i in batch['items']] + resumed
        self.assertEqual(len({i['item_id'] for i in submitted}), 181)
        self.assertEqual(next(i for i in submitted if i['item_id'] == rows[0]['id']), w.r04_item(rows[0]))
        passed = {i['id'] for i in w.run_items(self.con, rid) if i['r04_status'] in ('relevant', 'uncertain')}
        self.assertEqual({iid for g in state['groups'] for iid in g['item_ids']}, passed)

    def test_legacy_candidate_limit_does_not_truncate_single_pass(self):
        self.activate(); rid = w.new_run(self.con)
        w.store_rows(self.con, rid, 't1', [item(n, 'irrelevant') for n in range(181)])
        state, p, _ = w.load_run(self.con, rid)
        self.assertEqual(state['candidate_limit'], 160)
        batches = []
        def call(con, owner, stage, system, payload, tokens, limit):
            self.assertEqual(stage, 'r04')
            batches.append(len(payload['items']))
            return json.loads(model(json.dumps(payload), system, tokens)[0])
        with patch.object(w, 'call_model', side_effect=call): w.analysis(self.con, rid, state, p)
        self.assertEqual(batches, [20] * 9 + [1])
        self.assertEqual({i['r04_status'] for i in w.run_items(self.con, rid)}, {'irrelevant'})

    def test_cache_covers_actual_input(self):
        original = item(1); original['extra'] = {'tags': ['a'], 'made_by_ai': False}
        key = w.relevance_key(plan(), original)
        changes = {'id': 'new', 'title': 'new', 'text': 'new', 'source': 'x', 'author': 'new',
                   'queries': ['new'], 'extra': {'tags': ['b'], 'made_by_ai': False}}
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertNotEqual(key, w.relevance_key(plan(), dict(original, **{field: value})))
        changed = copy.deepcopy(original); changed['extra']['made_by_ai'] = True
        self.assertNotEqual(key, w.relevance_key(plan(), changed))
        self.assertEqual(key, w.relevance_key(plan(), dict(original, metrics={'stars': 999})))

    def test_candidate_mix_fairness_missing_metrics_and_dedup(self):
        now = 1_000_000
        rows = []
        for source in ('douyin', 'bili'):
            for query in ('a', 'b'):
                for n in range(12):
                    row = item(f'{query}{n:02}', source=source)
                    row.update(kind='video', query=query, published_at=now-400000,
                               metrics={'likes': n*100, 'views': None if source == 'douyin' else n*100, 'followers': 1000})
                    if n == 0: row.update(metrics={}, published_at=now-10)
                    if n == 1: row['extra'] = {'low_fans_hot': True}
                    rows.append(row)
        # Shared result belongs to both query buckets, but is returned only once.
        with patch.object(w.time, 'time', return_value=now):
            result = w.candidates(rows, plan())
            duplicated = w.candidates(rows + [dict(rows[0], query='b')], plan())
        self.assertEqual(len(duplicated), 48)
        self.assertEqual(len({r['id'] for r in duplicated}), 48)
        self.assertEqual(len(result), 48)
        self.assertEqual(len({r['id'] for r in result}), 48)
        self.assertEqual({(r['source'], r['query']) for r in result[:4]},
                         {('douyin', 'a'), ('douyin', 'b'), ('bili', 'a'), ('bili', 'b')})
        for source in ('douyin', 'bili'):
            for query in ('a', 'b'):
                group = [r for r in result if r['source'] == source and r['query'] == query]
                self.assertTrue(all(r['signals']['heat'] >= 80 or r['extra'].get('low_fans_hot') for r in group[:2]))
                self.assertEqual(group[2]['id'], f'{source}:{query}00')
                self.assertLess(group[3]['signals']['heat'], 80)
        self.assertEqual({r['id'] for r in result if not r['metrics']}, {r['id'] for r in rows if not r['metrics']})


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(RetentionTests(name) for name in RetentionTests.__dict__ if name.startswith('test_'))
