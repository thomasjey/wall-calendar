// Tests for the pure date functions (DESIGN §12.2). Served only in mock mode.
// Results: the page title becomes "PASS n" or "FAIL n of m".

import * as t from '../js/time.js';
import { el, setCalColor, setPhoto, showFullTextOnHover } from '../js/dom.js';
import { DEFAULTS, parseSettings } from '../js/settings.js';

const results = [];
function test(name, fn) {
  try {
    fn();
    results.push([true, name]);
  } catch (e) {
    results.push([false, `${name}: ${e.message}`]);
  }
}
function eq(a, b) {
  const sa = JSON.stringify(a);
  const sb = JSON.stringify(b);
  if (sa !== sb) throw new Error(`${sa} !== ${sb}`);
}

const local = (y, m, d, h = 0, min = 0) => new Date(y, m - 1, d, h, min);
const timed = (title, s, e) => ({ title, allDay: false, start: s.toISOString(), end: e.toISOString() });
const allDay = (title, s, e) => ({ title, allDay: true, startDate: s, endDate: e });

test('dateKey and fromKey round trip', () => {
  eq(t.dateKey(local(2026, 1, 5)), '2026-01-05');
  eq(t.dateKey(t.fromKey('2026-12-31')), '2026-12-31');
});

test('addDays across DST end and month/year ends', () => {
  eq(t.dateKey(t.addDays(local(2026, 10, 31), 2)), '2026-11-02');
  eq(t.dateKey(t.addDays(local(2026, 3, 7), 2)), '2026-03-09');
  eq(t.dateKey(t.addDays(local(2026, 12, 31), 1)), '2027-01-01');
});

test('week start sunday and monday', () => {
  eq(t.dateKey(t.weekStartOf(local(2026, 10, 21), 'sunday')), '2026-10-18');
  eq(t.dateKey(t.weekStartOf(local(2026, 10, 21), 'monday')), '2026-10-19');
  eq(t.dateKey(t.weekStartOf(local(2026, 10, 18), 'monday')), '2026-10-12');
});

test('month grid', () => {
  const g = t.monthGrid(local(2026, 10, 21), 'sunday');
  eq([t.dateKey(g.start), t.dateKey(g.end)], ['2026-09-27', '2026-11-01']);
  const a = t.monthGrid(local(2026, 8, 1), 'sunday');
  eq([t.dateKey(a.start), t.dateKey(a.end)], ['2026-07-26', '2026-09-06']);
});

test('12h and 24h clock', () => {
  eq(t.clockParts(local(2026, 1, 1, 0, 5), '12h'), { time: '12:05', ampm: 'AM' });
  eq(t.clockParts(local(2026, 1, 1, 12, 0), '12h'), { time: '12:00', ampm: 'PM' });
  eq(t.clockParts(local(2026, 1, 1, 14, 47), '12h'), { time: '2:47', ampm: 'PM' });
  eq(t.fmtTime(local(2026, 1, 1, 9, 5), '24h'), '09:05');
});

test('ranges', () => {
  eq(t.fmtRange(local(2026, 10, 21, 17, 15), local(2026, 10, 21, 18), '12h'), '5:15 – 6:00 PM');
  eq(t.fmtRange(local(2026, 10, 21, 11, 30), local(2026, 10, 21, 12, 30), '12h'), '11:30 AM – 12:30 PM');
  eq(t.fmtRange(local(2026, 10, 21, 22), local(2026, 10, 22, 0), '12h'), '10:00 PM – 12:00 AM');
  eq(t.fmtRange(local(2026, 10, 24, 19), local(2026, 10, 25, 9), '12h'),
    'Sat, Oct 24, 7:00 PM – Sun, Oct 25, 9:00 AM');
  eq(t.fmtRange(local(2026, 10, 21, 9), local(2026, 10, 21, 9), '12h'), '9:00 AM');
});

test('bucket: timed, overnight, ends at midnight, all-day exclusive end', () => {
  const map = t.bucket([
    timed('a', local(2026, 10, 21, 9), local(2026, 10, 21, 10)),
    timed('overnight', local(2026, 10, 24, 19), local(2026, 10, 25, 9)),
    timed('to midnight', local(2026, 10, 21, 22), local(2026, 10, 22, 0)),
    allDay('visit', '2026-10-21', '2026-10-24'),
  ]);
  const titles = (k) => (map.get(k) || []).map((e) => e.title).sort();
  eq(titles('2026-10-21'), ['a', 'to midnight', 'visit']);
  eq(titles('2026-10-22'), ['visit']);
  eq(titles('2026-10-23'), ['visit']);
  eq(titles('2026-10-24'), ['overnight']);
  eq(titles('2026-10-25'), ['overnight']);
});

test('eventsOn ordering and time labels', () => {
  const day = local(2026, 10, 25);
  const map = t.bucket([
    timed('late', local(2026, 10, 25, 15), local(2026, 10, 25, 16)),
    timed('overnight', local(2026, 10, 24, 19), local(2026, 10, 25, 9)),
    allDay('trip', '2026-10-25', '2026-10-26'),
    timed('long', local(2026, 10, 24, 8), local(2026, 10, 26, 8)),
  ]);
  const list = t.eventsOn(map, day);
  eq(list.map((e) => e.title), ['long', 'trip', 'overnight', 'late']);
  eq(list.map((e) => t.timeLabel(e, day, '12h')), ['All day', 'All day', 'Until 9:00 AM', '3:00 PM']);
});

