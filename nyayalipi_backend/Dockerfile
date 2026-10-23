FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-hin tesseract-ocr-mar tesseract-ocr-ben \
    tesseract-ocr-guj tesseract-ocr-kan tesseract-ocr-mal tesseract-ocr-tam \
    tesseract-ocr-tel tesseract-ocr-pan build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

# download the embedding model at build time so start-up is fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY . .
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}