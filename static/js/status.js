// The status line in the bottom corner (DESIGN §10.1). It tells apart the two
// ways the data can go old, because they have different causes:
// - the page can't reach its server (the device's network, or the server is
//   down): "Potential outage since <the last time it could>";
// - the page reaches its server, but the calendars haven't synced (Microsoft's
//   service is down, or the server's own network): "Calendars not updated
//   since <the oldest calendar's last sync>". The page keeps showing the last
//   good events in both cases.

export const STALE_MIN = 15;
export const OFFLINE_MIN = 60;

// s: { signedOut, data, waking, lastFetchOk, lastFetchOkAt (ms or null), nowMs, fmt (Date -> text) }.
// Returns { text, cls }; an empty text when all is well.
export function statusLine(s) {
  if (s.signedOut) return { text: 'Signed out', cls: 'bad' };  // reloads through sign-in (signin.js)
  const d = s.data;
  if (!d || d.error) return { text: 'Waiting for calendar data', cls: 'warn' };
  if (d.auth === 'reauth_required') return { text: 'Calendar sign-in needed', cls: 'bad' };
  // Back from sleep: last night's data is old until the first refresh has had its chance.
  if (s.waking) return { text: '', cls: '' };

  if (!s.lastFetchOk && s.lastFetchOkAt !== null && (s.nowMs - s.lastFetchOkAt) / 60000 > OFFLINE_MIN) {
    return { text: `Potential outage since ${s.fmt(new Date(s.lastFetchOkAt))}`, cls: 'bad' };
  }
  const times = (d.calendars || []).map((c) => c.lastSuccessAt).filter(Boolean)
    .map((t) => new Date(t).getTime()).filter(Number.isFinite);
  const oldest = times.length ? Math.min(...times) : null;
  const mins = oldest === null ? Infinity : (s.nowMs - oldest) / 60000;
  if (mins > OFFLINE_MIN) {
    return { text: oldest === null ? 'Calendars not updated' : `Calendars not updated since ${s.fmt(new Date(oldest))}`, cls: 'bad' };
  }
  if (mins > STALE_MIN || !s.lastFetchOk) return { text: `Updated ${Math.round(mins)} min ago`, cls: 'warn' };
  return { text: '', cls: '' };
}
