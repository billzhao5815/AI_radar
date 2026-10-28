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

    def test_fragments_are_original_locatable_spans(self):
        item=self.row();r=self.verdict(item)
        self.assertEqual(r['status'],'relevant')
        self.assertEqual(len(r['evidence']),2)
        for span in r['evidence']:
            self.assertEqual(item[span['field']][span['start']:span['end']],span['quote'])

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

    def test_adjacent_and_promotion_never_enter_r05_even_with_real_quotes(self):
        for relation,role in [('adjacent','main'),('mention','promotion'),('direct','promotion'),('direct','incidental'),('insufficient','missing')]:
            self.assertEqual(self.verdict(self.row(),relation,role)['status'],'uncertain')
        self.assertEqual(self.verdict(self.row(),'unrelated')['status'],'irrelevant')

    def test_evidence_failure_is_distinct_from_content_uncertainty(self):
        r=self.verdict(self.row(),evidence=['Invented text that is not present'])
        self.assertEqual(r['review_code'],'evidence_unmatched')
        self.assertEqual(self.verdict(self.row(),'insufficient')['review_code'],'insufficient')

    def test_actual_fde_quoted_ellipsis_recovers_without_rewriting_source(self):
        data=json.loads((Path(__file__).parents[1]/'docs/test-results/fde-run-10.json').read_text())
        item=next(i for i in data['result']['items'] if i['id']=='github:calmrocks/ai-engineer-notebooks')
        quote=item['r04_evidence']['evidence']
        spans=evidence_spans(quote,item)
        self.assertIsNotNone(spans)
        for span in spans:self.assertEqual(item[span['field']][span['start']:span['end']],span['quote'])
