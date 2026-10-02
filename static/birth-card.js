const BIRTH_UI_KEYS = ['title', 'intro', 'date', 'submit', 'personality', 'soul', 'bridge', 'both', 'guide', 'limited', 'invalid', 'future', 'privacy'];
const BIRTH_UI = {
  ko: ['나의 생일수', '생년월일로 성격 카드와 영혼 카드를 찾아보세요.', '생년월일', '내 카드 보기', '성격 카드', '영혼 카드', '중간 카드', '성격·영혼 카드', '카드 도감에서 보기 →', '', '올바른 생년월일을 입력하세요.', '미래 날짜는 입력할 수 없습니다.', '생년월일은 서버에 전송하거나 저장하지 않습니다.'],
  en: ['My Birth Cards', 'Find your personality and soul cards from your birth date.', 'Date of birth', 'Find my cards', 'Personality card', 'Soul card', 'Intermediate card', 'Personality & soul card', 'View in card guide →', 'Detailed birth-card interpretations are currently available in Korean.', 'Enter a valid birth date.', 'Future dates are not allowed.', 'Your birth date stays in this browser.'],
  ja: ['私の誕生カード', '生年月日から性格カードと魂のカードを調べましょう。', '生年月日', 'カードを見る', '性格カード', '魂のカード', '中間カード', '性格・魂のカード', 'カード図鑑で見る →', '詳しい誕生カードの解説は現在韓国語のみです。', '正しい生年月日を入力してください。', '未来の日付は入力できません。', '生年月日は送信・保存されません。'],
  es: ['Mis cartas de nacimiento', 'Descubre tus cartas de personalidad y alma.', 'Fecha de nacimiento', 'Ver mis cartas', 'Carta de personalidad', 'Carta del alma', 'Carta intermedia', 'Carta de personalidad y alma', 'Ver en la guía →', 'Las interpretaciones detalladas solo están disponibles en coreano.', 'Introduce una fecha válida.', 'No se permiten fechas futuras.', 'Tu fecha no se envía ni se guarda.'],
  fr: ['Mes cartes de naissance', 'Découvrez vos cartes de personnalité et d’âme.', 'Date de naissance', 'Voir mes cartes', 'Carte de personnalité', 'Carte de l’âme', 'Carte intermédiaire', 'Carte de personnalité et d’âme', 'Voir dans le guide →', 'Les interprétations détaillées sont disponibles uniquement en coréen.', 'Saisissez une date valide.', 'Les dates futures ne sont pas autorisées.', 'Votre date n’est ni envoyée ni enregistrée.'],
  de: ['Meine Geburtskarten', 'Entdecke deine Persönlichkeits- und Seelenkarte.', 'Geburtsdatum', 'Karten anzeigen', 'Persönlichkeitskarte', 'Seelenkarte', 'Zwischenkarte', 'Persönlichkeits- und Seelenkarte', 'Im Kartenführer ansehen →', 'Ausführliche Deutungen sind derzeit nur auf Koreanisch verfügbar.', 'Gib ein gültiges Datum ein.', 'Ein zukünftiges Datum ist nicht erlaubt.', 'Dein Geburtsdatum wird nicht gesendet oder gespeichert.'],
  pt: ['Minhas cartas de nascimento', 'Descubra suas cartas da personalidade e da alma.', 'Data de nascimento', 'Ver minhas cartas', 'Carta da personalidade', 'Carta da alma', 'Carta intermediária', 'Carta da personalidade e da alma', 'Ver no guia →', 'As interpretações detalhadas estão disponíveis apenas em coreano.', 'Insira uma data válida.', 'Datas futuras não são permitidas.', 'Sua data não é enviada nem salva.'],
  th: ['ไพ่ประจำวันเกิดของฉัน', 'ค้นหาไพ่บุคลิกภาพและไพ่จิตวิญญาณจากวันเกิด', 'วันเกิด', 'ดูไพ่ของฉัน', 'ไพ่บุคลิกภาพ', 'ไพ่จิตวิญญาณ', 'ไพ่ขั้นกลาง', 'ไพ่บุคลิกภาพและจิตวิญญาณ', 'ดูในคู่มือไพ่ →', 'คำอธิบายโดยละเอียดมีเฉพาะภาษาเกาหลีในขณะนี้', 'กรุณากรอกวันเกิดที่ถูกต้อง', 'ไม่สามารถเลือกวันที่ในอนาคตได้', 'วันเกิดจะไม่ถูกส่งหรือบันทึก'],
  ru: ['Мои карты рождения', 'Узнайте свои карты личности и души по дате рождения.', 'Дата рождения', 'Показать карты', 'Карта личности', 'Карта души', 'Промежуточная карта', 'Карта личности и души', 'Смотреть в справочнике →', 'Подробные толкования пока доступны только на корейском.', 'Введите верную дату.', 'Будущая дата недопустима.', 'Дата рождения не отправляется и не сохраняется.'],
  zh: ['我的生日牌', '根据出生日期查找人格牌与灵魂牌。', '出生日期', '查看我的牌', '人格牌', '灵魂牌', '中间牌', '人格与灵魂牌', '查看牌义 →', '详细生日牌解读目前仅提供韩语版本。', '请输入有效的出生日期。', '不能输入未来日期。', '出生日期不会发送或保存。'],
  it: ['Le mie carte di nascita', 'Scopri le tue carte della personalità e dell’anima.', 'Data di nascita', 'Mostra le carte', 'Carta della personalità', 'Carta dell’anima', 'Carta intermedia', 'Carta della personalità e dell’anima', 'Vedi nella guida →', 'Le interpretazioni dettagliate sono disponibili solo in coreano.', 'Inserisci una data valida.', 'Non sono ammesse date future.', 'La data non viene inviata né salvata.'],
  id: ['Kartu kelahiran saya', 'Temukan kartu kepribadian dan jiwa dari tanggal lahir.', 'Tanggal lahir', 'Lihat kartu saya', 'Kartu kepribadian', 'Kartu jiwa', 'Kartu perantara', 'Kartu kepribadian dan jiwa', 'Lihat panduan kartu →', 'Penjelasan lengkap saat ini hanya tersedia dalam bahasa Korea.', 'Masukkan tanggal yang valid.', 'Tanggal di masa depan tidak diperbolehkan.', 'Tanggal lahir tidak dikirim atau disimpan.'],
  vi: ['Lá bài ngày sinh của tôi', 'Tìm lá bài tính cách và tâm hồn theo ngày sinh.', 'Ngày sinh', 'Xem lá bài', 'Lá bài tính cách', 'Lá bài tâm hồn', 'Lá bài trung gian', 'Lá bài tính cách và tâm hồn', 'Xem trong hướng dẫn →', 'Phần giải thích chi tiết hiện chỉ có bằng tiếng Hàn.', 'Nhập ngày sinh hợp lệ.', 'Không thể chọn ngày trong tương lai.', 'Ngày sinh không được gửi hoặc lưu.'],
  tr: ['Doğum kartlarım', 'Doğum tarihinizden kişilik ve ruh kartlarınızı bulun.', 'Doğum tarihi', 'Kartlarımı göster', 'Kişilik kartı', 'Ruh kartı', 'Ara kart', 'Kişilik ve ruh kartı', 'Kart rehberinde gör →', 'Ayrıntılı yorumlar şu anda yalnızca Korece mevcuttur.', 'Geçerli bir tarih girin.', 'Gelecek bir tarih seçilemez.', 'Doğum tarihiniz gönderilmez veya kaydedilmez.'],
  pl: ['Moje karty urodzenia', 'Poznaj karty osobowości i duszy ze swojej daty urodzenia.', 'Data urodzenia', 'Pokaż karty', 'Karta osobowości', 'Karta duszy', 'Karta pośrednia', 'Karta osobowości i duszy', 'Zobacz w przewodniku →', 'Szczegółowe interpretacje są na razie dostępne tylko po koreańsku.', 'Wpisz poprawną datę.', 'Nie można wybrać przyszłej daty.', 'Data urodzenia nie jest wysyłana ani zapisywana.'],
};
const BIRTH_EXTRA = {
  ko: ['계산 방법', '숫자 흐름'], en: ['How it works', 'Number path'],
  ja: ['計算方法', '数字の流れ'], es: ['Cómo se calcula', 'Secuencia numérica'],
  fr: ['Méthode de calcul', 'Suite des nombres'], de: ['Berechnung', 'Zahlenfolge'],
  pt: ['Como calcular', 'Sequência numérica'], th: ['วิธีคำนวณ', 'ลำดับตัวเลข'],
  ru: ['Как рассчитать', 'Числовой путь'], zh: ['计算方法', '数字变化'],
  it: ['Come si calcola', 'Sequenza numerica'], id: ['Cara menghitung', 'Urutan angka'],
  vi: ['Cách tính', 'Chuỗi số'], tr: ['Hesaplama yöntemi', 'Sayı dizisi'],
  pl: ['Sposób obliczania', 'Ciąg liczb'],
};

