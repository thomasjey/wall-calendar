// The sky backdrop (DESIGN §10.1), shown where there are no photos: a gradient
// that follows the day, stars at night, the sun and the moon (in its real
// phase, lit side towards the sun) where they really are, and hills along the bottom. Built once from
// SVG elements (no markup strings, so Trusted Types is untouched), then moved
// and recoloured once a minute: cheap on the Pi.

import { brightLimb, moonPhase, moonPosition, sunPosition } from './astro.js';
import { mixColor, skyColors } from './time.js';

const SVG = 'http://www.w3.org/2000/svg';
const STARS = 70;
const NIGHT_GROUND = '#05070f';

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  node.append(...children);
  return node;
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// A small deterministic random sequence, so the stars stay put between visits.
function seeded(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// A soft halo fading out from `from` (a fraction of the radius); its colour
// comes from the stylesheet, so the low sun can warm it.
function glow(id, from) {
  return svg('defs', {}, svg('radialGradient', { id },
    svg('stop', { offset: from, class: 'halo', 'stop-opacity': 0.5 }),
    svg('stop', { offset: 1, class: 'halo', 'stop-opacity': 0 })));
}

// The three ranges of hills (far to near), on the hills' 100 x 30 drawing,
// as y values at x = 0..100. The recipe of the sample photos (samplephotos.py):
// a broad swell per range, more swells for nearer ones, plus small irregular
// facets joined by straight lines; each nearer range stays below the one behind.
const RANGES = [  // base height, swell height, swell length (radians across the width)
  [11, 5, 3.2],
  [16.5, 3.5, 5.5],
  [22, 2.5, 8],
];
const FACETS = 18;

export function ridges(rand) {
  const step = 100 / FACETS;
  let behind = null;
  return RANGES.map(([base, swell, span]) => {
    const phase = rand() * 2 * Math.PI;
    const jag = Array.from({ length: FACETS + 2 }, () => rand() * 2 - 1);
    const ys = [];
    for (let x = 0; x <= 100; x++) {
      const k = Math.floor(x / step);
      const facet = jag[k] + (jag[k + 1] - jag[k]) * ((x % step) / step);
      let y = base + swell * Math.sin((x / 100) * span + phase) + 1.6 * facet;
      if (behind) y = Math.max(y, behind[x] + 1);
      ys.push(Math.min(29, Math.max(1, y)));
    }
    behind = ys;
    return ys;
  });
}

// The mountains as first drawn and chosen (2026-10-23): this generator and seed.
function ridgeRandom(seed) {
  let s = seed >>> 0;
  return () => (s = (s * 1103515245 + 12345) >>> 0) / 4294967296;
}

const ridgePath = (ys) => `M${ys.map((y, x) => `${x},${y.toFixed(2)}`).join(' L')} L100,30 L0,30 Z`;

let parts = null;

export function initSky() {
  const bg = document.getElementById('bg');
  const rand = seeded(20261022);
  const stars = svg('svg', { class: 'stars', viewBox: '0 0 100 100', preserveAspectRatio: 'none' });
  for (let i = 0; i < STARS; i++) {
    stars.append(svg('circle', { cx: (rand() * 100).toFixed(2), cy: (rand() * 62).toFixed(2),
      r: (0.08 + rand() * 0.22).toFixed(2), opacity: (0.45 + rand() * 0.55).toFixed(2) }));
  }
  const sun = svg('svg', { class: 'orb sun', viewBox: '-2 -2 4 4' },
    glow('sun-glow', 0.3), svg('circle', { r: 2, class: 'glow', fill: 'url(#sun-glow)' }),
    svg('circle', { r: 0.62, class: 'disc' }));
  const lit = svg('path', { class: 'lit' });
  // Only the lit part is drawn, and its glow (app.css) follows that shape: a
  // crescent shows as a crescent, not as a full disc with a dark side.
  const moon = svg('svg', { class: 'orb moon', viewBox: '-1.6 -1.6 3.2 3.2' }, lit);
  const hills = svg('svg', { class: 'hills', viewBox: '0 0 100 30', preserveAspectRatio: 'none' },
    ...ridges(ridgeRandom(20261023)).map((ys, i) => svg('path', { class: `hill h${i}`, d: ridgePath(ys) })));
  bg.append(stars, sun, moon, hills);  // back to front
  parts = { bg, stars, sun, moon, lit, hills };
}

// Where a body sits: --x from -1 (east, on the left when facing the equator)
// to 1 (west), --y from 0 at the horizon to 1 overhead. The stylesheet turns
// them into a spot clear of the events for each layout.
function place(node, pos, lat) {
  const facing = lat >= 0 ? 180 : 0;
  const rel = ((pos.az - facing + 540) % 360) - 180;
  node.style.setProperty('--x', clamp(rel / 90, -1, 1).toFixed(4));
  node.style.setProperty('--y', (clamp(pos.alt, -3, 90) / 90).toFixed(4));
}

// The lit part of the moon on a unit disc, lit side to the right: a semicircle
// plus the terminator. paintSky turns it to face the sun.
function moonPath(lit) {
  const rx = Math.abs(1 - 2 * lit).toFixed(3);
  return `M0,-1 A1,1 0 0 1 0,1 A${rx},1 0 0 ${lit > 0.5 ? 1 : 0} 0,-1 Z`;
}

// Fallback position when no location is configured: latitude 40, longitude
// from the device's time zone (15 degrees an hour).
function fallbackLocation(now) {
  return [40, -now.getTimezoneOffset() / 4];
}

export function paintSky(now, location) {
  const colors = skyColors(now, location);
  const body = document.body;
  colors.forEach((c, i) => body.style.setProperty(`--sky-${i}`, c));
  [0.42, 0.56, 0.7].forEach((t, i) => body.style.setProperty(`--hill-${i}`, mixColor(colors[3], NIGHT_GROUND, t)));
  if (!parts) return;
  const [lat, lon] = location || fallbackLocation(now);
  const sun = sunPosition(now, lat, lon);
  const moon = moonPosition(now, lat, lon);
  const { lit } = moonPhase(now);

  parts.stars.style.opacity = String(clamp((-sun.alt - 4) / 8, 0, 1) * 0.85);
  place(parts.sun, sun, lat);
  parts.sun.style.opacity = String(clamp((sun.alt + 4) / 6, 0, 1));
  parts.sun.classList.toggle('low', sun.alt < 12);  // warmer and larger near the horizon
  place(parts.moon, moon, lat);
  const daylight = clamp((sun.alt + 6) / 12, 0, 1);  // the moon fades in daylight
  parts.moon.style.opacity = String(clamp((moon.alt + 2) / 4, 0, 1) * (1 - 0.6 * daylight) * (lit < 0.03 ? 0 : 1));
  parts.lit.setAttribute('d', moonPath(lit));
  // brightLimb is anticlockwise from up; the path's lit side starts at the right.
  parts.lit.setAttribute('transform', `rotate(${(-90 - brightLimb(now, lat, lon)).toFixed(1)})`);
  // From the second frame on, later paints glide rather than jump.
  if (!parts.bg.classList.contains('settled')) {
    requestAnimationFrame(() => requestAnimationFrame(() => parts.bg.classList.add('settled')));
  }
}
