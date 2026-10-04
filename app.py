import json
import os
import re
import html as _html
import anthropic
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse, PlainTextResponse, Response, RedirectResponse
from pydantic import BaseModel
from typing import List, Optional

from tarot_i18n import SITE_LANGS, LANG_LABELS, OG_LOCALE, UI_KO, ui_overrides, minor_name

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
class CachedImageStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            response.headers["Cache-Control"] = "public, max-age=604800"
        return response


app.mount("/images", CachedImageStaticFiles(directory=os.path.join(BASE_DIR, "tarot_images")), name="images")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/saved-readings")
async def saved_readings_page():
    return FileResponse(os.path.join(BASE_DIR, "static", "saved-readings.html"))


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
# 타로 카드 도감 (SEO 유입용, 15개 언어)
#   /cards, /card/{slug}                : 한국어 (기본, 기존 URL 유지)
#   /{lang}/cards, /{lang}/card/{slug}  : 그 외 14개 언어
#   /sitemap.xml, /robots.txt
# 검색엔진이 읽을 수 있도록 서버에서 HTML을 직접 렌더링한다.
# 번역 데이터는 translate_cards.py 가 output/i18n/ 에 생성한다.
# ──────────────────────────────────────────────────────────────
SITE_URL = "https://ultratarot.com"
I18N_DIR = os.path.join(BASE_DIR, "output", "i18n")
_CARDS_CACHE = None
_I18N_CACHE = {}

_SUIT_KEYS = {"CUPS": "cups", "WANDS": "wands", "SWORDS": "swords", "PENTACLES": "pentacles"}
_SUIT_ORDER = ["CUPS", "WANDS", "SWORDS", "PENTACLES"]

# 메인 앱 네비게이션 라벨과 동일하게 맞춘다 (모델 번역보다 우선)
NAV_CARDS = {
    "ko": "전체 보기", "en": "Card Guide", "ja": "カード図鑑", "zh": "塔罗牌图鉴",
    "es": "Guía de Cartas", "fr": "Guide des Cartes", "de": "Kartenführer", "pt": "Guia de Cartas",
    "it": "Guida alle Carte", "ru": "Справочник карт", "th": "สารานุกรมไพ่", "id": "Panduan Kartu",
    "vi": "Từ điển bài", "tr": "Kart Rehberi", "pl": "Przewodnik po kartach",
}


def _slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')


def _suit_of(name_en: str) -> str:
    for key in _SUIT_ORDER:
        if key in (name_en or '').upper():
            return key
    return "MAJOR"


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
            c["suit"] = _suit_of(c.get("name_en"))
            deck.append(c)
        _CARDS_CACHE = deck
    return _CARDS_CACHE


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def get_ui(lang: str) -> dict:
    """도감 UI 문구. 번역이 없는 키는 한국어 원문으로 대체한다."""
    key = ("ui", lang)
    if key not in _I18N_CACHE:
        ui = dict(UI_KO)
        if lang != "ko":
            ui.update(_read_json(os.path.join(I18N_DIR, f"ui_{lang}.json"), {}))
            ui.update(ui_overrides(lang))          # 수트 용어·어색한 문구는 고정값이 번역보다 우선
        ui["nav_cards"] = NAV_CARDS.get(lang, ui["nav_cards"])
        _I18N_CACHE[key] = ui
    return _I18N_CACHE[key]


def get_cards_i18n(lang: str) -> dict:
    key = ("cards", lang)
    if key not in _I18N_CACHE:
        _I18N_CACHE[key] = {} if lang == "ko" else _read_json(os.path.join(I18N_DIR, f"cards_{lang}.json"), {})
    return _I18N_CACHE[key]


