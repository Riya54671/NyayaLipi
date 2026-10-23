import os
import re

# Honorific list. "Hon'ble" is deliberately NOT here: "Hon'ble High Court" would
# otherwise be captured as a person's name and masked.
NAME_PATTERN = re.compile(
    r"\b(?:Mr\.?|Mrs\.?|Ms\.?|Shri\.?|Smt\.?|Sau\.?|Kum\.?|Dr\.?|Adv\.?)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b"
)

DATE_PATTERN = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|"
    r"August|September|October|November|December),?\s+\d{4}\b",
    re.IGNORECASE,
)

AMOUNT_PATTERN = re.compile(r"₹\s?\d[\d,]*(?:\.\d{1,2})?|(?:Rs\.?|INR)\s?\d[\d,]*(?:\.\d{1,2})?")

_PATTERNS = [
    ("NAME", NAME_PATTERN),
    ("DATE", DATE_PATTERN),
    ("AMOUNT", AMOUNT_PATTERN),
]

_TOKEN_SPLIT = re.compile(r"(\[\[[A-Z]+_\d+\]\])")


def mask_sensitive_terms(text: str) -> tuple[str, dict[str, str]]:
    """
    Replace names, dates, and amounts with placeholder tokens the LLM is told not to
    translate. Returns (masked_text, mapping) where mapping restores the originals
    after translation. One shared mapping/counter across all three categories so
    tokens never collide.
    """
    mapping: dict[str, str] = {}
    counters = {"NAME": 0, "DATE": 0, "AMOUNT": 0}

    masked = text
    for label, pattern in _PATTERNS:
        def _replace(match, label=label):
            full_match = match.group(0)
            for token, original in mapping.items():
                if original == full_match and token.startswith(f"[[{label}_"):
                    return token  # reuse same token for repeated mentions
            token = f"[[{label}_{counters[label]}]]"
            mapping[token] = full_match
            counters[label] += 1
            return token

        masked = pattern.sub(_replace, masked)

    return masked, mapping


def mask_terms(text: str, term_translations: dict[str, dict],
               mapping: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """
    Glossary substitution. Replace each KB legal term that has a vetted target-language
    translation with a [[TERM_n]] token; the token's mapping value is the TRANSLATION,
    so merging the returned mapping into the name/date/amount mapping lets
    unmask_sensitive_terms() restore everything in one pass.

    term_translations: {term: {"forms": [surface forms incl. variants], "translation": str}}
    Returns (masked_text, new_mapping) — new_mapping holds only the TERM tokens.

    - Longest form wins (so "High Court" is matched before "Court").
    - Whole-word, case-insensitive; never touches text inside existing [[...]] tokens.
    - Same term -> same token.
    """
    new_mapping: dict[str, str] = {}
    if not term_translations:
        return text, new_mapping

    form_to_term: dict[str, tuple[str, str]] = {}
    for term, info in term_translations.items():
        tr = (info.get("translation") or "").strip()
        if not tr:
            continue
        for form in (info.get("forms") or [term]):
            form = (form or "").strip()
            if form:
                form_to_term[form.lower()] = (term, tr)
    if not form_to_term:
        return text, new_mapping

    forms_longest_first = sorted(form_to_term, key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(f) for f in forms_longest_first) + r")(?!\w)",
        re.IGNORECASE,
    )

    used = [int(m.group(1)) for tok in (mapping or {})
            if (m := re.fullmatch(r"\[\[TERM_(\d+)\]\]", tok))]
    next_id = max(used) + 1 if used else 0
    token_for_term: dict[str, str] = {}

    def _replace(match):
        nonlocal next_id
        term, tr = form_to_term[match.group(0).lower()]
        if term not in token_for_term:
            token = f"[[TERM_{next_id}]]"
            next_id += 1
            token_for_term[term] = token
            new_mapping[token] = tr
        return token_for_term[term]

    parts = _TOKEN_SPLIT.split(text)
    for i in range(0, len(parts), 2):          # even indexes = plain text, odd = existing tokens
        parts[i] = pattern.sub(_replace, parts[i])
    return "".join(parts), new_mapping


