const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('shared image grows to include the full reading without a promo tagline', async () => {
  const html = fs.readFileSync(require('node:path').join(__dirname, '../static/index.html'), 'utf8');
  const start = html.indexOf('function wrapLines(');
  const end = html.indexOf('function canvasToBlob(', start);
  assert.ok(start > 0 && end > start);

  const drawn = [];
  const ctx = {
    measureText: text => ({ width: text.length * 20 }),
    createRadialGradient: () => ({ addColorStop() {} }),
    fillRect() {}, beginPath() {}, arc() {}, fill() {}, drawImage() {},
    fillText: text => drawn.push(text),
  };
  const canvas = { getContext: () => ctx };
  const reading = Array.from({ length: 120 }, (_, i) => `Paragraph ${i}: a complete tarot interpretation.`).join('\n') + '\nLAST_LINE';
  const scope = {
    document: {
      createElement: () => canvas,
      getElementById: () => ({ innerText: reading }),
    },
    readingQuestion: () => 'Which option should I choose?',
    drawnCards: [],
    currentLang: 'en',
  };
  vm.runInNewContext(`${html.slice(start, end)}\nthis.buildShareCanvas = buildShareCanvas;`, scope);
  const result = await scope.buildShareCanvas();

  assert.equal(result, canvas);
  assert.ok(canvas.height > 1350);
  assert.ok(drawn.includes('LAST_LINE'));
  assert.ok(drawn.includes('ultratarot.com'));
  assert.ok(!drawn.some(text => String(text).includes('무료 3회')));
});
