import json
import os
import anthropic
import httpx
from fastapi import FastAPI, HTTPException
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
    'zh': 'Chinese', 'it': 'Italian', 'id': 'Indonesian',
    'vi': 'Vietnamese', 'tr': 'Turkish', 'pl': 'Polish',
}

# 포트원 API Secret (Render 대시보드에서도 PORTONE_API_SECRET 환경변수를 설정해야 합니다)
PORTONE_API_SECRET = os.environ.get("PORTONE_API_SECRET", "")

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

@app.get("/legal.html")
async def legal():
    return FileResponse(os.path.join(BASE_DIR, "static", "legal.html"))


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


class PaymentVerifyRequest(BaseModel):
    payment_id: str
    amount: int
    uid: str


@app.post("/api/payment/verify")
async def verify_payment(request: PaymentVerifyRequest):
    # 포트원 API로 결제 정보 조회
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.portone.io/payments/{request.payment_id}",
            headers={"Authorization": f"PortOne {PORTONE_API_SECRET}"}
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="결제 정보 조회 실패")

    data = resp.json()

    # 결제 상태 확인
    if data.get("status") != "PAID":
        raise HTTPException(status_code=400, detail="결제가 완료되지 않았습니다.")

    # 금액 위변조 검증
    paid = data.get("amount", {}).get("total", 0)
    if paid != request.amount:
        raise HTTPException(status_code=400, detail="결제 금액이 일치하지 않습니다.")

    credits = request.amount // 100
    return {"ok": True, "credits": credits}


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
{{"index": 1, "name_translated": "스프레드 이름 번역", "reason": "선택 이유"}}
index는 1부터 시작합니다.
name_translated는 선택한 스프레드의 이름을 {lang_name}으로 번역한 것입니다.
reason 값과 name_translated 값은 반드시 {lang_name}으로 작성하세요."""}]
    )

    import re
    text = response.content[0].text.strip()
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        result = {"index": 1, "name_translated": "", "reason": "질문에 균형 잡힌 시각을 제공하기 위해 선택했습니다."}
    else:
        try:
            result = json.loads(m.group())
        except Exception:
            result = {"index": 1, "name_translated": "", "reason": "질문에 균형 잡힌 시각을 제공하기 위해 선택했습니다."}

    idx = max(0, min(int(result.get("index", 1)) - 1, len(valid_spreads) - 1))
    spread = dict(valid_spreads[idx])
    spread["reason"] = result.get("reason", "")
    spread["name_translated"] = result.get("name_translated", "") or spread.get("name", "")
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
        system_prompt = f"""CRITICAL INSTRUCTION: You MUST write your ENTIRE response in {lang_name}. Every single word must be in {lang_name}. Do not use any other language.

You are a professional tarot reader with 20 years of experience. You have deep insight and a balanced perspective, helping clients face their situations clearly and see the bigger picture.

Reading approach:
- Clearly mention each card's position and orientation (upright/reversed)
- Analyze the energy flow and connections between cards
- Interpret what the cards show without exaggeration or minimization
- For difficult cards: honestly address the challenge, but also mention lessons or growth potential within the situation
- For positive cards: acknowledge the positive energy, but also note blind spots or cautions
- Do not sugarcoat results; help the client see multiple perspectives of their situation
- Provide realistic and specific advice
- Use a professional yet warm tone
- Structure paragraphs clearly for each card

Formatting rules (strictly follow):
- Do NOT use markdown symbols (**, *, #, ##, ### are forbidden)
- Use angle brackets for section titles. Example: <Card Reading>, <Overall Message>
- Use numbers for sub-items. Example: 1) Current situation, 2) Advice
- Express emphasis naturally through sentences, not symbols

REMINDER: Your entire response must be written in {lang_name}."""

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