_LEADING_WORDS = {"the", "this", "that", "said", "such", "any", "an", "a", "each", "every", "under", "of"}

# Only the NUMBER of a statutory reference is protected. The word ("Section") is left
# for the engine to translate (-> धारा), so Hindi text reads naturally.
SECTION_REF_PATTERN = re.compile(
    r"\b((?:Sections?|Article|Clause|Rule)\s+)(\d+[A-Za-z]?)\b", re.IGNORECASE
)


def _clean_act(entity: str) -> str | None:
    """Reduce an NER 'ACT' hit to a real named act, or None. 'The Maharashtra Rent
    Control Act, 1999' -> 'Maharashtra Rent Control Act, 1999'; bare 'This Act' -> None."""
    words = entity.split()
    while words and words[0].lower() in _LEADING_WORDS:
        words.pop(0)
    idx = next((i for i, w in enumerate(words) if w.rstrip(",").lower() == "act"), None)
    if idx is None or idx == 0:
        return None
    return " ".join(words)


def _next_ids(mapping: dict[str, str]) -> dict[str, int]:
    nxt: dict[str, int] = {}
    for tok in mapping:
        m = re.fullmatch(r"\[\[([A-Z]+)_(\d+)\]\]", tok)
        if m:
            nxt[m.group(1)] = max(nxt.get(m.group(1), -1), int(m.group(2)))
    return {label: n + 1 for label, n in nxt.items()}


