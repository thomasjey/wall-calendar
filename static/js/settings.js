// Display settings from /api/settings. Only known keys of the expected type are
// copied (never Object.assign from JSON, which would honour a "__proto__" key).

export const DEFAULTS = Object.freeze({
  clock: '12h', weekStart: 'sunday', showNotes: true, idleSeconds: 120,
  photoIntervalSeconds: 600, nightDim: [], location: null, mock: false,
});

const isTime = (t) => typeof t === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(t);
const CHECKS = {
  clock: (v) => v === '12h' || v === '24h',
  weekStart: (v) => v === 'sunday' || v === 'monday',
  showNotes: (v) => typeof v === 'boolean',
  idleSeconds: (v) => Number.isInteger(v) && v >= 15 && v <= 3600,
  photoIntervalSeconds: (v) => Number.isInteger(v) && v >= 10 && v <= 86400,
  nightDim: (v) => Array.isArray(v) && (v.length === 0 || (v.length === 2 && v.every(isTime))),
  location: (v) => Array.isArray(v) && v.length === 2 && v.every((n) => typeof n === 'number' && Number.isFinite(n))
    && Math.abs(v[0]) <= 90 && Math.abs(v[1]) <= 180,
  mock: (v) => typeof v === 'boolean',
};

// Returns { settings, offsetMs }; offsetMs is non-zero only with mock --now.
export function parseSettings(body, nowMs = Date.now()) {
  const settings = { ...DEFAULTS, nightDim: [...DEFAULTS.nightDim] };
  if (body === null || typeof body !== 'object') return { settings, offsetMs: 0 };
  for (const [key, ok] of Object.entries(CHECKS)) {
    if (Object.hasOwn(body, key) && ok(body[key])) settings[key] = body[key];
  }
  const t = typeof body.debugNow === 'string' ? Date.parse(body.debugNow) : NaN;
  return { settings, offsetMs: Number.isNaN(t) ? 0 : t - nowMs };
}
