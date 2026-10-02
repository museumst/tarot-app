"""
카드 도감 다국어 공통 정의 (서버 app.py 와 번역 스크립트 translate_cards.py 가 함께 사용)

- UI_KO 는 도감 페이지 문구의 '원문(한국어)'이다. 다른 언어는 이 원문을 번역해
  output/i18n/ui_{lang}.json 으로 저장한다. 문구를 추가/수정하면 translate_cards.py 로
  다시 번역해야 한다 (UI 문구만: python3 translate_cards.py --ui-only --force).
- {n} {suit} {name} {name_en} {brand} 는 자리표시자로, 번역 시 그대로 보존되어야 한다.
"""

SITE_LANGS = ["ko", "en", "ja", "es", "fr", "de", "pt", "th", "ru", "zh", "it", "id", "vi", "tr", "pl"]
TRANSLATE_LANGS = [l for l in SITE_LANGS if l != "ko"]

LANG_NAMES = {
    "en": "English", "ja": "Japanese", "es": "Spanish", "fr": "French", "de": "German",
    "pt": "Brazilian Portuguese", "th": "Thai", "ru": "Russian", "zh": "Simplified Chinese",
    "it": "Italian", "id": "Indonesian", "vi": "Vietnamese", "tr": "Turkish", "pl": "Polish",
}

# 언어 선택 드롭다운에 표시할 자국어 표기
LANG_LABELS = {
    "ko": "한국어", "en": "English", "ja": "日本語", "es": "Español", "fr": "Français",
    "de": "Deutsch", "pt": "Português", "th": "ไทย", "ru": "Русский", "zh": "中文",
    "it": "Italiano", "id": "Bahasa Indonesia", "vi": "Tiếng Việt", "tr": "Türkçe", "pl": "Polski",
}

OG_LOCALE = {
    "ko": "ko_KR", "en": "en_US", "ja": "ja_JP", "es": "es_ES", "fr": "fr_FR", "de": "de_DE",
    "pt": "pt_BR", "th": "th_TH", "ru": "ru_RU", "zh": "zh_CN", "it": "it_IT", "id": "id_ID",
    "vi": "vi_VN", "tr": "tr_TR", "pl": "pl_PL",
}

UI_KO = {
    "nav_cards": "전체 보기",
    "nav_home": "나가기↩︎",
    "index_title": "타로 카드 도감",
    "index_sub": "타로 카드 {n}장의 의미와 상징을 정리했습니다. 카드를 눌러 자세한 해설을 확인하세요.",
    "search_ph": "카드 이름으로 검색...",
    "no_result": "검색 결과가 없습니다.",
    "major_heading": "메이저 아르카나 ({n}장)",
    "suit_heading": "{suit} 수트 ({n}장)",
    "major": "메이저 아르카나",
    "suit_label": "{suit} 수트",
    "cups": "컵",
    "wands": "완드",
    "swords": "소드",
    "pentacles": "펜타클",
    "cta_index": "내 타로 보러 가기 →",
    "cta_card": "이 카드로 내 타로 보기 →",
    "back_all": "← 전체 카드 도감",
    "h_meaning": "카드의 의미",
    "h_symbols": "카드 속 상징",
    "h_reversed": "역방향으로 나왔을 때",
    "h_love": "연애·인간관계",
    "h_career": "직장·진로",
    "h_money": "금전·재물",
    "h_advice": "이 카드의 조언",
    "sym_person": "핵심인물",
    "sym_symbol": "주요상징",
    "sym_bg": "배경",
    "footer_tagline": "AI가 읽어주는 타로 카드",
    "footer_terms": "이용약관",
    "footer_privacy": "개인정보처리방침",
    "alt_card": "{name}({name_en}) 타로카드 이미지",
    "alt_tile": "{name} 타로카드",
    "title_index": "타로 카드 의미 총정리 — 타로카드 {n}장 도감 | {brand}",
    "desc_index": "타로 카드 {n}장의 의미와 상징을 한눈에. 메이저 아르카나부터 컵·완드·소드·펜타클까지 카드별 해설을 확인하세요.",
    "title_card": "{name}({name_en}) 타로카드 의미와 상징 | {brand}",
    "desc_fallback": "{name} 타로카드의 의미와 상징을 알아보세요.",
    "lang_label": "언어",
}


