import json
import os
import re
import html as _html
import anthropic
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, PlainTextResponse, Response
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
    "중 어디", "중에서", "중에 어떤", "중에 어느", "중에 뭐", "중에 무엇",
    "어느 쪽", "어느쪽", "어느 것", "어떤 걸",
    "어떤 게 나", "어떤게 나", "어느 게 나", "어느게 나",
    "어떤 게 좋", "어떤게 좋", "어느 게 좋", "어느게 좋",
    "뭐가 나", "뭐가 좋", "무엇이 나", "무엇이 좋",
    "더 나은", "더 나을", "더 좋은", "더 좋을", "더 나은지",
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


# 코드로 정의하는 선택 비교 스프레드 (spreads.json에는 없음). Haiku 후보 목록 표시용 기본형.
COMPARISON_SPREAD = {
    "name": "선택 비교 스프레드",
    "card_count": 3,
    "positions": [
        {"position": 1, "meanings": ["선택지 1의 흐름과 예상 결과"]},
        {"position": 2, "meanings": ["선택지 2의 흐름과 예상 결과"]},
        {"position": 3, "meanings": ["종합 조언과 결정을 위한 핵심"]},
    ],
    "when_to_use": "여러 선택지(2개 이상) 중 하나를 결정해야 할 때",
    "how_to_read": "각 선택지를 카드에 대응시켜 비교한 뒤 종합적으로 판단한다",
}
COMPARISON_MAX_OPTIONS = 5  # 카드가 너무 많아지지 않도록 상한


def count_options(text: str) -> int:
    """질문에 제시된 선택지 개수를 추정 (번호목록/동그라미숫자/구분자 기반). 기본 2, 최대 5."""
    import re
    t = text or ""
    circled = "①②③④⑤⑥⑦⑧⑨"
    nums = set()
    if any(c in t for c in circled):
        for c in t:
            if c in circled:
                nums.add(circled.index(c) + 1)
    else:
        for m in re.findall(r'(?:^|[\s(])([1-9])[.)．、]', t):
            nums.add(int(m))
    # 1,2,3... 연속으로 몇 개인지
    seq = 0
    i = 1
    while i in nums:
        seq += 1
        i += 1
    # 구분자(vs, or, 또는) 기반 추정
    low = t.lower()
    sep = sum(low.count(s) for s in [" vs ", "vs.", " or ", "또는"])
    by_sep = sep + 1 if sep >= 1 else 0
    n = max(seq if seq >= 2 else 0, by_sep if by_sep >= 2 else 0, 2)
    return min(n, COMPARISON_MAX_OPTIONS)


