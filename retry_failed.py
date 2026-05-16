#!/usr/bin/env python3
"""
실패한 항목만 재처리 스크립트
- cards: IMG_0498~0505, IMG_0764~0767
- spreads: IMG_0855~0857, IMG_0858~0859, IMG_0879~0880, IMG_0930~0936
"""

import re
import json
import time
import base64
import traceback
from pathlib import Path
import anthropic

BASE_DIR = Path(__file__).parent
CARDS_DIR = BASE_DIR / "images" / "cards"
SPREADS_DIR = BASE_DIR / "images" / "spreads"
OUTPUT_DIR = BASE_DIR / "output"
ERROR_LOG = OUTPUT_DIR / "error_log_retry.txt"
CARDS_FINAL = OUTPUT_DIR / "cards.json"
SPREADS_FINAL = OUTPUT_DIR / "spreads.json"

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-5"

# 재처리할 그룹 지정
FAILED_CARDS = [
    ["IMG_0498.JPG","IMG_0499.JPG","IMG_0500.JPG","IMG_0501.JPG",
     "IMG_0502.JPG","IMG_0503.JPG","IMG_0504.JPG","IMG_0505.JPG"],
    ["IMG_0764.JPG","IMG_0765.JPG","IMG_0766.JPG","IMG_0767.JPG"],
]

FAILED_SPREADS = [
    ["IMG_0855.JPG","IMG_0856.JPG","IMG_0857.JPG"],
    ["IMG_0858.JPG","IMG_0859.JPG"],
    ["IMG_0879.JPG","IMG_0880.JPG"],
    ["IMG_0930.JPG","IMG_0931.JPG","IMG_0932.JPG","IMG_0933.JPG",
     "IMG_0934.JPG","IMG_0935.JPG","IMG_0936.JPG"],
]


def log_error(msg: str):
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(f"  [ERROR] {msg}")


def image_to_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def ask_claude_multi(image_paths: list, prompt: str) -> str:
    content = []
    for p in image_paths:
        b64 = image_to_base64(p)
        ext = p.suffix.lower()
        media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })
    content.append({"type": "text", "text": prompt})
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text


def ask_claude(image_path: Path, prompt: str) -> str:
    b64 = image_to_base64(image_path)
    ext = image_path.suffix.lower()
    media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": prompt},
        ]}],
    )
    return response.content[0].text


def extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m2 = re.search(r"(\{[\s\S]*\})", text)
    if m2:
        try:
            return json.loads(m2.group(1))
        except json.JSONDecodeError:
            pass
    return None


CARD_SINGLE_PROMPT = """이 이미지는 타로 카드 교재의 한 페이지입니다.
이미지에 보이는 내용을 아래 JSON 형식으로 추출해 주세요.
- id: 이미지 안에 카드 번호가 있으면 숫자로, 없으면 null
- name_ko: 카드 한국어 이름
- name_en: 카드 영어 이름 (대문자)
- symbols: 이미지/텍스트에서 보이는 상징 요소를 키-값으로 (자세, 복장, 도구, 꽃 등)
- meaning: 카드 전체 해석 텍스트
- reversed: 역방향 의미 (있으면 텍스트, 없으면 null)

반드시 순수 JSON만 반환하세요 (설명 텍스트 없이).
```json
{
  "id": null,
  "name_ko": "...",
  "name_en": "...",
  "symbols": {},
  "meaning": "...",
  "reversed": null
}
```"""

CARD_MULTI_PROMPT = """이 {n}장의 이미지는 같은 타로 카드를 여러 페이지에 걸쳐 설명합니다.
모든 페이지의 내용을 합쳐서 아래 JSON 형식 하나로 추출해 주세요.
- id: 이미지 안에 카드 번호가 있으면 숫자로, 없으면 null
- name_ko: 카드 한국어 이름
- name_en: 카드 영어 이름 (대문자)
- symbols: 상징 요소 키-값 (자세, 복장, 도구, 꽃 등 보이는 것 모두)
- meaning: 카드 전체 해석 텍스트 (모든 페이지 통합)
- reversed: 역방향 의미 (있으면 텍스트, 없으면 null)

반드시 순수 JSON만 반환하세요.
```json
{{
  "id": null,
  "name_ko": "...",
  "name_en": "...",
  "symbols": {{}},
  "meaning": "...",
  "reversed": null
}}
```"""

