"""Explicitly paid, isolated live acceptance run. Never used by offline tests."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ['RADAR_DATA_DIR'] = '/tmp/ai-radar-r05-real-20261029'
from radar import workflow as w, capabilities as cap, config, net

OUT = Path(__file__).resolve().parent

def dump(name, data):
    (OUT/name).write_text(json.dumps(data, ensure_ascii=False, indent=2))

def log(event, **data):
    print(json.dumps(dict(event=event, **data), ensure_ascii=False), flush=True)

con=w.connect()
if not con.execute('SELECT 1 FROM wf_configs').fetchone():
    answers=dict(goal='AI短剧', detail={'include': [], 'exclude': []}, sources=['bili','douyin','xhs'])
    goal=dict(name='AI短剧真实验收', monitoring_goal='AI短剧', monitoring_scope={'include': [],'exclude': []}, terms=['AI短剧'])
    plan=w.build_plan(answers,goal,goal['monitoring_scope'],{s:['AI短剧'] for s in answers['sources']})
    con.execute('INSERT INTO wf_configs(created,active,payload) VALUES(?,1,?)',(time.time(),w.js(plan)))
    con.commit()
    rid=w.new_run(con)
else:
    rid=con.execute('SELECT MAX(run_id) FROM wf_runs').fetchone()[0]
state, plan, _=w.load_run(con,rid)
log('start',run_id=rid,phase=sys.argv[1],model=config.LLM_MAIN,task_count=len(plan['tasks']),analysis_limit=state['limit_cny'])

if sys.argv[1]=='collect':
    for task in plan['tasks']:
        if state['tasks'].get(task['id'],{}).get('status') in ('ok','empty'):continue
        budget=cap.estimate([task])
        if state['collection_calls']+budget['max_calls_with_retries']>config.TIKHUB_MAX_CALLS or state['collection_usd']+budget['max_usd_est']>config.TIKHUB_MAX_USD:
            log('collection_budget_stop');break
        state['collection_calls']+=budget['max_calls_with_retries'];state['collection_usd']+=budget['max_usd_est']
        w.save_state(con,rid,state)
        warnings=[];token=net.collection_errors.set(warnings);before=net.ledger.snapshot()
        try:
            rows=cap.execute(task)
            w.store_rows(con,rid,task['id'],rows)
            state['tasks'][task['id']]=dict(status='partial' if warnings and rows else 'error' if warnings else 'ok' if rows else 'empty',count=len(rows),errors=[w.redact(x) for x in warnings])
        except Exception as exc:
            state['tasks'][task['id']]=dict(status='error',count=0,error=w.redact(str(exc)))
        finally:net.collection_errors.reset(token)
        state['tasks'][task['id']]['cost']=net.ledger.summary(before)
        w.save_state(con,rid,state)
        log('collected',task=task['id'],source=task['source'],result=state['tasks'][task['id']],unique_count=len(w.run_items(con,rid)))
    dump('collected.json',dict(plan=plan,state=state,items=w.run_items(con,rid)))
    log('collection_done',unique_count=len(w.run_items(con,rid)),ledger=net.ledger.summary())
elif sys.argv[1]=='analyze':
    original=w.call_model
    def logged(con,owner,stage,system,payload,*args,**kwargs):
        log('model_start',stage=stage,mode='merge' if 'units' in payload else 'discovery' if stage=='r05' else 'relevance',inputs=len(payload.get('items',payload.get('units',[]))))
        start=time.monotonic()
        try:return original(con,owner,stage,system,payload,*args,**kwargs)
        finally:log('model_end',stage=stage,seconds=round(time.monotonic()-start,1),costs=w.costs(con,owner))
    w.call_model=logged
    con.close()
    w.execute_run(rid)
    con=w.connect()
    result=w.result(con,rid)
    dump('result.json',result)
    dump('calls.json',[dict(r) for r in con.execute('SELECT stage,created,reserved,cost,input_tokens,output_tokens,status FROM wf_calls ORDER BY id')])
    log('done',state=result['state']['status'],r04=result['counts'],topics=len(result['state']['groups']),ungrouped=len(result['state'].get('ungrouped_item_ids',[])),r05_complete=result['state'].get('r05_complete'),costs=result['costs'],errors=result['state']['errors'])
con.close()