def build_comparison_spread(n_options: int, language: str, client) -> dict:
    """선택지 개수(n)에 맞춰 카드 n+1장짜리 비교 스프레드를 생성 (마지막 1장은 종합 조언)."""
    n = max(2, min(int(n_options), COMPARISON_MAX_OPTIONS))
    positions = [
        {"position": i + 1, "meanings": [f"선택지 {i + 1}의 흐름과 예상 결과"]}
        for i in range(n)
    ]
    positions.append({"position": n + 1, "meanings": ["종합 조언과 결정을 위한 핵심"]})
    name = "양자택일 비교 스프레드" if n == 2 else f"{n}가지 선택 비교 스프레드"
    spread = {
        "name": name,
        "card_count": n + 1,
        "positions": positions,
        "when_to_use": "여러 선택지 중 하나를 결정해야 할 때",
        "how_to_read": "각 선택지를 카드에 대응시켜 비교한 뒤 종합적으로 판단한다",
    }
    if language == 'ko':
        spread["name_translated"] = name
        spread["reason"] = f"{n}가지 선택지를 각각 카드에 대응시켜 비교·판단하기 위해 선택했습니다."
    else:
        import re as _re
        try:
            tr = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": f"""Translate these JSON values into {LANG_NAMES.get(language, 'English')}. Respond ONLY with JSON, no other text:
{{"name": "Comparison Spread for {n} Options", "reason": "Chosen to compare your {n} options side by side, each mapped to a card, then reach a conclusion."}}"""}]
            )
            m = _re.search(r'\{.*\}', tr.content[0].text, _re.DOTALL)
            d = json.loads(m.group()) if m else {}
        except Exception:
            d = {}
        spread["name_translated"] = d.get("name") or name
        spread["reason"] = d.get("reason") or ""
    return spread

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

# ── 검색엔진 소유권 확인 파일 (루트 경로에서 그대로 서빙되어야 함) ──
@app.get("/googlefa1b26a823641718.html")
async def google_site_verification():
    return FileResponse(os.path.join(BASE_DIR, "static", "googlefa1b26a823641718.html"))


@app.get("/naverbecce9a4943175d5c9badc65c8e9e828.html")
async def naver_site_verification():
    return FileResponse(os.path.join(BASE_DIR, "static", "naverbecce9a4943175d5c9badc65c8e9e828.html"))


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


# ──────────────────────────────────────────────────────────────
# 타로 카드 도감 (SEO 유입용 정적 페이지)
#   /cards           : 전체 목록
#   /card/{slug}     : 카드 상세
#   /sitemap.xml, /robots.txt
# 검색엔진이 읽을 수 있도록 서버에서 HTML을 직접 렌더링한다.
# ──────────────────────────────────────────────────────────────
SITE_URL = "https://ultratarot.com"
_CARDS_CACHE = None

_SUITS = [("CUPS", "컵"), ("WANDS", "완드"), ("SWORDS", "소드"), ("PENTACLES", "펜타클")]


def _slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')


def _suit_of(name_en: str):
    for key, label in _SUITS:
        if key in (name_en or '').upper():
            return key, label
    return "MAJOR", "메이저 아르카나"


def load_deck():
    """카드 데이터를 슬러그/수트 정보와 함께 로드 (최초 1회 캐시)."""
    global _CARDS_CACHE
    if _CARDS_CACHE is None:
        with open(os.path.join(BASE_DIR, "output", "cards.json"), encoding="utf-8") as f:
            raw = json.load(f)
        deck = []
        for c in raw:
            if not c.get("image_file"):
                continue
            c = dict(c)
            c["slug"] = _slugify(c.get("name_en"))
            c["suit"], c["suit_label"] = _suit_of(c.get("name_en"))
            deck.append(c)
        _CARDS_CACHE = deck
    return _CARDS_CACHE


def _e(s) -> str:
    return _html.escape(str(s or ''))


def _shell(title: str, desc: str, canonical: str, body: str, og_image: str) -> str:
    """도감 페이지 공통 HTML 껍데기 (본 사이트와 동일한 다크/골드 테마)."""
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(title)}</title>
<meta name="description" content="{_e(desc)}">
<link rel="canonical" href="{_e(canonical)}">
<meta name="robots" content="index, follow">
<meta name="theme-color" content="#0d0d1a">
<meta property="og:type" content="article">
<meta property="og:site_name" content="울트라타로">
<meta property="og:url" content="{_e(canonical)}">
<meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(desc)}">
<meta property="og:image" content="{_e(og_image)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_e(title)}">
<meta name="twitter:description" content="{_e(desc)}">
<meta name="twitter:image" content="{_e(og_image)}">
<link rel="icon" href="/static/favicon.png" type="image/png">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0d0d1a;color:#e8e3d8;font-family:'Noto Sans KR',sans-serif;font-weight:300;line-height:1.75}}
  a{{color:#c4a96b;text-decoration:none}} a:hover{{color:#d9bf8e}}
  .wrap{{max-width:900px;margin:0 auto;padding:28px 20px 80px}}
  .topbar{{border-bottom:1px solid rgba(196,169,107,.18);padding-bottom:16px;margin-bottom:34px;
          display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}}
  .brand{{font-weight:700;font-size:1.12rem;color:#d9bf8e}}
  .nav a{{font-size:.86rem;margin-left:16px}}
  h1{{font-size:clamp(1.7rem,4.6vw,2.5rem);font-weight:700;color:#d9bf8e;margin-bottom:6px;line-height:1.3}}
  h2{{font-size:1.1rem;color:#c4a96b;margin:34px 0 12px;font-weight:500}}
  .sub{{color:#7c8090;font-size:.92rem;margin-bottom:26px}}
  .card-head{{display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start}}
  .card-img{{width:210px;flex-shrink:0}}
  .card-img img{{width:100%;border-radius:10px;border:1px solid rgba(196,169,107,.45);display:block}}
  .card-body{{flex:1;min-width:250px}}
  p{{margin-bottom:14px}}
  .sym{{border:1px solid rgba(196,169,107,.2);border-radius:10px;padding:16px 18px;background:rgba(255,255,255,.02)}}
  .sym div{{margin-bottom:10px}} .sym div:last-child{{margin-bottom:0}}
  .sym b{{color:#c4a96b;font-weight:500;display:block;font-size:.86rem;margin-bottom:2px}}
  .cta{{display:inline-block;margin:30px 0 8px;background:linear-gradient(135deg,#8a6d2f,#c4a96b);
       color:#1a1626;font-weight:700;padding:14px 30px;border-radius:9px}}
  .cta:hover{{color:#1a1626;filter:brightness(1.08)}}
  .pager{{display:flex;justify-content:space-between;gap:12px;margin-top:40px;
         border-top:1px solid rgba(196,169,107,.18);padding-top:18px;font-size:.9rem}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:16px}}
  .tile{{display:block;text-align:center}}
  .tile img{{width:100%;border-radius:8px;border:1px solid rgba(196,169,107,.3);display:block;margin-bottom:7px}}
  #card-search{{width:100%;padding:13px 16px;margin-bottom:8px;border-radius:9px;
    background:rgba(255,255,255,.04);border:1px solid rgba(196,169,107,.3);
    color:#e8e3d8;font-family:'Noto Sans KR',sans-serif;font-size:.95rem}}
  #card-search:focus{{outline:none;border-color:#c4a96b}}
  #card-search::placeholder{{color:#7c8090}}
  .tile span{{font-size:.84rem;color:#e8e3d8}}
  .tile small{{display:block;color:#7c8090;font-size:.72rem}}
  footer{{margin-top:56px;border-top:1px solid rgba(196,169,107,.15);padding-top:20px;
         color:#7c8090;font-size:.78rem;text-align:center}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <a class="brand" href="/">✨ 울트라타로</a>
    <div class="nav"><a href="/cards">카드 도감</a><a href="/">타로 보기</a></div>
  </div>
  {body}
  <footer>
    <a href="/">울트라타로</a> · AI가 읽어주는 타로 카드 ·
    <a href="/legal.html#terms">이용약관</a> ·
    <a href="/legal.html#privacy">개인정보처리방침</a>
  </footer>
</div>
</body>
</html>"""


