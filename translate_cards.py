"""
카드 도감 다국어 번역 스크립트

한국어 원본(output/cards.json)을 14개 언어로 번역해 output/i18n/ 에 저장한다.
  - output/i18n/ui_{lang}.json     : 도감 페이지 UI 문구(제목, 버튼, 메타 등)
  - output/i18n/cards_{lang}.json  : {slug: {name, meaning, sym_*, upright, ...}}

특징
  - 이미 번역된 항목은 건너뛰므로 중단 후 재실행해도 안전 (--force 로 재생성)
  - 병렬 호출(--workers), 실패 시 재시도, 토큰 사용량 집계

사용법
    python3 translate_cards.py --langs en ja --limit 2     # 파일럿
    python3 translate_cards.py                              # 전부
    python3 translate_cards.py --ui-only                    # UI 문구만
"""
import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

BASE = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(BASE, "output", "cards.json")
OUTDIR = os.path.join(BASE, "output", "i18n")
MODEL = os.environ.get("TRANSLATE_MODEL", "claude-sonnet-5")

from tarot_i18n import TRANSLATE_LANGS as LANGS, LANG_NAMES, UI_KO, suit_glossary_line  # noqa: E402

CARD_FIELDS = ["name", "meaning", "sym_person", "sym_symbol", "sym_bg",
               "upright", "reversed", "love", "career", "money", "advice"]
REQUIRED = ["name", "meaning", "upright", "reversed", "love", "career", "money", "advice"]

UI_PROMPT = """아래는 타로 카드 도감 웹페이지의 UI 문구(한국어)입니다.
각 항목을 {lang}로 자연스럽게 번역하세요.

규칙:
- {{n}}, {{suit}}, {{name}}, {{name_en}}, {{brand}} 같은 중괄호 자리표시자는 절대 번역하거나 바꾸지 말고 그대로 두세요.
- 타로 용어는 해당 언어에서 라이더-웨이트-스미스 덱에 통용되는 표준 표기를 쓰세요
  (컵/완드/소드/펜타클, 메이저 아르카나 등).
- "{{suit}} 수트"는 해당 언어의 자연스러운 표현으로 옮기세요 (예: 영어 "Suit of {{suit}}").
- 화살표(→, ←)와 줄임표는 유지하세요.
- 번역 결과만 출력하고 설명은 붙이지 마세요.

출력 형식 (키 이름은 그대로):
###키###
번역문

번역할 항목:
{items}"""

CARD_PROMPT = """당신은 타로 서적 전문 번역가입니다. 아래 한국어 타로 카드 해설을 {lang}로 번역하세요.

카드: {name_ko} ({name_en})

규칙:
- 독자가 모국어 화자라고 생각하고 자연스럽게 번역하세요. 직역투를 피하세요.
- 원문의 내용을 더하거나 빼지 마세요. 단정적 예언을 피하는 원문의 어조를 유지하세요.
- name 은 이 카드의 {lang} 표준 명칭입니다 (라이더-웨이트-스미스 덱 기준, 예: The Magician → 해당 언어의 통용 표기).
- 마크다운 기호(**, #, - 등)를 쓰지 말고 평문 문단으로 쓰세요.
- 번역문만 출력하고 설명은 붙이지 마세요. 아래 형식을 그대로 지키세요.
- 타로 수트 용어는 반드시 다음 표기로 통일하세요(본문에서 '컵·완드·소드·펜타클'을 언급할 때 항상 이 표기만 사용): {glossary}
- 구분자(###키###)의 키는 영어 그대로 쓰고 절대 번역하거나 다른 말로 바꾸지 마세요.
- ###name### 구분자 바로 아래 줄에 번역된 카드 이름만 쓰세요. 구분자 안에 카드 이름을 넣지 마세요.

출력 형식:
###name###
###meaning###
###sym_person###
###sym_symbol###
###sym_bg###
###upright###
###reversed###
###love###
###career###
###money###
###advice###
(각 구분자 아래에 번역문. 원문에 없는 sym_* 항목은 구분자만 쓰고 비워 두세요)

===== 원문 =====
###name###
{name_ko}
###meaning###
{meaning}
###sym_person###
{sym_person}
###sym_symbol###
{sym_symbol}
###sym_bg###
{sym_bg}
###upright###
{upright}
###reversed###
{reversed}
###love###
{love}
###career###
{career}
###money###
{money}
###advice###
{advice}"""


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def parse_blocks(text):
    parts = re.split(r"###\s*([^#\n]+?)\s*###", text)
    out, stray = {}, []
    for i in range(1, len(parts) - 1, 2):
        key, val = parts[i].strip(), parts[i + 1].strip()
        if key in CARD_FIELDS or key in UI_KO:
            out[key] = val
        elif not val:
            stray.append(key)   # 구분자 안에 이름을 넣어버린 경우(예: ###The Fool###)
    # name 이 비어 있으면, 구분자 안에 들어간 이름을 구제한다
    if "name" in CARD_FIELDS and not out.get("name") and stray:
        out["name"] = stray[0]
    return out


