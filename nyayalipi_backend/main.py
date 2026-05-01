"""
Document Translation Pipeline
------------------------------
Flow: Upload doc → Extract text → Translate via Sarvam API
      → Replace in doc → Download  +  Bulbul TTS audio

Env vars (set before running uvicorn):
    SARVAM_API_KEY   sk_9lwdwj67_...
"""

import os
import uuid
import shutil
import tempfile
import requests as _requests
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from extractor import extract_text_from_file
from translator import translate_text, resolve_lang_name
from replacer import replace_text_in_document
from tts import synthesize_audio_bulbul
from rag_pipeline import RAGPipeline
from dotenv import load_dotenv
import os

load_dotenv()

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class DetectLanguageResponse(BaseModel):
    language: str


class TranslationResponse(BaseModel):
    job_id: str
    source_language: str
    target_language: str
    translated_text_preview: str
    document_download_url: str
    audio_download_url: Optional[str]
    original_filename: str
    message: str
    legal_terms_found: list = []
    entities_found: dict = {}

SUPPORTED_EXTENSIONS = {
    ".docx", ".txt", ".pdf",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}



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
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    tmp = Path(tempfile.mktemp(suffix=suffix))
    try:
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        sample = extract_text_from_file(tmp)[:800]
    finally:
        tmp.unlink(missing_ok=True)

    if not sample.strip():
        return DetectLanguageResponse(language="Unknown")

    lang_name = _detect_language_name(sample)
    return DetectLanguageResponse(language=lang_name)


@app.post("/translate", response_model=TranslationResponse)
async def translate_document(
    request: Request,
    file: UploadFile = File(...),
    source_language: str = Form("English"),
    target_language: str = Form("Hindi"),
    tts_speaker: str = Form("anushka"),
    generate_audio: bool = Form(True),
):
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

        print(f"[TRANSLATED OUTPUT]:\n{translated}\n")
        if not translated or not translated.strip():
            raise HTTPException(status_code=502, detail="Translation returned empty output.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Translation failed: {e}")

    # Step 3 — Rebuild document
    out_suffix = ".txt" if suffix in {".pdf"} | IMAGE_EXTENSIONS else suffix
    output_doc_path = job_dir / f"translated{out_suffix}"
    try:
        replace_text_in_document(
            input_path=input_path,
            output_path=output_doc_path,
            original_text=extracted,
            translated_text=translated,
            file_type=out_suffix,
        )
        print(f"[DEBUG] Output doc exists: {output_doc_path.exists()}, size: {output_doc_path.stat().st_size if output_doc_path.exists() else 'MISSING'}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document rebuild failed: {e}")

    # Step 4 — TTS (non-fatal)
    audio_url = None
    if generate_audio:
        audio_path = job_dir / "audio.wav"
        try:
            synthesize_audio_bulbul(
                text=translated,
                output_path=audio_path,
                speaker=tts_speaker,
                language=tgt_name,
            )
            audio_url = f"/download/audio/{job_id}"
        except Exception as e:
            print(f"[WARN] TTS failed for {job_id}: {e}")

    return TranslationResponse(
        job_id=job_id,
        source_language=src_name,
        target_language=tgt_name,
        translated_text_preview=translated[:500],
        document_download_url=f"/download/document/{job_id}",
        legal_terms_found = legal_terms,   
        entities_found    = entities,
        audio_download_url=audio_url,
        original_filename=file.filename,
        message="Translation complete.",
    )


@app.get("/download/document/{job_id}")
def download_document(job_id: str):
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")
    for ext in (".docx", ".txt", ".pdf"):
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
    try:
        resp = _requests.post(
            "https://api.sarvam.ai/text-lid",  # correct endpoint
            json={"input": text[:1000]},              # max 1000 chars
            headers={
                "Content-Type": "application/json",
                "api-subscription-key": SARVAM_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"[LID] Raw response: {data}")

        lang_code = data.get("language_code", "")
        if not lang_code:
            return "Unknown"

        from translator import _CODE_TO_NAME
        return _CODE_TO_NAME.get(lang_code, lang_code.split("-")[0].title())

    except Exception as e:
        print(f"[WARN] Language detection failed: {e}")
        return "Unknown"