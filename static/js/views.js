// Day, Week and Month views (DESIGN §10.2). Each returns a DOM node.
// ctx: { now, focus, byDay, cals, settings, inWindow(day), openEvent(ev, day), goDay(day) }

import { el, setTooltip } from './dom.js';
import {
  DOW, MONTHS, addDays, coversDay, endLabel, eventsOn, longDate, monthGrid, relativeDay,
  sameDay, startOfDay, timeLabel, weekStartOf,
} from './time.js';

const TOMORROW_MAX = 4;
const WEEK_CHIPS = 3;
const MONTH_DOTS = 8;

const color = (ctx, ev) => ctx.cals.get(ev.cal)?.color;

function chip(ctx, ev, day, withTime) {
  const label = withTime && !coversDay(ev, day) ? `${timeLabel(ev, day, ctx.settings.clock)}  ${ev.title}` : ev.title;
  return el('div', {
    cls: 'chip', text: label, color: color(ctx, ev),
    on: { click: (e) => { e.stopPropagation(); ctx.openEvent(ev, day); } },
  });
}

function more(n) {
  return el('div', { cls: 'more', text: `+${n} more` });
}

export function day(ctx) {
  const { now, focus } = ctx;
  const isToday = sameDay(focus, now);
  const root = el('div', { cls: 'day' });
  root.append(isToday
    ? el('div', { cls: 'label', text: 'Today' })
    : el('div', { cls: 'label' }, el('span', { cls: 'date', text: longDate(focus) }),
      el('span', { cls: 'rel', text: ` · ${relativeDay(focus, now)}` })));

  const list = eventsOn(ctx.byDay, focus);
  if (!ctx.inWindow(focus)) root.append(el('div', { cls: 'empty', text: 'Not synced this far' }));
  else if (!list.length) root.append(el('div', { cls: 'empty', text: 'Nothing scheduled' }));
  for (const ev of list) {
    const end = endLabel(ev, focus, ctx.settings.clock);
    const row = el('div', { cls: 'ev', color: color(ctx, ev), on: { click: () => ctx.openEvent(ev, focus) } },
      el('div', { cls: 't' },
        el('div', { text: timeLabel(ev, focus, ctx.settings.clock) }),
        end ? el('div', { cls: 'end', text: end }) : null),
      el('div', { cls: 'body' },
        el('div', { cls: 'title', text: ev.title }),
        ev.location ? el('div', { cls: 'loc', text: ev.location }) : null));
    if (isToday && !ev.allDay) {
      const s = new Date(ev.start);
      const e = new Date(ev.end);
      if (e <= now) row.classList.add('past');
      else if (s <= now) row.classList.add('now');
    }
    root.append(row);
  }

  if (isToday) {
    const tomorrow = addDays(focus, 1);
    const next = eventsOn(ctx.byDay, tomorrow);
    if (next.length) {
      root.append(el('div', { cls: 'label', text: 'Tomorrow' }));
      for (const ev of next.slice(0, TOMORROW_MAX)) {
        root.append(el('div', { cls: 'next', on: { click: () => ctx.openEvent(ev, tomorrow) } },
          el('span', { cls: 'dot', color: color(ctx, ev) }),
          el('span', { cls: 't', text: timeLabel(ev, tomorrow, ctx.settings.clock) }),
          el('span', { cls: 'title', text: ev.title })));
      }
      if (next.length > TOMORROW_MAX) root.append(more(next.length - TOMORROW_MAX));
    }
  }
  return root;
}

export function week(ctx) {
  const start = weekStartOf(ctx.focus, ctx.settings.weekStart);
  const end = addDays(start, 6);
  const root = el('div', { cls: 'week' });
  const range = start.getMonth() === end.getMonth()
    ? `${MONTHS[start.getMonth()]} ${start.getDate()} – ${end.getDate()}`
    : `${MONTHS[start.getMonth()].slice(0, 3)} ${start.getDate()} – ${MONTHS[end.getMonth()].slice(0, 3)} ${end.getDate()}`;
  root.append(el('div', { cls: 'label', text: range }));
  for (let i = 0; i < 7; i++) {
    const day = addDays(start, i);
    const list = eventsOn(ctx.byDay, day);
    const chips = el('div', { cls: 'chips' });
    for (const ev of list.slice(0, WEEK_CHIPS)) chips.append(chip(ctx, ev, day, true));
    if (!list.length) chips.append(el('div', { cls: 'none', text: ctx.inWindow(day) ? 'No events' : 'Not synced' }));
    const row = el('div', { cls: 'wk-row', on: { click: () => ctx.goDay(day) } },
      el('div', { cls: 'wk-date' },
        el('div', { cls: 'dow', text: DOW[day.getDay()].slice(0, 3) }),
        el('div', { cls: 'num', text: day.getDate() }),
        list.length > WEEK_CHIPS ? el('div', { cls: 'more', text: `+${list.length - WEEK_CHIPS} more` }) : null),
      chips);
    if (sameDay(day, ctx.now)) row.classList.add('is-today');
    root.append(row);
  }
  return root;
}

export function month(ctx) {
  const { focus } = ctx;
  const { start, end } = monthGrid(focus, ctx.settings.weekStart);
  const root = el('div', { cls: 'month' });
  root.append(el('div', { cls: 'label', text: `${MONTHS[focus.getMonth()]} ${focus.getFullYear()}` }));
  const grid = el('div', { cls: 'mgrid' });
  for (let i = 0; i < 7; i++) {
    grid.append(el('div', { cls: 'mdow', text: DOW[addDays(start, i).getDay()].slice(0, 1) }));
  }
  for (let day = start; day < end; day = addDays(day, 1)) {
    const d = startOfDay(day);
    const list = eventsOn(ctx.byDay, d);
    // A glanceable pattern, not tiny text: one dot per event in its calendar's
    // colour (a short pill for all-day events). Tap the day for the details.
    const dots = el('div', { cls: 'mdots' });
    for (const ev of list.slice(0, MONTH_DOTS)) {
      dots.append(el('span', { cls: coversDay(ev, d) ? 'mdot allday' : 'mdot', color: color(ctx, ev) }));
    }
    if (list.length > MONTH_DOTS) dots.append(el('span', { cls: 'mmore', text: `+${list.length - MONTH_DOTS}` }));
    const cell = el('div', { cls: 'mcell', on: { click: () => ctx.goDay(d) } },
      el('div', { cls: 'mnum', text: d.getDate() }), list.length ? dots : null);
    if (list.length) setTooltip(cell, list.map((ev) => `${timeLabel(ev, d, ctx.settings.clock)}  ${ev.title}`).join('\n'));
    if (d.getMonth() !== focus.getMonth()) cell.classList.add('other');
    if (sameDay(d, ctx.now)) cell.classList.add('is-today');
    if (!ctx.inWindow(d)) cell.classList.add('unsynced');
    grid.append(cell);
  }
  grid.style.setProperty('--rows', String(Math.round((end - start) / 864e5 / 7)));
  root.append(grid);
  return root;
}

