const test = require('node:test');
const assert = require('node:assert/strict');
const { cardsFromSum, calculateBirthCards, daysInMonth } = require('../static/birth-card.js');

test('wheel day counts follow leap-year rules', () => {
  assert.equal(daysInMonth(2000, 2), 29);
  assert.equal(daysInMonth(1900, 2), 28);
  assert.equal(daysInMonth(2024, 2), 29);
  assert.equal(daysInMonth(2025, 4), 30);
});

test('birth date sums eight digits and reduces to the major arcana range', () => {
  const result = calculateBirthCards('1988-09-29', new Date(2026, 9, 3));
  assert.deepEqual(result, { personality: 10, soul: 1, bridge: null, stages: [46, 10, 1] });
});

test('19 includes the intermediate wheel card', () => {
  assert.deepEqual(cardsFromSum(19), { personality: 19, soul: 1, bridge: 10, stages: [19, 10, 1] });
});

test('22 maps to the fool while the soul card remains 4', () => {
  assert.deepEqual(cardsFromSum(22), { personality: 0, soul: 4, bridge: null, stages: [22, 4] });
});

test('single-digit results use one card and keep RWS numbers', () => {
  assert.deepEqual(cardsFromSum(8), { personality: 8, soul: null, bridge: null, stages: [8] });
  assert.deepEqual(cardsFromSum(11), { personality: 11, soul: 2, bridge: null, stages: [11, 2] });
});

test('rejects invalid and future birth dates', () => {
  const today = new Date(2026, 9, 3);
  assert.doesNotThrow(() => calculateBirthCards('2000-02-29', today));
  assert.throws(() => calculateBirthCards('1900-02-29', today), /invalid/);
  assert.throws(() => calculateBirthCards('2026-10-04', today), /future/);
  assert.throws(() => calculateBirthCards('2026-13-01', today), /invalid/);
});

test('all birth cards resolve to deck images and RWS numbering', () => {
  const birth = require('../output/birth_cards_ko.json').cards;
  const deck = require('../output/cards.json');
  const deckSlugs = new Set(deck.filter(card => card.image_file).map(card =>
    card.name_en.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  ));
  assert.deepEqual(birth.map(card => card.id), Array.from({ length: 22 }, (_, id) => id));
  assert.ok(birth.every(card => deckSlugs.has(card.slug)));
  assert.equal(birth[8].slug, 'strength');
  assert.equal(birth[11].slug, 'justice');
});
