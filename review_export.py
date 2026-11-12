#!/usr/bin/env python3
"""저장된 번역 콘텐츠(오늘의 타로·생일수·카드도감·도감 UI)를 외부 검수용 파일로 내보낸다.

사용법:
    python3 review_export.py en            # output/review/en/ 에 생성
    python3 review_export.py ja --max-chars 40000

생성물 (언어당):
    00_auto_checks.md          기계적 검사 결과 (한글 혼입, 누락, 길이 이상, 마크다운 등)
    daily_01.md, ...           오늘의 타로   (ko 원문 | 번역문)
    birth_01.md, ...           나의 생일수
    cards_01.md, ...           카드도감
    ui.md                      도감 UI 문구
각 파일 맨 위에 검수 프롬프트가 들어 있어 파일 하나만 ChatGPT 에 올려도 된다.
검수 결과(JSON)는 review_apply.py 로 반영한다(별도).
"""
import argparse
import json
import os
import re
import statistics
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")

LANG_NAMES = {
    "en": "English", "ja": "Japanese", "es": "Spanish", "fr": "French", "de": "German",
    "pt": "Portuguese (Brazilian)", "th": "Thai", "ru": "Russian", "zh": "Chinese (Simplified)",
    "it": "Italian", "id": "Indonesian", "vi": "Vietnamese", "tr": "Turkish", "pl": "Polish",
}

DAILY_FIELDS = ["headline", "message", "action", "watch"]
BIRTH_TEXT = ["tagline", "personality", "life_lesson", "relationships", "soul_note", "year_theme"]
BIRTH_LISTS = ["keywords", "strengths", "shadow"]
CARD_FIELDS = ["meaning", "sym_person", "sym_symbol", "sym_bg", "upright", "reversed", "love", "career", "money", "advice"]
SYM_KO = {"sym_person": "핵심인물", "sym_symbol": "주요상징", "sym_bg": "배경"}

PROMPT = """# TRANSLATION REVIEW — {what} ({lang_name})

You are a native {lang_name} editor with solid knowledge of tarot (Rider-Waite-Smith tradition).
Below are entries from a Korean tarot website ("Ultra Tarot"). Each entry shows the Korean SOURCE
and the {lang_name} TRANSLATION that is currently live on the site. Review ONLY the translation.

## What to check
1. Mistranslation, omitted meaning, or added meaning that is not in the Korean source.
2. Unnatural, stiff, or machine-sounding {lang_name}; grammar and spelling errors.
3. Tarot terminology: use the standard {lang_name} terms for card names and suits
   (Wands / Cups / Swords / Pentacles) and keep them consistent across entries.
   The Korean source sometimes names minor cards inconsistently (e.g. "컵의 2" vs "두 개의 컵"); that is
   a source quirk — do NOT report it, just make sure the translation uses the standard card name.
4. Tone: warm, reflective, non-fatalistic. Flag any wording that sounds like a hard prediction or gives
   definite medical, legal, or investment advice.
5. Gender neutrality: the reader's gender is unknown. Flag gendered wording about the reader
   (in languages that mark gender on verbs/adjectives, the neutral or inclusive form should be used).
6. Leftover Korean characters, markdown symbols (** ##), or broken sentences.

## What NOT to do
- Do not rewrite sentences just because you would phrase them differently. Report only real problems.
- Do not change the meaning, add new ideas, or make the text longer without a reason.
- Do not report an entry that is fine.

## Output format (strict)
Reply with ONLY one JSON array, no commentary before or after, no code fence needed.
Each problem is one object:
{{"id": "<entry id from the heading>", "field": "<field name>", "severity": "high|medium|low",
  "type": "mistranslation|omission|addition|unnatural|terminology|grammar|tone|gender|other",
  "problem": "<one short sentence, in English>",
  "original": "<exact excerpt copied from the CURRENT translation>",
  "suggestion": "<replacement for exactly that excerpt>"}}
- severity: high = meaning is wrong or misleading; medium = clearly unnatural or wrong terminology;
  low = minor polish.
- "original" must be copied character-for-character so it can be found and replaced automatically.
  Keep it as short as possible while staying unique inside that field.
- If there are no problems, reply with [].
- If your answer would be cut off, finish the current object, close the array, and I will reply
  "continue"; then resume after the last entry you reported.

---

"""

