import asyncio
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from faster_whisper import WhisperModel

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/app/models"))

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
CONTACT_TO = os.environ.get("CONTACT_TO", "robotics@dexx.systems").strip()
CONTACT_FROM = os.environ.get("CONTACT_FROM", "Igunosalabs <robotics@dexx.systems>").strip()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_AUDIO_SECONDS = 45.0

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_models: dict[str, WhisperModel] = {}
_transcribe_lock = asyncio.Semaphore(1)

MODEL_PATHS = {
    "small": MODELS_DIR / "unose-huen-small",
    "base": MODELS_DIR / "unose-huen-base",
}


def get_model(key: str) -> WhisperModel:
    if key not in MODEL_PATHS:
        key = "small"
    if key not in _models:
        _models[key] = WhisperModel(
            str(MODEL_PATHS[key]),
            device="cpu",
            compute_type="int8",
            cpu_threads=2,
            num_workers=1,
        )
    return _models[key]


@app.post("/api/contact")
async def contact(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON."}, status_code=400)

    email = str(body.get("email") or "").strip()
    project = str(body.get("project") or "").strip()
    note = str(body.get("note") or "").strip()

    if not email or not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return JSONResponse({"ok": False, "error": "Please enter a valid email address."}, status_code=400)

    record = {
        "email": email,
        "project": project or "General",
        "note": note,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        with open("/tmp/inquiries.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

    if not RESEND_API_KEY:
        return JSONResponse({"ok": True, "queued": True})

    lines = [
        "New inquiry from robotics.dexx.systems",
        "",
        f"Email: {email}",
        f"Project: {project or 'General / Open to discuss'}",
    ]
    if note:
        lines.append(f"Note: {note}")
    lines.append(f"Time: {record['timestamp']}")

    payload = json.dumps(
        {
            "from": CONTACT_FROM,
            "to": [CONTACT_TO],
            "reply_to": email,
            "subject": f"Igunosalabs Inquiry{f': {project}' if project else ''} — {email}",
            "text": "\n".join(lines),
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "igunosalabs/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if 200 <= resp.status < 300:
                return JSONResponse({"ok": True})
    except urllib.error.HTTPError as e:
        print("[contact] Resend HTTP error:", e.code, e.read().decode(errors="ignore"))
        return JSONResponse({"ok": False, "error": "Could not deliver message right now."}, status_code=502)
    except Exception as e:
        print("[contact] Delivery failed:", e)
        return JSONResponse({"ok": False, "error": "Delivery service unreachable."}, status_code=502)

    return JSONResponse({"ok": True})


@app.post("/api/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    model: str = Form("small"),
):
    model_key = "base" if model.strip().lower() == "base" else "small"
    data = await audio.read()
    if not data:
        return JSONResponse({"ok": False, "error": "Empty audio file."}, status_code=400)
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse({"ok": False, "error": "Audio file exceeds 10 MB limit."}, status_code=413)

    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        async with _transcribe_lock:
            t0 = time.perf_counter()

            def _run():
                m = get_model(model_key)
                segments, info = m.transcribe(
                    tmp_path,
                    beam_size=1,
                    vad_filter=True,
                    language="en",
                )
                if info.duration and info.duration > MAX_AUDIO_SECONDS:
                    raise ValueError(f"Audio is {info.duration:.1f}s; maximum allowed is {int(MAX_AUDIO_SECONDS)}s.")
                text = " ".join(seg.text.strip() for seg in segments).strip()
                return text, float(info.duration or 0.0)

            text, duration = await asyncio.to_thread(_run)
            elapsed = round(time.perf_counter() - t0, 2)

        return JSONResponse(
            {
                "ok": True,
                "model": f"Unose-Huen-{'Base' if model_key == 'base' else 'Small'}",
                "text": text,
                "duration": round(duration, 2),
                "seconds": elapsed,
            }
        )
    except ValueError as ve:
        return JSONResponse({"ok": False, "error": str(ve)}, status_code=400)
    except Exception as e:
        print("[transcribe] Error:", e)
        return JSONResponse({"ok": False, "error": "Could not transcribe audio. Try WAV, MP3, M4A, or WebM."}, status_code=500)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


@app.get("/{full_path:path}")
async def serve_static(full_path: str):
    clean = full_path.strip("/")
    if not clean:
        target = PUBLIC_DIR / "index.html"
    else:
        target = (PUBLIC_DIR / clean).resolve()
        if not str(target).startswith(str(PUBLIC_DIR.resolve())):
            return PlainTextResponse("Not found", status_code=404)
        if not target.exists() and not target.suffix:
            html_candidate = target.with_suffix(".html")
            if html_candidate.exists():
                target = html_candidate
        elif target.is_dir():
            target = target / "index.html"

    if not target.exists() or not target.is_file():
        return PlainTextResponse("Not found", status_code=404)

    headers = {}
    if target.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".svg", ".css", ".js"}:
        headers["Cache-Control"] = "public, max-age=86400"
    return FileResponse(target, headers=headers)
