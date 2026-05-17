import json
import os
import anthropic
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="AI Tarot Reading")

LANG_NAMES = {
    'ko': '한국어', 'en': 'English', 'ja': 'Japanese',
    'es': 'Spanish', 'fr': 'French', 'de': 'German',
    'pt': 'Portuguese', 'th': 'Thai', 'ru': 'Russian',
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Mount static files
app.mount("/images", StaticFiles(directory=os.path.join(BASE_DIR, "tarot_images")), name="images")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/api/cards")
async def get_cards():
    with open(os.path.join(BASE_DIR, "output", "cards.json"), encoding="utf-8") as f:
        cards = json.load(f)
    # Filter out non-card entries (MINOR ARCANA header)
    valid_cards = [c for c in cards if c.get("image_file") is not None]
    return valid_cards


@app.get("/api/spreads")
async def get_spreads():
    with open(os.path.join(BASE_DIR, "output", "spreads.json"), encoding="utf-8") as f:
        spreads = json.load(f)
    # Filter spreads with actual card positions
    valid_spreads = [s for s in spreads if s.get("card_count") and s.get("positions")]
    return valid_spreads


class SpreadSelectRequest(BaseModel):
    question: str
    language: str = 'ko'


@app.post("/api/select-spread")
async def select_spread(request: SpreadSelectRequest):
    with open(os.path.join(BASE_DIR, "output", "spreads.json"), encoding="utf-8") as f:
        spreads = json.load(f)
    valid_spreads = [
        s for s in spreads
        if s.get("card_count") and s.get("positions") and s.get("name")
    ]

    spread_list = "\n".join([
        f"{i+1}. {s.get('name','')} ({s.get('card_count',3)}장) - {(s.get('when_to_use') or '')[:60]}"
        for i, s in enumerate(valid_spreads)
    ])

    lang_name = LANG_NAMES.get(request.language, 'Korean')
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": f"""내담자의 질문: {request.question}

사용 가능한 타로 스프레드 목록:
{spread_list}

위 질문에 가장 적합한 스프레드 하나를 선택하고 이유를 한 문장으로 설명하세요.
반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{"index": 1, "reason": "선택 이유"}}
index는 1부터 시작합니다.
위 JSON에서 reason 값은 반드시 {lang_name}으로 작성하세요."""}]
    )

    import re
    text = response.content[0].text.strip()
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        result = {"index": 1, "reason": "질문에 균형 잡힌 시각을 제공하기 위해 선택했습니다."}
    else:
        try:
            result = json.loads(m.group())
        except Exception:
            result = {"index": 1, "reason": "질문에 균형 잡힌 시각을 제공하기 위해 선택했습니다."}

    idx = max(0, min(int(result.get("index", 1)) - 1, len(valid_spreads) - 1))
    spread = dict(valid_spreads[idx])
    spread["reason"] = result.get("reason", "")
    return spread


class DrawnCard(BaseModel):
    name_ko: str
    name_en: str
    meaning: str
    symbols: Optional[dict] = None
    reversed: bool
    position_meaning: Optional[str] = None
    image_file: Optional[str] = None


class ReadingRequest(BaseModel):
    question: str
    cards: List[DrawnCard]
    spread_name: str
    language: str = 'ko'


@app.post("/api/reading")
async def tarot_reading(request: ReadingRequest):
    async def generate():
        client = anthropic.AsyncAnthropic()

        # Build the user prompt
        cards_text = ""
        for i, card in enumerate(request.cards, 1):
            direction = "역방향" if card.reversed else "정방향"
            position_text = f"\n  - 위치 의미: {card.position_meaning}" if card.position_meaning else ""

            # Extract key symbols
            symbols_text = ""
            if card.symbols:
                key_symbols = list(card.symbols.items())[:3]
                symbols_text = ", ".join([f"{k}: {v[:50]}..." if len(v) > 50 else f"{k}: {v}" for k, v in key_symbols])
                symbols_text = f"\n  - 주요 상징: {symbols_text}"

            # Truncate meaning to key parts
            meaning_preview = card.meaning[:200] + "..." if len(card.meaning) > 200 else card.meaning

            cards_text += f"""
카드 {i}: {card.name_ko} ({card.name_en}) - {direction}{position_text}{symbols_text}
  - 핵심 의미: {meaning_preview}
"""

        user_prompt = f"""질문: {request.question}

스프레드: {request.spread_name}

뽑힌 카드들:
{cards_text}

위 카드들을 바탕으로 내담자의 질문에 대한 깊이 있는 타로 리딩을 해주세요.

각 카드의 위치 의미와 방향(정/역방향)을 고려하고, 카드들 사이의 연결과 흐름을 분석하여 종합적인 메시지를 전달해주세요. 내담자의 상황에 공감하며 구체적이고 실용적인 조언을 포함해주세요."""

        lang_name = LANG_NAMES.get(request.language, 'Korean')
        system_prompt = f"""당신은 20년 경력의 전문 타로 리더입니다. 깊은 통찰력과 균형 잡힌 시각을 가지고 있으며, 내담자가 자신의 상황을 있는 그대로 직면하고 더 넓게 볼 수 있도록 돕습니다.

리딩 방식:
- 각 카드의 위치와 방향(정/역방향)을 명확히 언급하세요
- 카드들 사이의 에너지 흐름과 연결을 분석하세요
- 카드가 보여주는 현실을 과장하거나 축소하지 말고 있는 그대로 해석하세요
- 어려운 카드가 나왔다면 그 도전과 위험을 솔직하게 짚되, 그 상황 안에 담긴 교훈이나 성장의 가능성도 함께 언급하세요
- 좋은 카드가 나왔다면 그 긍정적 에너지를 인정하되, 놓치기 쉬운 맹점이나 주의할 점도 균형 있게 짚어주세요
- 결과를 좋게 포장하려 하지 말고, 내담자가 상황의 여러 면을 스스로 볼 수 있도록 시각을 넓혀주는 것을 목표로 하세요
- 현실적이고 구체적인 조언을 제공하세요
- Write all responses in {lang_name}.
- 전문적이되 친근한 말투를 사용하세요
- 각 카드별로 단락을 나눠서 읽기 쉽게 구성하세요

서식 규칙 (반드시 지켜주세요):
- **절대 마크다운 기호를 사용하지 마세요** (**, *, #, ##, ### 등 금지)
- 단락 제목은 꺾쇠괄호로 표시하세요. 예: <카드 해석>, <종합 메시지>
- 소제목이나 항목은 번호로 표시하세요. 예: 1) 현재 상황, 2) 조언
- 강조는 기호 없이 문장으로 자연스럽게 표현하세요"""

        async with client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        ) as stream:
            async for text in stream.text_stream:
                # Escape newlines for SSE
                escaped = text.replace("\n", "\\n")
                yield f"data: {escaped}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