# ── 타로 용어 고정 용어집 ─────────────────────────────────────────
# 같은 페이지 안에서 카드 본문과 UI의 용어가 갈리지 않도록 언어별로 고정한다.
# (순서: 컵, 완드, 소드, 펜타클)
SUIT_TERMS = {
    "ko": ("컵", "완드", "소드", "펜타클"),
    "en": ("Cups", "Wands", "Swords", "Pentacles"),
    "ja": ("カップ", "ワンド", "ソード", "ペンタクル"),
    "es": ("Copas", "Bastos", "Espadas", "Pentáculos"),
    "fr": ("Coupes", "Bâtons", "Épées", "Pentacles"),
    "de": ("Kelche", "Stäbe", "Schwerter", "Münzen"),
    "pt": ("Copas", "Paus", "Espadas", "Ouros"),
    "th": ("ถ้วย", "ไม้เท้า", "ดาบ", "เหรียญ"),
    "ru": ("Кубки", "Жезлы", "Мечи", "Пентакли"),
    "zh": ("圣杯", "权杖", "宝剑", "星币"),
    "it": ("Coppe", "Bastoni", "Spade", "Denari"),
    "id": ("Cups", "Wands", "Swords", "Pentacles"),
    "vi": ("Cốc", "Gậy", "Kiếm", "Tiền"),
    "tr": ("Kupalar", "Değnekler", "Kılıçlar", "Tılsımlar"),
    "pl": ("Puchary", "Buławy", "Miecze", "Pentakle"),
}


def suit_glossary_line(lang):
    """번역 프롬프트에 넣을 용어 고정 문구."""
    c, w, s, p = SUIT_TERMS[lang]
    return "컵=%s, 완드=%s, 소드=%s, 펜타클=%s" % (c, w, s, p)


# 모델 번역이 어색한 UI 문구는 언어별로 고정 (app.get_ui 에서 번역보다 우선 적용)
UI_OVERRIDES = {
    "fr": {"suit_label": "Les {suit}", "suit_heading": "Les {suit} ({n} cartes)"},
    "de": {"suit_label": "{suit}", "suit_heading": "{suit} ({n} Karten)"},
}


def ui_overrides(lang):
    c, w, s, p = SUIT_TERMS[lang]
    o = {"cups": c, "wands": w, "swords": s, "pentacles": p}
    o.update(UI_OVERRIDES.get(lang, {}))
    return o


# ── 소수 아르카나 카드 이름 규칙 ──────────────────────────────────
# 카드별로 독립 번역하면 같은 규칙의 이름이 제각각이 된다(예: "Le Deux d'Épées" / "Quatre de Coupes").
# 소수 아르카나는 '숫자 + 수트'로 완전히 정해지므로 언어별 규칙으로 이름을 생성해 번역보다 우선 적용한다.
# ranks 순서: 에이스, 2~10, 시종(Page), 기사(Knight), 여왕(Queen), 왕(King)
_RANK_WORDS = ["ace", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
               "page", "knight", "queen", "king"]
_SUIT_SLUG = {"cups": 0, "wands": 1, "swords": 2, "pentacles": 3}

