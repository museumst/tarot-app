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

# ── 양자택일(선택) 질문 감지 ──
# 두 선택지 중 하나를 고르는 질문이면 비교 스프레드 + 비교 프롬프트로 분기한다.
_BINARY_MARKERS = [
    "vs", "versus", "v.s",
    "아니면", "둘 중", "둘중", "중 하나", "중하나", "중 어느", "중 어떤",
    "중 어디", "중에서", "어느 쪽", "어느쪽", "어느 것", "어떤 걸",
    "할까 말까", "할까말까", "갈까 말까", "살까 말까", "그만둘까", "말까",
    "either", " or not",
    "それとも", "どっち", "どちら",
    "还是", "哪个", "哪一个", "或者", "还是不",
]


def is_binary_question(text: str) -> bool:
    """A vs B 형태의 양자택일/선택 질문인지 판별."""
    import re
    t = (text or "").lower()
    if any(m in t for m in _BINARY_MARKERS):
        return True
    # 영어: "should I X or Y", "X or Y?" 등 (or + 질문/비교 신호가 함께일 때만)
    if re.search(r'\bor\b', t) and ('?' in t or 'should' in t or 'better' in t):
        return True
    return False


# 코드로 정의하는 양자택일 비교 스프레드 (spreads.json에는 없음)
COMPARISON_SPREAD = {
    "name": "양자택일 비교 스프레드",
    "card_count": 3,
    "positions": [
        {"position": 1, "meanings": ["선택지 A(첫 번째 길)의 흐름과 예상 결과"]},
        {"position": 2, "meanings": ["선택지 B(두 번째 길)의 흐름과 예상 결과"]},
        {"position": 3, "meanings": ["종합 조언과 결정을 위한 핵심"]},
    ],
    "when_to_use": "두 가지 선택지 중 하나를 결정해야 할 때",
    "how_to_read": "각 선택지를 카드에 대응시켜 비교한 뒤 종합적으로 판단한다",
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

    CREDIT_TABLE = {1000: 10, 3000: 35, 5000: 60}
    credits = CREDIT_TABLE.get(request.amount, request.amount // 100)
    return {"ok": True, "credits": credits}


class SpreadSelectRequest(BaseModel):
    question: str
    language: str = 'ko'


@app.post("/api/select-spread")
async def select_spread(request: SpreadSelectRequest):
    # 양자택일(선택) 질문이면 비교 스프레드로 분기
    if is_binary_question(request.question):
        lang_name = LANG_NAMES.get(request.language, 'Korean')
        spread = json.loads(json.dumps(COMPARISON_SPREAD))  # deep copy
        if request.language == 'ko':
            spread["name_translated"] = spread["name"]
            spread["reason"] = "두 가지 선택지를 각각 카드에 대응시켜 비교·판단하기 위해 선택했습니다."
        else:
            import re as _re
            client = anthropic.Anthropic()
            tr = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": f"""Translate the following JSON values into {lang_name}. Respond ONLY with JSON, no other text:
{{"name": "Two-Choice Comparison Spread", "reason": "Chosen to compare your two options side by side, each mapped to a card, then reach a conclusion."}}"""}]
            )
            m = _re.search(r'\{.*\}', tr.content[0].text, _re.DOTALL)
            try:
                d = json.loads(m.group()) if m else {}
            except Exception:
                d = {}
            spread["name_translated"] = d.get("name") or spread["name"]
            spread["reason"] = d.get("reason") or ""
        return spread

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
카드 {i}: {card.name_ko} ({card.name_en}){position_text}{symbols_text}
  - 핵심 의미: {meaning_preview}
"""

        user_prompt = f"""질문: {request.question}

스프레드: {request.spread_name}

뽑힌 카드들:
{cards_text}

위 카드들을 바탕으로 내담자의 질문에 대한 깊이 있는 타로 리딩을 해주세요.

각 카드의 위치 의미와 카드들 사이의 연결과 흐름을 분석하여 종합적인 메시지를 전달해주세요. 내담자의 상황에 공감하며 구체적이고 실용적인 조언을 포함해주세요."""

        lang_name = LANG_NAMES.get(request.language, 'Korean')
        system_prompt = f"""CRITICAL INSTRUCTION: You MUST write your ENTIRE response in {lang_name}. Every single word must be in {lang_name}. Do not use any other language.

You are a professional tarot reader with 20 years of experience. You have deep insight and a balanced perspective, helping clients face their situations clearly and see the bigger picture.

Reading approach:
- Clearly mention each card's position meaning
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

        # 양자택일(선택) 질문이면 비교/종합판단 지시를 추가
        if is_binary_question(request.question):
            system_prompt += """

IMPORTANT - This is an either/or (binary choice) question. Handle it as a COMPARISON reading:
- Treat the first card as "Option A" (the first path), the second card as "Option B" (the second path), and the final card as synthesis/advice.
- Clearly compare the energy and the likely outcome of each option side by side.
- After the comparison, add a section (angle-bracket title, e.g. <Final Judgment>) that states which option the cards lean toward and why, giving the client a clear, well-reasoned direction. Note that this is guidance for reflection, not a guaranteed outcome."""

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
