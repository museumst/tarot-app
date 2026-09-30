"""
카드 해설 보강 스크립트 (SEO 도감 페이지용)

output/cards.json 의 각 카드에 'seo' 필드를 추가한다.
 - 기존 'meaning' 필드는 건드리지 않는다 (리딩 프롬프트가 사용 중)
 - 이미 'seo'가 있는 카드는 건너뛰므로 중단 후 재실행해도 안전하다
 - 매 카드마다 저장하여 중단 대비

사용법:
    python3 enrich_cards.py --limit 2      # 샘플 2장만
    python3 enrich_cards.py                # 남은 카드 전부
    python3 enrich_cards.py --force        # 이미 보강된 것도 다시 생성
"""
import argparse
import json
import os
import re
import sys
import time

import anthropic

BASE = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(BASE, "output", "cards.json")
ERRLOG = os.path.join(BASE, "output", "enrich_errors.log")
MODEL = os.environ.get("ENRICH_MODEL", "claude-sonnet-5")

FIELDS = ["upright", "reversed", "love", "career", "money", "advice"]

PROMPT = """당신은 타로 카드 해설을 쓰는 전문 작가입니다.
아래 카드에 대한 해설을 한국어로 작성하세요.

카드 이름: {name_ko} ({name_en})
분류: {suit_label}
기존 핵심 의미: {meaning}
카드 속 상징: {symbols}

다음 6개 항목을 작성하세요.
- upright: 정방향의 의미를 깊이 있게 설명 (4~5문장)
- reversed: 역방향으로 나왔을 때의 의미 (3~4문장)
- love: 연애·인간관계 질문에서 이 카드가 나왔을 때 (3문장)
- career: 직장·진로 질문에서 이 카드가 나왔을 때 (3문장)
- money: 금전·재물 질문에서 이 카드가 나왔을 때 (3문장)
- advice: 이 카드가 건네는 조언 (3문장)

작성 규칙:
1. 반드시 당신의 표현으로 새로 쓰세요. 특정 서적이나 웹사이트의 문장을 그대로 옮기지 마세요.
2. "반드시 ~한다", "틀림없이 ~된다" 같은 단정적 예언은 피하고, 흐름과 가능성을 이야기하세요.
3. 추상적인 미사여구보다 독자가 자기 상황에 대입할 수 있는 구체적인 표현을 쓰세요.
4. 카드의 상징과 연결해 설명하면 좋습니다.
5. 각 항목은 완결된 문단으로 쓰고, 항목 제목이나 번호는 본문에 넣지 마세요.

아래 형식 그대로 응답하세요. 머리말이나 맺음말 없이 이 형식만 출력합니다.

###upright###
(내용)
###reversed###
(내용)
###love###
(내용)
###career###
(내용)
###money###
(내용)
###advice###
(내용)"""

SUITS = [("CUPS", "컵 수트"), ("WANDS", "완드 수트"),
         ("SWORDS", "소드 수트"), ("PENTACLES", "펜타클 수트")]


def suit_label(name_en):
    for key, label in SUITS:
        if key in (name_en or "").upper():
            return label
    return "메이저 아르카나"


def enrich_one(client, card):
    prompt = PROMPT.format(
        name_ko=card.get("name_ko", ""),
        name_en=card.get("name_en", ""),
        suit_label=suit_label(card.get("name_en")),
        meaning=(card.get("meaning") or "").strip(),
        symbols=json.dumps(card.get("symbols") or {}, ensure_ascii=False),
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    # 확장 사고(thinking) 블록이 앞에 올 수 있으므로 text 블록만 골라낸다
    text = "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()
    # ###필드### 구분자로 파싱 (본문에 따옴표가 있어도 안전)
    parts = re.split(r"###\s*([a-z]+)\s*###", text)
    data = {}
    for i in range(1, len(parts) - 1, 2):
        data[parts[i].strip().lower()] = parts[i + 1].strip()
    missing = [f for f in FIELDS if not (data.get(f) or "").strip()]
    if missing:
        raise ValueError("누락된 항목: %s" % missing)
    return {f: data[f].strip() for f in FIELDS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="처리할 카드 수 (0=전부)")
    ap.add_argument("--force", action="store_true", help="이미 보강된 카드도 다시 생성")
    ap.add_argument("--delay", type=float, default=0.5, help="요청 간 대기(초)")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY 가 설정되어 있지 않습니다.")

    with open(CARDS, encoding="utf-8") as f:
        cards = json.load(f)

    targets = [
        c for c in cards
        if c.get("image_file") and (args.force or not c.get("seo"))
    ]
    if args.limit:
        targets = targets[: args.limit]

    print("대상 %d장 / 전체 %d장 (모델: %s)" % (len(targets), len(cards), MODEL))
    client = anthropic.Anthropic()
    done = fail = 0

    for i, card in enumerate(targets, 1):
        name = card.get("name_ko") or card.get("name_en")
        print("  [%d/%d] %s ..." % (i, len(targets), name), end=" ", flush=True)
        try:
            card["seo"] = enrich_one(client, card)
            done += 1
            print("완료 (%d자)" % sum(len(v) for v in card["seo"].values()))
        except Exception as e:
            fail += 1
            print("실패: %s" % e)
            with open(ERRLOG, "a", encoding="utf-8") as lf:
                lf.write("%s\t%s\n" % (name, e))
        # 중단 대비 즉시 저장
        with open(CARDS, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)
        time.sleep(args.delay)

    total = sum(1 for c in cards if c.get("seo"))
    print("\n완료 %d / 실패 %d · 누적 보강된 카드: %d장" % (done, fail, total))


if __name__ == "__main__":
    main()
