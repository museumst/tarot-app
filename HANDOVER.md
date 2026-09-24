# 울트라타로(ultratarot.com) 기술 인수인계 문서

> 최종 갱신: 2026-09-25
> 이 문서는 프로젝트를 이어받는 개발자/AI가 **코드를 읽기 전에 먼저 읽어야 할 안내서**입니다.
> ⚠️ **이 저장소는 GitHub Public입니다.** 비밀번호·API 시크릿을 이 문서나 코드에 절대 적지 마세요.

---

## 1. 프로젝트 개요

- **서비스명**: 울트라타로 (https://ultratarot.com)
- **내용**: AI(Claude)가 타로 카드를 해석해주는 웹 서비스. 무료 3회 후 크레딧(유료) 차감 방식
- **사업자**: 회색돌 (대표 박상범) — 사업자·연락처 정보는 `static/index.html` 푸터와 `static/legal.html` 참조
- **저장소**: https://github.com/museumst/tarot-app (main 브랜치 단일 운영, 브랜치 전략 없음)

### 기술 스택
| 영역 | 사용 기술 |
|---|---|
| 백엔드 | Python / FastAPI / uvicorn |
| 프론트엔드 | **단일 HTML 파일** (`static/index.html`, 약 3,400줄). 빌드 도구·프레임워크 없음 |
| AI | Anthropic Claude (`claude-haiku-4-5-20251001`) |
| 인증 | Firebase Authentication (Google + 익명) |
| DB | Firebase Firestore |
| 결제 | PortOne(포트원) V2 — KG이니시스 / 카카오페이 / PayPal |
| 배포 | Railway (GitHub `main` 푸시 시 자동 배포) |

---

## 2. 실행 방법

### 로컬 실행
```bash
uvicorn app:app --reload --port 8000
```
- `.claude/launch.json`에 `tarot-api` 설정이 있음 (Claude Code preview 용)
- 접속: http://localhost:8000

### 필요한 환경변수
| 변수 | 용도 | 비고 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API 호출 | anthropic SDK가 자동으로 읽음 |
| `PORTONE_API_SECRET` | 결제 검증(서버→포트원 조회) | Railway 대시보드에 설정되어 있음 |

> 값은 Railway 환경변수와 로컬 셸에만 존재합니다. **코드에 하드코딩 금지.**

### 배포
- `main`에 push → **Railway 자동 배포**
- `Procfile`: `web: uvicorn app:app --host 0.0.0.0 --port $PORT`
- ⚠️ **과거 사고**: Railway-GitHub 연결이 끊겨 푸시해도 배포가 안 되는데 아무도 몰랐던 적이 있음. 변경이 라이브에 반영 안 되면 **Railway 연결 상태부터 확인**할 것.

---

## 3. 폴더 구조

```
tarot-project/
├── app.py                 # FastAPI 백엔드 (전부 여기에 있음)
├── Procfile               # Railway 실행 명령
├── requirements.txt       # fastapi, uvicorn, anthropic, httpx, python-multipart
├── static/
│   ├── index.html         # 프론트엔드 전체 (SPA, 단일 파일)
│   └── legal.html         # 법적 고지 5종 (탭 UI)
├── output/
│   ├── cards.json         # 타로 카드 75장 데이터
│   └── spreads.json       # 스프레드 28종 데이터
├── tarot_images/          # 카드 이미지 (78개) → /images 로 서빙
├── menual/                # KG이니시스 상점관리자 PDF 매뉴얼 (참고용)
├── extract.py, rewrite_cards.py, apply_cards.py 등
│                          # 초기 데이터 구축용 일회성 스크립트 (운영에 불필요)
└── CLAUDE.md              # 초기 데이터 추출 작업 지침 (과거 이력, 현재 운영과 무관)
```

> `preview_*.html`, `ultrataro-legal.html`, `다운로드도구` 등은 과거 작업 잔여물로 운영에 사용되지 않습니다.

---

## 4. 백엔드 (`app.py`)

정적 파일 서빙 + 4개 API. 전부 단일 파일에 있습니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | `static/index.html` 반환 |
| GET | `/legal.html` | 법적 고지 페이지 |
| GET | `/api/cards` | 카드 75장 JSON |
| GET | `/api/spreads` | 스프레드 목록 |
| POST | `/api/select-spread` | 질문 → 적합한 스프레드 선택 (Claude 호출) |
| POST | `/api/reading` | 카드 해석 생성 (Claude 스트리밍, **SSE**) |
| POST | `/api/payment/verify` | 결제 검증 후 지급할 크레딧 수 반환 |

### 마운트
- `/images` → `tarot_images/`
- `/static` → `static/`

### `/api/reading` 특이사항
- **SSE 스트리밍**(`text/event-stream`). 개행을 `\\n`으로 이스케이프해 전송하고 프론트에서 복원
- 종료 신호: `data: [DONE]`

### `/api/payment/verify` (보안상 가장 중요)
1. 포트원 API로 `payment_id` 조회
2. `status == "PAID"` 확인
3. **결제 금액이 클라이언트가 보낸 값과 일치**하는지 확인 (위변조 방지)
4. **통화(KRW/USD) 확인 후 통화별 상품표로 크레딧 산출**
   - `CREDIT_TABLE_KRW = {1000:10, 3000:35, 5000:60}`
   - `CREDIT_TABLE_USD = {99:10, 299:35, 499:60}` ← **센트 단위**
   - 통화를 확인하는 이유: KRW로 99원 결제하고 USD $0.99 상품 크레딧을 받는 **교차 위변조**를 막기 위함
5. 표에 없는 금액은 거부

> ⚠️ 크레딧은 **프론트가 Firestore에 직접 기록**합니다. 서버는 "몇 개 줄지"만 계산합니다. 보안 강화가 필요하면 서버에서 Firestore에 쓰도록 바꾸는 것을 검토하세요(현재는 Firestore 규칙으로 본인만 쓰도록 제한).

---

## 5. 프론트엔드 (`static/index.html`)

**빌드 없는 단일 HTML.** 구조를 반드시 이해하고 수정하세요.

```
<style>          ... 전체 CSS
<body>           ... 전체 마크업 (모달 포함)
<script>         (약 1163~3235줄) 일반 스크립트 — UI/결제/다국어 로직
<script type="module">  (약 3237~3417줄) Firebase (인증/Firestore)
<script src="portone browser-sdk">       포트원 V2 SDK
```

### 두 스크립트의 관계 (중요)
- **일반 스크립트**: `updateCreditBadge`, `openChargeModal`, `startPayment` 등을 **전역 함수**로 정의
- **모듈 스크립트**: Firebase를 다루며, `window.addCredits`, `window.deductCredit`, `window.currentUser` 등을 **window에 노출**해 일반 스크립트와 통신
- 즉 **두 스크립트는 `window` 전역을 통해 느슨하게 결합**되어 있습니다.

### ⚠️⚠️ 가장 중요한 함정 — TDZ (이 프로젝트에서 **두 번** 사고가 남)
일반 스크립트는 **위에서 아래로 동기 실행**됩니다. 최상위에서 즉시 실행되는 코드가 **아래쪽에 선언된 `const`를 참조하면** `ReferenceError`(Temporal Dead Zone)가 나고, **그 아래 모든 코드가 실행되지 않습니다** → 이벤트 핸들러가 전부 등록되지 않아 **버튼이 통째로 먹통**이 됩니다.

- 1차 사고: `NAV_LABELS` → 상수를 스크립트 상단으로 이동해 해결
- 2차 사고: `CONTENT_TEXT` → **부트스트랩 호출을 스크립트 맨 끝으로 이동**해 해결

**현재 규칙: 즉시 실행 코드(`buildLangDropdown(); applyLang(); window.t = t; init();`)는 스크립트 맨 아래에 있어야 합니다. 절대 위로 올리지 마세요.**

증상이 의심되면 브라우저 콘솔에서 `ReferenceError: Cannot access 'X' before initialization`을 확인하세요.

### 주요 전역 함수
| 함수 | 역할 |
|---|---|
| `init()` | 카드 로드 및 초기화 |
| `applyLang()` / `t(key)` | 다국어 UI 적용 |
| `selectCard()` / `buildDeck()` | 카드 뽑기 |
| `startReading()` | `/api/reading` SSE 수신 및 렌더링 |
| `canStartReading()` | 무료/크레딧/관리자 판정 |
| `openChargeModal()` | 충전 모달 열기 |
| `selectPayMethod(m)` | `'card'` / `'kakao'` / `'paypal'` 전환 |
| `startPayment(krw)` | 카드·카카오 결제 (포트원 `requestPayment`) |
| `initPaypalUI()` / `handlePaypalSuccess()` | PayPal SPB 결제 |
| `loadCreditHistory()` | 크레딧 이용내역 조회 |

---

## 6. 인증 (Firebase Authentication)

Firebase 프로젝트: **`tarot-7bad9`** (설정값은 `index.html`에 그대로 있음 — 공개되어도 되는 값)

### 로그인 방식 2가지
1. **Google 로그인** (`signInWithPopup`) — 일반 사용자
2. **익명 로그인** (`signInAnonymously`) — 헤더의 **"🛒 비회원 결제"** 버튼

### 익명(비회원) 로그인이 존재하는 이유 (중요)
- Google 계정은 **낯선 기기/위치에서 로그인하면 Google이 SMS 본인인증을 요구**합니다. 이건 우리가 끌 수 없습니다.
- 그 결과 **카카오페이 심사자가 테스트 계정으로 로그인할 수 없었습니다.**
- 그래서 **로그인 없이 결제창까지 도달하는 경로**로 익명 로그인을 도입했습니다.
- 부수 효과: 외국인 고객도 로그인 없이 결제 가능

### 익명 사용자 처리 시 주의
- `user.email`, `user.displayName`이 **`null`** 입니다.
- **KG이니시스 V2 카드결제는 구매자 이메일이 필수**이므로, 익명 사용자에게는 `guest_<uid앞16자>@ultratarot.com` 형태의 **placeholder 이메일**을 만들어 넘깁니다. (`startPayment` 참조)
- 표시 이름은 `'비회원'`

### 관리자
- `ADMIN_EMAILS = ['museumst@gmail.com']`
- 관리자는 **무료 무제한**(크레딧 차감 없음). 단, 크레딧 잔액은 정상 로드되어 결제 테스트가 가능합니다.

---

## 7. 데이터베이스 (Firestore)

### 스키마
```
users/{uid}
  ├─ email:      string | null(익명)
  ├─ free_used:  number   # 사용한 무료 리딩 횟수
  ├─ credits:    number   # 보유 크레딧
  └─ created_at: timestamp

users/{uid}/creditHistory/{autoId}     # 크레딧 이용내역
  ├─ type:       'charge' | 'use'
  ├─ credits:    number    # 충전 +N, 사용 -1
  ├─ currency:   'KRW' | 'USD'
  ├─ amount:     number    # 실제 결제 금액 (KRW는 1000, USD는 0.99)
  ├─ amount_krw: number|null  # 구버전 호환 필드
  ├─ purpose:    string
  └─ date:       serverTimestamp
```

> `currency`/`amount`는 나중에 추가된 필드입니다. **`currency`가 없는 과거 기록은 KRW로 간주**해 표시합니다 (`fmtHistoryAmount()`).

### 보안 규칙 (Firebase 콘솔에서 관리, 저장소에 파일 없음)
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{uid} {
      allow read, write: if request.auth != null && request.auth.uid == uid;
      match /creditHistory/{docId} {
        allow read, write: if request.auth != null && request.auth.uid == uid;
      }
    }
  }
}
```
⚠️ **Firestore 규칙은 하위 컬렉션에 자동 상속되지 않습니다.** `creditHistory` 규칙을 빠뜨려 "Missing or insufficient permissions" 오류가 났던 사고가 있었습니다.

---

## 8. 크레딧 / 무료 정책

- **무료 3회** (`FREE_LIMIT = 3`) — 일반 스크립트와 모듈 스크립트에 **각각 선언되어 있으니 바꿀 때 둘 다** 수정
- 무료 소진 후 크레딧 차감 (현재 **1크레딧 = 리딩 1회 = 100원**)
- 크레딧 유효기간 **1년** (미사용 시 소멸) — 법적 고지에 명시됨. **자동 소멸 로직은 미구현**(수동/배치 필요)
- 관리자는 차감 없음

### 현재 판매 상품
| 상품 | 크레딧 | USD(PayPal) |
|---|---|---|
| 1,000원 | 10회 | $0.99 (99센트) |
| 3,000원 | 35회 | $2.99 (299센트) |
| 5,000원 | 60회 | $4.99 (499센트) |

> 📌 **가격 개편이 예정되어 있습니다.** 아래 12번 참조.

---

## 9. 결제 (PortOne V2)

**상점 ID**: `store-62ed5f10-8b20-4a78-90f1-8b1bd9d6b313`
채널키는 `static/index.html` 상단 "포트원 v2 설정" 블록에 모여 있습니다. (클라이언트에 노출되는 값이라 비밀이 아님)

| 수단 | PG | 상태 | 비고 |
|---|---|---|---|
| 신용카드 | KG이니시스 (`inicis_v2`) | ✅ **실연동 운영 중** | MID `MOI4572511` |
| 카카오페이 | kakaopay | ⏳ **심사 중 / 코드에 테스트키** | 아래 ⚠️ |
| PayPal | `paypal_v2` (SPB) | ✅ **실연동 완료** | 해외 전용 |

### ⚠️ 카카오페이 — 반드시 확인할 것
현재 코드의 `PORTONE_KAKAO_KEY`는 **테스트 채널키**입니다. 카카오페이 심사가 완료되면 **실연동 채널키로 교체해야 실제 결제가 됩니다.** (2026-09-22 기준 포트원에서 "실운영모드 설정 안내" 메일 수신 → 콘솔에서 실연동 채널 확인 필요)

### 결제 흐름 A — 카드 / 카카오페이
`startPayment(krw)` → `PortOne.requestPayment()` → 성공 시 `/api/payment/verify` → `window.addCredits()`

- 카드 결제는 **휴대폰 번호 필수**(이니시스). 번호 없이 누르면 입력창이 흔들리며 안내
- 충전 버튼은 **항상 활성화 상태로 표시**합니다 (카카오페이 심사에서 "결제버튼 활성화" 요건 때문). 검증은 클릭 시 수행

### 결제 흐름 B — PayPal (완전히 다름)
PayPal은 `requestPayment`가 **아니라** 버튼을 미리 렌더링하는 방식입니다.

- `PortOne.loadPaymentUI({ uiType: 'PAYPAL_SPB', ... })` → `<div class="portone-ui-container">`에 PayPal 버튼 렌더
- 금액 변경 시 재렌더링하지 않고 **`PortOne.updateLoadPaymentUIRequest()`** 로 갱신
- 콜백 `onPaymentSuccess` / `onPaymentFail`
- **통화는 `'CURRENCY_USD'`**, **금액은 최소단위(센트)** — `$0.99 → 99`
- 성공 시 `handlePaypalSuccess()` → 서버 검증 → 크레딧 지급

### ⚠️ PayPal 정책 제약 (중요)
1. **판매자·구매자가 모두 한국이면 결제 불가** (PayPal 정책). 그래서 **한국어가 아닐 때만 PayPal 탭을 노출**합니다 (`updateChargeLangUI()`).
2. 따라서 **한국 카드·한국 PayPal 계정으로는 테스트 자체가 불가능**합니다.
   - 테스트하려면: 포트원 **테스트 채널키**(`channel-key-46fd9e40-55b1-4e8d-bfb1-7aa990108d22`) + **국가가 US인 PayPal 샌드박스 구매자 계정**
3. 수수료 **4.4% + 고정 $0.30** (+환전 4%) → **$0.99는 수수료 비중이 약 35%**. 소액 상품에 불리
4. PayPal이 디지털 상품에 **STC API(판매자 보호)** 연동을 권장 — **미구현**

---

## 10. 다국어 (15개 언어)

`ko, en, ja, es, fr, de, pt, th, ru, zh, it, id, vi, tr, pl`

- **`TRANSLATIONS`**: UI 레이블 (`t('key')`)
- **`CONTENT_TEXT`**: 충전 모달·안내 콘텐츠 (`getCT()`)
- 리딩 결과는 백엔드에서 `LANG_NAMES`로 언어를 지정해 **Claude가 해당 언어로 생성**

> ⚠️ 스프레드의 `positions` 의미는 **한국어일 때만** 원문을 사용하고, 다른 언어는 "Card 1" 같은 일반 레이블을 씁니다. 그래서 다국어 해석 품질은 **리딩 프롬프트**에 의존합니다.

---

## 11. 타로 도메인 로직

### 스프레드 선택 (`/api/select-spread`)
질문을 Claude에게 보내 28종 중 적합한 것을 고르게 합니다.

### 양자택일(선택) 질문 특별 처리
"A vs B", "이직할까 말까", "제주도·부산·강릉 중 어디" 같은 **선택 질문**을 감지해 **비교 스프레드**를 동적으로 생성합니다.

- `is_binary_question()` — 키워드 기반 1차 감지 (한/영/일/중)
- `count_options()` — 번호목록(`1. 2. 3.`)·기호(`①②③`)·구분자(`vs`) 로 선택지 개수 추정
- **AI 의미 판단** — 스프레드 선택 Claude 호출이 `options_count`를 함께 반환 (자유서술 "A, B, C 중" 대응)
- `build_comparison_spread(n)` — **선택지 n개 + 종합 조언 1장 = n+1장** 스프레드 동적 생성 (최대 5지선다)
- 리딩 프롬프트에 "마지막 카드 제외 각 카드 = 사용자가 나열한 선택지(순서대로)" 지시 추가

---

## 12. 현재 진행 상황 & 다음 할 일

### 진행 중
| 항목 | 상태 |
|---|---|
| KG이니시스 | ✅ 완료 — 실결제 정상 |
| PayPal | ✅ 완료 — 샌드박스 검증 완료, 실연동키 적용 |
| **카카오페이** | ⏳ **심사 중** (9/1 보완서류 회신, 영업일 2~3주) |
| 한국결제네트웍스(퍼스트페이) | 🗑️ 불필요 — 방치 시 자동 취소 |

### 즉시 해야 할 일
1. **카카오페이 실연동 채널키 교체** (심사 완료 후) — `PORTONE_KAKAO_KEY`
2. **결제·환불 테스트** — 포트원이 서비스 오픈 전 필수로 요구. 환불은 앱에 기능이 없으므로 **포트원 콘솔 결제내역에서 취소**

### 예정된 가격 개편 (사용자 확정, **카카오페이 심사 완료 후** 적용)
회당 **200원**으로 인상하고 1,000원 티어 폐지:

| 상품 | 크레딧 | 회당 |
|---|---|---|
| 3,000원 | 15회 | 200원 |
| 5,000원 | 28회 | 178.6원 |
| 10,000원 | 60회 | 166.7원 |

- USD 가격은 **미정** (적용 시 재확인 필요)
- **심사 중 변경 금지**: 카카오페이에 제출한 상품 캡쳐와 달라지면 심사에 문제가 생깁니다
- 수정할 곳: `CREDIT_TABLE_JS`, `KRW_TO_USD_CENTS`, `USD_LABEL`, 충전 모달 금액 옵션(`data-krw`, `opt-amt-*`), 15개 언어 문구, `app.py`의 `CREDIT_TABLE_KRW`/`CREDIT_TABLE_USD`, `legal.html` 이용요금 페이지

### 검토 과제
- 크레딧 1년 소멸 **자동 처리 미구현**
- PayPal **STC API** 미연동
- 결제 **웹훅** 미연동 (PayPal은 pending 상태가 있어 포트원이 웹훅을 권장)
- 크레딧 지급을 **서버 주도**로 옮길지 검토

---

## 13. 과거에 실제로 겪은 함정 모음 (재발 방지)

| 증상 | 원인 | 해결 |
|---|---|---|
| **버튼이 전부 먹통** | TDZ — 아래에 선언된 `const`를 위에서 참조해 스크립트 전체 중단 | 부트스트랩 호출을 스크립트 **맨 끝**으로 |
| 결제창 `V016 signkey 오류` | 포트원 콘솔의 signkey가 KG 원본과 **한 글자(대문자 I ↔ 소문자 l)** 달랐음 | KG 값을 **복사-붙여넣기**로 교체 (타이핑 금지) |
| 이용내역 `Missing or insufficient permissions` | Firestore 규칙이 **하위 컬렉션에 상속되지 않음** | `creditHistory` 규칙 별도 추가 |
| 비회원 결제 시 `customer.email` 오류 | 익명 사용자는 email이 `null`인데 **이니시스는 이메일 필수** | placeholder 이메일 생성 |
| PayPal "한국 계정 간 결제 불가" | PayPal 정책 (판매자·구매자 모두 한국) | 비한국어에만 노출 + 샌드박스로 테스트 |
| 배포해도 반영 안 됨 | **Railway-GitHub 연결 끊김** | Railway 연결 상태 확인 |
| 심사자가 로그인 불가 | Google의 낯선 기기 본인인증 (우리가 못 끔) | 익명 로그인(비회원 결제) 도입 |

---

## 14. 비밀정보 위치 (값은 여기 적지 말 것)

| 항목 | 위치 |
|---|---|
| `ANTHROPIC_API_KEY` | Railway 환경변수 / 로컬 셸 |
| `PORTONE_API_SECRET` | Railway 환경변수 |
| PayPal API 자격증명 | PayPal 비즈니스 계정 (V2/SPB에서는 사용 안 함) |
| KG이니시스 signkey 등 | KG 상점관리자 ↔ 포트원 콘솔 채널 설정 |
| 심사용 테스트 계정 | **별도 전달** (저장소에 기록 금지) |
| Firestore 보안 규칙 | Firebase 콘솔 (저장소에 파일 없음) |

### 외부 콘솔
- Firebase: 프로젝트 `tarot-7bad9`
- 포트원: admin.portone.io
- KG이니시스 상점관리자: iniweb.inicis.com (MID `MOI4572511`)
- 카카오페이 파트너어드민: pg.kakao.com (심사 통과 후 로그인 가능)
- Railway: 배포

---

## 15. 인수인계 받은 사람에게 권하는 첫 작업 순서

1. 로컬에서 `uvicorn app:app --reload --port 8000` 실행해 동작 확인
2. `static/index.html`의 **스크립트 2개 블록 경계**와 `window.*` 결합 구조 파악
3. `app.py`의 `/api/payment/verify` 로직 이해 (돈이 걸린 부분)
4. **13번 함정 목록**을 반드시 읽을 것 — 같은 실수가 두 번 난 적이 있음
5. 카카오페이 심사 결과 확인 → 실연동 채널키 교체 → 결제·환불 테스트
6. 그 다음 가격 개편 적용
