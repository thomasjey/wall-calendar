// Wall calendar app: clock, views, navigation, idle reset, status (DESIGN §10).

import { closeDetails, initDetails, openDetails } from './details.js';
import { el, showFullTextOnHover } from './dom.js';
import { initPhotos } from './photos.js';
import { DEFAULTS, parseSettings } from './settings.js';
import { initSky, paintSky } from './sky.js';
import {
  addDays, bucket, clockParts, firstOfMonth, fmtTime, fromKey, inDailyRange, longDate,
  monthGrid, startOfDay, weekStartOf,
} from './time.js';
import * as views from './views.js';

const POLL_MS = 60_000;
const STALE_MIN = 15;
const OFFLINE_MIN = 60;
const SWIPE_PX = 60;
const DRAG_PX = 12;  // horizontal movement before the page starts to follow the finger
const RELOAD_HOUR = 3;

const state = {
  settings: { ...DEFAULTS },
  offsetMs: 0, // non-zero only with mock --now
  data: null,
  byDay: new Map(),
  cals: new Map(),
  view: 'day',
  focus: null,
  lastFetchOk: true,
  loadedAt: Date.now(),
  lastMinute: '',
  etag: null,
  tickTimer: null,
  pollTimer: null,
};

const $ = (id) => document.getElementById(id);
const now = () => new Date(Date.now() + state.offsetMs);

