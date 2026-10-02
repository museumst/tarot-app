// 모든 페이지 상단에 표시되는 계정 바 (프로필·무료/무제한·충전·내역·로그아웃)
// 메인 앱(index.html)과 같은 도메인이라 Firebase 로그인 상태가 그대로 공유된다.
// 충전/내역 모달은 메인 앱에만 있으므로, 누르면 메인 앱으로 이동해 해당 창을 연다.
import { initializeApp, getApps } from 'https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js';
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, onAuthStateChanged }
  from 'https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js';
import { getFirestore, doc, getDoc }
  from 'https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js';

const FREE_LIMIT = 3;
const ADMIN_EMAILS = ['museumst@gmail.com'];
const COPY = {
  ko: { logout:'로그아웃', free:n => `무료 ${n}회 남음`, unl:'무제한', topUp:'💳 충전하기', balance:n => `💳 ${n}회`, history:'내역', histTitle:'크레딧 이용내역' },
  en: { logout:'Logout', free:n => `${n} free reading${n!==1?'s':''} left`, unl:'Unlimited', topUp:'💳 Top Up', balance:n => `💳 ${n} credits`, history:'History', histTitle:'Credit history' },
  ja: { logout:'ログアウト', free:n => `残り${n}回無料`, unl:'無制限', topUp:'💳 チャージ', balance:n => `💳 ${n}回`, history:'履歴', histTitle:'クレジット利用履歴' },
  es: { logout:'Cerrar Sesión', free:n => `${n} lectura${n!==1?'s':''} gratuita${n!==1?'s':''} restante${n!==1?'s':''}`, unl:'Ilimitado', topUp:'💳 Recargar', balance:n => `💳 ${n} créditos`, history:'Historial', histTitle:'Historial de créditos' },
  fr: { logout:'Déconnexion', free:n => `${n} lecture${n>1?'s':''} gratuite${n>1?'s':''} restante${n>1?'s':''}`, unl:'Illimité', topUp:'💳 Recharger', balance:n => `💳 ${n} crédits`, history:'Historique', histTitle:'Historique des crédits' },
  de: { logout:'Abmelden', free:n => `${n} kostenlose Legung${n!==1?'en':''} übrig`, unl:'Unbegrenzt', topUp:'💳 Aufladen', balance:n => `💳 ${n} Credits`, history:'Verlauf', histTitle:'Credit-Verlauf' },
  pt: { logout:'Sair', free:n => `${n} leitura${n!==1?'s':''} gratuita${n!==1?'s':''} restante${n!==1?'s':''}`, unl:'Ilimitado', topUp:'💳 Recarregar', balance:n => `💳 ${n} créditos`, history:'Histórico', histTitle:'Histórico de créditos' },
  th: { logout:'ออกจากระบบ', free:n => `เหลือ ${n} ครั้ง`, unl:'ไม่จำกัด', topUp:'💳 เติมเครดิต', balance:n => `💳 ${n} เครดิต`, history:'ประวัติ', histTitle:'ประวัติเครดิต' },
  ru: { logout:'Выйти', free:n => `Осталось ${n} расклад${n===1?'':n<5?'а':'ов'}`, unl:'Безлимитно', topUp:'💳 Пополнить', balance:n => `💳 ${n} кредитов`, history:'История', histTitle:'История кредитов' },
  zh: { logout:'退出登录', free:n => `剩余${n}次免费`, unl:'无限制', topUp:'💳 充值', balance:n => `💳 ${n}积分`, history:'记录', histTitle:'积分记录' },
  it: { logout:'Esci', free:n => `${n} lettura${n!==1?'e':''} gratuita${n!==1?'e':''} rimasta${n!==1?'e':''}`, unl:'Illimitato', topUp:'💳 Ricarica', balance:n => `💳 ${n} crediti`, history:'Storico', histTitle:'Storico crediti' },
  id: { logout:'Keluar', free:n => `${n} pembacaan gratis tersisa`, unl:'Tidak Terbatas', topUp:'💳 Isi Ulang', balance:n => `💳 ${n} kredit`, history:'Riwayat', histTitle:'Riwayat kredit' },
  vi: { logout:'Đăng xuất', free:n => `Còn ${n} lần miễn phí`, unl:'Không giới hạn', topUp:'💳 Nạp thêm', balance:n => `💳 ${n} lượt`, history:'Lịch sử', histTitle:'Lịch sử lượt' },
  tr: { logout:'Çıkış Yap', free:n => `${n} ücretsiz okuma kaldı`, unl:'Sınırsız', topUp:'💳 Kredi Yükle', balance:n => `💳 ${n} kredi`, history:'Geçmiş', histTitle:'Kredi geçmişi' },
  pl: { logout:'Wyloguj', free:n => `Pozostało ${n} bezpłatne${n===1?'':n<5?'':'ch'} czytanie${n===1?'':n<5?'a':'ń'}`, unl:'Nieograniczone', topUp:'💳 Doładuj', balance:n => `💳 ${n} kredytów`, history:'Historia', histTitle:'Historia kredytów' },
};

