#!/usr/bin/env python3
"""
Tarot Knowledge Base Extraction
CLAUDE.md 명세에 따라 images/cards/ 와 images/spreads/ 의 JPG를
Anthropic Vision API로 읽어 JSON으로 추출한다.
"""

import os
import re
import json
import time
import base64
import traceback
from pathlib import Path
import anthropic

# ── 경로 설정 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CARDS_DIR = BASE_DIR / "images" / "cards"
SPREADS_DIR = BASE_DIR / "images" / "spreads"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

ERROR_LOG = OUTPUT_DIR / "error_log.txt"
CARDS_PARTIAL = OUTPUT_DIR / "cards_partial.json"
CARDS_FINAL = OUTPUT_DIR / "cards.json"
SPREADS_FINAL = OUTPUT_DIR / "spreads.json"

# ── Anthropic 클라이언트 ───────────────────────────────────
client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-5"


def log_error(msg: str):
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(f"  [ERROR] {msg}")


def sorted_jpgs(directory: Path) -> list[Path]:
    """파일명의 숫자 기준 오름차순 정렬"""
    files = [f for f in directory.iterdir() if f.suffix.upper() in (".JPG", ".JPEG", ".PNG")]

    def num_key(p: Path):
        m = re.search(r"(\d+)", p.stem)
        return int(m.group(1)) if m else 0

    return sorted(files, key=num_key)


def image_to_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def ask_claude(image_path: Path, prompt: str) -> str:
    """단일 이미지 → Claude Vision → 텍스트 응답"""
    b64 = image_to_base64(image_path)
    ext = image_path.suffix.lower()
    media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return response.content[0].text


def ask_claude_multi(image_paths: list[Path], prompt: str) -> str:
    """여러 이미지(연속 페이지) → Claude Vision → 텍스트 응답"""
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


def extract_json(text: str) -> dict | list | None:
    """응답 텍스트에서 JSON 블록 추출"""
    # ```json ... ``` 블록 우선
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 블록 없으면 첫 { ... } 시도
    m2 = re.search(r"(\{[\s\S]*\})", text)
    if m2:
        try:
            return json.loads(m2.group(1))
        except json.JSONDecodeError:
            pass
    return None


# ══════════════════════════════════════════════════════════
#  STEP 1 : cards/ 처리
# ══════════════════════════════════════════════════════════

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

CONTINUATION_CHECK_PROMPT = """두 이미지를 보세요.
첫 번째 이미지와 두 번째 이미지가 같은 타로 카드(또는 같은 스프레드)의 내용을
연속으로 다루고 있나요?
"yes" 또는 "no" 한 단어만 답하세요."""


def is_continuation(prev_path: Path, next_path: Path) -> bool:
    """두 이미지가 같은 카드/스프레드의 연속인지 판단"""
    try:
        answer = ask_claude_multi(
            [prev_path, next_path], CONTINUATION_CHECK_PROMPT
        ).strip().lower()
        time.sleep(0.5)
        return answer.startswith("yes")
    except Exception as e:
        log_error(f"continuation check 오류 ({prev_path.name} / {next_path.name}): {e}")
        return False


def group_files(files: list[Path]) -> list[list[Path]]:
    """연속 파일들을 같은 카드 그룹으로 묶는다"""
    if not files:
        return []

    groups: list[list[Path]] = [[files[0]]]
    total = len(files)

    for i in range(1, total):
        prev = groups[-1][-1]
        curr = files[i]
        print(f"  연속 확인: {prev.name} → {curr.name} ({i}/{total-1})")
        if is_continuation(prev, curr):
            groups[-1].append(curr)
        else:
            groups.append([curr])

    return groups


def process_card_group(group: list[Path], idx: int, total: int) -> dict:
    """카드 그룹(1장 이상)을 JSON 객체로 추출"""
    label = ", ".join(p.name for p in group)
    print(f"처리중: {label} ({idx}/{total})")

    try:
        if len(group) == 1:
            raw = ask_claude(group[0], CARD_SINGLE_PROMPT)
        else:
            prompt = CARD_MULTI_PROMPT.format(n=len(group))
            raw = ask_claude_multi(group, prompt)
        time.sleep(0.5)

        data = extract_json(raw)
        if data is None:
            raise ValueError(f"JSON 추출 실패: {raw[:200]}")

        data["source_file"] = [p.name for p in group] if len(group) > 1 else group[0].name
        return data

    except Exception as e:
        err_msg = f"카드 처리 오류 [{label}]: {e}\n{traceback.format_exc()}"
        log_error(err_msg)
        return {
            "source_file": [p.name for p in group] if len(group) > 1 else group[0].name,
            "error": str(e),
        }


def process_cards():
    files = sorted_jpgs(CARDS_DIR)
    print(f"\n=== cards/ 처리 시작: {len(files)}장 ===")

    # 연속 그룹 묶기
    print("연속 파일 그룹핑 중...")
    groups = group_files(files)
    print(f"그룹 수: {len(groups)} (카드 객체 예상 수)")

    results = []
    total = len(groups)

    for i, group in enumerate(groups, start=1):
        obj = process_card_group(group, i, total)
        results.append(obj)

        # 50장(그룹)마다 중간 저장
        if i % 50 == 0:
            with open(CARDS_PARTIAL, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"  ✓ 중간저장: {CARDS_PARTIAL} ({i}/{total})")

    with open(CARDS_FINAL, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n=== cards/ 완료: {CARDS_FINAL} ({len(results)}개 객체) ===\n")
    return results


# ══════════════════════════════════════════════════════════
#  STEP 2 : spreads/ 처리
# ══════════════════════════════════════════════════════════

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


def process_spread_group(group: list[Path], idx: int, total: int) -> dict:
    label = ", ".join(p.name for p in group)
    print(f"처리중: {label} ({idx}/{total})")

    try:
        if len(group) == 1:
            raw = ask_claude(group[0], SPREAD_SINGLE_PROMPT)
        else:
            prompt = SPREAD_MULTI_PROMPT.format(n=len(group))
            raw = ask_claude_multi(group, prompt)
        time.sleep(0.5)

        data = extract_json(raw)
        if data is None:
            raise ValueError(f"JSON 추출 실패: {raw[:200]}")

        data["source_file"] = [p.name for p in group] if len(group) > 1 else group[0].name
        return data

    except Exception as e:
        err_msg = f"스프레드 처리 오류 [{label}]: {e}\n{traceback.format_exc()}"
        log_error(err_msg)
        return {
            "source_file": [p.name for p in group] if len(group) > 1 else group[0].name,
            "error": str(e),
        }


def process_spreads():
    files = sorted_jpgs(SPREADS_DIR)
    print(f"\n=== spreads/ 처리 시작: {len(files)}장 ===")

    print("연속 파일 그룹핑 중...")
    groups = group_files(files)
    print(f"그룹 수: {len(groups)}")

    results = []
    total = len(groups)

    for i, group in enumerate(groups, start=1):
        obj = process_spread_group(group, i, total)
        results.append(obj)

    with open(SPREADS_FINAL, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n=== spreads/ 완료: {SPREADS_FINAL} ({len(results)}개 객체) ===\n")
    return results


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Tarot Knowledge Base Extraction 시작")
    print(f"모델: {MODEL}")
    print(f"출력 디렉토리: {OUTPUT_DIR}\n")

    process_cards()
    process_spreads()

    print("모든 처리 완료.")
    if ERROR_LOG.exists():
        with open(ERROR_LOG, encoding="utf-8") as f:
            errs = f.read().strip()
        if errs:
            print(f"\n오류 로그 ({ERROR_LOG}):\n{errs}")
