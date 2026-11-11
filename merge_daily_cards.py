"""
오늘의 타로(카드 1장) 저장형 해설 병합 도구 — API 호출 없음

결과: output/daily_cards_{lang}.json   (한국어는 lang=ko)
카드 slug 는 app.py load_deck() 기준(78장).

사용법
    python3 merge_daily_cards.py --status
    python3 merge_daily_cards.py ko --merge < part.txt
    python3 merge_daily_cards.py ko --md        # 검수용 output/daily_cards_ko.md 생성

입력 형식: '=== slug ===' 로 카드 시작, 항목은 ###키### 구분자.
    headline, message, action, watch  (모두 필수)
    '=== _meta ===' 블록(번역 시): title, label_headline, label_message, label_action, label_watch
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "output")
FIELDS = ["headline", "message", "action", "watch"]
LABELS_KO = {"headline": "오늘의 한 줄", "message": "오늘의 메시지", "action": "오늘 해볼 일", "watch": "오늘 살펴볼 점"}
BANNED_KO = ["역방향", "정방향이라면", "**", "##"]


def deck_slugs():
    import app  # noqa: WPS433
    return [c["slug"] for c in app.load_deck()], {c["slug"]: c["name_ko"] for c in app.load_deck()}


def load(path, default=None):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def parse(body):
    parts = re.split(r"^###\s*([a-z_]+)\s*###\s*$", body, flags=re.M)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def path_for(lang):
    return os.path.join(OUT, "daily_cards_%s.json" % lang)


def merge(lang, text):
    slugs, _ = deck_slugs()
    data = load(path_for(lang), {"lang": lang, "_meta": None, "cards": {}})
    chunks = re.split(r"^===\s*([a-z0-9_\-]+)\s*===\s*$", text, flags=re.M)
    ok, errs = [], []
    for i in range(1, len(chunks) - 1, 2):
        slug, body = chunks[i], chunks[i + 1]
        try:
            b = parse(body)
            if slug == "_meta":
                need = ["title"] + ["label_" + k for k in FIELDS]
                miss = [k for k in need if not b.get(k)]
                if miss:
                    raise ValueError("누락: %s" % miss)
                data["_meta"] = {"title": b["title"], "labels": {k: b["label_" + k] for k in FIELDS}}
                ok.append(slug)
                continue
            if slug not in slugs:
                raise ValueError("알 수 없는 slug")
            miss = [k for k in FIELDS if not b.get(k)]
            if miss:
                raise ValueError("누락: %s" % miss)
            for k in FIELDS:
                if "\n" in b[k]:
                    raise ValueError("%s 는 한 문단이어야 함" % k)
                if lang == "ko":
                    for bad in BANNED_KO:
                        if bad in b[k]:
                            raise ValueError("%s 에 금지 표현 '%s'" % (k, bad))
            for k in FIELDS:
                if "**" in b[k] or "##" in b[k]:
                    raise ValueError("%s 에 마크다운 기호" % k)
                if lang != "ko" and re.search("[가-힣]", b[k]):
                    raise ValueError("%s 에 한글이 섞여 있음" % k)
            limit = 60 if lang == "ko" else 110
            if len(b["headline"]) > limit:
                raise ValueError("headline 이 너무 김(%d자)" % len(b["headline"]))
            data["cards"][slug] = {k: b[k] for k in FIELDS}
            ok.append(slug)
        except Exception as e:  # noqa: BLE001
            errs.append((slug, str(e)))
    data["cards"] = {s: data["cards"][s] for s in slugs if s in data["cards"]}
    data["lang"] = lang
    tmp = path_for(lang) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path_for(lang))
    print("# 병합 %d 성공 / %d 실패 → %s 누적 카드 %d/%d" % (len(ok), len(errs), lang, len(data["cards"]), len(slugs)))
    for s, e in errs:
        print("#   ✗ %s: %s" % (s, e))
    return len(errs)


def status():
    slugs, _ = deck_slugs()
    for f in sorted(os.listdir(OUT)):
        m = re.match(r"daily_cards_([a-z]+)\.json$", f)
        if m:
            d = load(os.path.join(OUT, f))
            n = len(d.get("cards", {}))
            print("  %s: %2d/%d %s" % (m.group(1), n, len(slugs), "✅" if n >= len(slugs) else ""))
    missing = [s for s in slugs if s not in (load(path_for("ko"), {"cards": {}})["cards"])]
    if missing:
        print("  ko 누락:", ", ".join(missing))


def md(lang):
    slugs, names = deck_slugs()
    d = load(path_for(lang))
    lines = ["# 오늘의 타로 해설 (%s)\n" % lang]
    for s in slugs:
        c = d["cards"].get(s)
        if not c:
            continue
        lines.append("## %s (%s)\n" % (names[s], s))
        for k in FIELDS:
            lines.append("- **%s**: %s" % (LABELS_KO[k], c[k]))
        lines.append("")
    p = os.path.join(OUT, "daily_cards_%s.md" % lang)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("작성:", p)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--status":
        status()
    elif len(args) >= 2 and args[1] == "--merge":
        sys.exit(1 if merge(args[0], sys.stdin.read()) else 0)
    elif len(args) >= 2 and args[1] == "--md":
        md(args[0])
    else:
        print(__doc__)