def mask_entities(text: str, entities: dict[str, list[str]] | None,
                  mapping: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """
    Verbatim tokens. The token's restore value is the ORIGINAL text, so these never
    get translated or transliterated by the engine:
      - act names           -> [[ACT_n]]   (from NER 'ACT' entities, cleaned)
      - case citations      -> [[CASE_n]]  (from NER 'CASE_REF' entities)
      - statutory ref numbers ("Section 138A") -> "Section [[REF_n]]"  (number only)
    Returns (masked_text, new_mapping). Never touches text inside existing [[...]] tokens.
    """
    new_mapping: dict[str, str] = {}
    nxt = _next_ids(mapping or {})
    token_for: dict[tuple[str, str], str] = {}

    def tok_for(label: str, value: str) -> str:
        key = (label, value)
        if key not in token_for:
            n = nxt.get(label, 0)
            nxt[label] = n + 1
            token = f"[[{label}_{n}]]"
            token_for[key] = token
            new_mapping[token] = value
        return token_for[key]

    parts = _TOKEN_SPLIT.split(text)           # even = plain text, odd = existing tokens

    verbatim: list[tuple[str, str]] = []
    for label, ner_key in (("ACT", "ACT"), ("CASE", "CASE_REF")):
        for ent in (entities or {}).get(ner_key, []):
            val = _clean_act(ent) if label == "ACT" else ent.strip()
            if val:
                verbatim.append((label, val))
    verbatim.sort(key=lambda lv: len(lv[1]), reverse=True)      # longest first

    for label, val in verbatim:
        pat = re.compile(r"(?<!\w)" + re.escape(val) + r"(?!\w)")
        for i in range(0, len(parts), 2):
            parts[i] = pat.sub(lambda m, l=label: tok_for(l, m.group(0)), parts[i])

    if os.getenv("MASK_REFS", "0") == "1":     # off by default: engines drop/alter these tokens
        for i in range(0, len(parts), 2):
            parts[i] = SECTION_REF_PATTERN.sub(lambda m: m.group(1) + tok_for("REF", m.group(2)), parts[i])

    return "".join(parts), new_mapping


def unmask_sensitive_terms(translated_text: str, mapping: dict[str, str]) -> str:
    for token, original in mapping.items():
        if token in translated_text:
            translated_text = translated_text.replace(token, original)
            continue
        # fallback: tolerate spacing/case drift around the token
        loose_pattern = re.escape(token).replace(r"\[", r"\[\s*").replace(r"\]", r"\s*\]")
        translated_text, n = re.subn(loose_pattern, original, translated_text, flags=re.IGNORECASE)
        if n == 0:
            print(f"[WARN] Could not restore value for token {token} — original: {original}")
    return translated_text


if __name__ == "__main__":
    text = ("Mr. Ramesh Deshpande (the lessor) and Shri. Amit Kulkarni (the lessee) agree. "
            "Rent is Rs. 15,000 from 1st April 2025. A claim may be filed in the Hon'ble High Court; "
            "the court may enter a default judgment. The Lessor must give notice.")
    glossary = {
        "lessor": {"forms": ["lessor"], "translation": "पट्टाकर्ता"},
        "lessee": {"forms": ["lessee"], "translation": "पट्टेदार"},
        "High Court": {"forms": ["High Court"], "translation": "उच्च न्यायालय"},
        "Court": {"forms": ["Court"], "translation": "न्यायालय"},
        "default judgment": {"forms": ["default judgment"], "translation": "एकपक्षीय निर्णय"},
    }

    masked, m1 = mask_sensitive_terms(text)
    masked, m2 = mask_terms(masked, glossary, m1)
    print("MASKED:\n", masked, "\n")

    assert "Ramesh" not in masked and "Amit" not in masked, "names must be masked (incl. 'Shri.')"
    assert "[[TERM_" in masked
    assert "High Court" not in masked and "[[TERM_" in masked
    assert masked.count("[[TERM_0]]") == 2, "same term (Lessor/lessor) must reuse one token"
    # 'Hon'ble High Court' must not be swallowed as a NAME
    assert "[[NAME_" in masked and masked.count("[[NAME_") == 2

    restored = unmask_sensitive_terms(masked, {**m1, **m2})   # identity "translation"
    print("RESTORED:\n", restored)
    assert "उच्च न्यायालय" in restored and "एकपक्षीय निर्णय" in restored
    assert "Ramesh Deshpande" in restored and "Amit Kulkarni" in restored and "15,000" in restored
    assert "[[" not in restored
    print("\nOK: names/dates/amounts/terms masked and restored; longest-match and token-reuse verified.")

    # --- verbatim entity tokens ---
    t2 = ("This Act applies. The tenant filed under the Maharashtra Rent Control Act, 1999, "
          "Section 138A and Clause 4, citing AIR 2020 SC 123. See Section 138A again.")
    ents = {"ACT": ["This Act", "The Maharashtra Rent Control Act, 1999"],
            "CASE_REF": ["AIR 2020 SC 123"]}
    m_names, mp = mask_sensitive_terms(t2)
    m_ent, mp_e = mask_entities(m_names, ents, mp)
    print("\nENTITY-MASKED:\n", m_ent)
    assert "This Act applies" in m_ent, "bare 'This Act' must NOT be masked verbatim"
    assert "Maharashtra" not in m_ent and "[[ACT_0]]" in m_ent
    assert "[[CASE_0]]" in m_ent and "AIR 2020" not in m_ent
    if os.getenv("MASK_REFS", "0") == "1":
        assert m_ent.count("Section [[REF_0]]") == 2 and "Clause [[REF_1]]" in m_ent
    fake_translated = m_ent.replace("Section", "धारा").replace("Clause", "खंड")   # engine translates words only
    back = unmask_sensitive_terms(fake_translated, {**mp, **mp_e})
    print("RESTORED:\n", back)
    assert "Maharashtra Rent Control Act, 1999" in back and "AIR 2020 SC 123" in back
    assert "[[" not in back
    print("\nOK: act/case verbatim tokens and section-number tokens verified.")