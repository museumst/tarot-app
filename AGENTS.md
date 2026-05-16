# Tarot Knowledge Base Extraction
## 파일 구조
- images/cards/     : IMG_0498.JPG ~ (352장)
- images/spreads/   : 별도 폴더 (82장)
- output/           : 결과 JSON 저장 위치
## 처리 순서
파일명의 숫자 기준으로 오름차순 정렬 후 순서대로 처리
(IMG_0498 → IMG_0499 → IMG_0500 ...)
## cards/ 추출 구조
{
  "source_file": "IMG_0498.JPG",
  "id": null,              ← 이미지 안에서 카드 번호 읽기, 없으면 null
  "name_ko": "마법사",
  "name_en": "THE MAGICIAN",
  "symbols": {
    "자세": "...",
    "복장": "...",
    "도구": "...",
    "꽃": "..."
  },
  "meaning": "카드 전체 해석 텍스트",
  "reversed": "역방향 의미 (있을 경우)"
}
## spreads/ 추출 구조
{
  "source_file": "IMG_XXXX.JPG",
  "id": null,              ← 이미지 안에서 번호 읽기
  "name": "기초 3카드 스프레드",
  "card_count": 3,
  "positions": [
    { "position": 1, "meanings": ["작동하는 것", "분리된 상태", "내담자가 원하는 것"] },
    { "position": 2, "meanings": ["작동하지 않는 것", "결합된 상태", "타인이 원하는 것"] },
    { "position": 3, "meanings": ["학습하는 것", "행동하는 상태", "나아가고 있는 방향"] }
  ],
  "when_to_use": "...",
  "how_to_read": "..."
}
## 실행 규칙
- 한 장의 JPG가 여러 페이지에 걸친 내용일 수 있음 (연속된 파일이 같은 카드일 수 있음)
- 같은 카드가 여러 JPG에 걸쳐있으면 내용을 합쳐서 하나의 객체로 저장
- 처리 중 진행상황 출력: "처리중: IMG_0498.JPG (1/352)"
- 오류 발생 시 error_log.txt에 기록하고 계속 진행
- 중간 저장: 50장마다 output/cards_partial.json으로 저장 (중단 대비)
- 최종 저장: output/cards.json, output/spreads.json
```
---
## Codex 실행 프롬프트
```
AGENTS.md를 읽고 extract.py를 작성한 뒤 실행해줘.
주의사항:
- anthropic SDK의 Vision 기능으로 각 JPG를 읽는다
- 연속된 파일이 같은 카드를 다루는지 판단해서 합쳐야 한다
- cards/ 먼저 완료 후 spreads/ 처리
- API rate limit 대비해서 요청 사이에 0.5초 딜레이 넣어줘
