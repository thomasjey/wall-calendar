// Background photo crossfade (DESIGN §10.1). Photos come only from /photos/.

import { setPhoto } from './dom.js';

const LIST_REFRESH_MS = 60 * 60 * 1000;

let urls = [];
let index = 0;
let front = 0;

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

async function loadList() {
  try {
    const r = await fetch('/api/photos', { cache: 'no-store' });
    if (!r.ok) return;
    const body = await r.json();
    if (Array.isArray(body.photos)) urls = shuffle(body.photos.filter((u) => typeof u === 'string'));
  } catch {
    // keep the current list
  }
}

async function showNext() {
  if (!urls.length || document.hidden) return; // no decoding work in a hidden tab
  const layers = document.querySelectorAll('#bg .photo');
  const back = layers[1 - front];
  const url = urls[index++ % urls.length];
  if (!setPhoto(back, url)) return;
  try {
    await back.decode();
  } catch {
    return; // unreadable photo: keep the current one
  }
  back.classList.add('on');
  layers[front].classList.remove('on');
  front = 1 - front;
}

export async function initPhotos(intervalSeconds) {
  await loadList();
  await showNext();
  setInterval(showNext, intervalSeconds * 1000);
  setInterval(loadList, LIST_REFRESH_MS);
}