def text_of(resp):
    # 확장 사고(thinking) 블록이 앞설 수 있으므로 text 블록만 합친다
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


# ── 번역 품질 검증: 해당 언어에 있을 수 없는 문자가 섞였는지 검사 ──
# (저자원 언어에서 모델이 중국어/한글 글자를 섞어 쓰는 오류가 실제로 관찰됨)
_SCRIPTS = {
    "hangul": [(0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F)],
    "kana":   [(0x3040, 0x30FF)],
    "han":    [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)],
    "cyril":  [(0x0400, 0x04FF)],
    "thai":   [(0x0E00, 0x0E7F)],
}
_ALLOWED = {"ja": {"kana", "han"}, "zh": {"han"}, "th": {"thai"}, "ru": {"cyril"}}


def _script_of(ch):
    cp = ord(ch)
    for name, ranges in _SCRIPTS.items():
        if any(a <= cp <= b for a, b in ranges):
            return name
    return None


def check_scripts(lang, values):
    allowed = _ALLOWED.get(lang, set())
    for v in values:
        for ch in v or "":
            sc = _script_of(ch)
            if sc and sc not in allowed:
                raise ValueError("다른 문자 혼입(%s) '%s' ... %r" % (sc, ch, (v or "")[:40]))


class Usage:
    def __init__(self):
        self.i = self.o = self.calls = 0
        self.lock = threading.Lock()

    def add(self, resp):
        u = getattr(resp, "usage", None)
        with self.lock:
            self.calls += 1
            if u:
                self.i += getattr(u, "input_tokens", 0) or 0
                self.o += getattr(u, "output_tokens", 0) or 0


USAGE = Usage()


def call(client, prompt, max_tokens):
    resp = client.messages.create(model=MODEL, max_tokens=max_tokens,
                                  messages=[{"role": "user", "content": prompt}])
    USAGE.add(resp)
    return text_of(resp)


def translate_ui(client, lang):
    items = "\n".join("###%s###\n%s" % (k, v) for k, v in UI_KO.items())
    base = UI_PROMPT.format(lang=LANG_NAMES[lang], items=items)
    last = None
    for attempt in range(4):
        prompt = base if attempt == 0 else base + (
            "\n\n[주의] 이전 시도에서 오류가 있었습니다(%s). %s 외의 언어나 문자를 섞지 말고 다시 작성하세요." % (last, LANG_NAMES[lang]))
        try:
            blocks = parse_blocks(call(client, prompt, 3000))
            missing = [k for k in UI_KO if not blocks.get(k)]
            if missing:
                raise ValueError("누락: %s" % missing)
            for k, v in UI_KO.items():
                for ph in re.findall(r"\{[a-z_]+\}", v):
                    if ph not in blocks[k]:
                        raise ValueError("%s: 자리표시자 %s 소실" % (k, ph))
            check_scripts(lang, [blocks[k] for k in UI_KO])
            return {k: blocks[k] for k in UI_KO}
        except Exception as e:
            last = str(e)[:80]
            time.sleep(1.5)
    raise ValueError(last)


