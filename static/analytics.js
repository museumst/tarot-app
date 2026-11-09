/* 울트라타로 방문 분석 (Google Analytics 4)
 *
 * - GA_MEASUREMENT_ID 가 비어 있으면 아무것도 로드하지 않고 track() 은 아무 일도 하지 않는다.
 * - localhost 에서는 켜지 않는다(개발 중 방문이 통계에 섞이지 않도록).
 * - 유럽(EEA)·영국·스위스 방문자는 동의 전 기본값을 '거부'로 두어 분석 쿠키를 만들지 않는다.
 *   (동의 배너가 없으므로 해당 지역은 쿠키 없는 익명 집계만 전송된다.)
 * - 질문 내용, 생년월일, 계정 정보(uid·이메일)는 어떤 이벤트에도 보내지 않는다.
 */
(function () {
  var GA_MEASUREMENT_ID = 'G-8D0NK8MPTL';   // 예: 'G-XXXXXXXXXX'  (GA4 > 관리 > 데이터 스트림 > 측정 ID)

  var NO_CONSENT_REGIONS = ['AT','BE','BG','HR','CY','CZ','DK','EE','FI','FR','DE','GR','HU','IE','IT','LV','LT','LU',
    'MT','NL','PL','PT','RO','SK','SI','ES','SE','IS','LI','NO','GB','CH'];

  var enabled = false;

  function gtag() { window.dataLayer.push(arguments); }

  function init(id, opts) {
    opts = opts || {};
    if (enabled || !id) return false;
    var host = location.hostname;
    if (!opts.force && (host === 'localhost' || host === '127.0.0.1' || host === '[::1]' || /\.localhost$/.test(host))) return false;
    window.dataLayer = window.dataLayer || [];
    gtag('consent', 'default', {
      analytics_storage: 'denied', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied',
      region: NO_CONSENT_REGIONS
    });
    gtag('consent', 'default', {
      analytics_storage: 'granted', ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied'
    });
    gtag('js', new Date());
    gtag('config', id, { allow_google_signals: false, allow_ad_personalization_signals: false });
    if (!opts.skipLoad) {
      var s = document.createElement('script');
      s.async = true;
      s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
      document.head.appendChild(s);
    }
    enabled = true;
    return true;
  }

  // 이벤트 전송. 분석이 꺼져 있거나 오류가 나도 앱 동작에는 영향이 없다.
  window.track = function (name, params) {
    if (!enabled) return;
    try { gtag('event', name, params || {}); } catch (e) { /* 무시 */ }
  };
  window.ultraAnalytics = { init: init };

  init(GA_MEASUREMENT_ID);
})();
