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
