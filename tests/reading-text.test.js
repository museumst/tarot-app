const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
const start = html.indexOf('function normalizeKoreanCardCounts(');
const end = html.indexOf('async function startReading()', start);
assert.ok(start > 0 && end > start);
const scope = {};
vm.runInNewContext(`${html.slice(start, end)}\nthis.normalize = normalizeKoreanCardCounts;`, scope);

const positionStart = html.indexOf('function spreadPositionMeaning(');
const positionEnd = html.indexOf('function enterToday()', positionStart);
assert.ok(positionStart > 0 && positionEnd > positionStart);
const spreads = JSON.parse(fs.readFileSync(path.join(__dirname, '../output/spreads.json'), 'utf8'));
const positionScope = { selectedSpread: null, t: (_, i) => `Card ${i + 1}` };
vm.runInNewContext(`${html.slice(positionStart, positionEnd)}\nthis.meaning = spreadPositionMeaning; this.label = spreadPositionLabel;`, positionScope);

test('numbered card names use native Korean counters', () => {
  assert.equal(scope.normalize('<카드 3: 오개의 컵>'), '<카드 3: 다섯 개의 컵>');
  assert.equal(scope.normalize('육개의 검과 칠개의 지팡이'), '여섯 개의 검과 일곱 개의 지팡이');
  assert.equal(scope.normalize('십 개의 동전'), '열 개의 동전');
});

test('unrelated words and multi-digit counts are unchanged', () => {
  assert.equal(scope.normalize('오개념과 십오개의 컵'), '오개념과 십오개의 컵');
  assert.equal(scope.normalize('다섯 개의 컵'), '다섯 개의 컵');
});

test('ten-card spreads keep fixed position labels separate from full meanings', () => {
  for (const spread of spreads.filter(item => item.card_count === 10 && item.positions?.length === 10)) {
    positionScope.selectedSpread = spread;
    for (let i = 0; i < 10; i++) {
      assert.equal(positionScope.meaning(i), spread.positions[i].meaning);
      assert.equal(positionScope.label(i), spread.positions[i].label);
    }
  }
});

test('Korean card headings use the fixed label, not an invented subtitle', () => {
  const cards = [{ card: { name_ko: '여덟 개의 컵' }, positionLabel: '현재 상황' }];
  const headingScope = { drawnCards: cards };
  vm.runInNewContext(`${html.slice(start, end)}\nthis.normalizeHeading = normalizeKoreanPositionHeadings;`, headingScope);
  assert.equal(
    headingScope.normalizeHeading('<1번 카드: 여덟 개의 컵 - 당신의 출발점>', cards),
    '<1번 카드: 여덟 개의 컵 - 현재 상황>'
  );
  assert.equal(
    headingScope.normalizeHeading('<카드 1: 여덟 개의 컵 - 출발점>', cards),
    '<1번 카드: 여덟 개의 컵 - 현재 상황>'
  );
});