MINOR_NAMES = {
    "fr": {"fmt": "{rank} de {suit}", "elide": True,
           "ranks": ["As", "Deux", "Trois", "Quatre", "Cinq", "Six", "Sept", "Huit", "Neuf", "Dix",
                     "Valet", "Cavalier", "Reine", "Roi"]},
    "es": {"fmt": "{rank} de {suit}",
           "ranks": ["As", "Dos", "Tres", "Cuatro", "Cinco", "Seis", "Siete", "Ocho", "Nueve", "Diez",
                     "Sota", "Caballero", "Reina", "Rey"]},
    "ja": {"fmt": "{suit}の{rank}",
           "ranks": ["エース", "2", "3", "4", "5", "6", "7", "8", "9", "10",
                     "ペイジ", "ナイト", "クイーン", "キング"]},
    "zh": {"fmt": "{suit}{rank}",
           "ranks": ["王牌", "二", "三", "四", "五", "六", "七", "八", "九", "十", "侍从", "骑士", "王后", "国王"]},
    "de": {"fmt": "{rank} der {suit}",
           "ranks": ["Ass", "Zwei", "Drei", "Vier", "Fünf", "Sechs", "Sieben", "Acht", "Neun", "Zehn",
                     "Bube", "Ritter", "Königin", "König"]},
    "pt": {"fmt": "{rank} de {suit}",
           "ranks": ["Ás", "Dois", "Três", "Quatro", "Cinco", "Seis", "Sete", "Oito", "Nove", "Dez",
                     "Valete", "Cavaleiro", "Rainha", "Rei"]},
    "ru": {"fmt": "{rank} {suit}",
           "suits": ("Кубков", "Жезлов", "Мечей", "Пентаклей"),     # 속격 복수
           "ranks": ["Туз", "Двойка", "Тройка", "Четвёрка", "Пятёрка", "Шестёрка", "Семёрка", "Восьмёрка",
                     "Девятка", "Десятка", "Паж", "Рыцарь", "Королева", "Король"]},
    "th": {"fmt": "{rank}{suit}",
           "ranks": ["เอซ", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า", "สิบ",
                     "เพจ", "อัศวิน", "ราชินี", "ราชา"]},
    "it": {"fmt": "{rank} di {suit}",
           "ranks": ["Asso", "Due", "Tre", "Quattro", "Cinque", "Sei", "Sette", "Otto", "Nove", "Dieci",
                     "Fante", "Cavaliere", "Regina", "Re"]},
    "vi": {"fmt": "{rank} {suit}",
           "ranks": ["Át", "Hai", "Ba", "Bốn", "Năm", "Sáu", "Bảy", "Tám", "Chín", "Mười",
                     "Thị Đồng", "Kỵ Sĩ", "Nữ Hoàng", "Vua"]},
    "id": {"fmt": "{rank} of {suit}",      # 인도네시아 타로 커뮤니티는 영어 명칭을 그대로 쓴다
           "ranks": ["Ace", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                     "Page", "Knight", "Queen", "King"]},
    "tr": {"fmt": "{suit} {rank}",
           "suits": ("Kupa", "Değnek", "Kılıç", "Tılsım"),           # 합성어에서는 단수형
           "ranks": ["Ası", "İkilisi", "Üçlüsü", "Dörtlüsü", "Beşlisi", "Altılısı", "Yedilisi", "Sekizlisi",
                     "Dokuzlusu", "Onlusu", "Uşağı", "Şövalyesi", "Kraliçesi", "Kralı"]},
    "pl": {"fmt": "{rank} {suit}",
           "suits": ("Pucharów", "Buław", "Mieczy", "Pentakli"),    # 속격 복수
           "ranks": ["As", "Dwójka", "Trójka", "Czwórka", "Piątka", "Szóstka", "Siódemka", "Ósemka",
                     "Dziewiątka", "Dziesiątka", "Paź", "Rycerz", "Królowa", "Król"]},
}


def minor_name(lang, slug):
    """소수 아르카나면 규칙으로 만든 이름을, 아니면(메이저 등) None 을 반환."""
    spec = MINOR_NAMES.get(lang)
    parts = (slug or "").split("-of-")
    if not spec or len(parts) != 2 or parts[0] not in _RANK_WORDS or parts[1] not in _SUIT_SLUG:
        return None
    rank = spec["ranks"][_RANK_WORDS.index(parts[0])]
    suit = spec.get("suits", SUIT_TERMS[lang])[_SUIT_SLUG[parts[1]]]
    name = spec["fmt"].format(rank=rank, suit=suit)
    if spec.get("elide"):
        import re
        name = re.sub(r" de ([AEIOUÀÂÉÈÊÎÔÛaeiou])", r" d'\1", name)
    return name
