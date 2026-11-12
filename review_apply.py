#!/usr/bin/env python3
"""외부 검수(JSON)를 번역 데이터에 반영한다.

사용법:
    python3 review_apply.py daily en fixes.json            # 미리보기(파일 수정 없음)
    python3 review_apply.py daily en fixes.json --write    # 실제 반영

종류: daily(오늘의 타로) / birth(생일수) / cards(카드도감) / ui(도감 UI 문구)
fixes.json 은 {id, field, original, suggestion} 객체의 배열이다.
  - 항목에 "skip": true 가 있으면 건너뛴다.
  - "original" 이 해당 필드에 정확히 1번 나올 때만 치환한다(0번·2번 이상이면 건너뛰고 보고).
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "output")
TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _walk(obj, path):
    """'career.fields[1]' 같은 경로를 따라 (부모, 키)를 돌려준다."""
    keys = []
    for part in path.split("."):
        m = re.fullmatch(r"([^\[\]]+)((?:\[\d+\])*)", part)
        if not m:
            raise KeyError(path)
        keys.append(m.group(1))
        keys += [int(i) for i in re.findall(r"\[(\d+)\]", m.group(2))]
    for k in keys[:-1]:
        obj = obj[k]
    return obj, keys[-1]


def locate(kind, lang, data, id_, field):
    """(parent, key) 를 반환. 못 찾으면 KeyError."""
    if kind == "daily":
        if id_ == "_meta":
            if field == "title":
                return data["_meta"], "title"
            return data["_meta"]["labels"], field.replace("label_", "", 1)
        return data["cards"][id_], field
    if kind == "cards":
        return data[id_], field.split("(")[0]
    if kind == "birth":
        if id_ == "_meta":
            if field.startswith("label_"):
                return data["_meta"]["labels"], field.replace("label_", "", 1)
            return _walk(data["_meta"], field)
        return _walk(data["cards"][id_], field)
    if kind == "ui":
        return data, field
    raise KeyError(kind)


def path_for(kind, lang):
    return {
        "daily": os.path.join(OUT, f"daily_cards_{lang}.json"),
        "birth": os.path.join(OUT, f"birth_cards_{lang}.json"),
        "cards": os.path.join(OUT, "i18n", f"cards_{lang}.json"),
        "ui": os.path.join(OUT, "i18n", f"ui_{lang}.json"),
    }[kind]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["daily", "birth", "cards", "ui"])
    ap.add_argument("lang")
    ap.add_argument("fixes")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    path = path_for(a.kind, a.lang)
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw)
    # 기존 파일의 들여쓰기·끝 줄바꿈을 그대로 유지해 불필요한 diff 가 생기지 않게 한다.
    second = raw.split("\n", 2)[1] if "\n" in raw else ""
    indent = len(second) - len(second.lstrip(" ")) or None
    trailing_nl = raw.endswith("\n")
    with open(a.fixes, encoding="utf-8") as f:
        fixes = json.load(f)

    applied, skipped, failed = 0, 0, []
    for n, fx in enumerate(fixes):
        tag = f"#{n} {fx.get('id')}.{fx.get('field')}"
        if fx.get("skip"):
            skipped += 1
            continue
        try:
            parent, key = locate(a.kind, a.lang, data, fx["id"], fx["field"])
            text = parent[key]
        except (KeyError, IndexError, TypeError):
            failed.append((tag, "필드를 찾을 수 없음"))
            continue
        if not isinstance(text, str):
            failed.append((tag, "문자열 필드가 아님"))
            continue
        cnt = text.count(fx["original"])
        if cnt != 1:
            failed.append((tag, f"original 이 {cnt}번 나타남"))
            continue
        parent[key] = text.replace(fx["original"], fx["suggestion"])
        applied += 1

    print(f"반영 {applied}건 / 건너뜀 {skipped}건 / 실패 {len(failed)}건")
    for tag, why in failed:
        print(f"  실패 {tag}: {why}")
    if a.write and applied:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            if trailing_nl:
                f.write("\n")
        print(f"저장: {os.path.relpath(path, BASE)}")
    elif not a.write:
        print("(미리보기 — 저장하지 않았습니다. 반영하려면 --write)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
