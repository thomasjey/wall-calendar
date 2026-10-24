// Tests for the pure date functions (DESIGN §12.2). Served only in mock mode.
// Results: the page title becomes "PASS n" or "FAIL n of m".

import * as t from '../js/time.js';
import * as astro from '../js/astro.js';
import { initSky, paintSky, ridges } from '../js/sky.js';
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

test('sunrise and sunset (NOAA), within 5 minutes of published values', () => {
  const near = (d, iso) => { if (Math.abs(d.getTime() - Date.parse(iso)) > 5 * 60000) throw new Error(`${d.toISOString()} vs ${iso}`); };
  // London, midsummer and midwinter (published: 03:43/20:21 and 08:04/15:54 UTC).
  const summer = t.sunTimes(local(2026, 6, 21, 12), 51.5, -0.1);
  near(summer.sunrise, '2026-06-21T03:43:00Z');
  near(summer.sunset, '2026-06-21T20:21:00Z');
  const winter = t.sunTimes(local(2026, 12, 21, 12), 51.5, -0.1);
  near(winter.sunrise, '2026-12-21T08:04:00Z');
  near(winter.sunset, '2026-12-21T15:54:00Z');
  // No sunrise in the polar night, no sunset in the midnight sun.
  eq(t.sunTimes(local(2026, 12, 21, 12), 78.2, 15.6), null);
  eq(t.sunTimes(local(2026, 6, 21, 12), 78.2, 15.6), null);
});

