# ⚖️ NyayaLipi — AI-Powered Legal Document Translator

An intelligent legal document translation app that combines RAG (Retrieval-Augmented Generation), Named Entity Recognition for legal terms, and neural translation to deliver accurate, context-aware translations of legal documents across Indian languages.

---

## ✨ Key Features

- 📄 **Legal document upload** — supports PDF and image formats
- 🔍 **Automatic language detection** — identifies source language from document content
- 🧠 **RAG pipeline** — fetches legal term context from FAISS vector store for precise translation
- 🏷️ **InLegalNER** — detects and preserves legal named entities during translation
- 🌐 **Sarvam Translate** — neural translation engine optimized for Indian languages
- 🔊 **Audio output** — text-to-speech via Sarvam TTS
- 📥 **Reconstructed document download** — translated text re-embedded back into original document
- 🔔 **In-app notifications** — status updates throughout the pipeline

---

## 🏗️ Architecture Overview

### Translation Pipeline

```
Input Document
      │
      ▼
┌─────────────────┐
│  Text Extraction │  ← Extract raw text from PDF/image
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│  Convert to English  │  ← Intermediate English representation
└────────┬────────────┘
         │
         ▼
┌──────────────────────┐
│  InLegalNER          │  ← Detect legal named entities & terms
└────────┬─────────────┘
         │
         ▼
┌──────────────────────────────┐
│  FAISS Vector Store (RAG)    │  ← Fetch context for legal terms
└────────┬─────────────────────┘
         │
         ▼
┌──────────────────────────────┐
│  System Prompt Construction  │  ← Build enriched translation prompt
└────────┬─────────────────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│  Sarvam-Translate                          │  ← Full text + system prompt
│  (original text + legal context injected)  │
└────────┬───────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│  Refined Output  │  ← Context-aware translated text
└──────────────────┘
```

---

### App Flow

```
Landing Screen
      │
      ▼
Home Screen
      │
      ├── Upload Document
      │         │
      │         ▼
      │   In-app notification → "Document received"
      │         │
      │         ▼
      │   Send to Backend
      │         │
      │         ▼
      │   Language Detection
      │         │
      │         ▼
      │   Show detected source language to user
      │         │
      │    ┌────┴─────┐
      │  Correct?    No
      │    │          │
      │    ▼          ▼
      │  Proceed   User inputs correct source language
      │    │          │
      │    └────┬─────┘
      │         ▼
      │   User selects Target Language
      │         │
      │         ▼
      │   Send to Backend → RAG Pipeline runs
      │         │
      │         ▼
      │   Translated text re-embedded into original doc
      │         │
      │         ▼
      │   Backend sends doc to Frontend
      │         │
      │         ├──────────────────────────────────┐
      │         ▼                                  ▼
      │   📥 Download Available            🔤 English text displayed
      │   (notification sent)              (from intermediate English
      │         │                           layer of pipeline)
      │         ▼
      │   🔊 Audio Output (Sarvam TTS)
      │   (audio streamed from backend)
```

---

## 🔧 Tech Stack

| Component | Technology |
|---|---|
| Translation Engine | Sarvam-Translate |
| Text-to-Speech | Sarvam TTS |
| Legal NER | InLegalNER |
| Vector Store | FAISS |
| Text Extraction | PyMuPDF / Tesseract OCR |
| Backend | FastAPI / Python |
| Frontend |  Flutter  |

---

## 🚀 Getting Started

### Prerequisites

```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file at the project root:

```env
SARVAM_API_KEY=your_sarvam_api_key
FAISS_INDEX_PATH=./data/faiss_index
```

### Run the Backend

```bash
cd backend
uvicorn main:app --reload
```

### Run the Frontend

```bash
cd frontend
npm install
npm start
```

---

## 📁 Project Structure

```
├── backend/
│   ├── pipeline/
│   │   ├── text_extraction.py       # PDF/image text extraction
│   │   ├── language_detection.py    # Source language detection
│   │   ├── ner.py                   # InLegalNER integration
│   │   ├── rag.py                   # FAISS retrieval & prompt builder
│   │   └── translate.py             # Sarvam-Translate integration
│   │   └── sarvam_tts.py            # Text-to-speech output
│   └── main.py                      # FastAPI entry point
│
├── frontend/
│   ├── screens/
│   │   ├── LandingScreen
│   │   ├── HomeScreen
│   │   └── DocumentViewer
│   └── components/
│       ├── UploadWidget
│       ├── LanguageSelector
│       └── NotificationBanner
│
├── data/
│   └── faiss_index/                 # Legal terms vector index
│
├── .env.example
├── requirements.txt
└── README.md
```

---

## 🧠 How the RAG Pipeline Works

1. **Text Extraction** — Raw text is pulled from the uploaded document (PDF parsing or OCR for scanned images).
2. **English Conversion** — Text is converted to English as an intermediate step to standardize NER processing.
3. **InLegalNER** — Legal named entities (acts, clauses, parties, jurisdictions) are identified and tagged.
4. **FAISS Retrieval** — For each detected legal term, the FAISS index is queried to fetch relevant legal definitions and context.
5. **Prompt Construction** — A structured system prompt is built combining extracted context and translation instructions.
6. **Sarvam-Translate** — The full original text plus the enriched system prompt is sent to Sarvam-Translate for final, context-aware translation.
7. **Document Reconstruction** — Translated text is re-embedded back into the original document layout.

---

## 🌍 Supported Languages

Supports Indian languages available via the Sarvam API — including Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, and more.

---

## 📌 Notes

- The English intermediate text generated during pipeline execution is reused directly for the English display view — no extra translation call needed.
- Audio output is generated server-side via Sarvam TTS and streamed to the frontend.
- InLegalNER model weights are not included — see [InLegalNER](https://github.com/Legal-NLP-EkStep/legal_NER) for setup instructions.

---

*Built to make legal documents accessible across language barriers.*
