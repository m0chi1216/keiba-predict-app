"""Dependency-free local HTTP server and background job runner."""
import argparse
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .service import ROOT, validate_request

STATIC = Path(__file__).parent / "static"
JOBS = {}
LOCK = threading.Lock()


def execute_job(job_id, request):
    folder = ROOT / "data/webapp/jobs" / job_id
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "result.json"
    log = folder / "worker.log"
    log.touch()
    with LOCK:
        JOBS[job_id].update(status="running", log=str(log))
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.run([sys.executable, "-m", "apps.race_predict.worker", str(output)],
                                     input=json.dumps(request), text=True, encoding="utf-8", cwd=ROOT,
                                     stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=1800,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if process.returncode or not output.exists():
            raise RuntimeError("処理を完了できませんでした。進捗ログを確認してください。")
        payload = json.loads(output.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        payload = {"status": "error", "error": "処理が30分を超えたため終了しました。"}
    except Exception as error:
        payload = {"status": "error", "error": str(error)}
    with LOCK:
        JOBS[job_id].update(payload)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def respond(self, status, body, content_type="application/json; charset=utf-8"):
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8") if isinstance(body, dict) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        local_host = urlparse("http://" + host)
        if local_host.hostname in {"localhost", "127.0.0.1"} and not local_host.username and not local_host.path:
            allowed.add(host)
        origins = {"http://" + item for item in allowed}
        public_origin = os.environ.get("APP_ORIGIN", "").rstrip("/")
        if public_origin:
            allowed.add(urlparse(public_origin).netloc)
            origins.add(public_origin)
        return host in allowed and (not origin or (origin in origins and urlparse(origin).netloc == host))

    def do_GET(self):
        if not self.local_request():
            return self.respond(403, {"error": "ローカルからアクセスしてください。"})
        path = urlparse(self.path).path
        if path == "/healthz":
            return self.respond(200, {"status": "ok"})
        if path.startswith("/api/jobs/"):
            with LOCK:
                job = dict(JOBS.get(path.rsplit("/", 1)[-1], {}))
            if not job:
                return self.respond(404, {"error": "ジョブが見つかりません。"})
            logfile = job.pop("log", None)
            if logfile:
                with Path(logfile).open("rb") as stream:
                    stream.seek(max(0, Path(logfile).stat().st_size - 12000))
                    job["logs"] = stream.read().decode("utf-8", errors="replace")
            return self.respond(200, job)
        assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                  "/style.css": ("style.css", "text/css")}
        if path not in assets:
            return self.respond(404, {"error": "ページが見つかりません。"})
        filename, content_type = assets[path]
        self.respond(200, (STATIC / filename).read_bytes(), content_type + "; charset=utf-8")

    def do_POST(self):
        if not self.local_request():
            return self.respond(403, {"error": "ローカルからアクセスしてください。"})
        if self.path != "/api/jobs":
            return self.respond(404, {"error": "APIが見つかりません。"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("リクエストサイズが不正です。")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("JSONオブジェクトを指定してください。")
            if request.get("action") == "predict":
                validate_request(request)
            elif request.get("action") == "races":
                if not isinstance(request.get("date"), str):
                    raise ValueError("開催日を指定してください。")
                datetime.strptime(request["date"], "%Y-%m-%d")
            else:
                raise ValueError("不明な操作です。")
        except (ValueError, TypeError) as error:
            return self.respond(400, {"error": str(error)})
        with LOCK:
            if any(job["status"] in {"queued", "running"} for job in JOBS.values()):
                return self.respond(409, {"error": "別の処理を実行中です。完了後に再度お試しください。"})
            job_id = uuid.uuid4().hex
            JOBS[job_id] = {"id": job_id, "status": "queued"}
        threading.Thread(target=execute_job, args=(job_id, request), daemon=True).start()
        self.respond(202, {"id": job_id})


def main():
    parser = argparse.ArgumentParser(description="競馬予想ローカルWebアプリ")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    from .assets import verify_assets
    verify_assets()
    origin = os.environ.get("APP_ORIGIN", "")
    if origin and (urlparse(origin).scheme != "https" or not urlparse(origin).hostname or urlparse(origin).path):
        parser.error("APP_ORIGIN must be an HTTPS origin without a path")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"競馬予想: http://127.0.0.1:{server.server_port} (Ctrl+Cで終了)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
