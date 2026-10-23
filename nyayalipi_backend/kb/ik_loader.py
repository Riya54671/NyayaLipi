# kb/ik_loader.py — Indian Kanoon → sections + definitions → MongoDB Atlas
# Run from nyayalipi_backend/: python kb/ik_loader.py

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

load_dotenv()

# ---------- Config ----------
ACTS = [
    # Core civil/criminal
    "Indian Contract Act, 1872",
    "Specific Relief Act, 1963",
    "General Clauses Act, 1897",
    "Bharatiya Nyaya Sanhita, 2023",
    "Bharatiya Nagarik Suraksha Sanhita, 2023",
    "Bharatiya Sakshya Adhiniyam, 2023",
    "Indian Penal Code, 1860",
    "Code of Criminal Procedure, 1973",
    "Indian Evidence Act, 1872",

    # Civil, property, commercial
    "Code of Civil Procedure, 1908",
    "Transfer of Property Act, 1882",
    "Limitation Act, 1963",
    "Registration Act, 1908",
    "Indian Stamp Act, 1899",
    "Negotiable Instruments Act, 1881",
    "Sale of Goods Act, 1930",
    "Indian Partnership Act, 1932",
    "Arbitration and Conciliation Act, 1996",

    # Corporate, finance, tax
    "Companies Act, 2013",
    "Insolvency and Bankruptcy Code, 2016",
    "Central Goods and Services Tax Act, 2017",
    "Prevention of Money-laundering Act, 2002",

    # Consumer, real estate, tech, IP
    "Consumer Protection Act, 2019",
    "Real Estate (Regulation and Development) Act, 2016",
    "Information Technology Act, 2000",
    "Trade Marks Act, 1999",
    "Copyright Act, 1957",

    # Family, social, criminal special laws
    "Hindu Marriage Act, 1955",
    "Hindu Succession Act, 1956",
    "Protection of Women from Domestic Violence Act, 2005",
    "Protection of Children from Sexual Offences Act, 2012",
    "Juvenile Justice (Care and Protection of Children) Act, 2015",
    "Narcotic Drugs and Psychotropic Substances Act, 1985",
    "Right to Information Act, 2005",

    # Labour, infrastructure
    "Code on Wages, 2019",
    "Industrial Relations Code, 2020",
    "Code on Social Security, 2020",
    "Motor Vehicles Act, 1988",
    "Electricity Act, 2003",

    # ---- Optional (not yet tested; check the summary after uncommenting) ----
    # "Income Tax Act, 2025",
]

# Manual IDs: either the Entire Act ID or ANY section ID of the act (loader follows it to the Entire Act)
KNOWN_TIDS = {
    "Bharatiya Nyaya Sanhita, 2023": 149679501,             # Entire Act
    "Bharatiya Nagarik Suraksha Sanhita, 2023": 4405974,    # Section 2 → Entire Act
    "Bharatiya Sakshya Adhiniyam, 2023": 89955729,          # Section 2 → Entire Act
    "Income Tax Act, 2025": 10588298,                       # Section 2 → Entire Act (only if uncommented above)
}

# Repealed acts → the act that replaced them
REPEALED = {
    "Indian Penal Code, 1860": "Bharatiya Nyaya Sanhita, 2023",
    "Code of Criminal Procedure, 1973": "Bharatiya Nagarik Suraksha Sanhita, 2023",
    "Indian Evidence Act, 1872": "Bharatiya Sakshya Adhiniyam, 2023",
}

# Acts whose definitions are a RANGE of sections, one term per section, where the TITLE is the term
DEFINITION_RANGES = {
    "Indian Penal Code, 1860": (6, 52),
    # "Negotiable Instruments Act, 1881": (4, 16),   # optional, untested
}

BUDGET_RS = 60.0      # hard cap per run; stops cleanly when reached
SEARCH_PAGES = 2
LOW_TERMS = 5

API = "https://api.indiankanoon.org"
HEADERS = {"Authorization": f"Token {os.environ['IK_API_TOKEN']}", "Accept": "application/json"}
COST = {"search": 0.50, "doc": 0.20}

KB_DIR = Path(__file__).resolve().parent          # always kb/, wherever you run from
CACHE = KB_DIR / "ik_cache"
CACHE.mkdir(exist_ok=True)
ACT_INDEX = KB_DIR / "act_index.json"
REPORT = KB_DIR / "load_report.json"
spent = 0.0

