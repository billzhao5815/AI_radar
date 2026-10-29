"""Local web workflow and static legacy dashboard, served by the existing CLI."""
from __future__ import annotations

import fcntl
import http.server
import json
import secrets
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from . import config, workflow as wf

ASSETS = Path(__file__).with_name('web_assets')


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None

    def busy(self): return self.process is not None and self.process.poll() is None

    def reconcile(self, con):
        if self.process is None or self.busy(): return
        for row in con.execute("SELECT run_id,state FROM wf_runs WHERE json_extract(state,'$.status')='running'").fetchall():
            state = json.loads(row['state']); state['status'] = 'interrupted'
            wf.save_state(con, row['run_id'], state)
        con.execute("UPDATE wf_drafts SET status='error',error='任务中断，请重新生成' WHERE status='generating'")
        con.execute("UPDATE wf_goals SET status='error',error='目标校验中断，请重试' WHERE status='generating'")
        con.commit()
        self.process = None

    def launch(self, mode, key):
        # Only IDs go on the command line, never prompts or secrets.
        self.process = subprocess.Popen([sys.executable, '-m', 'radar.web', mode, str(key)],
                                        cwd=str(config.ROOT), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_handler(jobs, token):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw): super().__init__(*a, directory=str(config.SITE_DIR), **kw)
        def log_message(self, *a): pass

        def reply(self, data, status=200):
            raw = wf.js(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers(); self.wfile.write(raw)

        def allowed_host(self):
            host = urlsplit('http://' + self.headers.get('Host', '')).hostname
            return host in {'localhost', '127.0.0.1', '::1', config.SERVE_HOST} - {'0.0.0.0', '::'}

        def do_GET(self):
            if not self.allowed_host(): return self.reply({'error': '不允许的访问地址'}, 403)
            path = urlsplit(self.path).path
            con = wf.connect()
            try:
                if path == '/api/state':
                    with jobs.lock: jobs.reconcile(con)
                    current = wf.active(con)
                    runs = [dict(r) for r in con.execute('SELECT r.id,r.day,r.status,w.config_id,c.payload FROM runs r JOIN wf_runs w ON w.run_id=r.id JOIN wf_configs c ON c.id=w.config_id ORDER BY r.id DESC LIMIT 100')]
                    for r in runs: r['name'] = json.loads(r.pop('payload'))['name']
                    return self.reply(dict(config=current, runs=runs, capabilities=wf.cap.menu(), names=wf.cap.NAMES,
                                           busy=jobs.busy(), token=token, llm_ready=bool(config.LLM_API_KEY)))
                if path == '/api/goal':
                    with jobs.lock: jobs.reconcile(con)
                    key = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                    row = con.execute('SELECT * FROM wf_goals WHERE id=?', (key,)).fetchone()
                    if not row: return self.reply({'error': '目标校验记录不存在'}, 404)
                    out = dict(row); out['payload'] = json.loads(out['payload']) if out['payload'] else None
                    out['costs'] = wf.costs(con, 'goal:' + key)
                    return self.reply(out)
                if path in ('/api/draft', '/api/draft-debug'):
                    with jobs.lock: jobs.reconcile(con)
                    key = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
                    row = con.execute('SELECT * FROM wf_drafts WHERE id=?', (key,)).fetchone()
                    if not row: return self.reply({'error': '预览不存在'}, 404)
                    if path == '/api/draft-debug':
                        return self.reply(dict(draft_id=key, status=row['status'], steps=wf.draft_steps(con, key)))
                    out = dict(row); out['payload'] = json.loads(out['payload']) if out['payload'] else None
                    out['costs'] = wf.costs(con, 'draft:' + key)
                    if out['payload'] and out['payload'].get('goal_id'):
                        out['goal_costs'] = wf.costs(con, 'goal:' + out['payload']['goal_id'])
                    return self.reply(out)
                if path == '/api/run':
                    rid = int(parse_qs(urlsplit(self.path).query).get('id', ['0'])[0])
                    return self.reply(wf.result(con, rid))
                if path == '/':
                    target = '/setup' if not wf.active(con) else '/index.html'
                    if target == '/index.html' and not (config.SITE_DIR / 'index.html').exists(): target = '/plan'
                    self.send_response(302); self.send_header('Location', target); self.end_headers(); return
                files = {'/setup': 'index.html', '/plan': 'index.html', '/collect': 'index.html',
                         '/workflow.js': 'app.js', '/workflow.css': 'style.css'}
                if path in files:
                    raw = (ASSETS / files[path]).read_bytes()
                    mime = 'text/html' if path in ('/setup', '/plan', '/collect') else 'text/javascript' if path.endswith('.js') else 'text/css'
                    self.send_response(200); self.send_header('Content-Type', mime + '; charset=utf-8')
                    self.send_header('Content-Length', str(len(raw)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
                    self.end_headers(); self.wfile.write(raw); return
            except (ValueError, TypeError) as exc: return self.reply({'error': wf.redact(str(exc))}, 400)
            finally: con.close()
            # Legacy static files remain under SITE_DIR; new database/config are never served.
            if path.startswith('/api/'): return self.reply({'error': '接口不存在'}, 404)
            return super().do_GET()

        def do_POST(self):
            if not self.allowed_host() or not secrets.compare_digest(self.headers.get('X-Radar-Token', ''), token):
                return self.reply({'error': '请刷新页面后重试'}, 403)
            origin = self.headers.get('Origin')
            if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                return self.reply({'error': '不允许跨站操作'}, 403)
            con = wf.connect()
            try:
                length = int(self.headers.get('Content-Length', 0))
                if not 0 < length <= 20000: raise ValueError('请求大小不合法')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict): raise ValueError('请求格式不正确')
                with jobs.lock:
                    jobs.reconcile(con)
                    if jobs.busy(): return self.reply({'error': '已有任务运行中，请等待完成'}, 409)
                    if self.path == '/api/understand':
                        if not config.LLM_API_KEY: raise ValueError('请先在 .env 配置 LLM_API_KEY，并重启服务')
                        goal = wf.clean_text(body.get('goal'), '监控目标')
                        key = uuid.uuid4().hex
                        con.execute("INSERT INTO wf_goals VALUES(?,'generating',?,?,NULL,NULL)", (key, time.time(), goal))
                        con.commit(); jobs.launch('goal', key)
                        return self.reply({'goal_id': key}, 202)
                    if self.path == '/api/generate':
                        if not config.LLM_API_KEY: raise ValueError('请先在原 .env 配置 LLM_API_KEY，并重启服务')
                        answers = wf.validate_answers(body)
                        goal_id = body.get('goal_id', '')
                        wf.checked_goal(con, goal_id, answers['goal'])
                        request = dict(answers=answers, goal_id=goal_id)
                        key = uuid.uuid4().hex
                        con.execute("INSERT INTO wf_drafts VALUES(?,'generating',?,?,NULL)", (key, time.time(), wf.js(request)))
                        con.commit(); jobs.launch('draft', key)
                        return self.reply({'draft_id': key}, 202)
                    if self.path == '/api/confirm':
                        return self.reply({'version': wf.confirm(con, body.get('draft_id', ''))})
                    if self.path == '/api/start':
                        if not config.LLM_API_KEY: raise ValueError('请先配置 LLM_API_KEY')
                        rid = wf.new_run(con); jobs.launch('run', rid)
                        return self.reply({'run_id': rid}, 202)
                    if self.path == '/api/resume':
                        rid = int(body['run_id']); state, _, _ = wf.load_run(con, rid)
                        if state['status'] in ('ok', 'running'): raise ValueError('该运行不需要恢复')
                        extra = body.get('extra_budget', 0)
                        if type(extra) not in (int, float) or not 0 <= extra <= 10: raise ValueError('追加额度必须在0至10元之间')
                        state['limit_cny'] = round(state['limit_cny'] + extra, 4)
                        state['candidate_limit'] += 160
                        state['prefer_target'] = False
                        state['status'] = 'running'
                        wf.save_state(con, rid, state); jobs.launch('run', rid)
                        return self.reply({'run_id': rid}, 202)
                    raise ValueError('接口不存在')
            except Exception as exc:
                con.rollback()
                return self.reply({'error': wf.redact(str(exc))}, 400)
            finally: con.close()
    return Handler


def serve(port=config.SERVE_PORT):
    config.ensure_dirs()
    # One local service owns scheduling and restart recovery for this database.
    lock = open(config.DATA_DIR / 'workflow.lock', 'a')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise RuntimeError('该数据目录已有 Web 服务运行') from None
    con = wf.connect()
    for row in con.execute("SELECT run_id,state FROM wf_runs WHERE json_extract(state,'$.status')='running'").fetchall():
        s = json.loads(row['state']); s['status'] = 'interrupted'; wf.save_state(con, row['run_id'], s)
    con.execute("UPDATE wf_drafts SET status='error',error='服务中断，请重新生成' WHERE status='generating'")
    con.execute("UPDATE wf_goals SET status='error',error='服务中断，请重新校验目标' WHERE status='generating'")
    con.commit(); con.close()
    jobs = Jobs()
    srv = http.server.ThreadingHTTPServer((config.SERVE_HOST, port), make_handler(jobs, secrets.token_urlsafe(32)))
    print(f'AI-radar http://{config.SERVE_HOST}:{srv.server_port}/setup', flush=True)
    try: srv.serve_forever()
    finally:
        if jobs.busy(): jobs.process.terminate(); jobs.process.wait(timeout=10)
        srv.server_close(); lock.close()


if __name__ == '__main__':
    mode, key = sys.argv[1:3]
    if mode == 'run': wf.execute_run(int(key))
    elif mode == 'goal': wf.understand_goal(key)
    elif mode == 'draft':
        con = wf.connect()
        answers = json.loads(con.execute('SELECT payload FROM wf_drafts WHERE id=?', (key,)).fetchone()[0])
        con.close(); wf.generate_draft(key, answers)
