"""Local browser interface for the autonomous development agent.

The service binds to loopback by default. Do not expose it to a network:
the agent can write files and execute generated development commands.
"""
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)

from agent.agent import run_agent  # noqa: E402
from agent.planner import create_plan  # noqa: E402
from agent.reviewer import review_project  # noqa: E402
from main import collect_project_files, collect_test_results  # noqa: E402

HOST = os.environ.get("AGENT_WEB_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", os.environ.get("AGENT_WEB_PORT", "8765")))
MAX_REQUEST_BYTES = 8_000
MAX_JOBS = 100
JOB_RETENTION_SECONDS = 60 * 60
TOKEN = os.environ.get("AGENT_WEB_TOKEN", "")

_jobs = {}
_jobs_lock = threading.Lock()
_job_queue = deque()
_queue_condition = threading.Condition()


class JobQueueFull(Exception):
    pass


def _clean_old_jobs():
    cutoff = time.time() - JOB_RETENTION_SECONDS
    with _jobs_lock:
        expired = [job_id for job_id, job in _jobs.items()
                   if job["created_at"] < cutoff and job["status"] in {"completed", "failed"}]
        for job_id in expired:
            _jobs.pop(job_id, None)


def _run_job(job_id, request):
    with _jobs_lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["updated_at"] = time.time()
    try:
        plan = create_plan(request)
        review = None
        agent_result = None
        for attempt in range(1, 4):
            developer_request = request if review is None else (
                f"ORIGINAL USER REQUEST:\n{request}\n\n"
                f"REVIEWER FEEDBACK FROM PREVIOUS ATTEMPT:\n"
                f"{json.dumps(review, indent=2)}\n\n"
                "Fix the reported issues, inspect relevant files, and rerun tests."
            )
            agent_result = run_agent(developer_request, plan)
            review = review_project(
                user_request=request,
                development_plan=plan,
                project_files=collect_project_files(plan),
                test_results=collect_test_results(agent_result),
            )
            if review.get("status") == "PASS":
                break
        result = {"plan": plan, "agent": agent_result, "review": review}
        with _jobs_lock:
            _jobs[job_id].update(status="completed", result=result, updated_at=time.time())
    except Exception as error:
        with _jobs_lock:
            _jobs[job_id].update(status="failed", error=f"{type(error).__name__}: {error}", updated_at=time.time())


def _worker():
    while True:
        with _queue_condition:
            while not _job_queue:
                _queue_condition.wait()
            job_id, request = _job_queue.popleft()
        _run_job(job_id, request)
        _clean_old_jobs()