test('sky blends from night to dawn at sunrise, day, dusk at sunset, night', () => {
  // Without a location: sunrise 6:30, sunset 19:00.
  eq(t.skyColors(local(2026, 10, 22, 2, 0), null), [...t.SKIES.night]);
  eq(t.skyColors(local(2026, 10, 22, 6, 30), null), [...t.SKIES.dawn]);
  eq(t.skyColors(local(2026, 10, 22, 13, 0), null), [...t.SKIES.day]);
  eq(t.skyColors(local(2026, 10, 22, 19, 0), null), [...t.SKIES.dusk]);
  eq(t.skyColors(local(2026, 10, 22, 23, 0), null), [...t.SKIES.night]);
  const between = t.skyColors(local(2026, 10, 22, 5, 45), null);  // halfway from night to dawn
  if (between[3] === t.SKIES.night[3] || between[3] === t.SKIES.dawn[3]) throw new Error('not blended');
  for (const c of between) if (!/^#[0-9a-f]{6}$/.test(c)) throw new Error(`bad colour ${c}`);
  // With a location the real sunrise is used (polar night: falls back to fixed hours).
  eq(t.skyColors(local(2026, 12, 21, 13, 0), [78.2, 15.6]), [...t.SKIES.day]);
});

test('settings: location only as two finite numbers in range', () => {
  eq(parseSettings({ location: [51.5, -0.1] }).settings.location, [51.5, -0.1]);
  for (const bad of [[91, 0], [0, 181], ['51', '0'], [51.5], null, 'x', [NaN, 0]]) {
    eq(parseSettings({ location: bad }).settings.location, null);
  }
});

test('sun and moon: the April 2024 total eclipse lines them up; phases', () => {
  const close = (a, b, tol, what) => { if (Math.abs(a - b) > tol) throw new Error(`${what}: ${a} vs ${b}`); };
  // Total solar eclipse, greatest eclipse 2024-04-08 18:17 UTC: sun and moon in the same place.
  const eclipse = new Date(Date.UTC(2024, 3, 8, 18, 17));
  const s = astro.sunEquatorial(eclipse);
  const m = astro.moonEquatorial(eclipse);
  close(m.dec / (Math.PI / 180), s.dec / (Math.PI / 180), 1.5, 'declination');
  const dra = Math.abs(((m.ra - s.ra) / (Math.PI / 180) + 540) % 360 - 180);
  close(dra, 0, 1.5, 'right ascension');
  // Seen from the eclipse path (Dallas), both stand together, high in the southern sky.
  const sunAt = astro.sunPosition(eclipse, 32.8, -96.8);
  const moonAt = astro.moonPosition(eclipse, 32.8, -96.8);
  close(sunAt.alt, moonAt.alt, 2, 'altitude');
  close(sunAt.az, moonAt.az, 3, 'azimuth');
  close(sunAt.alt, 64, 3, 'sun altitude');
  // New moon at the eclipse; full moon 2024-04-23 23:49 UTC.
  const atEclipse = astro.moonPhase(eclipse);
  if (atEclipse.lit > 0.02) throw new Error(`lit at new moon: ${atEclipse.lit}`);
  const full = astro.moonPhase(new Date(Date.UTC(2024, 3, 23, 23, 49)));
  close(full.phase, 0.5, 0.03, 'full moon phase');
  if (full.lit < 0.98) throw new Error(`lit at full moon: ${full.lit}`);
});

test('sun stands high at noon, below the horizon at midnight', () => {
  // London, midsummer: about 62 degrees at solar noon (12:01 UTC), well below at midnight.
  const noon = astro.sunPosition(new Date(Date.UTC(2026, 5, 21, 12, 1)), 51.5, -0.1);
  if (Math.abs(noon.alt - 62) > 1.5 || Math.abs(noon.az - 180) > 3) throw new Error(JSON.stringify(noon));
  const midnight = astro.sunPosition(new Date(Date.UTC(2026, 5, 21, 0, 1)), 51.5, -0.1);
  if (midnight.alt > -10) throw new Error(JSON.stringify(midnight));
});

test("the moon's lit side faces the sun, both hemispheres", () => {
  // An evening crescent, 2026-11-14: the sun just set, so the lit side faces
  // down and towards it (anticlockwise from up: negative is to the right). A
  // straight line on the sky from the moon to the sun is a fair check this close.
  const towardsSun = (t, lat, lon) => {
    const m = astro.moonPosition(t, lat, lon);
    const s = astro.sunPosition(t, lat, lon);
    const x = (((s.az - m.az + 540) % 360) - 180) * Math.cos(((m.alt + s.alt) / 2) * (Math.PI / 180));
    return Math.atan2(-x, s.alt - m.alt) / (Math.PI / 180);
  };
  for (const [iso, lat, lon, side] of [
    ['2026-11-14T17:00:00Z', 51.5, -0.1, -1],    // London: facing south, the sun is to the right
    ['2026-11-14T09:00:00Z', -33.9, 151.2, 1],   // Sydney: facing north, the sun is to the left
  ]) {
    const t = new Date(iso);
    const limb = astro.brightLimb(t, lat, lon);
    if (Math.sign(limb) !== side || Math.abs(limb - towardsSun(t, lat, lon)) > 10) {
      throw new Error(`${iso}: ${limb} vs ${towardsSun(t, lat, lon)}`);
    }
  }
});

test('mountain ridges: inside their band, nearer below farther, the same every time', () => {
  const gen = (seed) => () => (seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296;
  const a = ridges(gen(7));
  eq(a, ridges(gen(7)));  // a fixed seed draws the same mountains on every visit
  if (a.length !== 3 || a.some((ys) => ys.length !== 101)) throw new Error('three ranges, x = 0..100');
  for (const ys of a) {
    if (ys.some((y) => !(y >= 1 && y <= 29))) throw new Error(`outside the band: ${Math.min(...ys)}..${Math.max(...ys)}`);
  }
  for (let i = 1; i < a.length; i++) {
    if (a[i].some((y, x) => y < a[i - 1][x] + 1 - 1e-9)) throw new Error(`range ${i} rises above the one behind it`);
  }
  // Irregular, not a smooth curve: neighbouring slopes differ along every range.
  for (const ys of a) {
    const slopes = ys.slice(1).map((y, x) => y - ys[x]);
    if (new Set(slopes.map((d) => d.toFixed(2))).size < 10) throw new Error('ridge too regular');
  }
});

test('sky: glides from minute to minute, jumps after a gap (a device asleep overnight)', () => {
  const bg = document.createElement('div');
  bg.id = 'bg';
  document.body.append(bg);
  try {
    initSky();
    const loc = [47.5, -121.8];
    const t = new Date(2026, 9, 23, 23, 30);
    paintSky(t, loc);
    bg.classList.add('settled');  // as two frames after a paint
    paintSky(new Date(t.getTime() + 60_000), loc);
    if (!bg.classList.contains('settled')) throw new Error('a one-minute step should glide');
    paintSky(new Date(t.getTime() + 9.5 * 3_600_000), loc);  // the next morning
    if (bg.classList.contains('settled')) throw new Error('after a gap the sky should jump, not glide for a minute');
  } finally {
    bg.remove();
  }
});

const failed = results.filter(([ok]) => !ok);
document.getElementById('out').textContent = results.map(([ok, n]) => `${ok ? 'ok  ' : 'FAIL'} ${n}`).join('\n');
document.title = failed.length ? `FAIL ${failed.length} of ${results.length}` : `PASS ${results.length}`;