test('end labels under the start time', () => {
  const day = local(2026, 10, 24);
  eq(t.endLabel(timed('x', local(2026, 10, 24, 15, 30), local(2026, 10, 24, 16, 30)), day, '12h'), 'to 4:30 PM');
  eq(t.endLabel(timed('x', local(2026, 10, 24, 19), local(2026, 10, 25, 9)), day, '12h'), 'to Sun 9:00 AM');
  eq(t.endLabel(timed('x', local(2026, 10, 24, 22), local(2026, 10, 25, 0)), day, '12h'), 'to 12:00 AM');
  eq(t.endLabel(timed('x', local(2026, 10, 24, 9), local(2026, 10, 24, 9)), day, '12h'), '');
  eq(t.endLabel(allDay('x', '2026-10-24', '2026-10-25'), day, '12h'), '');
  // On the next day an overnight event already says "Until 9:00 AM".
  eq(t.endLabel(timed('x', local(2026, 10, 24, 19), local(2026, 10, 25, 9)), local(2026, 10, 25), '12h'), '');
  eq(t.endLabel(timed('x', local(2026, 10, 24, 15, 30), local(2026, 10, 24, 16, 30)), day, '24h'), 'to 16:30');
});

test('relative day labels', () => {
  const today = local(2026, 10, 21, 14, 47);
  eq([0, 1, -1, 5, -3].map((n) => t.relativeDay(local(2026, 10, 21 + n), today)),
    ['Today', 'Tomorrow', 'Yesterday', 'In 5 days', '3 days ago']);
  // Across the DST change (US: Nov 1 2026) it still counts calendar days.
  eq(t.relativeDay(local(2026, 11, 2), local(2026, 10, 31, 23, 30)), 'In 2 days');
});

test('whenText', () => {
  eq(t.whenText(allDay('x', '2026-10-21', '2026-10-22'), null, '12h'), 'All day · Wed, Oct 21');
  eq(t.whenText(allDay('x', '2026-10-21', '2026-10-24'), null, '12h'), 'All day · Wed, Oct 21 – Fri, Oct 23');
  eq(t.whenText(timed('x', local(2026, 10, 21, 17, 15), local(2026, 10, 21, 18)), null, '12h'),
    'Wed, Oct 21 · 5:15 – 6:00 PM');
});

test('night dim range crossing midnight', () => {
  const r = ['22:00', '06:30'];
  eq([23, 2, 6, 7, 12].map((h) => t.inDailyRange(local(2026, 1, 1, h), r)), [true, true, true, false, false]);
  eq(t.inDailyRange(local(2026, 1, 1, 6, 30), r), false);
  eq(t.inDailyRange(local(2026, 1, 1, 3), []), false);
});

test('dom helper: text stays text, unsafe attributes refused', () => {
  const node = el('div', { text: '<img src=x onerror=alert(1)>' }, '<b>child</b>');
  eq(node.children.length, 0);
  eq(node.textContent, '<img src=x onerror=alert(1)><b>child</b>');
  for (const attr of ['onclick', 'href', 'src', 'style', 'srcdoc']) {
    let threw = false;
    try { el('div', { attrs: { [attr]: 'x' } }); } catch { threw = true; }
    eq([attr, threw], [attr, true]);
  }
});

test('dom helper: colors and photo URLs validated', () => {
  const node = document.createElement('div');
  setCalColor(node, 'red; background: url(//evil)');
  eq(node.style.getPropertyValue('--cal'), '');
  setCalColor(node, '#7FB3FF');
  eq(node.style.getPropertyValue('--cal'), '#7FB3FF');
  const img = document.createElement('img');
  eq([setPhoto(img, 'javascript:alert(1)'), setPhoto(img, '/photos/../x'), img.getAttribute('src')],
    [false, false, null]);
  eq(setPhoto(img, '/photos/0123456789abcdef'), true);
});

test('settings: only known keys of the right type; no prototype change', () => {
  const body = JSON.parse('{"__proto__": {"polluted": true}, "clock": "24h", "weekStart": "friday",'
    + ' "idleSeconds": "5", "nightDim": ["22:00", "6:30"], "extra": 1, "debugNow": "2026-12-31T23:30:00Z"}');
  const { settings, offsetMs } = parseSettings(body, Date.parse('2026-12-31T23:00:00Z'));
  eq(settings, { ...DEFAULTS, clock: '24h' });
  eq(Object.getPrototypeOf(settings), Object.prototype);
  eq(({}).polluted, undefined);
  eq(offsetMs, 30 * 60 * 1000);
  eq(parseSettings(null).settings, { ...DEFAULTS });
});

test('hover shows full text only when it is cut off', () => {
  const box = el('div');
  const long = el('div', { cls: 'title', text: '<b>A very long event title that cannot fit</b>' });
  const short = el('div', { cls: 'title', text: 'Short' });
  for (const node of [long, short]) {
    node.style.setProperty('width', '60px');
    node.style.setProperty('white-space', 'nowrap');
    node.style.setProperty('overflow', 'hidden');
    box.append(node);
  }
  document.body.append(box);
  showFullTextOnHover(box, '.title');
  for (const node of [long, short]) node.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
  eq(long.getAttribute('title'), '<b>A very long event title that cannot fit</b>');
  eq(short.getAttribute('title'), null);
  eq(long.children.length, 0);
  box.remove();
});

test('Trusted Types blocks HTML sinks', () => {
  let blocked = false;
  try { document.createElement('div').innerHTML = '<b>x</b>'; } catch { blocked = true; }
  eq(blocked, true);
});

const failed = results.filter(([ok]) => !ok);
document.getElementById('out').textContent = results.map(([ok, n]) => `${ok ? 'ok  ' : 'FAIL'} ${n}`).join('\n');
document.title = failed.length ? `FAIL ${failed.length} of ${results.length}` : `PASS ${results.length}`;