// 마크업이 없는 페이지(legal.html 등)에서는 직접 만들어 넣는다
function ensureBar() {
  let el = document.getElementById('acct-bar');
  if (el) return el;
  let l = 'ko';
  try { l = localStorage.getItem('tarot-lang') || ''; } catch (e) {}
  if (!COPY[l]) l = COPY[document.documentElement.lang] ? document.documentElement.lang : 'ko';
  el = document.createElement('div');
  el.id = 'acct-bar';
  el.dataset.lang = l;
  el.innerHTML = '<button id="acct-login" type="button"></button><div id="acct-user">' +
    '<span id="acct-free" class="plenty"></span><a id="acct-credit" href="/"></a>' +
    '<a id="acct-history" href="/"></a><img id="acct-avatar" src="" alt="">' +
    '<span id="acct-name"></span><button id="acct-logout" type="button"></button></div>';
  el.className = 'site-topbar';
  document.body.prepend(el);
  return el;
}

const bar = ensureBar();
if (bar) {
  let savedLang = '';
  try { savedLang = localStorage.getItem('tarot-lang') || ''; } catch (e) {}
  const lang = bar.dataset.lang || savedLang || document.documentElement.lang || 'en';
  const c = COPY[lang] || COPY.en;
  const home = lang === 'ko' ? '/' : '/?lang=' + lang;
  const go = open => home + (home.includes('?') ? '&' : '?') + 'open=' + open;
  const $ = id => document.getElementById(id);

  $('acct-login').textContent = lang === 'ko' ? '🔑 로그인' : '🔑 Login';
  $('acct-history').textContent = c.history;
  $('acct-history').title = c.histTitle;
  $('acct-history').href = go('history');
  $('acct-credit').href = go('charge');
  $('acct-logout').textContent = c.logout;

  const app = getApps()[0] || initializeApp({
    apiKey: "AIzaSyDJ8KP4yPw_VcblGMtO-tTTkukhdwP6Ifg",
    authDomain: "tarot-7bad9.firebaseapp.com",
    projectId: "tarot-7bad9",
    storageBucket: "tarot-7bad9.firebasestorage.app",
    messagingSenderId: "1067477977686",
    appId: "1:1067477977686:web:c3a49c8e36748186f849f7"
  });
  const auth = getAuth(app);
  const db = getFirestore(app);

  function setCredit(n) {
    const el = $('acct-credit');
    el.textContent = n === 0 ? c.topUp : c.balance(n);
    el.className = n === 0 ? 'empty' : n <= 5 ? 'low' : '';
  }
  function setFree(used, unlimited) {
    const el = $('acct-free');
    if (unlimited) { el.textContent = c.unl; el.className = 'plenty'; return; }
    const left = Math.max(0, FREE_LIMIT - used);
    el.textContent = c.free(left);
    el.className = left >= 2 ? 'plenty' : left === 1 ? 'warning' : 'empty';
  }

  $('acct-login').addEventListener('click', async () => {
    try { await signInWithPopup(auth, new GoogleAuthProvider()); } catch (e) { console.error('로그인 실패', e); }
  });
  $('acct-logout').addEventListener('click', () => signOut(auth));

  onAuthStateChanged(auth, async user => {
    if (!user) {
      $('acct-user').style.display = 'none';
      $('acct-login').style.display = 'inline-block';
      return;
    }
    $('acct-login').style.display = 'none';
    $('acct-user').style.display = 'flex';
    const av = $('acct-avatar');
    if (user.photoURL) { av.src = user.photoURL; av.style.display = ''; } else { av.style.display = 'none'; }
    $('acct-name').textContent = user.isAnonymous ? (lang === 'ko' ? '비회원' : 'Guest') : (user.displayName || user.email || '');
    const admin = ADMIN_EMAILS.includes(user.email);
    setFree(0, admin); setCredit(0);
    try {
      const snap = await getDoc(doc(db, 'users', user.uid));
      const d = snap.exists() ? snap.data() : {};
      setFree(d.free_used || 0, admin);
      setCredit(d.credits || 0);
    } catch (e) { console.warn('사용자 정보 로드 실패', e); }
  });
}