def translate_card(client, lang, card):
    seo = card.get("seo") or {}
    sym = card.get("symbols") or {}
    base = CARD_PROMPT.format(
        lang=LANG_NAMES[lang], glossary=suit_glossary_line(lang),
        name_ko=card.get("name_ko", ""), name_en=card.get("name_en", ""),
        meaning=(card.get("meaning") or "").strip(),
        sym_person=sym.get("핵심인물", ""), sym_symbol=sym.get("주요상징", ""), sym_bg=sym.get("배경", ""),
        upright=seo.get("upright", ""), reversed=seo.get("reversed", ""),
        love=seo.get("love", ""), career=seo.get("career", ""),
        money=seo.get("money", ""), advice=seo.get("advice", ""),
    )
    last = None
    for attempt in range(4):
        prompt = base if attempt == 0 else base + (
            "\n\n[주의] 이전 시도에서 오류가 있었습니다(%s). 형식을 지키고, %s 외의 언어나 문자(한글·한자 등)를 "
            "섞지 말고 다시 작성하세요." % (last, LANG_NAMES[lang]))
        try:
            blocks = parse_blocks(call(client, prompt, 6000))
            missing = [k for k in REQUIRED if not blocks.get(k)]
            if missing:
                raise ValueError("누락: %s" % missing)
            res = {k: blocks.get(k, "") for k in CARD_FIELDS}
            for ko_key, f in (("핵심인물", "sym_person"), ("주요상징", "sym_symbol"), ("배경", "sym_bg")):
                if not sym.get(ko_key):
                    res[f] = ""
            check_scripts(lang, res.values())
            return res
        except Exception as e:
            last = str(e)[:80]
            time.sleep(1.5)
    raise ValueError(last)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", nargs="*", default=LANGS)
    ap.add_argument("--limit", type=int, default=0, help="언어당 번역할 카드 수 (0=전부)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--ui-only", action="store_true")
    ap.add_argument("--cards-only", action="store_true")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY 가 설정되어 있지 않습니다.")
    os.makedirs(OUTDIR, exist_ok=True)
    client = anthropic.Anthropic(max_retries=5)
    langs = [l for l in args.langs if l in LANG_NAMES]
    print("모델: %s / 언어: %s" % (MODEL, " ".join(langs)))

    # 1) UI 문구
    if not args.cards_only:
        for lang in langs:
            path = os.path.join(OUTDIR, "ui_%s.json" % lang)
            if os.path.exists(path) and not args.force:
                continue
            try:
                save_json(path, translate_ui(client, lang))
                print("  UI  %s 완료" % lang)
            except Exception as e:
                print("  UI  %s 실패: %s" % (lang, e))

    if args.ui_only:
        print_usage()
        return

    # 2) 카드 본문
    with open(CARDS, encoding="utf-8") as f:
        deck = [c for c in json.load(f) if c.get("image_file") and c.get("seo")]
    if args.limit:
        deck = deck[: args.limit]

    results, locks, tasks = {}, {}, []
    for lang in langs:
        path = os.path.join(OUTDIR, "cards_%s.json" % lang)
        results[lang] = load_json(path, {})
        locks[lang] = threading.Lock()
        for c in deck:
            if args.force or slugify(c["name_en"]) not in results[lang]:
                tasks.append((lang, c))
    print("번역 대상: %d건 (언어 %d × 카드 최대 %d)" % (len(tasks), len(langs), len(deck)))

    done = fail = 0

    def work(lang, card):
        return lang, card, translate_card(client, lang, card)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, l, c): (l, c) for l, c in tasks}
        for fut in as_completed(futs):
            lang, card = futs[fut]
            name = card["name_en"]
            try:
                _, _, res = fut.result()
                with locks[lang]:
                    results[lang][slugify(name)] = res
                    save_json(os.path.join(OUTDIR, "cards_%s.json" % lang), results[lang])
                done += 1
            except Exception as e:
                fail += 1
                with open(os.path.join(OUTDIR, "errors.log"), "a", encoding="utf-8") as lf:
                    lf.write("%s\t%s\t%s\n" % (lang, name, e))
            if (done + fail) % 25 == 0:
                print("  진행 %d/%d (실패 %d)" % (done + fail, len(tasks), fail), flush=True)

    print("\n완료 %d / 실패 %d" % (done, fail))
    for lang in langs:
        print("  %s: %d/%d장" % (lang, len(results[lang]), len([c for c in deck])))
    print_usage()


def print_usage():
    print("토큰 사용량: 호출 %d회 / 입력 %d / 출력 %d" % (USAGE.calls, USAGE.i, USAGE.o))


if __name__ == "__main__":
    main()