@app.get("/cards", response_class=HTMLResponse)
async def cards_index():
    deck = load_deck()
    groups = [("MAJOR", "메이저 아르카나")] + _SUITS
    sections = []
    for key, label in groups:
        items = [c for c in deck if c["suit"] == key]
        if not items:
            continue
        tiles = "".join(
            f'<a class="tile" href="/card/{_e(c["slug"])}">'
            f'<img src="/images/{_e(c["image_file"])}" alt="{_e(c["name_ko"])} 타로카드" loading="lazy">'
            f'<span>{_e(c["name_ko"])}</span><small>{_e(c["name_en"])}</small></a>'
            for c in items
        )
        suffix = "" if key == "MAJOR" else " 수트"
        sections.append(
            f'<section class="suit-sec"><h2>{_e(label)}{suffix} ({len(items)}장)</h2>'
            f'<div class="grid">{tiles}</div></section>'
        )

    search = (
        '<input id="card-search" type="search" placeholder="카드 이름으로 검색..." '
        'oninput="filterCards(this.value)" autocomplete="off">'
        '<p id="no-result" style="display:none;color:#7c8090">검색 결과가 없습니다.</p>'
        "<script>\n"
        "function filterCards(q){\n"
        "  q=(q||'').trim().toLowerCase();\n"
        "  var shown=0;\n"
        "  document.querySelectorAll('.tile').forEach(function(el){\n"
        "    var hit=!q||el.textContent.toLowerCase().indexOf(q)>-1;\n"
        "    el.style.display=hit?'':'none'; if(hit)shown++;\n"
        "  });\n"
        "  document.querySelectorAll('.suit-sec').forEach(function(sec){\n"
        "    var any=sec.querySelectorAll('.tile:not([style*=\"none\"])').length;\n"
        "    sec.style.display=any?'':'none';\n"
        "  });\n"
        "  document.getElementById('no-result').style.display=shown?'none':'';\n"
        "}\n"
        "</script>"
    )
    body = (
        "<h1>타로 카드 도감</h1>"
        f'<p class="sub">타로 카드 {len(deck)}장의 의미와 상징을 정리했습니다. '
        "카드를 눌러 자세한 해설을 확인하세요.</p>"
        + search
        + "".join(sections)
        + '<p style="text-align:center"><a class="cta" href="/">내 타로 보러 가기 →</a></p>'
    )
    return _shell(
        f"타로 카드 의미 총정리 — 타로카드 {len(deck)}장 도감 | 울트라타로",
        f"타로 카드 {len(deck)}장의 의미와 상징을 한눈에. 메이저 아르카나부터 컵·완드·소드·펜타클까지 카드별 해설을 확인하세요.",
        f"{SITE_URL}/cards",
        body,
        f"{SITE_URL}/static/og-image.jpg",
    )


