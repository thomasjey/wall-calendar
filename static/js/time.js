// Dates and times in the browser's local zone (the Pi's system zone).
// Pure functions; tested by /tests/ in mock mode.

export const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];

const pad = (n) => String(n).padStart(2, '0');

export const dateKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export function fromKey(key) {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
// Calendar arithmetic, so DST days still advance by exactly one date.
export const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
export const firstOfMonth = (d, n = 0) => new Date(d.getFullYear(), d.getMonth() + n, 1);
export const sameDay = (a, b) => dateKey(a) === dateKey(b);

export function weekStartOf(d, weekStart) {
  const first = weekStart === 'monday' ? 1 : 0;
  return addDays(startOfDay(d), -((d.getDay() - first + 7) % 7));
}

// [start, end) of the month grid containing d.
export function monthGrid(d, weekStart) {
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0);
  return { start: weekStartOf(firstOfMonth(d), weekStart), end: addDays(weekStartOf(last, weekStart), 7) };
}

export function clockParts(d, clock) {
  const h = d.getHours();
  const m = pad(d.getMinutes());
  if (clock === '24h') return { time: `${pad(h)}:${m}`, ampm: '' };
  return { time: `${h % 12 || 12}:${m}`, ampm: h < 12 ? 'AM' : 'PM' };
}

export function fmtTime(d, clock) {
  const { time, ampm } = clockParts(d, clock);
  return ampm ? `${time} ${ampm}` : time;
}

// How a day relates to today: "Today", "Tomorrow", "Yesterday", "In 5 days", "3 days ago".
export function relativeDay(day, today) {
  const n = Math.round((startOfDay(day) - startOfDay(today)) / 86_400_000);
  if (n === 0) return 'Today';
  if (n === 1) return 'Tomorrow';
  if (n === -1) return 'Yesterday';
  return n > 0 ? `In ${n} days` : `${-n} days ago`;
}

export const longDate = (d) => `${DOW[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}`;
export const shortDate = (d) => `${DOW[d.getDay()].slice(0, 3)}, ${MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()}`;

// True when a timed event runs past the end of its start day (ending exactly
// at midnight does not count).
export const crossesMidnight = (s, e) => e > s && !sameDay(s, new Date(e.getTime() - 1));

// "5:15 – 6:00 PM", "11:30 AM – 12:30 PM", or with dates when it crosses midnight.
export function fmtRange(s, e, clock) {
  if (crossesMidnight(s, e)) {
    return `${shortDate(s)}, ${fmtTime(s, clock)} – ${shortDate(e)}, ${fmtTime(e, clock)}`;
  }
  if (e - s < 60000) return fmtTime(s, clock);
  const a = clockParts(s, clock);
  const b = clockParts(e, clock);
  if (a.ampm && a.ampm === b.ampm) return `${a.time} – ${b.time} ${b.ampm}`;
  return `${fmtTime(s, clock)} – ${fmtTime(e, clock)}`;
}

// dateKey -> events touching that local day. An event ending exactly at
// midnight does not touch the next day.
export function bucket(events) {
  const map = new Map();
  const push = (d, ev) => {
    const k = dateKey(d);
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(ev);
  };
  for (const ev of events) {
    if (ev.allDay) {
      const end = fromKey(ev.endDate);
      for (let d = fromKey(ev.startDate), i = 0; d < end && i < 400; d = addDays(d, 1), i++) push(d, ev);
    } else {
      const s = new Date(ev.start);
      const e = new Date(ev.end);
      if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) continue;
      const lastDay = startOfDay(e > s ? new Date(e.getTime() - 1) : s);
      for (let d = startOfDay(s), i = 0; d <= lastDay && i < 400; d = addDays(d, 1), i++) push(d, ev);
    }
  }
  return map;
}

// True when the event fills the whole of `day` (all-day, or a timed event that
// started before and ends after it).
export function coversDay(ev, day) {
  if (ev.allDay) return true;
  const ds = startOfDay(day);
  return new Date(ev.start) <= ds && new Date(ev.end) >= addDays(ds, 1);
}

export function eventsOn(map, day) {
  const list = (map.get(dateKey(day)) || []).slice();
  const key = (ev) => (coversDay(ev, day) ? -Infinity : Math.max(new Date(ev.start), startOfDay(day)));
  return list.sort((a, b) => key(a) - key(b) || a.title.localeCompare(b.title));
}

// The label in the time column for an event on a given day.
export function timeLabel(ev, day, clock) {
  if (coversDay(ev, day)) return 'All day';
  const s = new Date(ev.start);
  return s >= startOfDay(day) ? fmtTime(s, clock) : `Until ${fmtTime(new Date(ev.end), clock)}`;
}

// The smaller second line under the start time in the Day view: when the
// event ends ("to 4:30 PM", or "to Sun 9:00 AM" when it ends on a later day).
// Empty for all-day, zero-length, and already-running events (those say "Until …").
export function endLabel(ev, day, clock) {
  if (coversDay(ev, day)) return '';
  const s = new Date(ev.start);
  const e = new Date(ev.end);
  if (s < startOfDay(day) || e - s < 60_000) return '';
  return crossesMidnight(s, e) ? `to ${DOW[e.getDay()].slice(0, 3)} ${fmtTime(e, clock)}` : `to ${fmtTime(e, clock)}`;
}

