"""
run_pipeline.py  -  run the NyayaLipi pipeline from the command line (no frontend, no login)

    python run_pipeline.py my.pdf --src Marathi --tgt Hindi
    python run_pipeline.py my.pdf --src Marathi --tgt Hindi --repeat 3     # 3 timed runs
    python run_pipeline.py my.pdf --src Marathi --tgt Hindi --audio        # also time TTS

It imports the same functions main.py uses (text extraction, translate_text, document rebuild),
so the timings match the API minus HTTP and auth. Per run it appends one row to
cli_out/timings.csv: seconds per stage, chunks per engine, fallbacks, failures.

Choose the engine(s) with the thresholds BEFORE running (PowerShell):
    $env:TERM_DENSITY_THRESHOLD="0";  $env:RISK_SENTENCE_RATIO_THRESHOLD="0"      # Mayura only
    $env:TERM_DENSITY_THRESHOLD="1";  $env:RISK_SENTENCE_RATIO_THRESHOLD="1.1"    # IndicTrans2 only
    $env:INDICTRANS_READ_TIMEOUT="900"                                             # CPU IndicTrans2
Unset them (Remove-Item Env:TERM_DENSITY_THRESHOLD ...) for the normal routed run.

Nothing from the document is printed; outputs go to cli_out/<run id>/ - delete when done.
"""
import argparse
import csv
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--src", default="English")
    ap.add_argument("--tgt", default="Hindi")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--audio", action="store_true", help="also time speech for the SUMMARY (summary_audio.py)")
    ap.add_argument("--audio-full", action="store_true", help="time speech for the FULL translated text (old behaviour, for comparison)")
    ap.add_argument("--speaker", default="shubh")
    ap.add_argument("--out", default="cli_out")
    a = ap.parse_args()

    path = Path(a.file)
    if not path.exists():
        sys.exit(f"File not found: {path}")

    import main as app                      # same objects the API uses
    from translator import translate_text, resolve_lang_name

    rag = getattr(app, "rag", None)
    if rag is None:
        from rag_pipeline import RAGPipeline
        rag = RAGPipeline()

    out_root = Path(a.out)
    out_root.mkdir(exist_ok=True)
    csv_path = out_root / "timings.csv"
    new_csv = not csv_path.exists()

    for n in range(1, a.repeat + 1):
        run_id = uuid.uuid4().hex[:8]
        run_dir = out_root / run_id
        run_dir.mkdir()
        t_all = time.perf_counter()

        t = time.perf_counter()
        extracted = app.extract_text_from_file(path)
        t_extract = time.perf_counter() - t
        if not extracted.strip():
            sys.exit("No text could be extracted (scanned PDF? needs OCR).")

        t = time.perf_counter()
        result = translate_text(text=extracted,
                                source_language=resolve_lang_name(a.src),
                                target_language=resolve_lang_name(a.tgt),
                                rag=rag)
        t_translate = time.perf_counter() - t
        translated = result["translated_text"]

        suffix = ".docx" if path.suffix.lower() == ".pdf" else path.suffix.lower()
        t = time.perf_counter()
        app.replace_text_in_document(output_path=run_dir / f"translated{suffix}",
                                     translated_text=translated, file_type=suffix)
        t_rebuild = time.perf_counter() - t

        t_tts, tts_chunks = "", ""
        if a.audio or a.audio_full:
            tgt_name = resolve_lang_name(a.tgt)
            t = time.perf_counter()
            if a.audio_full:
                audio_bytes, tts_chunks, failed_chunks = app.synthesize_audio_bulbul(
                    text=translated, speaker=a.speaker, language=tgt_name)
            else:
                from summary_audio import generate_summary_audio
                audio_bytes, tts_chunks, failed_chunks = generate_summary_audio(
                    translated, tgt_name, a.speaker)
            t_tts = time.perf_counter() - t
            if audio_bytes:
                (run_dir / "audio.wav").write_bytes(audio_bytes)

        total = time.perf_counter() - t_all
        log = result.get("routing_log", [])
        routes = [r["route"] for r in log]
        row = {
            "when": datetime.now().isoformat(timespec="seconds"),
            "run": run_id, "file": path.name, "src": a.src, "tgt": a.tgt,
            "term_density_thr": os.getenv("TERM_DENSITY_THRESHOLD", "default"),
            "risk_ratio_thr": os.getenv("RISK_SENTENCE_RATIO_THRESHOLD", "default"),
            "chars": len(extracted), "chunks": len(log),
            "to_indictrans2": sum(1 for r in routes if r == "indictrans2"),
            "to_mayura": sum(1 for r in routes if r == "sarvam_mayura"),
            "sentence_retry": sum(1 for r in routes if r.startswith("sentence_retry")),
            "unmasked_retry": sum(1 for r in routes if r == "sentence_retry_unmasked"),
            "fallbacks": sum(1 for r in routes if r.endswith("_fallback")),
            "failed": sum(1 for r in routes if r == "failed"),
            "extract_s": round(t_extract, 2), "translate_s": round(t_translate, 2),
            "rebuild_s": round(t_rebuild, 2),
            "tts_s": round(t_tts, 2) if t_tts != "" else "",
            "tts_chunks": tts_chunks,
            "total_s": round(total, 2),
        }
        if row["failed"]:
            print(f"\n*** INVALID RUN: {row['failed']} chunk(s) failed - not recorded in timings.csv ***")
            print(f"            output: {run_dir}")
            continue
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new_csv:
                w.writeheader()
                new_csv = False
            w.writerow(row)

        print(f"\n[run {n}/{a.repeat}] {run_id}: extract {row['extract_s']}s | translate {row['translate_s']}s | "
              f"rebuild {row['rebuild_s']}s" + (f" | tts {row['tts_s']}s ({tts_chunks} chunks)" if t_tts != "" else "") +
              f" | total {row['total_s']}s")
        print(f"            chunks {row['chunks']}: IndicTrans2 {row['to_indictrans2']}, "
              f"Mayura {row['to_mayura']}, sentence-retry {row['sentence_retry']} (unmasked {row['unmasked_retry']}), fallbacks {row['fallbacks']}, failed {row['failed']}")
        print(f"            output: {run_dir}")

    print(f"\nAll rows: {csv_path}")


if __name__ == "__main__":
    main()