"""Local HTTP server: JSON API + static single-page UI. Binds to 127.0.0.1 only."""
from __future__ import annotations

import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import coach
from .meta_client import BudgetExceeded, ModelError, make_client
from .store import Store

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
MAX_BODY = 12 * 1024 * 1024


def load_sample(store: Store):
    data = json.loads((ROOT / "sample" / "profile.json").read_text(encoding="utf-8"))
    store.reset()
    for f in data["facts"]:
        store.add_fact(f["text"], f["source"], "confirmed", True, f["id"])
    for s in data["stories"]:
        store.save_story(dict(s))
    return {"facts": len(data["facts"]), "stories": len(data["stories"]),
            "jd": (ROOT / "sample" / "jd.txt").read_text(encoding="utf-8")}


def make_handler(store: Store, client):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write("[grounded] " + fmt % args + "\n")

        def _send(self, code: int, body, ctype="application/json"):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _json(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("Request too large (12 MB max).")
            return json.loads(self.rfile.read(n) or b"{}")

        def _state(self):
            plan = store.latest_plan()
            return {"mode": "live" if client.live else "offline", "model": client.model,
                    "budget": {"spent": client.ledger.spent(), "cap": client.ledger.cap, "calls": client.ledger.calls()},
                    "facts": store.facts(), "stories": store.stories(), "plan": plan,
                    "attempts": store.attempts(plan["id"]) if plan else []}

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/state":
                return self._send(200, self._state())
            if path.startswith("/api/brief/"):
                try:
                    md = coach.brief_markdown(store, int(path.rsplit("/", 1)[1]))
                except (KeyError, ValueError):
                    return self._send(404, {"error": "plan not found"})
                return self._send(200, md.encode(), "text/markdown; charset=utf-8")
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            file = (STATIC / name).resolve()
            if STATIC not in file.parents or not file.is_file():
                return self._send(404, {"error": "not found"})
            self._send(200, file.read_bytes(), TYPES.get(file.suffix, "application/octet-stream"))

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                # Same-origin guard: the UI is the only intended caller.
                origin = self.headers.get("Origin")
                if origin and not origin.startswith(("http://127.0.0.1", "http://localhost")):
                    return self._send(403, {"error": "cross-origin request refused"})
                body = self._json()
                if path == "/api/sample":
                    return self._send(200, load_sample(store))
                if path == "/api/reset":
                    store.reset()
                    return self._send(200, {"ok": True})
                if path == "/api/import":
                    return self._send(200, coach.import_profile(client, store, body.get("text", ""), body.get("pdf_base64", ""),
                                                                body.get("filename", "resume.pdf")))
                if path == "/api/fact":
                    if body.get("new"):
                        fid = store.add_fact(body["text"], body.get("source", "Added by me"), body.get("status", "confirmed"))
                        return self._send(200, {"id": fid})
                    store.set_fact(body["id"], body.get("status"), body.get("text"))
                    return self._send(200, {"ok": True})
                if path == "/api/story":
                    known = {f["id"] for f in store.facts()}
                    body["fact_ids"] = [f for f in body.get("fact_ids", []) if f in known]
                    return self._send(200, {"id": store.save_story(body)})
                if path == "/api/plan":
                    return self._send(200, coach.make_plan(client, store, body.get("company", ""), body.get("role", ""),
                                                           body.get("jd", ""), bool(body.get("research"))))
                if path == "/api/grade":
                    return self._send(200, coach.grade_answer(client, store, int(body["plan_id"]), body["question_id"],
                                                              body.get("answer", ""), body.get("seconds")))
                return self._send(404, {"error": "unknown endpoint"})
            except BudgetExceeded as e:
                self._send(402, {"error": str(e)})
            except ModelError as e:
                self._send(502, {"error": str(e)})
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                self._send(400, {"error": str(e)})
            except Exception as e:  # keep the server up; surface the failure
                traceback.print_exc()
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def main():
    client = make_client(ROOT)
    store = Store(ROOT / "data" / "grounded.sqlite3")
    port = int(os.environ.get("PORT", "8787"))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, client))
    mode = f"LIVE · {client.model} · cap ${client.ledger.cap:.2f} (spent ${client.ledger.spent():.4f})" if client.live else "OFFLINE stub (set META_API_KEY in .env for Muse Spark)"
    print(f"Grounded running at http://127.0.0.1:{port}  —  {mode}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
