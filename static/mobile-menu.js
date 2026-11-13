/* 모바일(600px 이하) 상단바의 보조 항목을 ☰ 메뉴로 모은다.
 *
 * 상단바에는 로고, 남은 횟수·충전, 핵심 메뉴 4개만 남기고
 * 이용내역, 저장한 리딩, 타로카드 도감, 언어, 로그아웃은 ☰ 메뉴 안에 둔다.
 * 메인 화면(#top-bar)과 서버가 만드는 페이지(#acct-bar)가 같은 스크립트를 쓴다.
 *
 *  - 이용내역·로그아웃은 원래 버튼의 click()을 대신 눌러 준다(로그인 상태에 따라 보이는 여부는 열 때마다 확인).
 *  - 저장한 리딩·타로카드 도감은 상단 메뉴의 보조 링크(.site-brand/.site-mode 가 아닌 링크)를 복사해서 보여 준다.
 *  - 언어 선택기는 모바일에서만 메뉴 안으로 옮기고, 화면이 넓어지면 제자리로 돌려놓는다.
 */
(function () {
  var mq = window.matchMedia('(max-width: 600px)');
  var bar, userInfo, hist, logout, nameEl, lang, panel, toggle, langHome;

  function find() {
    bar = document.getElementById('top-bar') || document.getElementById('acct-bar');
    if (!bar) return false;
    userInfo = document.getElementById('user-info') || document.getElementById('acct-user');
    hist = document.getElementById('history-btn') || document.getElementById('acct-history');
    logout = document.getElementById('logout-btn') || document.getElementById('acct-logout');
    nameEl = document.getElementById('user-name') || document.getElementById('acct-name');
    lang = document.getElementById('lang-selector') || bar.querySelector('select');
    return true;
  }

  function loggedIn() {
    return !!userInfo && getComputedStyle(userInfo).display !== 'none';
  }

  function item(tag, text, attrs) {
    var el = document.createElement(tag);
    el.className = 'mm-item';
    el.textContent = text;
    Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
    return el;
  }

  function proxy(source) {
    var btn = item('button', (source.textContent || '').trim(), { type: 'button' });
    btn.addEventListener('click', function () { source.click(); });
    return btn;
  }

  // 메뉴를 열 때마다 현재 상태(로그인 여부, 언어에 따라 바뀐 문구)에 맞게 다시 채운다
  function refresh() {
    var keep = lang && panel.contains(lang) ? lang : null;        // 언어 선택기는 메뉴 안에 그대로 둔다
    if (keep) keep.parentNode.removeChild(keep);                 // 비우기 전에 떼어 두었다가 다시 붙인다
    panel.textContent = '';
    var on = loggedIn();
    var name = nameEl && (nameEl.textContent || '').trim();
    if (on && name) panel.appendChild(item('div', name, { class: 'mm-item mm-name' }));
    if (on && hist) panel.appendChild(proxy(hist));
    bar.querySelectorAll('.site-primary-nav a:not(.site-brand):not(.site-mode)').forEach(function (a) {
      panel.appendChild(item('a', (a.textContent || '').trim(), { href: a.getAttribute('href') }));
    });
    if (keep) { var wrap = document.createElement('div'); wrap.className = 'mm-item mm-lang'; wrap.appendChild(keep); panel.appendChild(wrap); }
    if (on && logout) panel.appendChild(proxy(logout));
  }

  function open(state) {
    if (state) refresh();
    panel.classList.toggle('open', state);
    toggle.setAttribute('aria-expanded', state ? 'true' : 'false');
  }

  // 언어 선택기: 좁은 화면에서는 메뉴 안, 넓은 화면에서는 원래 자리
  function placeLang() {
    if (!lang) return;
    if (mq.matches) {
      if (!lang.closest('.mm-panel')) {
        var wrap = document.createElement('div');
        wrap.className = 'mm-item mm-lang';
        wrap.appendChild(lang);
        panel.appendChild(wrap);
      }
    } else if (langHome && langHome.parentNode && lang.closest('.mm-panel')) {   // 메뉴(상단바 안에 있음) 안에 있으면 제자리로
      langHome.parentNode.insertBefore(lang, langHome);
      panel.querySelectorAll('.mm-lang').forEach(function (w) { w.remove(); });
    }
    if (!mq.matches) open(false);
  }

  function init() {
    if (!find() || bar.querySelector('.mm-toggle')) return;
    if (lang) { langHome = document.createComment('mm-lang'); lang.parentNode.insertBefore(langHome, lang); }

    toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'mm-toggle';
    toggle.setAttribute('aria-label', 'Menu');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16"/></svg>';

    panel = document.createElement('div');
    panel.className = 'mm-panel';
    panel.setAttribute('role', 'menu');

    bar.appendChild(toggle);
    bar.appendChild(panel);

    toggle.addEventListener('click', function (e) { e.stopPropagation(); open(!panel.classList.contains('open')); });
    panel.addEventListener('click', function (e) {
      // 언어 목록을 펼치는 버튼과 목록 자체는 메뉴를 닫지 않는다. 항목을 고르면 닫는다.
      if (e.target.closest('#lang-btn') || e.target.closest('select')) return;
      open(false);
    });
    document.addEventListener('click', function (e) { if (!panel.contains(e.target) && e.target !== toggle) open(false); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') open(false); });
    (mq.addEventListener ? mq.addEventListener('change', placeLang) : mq.addListener(placeLang));
    window.addEventListener('resize', placeLang);   // 기기를 가로로 돌리는 경우 등, change 이벤트가 오지 않아도 제자리를 찾는다
    placeLang();
  }

  // 서버 페이지 중에는 상단바를 스크립트가 늦게 만드는 곳도 있어서, 나타날 때까지 잠깐 기다린다
  function start() {
    if (find()) return init();
    var obs = new MutationObserver(function () { if (find()) { obs.disconnect(); init(); } });
    obs.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(function () { obs.disconnect(); }, 5000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
