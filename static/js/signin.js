// The online page sits behind Azure's built-in sign-in (DESIGN §15.4). When
// that session ends (after 12 hours), the page's requests are refused, with a
// 401 or a redirect to Microsoft's sign-in, and the page can't recover by
// itself. Starting sign-in again, which usually completes without typing
// anything, brings it back. It starts at the sign-in route with the page as
// an explicit return address (the platform's documented post_login_redirect_uri),
// so it ends on the calendar, never on the platform's "You have successfully
// signed in" page. It's tried only while someone is looking (the window
// visible and focused) and at most once every 30 minutes, so a real sign-in
// problem can't send the page round in circles. The kiosk's local server
// never refuses, so none of this happens on the wall.

export const RETRY_MS = 30 * 60_000;
export const SIGN_IN = '/.auth/login/aad?post_login_redirect_uri=%2F';
const KEY = 'fwcal.signinReloadAt';

// A fetch made with { redirect: 'manual' }: a redirect shows as 'opaqueredirect'.
export function signInRefused(res) {
  return res.status === 401 || res.type === 'opaqueredirect';
}

export function mayReload(now, lastAt, looking) {
  if (!looking) return false;
  return lastAt === null || now - lastAt >= RETRY_MS || now < lastAt;
}

// Signs in again (and returns true) if allowed. Without session storage there is no
// way to remember the last try across the sign-in, so it never tries then.
export function signInAgain(win = window) {
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
  win.location.assign(SIGN_IN);
  return true;
}