HANGUL = re.compile(r"[ㄱ-ㅎㅏ-ㅣ가-힣]")


def read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ── 항목 수집: [(id, 표시이름, [(field, ko, tr), ...]), ...] ──────────────────────────
def collect_daily(lang):
    ko = read(os.path.join(OUT, "daily_cards_ko.json"), {})
    tr = read(os.path.join(OUT, f"daily_cards_{lang}.json"), {})
    items = []
    deck = collect_deck()
    for slug, ko_card in ko.get("cards", {}).items():
        tc = tr.get("cards", {}).get(slug, {})
        fields = [(f, ko_card.get(f), tc.get(f)) for f in DAILY_FIELDS]
        items.append((slug, deck.get(slug, (slug, slug))[0] + " / " + deck.get(slug, (slug, slug))[1], fields))
    meta_ko, meta_tr = ko.get("_meta", {}), tr.get("_meta", {})
    meta = [("title", meta_ko.get("title"), meta_tr.get("title"))]
    for k in DAILY_FIELDS:
        meta.append((f"label_{k}", meta_ko.get("labels", {}).get(k), meta_tr.get("labels", {}).get(k)))
    items.insert(0, ("_meta", "section titles", meta))
    return items


def collect_birth(lang):
    ko = read(os.path.join(OUT, "birth_cards_ko.json"), {})
    tr = read(os.path.join(OUT, f"birth_cards_{lang}.json"), {})
    items = []
    mk, mt = ko.get("_meta", {}), tr.get("_meta", {})
    meta = [(k, mk.get(k), mt.get(k)) for k in ("title", "disclaimer", "deck_note")]
    for i, line in enumerate(mk.get("calculation", [])):
        meta.append((f"calculation[{i}]", line, (mt.get("calculation") or [None] * 9)[i] if i < len(mt.get("calculation") or []) else None))
    # 한국어 라벨은 사이트가 실제로 쓰는 값(app.py render_birth_card_page). 없는 키는 원문 없이 번역만 보여준다.
    ko_labels = {"personality": "성격·성향", "strengths": "강점", "shadow": "약점·그림자", "life_lesson": "인생 과제",
                 "relationships": "관계 스타일", "career": "직업 성향", "soul_note": "내면의 의미",
                 "keywords": "키워드", "year_theme": "올해의 카드로 나타날 때"}
    for k, v in (mt.get("labels") or {}).items():
        meta.append((f"label_{k}", ko_labels.get(k, ""), v))
    items.append(("_meta", "guide intro and labels", meta))
    for card in ko.get("cards", []):
        t = tr.get("cards", {}).get(card["slug"], {})
        fields = []
        for f in BIRTH_TEXT:
            fields.append((f, card.get(f), t.get(f)))
        for f in BIRTH_LISTS:
            for i, v in enumerate(card.get(f) or []):
                tv = (t.get(f) or [])
                fields.append((f"{f}[{i}]", v, tv[i] if i < len(tv) else None))
        ck, ct = card.get("career") or {}, t.get("career") or {}
        fields.append(("career.style", ck.get("style"), ct.get("style")))
        for i, v in enumerate(ck.get("fields") or []):
            tv = ct.get("fields") or []
            fields.append((f"career.fields[{i}]", v, tv[i] if i < len(tv) else None))
        fields.append(("career.caution", ck.get("caution"), ct.get("caution")))
        fields = [x for x in fields if x[1] or x[2]]
        items.append((card["slug"], f"{card['id']}. {card['name_ko']} / {t.get('name', card['name_en'])}", fields))
    return items


