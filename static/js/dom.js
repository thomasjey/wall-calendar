// The only way the app creates DOM (DESIGN §8.2). Text is always added as text
// nodes or textContent; HTML strings are never parsed.

const SAFE_ATTR = /^(aria-[a-z]+|role|type|tabindex|data-[a-z-]+)$/;
const COLOR = /^#[0-9A-Fa-f]{6}$/;
const PHOTO = /^\/photos\/[0-9a-f]{16}$/;

// el('div', {cls, text, attrs, on, color}, ...children)
// Children may be nodes or strings (strings become text nodes).
export function el(tag, opts = {}, ...children) {
  const node = document.createElement(tag);
  if (opts.cls) node.className = opts.cls;
  if (opts.text != null) node.textContent = String(opts.text);
  for (const [k, v] of Object.entries(opts.attrs || {})) {
    if (!SAFE_ATTR.test(k)) throw new Error(`attribute not allowed: ${k}`);
    node.setAttribute(k, String(v));
  }
  for (const [type, fn] of Object.entries(opts.on || {})) node.addEventListener(type, fn);
  if (opts.color) setCalColor(node, opts.color);
  for (const c of children) if (c != null && c !== false) node.append(c);
  return node;
}

// Calendar colors are validated again here, then applied through the CSSOM
// (CSP blocks inline style attributes).
export function setCalColor(node, color) {
  if (typeof color === 'string' && COLOR.test(color)) node.style.setProperty('--cal', color);
}

// A native hover tooltip. Browsers show it as plain text, so it is safe for
// untrusted event text.
export function setTooltip(node, text) {
  node.setAttribute('title', String(text));
}

// Hovering over text cut off with an ellipsis shows it in full as a native
// tooltip (laptop and desktop; the touch kiosk taps for the details panel).
// Tooltips render as plain text, so untrusted event text stays inert.
export function showFullTextOnHover(container, selector) {
  container.addEventListener('mouseover', (e) => {
    const target = e.target instanceof Element ? e.target.closest(selector) : null;
    if (!target || !container.contains(target)) return;
    if (target.scrollWidth > target.clientWidth) target.setAttribute('title', target.textContent);
    else target.removeAttribute('title');
  });
}

export function setPhoto(img, url) {
  if (typeof url !== 'string' || !PHOTO.test(url)) return false;
  img.src = url;
  return true;
}