@app.get("/card/{slug}", response_class=HTMLResponse)
async def card_detail(slug: str):
    deck = load_deck()
    idx = next((i for i, c in enumerate(deck) if c["slug"] == slug), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="카드를 찾을 수 없습니다.")
    c = deck[idx]
    prev_c = deck[idx - 1] if idx > 0 else None
    next_c = deck[idx + 1] if idx < len(deck) - 1 else None

    syms = c.get("symbols") or {}
    sym_html = "".join(f"<div><b>{_e(k)}</b>{_e(v)}</div>" for k, v in syms.items())
    sym_block = f'<h2>카드 속 상징</h2><div class="sym">{sym_html}</div>' if sym_html else ""

    # 보강된 해설(seo)이 있으면 상세 섹션을 구성하고, 없으면 기존 meaning만 보여준다
    seo = c.get("seo") or {}
    rev_block = ""
    topic_block = ""
    advice_block = ""
    if seo.get("reversed"):
        rev_block = f"<h2>역방향으로 나왔을 때</h2><p>{_e(seo['reversed'])}</p>"
    topics = [("love", "연애·인간관계"), ("career", "직장·진로"), ("money", "금전·재물")]
    parts = [f"<h2>{label}</h2><p>{_e(seo[key])}</p>" for key, label in topics if seo.get(key)]
    if parts:
        topic_block = "".join(parts)
    if seo.get("advice"):
        advice_block = f'<h2>이 카드의 조언</h2><div class="sym"><p style="margin:0">{_e(seo["advice"])}</p></div>'

    pager = '<div class="pager">'
    pager += f'<a href="/card/{_e(prev_c["slug"])}">← {_e(prev_c["name_ko"])}</a>' if prev_c else "<span></span>"
    pager += f'<a href="/card/{_e(next_c["slug"])}">{_e(next_c["name_ko"])} →</a>' if next_c else "<span></span>"
    pager += "</div>"

    meaning = (c.get("meaning") or "").strip()
    upright = (seo.get("upright") or "").strip()
    intro = f"<p>{_e(meaning)}</p>" + (f"<p>{_e(upright)}</p>" if upright else "")
    body = f"""
  <div class="card-head">
    <div class="card-img">
      <img src="/images/{_e(c['image_file'])}" alt="{_e(c['name_ko'])}({_e(c['name_en'])}) 타로카드 이미지">
    </div>
    <div class="card-body">
      <h1>{_e(c['name_ko'])}</h1>
      <p class="sub">{_e(c['name_en'])} · {_e(c['suit_label'])}</p>
      <h2 style="margin-top:8px">카드의 의미</h2>
      {intro}
    </div>
  </div>
  {sym_block}
  {rev_block}
  {topic_block}
  {advice_block}
  <p style="text-align:center"><a class="cta" href="/">이 카드로 내 타로 보기 →</a></p>
  <p style="text-align:center;font-size:.85rem"><a href="/cards">← 전체 카드 도감</a></p>
  {pager}
"""
    desc_src = upright or meaning
    desc = (desc_src[:150] + "…") if len(desc_src) > 150 else desc_src
    return _shell(
        f"{c['name_ko']}({c['name_en']}) 타로카드 의미와 상징 | 울트라타로",
        desc or f"{c['name_ko']} 타로카드의 의미와 상징을 알아보세요.",
        f"{SITE_URL}/card/{c['slug']}",
        body,
        f"{SITE_URL}/images/{c['image_file']}",
    )