_DECK = None


def collect_deck():
    """slug → (name_ko, name_en) (이미지가 있는 78장만, app.load_deck 과 동일 기준)."""
    global _DECK
    if _DECK is None:
        _DECK = {}
        for c in read(os.path.join(OUT, "cards.json"), []):
            if c.get("image_file"):
                slug = re.sub(r"[^a-z0-9]+", "-", (c.get("name_en") or "").lower()).strip("-")
                _DECK[slug] = (c["name_ko"], c["name_en"])
    return _DECK


def collect_cards(lang):
    sys.path.insert(0, BASE)
    from tarot_i18n import minor_name
    tr = read(os.path.join(OUT, "i18n", f"cards_{lang}.json"), {})
    items = []
    for c in read(os.path.join(OUT, "cards.json"), []):
        if not c.get("image_file"):
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", (c.get("name_en") or "").lower()).strip("-")
        t = tr.get(slug, {})
        seo, sym = c.get("seo") or {}, c.get("symbols") or {}
        shown = minor_name(lang, slug) or t.get("name")      # 사이트가 실제로 보여주는 이름
        fields = [("name(shown on site)", c["name_ko"], shown)]
        for f in CARD_FIELDS:
            if f in SYM_KO:
                src = sym.get(SYM_KO[f])
            elif f == "meaning":
                src = c.get("meaning")
            else:
                src = seo.get(f)
            fields.append((f, src, t.get(f)))
        fields = [x for x in fields if x[1] or x[2]]
        items.append((slug, f"{c['name_ko']} / {c['name_en']}", fields))
    return items


def collect_ui(lang):
    sys.path.insert(0, BASE)
    from tarot_i18n import UI_KO, ui_overrides
    tr = dict(read(os.path.join(OUT, "i18n", f"ui_{lang}.json"), {}))
    tr.update(ui_overrides(lang))
    fields = [(k, v, tr.get(k)) for k, v in UI_KO.items() if isinstance(v, str)]
    return [("ui", "card encyclopedia page labels", fields)]


# ── 자동 검사 ────────────────────────────────────────────────────────────────
def auto_checks(sections, lang):
    rows = []                      # (severity, section, id, field, message)
    ratios = {}
    for sec, items in sections.items():
        for id_, name, fields in items:
            for f, ko, tr in fields:
                if ko and not clean(tr):
                    rows.append(("high", sec, id_, f, "번역 누락(빈 값)"))
                    continue
                if not tr:
                    continue
                t = str(tr)
                if lang != "ko" and HANGUL.search(t):
                    rows.append(("high", sec, id_, f, "한글 혼입: " + "".join(HANGUL.findall(t))[:20]))
                if "**" in t or "##" in t or "`" in t:
                    rows.append(("high", sec, id_, f, "마크다운 기호 포함"))
                if re.search(r"\s{2,}", t.strip()) and "\n" not in t:
                    rows.append(("low", sec, id_, f, "연속 공백"))
                if t != t.strip():
                    rows.append(("low", sec, id_, f, "앞뒤 공백"))
                if re.search(r"\b(\w+)\s+\1\b", t, re.I) and lang in ("en", "es", "fr", "de", "pt", "it", "pl", "tr", "id", "vi"):
                    m = re.search(r"\b(\w+)\s+\1\b", t, re.I)
                    if m and len(m.group(1)) > 2 and m.group(1).lower() not in ("had", "that"):
                        rows.append(("medium", sec, id_, f, f"단어 중복: '{m.group(0)}'"))
                if len(t) > 80 and t.count("(") != t.count(")"):
                    rows.append(("medium", sec, id_, f, "괄호 짝 불일치"))
                if ko and len(clean(ko)) >= 30:
                    ratios.setdefault((sec, f.split("[")[0]), []).append((len(clean(t)) / len(clean(ko)), id_, f))
    for (sec, base), vals in ratios.items():
        if len(vals) < 5:
            continue
        med = statistics.median(r for r, _, _ in vals)
        for r, id_, f in vals:
            if r < med * 0.5 or r > med * 1.8:
                rows.append(("medium", sec, id_, f, f"길이 비율 이상: 원문 대비 {r:.2f} (같은 항목 중앙값 {med:.2f})"))
    order = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda r: (order[r[0]], r[1], r[2], r[3]))
    return rows