def lang_ready(lang: str) -> bool:
    """언어 단위로 '모든 카드의 번역이 끝난' 경우에만 공개한다.
    일부만 번역된 언어는 한글/영문 본문이 섞여 보이므로 공개하지 않는다
    (sitemap·hreflang·언어선택기에서 제외하고, 접근 시 영어판으로 보낸다)."""
    if lang == "ko":
        return True
    key = ("ready", lang)
    if key not in _I18N_CACHE:
        has_ui = os.path.exists(os.path.join(I18N_DIR, f"ui_{lang}.json"))
        tr = get_cards_i18n(lang)
        _I18N_CACHE[key] = has_ui and all(c["slug"] in tr for c in load_deck())
    return _I18N_CACHE[key]


def card_ready(lang: str, slug: str) -> bool:
    return lang_ready(lang)


def _fallback_url(path_for) -> str:
    """번역이 없는 언어로 들어온 경우의 대체 주소: 영어판 → (없으면) 한국어판."""
    return path_for("en") if lang_ready("en") else path_for("ko")


def _prefix(lang: str) -> str:
    return "" if lang == "ko" else f"/{lang}"


def cards_path(lang: str) -> str:
    return f"{_prefix(lang)}/cards"


def card_path(lang: str, slug: str) -> str:
    return f"{_prefix(lang)}/card/{slug}"


def home_path(lang: str) -> str:
    # 메인 앱은 ?lang= 값을 읽어 해당 언어로 열린다
    return "/" if lang == "ko" else f"/?lang={lang}"


def brand_of(lang: str) -> str:
    return "울트라타로" if lang == "ko" else "Ultra Tarot"


SITE_NAV = {
    "ko": ("앱 소개", "타로카드란?", "카드 도감", "저장한 리딩"),
    "en": ("About", "What is Tarot?", "Card Guide", "Saved Readings"),
    "ja": ("アプリについて", "タロットとは？", "カード図鑑", "保存したリーディング"),
    "es": ("Sobre la app", "¿Qué es el tarot?", "Guía de cartas", "Lecturas guardadas"),
    "fr": ("À propos", "Qu'est-ce que le tarot ?", "Guide des cartes", "Lectures enregistrées"),
    "de": ("Über die App", "Was ist Tarot?", "Kartenführer", "Gespeicherte Legungen"),
    "pt": ("Sobre o app", "O que é Tarot?", "Guia de cartas", "Leituras salvas"),
    "th": ("เกี่ยวกับแอป", "ไพ่ทาโรต์คืออะไร?", "คู่มือไพ่", "รายการที่บันทึกไว้"),
    "ru": ("О приложении", "Что такое Таро?", "Справочник карт", "Сохранённые расклады"),
    "zh": ("关于应用", "什么是塔罗？", "塔罗牌图鉴", "已保存的解读"),
    "it": ("Informazioni", "Cos'è il Tarot?", "Guida alle carte", "Letture salvate"),
    "id": ("Tentang aplikasi", "Apa itu Tarot?", "Panduan kartu", "Bacaan tersimpan"),
    "vi": ("Giới thiệu", "Tarot là gì?", "Hướng dẫn lá bài", "Bài đọc đã lưu"),
    "tr": ("Hakkında", "Tarot nedir?", "Kart rehberi", "Kaydedilen açılımlar"),
    "pl": ("O aplikacji", "Czym jest Tarot?", "Przewodnik po kartach", "Zapisane rozkłady"),
}


def render_site_nav(lang: str, active: str = "") -> str:
    labels = SITE_NAV.get(lang, SITE_NAV["en"])
    home = home_path(lang)
    items = f'<a class="site-brand" href="{_e(home)}">✨ {_e(brand_of(lang))}</a>'
    for url, name, key in ((cards_path(lang), labels[2], "cards"), (f"/saved-readings?lang={lang}", labels[3], "saved")):
        current = ' aria-current="page"' if key == active else ""
        items += f'<a href="{_e(url)}"{current}>{_e(name)}</a>'
    return f'<nav class="site-primary-nav" aria-label="Site">{items}</nav>'


