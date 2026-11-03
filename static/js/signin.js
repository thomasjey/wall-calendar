// The online page sits behind Azure's built-in sign-in (DESIGN §15.4). When
// that session ends (after 12 hours), the page's requests are refused, with a
// 401 or a redirect to Microsoft's sign-in, and the page can't recover by
// itself. Reloading it goes through sign-in, which usually completes without
// typing anything. It's tried only while someone is looking (the window
// visible and focused) and at most once every 30 minutes, so a real sign-in
// problem can't make the page reload over and over. The kiosk's local server
// never refuses, so none of this happens on the wall.

export const RETRY_MS = 30 * 60_000;
const KEY = 'fwcal.signinReloadAt';

// A fetch made with { redirect: 'manual' }: a redirect shows as 'opaqueredirect'.
export function signInRefused(res) {
  return res.status === 401 || res.type === 'opaqueredirect';
}

export function mayReload(now, lastAt, looking) {
  if (!looking) return false;
  return lastAt === null || now - lastAt >= RETRY_MS || now < lastAt;
}

// Reloads (and returns true) if allowed. Without session storage there is no
// way to remember the last try across the reload, so it never reloads then.
export function reloadForSignIn(win = window) {
  let lastAt = null;
  try {
    const v = win.sessionStorage.getItem(KEY);
    lastAt = v === null ? null : Number(v);
  } catch {
    return false;
  }
  const looking = !win.document.hidden && win.document.hasFocus();
  const now = Date.now();
  if (!mayReload(now, Number.isFinite(lastAt) ? lastAt : null, looking)) return false;
  try {
    win.sessionStorage.setItem(KEY, String(now));
  } catch {
    return false;
  }
  win.location.reload();
  return true;
}