# ---------- Definition patterns ----------
QUOTED_RE = re.compile(r"[“\"]([^”\"]{2,80})[”\"]|‘([^’]{2,80})’")
CLAUSE_END_RE = re.compile(
    r"\b(?:is|are|becomes?)\s+(?:called\s+|said\s+to\s+be\s+|termed\s+)?(?:an?\s+|the\s+)?"
    r"([A-Za-z][A-Za-z\-]*(?:\s+[A-Za-z\-]+){0,3})\s*[;.:]?\s*$"
)
START_TERM_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z\-' ]{0,60}?)\s*(?=,|\s+(?:means|includes|denotes|signifies|shall)\b)"
)
DEF_VERB_RE = re.compile(
    r"\b(?:means|includes|denotes|signifies|shall\s+mean|shall\s+include|"
    r"shall\s+have\s+the\s+same\s+meaning|shall\s+be\s+deemed)\b",
    re.IGNORECASE,
)
PREPOSITION_RE = re.compile(r"\s+(?:for|of|to|by|in|with|under|from|on)\s+.*$", re.IGNORECASE)
LABEL_RE = re.compile(r"^\s*(?:\(\s*[0-9A-Za-z]{1,5}\s*\)\s*)+")
HEADING_RE = re.compile(r"^\s*(\d+[A-Z]*)\.\s*(.*)$")
CONTAINER_CLASSES = ("akn-chapter", "akn-part", "akn-subpart")

STOPWORDS = {"and", "or", "the", "a", "an", "of", "to", "in", "by", "for", "when", "where", "if"}

# Titles/fragments that slip through but aren't real legal terms (add more as you find them)
JUNK_TERMS = {
    "section", "sense of expression once explained", "queen", "done negligently or not",
    "legally boundto do", "where this part", "not a decree", "settlement- settlement",
    "in relation to a cinematographic film", "in relation to a sound recording",
}


# ---------- API with cache + budget ----------
class BudgetReached(Exception):
    pass


def ik_post(path, kind):
    """Call the API once; later runs reuse the saved copy (no repeat charges)."""
    global spent
    cache_file = CACHE / (re.sub(r"[^\w]+", "_", path).strip("_") + ".json")
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    if spent + COST[kind] > BUDGET_RS:
        raise BudgetReached(f"Budget limit reached (₹{spent:.2f} spent). Raise BUDGET_RS to continue.")
    r = requests.post(API + path, headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "errmsg" in data:
        raise RuntimeError(f"API error for {path}: {data['errmsg']}")
    spent += COST[kind]
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"  [API ₹{COST[kind]:.2f}] {path}  (total ₹{spent:.2f})")
    return data