@app.get("/sitemap.xml")
async def sitemap():
    urls = [f"{SITE_URL}/", f"{SITE_URL}/cards", f"{SITE_URL}/legal.html"]
    urls += [f"{SITE_URL}/card/{c['slug']}" for c in load_deck()]
    items = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    return Response(content=xml, media_type="application/xml")


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"


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

    # 통화 확인 (KRW 금액으로 USD 크레딧을 받는 식의 교차 위변조 방지)
    currency = (data.get("currency") or data.get("amount", {}).get("currency") or "").upper()
    if currency.startswith("CURRENCY_"):
        currency = currency[len("CURRENCY_"):]

    # 통화별 상품표 (USD는 최소 단위=센트 기준: $0.99 -> 99)
    CREDIT_TABLE_KRW = {1000: 10, 3000: 35, 5000: 60}
    CREDIT_TABLE_USD = {99: 10, 299: 35, 499: 60}

    if currency == "USD":
        credits = CREDIT_TABLE_USD.get(paid)
    elif currency == "KRW":
        credits = CREDIT_TABLE_KRW.get(paid)
    else:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 결제 통화입니다: {currency or 'unknown'}")

    if credits is None:
        raise HTTPException(status_code=400, detail="유효하지 않은 결제 금액입니다.")

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

    # 비교 스프레드를 후보 마지막에 포함(선택 질문의 의미 기반 폴백)
    candidates = valid_spreads + [COMPARISON_SPREAD]
    comp_num = len(candidates)  # 비교 스프레드의 1-based 번호

    spread_list = "\n".join([
        f"{i+1}. {s.get('name','')} ({s.get('card_count',3)}장) - {(s.get('when_to_use') or '')[:60]}"
        for i, s in enumerate(candidates)
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
[중요] 질문이 두 개 이상의 구체적인 선택지(예: A vs B, 제품 A와 제품 B 중 어느 것, 세 가지 중 뭐가 좋을지, 이직할까 말까) 중 하나를 고르는 '선택 질문'이라면, 반드시 '선택 비교 스프레드'({comp_num}번)를 선택하세요.
또한 사용자가 고민하는 '선택지(보기)의 개수'를 정확히 세어 options_count에 담으세요. 선택 질문이 아니면 options_count는 0입니다. (번호목록·기호뿐 아니라 "제주도, 부산, 강릉 중" 같은 자유서술도 개수를 세어야 합니다.)
반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{"index": 1, "name_translated": "스프레드 이름 번역", "reason": "선택 이유", "options_count": 0}}
index는 1부터 시작합니다.
name_translated는 선택한 스프레드의 이름을 {lang_name}으로 번역한 것입니다.
reason 값과 name_translated 값은 반드시 {lang_name}으로 작성하세요."""}]
    )

    import re
    text = response.content[0].text.strip()
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        result = {"index": 1, "name_translated": "", "reason": "질문에 균형 잡힌 시각을 제공하기 위해 선택했습니다.", "options_count": 0}
    else:
        try:
            result = json.loads(m.group())
        except Exception:
            result = {"index": 1, "name_translated": "", "reason": "질문에 균형 잡힌 시각을 제공하기 위해 선택했습니다.", "options_count": 0}

    idx = max(0, min(int(result.get("index", 1)) - 1, len(candidates) - 1))
    chosen = candidates[idx]

    # 선택 질문 여부: 키워드 감지 또는 AI가 비교 스프레드 선택 또는 AI가 선택지 2개 이상으로 판단
    try:
        ai_n = int(result.get("options_count") or 0)
    except (TypeError, ValueError):
        ai_n = 0
    is_choice = is_binary_question(request.question) or (chosen is COMPARISON_SPREAD) or ai_n >= 2

    if is_choice:
        # 선택지 개수: AI 판단(우선) → 실패 시 정규식 폴백
        n = ai_n if ai_n >= 2 else count_options(request.question)
        return build_comparison_spread(n, request.language, client)

    spread = dict(chosen)
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

        # 선택 질문이거나 비교 스프레드가 선택된 경우 비교/종합판단 지시를 추가
        if is_binary_question(request.question) or "비교 스프레드" in (request.spread_name or ""):
            system_prompt += """

IMPORTANT - This is a CHOICE question where the user is deciding among two or more options. Handle it as a COMPARISON reading:
- Treat EACH card except the last one as one of the options the user listed, in the SAME order (1st card = the user's first option, 2nd card = second option, and so on). The LAST card is the synthesis/advice.
- Clearly compare the energy and the likely outcome of every option side by side.
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