function sumDigits(value) {
  return [...String(value)].reduce((total, digit) => total + Number(digit), 0);
}

function cardsFromSum(sum) {
  const stages = [sum];
  while (sum > 22) {
    sum = sumDigits(sum);
    stages.push(sum);
  }
  let soul = null;
  let bridge = null;
  if (sum >= 10) {
    soul = sumDigits(sum);
    stages.push(soul);
    if (soul >= 10) {
      bridge = soul;
      soul = sumDigits(soul);
      stages.push(soul);
    }
  }
  return { personality: sum === 22 ? 0 : sum, soul, bridge, stages };
}

function calculateBirthCards(value, today = new Date()) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || '');
  if (!match) throw new Error('invalid');
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]) throw new Error('invalid');
  const current = today.getFullYear() * 10000 + (today.getMonth() + 1) * 100 + today.getDate();
  if (year * 10000 + month * 100 + day > current) throw new Error('future');
  return cardsFromSum(sumDigits(match[1] + match[2] + match[3]));
}

function initBirthPage() {
  const app = document.getElementById('birth-app');
  if (!app) return;
  const data = JSON.parse(document.getElementById('birth-data').textContent);
  const lang = data.lang;
  const ui = Object.fromEntries(BIRTH_UI_KEYS.map((key, index) => [key, (BIRTH_UI[lang] || BIRTH_UI.en)[index]]));
  const extra = BIRTH_EXTRA[lang] || BIRTH_EXTRA.en;
  const byId = new Map(data.cards.map(card => [card.id, card]));
  const get = id => document.getElementById(id);
  get('birth-title').textContent = ui.title;
  get('birth-intro').textContent = ui.intro;
  get('birth-date-label').textContent = ui.date;
  get('birth-submit').textContent = ui.submit;
  get('birth-privacy').textContent = ui.privacy;
  get('birth-method-title').textContent = extra[0];

  const dateInput = get('birth-date');
  const now = new Date();
  dateInput.max = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

  const add = (parent, tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = text;
    parent.appendChild(element);
    return element;
  };
  const detail = (parent, heading, content) => {
    if (!content) return;
    add(parent, 'h3', '', heading);
    add(parent, 'p', '', content);
  };
  const list = (parent, heading, entries) => {
    if (!entries?.length) return;
    add(parent, 'h3', '', heading);
    const ul = add(parent, 'ul');
    entries.forEach(entry => add(ul, 'li', '', entry));
  };
  const renderCard = (parent, id, role) => {
    const card = byId.get(id);
    const article = add(parent, 'article', 'birth-card-result');
    const media = add(article, 'div', 'birth-card-media');
    const image = add(media, 'img');
    image.src = `/images/medium/${encodeURIComponent(card.image)}`;
    image.alt = card.name;
    image.width = 700;
    image.height = 1170;
    const content = add(article, 'div');
    add(content, 'p', 'birth-role', ui[role]);
    add(content, 'h2', '', `${id}. ${card.name}`);
    if (data.detailed) {
      if (role === 'personality' || role === 'both') {
        add(content, 'p', 'birth-tagline', card.tagline);
        add(content, 'p', 'birth-keywords', card.keywords.join(' · '));
        detail(content, data.labels.personality, card.personality);
        list(content, data.labels.strengths, card.strengths);
        list(content, data.labels.shadow, card.shadow);
        detail(content, data.labels.life_lesson, card.life_lesson);
        detail(content, data.labels.relationships, card.relationships);
        if (card.career) {
          add(content, 'h3', '', data.labels.career);
          add(content, 'p', '', card.career.style);
          add(content, 'p', '', card.career.fields.join(' · '));
          add(content, 'p', '', card.career.caution);
        }
      }
      if (card.soul_note && role !== 'personality') detail(content, data.labels.soul_note, card.soul_note);
    } else {
      add(content, 'p', 'birth-privacy', ui.limited);
    }
    const guide = add(content, 'a', '', ui.guide);
    guide.href = card.guide;
  };

  get('birth-form').addEventListener('submit', event => {
    event.preventDefault();
    const error = get('birth-error');
    error.hidden = true;
    let result;
    try {
      result = calculateBirthCards(dateInput.value);
    } catch (cause) {
      error.textContent = cause.message === 'future' ? ui.future : ui.invalid;
      error.hidden = false;
      get('birth-result').hidden = true;
      return;
    }
    const output = get('birth-result');
    output.replaceChildren();
    add(output, 'p', 'birth-summary', `${extra[1]}: ${result.stages.join(' → ')}`);
    renderCard(output, result.personality, result.soul === null ? 'both' : 'personality');
    if (result.bridge !== null) renderCard(output, result.bridge, 'bridge');
    if (result.soul !== null) renderCard(output, result.soul, 'soul');
    output.hidden = false;
    output.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initBirthPage);
if (typeof module !== 'undefined') module.exports = { cardsFromSum, calculateBirthCards };
