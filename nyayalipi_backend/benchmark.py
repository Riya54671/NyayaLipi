"""
benchmark.py  -  metrics for the NyayaLipi v2 paper (one document, many configurations)

Usage (from the backend folder):
    python benchmark.py --doc doc.txt --src Marathi --tgt Hindi
    python benchmark.py --doc doc.txt --src Marathi --tgt Hindi --ref ref_hindi.txt   # adds chrF++/BLEU
    python benchmark.py --doc doc.txt --src Marathi --tgt Hindi --configs B0,A3      # subset
    python benchmark.py --doc doc.txt --src Marathi --tgt Hindi --report-only        # rebuild table

doc.txt = the extracted text of your document (UTF-8). Results go to ./bench_results/ (change with --out, e.g. one folder per document).
Runs are resumable: a configuration that already has bench_results/<cfg>/run.json is skipped
(use --force to redo). IndicTrans2 rows are slow on CPU, so start those overnight.

Configurations
    B0   Mayura only, no RAG, no masking                    (baseline engine)
    B1   IndicTrans2 only, no RAG, no masking               (baseline engine)
    A1   Mayura only + name/date/amount masking only
    A2   A1 + verbatim tokens (acts, citations, section numbers)
    A3   A2 + glossary substitution                          (full v2 masking, one engine)
    R03  full v2, routed, density threshold 0.03
    R06  full v2, routed, density threshold 0.06
    R10  full v2, routed, density threshold 0.10
The A-rows all use Mayura, so differences between them come from masking, not routing.
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

OUT = Path("bench_results")
MASK_TOKEN_RE = re.compile(r"\[\[[A-Z]+_\d+\]\]")

MAYURA_ONLY = {"TERM_DENSITY_THRESHOLD": "0", "RISK_SENTENCE_RATIO_THRESHOLD": "0"}
IT2_ONLY = {"TERM_DENSITY_THRESHOLD": "1", "RISK_SENTENCE_RATIO_THRESHOLD": "1.1",
            "INDICTRANS_READ_TIMEOUT": "900"}
OFF = {"VERBATIM_ENABLED": "0", "GLOSSARY_ENABLED": "0"}

CONFIGS = {
    "B0":  {"rag": False, "env": {**MAYURA_ONLY, **OFF}},
    "B1":  {"rag": False, "env": {**IT2_ONLY, **OFF}},
    "A1":  {"rag": True,  "env": {**MAYURA_ONLY, **OFF}},
    "A2":  {"rag": True,  "env": {**MAYURA_ONLY, "VERBATIM_ENABLED": "1", "GLOSSARY_ENABLED": "0"}},
    "A3":  {"rag": True,  "env": {**MAYURA_ONLY, "VERBATIM_ENABLED": "1", "GLOSSARY_ENABLED": "1"}},
    "R03": {"rag": True,  "env": {"TERM_DENSITY_THRESHOLD": "0.03", "INDICTRANS_READ_TIMEOUT": "900"}},
    "R06": {"rag": True,  "env": {"TERM_DENSITY_THRESHOLD": "0.06", "INDICTRANS_READ_TIMEOUT": "900"}},
    "R10": {"rag": True,  "env": {"TERM_DENSITY_THRESHOLD": "0.10", "INDICTRANS_READ_TIMEOUT": "900"}},
}
DEFAULT_ORDER = ["B0", "A1", "A2", "A3", "R03", "R06", "R10", "B1"]   # slow IndicTrans2-only last


# ---------------------------------------------------------------------------
# Child process: run ONE configuration (env is set before translator is imported,
# because routing.py reads its thresholds at import time)
# ---------------------------------------------------------------------------
def run_child(cfg_name: str, tgt: str):
    cfg = CONFIGS[cfg_name]
    english = (OUT / "english.txt").read_text(encoding="utf-8")

    from translator import translate_text
    rag = None
    if cfg["rag"]:
        from rag_pipeline import RAGPipeline
        rag = RAGPipeline()

    t0 = time.perf_counter()
    res = translate_text(english, "English", tgt, rag=rag)
    wall = time.perf_counter() - t0

    d = OUT / cfg_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "translated.txt").write_text(res["translated_text"], encoding="utf-8")
    (d / "run.json").write_text(json.dumps(
        {"wall_seconds": round(wall, 2), "routing_log": res.get("routing_log", [])},
        ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Prepare: pivot once, build the checklist (what a good translation must keep)
# ---------------------------------------------------------------------------
def prepare(doc: Path, src: str, tgt: str):
    from translator import resolve_lang_code, resolve_lang_name, _translate_pass_pivot
    from rag_pipeline import RAGPipeline
    import masking

    OUT.mkdir(exist_ok=True)
    text = doc.read_text(encoding="utf-8")
    src_code, tgt_code = resolve_lang_code(src), resolve_lang_code(tgt)

    eng_path = OUT / "english.txt"
    if not eng_path.exists():
        english = text if src_code == "en-IN" else _translate_pass_pivot(text, src_code, "en-IN")
        eng_path.write_text(english, encoding="utf-8")
    english = eng_path.read_text(encoding="utf-8")

    rag = RAGPipeline()
    lang_key = tgt_code.split("-")[0]
    r = rag.process(extracted_text=english, target_language=resolve_lang_name(tgt_code), lang_key=lang_key)
    ents = r["entities"]

    acts = sorted({a for a in (masking._clean_act(x) for x in ents.get("ACT", [])) if a})
    checklist = {
        "names":    sorted({m.group(1) for m in masking.NAME_PATTERN.finditer(english)}),
        "dates":    sorted({m.group(0) for m in masking.DATE_PATTERN.finditer(english)}),
        "amounts":  sorted({m.group(0) for m in masking.AMOUNT_PATTERN.finditer(english)}),
        "acts":     acts,
        "citations": sorted({c.strip() for c in ents.get("CASE_REF", []) if c.strip()}),
        "sections": sorted({m.group(2) for m in masking.SECTION_REF_PATTERN.finditer(english)}),
        # vetted terms: occurrences in the English source (whole word, case-insensitive)
        "terms": {},
    }
    low = english.lower()
    for term, info in r.get("term_translations", {}).items():
        n = 0
        for form in info.get("forms", [term]):
            n += len(re.findall(r"(?<!\w)" + re.escape(form.lower()) + r"(?!\w)", low))
        if n:
            checklist["terms"][term] = {"translation": info["translation"], "src_count": n}
    (OUT / "checklist.json").write_text(json.dumps(checklist, ensure_ascii=False, indent=1), encoding="utf-8")
    return checklist


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _amount_digits(a: str) -> str:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", a)
    return m.group(0) if m else a


def _has_number(num: str, out: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(num) + r"(?![\w])", out) is not None


def score(cfg_name: str, checklist: dict, ref_text: str | None) -> dict:
    d = OUT / cfg_name
    out = (d / "translated.txt").read_text(encoding="utf-8")
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    log = run["routing_log"]

    row = {"config": cfg_name}

    # entity preservation (exact text for names/dates/acts/citations; number for amounts/sections)
    checks = {
        "names":     [(n, n in out) for n in checklist["names"]],
        "dates":     [(x, x in out) for x in checklist["dates"]],
        "amounts":   [(x, _amount_digits(x) in out) for x in checklist["amounts"]],
        "acts":      [(x, x in out) for x in checklist["acts"]],
        "citations": [(x, x in out) for x in checklist["citations"]],
        "sections":  [(x, _has_number(x, out)) for x in checklist["sections"]],
    }
    kept = total = 0
    for k, items in checks.items():
        ok = sum(1 for _, f in items if f)
        row[f"{k}_kept"] = f"{ok}/{len(items)}"
        kept += ok
        total += len(items)
    row["entity_acc_%"] = round(100 * kept / total, 1) if total else ""

    # terminology: occurrence-weighted adherence to the vetted translation
    num = den = 0
    for term, info in checklist["terms"].items():
        c = out.count(info["translation"])
        num += min(c, info["src_count"])
        den += info["src_count"]
    row["term_acc_%"] = round(100 * num / den, 1) if den else ""
    row["terms_checked"] = den

    # integrity / routing / latency
    routes = [r["route"] for r in log]
    row["chunks"] = len(log)
    row["leftover_tokens"] = len(MASK_TOKEN_RE.findall(out))
    row["failed_chunks"] = sum(1 for r in routes if r == "failed")
    row["fallbacks"] = sum(1 for r in routes if r.endswith("_fallback"))
    row["to_indictrans2"] = sum(1 for r in routes if r == "indictrans2")
    row["to_mayura"] = sum(1 for r in routes if r == "sarvam_mayura")
    secs = [r["seconds"] for r in log]
    row["chunk_sec_mean"] = round(sum(secs) / len(secs), 1) if secs else ""
    row["chunk_sec_total"] = round(sum(secs), 1)
    row["wall_sec"] = run["wall_seconds"]

    # quality vs reference (document level)
    if ref_text:
        try:
            from sacrebleu.metrics import CHRF, BLEU
            row["chrF++"] = round(CHRF(word_order=2).corpus_score([out], [[ref_text]]).score, 1)
            row["BLEU"] = round(BLEU().corpus_score([out], [[ref_text]]).score, 1)
        except ImportError:
            row["chrF++"] = row["BLEU"] = "pip install sacrebleu"
    return row


def report(configs, ref_path):
    checklist = json.loads((OUT / "checklist.json").read_text(encoding="utf-8"))
    ref = Path(ref_path).read_text(encoding="utf-8") if ref_path else None
    rows = [score(c, checklist, ref) for c in configs if (OUT / c / "run.json").exists()]
    if not rows:
        print("No finished runs to report.")
        return
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT / "summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    show = ["config", "entity_acc_%", "term_acc_%", "leftover_tokens", "failed_chunks", "fallbacks",
            "to_indictrans2", "to_mayura", "chunk_sec_mean", "wall_sec"] + (["chrF++", "BLEU"] if ref else [])
    print("\n" + " | ".join(f"{c:>14}" for c in show))
    for r in rows:
        print(" | ".join(f"{str(r.get(c, '')):>14}" for c in show))
    print(f"\nChecklist: {len(checklist['names'])} names, {len(checklist['dates'])} dates, "
          f"{len(checklist['amounts'])} amounts, {len(checklist['acts'])} acts, "
          f"{len(checklist['citations'])} citations, {len(checklist['sections'])} section numbers, "
          f"{len(checklist['terms'])} vetted terms.")
    print(f"Full table: {OUT / 'summary.csv'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc")
    ap.add_argument("--src", default="English")
    ap.add_argument("--tgt", default="Hindi")
    ap.add_argument("--ref")
    ap.add_argument("--configs", default=",".join(DEFAULT_ORDER))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--child")
    ap.add_argument("--out", default="bench_results", help="results folder (one per document)")
    a = ap.parse_args()
    global OUT
    OUT = Path(a.out)

    if a.child:
        run_child(a.child, a.tgt)
        return

    configs = [c.strip() for c in a.configs.split(",") if c.strip()]
    bad = [c for c in configs if c not in CONFIGS]
    if bad:
        sys.exit(f"Unknown configuration(s): {bad}. Choose from {list(CONFIGS)}")

    if not a.report_only:
        if not a.doc:
            sys.exit("--doc is required")
        prepare(Path(a.doc), a.src, a.tgt)
        for c in configs:
            if (OUT / c / "run.json").exists() and not a.force:
                print(f"[bench] {c}: already done, skipping")
                continue
            print(f"[bench] running {c} ...")
            env = {**os.environ, **CONFIGS[c]["env"]}
            t0 = time.perf_counter()
            p = subprocess.run([sys.executable, __file__, "--child", c, "--tgt", a.tgt, "--out", a.out], env=env)
            print(f"[bench] {c} finished in {time.perf_counter() - t0:.0f}s (exit {p.returncode})")
    report(configs, a.ref)


if __name__ == "__main__":
    main()