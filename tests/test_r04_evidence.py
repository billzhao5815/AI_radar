import json
import unittest
from pathlib import Path
from radar.analysis_rules import evidence_spans
from radar.workflow import validate_r04


class EvidenceTests(unittest.TestCase):
    def row(self, **kw):
        return dict(id='one',title='Forward Deployed Engineer',text='Build production-ready AI solutions. Work directly with clients.',**kw)

    def verdict(self, item, relation='direct', role='main', **kw):
        data=dict(item_id=item['id'],status='relevant',relation=relation,evidence_role=role,reason='测试关系',
                  target_evidence=[{'field':'title','quote':'Forward Deployed Engineer'}],
                  evidence=[{'field':'text','quote':'Build production ready AI solutions'},{'field':'text','quote':'Work directly with clients'}])
        data.update(kw)
        return validate_r04({'items':[data]},[item])[item['id']]

    def test_only_minimal_output_is_required(self):
        item=self.row()
        r=validate_r04({'items':[dict(item_id='one',status='relevant',reason='可能相关')]},[item])['one']
        self.assertEqual(r,dict(item_id='one',status='relevant',reason='可能相关'))

    def test_basic_contract_rejects_invalid_output(self):
        good=dict(item_id='one',status='relevant',reason='可能相关')
        for raw in (None, {}, {'items':[]}, {'items':[good,good]},
                    *({'items':[dict(good,**change)]} for change in
                      ({'item_id':'fake'}, {'item_id':[]}, {'status':'pending'}, {'reason':''}, {'reason':None}))):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_r04(raw,[self.row()])
        with self.assertRaises(ValueError):
            validate_r04({'items':[good,good]},[self.row(),dict(id='two')])

    def test_legacy_ellipsis_and_typographic_variants(self):
        item=self.row()
        spans=evidence_spans('Build production ready AI solutions ... Work directly with clients',item)
        self.assertEqual(len(spans),2)
        self.assertTrue(evidence_spans('“Build production-ready AI solutions”',item))

    def test_not_fuzzy_and_not_numeric_or_negative_rewrite(self):
        for original,quote in [('Costs 1.5 dollars','Costs 15 dollars'),('Profit -50 dollars','Profit 50 dollars'),
                               ('Do not deploy to production','Do deploy to production'),('Build systems for clients','Develop systems for clients')]:
            self.assertIsNone(evidence_spans(quote,dict(text=original)))
        self.assertIsNone(evidence_spans('Build production-ready AI solutions ... invented client result',self.row()))

    def test_hashtags_metadata_and_wrong_field_do_not_count(self):
        self.assertIsNone(evidence_spans('AI搞钱项目',dict(title='资产变化 #AI搞钱项目',query='AI搞钱项目')))
        self.assertIsNone(evidence_spans([dict(field='text',quote='Forward Deployed Engineer')],self.row()))

    def test_legacy_classifications_do_not_override_status(self):
        for relation,role in [('adjacent','main'),('mention','promotion'),('direct','promotion'),
                              ('direct','incidental'),('insufficient','missing'),('unrelated','main')]:
            self.assertEqual(self.verdict(self.row(),relation,role)['status'],'relevant')
        for status in ('relevant','uncertain','irrelevant'):
            self.assertEqual(self.verdict(self.row(),status=status)['status'],status)

    def test_missing_or_unmatched_quotes_do_not_gate_passage(self):
        for evidence in (None, [], ['Invented text that is not present']):
            r=self.verdict(self.row(),evidence=evidence,target_evidence=None)
            self.assertEqual(r['status'],'relevant')
            self.assertNotIn('evidence',r)
            self.assertNotIn('review_code',r)

    def test_actual_fde_quoted_ellipsis_recovers_without_rewriting_source(self):
        data=json.loads((Path(__file__).parents[1]/'docs/test-results/fde-run-10.json').read_text())
        item=next(i for i in data['result']['items'] if i['id']=='github:calmrocks/ai-engineer-notebooks')
        quote=item['r04_evidence']['evidence']
        spans=evidence_spans(quote,item)
        self.assertIsNotNone(spans)
        for span in spans:self.assertEqual(item[span['field']][span['start']:span['end']],span['quote'])