threading.Thread(target=_worker, name="agent-job-worker", daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    server_version = "AutonomousAgent/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send(self, status, data, content_type="application/json; charset=utf-8"):
        if isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        supplied = self.headers.get("Authorization", "")
        if not TOKEN:
            self._send(503, {"error": "Server is not configured. Set AGENT_WEB_TOKEN and restart."})
            return False
        if not hmac.compare_digest(supplied, f"Bearer {TOKEN}"):
            self._send(401, {"error": "Enter the access token configured by the server owner."})
            return False
        return True

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
            return
        if self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
            return
        if not self._authorized():
            return
        if self.path == "/api/jobs":
            with _jobs_lock:
                jobs = [{key: value for key, value in job.items() if key not in {"result", "error"}}
                        for job in _jobs.values()]
            self._send(200, {"jobs": sorted(jobs, key=lambda item: item["created_at"], reverse=True)})
            return
        if self.path.startswith("/api/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            with _jobs_lock:
                job = _jobs.get(job_id)
                snapshot = dict(job) if job else None
            if snapshot is None:
                self._send(404, {"error": "Job not found."})
            else:
                snapshot.pop("created_at", None)
                snapshot.pop("updated_at", None)
                self._send(200, snapshot)
            return
        if self.path == "/api/files":
            from tools.files import list_files
            self._send(200, {"files": list_files()})
            return
        self._send(404, {"error": "Not found."})

    def do_POST(self):
        if not self._authorized():
            return
        if self.path != "/api/jobs":
            self._send(404, {"error": "Not found."})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > MAX_REQUEST_BYTES:
                self._send(413, {"error": "Request must be between 1 and 8000 bytes."})
                return
            body = json.loads(self.rfile.read(size))
            request = body.get("request", "")
            if not isinstance(request, str) or not request.strip() or len(request) > 5_000:
                self._send(400, {"error": "Enter a request of 1 to 5000 characters."})
                return
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "Invalid request body."})
            return
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "request": request.strip(), "status": "queued", "created_at": time.time(), "updated_at": time.time()}
        with _jobs_lock:
            if len(_jobs) >= MAX_JOBS:
                self._send(503, {"error": "Job capacity reached. Restart the service after reviewing queued work."})
                return
            _jobs[job_id] = job
        with _queue_condition:
            _job_queue.append((job_id, request.strip()))
            _queue_condition.notify()
        self._send(202, {"id": job_id, "status": "queued"})


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Autonomous Dev Agent</title>
<style>
:root{color-scheme:light;--ink:#182321;--muted:#66736e;--line:#dce4df;--green:#176b50;--bg:#f5f7f4}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,Segoe UI,sans-serif}.wrap{max-width:880px;margin:48px auto;padding:0 22px}header{margin-bottom:28px}h1{font-size:30px;letter-spacing:-.03em;margin:0}header p{color:var(--muted);margin:6px 0}.card{background:white;border:1px solid var(--line);border-radius:14px;padding:22px;margin:16px 0;box-shadow:0 4px 16px #12221a08}label{font-weight:650;display:block;margin-bottom:8px}input,textarea,button{font:inherit}input,textarea{width:100%;border:1px solid var(--line);border-radius:9px;padding:11px 12px;background:white}textarea{height:130px;resize:vertical}button{border:0;border-radius:9px;padding:11px 17px;color:white;background:var(--green);font-weight:650;cursor:pointer;margin-top:12px}button:disabled{opacity:.55;cursor:wait}.hint,.status{color:var(--muted);font-size:14px}.job{border-top:1px solid var(--line);padding:14px 0}.job:first-child{border-top:0}.job b{color:var(--green)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8f6;padding:12px;border-radius:8px;max-height:360px;overflow:auto;font-size:13px}.error{color:#a1322c}.hidden{display:none}
</style></head><body><main class="wrap"><header><h1>Autonomous Dev Agent</h1><p>Describe a software change. The agent plans, implements, and reviews it in the project workspace.</p></header>
<section class="card"><label for="token">Access token</label><input id="token" type="password" autocomplete="current-password" placeholder="Token supplied by the server owner"><p class="hint">This service listens on this computer only.</p></section>
<section class="card"><label for="request">What should the agent build?</label><textarea id="request" maxlength="5000" placeholder="Describe the change and how to verify it…"></textarea><button id="submit">Start request</button><p id="message" class="status"></p></section>
<section class="card"><h2>Recent requests</h2><div id="jobs" class="status">Enter your token to load requests.</div></section></main>
<script>
const token=document.querySelector('#token'), requestBox=document.querySelector('#request'), submit=document.querySelector('#submit'), jobs=document.querySelector('#jobs'), message=document.querySelector('#message');
token.value=sessionStorage.getItem('agentToken')||'';token.addEventListener('change',()=>{sessionStorage.setItem('agentToken',token.value);refresh()});
async function api(path,options={}){const r=await fetch(path,{...options,headers:{'Authorization':'Bearer '+token.value,'Content-Type':'application/json',...(options.headers||{})}});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
function esc(x){const e=document.createElement('span');e.textContent=x??'';return e.innerHTML}
async function refresh(){if(!token.value){jobs.textContent='Enter your access token to view requests.';return}try{const data=await api('/api/jobs');jobs.innerHTML=data.jobs.length?data.jobs.map(j=>`<div class="job"><b>${esc(j.status.toUpperCase())}</b> · ${new Date(j.created_at*1000).toLocaleString()}<div>${esc(j.request)}</div><div class="hint">${esc(j.id)}</div></div>`).join(''):'No requests yet.'}catch(e){jobs.innerHTML='<span class="error">'+esc(e.message)+'</span>'}}
submit.addEventListener('click',async()=>{submit.disabled=true;message.textContent='Submitting…';try{await api('/api/jobs',{method:'POST',body:JSON.stringify({request:requestBox.value})});requestBox.value='';message.textContent='Request queued.';await refresh()}catch(e){message.textContent=e.message;message.className='status error'}finally{submit.disabled=false}});
async function poll(){await refresh();try{const data=await api('/api/jobs');const active=data.jobs.filter(j=>j.status==='queued'||j.status==='running');for(const j of active){const detail=await api('/api/jobs/'+j.id);if(detail.status==='completed'||detail.status==='failed'){const box=document.createElement('pre');box.textContent=JSON.stringify(detail.result||{error:detail.error},null,2);jobs.appendChild(box)}}}catch{}setTimeout(poll,4000)}poll();
</script></body></html>'''


def main():
    if not TOKEN or len(TOKEN) < 24:
        raise SystemExit("Set AGENT_WEB_TOKEN to a random value of at least 24 characters before starting.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Agent UI: http://{HOST}:{PORT}")
    print(f"Listening on {HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping agent service…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
