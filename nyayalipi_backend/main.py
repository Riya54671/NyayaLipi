"""
Document Translation Pipeline
------------------------------
Flow: Upload doc → Extract text → Translate via Sarvam API
      → Replace in doc → Download  +  Bulbul TTS audio

Env vars (set before running uvicorn):
    SARVAM_API_KEY   (set in .env, never commit the real key)
"""

import os
import re 
import uuid
import shutil
import tempfile
from datetime import datetime, timezone
import requests as _requests
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form, Depends, BackgroundTasks
from kb_updater import process_document
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from extractor import extract_text_from_file
from translator import translate_text, resolve_lang_name
from replacer import replace_text_in_document
from tts import synthesize_audio_bulbul
from summary_audio import generate_summary_audio
from rag_pipeline import RAGPipeline
from auth_routes import router as auth_router
from auth_utils import get_current_user
from database import files_collection
from dotenv import load_dotenv
from extractor import extract_pdf_lines_with_boxes, extract_image_lines_with_boxes
from bson import ObjectId
from glossary import glossary
from timing import reset_timing, get_timing_report
import time
import traceback
from fastapi import FastAPI, Request

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

api_key = os.getenv("SARVAM_API_KEY")

# init once at startup (loads FAISS index)
rag = RAGPipeline()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sarvam Document Translation Pipeline",
    version="1.0.0",
)

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    print(f"[HTTP] {request.method} {request.url.path} started", flush=True)
    try:
        response = await call_next(request)
    except Exception:
        elapsed = time.perf_counter() - start
        print(
            f"[HTTP] {request.method} {request.url.path} failed after {elapsed:.3f}s",
            flush=True,
        )
        raise
    elapsed = time.perf_counter() - start
    print(
        f"[HTTP] {request.method} {request.url.path} "
        f"returned {response.status_code} in {elapsed:.3f}s",
        flush=True,
    )
    response.headers["X-Process-Time"] = f"{elapsed:.3f}"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DetectLanguageResponse(BaseModel):
    language: str


class TranslationResponse(BaseModel):
    job_id: str
    file_id: Optional[str] = None
    source_language: str
    target_language: str
    translated_text_preview: str
    document_download_url: str
    audio_download_url: Optional[str]
    original_filename: str
    message: str
    legal_terms_found: list = []
    entities_found: dict = {}
    glossary: list = []
    timing: list = []
    routing_log: list = []

SUPPORTED_EXTENSIONS = {
    ".docx", ".txt", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

def _first_n_sentences(text: str, n: int = 8, max_chars: int = 800) -> str:
    """Return the first n sentences of text, capped at max_chars as a safety limit."""
    sentences = re.split(r'(?<=[.!?।])\s+', text.strip())
    sample = " ".join(sentences[:n]).strip()
    return sample[:max_chars]

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "service": "Sarvam Document Translation Pipeline",
    }

@app.post("/detect-language", response_model=DetectLanguageResponse)
async def detect_language(file: UploadFile = File(...)):
    filename = file.filename or ""
    print(f"[LID] Incoming detect-language request ({filename!r})", flush=True)
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        print(f"[LID] Unsupported file type: {suffix}", flush=True)
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            tmp = Path(temp_file.name)
            shutil.copyfileobj(file.file, temp_file)
        full_text = extract_text_from_file(tmp)
        sample = _first_n_sentences(full_text, n=8)
        print(f"[LID] Extracted {len(sample)} characters for detection", flush=True)
    except Exception as exc:
        print(f"[LID] Text extraction failed: {exc}", flush=True)
        raise HTTPException(status_code=422, detail="Text extraction failed.") from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

    if not sample.strip():
        print("[LID] Extracted text is empty; returning Unknown", flush=True)
        return DetectLanguageResponse(language="Unknown")

    lang_name = _detect_language_name(sample)
    print(f"[LID] Detected language: {lang_name}", flush=True)
    return DetectLanguageResponse(language=lang_name)


