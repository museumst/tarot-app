"""
번역 병합 도구 (API 호출 없음) — 대화 세션(플랜)에서 직접 번역할 때 사용

translate_cards.py 는 API 키로 Claude 를 호출하므로 API 크레딧이 소모된다.
이 도구는 사람이/세션의 모델이 직접 쓴 번역문을 같은 기준으로 검증하고 병합만 한다.

원본은 이미 완성된 영어판(output/i18n/cards_en.json)을 쓴다 (한국어 원본보다 읽는 분량이 적다).

사용법
    python3 merge_translations.py --status                    # 언어별 진행 현황
    python3 merge_translations.py fr --show 10                # fr 에 아직 없는 카드 10장의 영어 원문 출력
    python3 merge_translations.py fr --merge < part.txt       # 번역문 검증 후 병합
    python3 merge_translations.py fr --merge --show 10 < part.txt   # 병합 후 다음 10장 출력

번역문 입력 형식 (카드마다 '=== slug ===' 로 시작, 항목은 ###키### 구분자)
    === the-fool ===
    ###name###
    ...
    ###meaning###
    ...
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from tarot_i18n import TRANSLATE_LANGS, suit_glossary_line  # noqa: E402
import translate_cards as tc  # noqa: E402  (parse_blocks / check_scripts 재사용)

OUT = os.path.join(BASE, "output", "i18n")
SHOW_FIELDS = ["name", "meaning", "sym_person", "sym_symbol", "sym_bg",
               "upright", "reversed", "love", "career", "money", "advice"]
SYM_FIELDS = ["sym_person", "sym_symbol", "sym_bg"]


def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def deck_slugs():
    with open(tc.CARDS, encoding="utf-8") as f:
        cards = [c for c in json.load(f) if c.get("image_file") and c.get("seo")]
    return [(tc.slugify(c["name_en"]), c["name_en"]) for c in cards]


def status():
    total = len(deck_slugs())
    for lang in ["en"] + [l for l in TRANSLATE_LANGS if l != "en"]:
        n = len(load(os.path.join(OUT, "cards_%s.json" % lang), {}))
        print("  %s: %2d/%d %s" % (lang, n, total, "✅" if n >= total else ""))


def show(lang, n):
    en = load(os.path.join(OUT, "cards_en.json"), {})
    mine = load(os.path.join(OUT, "cards_%s.json" % lang), {})
    todo = [(s, ne) for s, ne in deck_slugs() if s not in mine]
    print("# %s: 남은 카드 %d장 중 %d장 표시 | 수트 용어: %s" % (lang, len(todo), min(n, len(todo)), suit_glossary_line(lang)))
    if mine:
        print("# 이미 번역된 이름(일관성 참고): " + " / ".join(v["name"] for v in list(mine.values())[-6:]))
    for slug, name_en in todo[:n]:
        t = en.get(slug)
        if not t:
            print("=== %s === (영어 원문 없음)" % slug)
            continue
        print("\n=== %s === [%s]" % (slug, name_en))
        for k in SHOW_FIELDS:
            if t.get(k):
                print("%s: %s" % (k, t[k]))


def merge(lang, text):
    en = load(os.path.join(OUT, "cards_en.json"), {})
    path = os.path.join(OUT, "cards_%s.json" % lang)
    mine = load(path, {})
    valid_slugs = {s for s, _ in deck_slugs()}
    chunks = re.split(r"^===\s*([a-z0-9\-]+)\s*===\s*$", text, flags=re.M)
    ok, errs = [], []
    for i in range(1, len(chunks) - 1, 2):
        slug, body = chunks[i], chunks[i + 1]
        try:
            if slug not in valid_slugs:
                raise ValueError("알 수 없는 slug")
            blocks = tc.parse_blocks(body)
            src = en.get(slug, {})
            missing = [k for k in tc.REQUIRED if not blocks.get(k)]
            if missing:
                raise ValueError("누락: %s" % missing)
            res = {k: blocks.get(k, "") for k in tc.CARD_FIELDS}
            for f in SYM_FIELDS:
                if src.get(f) and not res[f]:
                    raise ValueError("%s 누락" % f)
                if not src.get(f):
                    res[f] = ""
            tc.check_scripts(lang, res.values())
            # 지나치게 짧으면(번역 누락 의심) 거부: 영어 길이의 25% 미만
            for k in ("meaning", "upright", "reversed", "love", "career", "money", "advice"):
                if src.get(k) and len(res[k]) < 0.25 * len(src[k]):
                    raise ValueError("%s 가 너무 짧음(%d/%d자)" % (k, len(res[k]), len(src[k])))
            mine[slug] = res
            ok.append(slug)
        except Exception as e:
            errs.append((slug, str(e)))
    save(path, mine)
    print("# 병합 %d장 성공 / %d장 실패 → %s 누적 %d/%d" % (len(ok), len(errs), lang, len(mine), len(valid_slugs)))
    for s, e in errs:
        print("#   ✗ %s: %s" % (s, e))
    return len(errs)


def main():
    args = sys.argv[1:]
    if not args or "--status" in args:
        status()
        return
    lang = args[0]
    if lang not in TRANSLATE_LANGS:
        sys.exit("지원하지 않는 언어: %s" % lang)
    rc = 0
    if "--merge" in args:
        rc = merge(lang, sys.stdin.read())
    if "--show" in args:
        show(lang, int(args[args.index("--show") + 1]))
    sys.exit(1 if rc else 0)


if __name__ == "__main__":
    main()