async function getJSON(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

// Window bounds as local dates; [start, end).
function windowRange() {
  const w = state.data?.window;
  return w ? [fromKey(w.start), fromKey(w.end)] : null;
}
function inWindow(day) {
  const w = windowRange();
  return !!w && day >= w[0] && day < w[1];
}
function overlapsWindow(start, end) {
  const w = windowRange();
  return !!w && start < w[1] && end > w[0];
}

function setData(data) {
  state.data = data;
  state.cals = new Map((data.calendars || []).map((c) => [c.key, c]));
  state.byDay = bucket(data.events || []);
}

// Conditional request: the server answers 304 (no body) until the data changes.
async function refresh() {
  try {
    const headers = state.etag ? { 'If-None-Match': state.etag } : {};
    const r = await fetch('/api/events', { cache: 'no-store', headers });
    if (r.status !== 304) {
      if (!r.ok) throw new Error(`events: ${r.status}`);
      const data = await r.json();
      state.etag = r.headers.get('ETag');
      if (data.generatedAt !== state.data?.generatedAt || data.error) {
        setData(data);
        render();
      }
    }
    state.lastFetchOk = true;
  } catch {
    state.lastFetchOk = false;
  }
  renderStatus();
}

// ----- rendering -----

function renderClock() {
  const n = now();
  const { time, ampm } = clockParts(n, state.settings.clock);
  $('time').textContent = time;
  $('ampm').textContent = ampm;
  $('date').textContent = longDate(n);
}

function viewCtx(focus) {
  return {
    now: now(), focus, byDay: state.byDay, cals: state.cals, settings: state.settings,
    inWindow,
    openEvent: (ev, day) => openDetails(ev, day, state.cals.get(ev.cal), state.settings),
    goDay: (day) => { state.view = 'day'; state.focus = startOfDay(day); render(); },
  };
}

function render({ keepScroll = false } = {}) {
  const view = $('view');
  const top = view.scrollTop;
  view.replaceChildren(views[state.view](viewCtx(state.focus)));
  peek = null;  // replaceChildren removed any page drawn beside this one
  dragX = 0;
  view.scrollTop = keepScroll ? top : 0;
  for (const b of document.querySelectorAll('#tabs button')) {
    const on = b.dataset.view === state.view;
    b.classList.toggle('on', on);
    b.setAttribute('aria-selected', String(on));
  }
  renderLegend();
  renderStatus();
}

function renderLegend() {
  $('legend').replaceChildren(...[...state.cals.values()].map((c) =>
    el('span', { cls: 'item' }, el('span', { cls: 'dot', color: c.color }), c.name)));
}

function renderStatus() {
  const s = $('status');
  const d = state.data;
  let text = '';
  let cls = '';
  if (!d || d.error) {
    text = 'Waiting for calendar data';
    cls = 'warn';
  } else if (d.auth === 'reauth_required') {
    text = 'Calendar sign-in needed';
    cls = 'bad';
  } else {
    const times = d.calendars.map((c) => c.lastSuccessAt).filter(Boolean).map((t) => new Date(t));
    const oldest = times.length ? new Date(Math.min(...times)) : null;
    const mins = oldest ? (now() - oldest) / 60000 : Infinity;
    if (mins > OFFLINE_MIN) {
      text = oldest ? `Offline since ${fmtTime(oldest, state.settings.clock)}` : 'Offline';
      cls = 'bad';
    } else if (mins > STALE_MIN || !state.lastFetchOk) {
      text = `Updated ${Math.round(mins)} min ago`;
      cls = 'warn';
    }
  }
  if (state.settings.mock) text = text ? `Mock data · ${text}` : 'Mock data';
  s.textContent = text;
  s.className = cls;
}

// ----- navigation -----

function toast(text) {
  const t = $('toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 2000);
}

// Where paging one step in `dir` (+1 next, -1 previous) leads, or null if that
// page is outside the synced window.
function neighbour(dir) {
  const f = state.focus;
  let next;
  let range;
  if (state.view === 'day') {
    next = addDays(f, dir);
    range = [next, addDays(next, 1)];
  } else if (state.view === 'week') {
    next = addDays(f, 7 * dir);
    const ws = weekStartOf(next, state.settings.weekStart);
    range = [ws, addDays(ws, 7)];
  } else {
    next = firstOfMonth(f, dir);
    const g = monthGrid(next, state.settings.weekStart);
    range = [g.start, g.end];
  }
  return overlapsWindow(range[0], range[1]) ? next : null;
}

// Paging as a reel (DESIGN §10.2): during a drag the neighbouring page is drawn
// just beside the current one and both move with the finger; on release they
// roll on to it or back. Swiping left brings the next page, as in other
// calendars. Only transforms change, so it's cheap on the Pi; with reduced
// motion the page simply changes.
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const ROLL_MS = 220;
const EDGE_RESISTANCE = 0.25;  // how far the page gives when there is nothing beyond it
const page = () => $('view').firstElementChild;
let peek = null;  // { dir, next, el }: the neighbouring page drawn beside the current one
let dragX = 0;    // where the current page is drawn now

function showPeek(dir) {
  if (peek && peek.dir === dir) return peek;
  dropPeek();
  const next = neighbour(dir);
  if (!next) return null;
  const v = $('view');
  const el = views[state.view](viewCtx(next));
  el.classList.add('peek');
  el.style.top = `${v.scrollTop}px`;
  v.append(el);
  peek = { dir, next, el };
  return peek;
}

function dropPeek() {
  peek?.el.remove();
  peek = null;
}

function dragTo(dx) {
  const cur = page();
  if (!cur || reduceMotion.matches) return;
  const dir = dx < 0 ? 1 : -1;
  const p = dx ? showPeek(dir) : null;
  dragX = p ? dx : dx * EDGE_RESISTANCE;
  cur.style.transform = `translateX(${dragX}px)`;
  if (p) p.el.style.transform = `translateX(${dragX + dir * $('view').clientWidth}px)`;
}

function navigate(dir) {
  const p = reduceMotion.matches ? null : showPeek(dir);
  const next = p ? p.next : neighbour(dir);
  if (!next) {
    toast(dir > 0 ? 'Not synced this far ahead' : 'Not synced this far back');
    rollBack();
    return;
  }
  const cur = page();
  if (!p || !cur?.animate) {
    dropPeek();
    state.focus = next;
    render();
    return;
  }
  const w = $('view').clientWidth;
  const opts = { duration: ROLL_MS, easing: 'ease-out', fill: 'forwards' };
  cur.style.transform = '';
  p.el.style.transform = '';
  const roll = cur.animate([{ transform: `translateX(${dragX}px)` }, { transform: `translateX(${-dir * w}px)` }], opts);
  p.el.animate([{ transform: `translateX(${dragX + dir * w}px)` }, { transform: 'translateX(0)' }], opts);
  dragX = 0;
  roll.onfinish = () => {
    peek = null;
    state.focus = next;
    render();  // draws the same page in its normal place, so nothing jumps
  };
}

function rollBack() {
  const cur = page();
  const from = dragX;
  dragX = 0;
  if (!cur) return;
  cur.style.transform = '';
  if (!from || reduceMotion.matches || !cur.animate) { dropPeek(); return; }
  const opts = { duration: ROLL_MS * 0.7, easing: 'ease-out' };
  cur.animate([{ transform: `translateX(${from}px)` }, { transform: 'translateX(0)' }], opts);
  if (peek) {
    const { el, dir } = peek;
    const w = $('view').clientWidth;
    el.style.transform = `translateX(${dir * w}px)`;
    el.animate([{ transform: `translateX(${from + dir * w}px)` }, { transform: `translateX(${dir * w}px)` }], opts)
      .onfinish = () => { if (peek?.el === el) dropPeek(); };
  }
}

function goHome() {
  closeDetails();
  state.view = 'day';
  state.focus = startOfDay(now());
  render();
}

function initInput() {
  for (const b of document.querySelectorAll('#tabs button')) {
    b.addEventListener('click', () => {
      state.view = b.dataset.view;
      state.focus = startOfDay(now());
      render();
    });
  }
  const view = $('view');
  showFullTextOnHover(view, '.title, .loc, .chip');
  // Horizontal swipes page; vertical movement is left to scrolling (touch-action: pan-y).
  let start = null;
  let dragging = false;
  let swallowClick = false;
  view.addEventListener('pointerdown', (e) => {
    start = { x: e.clientX, y: e.clientY, id: e.pointerId };
    dragging = false;
    swallowClick = false;  // touch swipes fire no click, so don't let one carry over to the next tap
  });
  view.addEventListener('pointermove', (e) => {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (!dragging && Math.abs(dx) > DRAG_PX && Math.abs(dx) > 1.5 * Math.abs(dy)) {
      dragging = true;
      try { view.setPointerCapture(e.pointerId); } catch { /* pointer already gone: the drag still works */ }
    }
    if (dragging) dragTo(dx);
  });
  view.addEventListener('pointerup', (e) => {
    if (!start || e.pointerId !== start.id) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    const wasDragging = dragging;
    start = null;
    dragging = false;
    swallowClick = wasDragging;  // a drag that ends on an event must not open it
    if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > 1.5 * Math.abs(dy)) navigate(dx < 0 ? 1 : -1);
    else if (wasDragging) rollBack();
  });
  view.addEventListener('pointercancel', (e) => {
    if (!start || e.pointerId !== start.id) return;
    start = null;
    dragging = false;
    rollBack();
  });
  view.addEventListener('click', (e) => {
    if (swallowClick) { swallowClick = false; e.stopPropagation(); e.preventDefault(); }
  }, true);

  // Kiosk: no selection, callout or context menu (DESIGN §8.2).
  document.addEventListener('contextmenu', (e) => e.preventDefault());
  document.addEventListener('selectstart', (e) => e.preventDefault());
  document.addEventListener('dragstart', (e) => e.preventDefault());

  // Laptop development convenience; the kiosk has no keyboard.
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') navigate(-1);
    else if (e.key === 'ArrowRight') navigate(1);
    else if (e.key === 'Escape') closeDetails();
    else if (['1', '2', '3'].includes(e.key)) {
      state.view = ['day', 'week', 'month'][Number(e.key) - 1];
      state.focus = startOfDay(now());
      render();
    }
  });

  let idle = null;
  const resetIdle = () => {
    clearTimeout(idle);
    idle = setTimeout(goHome, state.settings.idleSeconds * 1000);
  };
  for (const type of ['pointerdown', 'keydown']) document.addEventListener(type, resetIdle, { capture: true });
  resetIdle();
}