def write_checks(path, rows, lang, counts):
    lines = [f"# 자동 검사 결과 ({lang})", "", "검수 대상 항목 수: " + ", ".join(f"{k} {v}건" for k, v in counts.items()),
             f"발견: 총 {len(rows)}건 (high {sum(r[0]=='high' for r in rows)} / medium {sum(r[0]=='medium' for r in rows)} / low {sum(r[0]=='low' for r in rows)})", ""]
    if not rows:
        lines.append("문제 없음.")
    else:
        lines += ["| 심각도 | 콘텐츠 | id | 필드 | 내용 |", "|---|---|---|---|---|"]
        for sev, sec, id_, f, msg in rows:
            lines.append(f"| {sev} | {sec} | {id_} | {f} | {msg.replace('|', '/')} |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ── 마크다운 출력 ────────────────────────────────────────────────────────────
def render_entry(id_, name, fields, lang):
    out = [f"## [{id_}] {name}", ""]
    for f, ko, tr in fields:
        out.append(f"**{f}**")
        out.append(f"- KO: {clean(ko) or '(none)'}")
        out.append(f"- {lang.upper()}: {clean(tr) or '(MISSING)'}")
        out.append("")
    return "\n".join(out)


def write_parts(outdir, prefix, what, items, lang, max_chars):
    prompt = PROMPT.format(what=what, lang_name=LANG_NAMES[lang])
    blocks = [render_entry(i, n, f, lang) for i, n, f in items]
    parts, cur, size = [], [], 0
    for b in blocks:
        if cur and size + len(b) > max_chars:
            parts.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += len(b)
    if cur:
        parts.append(cur)
    names = []
    for n, part in enumerate(parts, 1):
        name = f"{prefix}_{n:02d}.md" if len(parts) > 1 else f"{prefix}.md"
        header = prompt.replace("— " + what, f"— {what} (part {n}/{len(parts)})")
        with open(os.path.join(outdir, name), "w", encoding="utf-8") as fh:
            fh.write(header + "\n".join(part))
        names.append((name, len(part), sum(len(x) for x in part)))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lang", choices=sorted(LANG_NAMES))
    ap.add_argument("--max-chars", type=int, default=45000, help="파일 하나의 본문 최대 글자 수")
    a = ap.parse_args()
    lang = a.lang
    outdir = os.path.join(OUT, "review", lang)
    os.makedirs(outdir, exist_ok=True)
    for old in os.listdir(outdir):
        if old.endswith(".md"):
            os.remove(os.path.join(outdir, old))

    sections = {
        "daily": collect_daily(lang),
        "birth": collect_birth(lang),
        "cards": collect_cards(lang),
        "ui": collect_ui(lang),
    }
    meta = {"daily": "Daily Tarot readings", "birth": "Birth Card guide", "cards": "Card encyclopedia", "ui": "Encyclopedia UI labels"}
    written = []
    for key, items in sections.items():
        written += write_parts(outdir, key, meta[key], items, lang, a.max_chars)
    rows = auto_checks(sections, lang)
    counts = {k: len(v) for k, v in sections.items()}
    write_checks(os.path.join(outdir, "00_auto_checks.md"), rows, lang, counts)
    print(f"[{lang}] output/review/{lang}/")
    for name, n, size in written:
        print(f"  {name:14s} {n:3d} entries  {size/1000:5.1f}K chars")
    print(f"  00_auto_checks.md  {len(rows)} findings")


if __name__ == "__main__":
    main()