def render_site_footer(lang: str) -> str:
    labels = SITE_NAV.get(lang, SITE_NAV["en"])
    home = home_path(lang)
    about = home + ("&" if "?" in home else "?") + "open=about"
    tarot = home + ("&" if "?" in home else "?") + "open=tarot"
    return f"""<footer class="site-footer">
  <div class="footer-inner">
    <div class="footer-links">
      <a href="{_e(about)}">{_e(labels[0])}</a>
      <a href="{_e(tarot)}">{_e(labels[1])}</a>
      <a href="/legal.html#pricing" target="_blank">이용요금</a>
      <a href="/legal.html#terms" target="_blank">이용약관</a>
      <a href="/legal.html#privacy" target="_blank">개인정보처리방침</a>
      <a href="/legal.html#refund" target="_blank">환불정책</a>
    </div>
    <div class="footer-biz">
      상호명: 회색돌 &nbsp;|&nbsp; 대표자: 박상범 &nbsp;|&nbsp; 사업자등록번호: 247-08-03432<br/>
      주소: 경기도 남양주시 양지로240번길 37, 115동 1801호 &nbsp;|&nbsp; 전화: 010-6786-8812<br/>
      통신판매업 신고번호: 2026-진접오남-0322 &nbsp;|&nbsp; 문의: ashoshostudio@gmail.com<br/>
      <span style="color:rgba(196,169,107,.7);font-size:.78rem;">모든 거래에 대한 책임과 환불, 민원 등은 <strong>회색돌</strong>에서 진행합니다. &nbsp;|&nbsp; 민원담당자: 박상범 (010-6786-8812)</span>
    </div>
    <div class="footer-copy">© 2025 울트라타로. All rights reserved.</div>
  </div>
</footer>"""


def _fmt(text: str, **kw) -> str:
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def _fmt_name(tpl: str, name: str, name_en: str, **kw) -> str:
    """{name}({name_en}) 형태 문구에서, 이름이 영문명과 같으면 괄호 부분을 생략한다."""
    if name.strip().lower() == name_en.strip().lower():
        tpl = re.sub(r"\s*[（(]\{name_en\}[）)]", "", tpl)
    return _fmt(tpl, name=name, name_en=name_en, **kw)


def suit_text(ui: dict, key: str) -> str:
    if key == "MAJOR":
        return ui["major"]
    return _fmt(ui["suit_label"], suit=ui[_SUIT_KEYS[key]])


def localize(c: dict, lang: str) -> dict:
    """카드 한 장을 해당 언어의 표시용 dict 로 변환. 번역이 없으면 ok=False 로 한국어 대체."""
    ui = get_ui(lang)
    seo = c.get("seo") or {}
    sym = c.get("symbols") or {}
    t = get_cards_i18n(lang).get(c["slug"]) if lang != "ko" else None
    if lang == "ko" or not t:
        name = c["name_ko"] if lang == "ko" else c["name_en"]
        meaning, up = (c.get("meaning") or "").strip(), (seo.get("upright") or "").strip()
        rest = {k: (seo.get(k) or "").strip() for k in ("reversed", "love", "career", "money", "advice")}
        syms = [(ui["sym_person"], sym.get("핵심인물")), (ui["sym_symbol"], sym.get("주요상징")), (ui["sym_bg"], sym.get("배경"))]
        ok = lang == "ko"
    else:
        name = minor_name(lang, c["slug"]) or t["name"]      # 소수 아르카나는 규칙 이름 우선(표기 통일)
        meaning, up = t["meaning"], t["upright"]
        rest = {k: t.get(k, "") for k in ("reversed", "love", "career", "money", "advice")}
        syms = [(ui["sym_person"], t.get("sym_person")), (ui["sym_symbol"], t.get("sym_symbol")), (ui["sym_bg"], t.get("sym_bg"))]
        ok = True
    return {"name": name, "meaning": meaning, "upright": up, "syms": [(l, v) for l, v in syms if v], "ok": ok, **rest}


def _e(s) -> str:
    return _html.escape(str(s or ''))