SPREAD_SINGLE_PROMPT = """이 이미지는 타로 스프레드(배열법) 교재의 한 페이지입니다.
이미지에 보이는 내용을 아래 JSON 형식으로 추출해 주세요.
- id: 이미지 안에 번호가 있으면 숫자로, 없으면 null
- name: 스프레드 이름
- card_count: 사용 카드 수 (숫자, 모르면 null)
- positions: 각 포지션 번호와 의미 배열
- when_to_use: 이 스프레드를 언제 사용하는지 (없으면 null)
- how_to_read: 읽는 방법 설명 (없으면 null)

반드시 순수 JSON만 반환하세요.
```json
{
  "id": null,
  "name": "...",
  "card_count": null,
  "positions": [],
  "when_to_use": null,
  "how_to_read": null
}
```"""

SPREAD_MULTI_PROMPT = """이 {n}장의 이미지는 같은 타로 스프레드를 여러 페이지에 걸쳐 설명합니다.
모든 페이지 내용을 합쳐서 아래 JSON 형식 하나로 추출해 주세요.
- id: 이미지 안에 번호가 있으면 숫자로, 없으면 null
- name: 스프레드 이름
- card_count: 사용 카드 수 (숫자, 모르면 null)
- positions: 각 포지션 번호와 의미 배열 (모든 페이지 통합)
- when_to_use: 언제 사용하는지 (없으면 null)
- how_to_read: 읽는 방법 설명 (없으면 null)

반드시 순수 JSON만 반환하세요.
```json
{{
  "id": null,
  "name": "...",
  "card_count": null,
  "positions": [],
  "when_to_use": null,
  "how_to_read": null
}}
```"""


def process_group(group: list, idx: int, total: int, mode: str) -> dict:
    label = ", ".join(p.name for p in group)
    print(f"처리중: {label} ({idx}/{total})")
    try:
        if mode == "card":
            raw = ask_claude(group[0], CARD_SINGLE_PROMPT) if len(group) == 1 \
                else ask_claude_multi(group, CARD_MULTI_PROMPT.format(n=len(group)))
        else:
            raw = ask_claude(group[0], SPREAD_SINGLE_PROMPT) if len(group) == 1 \
                else ask_claude_multi(group, SPREAD_MULTI_PROMPT.format(n=len(group)))
        time.sleep(0.5)
        data = extract_json(raw)
        if data is None:
            raise ValueError(f"JSON 추출 실패: {raw[:200]}")
        data["source_file"] = [p.name for p in group] if len(group) > 1 else group[0].name
        return data
    except Exception as e:
        log_error(f"{mode} 처리 오류 [{label}]: {e}\n{traceback.format_exc()}")
        return {
            "source_file": [p.name for p in group] if len(group) > 1 else group[0].name,
            "error": str(e),
        }


# ── STEP 1: 카드 재처리 ──────────────────────────────────
print(f"\n=== 카드 재처리: {len(FAILED_CARDS)}개 그룹 ===")
with open(CARDS_FINAL, encoding="utf-8") as f:
    cards = json.load(f)

for i, file_names in enumerate(FAILED_CARDS, start=1):
    group = [CARDS_DIR / f for f in file_names]
    new_data = process_group(group, i, len(FAILED_CARDS), "card")
    # cards.json에서 해당 source_file 항목 찾아서 교체
    for j, c in enumerate(cards):
        src = c.get("source_file")
        if (isinstance(src, list) and src == file_names) or src == file_names[0]:
            cards[j] = new_data
            break

with open(CARDS_FINAL, "w", encoding="utf-8") as f:
    json.dump(cards, f, ensure_ascii=False, indent=2)
print(f"✓ cards.json 업데이트 완료\n")


# ── STEP 2: 스프레드 재처리 ─────────────────────────────
print(f"=== 스프레드 재처리: {len(FAILED_SPREADS)}개 그룹 ===")
with open(SPREADS_FINAL, encoding="utf-8") as f:
    spreads = json.load(f)

for i, file_names in enumerate(FAILED_SPREADS, start=1):
    group = [SPREADS_DIR / f for f in file_names]
    new_data = process_group(group, i, len(FAILED_SPREADS), "spread")
    # spreads.json에서 해당 source_file 항목 찾아서 교체
    for j, s in enumerate(spreads):
        src = s.get("source_file")
        if (isinstance(src, list) and src == file_names) or src == file_names[0]:
            spreads[j] = new_data
            break

with open(SPREADS_FINAL, "w", encoding="utf-8") as f:
    json.dump(spreads, f, ensure_ascii=False, indent=2)
print(f"✓ spreads.json 업데이트 완료\n")

print("✅ 재처리 완료!")