def clean(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def normalize(term):
    return re.sub(r"\s+", " ", term.strip().lower())


def is_valid_term(term):
    """Reject fragments: must start with a letter, be 1–6 words, no brackets/asterisks/digits."""
    t = term.strip()
    if not t or not t[0].isalpha():
        return False
    if re.search(r"[\[\]\*\d(){};]", t):
        return False
    if len(t.split()) > 6 or t.lower() in STOPWORDS:
        return False
    if re.search(r"\b(?:repealed|omitted|substituted|inserted|subs|ins|rep)\b", t, re.IGNORECASE):
        return False
    if normalize(t) in JUNK_TERMS:
        return False
    return True


# ---------- Step 1: act name → Entire Act document ----------
def act_core(act_name):
    return re.sub(r",?\s*\d{4}\s*$", "", act_name).lower().removeprefix("the ").strip()


def title_matches(title, act_name):
    t = clean(title).lower()
    year = re.search(r"\d{4}", act_name)
    return act_core(act_name) in t and (not year or year.group(0) in t)


def is_whole_act_title(title, act_name):
    t = clean(title).lower().removeprefix("the ").strip()
    year = re.search(r"\d{4}", act_name)
    return t.startswith(act_core(act_name)) and (not year or year.group(0) in t)


def load_index():
    return json.loads(ACT_INDEX.read_text(encoding="utf-8")) if ACT_INDEX.exists() else {}


def remember(act_name, tid):
    index = load_index()
    index[act_name] = tid
    ACT_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return tid


def follow_to_entire_act(tid):
    doc = ik_post(f"/doc/{tid}/", "doc")
    for c in doc.get("covers") or []:
        if c.get("title") == "Entire Act":
            return c["tid"]
    return tid


def find_entire_act(act_name):
    if act_name in KNOWN_TIDS:
        return remember(act_name, follow_to_entire_act(KNOWN_TIDS[act_name]))

    index = load_index()
    if act_name in index:
        return index[act_name]

    core = re.sub(r",?\s*\d{4}\s*$", "", act_name).strip()
    for query in [f'"{core}" doctypes:union-act', f"{act_name} doctypes:union-act"]:
        res = ik_post(f"/search/?formInput={requests.utils.quote(query)}&pagenum=0", "search")
        for d in res.get("docs", []):
            if is_whole_act_title(d.get("title"), act_name):
                return remember(act_name, d["tid"])

    for query in [f"{act_name} doctypes:union-laws", f'"{core}" doctypes:union-laws']:
        for page in range(SEARCH_PAGES):
            res = ik_post(f"/search/?formInput={requests.utils.quote(query)}&pagenum={page}", "search")
            docs = res.get("docs", [])
            for d in docs:
                if title_matches(d.get("title"), act_name):
                    entire = follow_to_entire_act(d["tid"])
                    if entire != d["tid"]:
                        return remember(act_name, entire)
            if not docs:
                break
    return None


# ---------- Step 2: parse sections and definitions ----------
def section_nodes(s):
    """Section element plus following siblings up to the next section or a chapter/part container."""
    nodes = [s]
    for sib in s.next_siblings:
        if not isinstance(sib, Tag):
            continue
        classes = sib.get("class") or []
        if ("akn-section" in classes
                or any(c in classes for c in CONTAINER_CLASSES)
                or sib.select_one("section.akn-section")):
            break
        nodes.append(sib)
    return nodes


def collect_clauses(nodes, kind):
    clauses = []
    for n in nodes:
        if kind in (n.get("class") or []):
            clauses.append(n)
        else:
            clauses.extend(n.select(f"section.{kind}"))
    return clauses


def extract_terms(clause_text):
    """Find defined terms in one clause using all three drafting styles."""
    content = LABEL_RE.sub("", clause_text).lstrip("[ ").strip()
    found = {a or b for a, b in QUOTED_RE.findall(content)}

    end = CLAUSE_END_RE.search(content)
    if end:
        term = PREPOSITION_RE.sub("", end.group(1)).strip()
        if term:
            found.add(term)

    if not found:
        start = START_TERM_RE.match(content)
        if start and DEF_VERB_RE.search(content[: len(start.group(0)) + 150]):
            found.add(start.group(1))

    return {t.strip() for t in found if is_valid_term(t)}


def terms_from_title(title):
    """IPC-style: the section title IS the term."""
    quoted = [a or b for a, b in QUOTED_RE.findall(title)]
    candidates = quoted or [title]
    out = []
    for c in candidates:
        c = re.sub(r"^(?:a|an|the)\s+", "", c.strip(" .—-–\"'“”‘’"), flags=re.IGNORECASE)
        if is_valid_term(c):
            out.append(c)
    return out


def in_range(num, rng):
    base = re.match(r"\d+", num)
    return bool(base) and rng[0] <= int(base.group(0)) <= rng[1]


def parse_act(html, def_range=None):
    soup = BeautifulSoup(html, "html.parser")
    for remark in soup.select(".akn-remark"):
        remark.decompose()

    sections, terms, seen = [], [], set()
    for s in soup.select("section.akn-section"):
        h3 = s.find("h3")
        heading = h3.get_text(" ", strip=True) if h3 else ""
        m = HEADING_RE.match(heading)
        if m:
            num, title = m.group(1), m.group(2)
        else:
            num, title = (s.get("id") or "").replace("section_", ""), heading
        title = title.strip("[]—-– .")
        if not num or num in seen:
            continue
        seen.add(num)

        nodes = section_nodes(s)
        text = " ".join(n.get_text(" ", strip=True) for n in nodes).strip()
        sections.append({"section_number": num, "section_title": title, "text": text})

        if def_range and in_range(num, def_range):
            for term in terms_from_title(title):
                terms.append({"term": term, "context": text, "section_number": num})
            continue

        if "definition" in title.lower() or "interpretation" in title.lower():
            clauses = (collect_clauses(nodes, "akn-subsection")
                       or collect_clauses(nodes, "akn-paragraph")
                       or nodes)
            for clause in clauses:
                clause_text = clause.get_text(" ", strip=True)
                for term in extract_terms(clause_text):
                    terms.append({"term": term, "context": clause_text, "section_number": num})

    return sections, terms


# ---------- Step 3: save to MongoDB ----------
def save(db, act, sections, terms):
    now = datetime.now(timezone.utc)
    year = re.search(r"(\d{4})\s*$", act["config_name"])
    repealed_by = REPEALED.get(act["config_name"])

    section_ops = [
        UpdateOne(
            {"act_id": act["act_id"], "section_number": s["section_number"]},
            {
                "$set": {
                    "act_name": act["name"],
                    "act_year": int(year.group(1)) if year else None,
                    "section_title": s["section_title"],
                    "text": s["text"],
                    "content_hash": hashlib.sha256(s["text"].encode()).hexdigest(),
                    "source": "indian_kanoon",
                    "ik_doc_id": act["tid"],
                    "source_url": f"https://indiankanoon.org/doc/{act['tid']}/",
                    "retrieved_on": now,
                    "in_force": repealed_by is None,
                    "replaced_by_act": repealed_by,
                },
                "$setOnInsert": {"added_on": now, "replaced_by": None},
            },
            upsert=True,
        )
        for s in sections
    ]
    if section_ops:
        db.acts_and_laws.bulk_write(section_ops, ordered=False)

    term_ops = []
    for t in terms:
        norm = normalize(t["term"])
        if len(norm) < 2:
            continue
        term_ops.append(UpdateOne(
            {"term_normalized": norm},
            {
                "$setOnInsert": {
                    "term": t["term"],
                    "lemma": norm,
                    "variants": [],
                    "context": t["context"][:1000],
                    "translations": {},
                    "status": "approved",
                    "source": "indian_kanoon",
                    "added_on": now,
                },
                "$addToSet": {"definitions": {
                    "act_id": act["act_id"],
                    "act_name": act["name"],
                    "section_number": t["section_number"],
                    "in_force": repealed_by is None,
                }},
                "$set": {"updated_on": now},
            },
            upsert=True,
        ))

    changed = 0
    if term_ops:
        res = db.legal_terms.bulk_write(term_ops, ordered=False)
        changed = res.upserted_count + res.modified_count
    return changed


# ---------- Main ----------
def main():
    client = MongoClient(os.environ["MONGO_URI"])
    db = client[os.environ["MONGO_DB"]]            # required
    total_changed = 0
    report = []

    try:
        for name in ACTS:
            label = f"{name}  [REPEALED → {REPEALED[name]}]" if name in REPEALED else name
            print(f"\n{label}")
            entry = {"act": name, "status": "", "sections": 0, "terms": 0, "sample": []}
            try:
                tid = find_entire_act(name)
                if not tid:
                    entry["status"] = "NOT FOUND"
                    print("  NOT FOUND: add its ID to KNOWN_TIDS (indiankanoon.org → Laws → 'Union of India - Act')")
                    continue
                doc = ik_post(f"/doc/{tid}/", "doc")
                sections, terms = parse_act(doc.get("doc", ""), DEFINITION_RANGES.get(name))
                if not sections:
                    entry["status"] = "0 SECTIONS"
                    print(f"  0 SECTIONS: check indiankanoon.org/doc/{tid}/")
                    continue
                act = {"name": clean(doc.get("title")) or name, "tid": tid,
                       "act_id": f"ik:{tid}", "config_name": name}
                changed = save(db, act, sections, terms)
                total_changed += changed
                unique_terms = sorted({t["term"] for t in terms})
                entry.update(sections=len(sections), terms=len(unique_terms), sample=unique_terms[:15],
                             status="LOW TERMS" if len(unique_terms) < LOW_TERMS else "OK")
                print(f"  {len(sections)} sections, {len(unique_terms)} terms ({changed} added/updated)")
            except BudgetReached:
                raise
            except Exception as e:
                entry["status"] = f"ERROR: {e}"
                print(f"  ERROR: {e}")
            finally:
                report.append(entry)
    except BudgetReached as e:
        print(f"\nStopped: {e}")
    finally:
        if total_changed:
            db.kb_meta.update_one(
                {"_id": "kb_version"},
                {"$inc": {"version": 1}, "$set": {"updated_on": datetime.now(timezone.utc)}},
                upsert=True,
            )
        total_terms = db.legal_terms.count_documents({})
        total_sections = db.acts_and_laws.count_documents({})
        REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        print("\n" + "=" * 70 + "\nSUMMARY\n" + "=" * 70)
        for e in report:
            print(f"  {e['status']:<12} {e['act'][:52]:<52} {e['sections']:>4} sec  {e['terms']:>3} terms")
        flagged = [e for e in report if e["status"] != "OK"]
        print(f"\nActs processed: {len(report)}  |  needing attention: {len(flagged)}")
        print(f"Database totals: {total_sections} sections, {total_terms} unique terms")
        print(f"Spent this run: ₹{spent:.2f}  |  Report: {REPORT}")
        client.close()


if __name__ == "__main__":
    main()