def _page(lang: str, title: str, desc: str, path: str, body: str, og_image: str,
          alt_paths: dict, noindex: bool = False, extra_head: str = "", active_nav: str = "cards",
          language_paths: dict | None = None) -> str:
    """도감 페이지 공통 HTML 껍데기 (본 사이트와 동일한 다크/골드 테마)."""
    ui = get_ui(lang)
    canonical = f"{SITE_URL}{path}"
    hreflangs = "".join(
        f'<link rel="alternate" hreflang="{code}" href="{SITE_URL}{p}">' for code, p in alt_paths.items()
    )
    if "en" in alt_paths:
        hreflangs += f'<link rel="alternate" hreflang="x-default" href="{SITE_URL}{alt_paths["en"]}">'
    options = "".join(
        f'<option value="{_e(p)}" data-code="{code}"{" selected" if code == lang else ""}>{_e(LANG_LABELS[code])}</option>'
        for code, p in (language_paths or alt_paths).items()
    )
    robots = "noindex, follow" if noindex else "index, follow"
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_e(title)}</title>
<meta name="description" content="{_e(desc)}">
<link rel="canonical" href="{_e(canonical)}">
{hreflangs}
<meta name="robots" content="{robots}">
<meta name="theme-color" content="#0d0d1a">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{_e(brand_of(lang))}">
<meta property="og:locale" content="{OG_LOCALE[lang]}">
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
<link rel="stylesheet" href="/static/site-shell.css?v=5">
<link rel="stylesheet" href="/static/acct-bar.css?v=3">
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0d0d1a;color:#e8e3d8;font-family:'Noto Sans KR','Noto Sans',system-ui,sans-serif;font-weight:300;line-height:1.75}}
  a{{color:#c4a96b;text-decoration:none}} a:hover{{color:#d9bf8e}}
  .wrap{{flex:1 0 auto;width:100%;max-width:900px;margin:0 auto;padding:24px 20px 80px}}
  #lang-select{{background:rgba(255,255,255,.05);color:#e8e3d8;border:1px solid rgba(196,169,107,.35);
               border-radius:7px;padding:5px 8px;font-size:.82rem;font-family:inherit;cursor:pointer}}
  #lang-select option{{background:#16122a;color:#e8e3d8}}
  @media (max-width:600px){{ .wrap{{padding-left:16px;padding-right:16px}} }}
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
  .tile img{{width:100%;height:auto;aspect-ratio:auto 3 / 5;border-radius:8px;border:1px solid rgba(196,169,107,.3);display:block;margin-bottom:7px}}
  #card-search{{width:100%;padding:13px 16px;margin-bottom:8px;border-radius:9px;
    background:rgba(255,255,255,.04);border:1px solid rgba(196,169,107,.3);
    color:#e8e3d8;font-family:inherit;font-size:.95rem}}
  #card-search:focus{{outline:none;border-color:#c4a96b}}
  #card-search::placeholder{{color:#7c8090}}
  .tile span{{font-size:.84rem;color:#e8e3d8}}
  .tile small{{display:block;color:#7c8090;font-size:.72rem}}
</style>
{extra_head}
</head>
<body class="site-shell">
<div id="acct-bar" class="site-topbar" data-lang="{_e(lang)}">
    {render_site_nav(lang, active_nav)}
    <select id="lang-select" aria-label="{_e(ui['lang_label'])}" onchange="switchLang(this)">{options}</select>
    <button id="acct-login" type="button"></button>
    <div id="acct-user">
      <span id="acct-free" class="plenty"></span>
      <a id="acct-credit" href="/"></a>
      <a id="acct-history" href="/"></a>
      <img id="acct-avatar" src="" alt="">
      <span id="acct-name"></span>
      <button id="acct-logout" type="button"></button>
    </div>
  </div>
<main class="wrap">
  {body}
</main>
{render_site_footer(lang)}
<script>
function switchLang(sel){{
  var o=sel.options[sel.selectedIndex];
  try{{localStorage.setItem('tarot-lang',o.dataset.code)}}catch(e){{}}
  location.href=o.value;
}}
</script>
<script type="module" src="/static/acct-bar.js?v=4"></script>
</body>
</html>"""


def _alt_paths_index() -> dict:
    return {code: cards_path(code) for code in SITE_LANGS if lang_ready(code)}


def _alt_paths_card(slug: str) -> dict:
    return {code: card_path(code, slug) for code in SITE_LANGS if card_ready(code, slug)}


def render_cards_index(lang: str) -> str:
    ui = get_ui(lang)
    deck = load_deck()
    n = len(deck)
    groups = [("MAJOR", _fmt(ui["major_heading"], n=sum(1 for c in deck if c["suit"] == "MAJOR")))]
    for key in _SUIT_ORDER:
        cnt = sum(1 for c in deck if c["suit"] == key)
        groups.append((key, _fmt(ui["suit_heading"], suit=ui[_SUIT_KEYS[key]], n=cnt)))

    sections = []
    for key, heading in groups:
        items = [c for c in deck if c["suit"] == key]
        if not items:
            continue
        tiles = ""
        for c in items:
            L = localize(c, lang)
            sub = "" if L["name"].strip().lower() == c["name_en"].strip().lower() else f'<small>{_e(c["name_en"])}</small>'
            thumbnail = os.path.splitext(c["image_file"])[0] + ".webp"
            tiles += (
                f'<a class="tile" href="{_e(card_path(lang, c["slug"]))}">'
                f'<img src="/images/thumbs/{_e(thumbnail)}" alt="{_e(_fmt(ui["alt_tile"], name=L["name"]))}" width="600" height="1000" loading="lazy" decoding="async">'
                f'<span>{_e(L["name"])}</span>{sub}</a>'
            )
        sections.append(f'<section class="suit-sec"><h2>{_e(heading)}</h2><div class="grid">{tiles}</div></section>')

    search = (
        f'<input id="card-search" type="search" placeholder="{_e(ui["search_ph"])}" '
        'oninput="filterCards(this.value)" autocomplete="off">'
        f'<p id="no-result" style="display:none;color:#7c8090">{_e(ui["no_result"])}</p>'
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
        f"<h1>{_e(ui['index_title'])}</h1>"
        f'<p class="sub">{_e(_fmt(ui["index_sub"], n=n))}</p>'
        + search + "".join(sections)
        + f'<p style="text-align:center"><a class="cta" href="{_e(home_path(lang))}">{_e(ui["cta_index"])}</a></p>'
    )
    return _page(
        lang,
        _fmt(ui["title_index"], n=n, brand=brand_of(lang)),
        _fmt(ui["desc_index"], n=n),
        cards_path(lang), body, f"{SITE_URL}/static/og-image.jpg", _alt_paths_index(),
    )


def render_card_detail(lang: str, slug: str) -> str:
    deck = load_deck()
    idx = next((i for i, c in enumerate(deck) if c["slug"] == slug), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Card not found")
    ui = get_ui(lang)
    c = deck[idx]
    L = localize(c, lang)
    prev_c = deck[idx - 1] if idx > 0 else None
    next_c = deck[idx + 1] if idx < len(deck) - 1 else None

    sym_html = "".join(f"<div><b>{_e(k)}</b>{_e(v)}</div>" for k, v in L["syms"])
    sym_block = f'<h2>{_e(ui["h_symbols"])}</h2><div class="sym">{sym_html}</div>' if sym_html else ""
    rev_block = f'<h2>{_e(ui["h_reversed"])}</h2><p>{_e(L["reversed"])}</p>' if L["reversed"] else ""
    topic_block = "".join(
        f'<h2>{_e(ui[hk])}</h2><p>{_e(L[k])}</p>'
        for k, hk in (("love", "h_love"), ("career", "h_career"), ("money", "h_money")) if L[k]
    )
    advice_block = (
        f'<h2>{_e(ui["h_advice"])}</h2><div class="sym"><p style="margin:0">{_e(L["advice"])}</p></div>'
        if L["advice"] else ""
    )

    def pager_link(card, arrow_left):
        name = localize(card, lang)["name"]
        label = f"← {name}" if arrow_left else f"{name} →"
        return f'<a href="{_e(card_path(lang, card["slug"]))}">{_e(label)}</a>'
    pager = '<div class="pager">'
    pager += pager_link(prev_c, True) if prev_c else "<span></span>"
    pager += pager_link(next_c, False) if next_c else "<span></span>"
    pager += "</div>"

    intro = f"<p>{_e(L['meaning'])}</p>" + (f"<p>{_e(L['upright'])}</p>" if L["upright"] else "")
    en_sub = "" if L["name"].strip().lower() == c["name_en"].strip().lower() else f"{_e(c['name_en'])} · "
    medium_image = os.path.splitext(c["image_file"])[0] + ".webp"
    body = f"""
  <div class="card-head">
    <div class="card-img">
      <img src="/images/medium/{_e(medium_image)}" alt="{_e(_fmt_name(ui['alt_card'], L['name'], c['name_en']))}">
    </div>
    <div class="card-body">
      <h1>{_e(L['name'])}</h1>
      <p class="sub">{en_sub}{_e(suit_text(ui, c['suit']))}</p>
      <h2 style="margin-top:8px">{_e(ui['h_meaning'])}</h2>
      {intro}
    </div>
  </div>
  {sym_block}
  {rev_block}
  {topic_block}
  {advice_block}
  <p style="text-align:center;font-size:.85rem"><a href="{_e(cards_path(lang))}">{_e(ui['back_all'])}</a></p>
  {pager}
"""
    desc_src = L["upright"] or L["meaning"]
    limit = 100 if lang in ("ja", "zh", "th") else 150
    desc = (desc_src[:limit] + "…") if len(desc_src) > limit else desc_src
    return _page(
        lang,
        _fmt_name(ui["title_card"], L["name"], c["name_en"], brand=brand_of(lang)),
        desc or _fmt(ui["desc_fallback"], name=L["name"]),
        card_path(lang, slug), body, f"{SITE_URL}/images/{c['image_file']}", _alt_paths_card(slug),
        noindex=not L["ok"],
    )


@app.get("/cards", response_class=HTMLResponse)
async def cards_index():
    return render_cards_index("ko")


@app.get("/card/{slug}", response_class=HTMLResponse)
async def card_detail(slug: str):
    return render_card_detail("ko", slug)


@app.get("/{lang}/cards", response_class=HTMLResponse)
async def cards_index_lang(lang: str):
    if lang == "ko":
        return RedirectResponse("/cards", status_code=301)
    if lang not in SITE_LANGS:
        raise HTTPException(status_code=404, detail="Not found")
    if not lang_ready(lang):      # 번역 준비 중 → 임시(302) 이동이라 색인에 영향 없음
        return RedirectResponse(_fallback_url(cards_path), status_code=302)
    return render_cards_index(lang)


@app.get("/{lang}/card/{slug}", response_class=HTMLResponse)
async def card_detail_lang(lang: str, slug: str):
    if lang == "ko":
        return RedirectResponse(f"/card/{slug}", status_code=301)
    if lang not in SITE_LANGS:
        raise HTTPException(status_code=404, detail="Not found")
    if not lang_ready(lang):
        return RedirectResponse(_fallback_url(lambda l: card_path(l, slug)), status_code=302)
    return render_card_detail(lang, slug)


def birth_card_path(lang: str) -> str:
    return "/birth-card" if lang == "ko" else f"/birth-card?lang={lang}"


def birth_translation(lang: str, source: dict) -> tuple[dict, dict] | None:
    if lang == "ko":
        return {card["slug"]: card for card in source.get("cards", [])}, source.get("_meta", {})
    translated = _read_json(os.path.join(BASE_DIR, "output", f"birth_cards_{lang}.json"), {})
    cards = translated.get("cards")
    meta = translated.get("_meta")
    required = {"tagline", "keywords", "personality", "strengths", "shadow", "life_lesson", "relationships", "career", "soul_note"}
    required_labels = {"personality", "strengths", "shadow", "life_lesson", "relationships", "career", "soul_note"}
    slugs = {card["slug"] for card in source.get("cards", [])}
    if (not isinstance(cards, dict) or set(cards) != slugs or not isinstance(meta, dict)
            or not isinstance(meta.get("labels"), dict)
            or not required_labels.issubset(meta["labels"])
            or not meta.get("disclaimer") or not meta.get("calculation")
            or any(not isinstance(card, dict) or not required.issubset(card) for card in cards.values())):
        return None
    return cards, meta


def render_birth_card_page(lang: str) -> str:
    source = _read_json(os.path.join(BASE_DIR, "output", "birth_cards_ko.json"), {})
    birth_cards = source.get("cards", [])
    deck = {card["slug"]: card for card in load_deck()}
    if (len(birth_cards) != 22 or {card.get("id") for card in birth_cards} != set(range(22))
            or any(card.get("slug") not in deck for card in birth_cards)):
        raise HTTPException(status_code=500, detail="Birth card data is incomplete")

    translated = birth_translation(lang, source)
    details, meta = translated if translated else ({}, {})
    guide_lang = lang if lang_ready(lang) else ("en" if lang_ready("en") else "ko")
    cards = []
    for card in birth_cards:
        deck_card = deck[card["slug"]]
        item = {
            "id": card["id"],
            "slug": card["slug"],
            "name": localize(deck_card, lang)["name"],
            "image": os.path.splitext(deck_card["image_file"])[0] + ".webp",
            "guide": card_path(guide_lang, card["slug"]),
        }
        if translated:
            item.update({key: details[card["slug"]].get(key) for key in (
                "tagline", "keywords", "personality", "strengths", "shadow",
                "life_lesson", "relationships", "career", "soul_note",
            )})
        cards.append(item)

    labels = ({"personality": "성격·성향", "strengths": "강점", "shadow": "약점·그림자",
               "life_lesson": "인생 과제", "relationships": "관계 스타일", "career": "직업 성향",
               "soul_note": "내면의 의미"} if lang == "ko" else meta.get("labels", {}))
    data = json.dumps({"cards": cards, "lang": lang, "detailed": bool(translated), "labels": labels},
                      ensure_ascii=False).replace("<", "\\u003c")
    korean = lang == "ko"
    title = ("나의 생일수 | 울트라타로" if korean else
             f"{meta.get('title', 'Birth Cards')} | Ultra Tarot")
    desc = ("생년월일로 성격 카드와 영혼 카드를 계산하고, 나를 상징하는 타로 카드를 알아보세요."
            if korean else next(iter(meta.get("calculation", [])),
                                "Find your personality and soul tarot cards from your birth date."))
    disclaimer = meta.get("disclaimer") or "This symbolic reading is for self-reflection, not a scientific personality test or a substitute for important decisions."
    body = f"""
<div id="birth-app" data-lang="{_e(lang)}">
  <h1 id="birth-title">{'나의 생일수' if korean else 'My Birth Cards'}</h1>
  <p class="sub" id="birth-intro">{_e(desc)}</p>
  <form id="birth-form" class="birth-form">
    <div id="birth-date-label" class="birth-date-label">{'생년월일' if korean else 'Date of birth'}</div>
    <div class="birth-wheel-labels" aria-hidden="true">
      <span id="birth-year-label">연도</span><span id="birth-month-label">월</span><span id="birth-day-label">일</span>
    </div>
    <div class="birth-wheel-picker" role="group" aria-labelledby="birth-date-label">
      <div id="birth-year-wheel" class="birth-wheel" role="listbox" tabindex="0" aria-labelledby="birth-year-label"></div>
      <div id="birth-month-wheel" class="birth-wheel" role="listbox" tabindex="0" aria-labelledby="birth-month-label"></div>
      <div id="birth-day-wheel" class="birth-wheel" role="listbox" tabindex="0" aria-labelledby="birth-day-label"></div>
    </div>
    <input id="birth-date" type="hidden">
    <div class="birth-controls">
      <button type="submit" id="birth-submit">{'내 카드 보기' if korean else 'Find my cards'}</button>
    </div>
    <p id="birth-privacy" class="birth-privacy">{'생년월일은 서버에 전송하거나 저장하지 않습니다.' if korean else 'Your birth date stays in this browser.'}</p>
    <p id="birth-error" role="alert" hidden></p>
  </form>
  <div id="birth-result" hidden aria-live="polite"></div>
  <p class="birth-disclaimer">{_e(disclaimer)}</p>
</div>
<script id="birth-data" type="application/json">{data}</script>
<script src="/static/birth-card.js?v=3" defer></script>
"""
    return _page(lang, title, desc, birth_card_path(lang), body,
                 f"{SITE_URL}/static/og-image.jpg",
                 {code: birth_card_path(code) for code in SITE_LANGS if birth_translation(code, source)},
                 noindex=not translated,
                 extra_head='<link rel="stylesheet" href="/static/birth-card.css?v=3">',
                 active_nav="",
                 language_paths={code: birth_card_path(code) for code in SITE_LANGS})


@app.get("/birth-card", response_class=HTMLResponse)
async def birth_card_page(lang: str = "ko"):
    if lang not in SITE_LANGS:
        raise HTTPException(status_code=404, detail="Not found")
    return render_birth_card_page(lang)


@app.get("/sitemap.xml")
async def sitemap():
    urls = [f"{SITE_URL}/", f"{SITE_URL}/legal.html"]
    birth_source = _read_json(os.path.join(BASE_DIR, "output", "birth_cards_ko.json"), {})
    for code in SITE_LANGS:
        if birth_translation(code, birth_source):
            urls.append(f"{SITE_URL}{birth_card_path(code)}")
    for code in SITE_LANGS:
        if lang_ready(code):
            urls.append(f"{SITE_URL}{cards_path(code)}")
    for c in load_deck():
        for code in SITE_LANGS:
            if card_ready(code, c["slug"]):          # 번역이 완료된 페이지만 제출
                urls.append(f"{SITE_URL}{card_path(code, c['slug'])}")
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
    mode: str = 'reading'


@app.post("/api/select-spread")
async def select_spread(request: SpreadSelectRequest):
    if request.mode == 'choice':
        return build_comparison_spread(2, request.language, anthropic.Anthropic())
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
    position_label: Optional[str] = None
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
            position_label = card.position_label or card.position_meaning
            label_text = f"\n  - 고정 자리 제목: {position_label}" if position_label else ""

            # Extract key symbols
            symbols_text = ""
            if card.symbols:
                key_symbols = list(card.symbols.items())[:3]
                symbols_text = ", ".join([f"{k}: {v[:50]}..." if len(v) > 50 else f"{k}: {v}" for k, v in key_symbols])
                symbols_text = f"\n  - 주요 상징: {symbols_text}"

            # Truncate meaning to key parts
            meaning_preview = card.meaning[:200] + "..." if len(card.meaning) > 200 else card.meaning

            cards_text += f"""
카드 {i}: {card.name_ko} ({card.name_en}){position_text}{label_text}{symbols_text}
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
- Keep each card's position meaning fixed; adapt the interpretation, not the position, to the user's question
- Title each card section with its supplied fixed position label. In Korean, copy that label exactly. In other languages, translate that label faithfully into the response language. Never invent a poetic or question-specific subtitle for a card position
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
- For each card section, use <card number: card name - fixed position label> in the response language. The heading must contain only these three elements; discuss the question-specific meaning in the paragraph below it
- Use numbers for sub-items. Example: 1) Current situation, 2) Advice
- Express emphasis naturally through sentences, not symbols

REMINDER: Your entire response must be written in {lang_name}."""

        if request.language == 'ko':
            system_prompt += "\nFor Korean card sections, use the exact heading format <1번 카드: 카드 이름 - 고정 자리 제목>, changing only the number, supplied card name, and supplied fixed label. Use native Korean counters such as '다섯 개의 컵', '여섯 개의 검', and '일곱 개의 지팡이'; never write '오개의', '육개의', or '칠개의'."

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
