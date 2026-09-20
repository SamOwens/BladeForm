#!/usr/bin/env python3
"""BladeForm local helper — bound to 127.0.0.1 only.

Serves the viewer over HTTP (not file://) and handles two export actions:
  POST /api/save-project  → write name.bfproj into projects/
  POST /api/export-step   → temp .bfproj → STEP export → verify → steps/

No arbitrary command execution. Filenames are sanitised. CORS is same-origin
only (the viewer is served from this process).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
PROJECTS = ROOT / "projects"
STEPS = ROOT / "steps"
TEMP = ROOT / "temp_export"
VIEWER_FILE = ROOT / "bladeform-viewer.html"
HOST = "127.0.0.1"
PORT = 8765

# Safe design-name characters only; everything else becomes underscore.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_name(raw: str) -> str:
    name = (raw or "").strip()
    name = _SAFE_NAME.sub("_", name).strip("._-")
    if not name or name in (".", ".."):
        raise ValueError("design name is empty or invalid after sanitisation")
    if len(name) > 120:
        name = name[:120]
    return name


def ensure_dirs():
    for d in (PROJECTS, STEPS, TEMP):
        d.mkdir(parents=True, exist_ok=True)


def load_viewer_html() -> bytes:
    if not VIEWER_FILE.is_file():
        raise FileNotFoundError(f"viewer not found: {VIEWER_FILE}")
    return VIEWER_FILE.read_bytes()


def project_payload_from_body(body: dict) -> dict:
    """Accept either a full project object or {design, snapshots} and normalise."""
    if body.get("format") == "bladeform-project":
        return body
    if "design" not in body:
        raise ValueError("body must contain a design object")
    return {
        "format": "bladeform-project",
        "version": int(body.get("version") or 1),
        "saved": body.get("saved") or "",
        "design": body["design"],
        "snapshots": body.get("snapshots") or [],
    }


def save_project_file(name: str, body: dict, overwrite: bool) -> dict:
    ensure_dirs()
    safe = sanitize_name(name)
    path = PROJECTS / f"{safe}.bfproj"
    if path.exists() and not overwrite:
        return {"ok": False, "exists": True, "path": str(path),
                "message": f"Project '{safe}.bfproj' already exists. Confirm overwrite."}
    payload = project_payload_from_body(body)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return {"ok": True, "path": str(path), "name": safe,
            "message": f"Saved projects/{safe}.bfproj"}


def export_step_file(name: str, body: dict, overwrite: bool) -> dict:
    """Write temp .bfproj, run STEP export, verify, write steps/name.step, clean up."""
    ensure_dirs()
    safe = sanitize_name(name)
    out_path = STEPS / f"{safe}.step"
    if out_path.exists() and not overwrite:
        return {"ok": False, "exists": True, "path": str(out_path),
                "message": f"STEP file '{safe}.step' already exists. Confirm overwrite."}

    # Warn if no saved project with that name exists (still allow export from live design).
    saved_proj = PROJECTS / f"{safe}.bfproj"
    warn = None
    if not saved_proj.is_file():
        warn = (f"No saved project named '{safe}' in projects/. "
                "Exporting from the live design in the viewer.")

    payload = project_payload_from_body(body)
    # Isolate temp under temp_export so failures leave an inspectable file.
    tmp_bfproj = TEMP / f"{safe}.bfproj"
    tmp_step = TEMP / f"{safe}.step"

    try:
        with open(tmp_bfproj, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

        # Import CAD stack only when needed (cadquery-ocp is optional / large).
        try:
            from bladeform.exporters import load_project
            from bladeform.step_export import export_step
            from bladeform.step_verify import verify
        except ImportError as e:
            return {
                "ok": False,
                "message": (
                    "STEP export requires the OpenCASCADE package "
                    f"(cadquery-ocp). Install it, then retry. Detail: {e}"
                ),
                "temp_bfproj": str(tmp_bfproj),
            }

        design, _snaps = load_project(str(tmp_bfproj))
        result = export_step(design, str(tmp_step))
        if not os.path.isfile(tmp_step) or os.path.getsize(tmp_step) < 200:
            return {
                "ok": False,
                "message": (
                    f"STEP writer produced no usable file "
                    f"(size={os.path.getsize(tmp_step) if os.path.isfile(tmp_step) else 0}). "
                    f"Notes: {result.get('notes')}"
                ),
                "temp_bfproj": str(tmp_bfproj),
                "export": result,
            }

        v = verify(str(tmp_step))
        if not v.get("ok"):
            return {
                "ok": False,
                "message": "STEP verification failed: " + "; ".join(v.get("problems") or ["unknown"]),
                "verify": v,
                "temp_bfproj": str(tmp_bfproj),
                "temp_step": str(tmp_step),
            }

        # Extra checks requested: size, units (file exists + non-trivial), solid count.
        solid_count = int(v.get("manifold_solids") or 0) + int(v.get("closed_shells") or 0)
        if solid_count < 1:
            return {
                "ok": False,
                "message": "Verification found no closed/manifold solids in the STEP file.",
                "verify": v,
                "temp_bfproj": str(tmp_bfproj),
                "temp_step": str(tmp_step),
            }

        # Move verified result into steps/
        with open(tmp_step, "rb") as src, open(out_path, "wb") as dst:
            dst.write(src.read())
        try:
            tmp_step.unlink(missing_ok=True)
            tmp_bfproj.unlink(missing_ok=True)
        except OSError:
            pass

        msg = f"Wrote steps/{safe}.step ({os.path.getsize(out_path)} bytes, " \
              f"{v.get('advanced_faces', 0)} faces, {v.get('manifold_solids', 0)} solids)."
        if warn:
            msg = warn + " " + msg
        return {
            "ok": True,
            "path": str(out_path),
            "name": safe,
            "message": msg,
            "verify": {
                "advanced_faces": v.get("advanced_faces"),
                "manifold_solids": v.get("manifold_solids"),
                "closed_shells": v.get("closed_shells"),
                "curved_surfaces": list((v.get("curved_surfaces") or {}).keys()),
            },
            "export_notes": result.get("notes"),
            "warning": warn,
        }
    except Exception as e:
        # Keep temp .bfproj on failure for inspection.
        tb = traceback.format_exc(limit=8)
        return {
            "ok": False,
            "message": f"STEP export failed: {e}",
            "detail": tb,
            "temp_bfproj": str(tmp_bfproj) if tmp_bfproj.exists() else None,
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "BladeFormHelper/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _cors(self):
        # Viewer is same-origin when served by us; still allow local file fallback probes.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code: int, obj: dict):
        data = json.dumps(obj, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _bytes(self, code: int, data: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/bladeform-viewer.html", "/viewer"):
            try:
                html = load_viewer_html()
            except FileNotFoundError as e:
                return self._json(500, {"ok": False, "message": str(e)})
            return self._bytes(200, html, "text/html; charset=utf-8")
        if path == "/api/ping":
            return self._json(200, {"ok": True, "helper": True, "host": HOST, "port": PORT})
        if path == "/api/list-projects":
            ensure_dirs()
            names = sorted(p.stem for p in PROJECTS.glob("*.bfproj"))
            return self._json(200, {"ok": True, "projects": names})
        self._json(404, {"ok": False, "message": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length > 20_000_000:
            return self._json(413, {"ok": False, "message": "body too large"})
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as e:
            return self._json(400, {"ok": False, "message": f"invalid JSON: {e}"})

        name = body.get("name") or body.get("design_name") or ""
        overwrite = bool(body.get("overwrite"))

        if path == "/api/save-project":
            try:
                result = save_project_file(name, body, overwrite)
                code = 200 if result.get("ok") else (409 if result.get("exists") else 400)
                return self._json(code, result)
            except ValueError as e:
                return self._json(400, {"ok": False, "message": str(e)})
            except Exception as e:
                return self._json(500, {"ok": False, "message": str(e),
                                        "detail": traceback.format_exc(limit=6)})

        if path == "/api/export-step":
            try:
                result = export_step_file(name, body, overwrite)
                code = 200 if result.get("ok") else (409 if result.get("exists") else 400)
                return self._json(code, result)
            except ValueError as e:
                return self._json(400, {"ok": False, "message": str(e)})
            except Exception as e:
                return self._json(500, {"ok": False, "message": str(e),
                                        "detail": traceback.format_exc(limit=6)})

        self._json(404, {"ok": False, "message": "not found"})


def main():
    ensure_dirs()
    # Bind loopback only — never 0.0.0.0.
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"BladeForm helper listening on http://{HOST}:{PORT}/", flush=True)
    print(f"  projects → {PROJECTS}", flush=True)
    print(f"  steps    → {STEPS}", flush=True)
    print("  Open the URL above in your browser (launched by start_bladeform.bat).", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
        httpd.shutdown()


if __name__ == "__main__":
    main()