// ----- clock tick -----


function tick() {
  const n = now();
  const minute = `${n.toDateString()} ${n.getHours()}:${n.getMinutes()}`;
  if (minute === state.lastMinute) return;
  const dayChanged = state.lastMinute && !state.lastMinute.startsWith(n.toDateString());
  state.lastMinute = minute;
  renderClock();
  document.body.classList.toggle('night', inDailyRange(n, state.settings.nightDim));
  paintSky(n, state.settings.location);  // the backdrop where there are no photos
  if (dayChanged) state.focus = startOfDay(n);
  render({ keepScroll: !dayChanged }); // past/now highlighting and status age move with the clock
  if (n.getHours() === RELOAD_HOUR && n.getMinutes() === 0 && Date.now() - state.loadedAt > 3_600_000) {
    window.location.reload();
  }
}

// ----- timers: one wake-up per minute, on the minute; none while hidden -----

function scheduleTick() {
  clearTimeout(state.tickTimer);
  const ms = 60_000 - (now().getTime() % 60_000) + 50; // just after the next minute boundary
  state.tickTimer = setTimeout(() => { tick(); scheduleTick(); }, ms);
}

function schedulePoll() {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => { await refresh(); schedulePoll(); }, POLL_MS);
}

function startTimers() {
  tick(); // catch up at once (after sleep or while the page was hidden)
  scheduleTick();
  refresh();
  schedulePoll();
}

function stopTimers() {
  clearTimeout(state.tickTimer);
  clearTimeout(state.pollTimer);
}

async function main() {
  try {
    ({ settings: state.settings, offsetMs: state.offsetMs } = parseSettings(await getJSON('/api/settings')));
  } catch {
    // defaults
  }
  state.focus = startOfDay(now());
  initDetails();
  initInput();
  initSky();  // before the first tick paints it
  renderClock();
  await refresh();
  if (!state.data) render();
  tick();
  scheduleTick();
  schedulePoll();
  // The kiosk is never hidden; a laptop tab in the background does no work.
  document.addEventListener('visibilitychange', () => (document.hidden ? stopTimers() : startTimers()));
  initPhotos(state.settings.photoIntervalSeconds);
}

main();
