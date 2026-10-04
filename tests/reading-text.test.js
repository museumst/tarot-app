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

test('numbered card names use native Korean counters', () => {
  assert.equal(scope.normalize('<카드 3: 오개의 컵>'), '<카드 3: 다섯 개의 컵>');
  assert.equal(scope.normalize('육개의 검과 칠개의 지팡이'), '여섯 개의 검과 일곱 개의 지팡이');
  assert.equal(scope.normalize('십 개의 동전'), '열 개의 동전');
});

test('unrelated words and multi-digit counts are unchanged', () => {
  assert.equal(scope.normalize('오개념과 십오개의 컵'), '오개념과 십오개의 컵');
  assert.equal(scope.normalize('다섯 개의 컵'), '다섯 개의 컵');
});
