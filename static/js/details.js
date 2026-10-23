// Event details bottom sheet (DESIGN §10.3). Notes are plain text and are
// never turned into links.

import { el, setCalColor } from './dom.js';
import { whenText } from './time.js';

const AUTO_CLOSE_MS = 60_000;
const SWIPE_CLOSE_PX = 80;

const sheet = () => document.getElementById('sheet');
const panel = () => document.getElementById('panel');
let timer = null;

export function closeDetails() {
  clearTimeout(timer);
  sheet().hidden = true;
  panel().replaceChildren();
}

export function openDetails(ev, day, cal, settings) {
  const p = panel();
  setCalColor(p, cal?.color);
  // replaceChildren() would print a null as the text "null", so drop them.
  p.replaceChildren(...[
    el('div', { cls: 'd-head' },
      el('div', { cls: 'd-title', text: ev.title }),
      el('button', { cls: 'close', text: '✕', attrs: { type: 'button', 'aria-label': 'Close' }, on: { click: closeDetails } })),
    el('div', { cls: 'd-cal' }, el('span', { cls: 'dot', color: cal?.color }), cal?.name ?? ''),
    el('div', { cls: 'd-when', text: whenText(ev, day, settings.clock) }),
    ev.location ? el('div', { cls: 'd-loc', text: ev.location }) : null,
    settings.showNotes && ev.notes ? el('div', { cls: 'd-notes', text: ev.notes }) : null,
  ].filter(Boolean));
  sheet().hidden = false;
  clearTimeout(timer);
  timer = setTimeout(closeDetails, AUTO_CLOSE_MS);
}

export function initDetails() {
  const s = sheet();
  s.addEventListener('click', (e) => { if (e.target === s) closeDetails(); });
  let y0 = null;
  s.addEventListener('pointerdown', (e) => { y0 = e.clientY; });
  s.addEventListener('pointerup', (e) => {
    if (y0 !== null && e.clientY - y0 > SWIPE_CLOSE_PX) closeDetails();
    y0 = null;
  });
}