// The when-line in the details panel.
export function whenText(ev, day, clock) {
  if (ev.allDay) {
    const s = fromKey(ev.startDate);
    const last = addDays(fromKey(ev.endDate), -1);
    return sameDay(s, last) ? `All day · ${shortDate(s)}` : `All day · ${shortDate(s)} – ${shortDate(last)}`;
  }
  const s = new Date(ev.start);
  const e = new Date(ev.end);
  const range = fmtRange(s, e, clock);
  return crossesMidnight(s, e) ? range : `${shortDate(s)} · ${range}`;
}

// "HH:MM" pair; true when `now` is inside the range (which may cross midnight).
export function inDailyRange(now, range) {
  if (!Array.isArray(range) || range.length !== 2) return false;
  const mins = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
  const n = now.getHours() * 60 + now.getMinutes();
  const a = mins(range[0]);
  const b = mins(range[1]);
  return a <= b ? n >= a && n < b : n >= a || n < b;
}

// ----- the sky backdrop (DESIGN §10.1), shown when there are no photos -----

// Sunrise and sunset for the local date of `day` at [lat, lon], as Dates, using
// NOAA's solar equations (accurate to a minute or two). null at the poles on
// days the sun doesn't rise or set.
export function sunTimes(day, lat, lon) {
  const y = day.getFullYear();
  const start = Date.UTC(y, 0, 1);
  const n = Math.round((Date.UTC(y, day.getMonth(), day.getDate()) - start) / 86400000);
  const g = (2 * Math.PI / 365) * n;
  const eqtime = 229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g)
    - 0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  const decl = 0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) - 0.006758 * Math.cos(2 * g)
    + 0.000907 * Math.sin(2 * g) - 0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  const rad = Math.PI / 180;
  const arg = Math.cos(90.833 * rad) / (Math.cos(lat * rad) * Math.cos(decl)) - Math.tan(lat * rad) * Math.tan(decl);
  if (arg < -1 || arg > 1) return null;
  const ha = Math.acos(arg) / rad;
  const utcMidnight = Date.UTC(y, day.getMonth(), day.getDate());
  return {
    sunrise: new Date(utcMidnight + (720 - 4 * (lon + ha) - eqtime) * 60000),
    sunset: new Date(utcMidnight + (720 - 4 * (lon - ha) - eqtime) * 60000),
  };
}

// Four gradient stops (top to bottom) for each part of the day; muted so white
// text stays readable everywhere.
export const SKIES = Object.freeze({
  night: ['#0b1022', '#121a33', '#18213d', '#1c2644'],
  dawn: ['#1c2346', '#4a3f6b', '#9a6577', '#c98a72'],
  day: ['#24497a', '#3a6fa3', '#4f85b6', '#5b8fbd'],
  dusk: ['#191d3c', '#3f3463', '#87536f', '#b56e66'],
});

// Colours are blended in OKLCH, the way the eye sees them: orange to blue goes
// through soft pink and lilac, as a real sky does, not through muddy grey.
const toLinear = (v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
const fromLinear = (v) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055);

function hexToOklch(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => toLinear(parseInt(hex.slice(i, i + 2), 16) / 255));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return [L, Math.hypot(A, B), Math.atan2(B, A)];
}

function oklchToHex([L, C, h]) {
  const A = C * Math.cos(h);
  const B = C * Math.sin(h);
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return '#' + rgb.map((v) => Math.round(Math.min(1, Math.max(0, fromLinear(v))) * 255)
    .toString(16).padStart(2, '0')).join('');
}

function mixColor(a, b, t) {
  if (t <= 0) return a;
  if (t >= 1) return b;
  const [l1, c1, h1] = hexToOklch(a);
  const [l2, c2, h2] = hexToOklch(b);
  let dh = h2 - h1;  // the shorter way round the hue wheel
  if (dh > Math.PI) dh -= 2 * Math.PI;
  if (dh < -Math.PI) dh += 2 * Math.PI;
  return oklchToHex([l1 + (l2 - l1) * t, c1 + (c2 - c1) * t, h1 + dh * t]);
}

// The sky's gradient stops at `now`: night, warming to dawn at sunrise, easing
// into day, toward dusk at sunset, back to night. Without a location (or on a
// day with no sunrise), sunrise is taken as 6:30 and sunset as 19:00.
export function skyColors(now, location) {
  const sun = location ? sunTimes(now, location[0], location[1]) : null;
  const at = (h, m) => new Date(now.getFullYear(), now.getMonth(), now.getDate(), h, m).getTime();
  const rise = sun ? sun.sunrise.getTime() : at(6, 30);
  const set = sun ? sun.sunset.getTime() : at(19, 0);
  const min = 60000;
  const mid = (rise + set) / 2;
  const keys = [
    [rise - 90 * min, 'night'], [rise, 'dawn'], [Math.min(rise + 120 * min, mid), 'day'],
    [Math.max(set - 120 * min, mid), 'day'], [set, 'dusk'], [set + 90 * min, 'night'],
  ];
  const t = now.getTime();
  if (t <= keys[0][0] || t >= keys[keys.length - 1][0]) return [...SKIES.night];
  for (let i = 1; i < keys.length; i++) {
    const [t1, s1] = keys[i];
    const [t0, s0] = keys[i - 1];
    if (t <= t1) {
      const f = t1 > t0 ? (t - t0) / (t1 - t0) : 1;
      return SKIES[s0].map((c, j) => mixColor(c, SKIES[s1][j], f));
    }
  }
  return [...SKIES.night];
}