@app.get("/files/{file_id}/glossary")
def get_glossary(file_id: str, current_user: dict = Depends(get_current_user)):
    try:
        oid = ObjectId(file_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file id.")

    file = files_collection.find_one({"_id": oid, "user_id": current_user["_id"]})
    if not file:
        raise HTTPException(status_code=404, detail="File not found.")

    return glossary.get_terms_by_ids(file.get("term_ids", []))

@app.get("/me/files")
def get_my_files(current_user: dict = Depends(get_current_user)):
    """All documents this user has translated, newest first."""
    docs = files_collection.find({"user_id": current_user["_id"]}).sort("time", -1)
    return [
        {
            "file_id": str(d["_id"]),
            "document_name": d.get("document_name", ""),
            "time": d["time"].isoformat() if d.get("time") else None,
            "term_count": len(d.get("term_ids", [])),
        }
        for d in docs
    ]

@app.post("/translate", response_model=TranslationResponse)
async def translate_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_language: str = Form("English"),
    target_language: str = Form("Hindi"),
    tts_speaker: str = Form("shubh"),
    generate_audio: bool = Form(True),
    current_user: dict = Depends(get_current_user),
):
    # Keep the background task object referenced so FastAPI injection works cleanly.
    background_tasks.add_task(lambda: None)
    job_id = str(uuid.uuid4())
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    # Save upload
    input_path = job_dir / f"input{suffix}"
    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Step 1 — Extract
    try:
        extracted = extract_text_from_file(input_path)
        print(f"[DEBUG] FULL EXTRACTED TEXT:\n{extracted}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Text extraction failed: {e}")

    if not extracted.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted.")


    src_name = resolve_lang_name(source_language)
    tgt_name = resolve_lang_name(target_language)

    # Step 2 — Translate
    try:
        result = translate_text(
            text=extracted,
            source_language=src_name,
            target_language=tgt_name,
            rag=rag,
        )
        translated = result["translated_text"]
        legal_terms = result["legal_terms"]
        entities = result["entities"]

        background_tasks.add_task(process_document, result.get("english_text", extracted), legal_terms)

        print(f"[TRANSLATED OUTPUT]:\n{translated}\n")
        if not translated or not translated.strip():
            raise HTTPException(status_code=502, detail="Translation returned empty output.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Translation failed: {e}")

    # Step 3 — Rebuild document
    lines = None
    # For PDF input, output as .docx instead of reconstructing PDF layout —
    # .docx reconstruction is proven working; PDF layout reconstruction is not, given time constraints.
    if suffix == ".pdf":
        out_suffix = ".docx"
    else:
        out_suffix = suffix
    output_doc_path = job_dir / f"translated{out_suffix}"
    try:
        replace_text_in_document(
            output_path=output_doc_path,
            translated_text=translated,
            file_type=out_suffix,
        )
        print(f"[DEBUG] Output doc exists: {output_doc_path.exists()}, size: {output_doc_path.stat().st_size if output_doc_path.exists() else 'MISSING'}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Document rebuild failed: {e}")

    # Step 4 — TTS (non-fatal)
    audio_url = None
    if generate_audio:
        audio_path = job_dir / "audio.wav"
        try:
            # Speech is generated for a short summary only, not the full document (cost).
            audio_bytes, total_chunks, failed_chunks = generate_summary_audio(
                translated_text=translated,
                language=tgt_name,
                speaker=tts_speaker,
            )
            if audio_bytes:
                audio_path.write_bytes(audio_bytes)
                audio_url = f"/download/audio/{job_id}"
                if failed_chunks > 0:
                    print(f"[WARN] Audio for {job_id} is partial: {failed_chunks}/{total_chunks} chunks failed")
        except Exception as e:
            print(f"[WARN] TTS failed for {job_id}: {e}")

    # Step 5 — Record in user's file history with KB term IDs (non-fatal)
    term_ids = []
    file_id = None
    try:
        term_ids = [
            tid for t in legal_terms for tid in rag.aho.term_to_ids.get(t.lower(), [])
        ]
        inserted = files_collection.insert_one({
            "user_id": current_user["_id"],
            "document_name": file.filename,
            "term_ids": term_ids,
            "time": datetime.now(timezone.utc),
        })
        file_id = str(inserted.inserted_id)
    except Exception as e:
        print(f"[WARN] Failed to record file history for {job_id}: {e}")

    return TranslationResponse(
        job_id=job_id,
        file_id=file_id,
        source_language=src_name,
        target_language=tgt_name,
        translated_text_preview=translated[:500],
        timing=get_timing_report(),
        routing_log=result.get("routing_log", []),
        document_download_url=f"/download/document/{job_id}",
        legal_terms_found=legal_terms,
        entities_found=entities,
        glossary=glossary.get_terms_by_ids(term_ids),
        audio_download_url=audio_url,
        original_filename=file.filename,
        message="Translation complete.",
    )


@app.get("/download/document/{job_id}")
def download_document(job_id: str):
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    for ext in (".docx", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"):
        candidate = job_dir / f"translated{ext}"
        if candidate.exists():
            return FileResponse(str(candidate), filename=f"translated_{job_id}{ext}",
                                media_type="application/octet-stream")
    raise HTTPException(status_code=404, detail="Document not found.")


@app.get("/download/audio/{job_id}")
def download_audio(job_id: str):
    path = OUTPUT_DIR / job_id / "audio.wav"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not found.")
    return FileResponse(str(path), filename=f"audio_{job_id}.wav", media_type="audio/wav")


@app.get("/status/{job_id}")
def job_status(job_id: str):
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"job_id": job_id, "files": [p.name for p in job_dir.iterdir()]}


# ---------------------------------------------------------------------------
# Language detection helper — uses Sarvam API instead of Ollama
# ---------------------------------------------------------------------------
def _detect_language_name(text: str) -> str:
    """Detect language using Sarvam's /detect-language endpoint."""
    SARVAM_API_KEY = api_key
    if not SARVAM_API_KEY or not str(SARVAM_API_KEY).strip():
        print("[LID] Missing SARVAM_API_KEY; language detection cannot run.", flush=True)
        raise HTTPException(status_code=503, detail="Language detection is not configured.")

    try:
        payload = {"input": text[:1000]}
        print("[LID] Calling Sarvam text-lid", flush=True)
        resp = _requests.post(
            "https://api.sarvam.ai/text-lid",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "api-subscription-key": SARVAM_API_KEY,
            },
            timeout=15,
        )
        print(f"[LID] Sarvam response status={resp.status_code}", flush=True)
        resp.raise_for_status()
        data = resp.json()

        lang_code = data.get("language_code", "")
        if not lang_code:
            print("[LID] Language code missing in Sarvam response", flush=True)
            raise HTTPException(
                status_code=502,
                detail="Language detection service returned no language code.",
            )

        from translator import _CODE_TO_NAME
        return _CODE_TO_NAME.get(lang_code, lang_code.split("-")[0].title())

    except HTTPException:
        raise
    except Exception as exc:
        print(f"[LID] Sarvam language detection failed: {exc}", flush=True)
        raise HTTPException(
            status_code=502,
            detail="Language detection service failed.",
        ) from exc