// Generates the AppKata GUI mockups as SVG + PNG, with the app's design tokens (THEMES below, the
// same as src/appkata/qml/Theme.qml), window chrome and widgets.
// Usage: NODE_PATH=<dir with @resvg/resvg-js> node screenshots/src/render.js [name-filter]
// Screens are named by perspective: A = Apps, C = Catalog, S = Sources; X = app-wide (menu, tray).
const fs = require('fs');
const path = require('path');
const { Resvg } = require('@resvg/resvg-js');

const OUT = path.resolve(__dirname, '..');
let W = 1280, H = 800;
const PAD = 40;
const SANS = 'Cantarell', MONO = 'DejaVu Sans Mono';

const THEMES = {
  light: {
    backdrop: ['#dfe6f3', '#eee7f6'], bg: '#f5f6fa', side: '#eff1f6', surface: '#ffffff', raised: '#ffffff',
    hover: '#f3f4f8', border: '#e4e7ef', borderStrong: '#d4d8e3', text: '#1b1f2b', muted: '#6a7084', faint: '#a0a6b6',
    accent: '#5a67f2', accentSoft: '#eceefe', ok: '#0f9f6c', okSoft: '#e2f6ed', warn: '#c26a04',
    warnSoft: '#fdf1dc', err: '#e0445a', errSoft: '#fde8eb', track: '#eceef4', illusA: '#edf2ff',
    illusB: '#f5eeff', grid: '#edeff4', input: '#f7f8fb', segOn: '#ffffff', tipBg: '#1b1f2b', tipFg: '#ffffff',
    star: '#e0a106', shadow: 0.07, dark: false,
  },
  dark: {
    backdrop: ['#0b0d13', '#1d1633'], bg: '#15171e', side: '#1a1c24', surface: '#1f222b', raised: '#262a35',
    hover: '#2f3442', border: '#2c303c', borderStrong: '#3a3f4d', text: '#eceef4', muted: '#9aa0b3', faint: '#686d80',
    accent: '#8089ff', accentSoft: '#2a2d52', ok: '#34d399', okSoft: '#133a2d', warn: '#fbbf24',
    warnSoft: '#3a2e12', err: '#fb7185', errSoft: '#3d1a22', track: '#2c303c', illusA: '#222739',
    illusB: '#2a2442', grid: '#2a2e39', input: '#1a1d25', segOn: '#343847', tipBg: '#eceef4', tipFg: '#1b1f2b',
    star: '#fbbf24', shadow: 0.45, dark: true,
  },
};

// ---------------------------------------------------------------- helpers
let defs = [], uid = 0;
const nid = (p = 'i') => `${p}${uid++}`;
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const f1 = n => (+n).toFixed(1);

// real advance widths from the renderer's fonts, cached
const MW = new Map();
function mw(str, size, o = {}) {
  const key = `${o.mono ? 'm' : 's'}${o.bold ? 'b' : ''}|${str}`;
  if (!MW.has(key)) {
    const box = s2 => new Resvg(`<svg xmlns="http://www.w3.org/2000/svg" width="8000" height="200"><text x="10" y="120" font-family="${o.mono ? MONO : SANS}" font-size="100" font-weight="${o.bold ? 700 : 400}">${esc(s2)}</text></svg>`,
      { font: { loadSystemFonts: true } }).innerBBox().width;
    MW.set(key, (box(`|${str}|`) - box('||')) / 100);
  }
  return MW.get(key) * size;
}
const tw = mw;

function text(x, y, s, o = {}) {
  const { size = 14, weight = 400, fill, anchor = 'start', mono = false, ls, op } = o;
  return `<text x="${f1(x)}" y="${f1(y)}" font-family="${mono ? MONO : SANS}" font-size="${size}" font-weight="${weight}"` +
    ` fill="${fill}" text-anchor="${anchor}"${ls != null ? ` letter-spacing="${ls}"` : ''}` +
    `${op != null ? ` opacity="${op}"` : ''}>${esc(s)}</text>`;
}
function rect(x, y, w, h, r, fill, o = {}) {
  return `<rect x="${f1(x)}" y="${f1(y)}" width="${f1(w)}" height="${f1(h)}" rx="${r}" fill="${fill}"` +
    `${o.stroke ? ` stroke="${o.stroke}" stroke-width="${o.sw || 1}"` : ''}` +
    `${o.dash ? ` stroke-dasharray="${o.dash}"` : ''}${o.op != null ? ` opacity="${o.op}"` : ''}` +
    `${o.filter ? ` filter="url(#${o.filter})"` : ''}/>`;
}
const hline = (x1, x2, y, c) => `<path d="M${f1(x1)},${f1(y) }H${f1(x2)}" stroke="${c}"/>`;
function linGrad(stops, x2 = 1, y2 = 0) {
  const id = nid('lg');
  defs.push(`<linearGradient id="${id}" x1="0" y1="0" x2="${x2}" y2="${y2}">` +
    stops.map(([o, c, a = 1]) => `<stop offset="${o}" stop-color="${c}" stop-opacity="${a}"/>`).join('') + '</linearGradient>');
  return id;
}
function clip(x, y, w, h, r) {
  const id = nid('cl');
  defs.push(`<clipPath id="${id}"><rect x="${f1(x)}" y="${f1(y)}" width="${f1(w)}" height="${f1(h)}" rx="${r}"/></clipPath>`);
  return id;
}
// word-wrap plain text into at most `max` lines, ellipsizing the last one
function wrap(str, w, size, max = 99, o = {}) {
  const words = str.split(/\s+/), lines = [];
  let cur = '';
  for (const wd of words) {
    const t = cur ? cur + ' ' + wd : wd;
    if (mw(t, size, o) > w && cur) { lines.push(cur); cur = wd; } else cur = t;
  }
  if (cur) lines.push(cur);
  if (lines.length > max) {
    const out = lines.slice(0, max);
    let last = out[max - 1];
    while (mw(last + '…', size, o) > w) last = last.replace(/\s*\S+$/, '');
    out[max - 1] = last + '…';
    return out;
  }
  return lines;
}
function para(x, y, w, str, T, o = {}) {
  const { size = 13, lh = 19, max = 99, fill = T.muted, weight = 400 } = o;
  const L = wrap(str, w, size, max, { bold: weight === 700 });
  return { s: L.map((l, i) => text(x, y + i * lh, l, { size, fill, weight })).join(''), h: L.length * lh };
}

// ---------------------------------------------------------------- icons (16-unit grid)
const ICONS = {
  grid: '<rect x="2" y="2" width="5" height="5" rx="1.3"/><rect x="9" y="2" width="5" height="5" rx="1.3"/><rect x="2" y="9" width="5" height="5" rx="1.3"/><rect x="9" y="9" width="5" height="5" rx="1.3"/>',
  apps: '<rect x="2" y="2.5" width="12" height="3" rx="1"/><rect x="2" y="6.5" width="12" height="3" rx="1"/><rect x="2" y="10.5" width="12" height="3" rx="1"/>',
  branch: '<circle cx="4.5" cy="3.5" r="1.6"/><circle cx="4.5" cy="12.5" r="1.6"/><circle cx="11.5" cy="5.5" r="1.6"/><path d="M4.5 5.1V10.9M11.5 7.1C11.5 9.5 8 9 4.5 10.9"/>',
  chevDown: '<path d="M4 6L8 10L12 6"/>', chevRight: '<path d="M6 4L10 8L6 12"/>', chevUp: '<path d="M4 10L8 6L12 10"/>',
  plus: '<path d="M8 3V13M3 8H13"/>', x: '<path d="M4 4L12 12M12 4L4 12"/>',
  minimize: '<path d="M4 8.5H12"/>', maximize: '<rect x="3.5" y="3.5" width="9" height="9" rx="1.2"/>',
  pencil: '<path d="M10.5 2.5L13.5 5.5L5.5 13.5H2.5V10.5Z"/><path d="M9 4L12 7"/>',
  dots: '<circle cx="8" cy="3" r="1.2" fill="currentColor"/><circle cx="8" cy="8" r="1.2" fill="currentColor"/><circle cx="8" cy="13" r="1.2" fill="currentColor"/>',
  more: '<circle cx="3" cy="8" r="1.3" fill="currentColor"/><circle cx="8" cy="8" r="1.3" fill="currentColor"/><circle cx="13" cy="8" r="1.3" fill="currentColor"/>',
  panel: '<rect x="1.8" y="2.8" width="12.4" height="10.4" rx="2"/><path d="M10 3V13"/>',
  check: '<path d="M3 8.5L6.5 12L13 4.5"/>',
  warn: '<path d="M8 2L14.5 13.5H1.5Z"/><path d="M8 6.3V9.3"/><circle cx="8" cy="11.5" r=".6" fill="currentColor"/>',
  trash: '<path d="M3 4.5H13M6 4.5V2.8H10V4.5M4.5 4.5L5.3 13.5H10.7L11.5 4.5"/>',
  refresh: '<path d="M13 8A5 5 0 1 1 11.5 4.4"/><path d="M11.8 1.8V4.8H8.8"/>',
  search: '<circle cx="7" cy="7" r="4.5"/><path d="M10.4 10.4L14 14"/>',
  download: '<path d="M8 2.5V10.5M4.5 7L8 10.5L11.5 7"/><path d="M2.5 13.5H13.5"/>',
  update: '<circle cx="8" cy="8" r="6"/><path d="M8 11V5M5.4 7.4L8 4.8L10.6 7.4"/>',
  open: '<path d="M9 3H13V7M13 3L7.5 8.5M11 9.5V13H3V5H6.5"/>',
  shield: '<path d="M8 1.8L13.5 4V8C13.5 11 11.2 13.3 8 14.3C4.8 13.3 2.5 11 2.5 8V4Z"/>',
  shieldCheck: '<path d="M8 1.8L13.5 4V8C13.5 11 11.2 13.3 8 14.3C4.8 13.3 2.5 11 2.5 8V4Z"/><path d="M5.5 8.2L7.3 10L10.6 6.4"/>',
  pin: '<path d="M6 2H10L9.5 6.5L12 9H4L6.5 6.5Z"/><path d="M8 9V14"/>',
  clock: '<circle cx="8" cy="8" r="6"/><path d="M8 4.8V8L10.2 9.6"/>',
  key: '<circle cx="5" cy="10.5" r="3"/><path d="M7.2 8.4L13 2.6M11 4.6L12.8 6.4M9.6 6L11 7.4"/>',
  info: '<circle cx="8" cy="8" r="6"/><path d="M8 7.2V11"/><circle cx="8" cy="5" r=".6" fill="currentColor"/>',
  filter: '<path d="M2 3.5H14M4.5 8H11.5M7 12.5H9"/>',
  sort: '<path d="M4.5 2.5V13.5M2 11L4.5 13.5L7 11M11.5 13.5V2.5M9 5L11.5 2.5L14 5"/>',
  sync: '<path d="M2.8 6.5A5.3 5.3 0 0 1 12.6 5M13.2 9.5A5.3 5.3 0 0 1 3.4 11"/><path d="M12.8 2.2V5.2H9.8M3.2 13.8V10.8H6.2"/>',
  gear: '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.8V3.6M8 12.4V14.2M1.8 8H3.6M12.4 8H14.2M3.6 3.6L4.9 4.9M11.1 11.1L12.4 12.4M3.6 12.4L4.9 11.1M11.1 4.9L12.4 3.6"/>',
  globe: '<circle cx="8" cy="8" r="6"/><path d="M2 8H14M8 2C10 4 10 12 8 14M8 2C6 4 6 12 8 14"/>',
  lock: '<rect x="3" y="7" width="10" height="7" rx="1.6"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0V7"/>',
  folder: '<path d="M2 4.5A1.5 1.5 0 0 1 3.5 3H6.5L8 4.5H12.5A1.5 1.5 0 0 1 14 6V12A1.5 1.5 0 0 1 12.5 13.5H3.5A1.5 1.5 0 0 1 2 12Z"/>',
  ban: '<circle cx="8" cy="8" r="6"/><path d="M3.8 12.2L12.2 3.8"/>',
  copy: '<rect x="5" y="5" width="9" height="9" rx="1.6"/><path d="M3 11V3.6A1.6 1.6 0 0 1 4.6 2H11"/>',
  window: '<rect x="2" y="3" width="12" height="10" rx="2"/><path d="M2 6H14"/>',
  power: '<path d="M8 2V8"/><path d="M4.6 4.2A5 5 0 1 0 11.4 4.2"/>',
  audit: '<rect x="3" y="2" width="10" height="12" rx="1.6"/><path d="M5.5 5.5H10.5M5.5 8H10.5M5.5 10.5H8"/>',
  log: '<path d="M3 2.5H10L13 5.5V13.5H3Z"/><path d="M10 2.5V5.5H13M5.5 8H10.5M5.5 10.5H10.5"/>',
  compass: '<circle cx="8" cy="8" r="6"/><path d="M10.5 5.5L9 9L5.5 10.5L7 7Z"/>',
  play: '<path d="M5 3.5L12 8L5 12.5Z" fill="currentColor"/>',
  save: '<path d="M3 2.5H11L13.5 5V13.5H2.5V3Z"/><path d="M5 2.5V6H10V2.5M5 13.5V9.5H11V13.5"/>',
  star: '<path d="M8 1.5L9.9 5.6L14.3 6.1L11 9.1L11.9 13.5L8 11.3L4.1 13.5L5 9.1L1.7 6.1L6.1 5.6Z" fill="currentColor"/>',
  // app glyphs
  send: '<path d="M2.5 7.5L13.5 2.5L9 13.5L7.5 9Z"/><path d="M7.5 9L13.5 2.5"/>',
  note: '<rect x="3" y="2" width="10" height="12" rx="1.6"/><path d="M5.5 5.5H10.5M5.5 8H10.5M5.5 10.5H8.5"/>',
  vault: '<circle cx="6" cy="10" r="3"/><path d="M8.2 7.8L13 3M11 5L12.8 6.8"/>',
  record: '<circle cx="8" cy="8" r="6"/><circle cx="8" cy="8" r="2.4" fill="currentColor"/>',
  brush: '<path d="M13.5 2.5L7.5 8.5"/><path d="M7.5 8.5C5.5 8 3.5 9.5 4 11.5C4.2 12.5 3.2 13.3 2.5 13.5C5 14.2 8.5 13.5 7.5 8.5Z"/>',
  syncA: '<circle cx="8" cy="8" r="5.5"/><circle cx="8" cy="2.5" r="1.4" fill="currentColor"/><circle cx="3.2" cy="10.8" r="1.4" fill="currentColor"/><circle cx="12.8" cy="10.8" r="1.4" fill="currentColor"/>',
  wave: '<path d="M2 8H3.5M5 5V11M7.5 3V13M10 5.5V10.5M12.5 7V9M14 8H14"/>',
  chat: '<path d="M8 2.5C11.3 2.5 14 4.7 14 7.5S11.3 12.5 8 12.5C7.2 12.5 6.4 12.4 5.7 12.1L2.5 13.5L3.3 10.6C2.5 9.7 2 8.7 2 7.5C2 4.7 4.7 2.5 8 2.5Z"/>',
  camera: '<path d="M2 5.5A1.5 1.5 0 0 1 3.5 4H5L6.2 2.5H9.8L11 4H12.5A1.5 1.5 0 0 1 14 5.5V12A1.5 1.5 0 0 1 12.5 13.5H3.5A1.5 1.5 0 0 1 2 12Z"/><circle cx="8" cy="8.5" r="2.6"/>',
  code: '<path d="M5.5 4.5L2 8L5.5 11.5M10.5 4.5L14 8L10.5 11.5M9 3L7 13"/>',
  vector: '<path d="M3 13L8 3L13 13"/><path d="M5.2 9H10.8"/><circle cx="8" cy="3" r="1.3" fill="currentColor"/>',
  usb: '<path d="M8 1.5V12"/><path d="M5 4L8 1.5L11 4"/><circle cx="8" cy="13" r="1.5"/><path d="M8 9L4.5 7V5.5M8 7.5L11.5 6V4.5"/>',
  vpn: '<path d="M8 1.8L13.5 4V8C13.5 11 11.2 13.3 8 14.3C4.8 13.3 2.5 11 2.5 8V4Z"/><path d="M6 6.5L8 10L10 6.5"/>',
  film: '<rect x="2" y="3" width="12" height="10" rx="1.6"/><path d="M5 3V13M11 3V13M2 6.3H5M2 9.7H5M11 6.3H14M11 9.7H14"/>',
  zettel: '<path d="M4 3H12L4 13H12"/>',
  box: '<rect x="2.5" y="5" width="11" height="8.5" rx="1.4"/><path d="M2 5L3.8 2.5H12.2L14 5M6.5 8H9.5"/>',
};
function icon(name, x, y, size, color, sw = 1.6) {
  const k = size / 16;
  return `<g transform="translate(${f1(x)} ${f1(y)}) scale(${k})" fill="none" stroke="${color}" color="${color}" stroke-width="${sw / k}"` +
    ` stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</g>`;
}
function starPath(cx, cy, r) {
  let d = '';
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.45 : r;
    d += (i ? 'L' : 'M') + f1(cx + rr * Math.cos(a)) + ',' + f1(cy + rr * Math.sin(a));
  }
  return d + 'Z';
}
// stars for a 0–5 value with half steps; returns width
function stars(x, cy, v, r, T, o = {}) {
  let s = '';
  const gap = r * 2.25, on = o.color || T.star, off = o.off || (T.dark ? '#3a3f4d' : '#dfe2ea');
  for (let i = 0; i < 5; i++) {
    const cx = x + r + i * gap, fillv = Math.max(0, Math.min(1, v - i));
    s += `<path d="${starPath(cx, cy, r)}" fill="${off}"/>`;
    if (fillv > 0) {
      const c = clip(cx - r, cy - r, r * 2 * fillv, r * 2, 0);
      s += `<path d="${starPath(cx, cy, r)}" fill="${on}" clip-path="url(#${c})"/>`;
    }
  }
  return { s, w: gap * 4 + r * 2 };
}

// ---------------------------------------------------------------- widgets
function pill(x, y, label, o) {
  const { bg, fg, dot, ic, size = 11.5, h = 22, mono = false, bold = true, stroke, anchor = 'start' } = o;
  const w = tw(label, size, { mono, bold }) + (dot || ic ? 28 : 18);
  const x0 = anchor === 'end' ? x - w : x;
  let s = rect(x0, y, w, h, h / 2, bg, stroke ? { stroke } : {});
  if (dot) s += `<circle cx="${x0 + 12}" cy="${y + h / 2}" r="3.2" fill="${dot}"/>`;
  if (ic) s += icon(ic, x0 + 6.5, y + h / 2 - 6, 12, fg, 1.7);
  s += text(x0 + (dot || ic ? 21 : 9), y + h / 2 + size * 0.36, label, { size, weight: bold ? 700 : 400, fill: fg, mono });
  return { s, w };
}
function button(x, y, label, T, o = {}) {
  const { primary, ic, h = 34, disabled, anchor = 'start', danger, soft, size = 13 } = o;
  const w = (label ? tw(label, size, { bold: true }) + 28 : 0) + (ic ? (label ? 20 : h) : 0);
  const x0 = anchor === 'end' ? x - w : anchor === 'middle' ? x - w / 2 : x;
  const fill = disabled ? T.track : primary ? (danger ? T.err : T.accent) : soft ? T.accentSoft : T.surface;
  const fg = disabled ? T.faint : primary ? '#ffffff' : danger ? T.err : soft ? T.accent : T.text;
  let s = rect(x0, y, w, h, 10, fill, primary || disabled || soft ? {} : { stroke: T.border });
  let tx = x0 + 14;
  if (ic) { s += icon(ic, label ? x0 + 12 : x0 + (w - 16) / 2, y + (h - 16) / 2, 16, fg); tx += 20; }
  if (label) s += text(tx, y + h / 2 + size * 0.36, label, { size, weight: 700, fill: fg });
  return { s, w };
}
function iconBtn(cx, cy, name, T, o = {}) {
  const { r = 14, active, color, bg } = o;
  let s = active
    ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${T.accentSoft}" stroke="${T.accent}" stroke-width="1.5"/>`
    : `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${bg || T.track}"/>`;
  const is = o.size || (name === 'x' ? 12 : 14);
  return s + icon(name, cx - is / 2, cy - is / 2, is, active ? T.accent : color || T.muted, name === 'x' ? 1.8 : 1.6);
}
function sqBtn(x, y, name, T, o = {}) {   // small square icon-only button (rows)
  const { s: sz = 32, primary, danger, hover } = o;
  const fill = primary ? T.accent : hover ? T.hover : T.surface;
  const fg = primary ? '#ffffff' : danger ? T.err : T.muted;
  return rect(x, y, sz, sz, 9, fill, primary ? {} : { stroke: T.border }) + icon(name, x + (sz - 16) / 2, y + (sz - 16) / 2, 16, fg);
}
function checkbox(x, y, on, T, o = {}) {
  let s = rect(x, y, 18, 18, 5, on ? (o.disabled ? T.faint : T.accent) : 'none', on ? {} : { stroke: T.borderStrong, sw: 1.6 });
  if (on) s += icon('check', x + 2.5, y + 2.5, 13, '#ffffff', 2.2);
  return s;
}
function toggle(x, y, on, T) {
  return rect(x, y, 34, 20, 10, on ? T.accent : T.track, on ? {} : { stroke: T.borderStrong }) +
    `<circle cx="${on ? x + 24 : x + 10}" cy="${y + 10}" r="7" fill="#ffffff"/>`;
}
function input(x, y, w, T, o = {}) {
  const { h = 40, focus, err, value, placeholder, ic, mono, size = 13.5 } = o;
  let s = rect(x, y, w, h, 11, T.input, { stroke: err ? T.err : focus ? T.accent : T.border, sw: err || focus ? 2 : 1 });
  let tx = x + 14;
  if (ic) { s += icon(ic, x + 12, y + h / 2 - 8, 16, T.muted); tx += 24; }
  if (value) s += text(tx, y + h / 2 + 4.8, value, { size, fill: T.text, mono });
  else if (placeholder) s += text(tx, y + h / 2 + 4.8, placeholder, { size, fill: T.faint });
  if (focus && value) { const cx = tx + tw(value, size, { mono }) + 2; s += `<path d="M${f1(cx)},${y + 11}V${y + h - 11}" stroke="${T.accent}" stroke-width="1.5"/>`; }
  return s;
}
function chip(x, y, label, T, o = {}) {
  const warnTag = WARN_TAGS.includes(label);
  const bg = o.on ? T.accentSoft : warnTag ? T.warnSoft : T.track;
  const fg = o.on ? T.accent : warnTag ? T.warn : T.muted;
  return pill(x, y, label, { bg, fg, size: o.size || 11, h: o.h || 20, bold: true, stroke: o.on ? T.accent : null, ic: o.ic });
}
function tooltip(x, y, label, T, o = {}) {
  const w = tw(label, 12, { bold: true }) + 20, x0 = o.right !== undefined ? o.right - w : Math.min(x - w / 2, W - w - 8);
  const arrow = o.below ? `<path d="M${x - 5},${y} L${x},${y - 5} L${x + 5},${y}Z" fill="${T.tipBg}"/>`
    : `<path d="M${x - 5},${y + 26} L${x},${y + 31} L${x + 5},${y + 26}Z" fill="${T.tipBg}"/>`;
  return rect(x0, y, w, 26, 7, T.tipBg) + arrow +
    text(x0 + w / 2, y + 17.5, label, { size: 12, weight: 700, fill: T.tipFg, anchor: 'middle' });
}
function tipBtn(x, y, ic, T, o = {}) {      // a 32 px icon-only button; o: accent, danger, disabled, size
  const sz = o.size || 32, fill = o.disabled ? T.track : o.accent ? T.accent : T.surface;
  const fg = o.disabled ? T.faint : o.accent ? '#ffffff' : o.danger ? T.err : T.muted;
  return rect(x, y, sz, sz, 9, fill, o.accent || o.disabled ? {} : { stroke: T.border }) + icon(ic, x + (sz - 16) / 2, y + (sz - 16) / 2, 16, fg);
}
function tipLeft(xr, cy, label, T) {          // a tooltip ending at xr, centred on cy
  const w = tw(label, 12, { bold: true }) + 20;
  return rect(xr - w, cy - 13, w, 26, 7, T.tipBg) + text(xr - w / 2, cy + 4.5, label, { size: 12, weight: 700, fill: T.tipFg, anchor: 'middle' });
}
function cursor(x, y) {
  return `<path d="M${x},${y} l0,17 l4.5,-4 l3,7 l2.6,-1.2 l-3,-6.8 l6,0 Z" fill="#ffffff" stroke="#111" stroke-width="1.1" stroke-linejoin="round"/>`;
}
const WARN_TAGS = ['spyware', 'malware', 'ads', 'tracking', 'knownvuln'];
// Windows screens (W…): Minimize and Maximize in the header (req 15.13), and an app that needs the
// Visual C++ run-time (req 15.18). Set while one is drawn.
let WIN = false, MSVCRT = null;
const onWindows = (draw, msvcrt = null) => T => { WIN = true; MSVCRT = msvcrt; try { return draw(T); } finally { WIN = false; MSVCRT = null; } };

// ---------------------------------------------------------------- data
const APPS = {
  appkata: { name: 'AppKata', ver: '0.2.0', date: 'Sep 24', host: 'github.com', repo: 'MojoKata/AppKata', forge: 'GitHub', logo: true,
    glyph: 'send', grad: ['#818cf8', '#4338ca'], trust: 5.0, rating: 4.0, n: 1, tags: ['foss', 'signed'],
    summary: 'AppKata is a FOSS app store built on git. Apps come from your Sources and from Trusts.' },
  localsend: { name: 'LocalSend', ver: '1.17.0', date: 'Sep 24', host: 'github.com', repo: 'localsend/localsend', forge: 'GitHub',
    glyph: 'send', grad: ['#22d3ee', '#2563eb'], trust: 4.7, rating: 4.5, n: 3, tags: ['foss', 'donation', 'offline'],
    summary: 'An open-source app to securely share files and messages with nearby devices over your local network, without an internet connection.' },
  joplin: { name: 'Joplin', ver: '3.4.12', date: 'Sep 19', host: 'github.com', repo: 'laurent22/joplin', forge: 'GitHub',
    glyph: 'note', grad: ['#60a5fa', '#1e40af'], trust: 4.3, rating: 4.4, n: 2, tags: ['foss', 'donation'],
    summary: 'A note-taking and to-do application that can sync end-to-end encrypted notes through Nextcloud, Dropbox, WebDAV or Joplin Cloud.' },
  keepassxc: { name: 'KeePassXC', ver: '2.7.10', date: 'Mar 3', host: 'github.com', repo: 'keepassxreboot/keepassxc', forge: 'GitHub',
    glyph: 'vault', grad: ['#4ade80', '#15803d'], trust: 5.0, rating: 4.6, n: 3, tags: ['foss', 'offline', 'signed', 'reproducible', 'portable'],
    summary: 'A modern, secure, and open-source password manager that stores and manages your most sensitive information in an encrypted local database.' },
  obs: { name: 'OBS Studio', ver: '32.0.1', date: 'Sep 30', host: 'github.com', repo: 'obsproject/obs-studio', forge: 'GitHub',
    glyph: 'record', grad: ['#a78bfa', '#4c1d95'], trust: 4.6, rating: 4.8, n: 2, tags: ['foss', 'donation'],
    summary: 'Free and open source software for video recording and live streaming, with real-time capture, scene composition and audio mixing.' },
  krita: { name: 'Krita', ver: '5.2.11', date: 'Aug 7', host: 'invent.kde.org', repo: 'graphics/krita', forge: 'GitLab',
    glyph: 'brush', grad: ['#f472b6', '#9d174d'], trust: 4.8, rating: 4.7, n: 2, tags: ['foss', 'donation'],
    summary: 'A professional free and open source painting program, made by artists who want to see affordable art tools for everyone.' },
  syncthing: { name: 'Syncthing', ver: '2.0.9', date: 'Sep 16', host: 'github.com', repo: 'syncthing/syncthing', forge: 'GitHub',
    glyph: 'syncA', grad: ['#38bdf8', '#0e7490'], trust: 4.9, rating: 4.6, n: 3, tags: ['foss', 'donation', 'reproducible', 'offline'],
    summary: 'Continuous file synchronization between two or more computers, private and secure, with no central server.' },
  tenacity: { name: 'Tenacity', ver: '1.3.4', date: 'Jan 12', host: 'codeberg.org', repo: 'tenacityteam/tenacity', forge: 'Forgejo',
    glyph: 'wave', grad: ['#fb923c', '#c2410c'], trust: 4.0, rating: 3.9, n: 1, tags: ['foss'],
    summary: 'An easy-to-use, cross-platform multi-track audio editor and recorder for Windows, macOS, Linux and other operating systems.' },
  signal: { name: 'Signal Desktop', ver: '7.72.1', date: 'Sep 26', host: 'github.com', repo: 'signalapp/Signal-Desktop', forge: 'GitHub',
    glyph: 'chat', grad: ['#818cf8', '#3730a3'], trust: 4.4, rating: 4.2, n: 2, tags: ['foss', 'saas', 'donation', 'nonfreenet'],
    summary: 'Private messaging from your desktop. Signal Desktop links with Signal on Android or iOS and keeps your conversations end-to-end encrypted.' },
  flameshot: { name: 'Flameshot', ver: '13.1.0', date: 'Aug 28', host: 'github.com', repo: 'flameshot-org/flameshot', forge: 'GitHub',
    glyph: 'camera', grad: ['#f87171', '#b91c1c'], trust: null, rating: null, n: 0, tags: [],
    summary: 'Powerful yet simple to use screenshot software, with in-app annotation, customizable appearance and an upload option.' },
  vscodium: { name: 'VSCodium', ver: '1.104.2', date: 'Sep 29', host: 'github.com', repo: 'VSCodium/vscodium', forge: 'GitHub',
    glyph: 'code', grad: ['#3b82f6', '#0f172a'], trust: 4.2, rating: 4.3, n: 2, tags: ['foss'],
    summary: 'Free/Libre Open Source Software binaries of VS Code, built without Microsoft branding, telemetry or licensing.' },
  inkscape: { name: 'Inkscape', ver: '1.4.2', date: 'Sep 28', host: 'gitlab.com', repo: 'inkscape/inkscape', forge: 'GitLab',
    glyph: 'vector', grad: ['#94a3b8', '#1e293b'], trust: 4.8, rating: 4.4, n: 2, tags: ['foss', 'donation'],
    summary: 'A free and open source vector graphics editor for GNU/Linux, Windows and macOS, using SVG as its native format.' },
  ventoy: { name: 'Ventoy', ver: '1.1.07', date: 'Sep 2', host: 'github.com', repo: 'ventoy/Ventoy', forge: 'GitHub',
    glyph: 'usb', grad: ['#facc15', '#a16207'], trust: 3.5, rating: 4.5, n: 2, tags: ['foss', 'upstreamnonfree'],
    summary: 'A tool to create bootable USB drives: copy ISO, WIM, IMG, VHD and EFI files to the drive and boot them directly.' },
  zettlr: { name: 'Zettlr', ver: '3.6.0', date: 'Sep 22', host: 'github.com', repo: 'Zettlr/Zettlr', forge: 'GitHub',
    glyph: 'zettel', grad: ['#2dd4bf', '#115e59'], trust: 4.1, rating: 4.0, n: 1, tags: ['foss'],
    summary: 'A Markdown editor for the 21st century, for researchers and writers, with citations, Zettelkasten links and export to many formats.' },
  kdenlive: { name: 'Kdenlive', ver: '25.08.1', date: 'Sep 4', host: 'invent.kde.org', repo: 'multimedia/kdenlive', forge: 'GitLab',
    glyph: 'film', grad: ['#c084fc', '#581c87'], trust: null, rating: null, n: 0, tags: [],
    summary: 'A free and open source video editor based on the MLT framework, with multi-track editing, effects and transitions.' },
  turbovpn: { name: 'TurboShield VPN', ver: '4.2.0', date: 'Sep 30', host: 'github.com', repo: 'turboshield-free/vpn-desktop', forge: 'GitHub',
    glyph: 'vpn', grad: ['#f43f5e', '#7f1d1d'], trust: 0, rating: 1.5, n: 2, tags: ['spyware', 'ads', 'saas'], veto: true,
    summary: 'Free unlimited VPN for desktop. One-click connect to 90+ countries with turbo speed.' },
  xz: { name: 'XZ Utils', ver: '5.6.2', date: 'May 29', host: 'github.com', repo: 'tukaani-project/xz', forge: 'GitHub',
    glyph: 'box', grad: ['#a3a3a3', '#404040'], trust: 4.5, rating: 4.0, n: 2, tags: ['foss', 'offline'],
    summary: 'XZ Utils provide a general-purpose data-compression library plus command-line tools, using the LZMA2 algorithm.' },
  freevpnx: { name: 'Proton VPN', ver: '4.12.0', date: 'Sep 23', host: 'github.com', repo: 'ProtonVPN/proton-vpn-gtk-app', forge: 'GitHub',
    glyph: 'shield', grad: ['#8b5cf6', '#312e81'], trust: 4.2, rating: 4.1, n: 2, tags: ['foss', 'freemium', 'saas'],
    summary: 'The official Linux app for Proton VPN, with a free plan, Secure Core servers and a kill switch.' },
};
const CATALOG = ['localsend', 'keepassxc', 'syncthing', 'krita', 'obs', 'inkscape', 'joplin', 'signal', 'vscodium', 'zettlr', 'tenacity', 'ventoy', 'flameshot', 'kdenlive'];
const STATE = { appkata: 'update', localsend: 'update', signal: 'update', zettlr: 'update', keepassxc: 'installed', syncthing: 'selfupdating', inkscape: 'held', vscodium: 'installed', ventoy: 'pinned', flameshot: 'installed', obs: 'foreign' };
const INSTALLED = {
  appkata: { from: '0.1.0', to: '0.2.0', type: 'AppImage', self: true },
  localsend: { from: '1.16.1', to: '1.17.0', type: 'AppImage' },
  signal: { from: '7.70.0', to: '7.72.1', type: '.deb' },
  zettlr: { from: '3.5.1', to: '3.6.0', type: 'AppImage' },
  flameshot: { from: '13.1.0', type: 'Flatpak' },
  inkscape: { from: '1.4.1', to: '1.4.2', type: 'AppImage', held: 'Held · 5 days left' },
  keepassxc: { from: '2.7.10', type: 'AppImage' },
  syncthing: { from: '2.0.9', type: 'tar.gz', auto: true, by: 'Kenji’s app reviews' },     // updates itself (req 4.10)
  ventoy: { from: '1.0.99', to: '1.1.07', type: 'tar.gz', pinned: true },
  vscodium: { from: '1.104.2', type: '.rpm' },
};

const AVATARS = {
  mara: { name: 'Mara Lindqvist', init: 'ML', grad: ['#f59e0b', '#db2777'], kind: 'GPG', id: 'mara@lindqvist.se', fp: '7C1E 94A2 0B3D 5F18 6E04' },
  jo: { name: 'Jonas Okafor', init: 'JO', grad: ['#34d399', '#0e7490'], kind: 'SSH', id: 'jonas@desk.coop', fp: 'SHA256:q8Kf…v2Lw' },
  rp: { name: 'Rita Prado', init: 'RP', grad: ['#60a5fa', '#7c3aed'], kind: 'GPG', id: 'rita@desk.coop', fp: '3A90 11C7 E2F4 0D6B 9A51' },
  tk: { name: 'Tomasz Kral', init: 'TK', grad: ['#f472b6', '#9333ea'], kind: 'SSH', id: 'tk@desk.coop', fp: 'SHA256:Hn3x…0QzA' },
  ab: { name: 'Ade Bello', init: 'AB', grad: ['#fb923c', '#b91c1c'], kind: 'GPG', id: 'ade@desk.coop', fp: '0F2D 77B1 AC09 4E3E 5C2B' },
  ln: { name: 'Lea Novak', init: 'LN', grad: ['#a3e635', '#15803d'], kind: 'SSH', id: 'lea@desk.coop', fp: 'SHA256:7tRm…KcQ1' },
  sv: { name: 'Sam Vega', init: 'SV', grad: ['#38bdf8', '#1d4ed8'], kind: 'SSH', id: 'sam@desk.coop', fp: 'SHA256:ZpW2…a9Ue' },
  kj: { name: 'Kenji Mori', init: 'KM', grad: ['#c084fc', '#4338ca'], kind: 'Nostr', id: 'kenji@mori.dev', fp: 'npub1k3nj…8f2q' },
  ay: { name: 'Aya Mori', init: 'AM', grad: ['#fda4af', '#be123c'], kind: 'Nostr', id: 'aya@mori.dev', fp: 'npub1ay4m…r0dz' },
  me: { name: 'You', init: 'DG', grad: ['#8089ff', '#4f46e5'], kind: 'SSH', id: 'your signing key', fp: 'SHA256:dG7a…Xk2e' },
};
const TRUSTS = [
  { name: 'Your reviews', short: 'You', url: '~/src/reviews/AppKata.md', apps: 6, synced: 'local', auth: ['me'], own: true, score: 5 },
  { name: 'mara-dev / foss-picks', short: 'mara-dev', url: 'github.com/mara-dev/foss-picks', apps: 38, synced: '2 h ago', auth: ['mara'], score: 4 },
  { name: 'desk-collective / reviews', short: 'desk-collective', url: 'codeberg.org/desk-collective/reviews/docs/AppKata.md', apps: 112, synced: '2 h ago',
    auth: ['jo', 'rp', 'tk', 'ab', 'ln', 'sv'], warn: 'New signer', score: 3 },
  { name: 'Kenji’s app reviews', short: 'Kenji', url: 'nostr://npub1k3nj…8f2q/app-reviews', apps: 21, synced: '5 h ago', auth: ['kj', 'ay'], nostr: true, score: 5 },
];
// Trusts are listed by Score, then name; your own file first (req 7.6.7)
const byScore = (a, b) => (TRUSTS[b].own ? 1 : 0) - (TRUSTS[a].own ? 1 : 0) || TRUSTS[b].score - TRUSTS[a].score || TRUSTS[a].name.localeCompare(TRUSTS[b].name);
const TRUST_ORDER = TRUSTS.map((_, i) => i).sort(byScore);
// Where each app comes from (req 2.9): its own Source, and/or the Trusts that list it
const ORIGIN = {
  appkata: { src: true, tr: [3] },
  localsend: { src: true, tr: [1, 2, 3] }, keepassxc: { src: true, tr: [1, 2, 3] }, syncthing: { src: true, tr: [1, 2, 3] },
  krita: { src: false, tr: [1, 2] }, obs: { src: true, tr: [1, 2] }, inkscape: { src: true, tr: [1, 2] },
  joplin: { src: true, tr: [1, 2] }, signal: { src: true, tr: [1, 2] }, vscodium: { src: false, tr: [1, 2] },
  zettlr: { src: false, tr: [1] }, tenacity: { src: false, tr: [2] }, ventoy: { src: true, tr: [1, 2] },
  flameshot: { src: true, tr: [] }, kdenlive: { src: true, tr: [] }, turbovpn: { src: false, tr: [2, 1] },
  freevpnx: { src: false, tr: [1, 2] }, xz: { src: true, tr: [1, 2] },
};
function originText(key) {
  const o = ORIGIN[key], n = o.tr.length;
  if (o.src) return n ? `Source · ${n} trust${n > 1 ? 's' : ''}` : 'Source';
  return n === 1 ? TRUSTS[o.tr[0]].name : `${n} trusts`;
}
// first lines of each Trust's review section (req 5.7.6)
const REVIEW_TEXT = {
  localsend: 'No account, no cloud: transfers stay on the LAN and are TLS-encrypted. Releases are built in CI from tagged commits, with checksums.',
  krita: 'The best FOSS painting app, full stop. KDE signs the release builds; donations go to the Krita Foundation.',
  turbovpn: 'Phones home with device IDs and browsing stats even when disconnected. Injects ads. Avoid.',
};

// ---------------------------------------------------------------- art
function appIconArt(x, y, S, a, T) {
  if (a.logo) return logo(x, y, S, T);
  const g = linGrad([[0, a.grad[0]], [1, a.grad[1]]], 1, 1);
  const sheen = linGrad([[0, '#ffffff', 0.28], [0.5, '#ffffff', 0]], 0, 1);
  return rect(x, y, S, S, S * 0.26, `url(#${g})`) + rect(x, y, S, S * 0.6, S * 0.26, `url(#${sheen})`) +
    rect(x + 0.5, y + 0.5, S - 1, S - 1, S * 0.26, 'none', { stroke: '#ffffff', op: 0.14 }) +
    icon(a.glyph, x + S * 0.22, y + S * 0.22, S * 0.56, '#ffffff', Math.max(1.6, S / 22));
}
function heroArt(x, y, w, h, a, T) {
  const c = clip(x, y, w, h, 14);
  const g = linGrad([[0, a.grad[0]], [1, a.grad[1]]], 1, 1);
  const shade = linGrad([[0, '#000000', 0], [1, '#000000', T.dark ? 0.45 : 0.25]], 0, 1);
  let s = `<g clip-path="url(#${c})">` + rect(x, y, w, h, 0, `url(#${g})`);
  s += `<circle cx="${x + w * 0.85}" cy="${y + h * 0.1}" r="${h * 0.9}" fill="#ffffff" opacity="0.10"/>`;
  s += `<circle cx="${x + w * 0.1}" cy="${y + h * 1.1}" r="${h * 0.7}" fill="#000000" opacity="0.12"/>`;
  // a stylized app window "screenshot"
  const wx = x + w * 0.3, wy = y + h * 0.18, ww = w * 0.62, wh = h * 0.95;
  s += rect(wx, wy, ww, wh, 10, T.dark ? '#14161d' : '#ffffff', { op: 0.92 });
  s += rect(wx, wy, ww, 20, 10, T.dark ? '#262a35' : '#eef0f5', { op: 0.95 });
  ['#f87171', '#fbbf24', '#34d399'].forEach((cc, i) => { s += `<circle cx="${wx + 14 + i * 12}" cy="${wy + 10}" r="3.5" fill="${cc}"/>`; });
  s += rect(wx + 12, wy + 32, ww * 0.26, wh - 44, 6, a.grad[0], { op: 0.22 });
  for (let i = 0; i < 5; i++) s += rect(wx + ww * 0.3 + 12, wy + 34 + i * 18, (ww * 0.62) * (i % 2 ? 0.7 : 0.95), 8, 4, T.dark ? '#ffffff' : '#1b1f2b', { op: 0.12 });
  s += rect(wx + ww * 0.3 + 12, wy + 130, ww * 0.3, 26, 7, a.grad[0], { op: 0.85 });
  s += rect(x, y, w, h, 0, `url(#${shade})`) + '</g>';
  return s;
}
function avatar(cx, cy, r, key, T, o = {}) {
  const a = AVATARS[key];
  const g = linGrad([[0, a.grad[0]], [1, a.grad[1]]], 1, 1);
  let s = `<circle cx="${cx}" cy="${cy}" r="${r + (o.ring ? 2 : 0)}" fill="${o.ringColor || T.surface}"/>`;
  s += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#${g})" ${o.dim ? 'opacity="0.35"' : ''}/>`;
  s += text(cx, cy + r * 0.36, r < 14 ? a.init[0] : a.init, { size: r * 0.9, weight: 700, fill: '#ffffff', anchor: 'middle', op: o.dim ? 0.6 : null });
  return s;
}
function avatarStack(x, cy, keys, r, T, o = {}) {
  let s = '';
  const shown = keys.slice(0, 4), step = r * 1.35;
  shown.forEach((k, i) => { s += avatar(x + r + i * step, cy, r, k, T, { ring: true, ringColor: o.bg || T.surface }); });
  let w = r * 2 + (shown.length - 1) * step;
  if (keys.length > 4) {
    const cx = x + r + 4 * step;
    s += `<circle cx="${cx}" cy="${cy}" r="${r + 2}" fill="${o.bg || T.surface}"/><circle cx="${cx}" cy="${cy}" r="${r}" fill="${T.track}"/>`;
    s += text(cx, cy + 4, `+${keys.length - 4}`, { size: 10.5, weight: 700, fill: T.muted, anchor: 'middle' });
    w += step;
  }
  return { s, w };
}
function originMini(x, cy, key, T, o = {}) {   // branch icon for a Source, avatars for Trusts
  const og = ORIGIN[key];
  let s = '', w = 0;
  if (og.src) { s += icon('branch', x, cy - 7, 14, T.muted, 1.6); w += 18; }
  const tr = og.tr.filter(i => i > 0);
  tr.forEach((ti, i) => { s += avatar(x + w + 7 + i * 10, cy, 7, TRUSTS[ti].auth[0], T, { ring: true, ringColor: o.bg || T.surface }); });
  if (tr.length) w += 14 + (tr.length - 1) * 10;
  return { s, w };
}
function trustBadge(x, cy, a, T, o = {}) {        // shield value + rating stars
  if (a.veto) {
    return pill(x, cy - 11, 'Avoid', { bg: T.errSoft, fg: T.err, ic: 'warn', size: 11.5 });
  }
  if (a.trust == null) return pill(x, cy - 11, 'Unreviewed', { bg: T.track, fg: T.muted, size: 11 });
  let s = icon('shieldCheck', x, cy - 8, 16, T.ok, 1.6);
  s += text(x + 20, cy + 4.5, a.trust.toFixed(1), { size: 13, weight: 700, fill: T.text });
  const sx = x + 46;
  const st = stars(sx, cy, a.rating, 5.2, T);
  s += st.s;
  s += text(sx + st.w + 6, cy + 4.5, `(${a.n})`, { size: 11.5, fill: T.faint });
  return { s, w: sx + st.w + 30 - x };
}

// ---------------------------------------------------------------- chrome
function baseDefs(T) {
  return `<filter id="card" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="2" stdDeviation="6" flood-color="#0b0d14" flood-opacity="${T.shadow}"/></filter>` +
    `<filter id="lift" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="8" stdDeviation="14" flood-color="#0b0d14" flood-opacity="${T.shadow * 1.8}"/></filter>` +
    `<filter id="seg" x="-10%" y="-20%" width="120%" height="160%"><feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-color="#0b0d14" flood-opacity="${T.shadow * 1.6}"/></filter>` +
    `<filter id="win" x="-10%" y="-10%" width="120%" height="125%"><feDropShadow dx="0" dy="14" stdDeviation="18" flood-color="#0b0d14" flood-opacity="${T.dark ? 0.6 : 0.18}"/></filter>`;
}
function windowFrame(T, body) {
  const bgG = linGrad([[0, T.backdrop[0]], [1, T.backdrop[1]]], 1, 1);
  const c = nid('clip');
  defs.push(`<clipPath id="${c}"><rect x="0" y="0" width="${W}" height="${H}" rx="14"/></clipPath>`);
  return `<rect width="${W + PAD * 2}" height="${H + PAD * 2}" fill="url(#${bgG})"/>` +
    `<g transform="translate(${PAD} ${PAD})">` +
    `<rect x="0" y="0" width="${W}" height="${H}" rx="14" fill="${T.bg}" filter="url(#win)"/>` +
    `<g clip-path="url(#${c})"><rect width="${W}" height="${H}" fill="${T.bg}"/>${body}</g>` +
    `<rect x="0.5" y="0.5" width="${W - 1}" height="${H - 1}" rx="14" fill="none" stroke="${T.dark ? '#ffffff' : '#000000'}" stroke-opacity="${T.dark ? 0.08 : 0.1}"/>` +
    `</g>`;
}
// AppKata mark: a stacked "kata" diamond of three tiles
function logo(x, y, S, T) {
  const tile = linGrad([[0, T.dark ? '#3a3f4e' : '#343948'], [1, T.dark ? '#262a35' : '#1e222c']], 0, 1);
  const g1 = linGrad([[0, '#a5b4fc'], [1, '#6366f1']], 1, 1), g2 = linGrad([[0, '#67e8f9'], [1, '#0ea5e9']], 1, 1), g3 = linGrad([[0, '#f9a8d4'], [1, '#c026d3']], 1, 1);
  const c = S / 2, u = S * 0.17;
  const dia = (cx, cy, fill) => `<path d="M${f1(cx)},${f1(cy - u)} L${f1(cx + u)},${f1(cy)} L${f1(cx)},${f1(cy + u)} L${f1(cx - u)},${f1(cy)}Z" fill="url(#${fill})"/>`;
  return rect(x, y, S, S, S * 0.28, `url(#${tile})`) + rect(x + 0.5, y + 0.5, S - 1, S - 1, S * 0.28, 'none', { stroke: '#ffffff', op: 0.12 }) +
    dia(x + c, y + c - u * 1.05, g1) + dia(x + c - u * 1.05, y + c, g2) + dia(x + c + u * 1.05, y + c, g3) + dia(x + c, y + c + u * 1.05, g1);
}
function headerBar(T, view, o = {}) {
  let s = rect(0, 0, W, 52, 0, T.surface) + hline(0, W, 52.5, T.border);
  s += logo(18, 12, 28, T);
  s += text(56, 31, 'AppKata', { size: 15, weight: 700, fill: T.text });
  const segs = [['apps', 'apps', 'Apps'], ['catalog', 'grid', 'Catalog'], ['sources', 'branch', 'Sources'], ['audit', 'audit', 'Audit']];
  const sw = 500, sx = W / 2 - sw / 2, segW = (sw - 6) / 4;
  s += rect(sx, 9, sw, 34, 10, T.track);
  segs.forEach(([k, ic, label], i) => {
    const x = sx + 3 + i * segW, on = k === view;
    if (on) s += rect(x, 12, segW, 28, 8, T.segOn, { filter: 'seg' });
    const c = on ? T.text : T.muted, lw = tw(label, 13, { bold: true }) + 22 + (k === 'apps' ? 26 : 0);
    s += icon(ic, x + segW / 2 - lw / 2, 18, 16, c);
    s += text(x + segW / 2 - lw / 2 + 22, 30.5, label, { size: 13, weight: 700, fill: c });
    if (k === 'apps' && (o.badge ?? 4) > 0) {
      const bx = x + segW / 2 - lw / 2 + 22 + tw(label, 13, { bold: true }) + 6 + (o.installing ? 20 : 0);
      if (o.installing) s += icon('sync', bx - 20, 18, 14, T.accent);       // an install in progress (req 4.8.1)
      s += rect(bx, 17, 20, 18, 9, T.accent) + text(bx + 10, 30, String(o.badge ?? 4), { size: 11, weight: 700, fill: '#ffffff', anchor: 'middle' });
    }
  });
  const off = WIN ? 72 : 0;           // Windows: Minimize and Maximize before the close button
  // sync status
  if (o.syncing) {
    const cx = W - 152 - off;
    s += `<circle cx="${cx}" cy="26" r="9" fill="none" stroke="${T.track}" stroke-width="2.5"/>`;
    s += `<path d="M${cx},17 A9,9 0 0 1 ${f1(cx + 8.6)},${f1(23.4)}" fill="none" stroke="${T.accent}" stroke-width="2.5" stroke-linecap="round"/>`;
    s += text(cx - 16, 30.5, 'Syncing 12 / 40', { size: 12.5, weight: 700, fill: T.muted, anchor: 'end' });
  } else {
    s += icon('check', W - 160 - off, 19, 14, T.ok, 1.8);
    s += text(W - 166 - off, 30.5, 'Synced 2 h ago', { size: 12, fill: T.faint, anchor: 'end' });
  }
  s += o.menuOpen ? `<circle cx="${W - 80 - off}" cy="26" r="15" fill="${T.accentSoft}" stroke="${T.accent}" stroke-width="1.5"/>` : '';
  s += icon('dots', W - 88 - off, 18, 16, o.menuOpen ? T.accent : T.muted);
  if (WIN) {
    s += `<circle cx="${W - 104}" cy="26" r="12" fill="${T.track}"/>` + icon('minimize', W - 110, 20, 12, T.muted, 1.8);
    s += `<circle cx="${W - 68}" cy="26" r="12" fill="${T.track}"/>` + icon('maximize', W - 74, 20, 12, T.muted, 1.8);
  }
  s += `<circle cx="${W - 32}" cy="26" r="12" fill="${T.track}"/>` + icon('x', W - 38, 20, 12, T.muted, 1.8);
  return s;
}
function scrim(T) { return `<rect width="${W}" height="${H}" fill="#0b0d14" opacity="${T.dark ? 0.55 : 0.32}"/>`; }
function toast(T, msg, o = {}) {
  const w = tw(msg, 13, { bold: true }) + 70 + (o.action ? tw(o.action, 13, { bold: true }) + 24 : 0);
  const x = (o.cx || W / 2) - w / 2, y = H - 66;
  let s = rect(x, y, w, 42, 12, T.tipBg, { filter: 'lift' });
  s += icon(o.ic || 'check', x + 16, y + 13, 16, o.err ? T.err : T.ok, 1.8);
  s += text(x + 42, y + 26, msg, { size: 13, weight: 700, fill: T.tipFg });
  if (o.action) s += text(x + w - 18, y + 26, o.action, { size: 13, weight: 700, fill: T.dark ? '#4f46e5' : '#a5b4fc', anchor: 'end' });
  return s;
}

// ---------------------------------------------------------------- App Detail panel (req 5.6–5.7)
const PANEL_W = 450;
function detailPanel(T, key, o = {}) {
  const a = APPS[key], st = STATE[key], inst = INSTALLED[key];
  const px = W - PANEL_W;
  let s = rect(px, 53, PANEL_W, H - 53, 0, T.surface, { filter: 'lift' }) + `<path d="M${px + 0.5},53 V${H}" stroke="${T.border}"/>`;
  const x0 = px + 28, pw = PANEL_W - 56;
  s += text(x0, 86, 'APP DETAILS', { size: 11, weight: 700, fill: T.faint, ls: 1.2 });
  s += iconBtn(x0 + pw - 12, 81, 'x', T);
  const pcx = inst ? x0 + pw - 84 : x0 + pw - 48;
  if (inst) s += iconBtn(x0 + pw - 48, 81, 'dots', T);
  s += iconBtn(pcx, 81, 'pencil', T, { active: o.pencilHover });
  if (o.pencilHover) s += tooltip(pcx, 104, 'Write a review', T, { below: true });
  let y = 104;
  if (inst && inst.avoid) {        // a Trust avoids the installed version (req 10.6.5)
    const v = inst.avoid;
    s += rect(x0, y, pw, 64, 11, T.errSoft, { stroke: T.err });
    s += icon('warn', x0 + 14, y + 14, 16, T.err, 1.7);
    s += text(x0 + 40, y + 27.5, `A trusted reviewer says to avoid your version (${inst.from})`, { size: 12.5, weight: 700, fill: T.err });
    s += text(x0 + 40, y + 48, `${v.by} · Avoid from ${v.from} · “${v.note}”`, { size: 11.5, fill: T.text });
    y += 76;
  }
  if (inst && inst.reviewBadge) {   // a new version kept the user's grants; a standing nudge to review (decision 5)
    const q = inst.reviewBadge;
    const body = para(x0 + 40, y + 48, pw - 150, `Updated to ${q.ver}, running with your current sandbox. ${q.by} suggests ${q.what.join(' and ')}.`, T, { size: 11.5, lh: 16, fill: T.text });
    s += rect(x0, y, pw, 40 + body.h + 6, 11, T.accentSoft, { stroke: T.accent });
    s += icon('shield', x0 + 14, y + 14, 16, T.accent, 1.7);
    s += text(x0 + 40, y + 27.5, 'Reviewers suggest a sandbox change', { size: 12.5, weight: 700, fill: T.accent }) + body.s;
    s += button(x0 + pw - 12, y + 16, 'Review…', T, { soft: true, anchor: 'end', h: 30, size: 12 }).s;
    y += 40 + body.h + 18;
  }
  if (inst && inst.setupNeeded) {   // Ubuntu 24.04, AppArmor setup declined: running Off, re-engageable (decision 6)
    const body = para(x0 + 40, y + 48, pw - 150, 'This system blocks the sandbox until a one-time setup (asks for your password once). Until then it runs unsandboxed.', T, { size: 11.5, lh: 16, fill: T.text });
    s += rect(x0, y, pw, 40 + body.h + 6, 11, T.warnSoft, { stroke: T.warn });
    s += icon('warn', x0 + 14, y + 14, 16, T.warn, 1.7);
    s += text(x0 + 40, y + 27.5, 'Not sandboxed — system setup needed', { size: 12.5, weight: 700, fill: T.warn }) + body.s;
    s += button(x0 + pw - 12, y + 16, 'Enable…', T, { primary: true, anchor: 'end', h: 30, size: 12 }).s;
    y += 40 + body.h + 18;
  }
  if (a.veto) {
    s += rect(x0, y, pw, 44, 11, T.errSoft, { stroke: T.err });
    s += icon('warn', x0 + 14, y + 14, 16, T.err, 1.7);
    s += text(x0 + 40, y + 27.5, 'A trusted reviewer says to avoid this app', { size: 13, weight: 700, fill: T.err });
    y += 56;
  }
  s += heroArt(x0, y, pw, 150, a, T);
  s += rect(x0 + 16, y + 112, 68, 68, 20, T.surface);
  s += appIconArt(x0 + 20, y + 116, 60, a, T);
  y += 196;
  s += text(x0, y + 12, a.name, { size: 24, weight: 700, fill: T.text });
  s += text(x0, y + 34, `${a.host}/${a.repo}`, { size: 12, fill: T.muted, mono: true });
  // From: origins (req 5.7.3)
  const og = ORIGIN[key];
  s += text(x0, y + 64, 'From', { size: 12, weight: 700, fill: T.faint });
  let fx = x0 + 44;
  if (og.src) { const p = pill(fx, y + 50, 'Source', { bg: T.track, fg: T.text, ic: 'branch', size: 11.5 }); s += p.s; fx += p.w + 6; }
  og.tr.filter(i => i > 0).forEach(ti => {
    const t = TRUSTS[ti], w = tw(t.short, 11.5, { bold: true }) + 44;
    if (fx + w > x0 + pw) return;
    s += rect(fx, y + 50, w, 22, 11, T.track);
    s += avatar(fx + 11, y + 61, 8, t.auth[0], T, { ringColor: T.track });
    s += text(fx + 24, y + 65.2, t.short, { size: 11.5, weight: 700, fill: T.accent });
    s += icon('chevRight', fx + w - 15, y + 55, 11, T.accent, 1.8);
    fx += w + 6;
  });
  // chips
  let cx = x0; const cy = y + 82;
  const chips = [];
  if (key === 'keepassxc' || key === 'joplin' || key === 'localsend') chips.push(['Verified', T.okSoft, T.ok, 'shieldCheck']);
  else if (!a.veto) chips.push(['Checksum', T.accentSoft, T.accent, 'check']);
  else chips.push(['Unverified', T.warnSoft, T.warn, 'warn']);
  if (st === 'foreign') chips.push(['Installed outside AppKata', T.warnSoft, T.warn, 'info']);
  if (inst && inst.channel) chips.splice(0, chips.length, ...inst.channel);   // e.g. Flathub · verified (req 16.6)
  if (inst && !inst.channel) chips.push([inst.type, T.track, T.muted, null]);
  if (inst && inst.system) chips.push(['Updated by the system', T.track, T.muted, 'sync']);       // req 16.5
  if (inst && inst.auto) chips.push(['Updates itself', T.track, T.muted, 'sync']);
  if (inst && inst.sandbox && inst.sandbox.level !== 'Off') chips.push(['Sandboxed', T.okSoft, T.ok, 'shieldCheck']);
  if (inst && inst.setupNeeded) chips.push(['Not sandboxed', T.warnSoft, T.warn, 'warn']);
  if (inst && MSVCRT === key) chips.push(['MSVCRT', T.warnSoft, T.warn, 'warn']);          // req 15.18.2
  for (const [l, bg, fg, ic] of chips) { const p = pill(cx, cy, l, { bg, fg, ic, size: 11.5 }); s += p.s; cx += p.w + 6; }
  // actions
  y = cy + 40;
  let bx = x0;
  const add = b => { s += b.s; bx += b.w + 8; };
  if (st === 'foreign') {
    add(button(bx, y, 'Installed outside AppKata', T, { ic: 'ban', disabled: true }));
    s += para(x0, y + 54, pw, 'Found in /usr/bin via dpkg (obs-studio 30.0.2). Uninstall the existing copy first to manage it with AppKata.', T, { size: 12, lh: 17 }).s;
    y += 44;
  } else if (!inst) {
    add(button(bx, y, 'Install', T, { ic: 'download', primary: !a.veto, danger: a.veto }));
  } else if (inst.self) {     // AppKata itself (req 2.11)
    if (inst.restart) add(button(bx, y, 'Restart AppKata', T, { ic: 'sync', primary: true }));
    else if (inst.to) add(button(bx, y, 'Update', T, { ic: 'update', primary: true }));
    s += para(x0, y + 54, pw, inst.restart ? 'AppKata 0.2.0 is installed. Restart to finish updating; you’re running 0.1.0.'
      : 'AppKata updates itself like any portable app and keeps older versions for a quick rollback.', T, { size: 12, lh: 17 }).s;
    y += 30;
  } else if (o.busy && BUSY[key]) {        // installing: phase in the button, Cancel, bar, size and speed (req 4.8.1)
    add(button(bx, y, BUSY[key].phase, T, { ic: 'update', disabled: true }));
    add(button(bx, y, 'Cancel', T, { ic: 'x' }));
    s += rect(x0, y + 46, pw, 5, 2.5, T.track) + rect(x0, y + 46, pw * BUSY[key].p, 5, 2.5, T.accent);
    s += text(x0, y + 70, BUSY[key].detail || '', { size: 12, fill: T.muted });
    y += 36;
  } else {
    if (inst.avoid) add(button(bx, y, `Update to ${inst.to}`, T, { ic: 'update', primary: true }));
    else if (inst.to && !inst.held && !inst.pinned && !inst.system) add(button(bx, y, 'Update', T, { ic: 'update', primary: true }));
    add(button(bx, y, 'Uninstall', T, { ic: 'trash', danger: true }));
    add(button(bx, y, 'Open', T, { ic: 'open' }));
    if (inst.system) {
      s += para(x0, y + 54, pw, `${inst.system} updates this Flatpak automatically. AppKata shows new releases but leaves updating to it.`, T, { size: 12, lh: 17 }).s;
      y += 44;
    }
    if (inst.auto) {
      s += para(x0, y + 54, pw, `AppKata only tracks its releases and leaves updating to the app. ${inst.by} says it updates itself; change this in Install options.`, T, { size: 12, lh: 17 }).s;
      y += 44;
    }
  }
  y += 52;
  // version boxes
  const boxes = inst
    ? [[inst.from, 'installed'], [inst.to || a.ver, inst.to ? 'latest · ' + a.date : 'latest'], inst.system ? ['System', 'updates it'] : inst.auto ? ['Itself', 'updates it'] : [inst.held ? '5 days' : inst.to ? 'Update' : 'Current', inst.held ? 'until eligible' : inst.to ? 'available' : 'up to date']]
    : [[a.ver, 'latest'], [a.date, 'released'], [st === 'foreign' ? '30.0.2' : '92 MB', st === 'foreign' ? 'found on system' : 'AppImage · x86_64']];
  const bw = (pw - 16) / 3;
  boxes.forEach(([v, l], i) => {
    const bxx = x0 + i * (bw + 8);
    s += rect(bxx, y, bw, 62, 12, T.input);
    const accentV = i === 2 && inst && inst.to && !inst.held;
    s += text(bxx + 14, y + 28, v, { size: 17, weight: 700, fill: accentV ? T.accent : T.text });
    s += text(bxx + 14, y + 48, l, { size: 11.5, fill: T.muted });
  });
  y += 84;
  if (inst && inst.perms) {        // Flatpak permissions, and what an update added (req 16.6)
    s += text(x0, y, 'Permissions', { size: 14, weight: 700, fill: T.text });
    let qx = x0, qy = y + 14;
    inst.perms.forEach(([l, added]) => {
      const p = pill(qx, qy, l, { bg: added ? T.warnSoft : T.track, fg: added ? T.warn : T.muted, ic: added ? 'warn' : null, size: 11.5 });
      s += p.s; qx += p.w + 6;
    });
    y += 66;
  }
  if (inst && inst.sandbox) {      // what the sandbox lets it use (app-sandboxing.md)
    const sb = inst.sandbox;
    s += text(x0, y, 'Sandbox', { size: 14, weight: 700, fill: T.text });
    s += text(x0 + pw, y, 'Change…', { size: 12.5, weight: 700, fill: T.accent, anchor: 'end' });
    let qx = x0, qy = y + 14;
    const lv = pill(qx, qy, sb.level, { bg: T.okSoft, fg: T.ok, ic: 'shieldCheck', size: 11.5 });
    s += lv.s; qx += lv.w + 6;
    sb.access.forEach(([l, ic, warn]) => {
      if (qx + tw(l, 11.5, { bold: true }) + 28 > x0 + pw) { qx = x0; qy += 28; y += 28; }     // wrap to a new row
      const p = pill(qx, qy, l, { bg: warn ? T.warnSoft : T.track, fg: warn ? T.warn : T.muted, ic, size: 11.5 }); s += p.s; qx += p.w + 6;
    });
    if (sb.x11) {
      s += icon('info', x0, y + 46, 14, T.faint);
      s += text(x0 + 20, y + 57, 'X11 session: it can still see your screen and what you type in other windows.', { size: 11.5, fill: T.faint });
      y += 22;
    }
    y += 66;
  }
  // Trust
  s += text(x0, y, 'Reviews', { size: 14, weight: 700, fill: T.text });
  if (a.trust != null || a.veto) {
    const tb = trustBadge(x0 + pw - 150, y - 5, a, T);
    s += tb.s;
    y += 16;
    const VALS = { 1: [5, 4.5, a.tags.slice(0, 3)], 2: [4, 4, a.tags.slice(0, 2)], 3: [5, 5, ['foss']] };
    if (a.veto) { VALS[2] = [0, 1, ['spyware', 'ads', 'saas']]; VALS[1] = [2, 2, ['tracking', 'saas']]; }
    const revs = og.tr.filter(i => i > 0).sort(byScore).map(ti => [TRUSTS[ti].name, TRUSTS[ti].auth, ...VALS[ti]]);
    let ry = y + 8;
    revs.forEach(([name, keys, tv, rv, tags], i) => {
      const body = i === 0 && REVIEW_TEXT[key] && o.expand !== false ? para(x0 + 14, ry + 66, pw - 28, REVIEW_TEXT[key], T, { size: 12.5, lh: 18, max: 3, fill: T.text }) : null;
      const rh = body ? 50 + body.h + 8 : 50;
      s += rect(x0, ry, pw, rh, 11, T.input);
      if (body) s += hline(x0 + 12, x0 + pw - 12, ry + 48.5, T.border) + body.s;
      const stck = avatarStack(x0 + 10, ry + 25, keys, 11, T, { bg: T.input });
      s += stck.s;
      const nx = x0 + 104;
      s += text(nx, ry + 21, wrap(name, pw - 160 - (nx - x0), 12.5, 1, { bold: true })[0], { size: 12.5, weight: 700, fill: T.accent });
      let tx = nx;
      tags.forEach(t => { const c = chip(tx, ry + 28, t, T, { size: 10, h: 17 }); s += c.s; tx += c.w + 4; });
      const zero = tv === 0;
      s += icon('shield', x0 + pw - 150, ry + 17, 15, zero ? T.err : T.ok, 1.6);
      s += text(x0 + pw - 131, ry + 29, zero ? 'Avoid' : String(tv), { size: 12.5, weight: 700, fill: zero ? T.err : T.text });
      s += stars(x0 + pw - 84, ry + 25, rv, 4.6, T).s;
      s += icon(body ? 'chevUp' : 'chevDown', x0 + pw - 18, ry + 18, 12, T.faint);
      ry += rh + 8;
    });
    y = ry + 10;
  } else {
    s += pill(x0 + pw, y - 16, 'Unreviewed', { bg: T.track, fg: T.muted, anchor: 'end' }).s;
    y += 22;
  }
  // README
  s += text(x0, y + 4, 'About', { size: 14, weight: 700, fill: T.text });
  s += para(x0, y + 28, pw, a.summary, T, { size: 13, lh: 20, fill: T.muted }).s;
  return s;
}

// ---------------------------------------------------------------- Catalog (req 12)
function catalogTile(x, y, w, h, key, T, o = {}) {
  const a = APPS[key], st = STATE[key], k = w / 300;
  let s = '';
  const dim = a.veto;
  s += rect(x, y, w, h, 16, T.surface, { filter: 'card' });
  s += rect(x + 0.5, y + 0.5, w - 1, h - 1, 16, 'none', { stroke: o.selected ? T.accent : a.veto ? T.err : T.border, sw: o.selected ? 2 : 1 });
  // soft glow of the icon colours behind the icon
  const glow = linGrad([[0, a.grad[0], T.dark ? 0.16 : 0.12], [1, a.grad[1], 0]], 1, 1);
  s += rect(x + 1, y + 1, w - 2, 88 * k, 15, `url(#${glow})`);
  const g = dim ? `<g opacity="0.55">` : '<g>';
  s += g + appIconArt(x + 18, y + 18, 56 * Math.min(1.25, k), a, T);
  const nx = x + 18 + 56 * Math.min(1.25, k) + 14;
  s += text(nx, y + 52, a.name, { size: 16 * Math.min(1.15, k), weight: 700, fill: T.text });
  s += text(nx, y + 72, `v${a.ver}`, { size: 11.5, fill: T.muted });
  s += originMini(nx + tw(`v${a.ver}`, 11.5) + 10, y + 68, key, T).s;
  s += '</g>';
  // state mark (top right)
  const marks = { update: ['Update', T.accentSoft, T.accent, 'update'], installed: ['Installed', T.okSoft, T.ok, 'check'], held: ['Installed', T.okSoft, T.ok, 'check'], pinned: ['Installed', T.okSoft, T.ok, 'check'], foreign: ['Outside AppKata', T.warnSoft, T.warn, 'info'] };
  if (o.busy) s += pill(x + w - 12, y + 12, 'Installing 45%', { bg: T.accentSoft, fg: T.accent, ic: 'download', anchor: 'end', size: 11 }).s;
  else if (marks[st]) { const [l, bg, fg, ic] = marks[st]; s += pill(x + w - 12, y + 12, l, { bg, fg, ic, anchor: 'end', size: 11 }).s; }
  if (a.veto) s += pill(x + w - 12, y + 12, 'Avoid', { bg: T.errSoft, fg: T.err, ic: 'warn', anchor: 'end', size: 11 }).s;
  // summary
  const sy = y + 92 * Math.min(1.15, k);
  s += `<g ${dim ? 'opacity="0.6"' : ''}>` + para(x + 18, sy + 4, w - 36, a.summary, T, { size: 12.5 * Math.min(1.12, k), lh: 18.5 * Math.min(1.12, k), max: 3 }).s + '</g>';
  // footer
  s += hline(x + 16, x + w - 16, y + h - 44, T.border);
  const fy = y + h - 22;
  const tb = trustBadge(x + 18, fy, a, T);
  s += tb.s;
  // tags: as many as fit; if some don't, trim and end with a › button that pops up all of them (req 12.4)
  const left = x + 18 + tb.w + 8, right = x + w - 16, gapT = 5, BTN = 22;
  const widths = a.tags.map(t => tw(t, 10.5, { bold: true }) + 18);
  const total = widths.reduce((p, q) => p + q + gapT, -gapT);
  let shown = a.tags.length;
  if (total > right - left) {
    shown = 0; let used = BTN;
    while (shown < a.tags.length && used + widths[shown] + gapT <= right - left) { used += widths[shown] + gapT; shown++; }
  }
  const trimmed = shown < a.tags.length;
  let tx = right - (trimmed ? BTN + gapT : 0) - widths.slice(0, shown).reduce((p, q) => p + q + gapT, shown ? -gapT : 0);
  for (let i = 0; i < shown; i++) { s += chip(tx, fy - 10, a.tags[i], T, { size: 10.5 }).s; tx += widths[i] + gapT; }
  if (trimmed) {
    const bx = right - BTN, hov = o.tagsHover;
    s += rect(bx, fy - 10, BTN, 20, 10, hov ? T.accentSoft : T.track, hov ? { stroke: T.accent } : {});
    s += icon('chevRight', bx + 5, fy - 6, 12, hov ? T.accent : T.muted, 1.9);
    if (hov && o.out) o.out.pop = tagsPopover(bx + BTN, fy - 16, a, T) + cursor(bx + 17, fy + 3);
  }
  return s;
}
function tagsPopover(xr, yb, a, T) {             // all of an app's tags, above the › button
  const w = 250, chipsW = w - 28;
  const rows = []; let row = [], rw = 0;
  a.tags.forEach(t => {
    const cw = tw(t, 11.5, { bold: true }) + 18;
    if (rw + cw > chipsW && row.length) { rows.push(row); row = []; rw = 0; }
    row.push(t); rw += cw + 6;
  });
  if (row.length) rows.push(row);
  const h = 44 + rows.length * 28 + 6, x = xr - w + 8, y = yb - h;
  let s = rect(x, y, w, h, 12, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, w - 1, h - 1, 12, 'none', { stroke: T.border });
  s += text(x + 14, y + 26, `${a.tags.length} tags`, { size: 12, weight: 700, fill: T.faint });
  rows.forEach((r, i) => {
    let cx = x + 14;
    r.forEach(t => { const c = chip(cx, y + 38 + i * 28, t, T, { size: 11.5, h: 22 }); s += c.s; cx += c.w + 6; });
  });
  return s;
}
function catalogTitle(T, x, right, o = {}) {
  let s = text(x, 98, 'Catalog', { size: 28, weight: 700, fill: T.text });
  s += text(x + tw('Catalog', 28, { bold: true }) + 14, 97, o.search ? `3 matches for “${o.search}”` : '86 apps · 10 sources, 3 trusts', { size: 14, fill: T.muted });
  const sw = o.panel ? 230 : 300;
  s += input(right - sw, 72, sw, T, { ic: 'search', value: o.search, placeholder: 'Search apps, tags, sources', focus: !!o.search, h: 38 });
  if (o.search) s += iconBtn(right - 22, 91, 'x', T, { r: 10, size: 10 });
  // tag chips + sort
  let cx = x; const cy = 128;
  ['All', 'foss', 'donation', 'offline', 'saas', 'freemium', 'reproducible'].slice(0, o.panel ? 5 : 7).forEach((t, i) => {
    const on = i === 0;
    const p = pill(cx, cy, t, { bg: on ? T.accentSoft : T.surface, fg: on ? T.accent : T.muted, stroke: on ? T.accent : T.border, size: 12, h: 28 });
    s += p.s; cx += p.w + 8;
  });
  const mp = pill(cx, cy, 'More… ▾', { bg: o.allTags ? T.accentSoft : T.surface, fg: o.allTags ? T.accent : T.muted, stroke: o.allTags ? T.accent : T.border, size: 12, h: 28 });
  s += mp.s;
  if (o.allTags) o._moreX = cx;
  const so = 'Sort: Trust, name';
  const sx = right - tw(so, 12.5, { bold: true }) - 50;
  s += rect(sx, cy, right - sx, 28, 14, T.surface, { stroke: T.border });
  s += icon('sort', sx + 10, cy + 6, 15, T.muted);
  s += text(sx + 30, cy + 18.5, so, { size: 12.5, weight: 700, fill: T.text });
  s += icon('chevDown', right - 22, cy + 7, 13, T.muted);
  return s;
}
function catalogGrid(T, x0, width, keys, o = {}) {
  const gap = 16, cols = Math.max(1, Math.floor((width + gap) / (280 + gap)));
  const w = (width - gap * (cols - 1)) / cols, h = Math.max(206, 210 * Math.min(1.12, w / 300));
  let s = '';
  keys.forEach((k, i) => {
    const r = Math.floor(i / cols), c = i % cols;
    if ((o.y0 || 176) + r * (h + gap) > H) return;      // off-screen (resvg trips on fully clipped filtered content)
    s += catalogTile(x0 + c * (w + gap), (o.y0 || 176) + r * (h + gap), w, h, k, T, { selected: k === o.selected, tagsHover: k === o.tagsHover, out: o.out, busy: k === o.busy });
  });
  return { s, h, rows: Math.ceil(keys.length / cols) };
}
function catalogView(T, o = {}) {
  let s = headerBar(T, 'catalog', { menuOpen: o.menu, syncing: o.syncing });
  const right = o.detail ? W - PANEL_W - 28 : W - 32;
  const ct = { panel: !!o.detail, search: o.search, allTags: o.allTags };
  s += catalogTitle(T, 32, right, ct);
  const byTrust = (p, q) => ((APPS[q].trust ?? -1) - (APPS[p].trust ?? -1)) || APPS[p].name.localeCompare(APPS[q].name);
  const keys = o.keys || [...CATALOG].sort(byTrust);       // Trust, then name; unreviewed last (req 12.2)
  const out = {};
  const g = catalogGrid(T, 32, right - 32, keys, { selected: o.detail, tagsHover: o.tagsHover, out, busy: o.busyTile });
  s += g.s + (out.pop || '');
  if (o.note) {
    const ny = 176 + g.rows * (g.h + 16) + 4;
    s += icon('info', 32, ny, 16, T.muted);
    s += text(56, ny + 12.5, o.note, { size: 13, fill: T.muted });
  }
  if (o.detail) s += detailPanel(T, o.detail, o);
  if (o.menu) s += appMenu(T, o);
  if (o.allTags) s += allTagsPopover(ct._moreX, 162, T);
  return s;
}
function allTagsPopover(x, y, T) {           // More… (req 12.2)
  const tags = ['foss', 'donation', 'offline', 'saas', 'freemium', 'reproducible', 'signed', 'portable', 'nonfreenet', 'upstreamnonfree', 'tracking', 'spyware', 'ads'];
  const w = 340, rows = [];
  let row = [], rw = 0;
  tags.forEach(t => { const cw = tw(t, 11.5, { bold: true }) + 18; if (rw + cw > w - 28 && row.length) { rows.push(row); row = []; rw = 0; } row.push(t); rw += cw + 6; });
  rows.push(row);
  const h = 44 + rows.length * 28 + 6;
  let s = rect(x, y, w, h, 12, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, w - 1, h - 1, 12, 'none', { stroke: T.border });
  s += text(x + 14, y + 26, `All tags · ${tags.length}`, { size: 12, weight: 700, fill: T.faint });
  rows.forEach((r, i) => { let cx = x + 14; r.forEach(t => { const c = chip(cx, y + 38 + i * 28, t, T, { size: 11.5, h: 22 }); s += c.s; cx += c.w + 6; }); });
  return s + cursor(x + 60, y - 18);
}

// ---------------------------------------------------------------- app menu (req 5.4)
function appMenu(T, o = {}) {
  const mw_ = 290, x = W - 64 - mw_ + 40, y = 50, mh = 458;
  let s = rect(x, y, mw_, mh, 14, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, mw_ - 1, mh - 1, 14, 'none', { stroke: T.border });
  s += rect(x + 6, y + 6, mw_ - 12, 56, 10, T.hover);
  s += icon('sync', x + 20, y + 18, 16, T.accent);
  s += text(x + 48, y + 29, 'Sync', { size: 14, weight: 700, fill: T.text });
  s += text(x + 48, y + 48, 'Last synced 2 h ago · 14 sources, 3 trusts', { size: 11.5, fill: T.muted });
  s += icon('gear', x + 20, y + 80, 16, T.muted);
  s += text(x + 48, y + 93, 'Settings…', { size: 14, weight: 700, fill: T.text });
  s += hline(x + 12, x + mw_ - 12, y + 118.5, T.border);
  [['Match system', false], ['Dark', T.dark], ['Light', !T.dark]].forEach(([label, sel], i) => {
    const yy = y + 126 + i * 40;
    s += `<circle cx="${x + 28}" cy="${yy + 19}" r="10" fill="${sel ? T.accent : 'none'}" stroke="${sel ? 'none' : T.borderStrong}" stroke-width="1.6"/>`;
    if (sel) s += `<circle cx="${x + 28}" cy="${yy + 19}" r="4" fill="#ffffff"/>`;
    s += text(x + 50, yy + 24, label, { size: 14, weight: 700, fill: T.text });
  });
  s += hline(x + 12, x + mw_ - 12, y + 250.5, T.border);
  s += icon('log', x + 20, y + 266, 16, T.muted);
  s += text(x + 48, y + 277, 'Show app log', { size: 14, weight: 700, fill: T.text });
  s += text(x + 48, y + 295, 'Downloads, installs and errors', { size: 11.5, fill: T.muted });
  s += icon('info', x + 20, y + 320, 16, T.muted);
  s += text(x + 48, y + 333, 'About AppKata', { size: 14, weight: 700, fill: T.text });
  s += hline(x + 12, x + mw_ - 12, y + 358.5, T.border);
  s += icon('window', x + 20, y + 374, 16, T.muted);
  s += text(x + 48, y + 387, 'Close window', { size: 14, weight: 700, fill: T.text });
  s += text(x + mw_ - 18, y + 387, 'Keeps running in the tray', { size: 11, fill: T.faint, anchor: 'end' });
  s += icon('power', x + 20, y + 420, 16, T.err);
  s += text(x + 48, y + 433, 'Quit AppKata', { size: 14, weight: 700, fill: T.err });
  s += text(x + mw_ - 18, y + 433, 'Alt+Q', { size: 11.5, fill: T.faint, anchor: 'end' });
  return s;
}

// ---------------------------------------------------------------- Apps (req 6)
const APP_ORDER_UPD = ['appkata', 'localsend', 'signal', 'zettlr'];
// installing (req 4.8): one download, the rest waiting
const BUSY = { localsend: { phase: 'Downloading 45%', p: 0.45, detail: '41.4 MB of 92.0 MB · 3.4 MB/s' }, appkata: { phase: 'Waiting', p: 0 }, signal: { phase: 'Waiting', p: 0 } };
const APP_ORDER_REST = ['flameshot', 'inkscape', 'keepassxc', 'syncthing', 'ventoy', 'vscodium'];
function appRow(x, y, w, key, T, o = {}) {
  const a = APPS[key], inst = INSTALLED[key];
  const upd = inst.to && !inst.held && !inst.pinned && !inst.system;
  let s = rect(x, y, w, 60, 12, o.selected ? T.accentSoft : T.surface, { stroke: o.selected ? T.accent : T.border, sw: o.selected ? 1.5 : 1 });
  if (upd) s += rect(x, y + 12, 3.5, 36, 2, T.accent);
  s += appIconArt(x + 16, y + 14, 32, a, T);
  s += text(x + 62, y + 27, a.name, { size: 14.5, weight: 700, fill: T.text });
  const vx = x + 62;
  if (upd) {
    s += text(vx, y + 46, inst.from, { size: 12, fill: T.muted, mono: true });
    const ax = vx + tw(inst.from, 12, { mono: true }) + 6;
    s += text(ax, y + 46, '→', { size: 12, fill: T.accent });
    s += text(ax + 16, y + 46, inst.to, { size: 12, weight: 700, fill: T.accent, mono: true });
  } else s += text(vx, y + 46, inst.from, { size: 12, fill: T.muted, mono: true });
  // middle column: source host + type
  const mx = x + w * 0.42;
  const om = originMini(mx, y + 22, key, T, { bg: o.selected ? T.accentSoft : T.surface });
  s += om.s + text(mx + om.w + 6, y + 27, originText(key), { size: 12.5, fill: T.muted });
  s += text(mx, y + 46, `${a.host} · ${inst.type}`, { size: 11.5, fill: T.faint });
  if (inst.sandbox) {             // app-sandboxing.md
    const sx = mx + tw(`${a.host} · ${inst.type}`, 11.5) + 10, off = inst.sandbox.level === 'Off';
    s += icon(off ? 'shield' : 'shieldCheck', sx, y + 36, 13, off ? T.faint : T.ok, 1.6);
    s += text(sx + 17, y + 46, off ? 'No sandbox' : inst.sandbox.level, { size: 11.5, weight: off ? 400 : 700, fill: off ? T.faint : T.ok });
  }
  // status
  const bx = x + w - 16 - 32 + (inst.self ? 40 : 0);    // AppKata can't uninstall itself (req 2.11.2)
  const b = o.busy && BUSY[key];
  if (b) {                     // phase, progress bar and an icon-only Cancel (req 4.8.1)
    const cx = x + w - 16 - 32, wait = b.phase === 'Waiting';
    s += text(cx - 10, y + 27, b.phase, { size: 12, weight: 700, fill: wait ? T.muted : T.accent, anchor: 'end' });
    if (b.detail && w > 900) s += text(cx - 18 - tw(b.phase, 12, { bold: true }), y + 27, b.detail, { size: 11, fill: T.faint, anchor: 'end' });
    s += rect(cx - 180, y + 36, 170, 5, 2.5, T.track) + (b.p ? rect(cx - 180, y + 36, 170 * b.p, 5, 2.5, T.accent) : '');
    s += sqBtn(cx, y + 14, 'x', T);
    return s;
  }
  if (inst.auto) s += pill(bx - 8, y + 19, 'Updates itself', { bg: T.track, fg: T.muted, ic: 'sync', anchor: 'end' }).s;
  if (MSVCRT === key) {         // the Visual C++ run-time, missing here (req 15.18.2)
    const p = pill(bx - 8, y + 19, 'MSVCRT', { bg: T.warnSoft, fg: T.warn, ic: 'warn', anchor: 'end' });
    s += p.s;
    const tip = 'Microsoft Visual C++ Run-time: not installed';
    if (o.msvcrtTip) s += tooltip(bx - 8 - p.w / 2, y - 18, tip, T, { right: bx - 8 + 12 });
  }
  if (inst.system) s += pill(bx - 8, y + 19, 'Updated by the system', { bg: T.track, fg: T.muted, ic: 'sync', anchor: 'end' }).s;
  if (inst.notUpdated) {        // a distro package nothing updates automatically (req 16.5)
    const p = pill(bx - 8, y + 19, 'Not updated', { bg: T.warnSoft, fg: T.warn, ic: 'warn', anchor: 'end' });
    s += p.s + tooltip(bx - 8 - p.w / 2, y - 18, inst.notUpdated, T, { right: bx - 8 + 12 });
  }
  if (inst.reviewBadge) s += pill(bx - 8, y + 19, 'Review sandbox', { bg: T.accentSoft, fg: T.accent, ic: 'shield', anchor: 'end' }).s;
  if (inst.setupNeeded) s += pill(bx - 8, y + 19, 'Not sandboxed', { bg: T.warnSoft, fg: T.warn, ic: 'warn', anchor: 'end' }).s;
  if (upd && inst.avoid) {
    s += pill(bx - 48, y + 19, 'Avoid this version', { bg: T.errSoft, fg: T.err, ic: 'warn', anchor: 'end' }).s;
    s += sqBtn(bx - 40, y + 14, 'update', T, { primary: true });
  } else if (upd) {
    s += pill(bx - 48, y + 19, 'Update available', { bg: T.accentSoft, fg: T.accent, dot: T.accent, anchor: 'end' }).s;
    s += sqBtn(bx - 40, y + 14, 'update', T, { primary: true });
  } else if (inst.held) {
    s += icon('clock', bx - 40 - 4 - tw(inst.held, 12) - 22, y + 22, 15, T.faint);
    s += text(bx - 48, y + 34, inst.held, { size: 12, fill: T.faint, anchor: 'end' });
  } else if (inst.pinned) {
    s += icon('pin', bx - 48 - tw('Pinned at 1.0.99', 12) - 20, y + 22, 15, T.faint);
    s += text(bx - 48, y + 34, 'Pinned at 1.0.99', { size: 12, fill: T.faint, anchor: 'end' });
  }
  if (!inst.self) s += sqBtn(bx, y + 14, 'trash', T, { danger: true, hover: o.hoverTrash });
  if (o.hoverTrash) s += tooltip(bx + 16, y - 22, 'Uninstall', T);
  return s;
}
function appsView(T, o = {}) {
  if (o.selfUpdated) {        // AppKata 0.2.0 installed, still running 0.1.0 (req 2.11.3)
    const keep = INSTALLED.appkata;
    INSTALLED.appkata = { from: '0.2.0', type: 'AppImage', self: true, restart: true };
    const s = appsView(T, { ...o, selfUpdated: false, _self: true });
    INSTALLED.appkata = keep;
    return s;
  }
  const upd = o.upd || (o._self ? APP_ORDER_UPD.filter(k => k !== 'appkata') : APP_ORDER_UPD), rest = o.rest || (o._self ? ['appkata', ...APP_ORDER_REST] : APP_ORDER_REST);
  let s = headerBar(T, 'apps', { badge: upd.length, installing: o.busy });
  const right = o.detail ? W - PANEL_W - 28 : W - 32, x = 32, w = right - x;
  s += text(x, 98, 'Apps', { size: 28, weight: 700, fill: T.text });
  s += text(x + tw('Apps', 28, { bold: true }) + 14, 97, `10 installed · ${upd.length} updates`, { size: 14, fill: T.muted });
  const fw = o.detail ? 170 : 240;
  s += input(right - fw, 72, fw, T, { ic: 'filter', placeholder: 'Filter', h: 38 });
  s += button(right - fw - 12, 74, 'Update all', T, { ic: 'update', primary: true, anchor: 'end' }).s;
  let y = 134;
  s += text(x, y + 10, `UPDATES · ${upd.length}`, { size: 11, weight: 700, fill: T.accent, ls: 1.2 });
  y += 22;
  upd.forEach(k => { s += appRow(x, y, w, k, T, { selected: k === o.detail, busy: o.busy }); y += 68; });
  y += 14;
  s += text(x, y + 10, `INSTALLED · ${rest.length}`, { size: 11, weight: 700, fill: T.faint, ls: 1.2 });
  y += 22;
  rest.forEach(k => { s += appRow(x, y, w, k, T, { selected: k === o.detail, hoverTrash: o.hoverTrash === k, msvcrtTip: o.msvcrtTip }); y += 68; });
  if (o.detail) s += detailPanel(T, o.detail, o);
  return s;
}

// ---------------------------------------------------------------- review dialog (req 8.4)
function picker(x, y, value, T, o = {}) {        // "–★★★★★"
  let s = '';
  const avoid = o.trust && value === 0;
  // dash
  const dashOn = value === 0;
  s += rect(x, y, 34, 34, 9, dashOn ? (avoid ? T.errSoft : T.track) : 'none', dashOn ? { stroke: avoid ? T.err : T.borderStrong } : {});
  s += `<path d="M${x + 10},${y + 17}H${x + 24}" stroke="${dashOn ? (avoid ? T.err : T.text) : T.faint}" stroke-width="2.6" stroke-linecap="round"/>`;
  for (let i = 0; i < 5; i++) {
    const cx = x + 56 + i * 32, on = value != null && i < value;
    const col = avoid ? T.err : o.trust ? T.ok : T.star;
    s += `<path d="${starPath(cx, y + 17, 12)}" fill="${on ? col : 'none'}" stroke="${on ? col : T.borderStrong}" stroke-width="1.6" stroke-linejoin="round"/>`;
  }
  if (o.hover != null) s += cursor(x + 56 + o.hover * 32 + 4, y + 22);
  // clear
  s += iconBtn(x + 56 + 4 * 32 + 34, y + 17, 'x', T, { r: 10, size: 10 });
  return s;
}
const TRUST_WORDS = ['Avoid', 'Wary', 'Cautious', 'Trusted with reservations', 'Trusted', 'Fully trusted'];
function reviewDialog(T, o = {}) {
  const key = o.app || 'localsend', a = APPS[key];
  let s = appsView(T, { detail: key });
  s += scrim(T);
  const dw = 780, dh = o.version ? 756 : o.unsigned ? 712 : 664, dx = (W - dw) / 2, dy = (H - dh) / 2 + (o.version ? 0 : 12);
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  const x0 = dx + 30, iw = dw - 60;
  s += appIconArt(x0, dy + 24, 36, a, T);
  s += text(x0 + 50, dy + 40, 'Review', { size: 12, weight: 700, fill: T.faint, ls: 1 });
  s += text(x0 + 50, dy + 59, a.name, { size: 20, weight: 700, fill: T.text });
  s += iconBtn(x0 + iw - 12, dy + 42, 'x', T);
  s += icon('folder', x0 + iw - 40 - tw('~/src/reviews/AppKata.md', 11.5, { mono: true }) - 22, dy + 34, 14, T.faint);
  s += text(x0 + iw - 40, dy + 46, '~/src/reviews/AppKata.md', { size: 11.5, fill: T.faint, mono: true, anchor: 'end' });
  let y = dy + 92;
  if (o.version) {          // which review this is: a release, or Any version (req 8.4.1.1)
    s += text(x0, y, 'Version', { size: 12.5, weight: 700, fill: T.muted });
    s += input(x0, y + 10, 220, T, { value: o.version.value, h: 38 });
    s += icon('chevDown', x0 + 220 - 28, y + 21, 16, T.muted);
    s += para(x0 + 236, y + 26, iw - 236, o.version.note, T, { size: 12, lh: 16, fill: T.muted }).s;
    y += 66;
  }
  // tags
  s += text(x0, y, 'Tags', { size: 12.5, weight: 700, fill: T.muted });
  s += rect(x0, y + 10, iw, 42, 11, T.input, { stroke: o.tagsOpen ? T.accent : T.border, sw: o.tagsOpen ? 2 : 1 });
  let tx = x0 + 10;
  (o.tags || ['foss', 'donation', 'offline']).forEach(t => {
    const warnT = WARN_TAGS.includes(t);
    const fg = warnT ? T.warn : T.accent, pw_ = tw(t, 12, { bold: true }) + 36;
    s += rect(tx, y + 20, pw_, 22, 11, warnT ? T.warnSoft : T.accentSoft);
    s += text(tx + 10, y + 35.3, t, { size: 12, weight: 700, fill: fg });
    s += icon('x', tx + pw_ - 18, y + 26.5, 9, fg, 1.8);
    tx += pw_ + 8;
  });
  s += text(tx + 4, y + 36, 'Add a tag…', { size: 13, fill: T.faint });
  s += icon('chevDown', x0 + iw - 28, y + 23, 16, T.muted);
  y += 76;
  // trust + rating
  const tv = o.trust != null ? o.trust : 4, rv = o.rating != null ? o.rating : 5;
  s += text(x0, y, 'Trust', { size: 12.5, weight: 700, fill: T.muted });
  s += picker(x0, y + 12, tv, T, { trust: true });
  s += text(x0 + 252, y + 34, `${tv} · ${TRUST_WORDS[tv]}`, { size: 14, weight: 700, fill: tv === 0 ? T.err : T.ok });
  s += text(x0, y + 66, tv === 0 ? 'Avoid hides this app from everyone who trusts your file.' : 'How far you trust this app and its authors',
            { size: 11.5, fill: tv === 0 ? T.err : T.faint });
  const rx = x0 + 438;
  s += `<path d="M${rx - 22},${y - 6}V${y + 70}" stroke="${T.border}"/>`;
  s += text(rx, y, 'Rating', { size: 12.5, weight: 700, fill: T.muted });
  s += picker(rx, y + 12, rv, T, { hover: o.ratingHover });
  s += text(rx + 252, y + 34, `${rv} of 5`, { size: 14, weight: 700, fill: T.text });
  s += text(rx, y + 66, 'How much you like it', { size: 11.5, fill: T.faint });
  y += 92;
  // markdown editor
  s += text(x0, y + 4, 'Review', { size: 12.5, weight: 700, fill: T.muted });
  const tabs = [['Edit', true], ['Preview', false]];
  let tbx = x0 + iw - 150;
  s += rect(tbx, y - 12, 150, 28, 8, T.track);
  tabs.forEach(([l, on], i) => {
    if (on) s += rect(tbx + 3 + i * 72, y - 9, 72, 22, 6, T.segOn, { filter: 'seg' });
    s += text(tbx + 3 + i * 72 + 36, y + 6, l, { size: 12, weight: 700, fill: on ? T.text : T.muted, anchor: 'middle' });
  });
  y += 18;
  const eh = o.version ? 112 : o.md ? 190 : 210;
  s += rect(x0, y, iw, eh, 11, T.input, { stroke: T.accent, sw: 2 });
  s += rect(x0 + 1, y + 1, iw - 2, 32, 10, T.dark ? '#1f222b' : '#f0f2f7');
  hline(x0, x0 + iw, y + 33, T.border);
  ['B', 'I', '“', '•', '1.', '🔗'].forEach((b, i) => {
    s += text(x0 + 20 + i * 30, y + 22, b === '🔗' ? '⌁' : b, { size: 13, weight: 700, fill: T.muted, anchor: 'middle' });
  });
  s += text(x0 + iw - 14, y + 22, o.version ? `## ${a.name}[${String(o.version.value).split(" ")[0]}]` : `# ${a.name}`, { size: 11.5, fill: T.faint, mono: true, anchor: 'end' });
  const md = o.md || [
    ['Works great across Linux, Windows and my phone. No account, no cloud:', T.text],
    ['transfers stay on the LAN and are encrypted with TLS.', T.text],
    ['', T.text],
    ['- Releases are built in CI from tagged commits; checksums are published.', T.text],
    ['- **Watch out:** the firewall prompt on Windows is easy to dismiss.', T.text],
    ['', T.text],
    ['Donations via Open Collective.', T.text],
  ];
  md.forEach(([l, c], i) => {
    const y2 = y + 56 + i * 19;
    if (l.startsWith('- ')) {
      s += text(x0 + 16, y2, '-', { size: 12.5, fill: T.accent, mono: true });
      const bold = l.match(/\*\*(.+?)\*\*/);
      if (bold) {
        s += text(x0 + 34, y2, '**' + bold[1] + '**', { size: 12.5, fill: T.text, mono: true, weight: 700 });
        s += text(x0 + 34 + tw('**' + bold[1] + '**', 12.5, { mono: true, bold: true }), y2, l.slice(2).replace(/\*\*(.+?)\*\*/, '').replace(/^ /, '\u00a0'), { size: 12.5, fill: c, mono: true });
      } else s += text(x0 + 34, y2, l.slice(2), { size: 12.5, fill: c, mono: true });
    } else s += text(x0 + 16, y2, l, { size: 12.5, fill: c, mono: true });
  });
  if (o.version) { const last = md[md.length - 1][0]; s += `<path d="M${x0 + 16 + tw(last, 12.5, { mono: true }) + 2},${y + 56 + (md.length - 1) * 19 - 13}V${y + 56 + (md.length - 1) * 19 + 3}" stroke="${T.accent}" stroke-width="1.5"/>`; }
  else if (!o.md) s += `<path d="M${x0 + 16 + tw('Donations via Open Collective.', 12.5, { mono: true }) + 2},${y + 56 + 6 * 19 - 13}V${y + 56 + 6 * 19 + 3}" stroke="${T.accent}" stroke-width="1.5"/>`;
  y += eh + 12;
  if (o.version && o.version.details) {     // what the reviewer has installed, as ### <App>[<version>]::Details lines
    y += 4;
    s += checkbox(x0, y - 4, true, T);
    s += text(x0 + 28, y + 9, 'Include what I have installed', { size: 13.5, weight: 700, fill: T.text });
    s += text(x0 + 28 + tw('Include what I have installed ', 13.5, { bold: true }), y + 9, 'as Details, published with your review', { size: 12, fill: T.faint });
    y += 20;
    s += rect(x0 + 28, y, iw - 28, o.version.details.length * 17 + 14, 9, T.input, { stroke: T.border });
    o.version.details.forEach((l, i) => { s += text(x0 + 42, y + 20 + i * 17, l, { size: 11.5, fill: T.muted, mono: true }); });
    y += o.version.details.length * 17 + 26;
  }
  // the install options sub-section it will write (req 8.4.7)
  y += 10;
  // git options
  s += checkbox(x0, y - 4, true, T);
  s += text(x0 + 28, y + 9, 'Auto-commit', { size: 13.5, weight: 700, fill: T.text });
  s += checkbox(x0 + 150, y - 4, true, T);
  s += text(x0 + 178, y + 9, 'Auto-push', { size: 13.5, weight: 700, fill: T.text });
  s += icon('branch', x0 + 290, y - 3, 14, T.faint);
  s += text(x0 + 310, y + 8, 'main → origin  github.com/dgriffin/reviews', { size: 12, fill: T.faint });
  y += 30;
  if (o.unsigned) {
    s += rect(x0, y, iw, 60, 12, T.errSoft, { stroke: T.err });
    s += icon('lock', x0 + 14, y + 13, 16, T.err, 1.7);
    s += text(x0 + 40, y + 25, 'Commit 4e1c9a2 isn’t signed, so it wasn’t pushed.', { size: 13, weight: 700, fill: T.err });
    s += text(x0 + 40, y + 44, 'Your trust file must be signed by one of its authorities.', { size: 12, fill: T.text });
    s += button(x0 + iw - 12, y + 13, 'How to set up signing', T, { anchor: 'end', h: 34, size: 12.5 }).s;
    y += 72;
  } else {
    s += rect(x0, y, iw, 40, 11, T.okSoft);
    s += icon('key', x0 + 14, y + 12, 16, T.ok, 1.7);
    s += text(x0 + 40, y + 25, 'Commits are signed with your SSH key SHA256:dG7a…Xk2e', { size: 12.5, fill: T.text });
    y += 52;
  }
  // footer buttons
  const by = dy + dh - 58;
  const sv = button(x0 + iw, by, o.unsigned ? 'Amend with signing' : 'Save', T, { primary: true, anchor: 'end' });
  s += sv.s;
  s += button(x0 + iw - sv.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  if (o.unsigned) s += text(x0, by + 22, 'Saved to AppKata.md and committed locally.', { size: 12.5, fill: T.muted });
  return s;
}

// ---------------------------------------------------------------- Sources (req 7)
const SOURCES = [
  { key: 'localsend', chips: [['Installed', 'ok']] },
  { key: 'signal', chips: [['Installed', 'ok']] },
  { key: 'appkata', chips: [['Installed', 'ok'], ['Built in', 'accent']] },
  { key: 'kdenlive', chips: [], err: 'Rate limited until 14:32 · add a GitLab token in Settings' },
  { key: 'flameshot', chips: [['Installed', 'ok']] },
  { key: 'inkscape', chips: [['Installed', 'ok']] },
  { key: 'keepassxc', chips: [['Installed', 'ok']] },
  { key: 'obs', chips: [['Installed outside AppKata', 'warn', 'info']] },
  { key: 'joplin', chips: [['Track only', 'muted']] },
  { key: 'ventoy', chips: [['Installed', 'ok'], ['Pinned at 1.0.99', 'muted', 'pin']] },
  { key: 'syncthing', chips: [['Installed', 'ok']] },
];
function sourceRow(x, y, w, src, T, o = {}) {
  const a = APPS[src.key];
  const h = src.err ? 86 : 70;
  let s = rect(x, y, w, h, 12, o.selected ? T.accentSoft : T.surface, { stroke: o.selected ? T.accent : T.border });
  s += appIconArt(x + 16, y + 15, 40, a, T);
  s += text(x + 70, y + 30, a.name, { size: 14.5, weight: 700, fill: T.text });
  let cx = x + 70 + tw(a.name, 14.5, { bold: true }) + 10;
  for (const [l, k, ic] of src.chips) {
    const p = pill(cx, y + 16, l, { bg: k === 'ok' ? T.okSoft : k === 'warn' ? T.warnSoft : k === 'accent' ? T.accentSoft : T.track,
                                    fg: k === 'ok' ? T.ok : k === 'warn' ? T.warn : k === 'accent' ? T.accent : T.muted, ic, size: 10.5, h: 19 });
    s += p.s; cx += p.w + 5;
  }
  const tr = ORIGIN[src.key].tr.filter(i => i > 0);
  if (tr.length) {
    const lab = `In ${tr.length} trust${tr.length > 1 ? 's' : ''}`, pw_ = 18 + (tr.length - 1) * 10 + tw(lab, 10.5, { bold: true }) + 16;
    const bg = o.trustHover ? T.accentSoft : T.track;
    s += rect(cx, y + 16, pw_, 19, 9.5, bg, o.trustHover ? { stroke: T.accent } : {});
    tr.forEach((ti, i) => { s += avatar(cx + 10 + i * 10, y + 25.5, 6.5, TRUSTS[ti].auth[0], T, { ring: true, ringColor: bg }); });
    s += text(cx + 18 + (tr.length - 1) * 10 + 6, y + 29.3, lab, { size: 10.5, weight: 700, fill: T.accent });
    if (o.trustHover) o._pillX = cx;
  }
  s += text(x + 70, y + 51, `https://${a.host}/${a.repo}`, { size: 11.5, fill: T.muted, mono: true });
  if (src.err) {
    s += icon(src.errIc || 'clock', x + 70, y + 61, 13, T.warn, 1.6);
    s += text(x + 88, y + 72, src.err, { size: 12, weight: 700, fill: T.warn });
    if (src.action) s += button(x + 88 + tw(src.err, 12, { bold: true }) + 12, y + 58, src.action, T, { h: 22, size: 11.5, soft: true }).s;
  }
  // right: forge + version
  const rx = x + w - 56;
  s += text(rx - 4, y + 30, `v${a.ver}`, { size: 13, weight: 700, fill: T.text, mono: true, anchor: 'end' });
  s += text(rx - 4, y + 50, `${a.forge} · ${a.date}`, { size: 11.5, fill: T.faint, anchor: 'end' });
  s += iconBtn(x + w - 28, y + h / 2, 'more', T, { r: 15, active: o.menu, bg: 'none' });
  return { s, h };
}
function sourceMenu(x, y, T) {
  const mw_ = 230, mh = 186;
  let s = rect(x, y, mw_, mh, 12, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, mw_ - 1, mh - 1, 12, 'none', { stroke: T.border });
  const items = [['pin', 'Pin at 2.7.10'], ['gear', 'Source settings…'], ['open', 'Open project page']];
  items.forEach(([ic, l], i) => { s += icon(ic, x + 16, y + 14 + i * 40, 16, T.muted); s += text(x + 44, y + 27 + i * 40, l, { size: 13.5, weight: 700, fill: T.text }); });
  s += hline(x + 10, x + mw_ - 10, y + 132.5, T.border);
  s += rect(x + 6, y + 140, mw_ - 12, 38, 8, T.errSoft);
  s += icon('trash', x + 16, y + 151, 16, T.err);
  s += text(x + 44, y + 164, 'Remove source', { size: 13.5, weight: 700, fill: T.err });
  return s;
}
function trustsPopover(x, y, key, T) {          // which Trusts also list this Source (req 2.9.4)
  const tr = ORIGIN[key].tr.filter(i => i > 0).sort(byScore), w = 330, h = 44 + tr.length * 50;
  let s = rect(x, y, w, h, 14, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, w - 1, h - 1, 14, 'none', { stroke: T.border });
  s += text(x + 16, y + 27, `Also listed by ${tr.length} trusts`, { size: 12, weight: 700, fill: T.faint });
  const vals = [[5, 4.5], [4, 4], [5, 5]];
  tr.forEach((ti, i) => {
    const t = TRUSTS[ti], ry = y + 40 + i * 50;
    if (i === 0) s += rect(x + 6, ry, w - 12, 46, 10, T.hover);
    s += avatar(x + 30, ry + 23, 13, t.auth[0], T, { ringColor: i === 0 ? T.hover : T.raised });
    s += text(x + 52, ry + 20, t.name, { size: 13, weight: 700, fill: T.text });
    s += stars(x + 58 + tw(t.name, 13, { bold: true }), ry + 16, t.score, 4, T, { color: T.accent }).s;
    s += icon('shield', x + 52, ry + 27, 12, T.ok, 1.6);
    s += text(x + 68, ry + 37.5, String(vals[ti - 1][0]), { size: 11.5, weight: 700, fill: T.text });
    s += stars(x + 82, ry + 33, vals[ti - 1][1], 4.2, T).s;
    s += text(x + w - 36, ry + 28, 'Open', { size: 12, weight: 700, fill: T.accent, anchor: 'end' });
    s += icon('chevRight', x + w - 32, ry + 17, 12, T.accent, 1.8);
  });
  s += cursor(x + 112, y - 16);
  return s;
}
function trustRow(x, y, w, t, T, o = {}) {
  let s = rect(x, y, w, 66, 12, o.selected ? T.accentSoft : T.surface, { stroke: o.selected ? T.accent : T.border, sw: o.selected ? 1.5 : 1 });
  const st = avatarStack(x + 12, y + 33, t.auth, 13, T, { bg: o.selected ? T.accentSoft : T.surface });
  s += st.s;
  const nx = x + 12 + 13 * 2 + 4 * 13 * 1.35 + 12;
  s += text(nx, y + 28, t.name, { size: 13.5, weight: 700, fill: T.text });
  const sc = stars(nx, y + 43, t.score, 4.4, T, { color: T.accent });
  s += sc.s + text(nx + sc.w + 6, y + 47, t.own ? 'Your file · always applied' : `${t.apps} apps · synced ${t.synced}`, { size: 11.5, fill: T.muted });
  if (t.warn) {
    s += `<circle cx="${x + w - 22}" cy="${y + 33}" r="11" fill="${T.warnSoft}"/>` + icon('warn', x + w - 29, y + 26, 14, T.warn, 1.6);
  } else if (t.nostr) s += pill(x + w - 12, y + 22, 'ngit', { bg: T.track, fg: T.muted, anchor: 'end', size: 10.5, h: 19 }).s;
  return s;
}
function hoverCard(x, y, key, T) {
  const a = AVATARS[key], w = 340, h = 168;
  let s = rect(x, y, w, h, 14, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, w - 1, h - 1, 14, 'none', { stroke: T.border });
  s += avatar(x + 36, y + 38, 20, key, T, { ringColor: T.raised });
  s += text(x + 66, y + 34, a.name, { size: 14.5, weight: 700, fill: T.text });
  s += text(x + 66, y + 53, a.id, { size: 12, fill: T.muted });
  const rows = [['Key', `${a.kind} · ${a.fp}`], ['First seen', 'Mar 12, 2025 · commit 9f2ab01'], ['Last signed', 'Sep 29 · commit c41e7d3'], ['Status', 'Enabled authority']];
  rows.forEach(([k, v], i) => {
    s += text(x + 16, y + 86 + i * 20, k, { size: 11.5, fill: T.faint });
    s += text(x + 96, y + 86 + i * 20, v, { size: 11.5, fill: i === 3 ? T.ok : T.text, mono: i === 0 });
  });
  // auto-dismiss progress
  s += rect(x + 14, y + h - 6, w - 28, 2.5, 1.2, T.track) + rect(x + 14, y + h - 6, (w - 28) * 0.6, 2.5, 1.2, T.accent);
  return s;
}
function trustRail(T, px) {          // the Trust panel collapsed (req 7.6)
  let s = rect(px, 53, W - px, H - 53, 0, T.side) + `<path d="M${px + 0.5},53 V${H}" stroke="${T.border}"/>`;
  s += rect(px + 11, 74, 34, 32, 9, T.surface, { stroke: T.border }) + icon('panel', px + 20, 82, 16, T.muted);
  s += icon('shieldCheck', px + 18, 124, 20, T.accent) + `<circle cx="${px + 39}" cy="124" r="4.5" fill="${T.warn}"/>`;
  return s + cursor(px + 30, 96);
}
function trustPanel(T, px, o = {}) {
  const pw = W - px;
  let s = rect(px, 53, pw, H - 53, 0, T.side) + `<path d="M${px + 0.5},53 V${H}" stroke="${T.border}"/>`;
  const x0 = px + 22, iw = pw - 44;
  s += icon('shieldCheck', x0, 80, 18, T.accent);
  s += text(x0 + 26, 94, 'Trusts', { size: 19, weight: 700, fill: T.text });
  s += text(x0 + 26 + tw('Trusts', 19, { bold: true }) + 8, 94, String(TRUSTS.length), { size: 14, fill: T.faint });
  s += button(x0 + iw - 44, 75, 'Add', T, { ic: 'plus', anchor: 'end', h: 32 }).s;
  s += rect(x0 + iw - 34, 75, 34, 32, 9, T.surface, { stroke: T.border }) + icon('panel', x0 + iw - 26, 83, 16, T.muted);
  let y = 122;
  TRUST_ORDER.forEach(i => { s += trustRow(x0, y, iw, TRUSTS[i], T, { selected: o.trust === i }); y += 74; });
  if (o.hover != null) {
    const t = TRUSTS[o.hover.trust], pos = TRUST_ORDER.indexOf(o.hover.trust);
    s += hoverCard(x0 + 4, 122 + pos * 74 + 58, t.auth[o.hover.i], T);
    s += cursor(x0 + 12 + 13 + o.hover.i * 13 * 1.35 + 2, 122 + pos * 74 + 36);
  }
  if (o.trust != null) s += trustDetail(T, x0, iw, o.trust);
  return s;
}
function trustDetail(T, x0, iw, idx) {
  const t = TRUSTS[idx];
  const y0 = 422, px = x0 - 22, pw = iw + 44;
  let s = rect(px, y0, pw, H - y0, 0, T.surface, { filter: 'lift' }) + hline(px, px + pw, y0 + 0.5, T.border);
  s += text(x0, y0 + 30, 'TRUST DETAILS', { size: 11, weight: 700, fill: T.faint, ls: 1.2 });
  s += iconBtn(x0 + iw - 12, y0 + 25, 'x', T);
  s += text(x0, y0 + 58, t.name, { size: 16, weight: 700, fill: T.text });
  s += text(x0, y0 + 77, t.url.length > 44 ? t.url.slice(0, 43) + '…' : t.url, { size: 11, fill: T.muted, mono: true });
  s += icon('check', x0, y0 + 88, 13, T.ok, 1.8);
  s += text(x0 + 18, y0 + 99, 'Verified at c41e7d3 · Sep 29 · 112 apps · 1 parse warning', { size: 11.5, fill: T.muted });
  // Score (req 7.6.8): how much its reviews count
  s += text(x0, y0 + 128, 'Score', { size: 13, weight: 700, fill: T.text });
  s += stars(x0 + 50, y0 + 124, t.score, 7.5, T, { color: T.accent }).s;
  s += text(x0 + 140, y0 + 128, `${t.score} of 5`, { size: 12, fill: T.muted });
  s += para(x0, y0 + 148, iw, 'How much this Trust’s reviews count: a 5-star Trust weighs five times a 1-star one.', T, { size: 11, lh: 15, fill: T.faint }).s;
  // pending signer
  let y = y0 + 176;
  s += rect(x0, y, iw, 100, 11, T.warnSoft, { stroke: T.warn });
  s += `<circle cx="${x0 + 26}" cy="${y + 24}" r="13" fill="${T.track}"/>` + text(x0 + 26, y + 28.5, '?', { size: 13, weight: 700, fill: T.muted, anchor: 'middle' });
  s += text(x0 + 48, y + 20, 'New signer · not trusted', { size: 12.5, weight: 700, fill: T.warn });
  s += text(x0 + 48, y + 37, 'nadia@desk.coop · SSH SHA256:Lq9v…', { size: 11, fill: T.text, mono: true });
  s += text(x0 + 48, y + 54, 'Signed 3 commits since c41e7d3 · not applied', { size: 11.5, fill: T.muted });
  const tsb = button(x0 + iw - 10, y + 64, 'Trust signer', T, { anchor: 'end', h: 28, primary: true, size: 12 });
  s += tsb.s + button(x0 + iw - 18 - tsb.w, y + 64, 'Ignore', T, { anchor: 'end', h: 28, size: 12 }).s;
  y += 112;
  s += text(x0, y + 8, 'AUTHORITIES · 6', { size: 10.5, weight: 700, fill: T.faint, ls: 1.1 });
  y += 18;
  const list = ['jo', 'rp', 'tk', 'ab'];
  list.forEach((k, i) => {
    const a = AVATARS[k], ry = y + i * 48, off = k === 'ab';
    s += avatar(x0 + 18, ry + 22, 15, k, T, { dim: off });
    s += text(x0 + 44, ry + 18, a.name, { size: 13, weight: 700, fill: off ? T.faint : T.text });
    s += text(x0 + 44, ry + 35, `${a.kind} · ${a.fp}`, { size: 10.5, fill: T.muted, mono: true });
    s += toggle(x0 + iw - 76, ry + 12, !off, T);
    s += sqBtn(x0 + iw - 30, ry + 7, 'trash', T, { s: 30, danger: true });
    if (i < list.length - 1) s += hline(x0, x0 + iw, ry + 45, T.border);
  });
  return s;
}
function sourcesView(T, o = {}) {
  let s = headerBar(T, 'sources', { syncing: o.syncing });
  const px = o.collapsed ? W - 56 : W - 400;
  const right = px - 28, x = 32, w = right - x;
  s += text(x, 98, 'Sources', { size: 28, weight: 700, fill: T.text });
  s += text(x + tw('Sources', 28, { bold: true }) + 14, 97, '11 sources', { size: 14, fill: T.muted });
  const addB = button(right, 74, 'Add source', T, { ic: 'plus', primary: true, anchor: 'end' });
  const expB = button(right - addB.w - 10, 74, 'Explore', T, { ic: 'compass', anchor: 'end' });
  s += addB.s + expB.s;
  s += input(right - addB.w - expB.w - 22 - 170, 74, 170, T, { ic: 'filter', placeholder: 'Filter', h: 34 });
  let y = 132;
  let pop = '';
  (o.sources || SOURCES).forEach((src, i) => {
    const ro = { menu: o.menu === i, trustHover: o.trustHover === i, selected: o.highlight === src.key };
    const r = sourceRow(x, y, w, src, T, ro);
    s += r.s;
    if (o.menu === i) o._menuY = y + r.h / 2;
    if (ro.trustHover) pop = trustsPopover(ro._pillX, y + 40, src.key, T);
    y += r.h + 8;
  });
  s += pop;
  s += o.collapsed ? trustRail(T, px) : trustPanel(T, px, o);
  if (o.menu != null) s += sourceMenu(right - 236, o._menuY + 18 + 186 > H - 8 ? o._menuY - 18 - 186 : o._menuY + 18, T);   // opens upward near the bottom
  return s;
}

// ---------------------------------------------------------------- dialogs over Sources
function addSourceDialog(T) {
  let s = sourcesView(T, {});
  s += scrim(T);
  const dw = 600, dh = 590, dx = (W - dw) / 2, dy = (H - dh) / 2 + 12, a = APPS.tenacity;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  const x0 = dx + 30, iw = dw - 60;
  s += text(x0, dy + 46, 'Add source', { size: 21, weight: 700, fill: T.text });
  s += iconBtn(x0 + iw - 12, dy + 39, 'x', T);
  let y = dy + 82;
  s += text(x0, y, 'Project or releases URL', { size: 12.5, weight: 700, fill: T.muted });
  s += input(x0, y + 10, iw, T, { value: 'https://codeberg.org/tenacityteam/tenacity', focus: true, mono: true, size: 13, h: 42 });
  s += text(x0, y + 72, 'A forge project, a releases page, or an ngit nostr:// address.', { size: 12, fill: T.faint });
  y += 98;
  // detection steps
  const steps = [['Forgejo detected', '/api/v1/version → Forgejo 12.0 (Gitea-compatible API)'], ['Releases found', '24 releases · latest v1.3.4, Jan 12'], ['Download chosen for Linux x86_64', 'tenacity-linux-1.3.4.AppImage · 92 MB']];
  steps.forEach(([h1, h2], i) => {
    const sy = y + i * 46;
    s += `<circle cx="${x0 + 11}" cy="${sy + 11}" r="11" fill="${T.okSoft}"/>` + icon('check', x0 + 5, sy + 5, 12, T.ok, 2);
    s += text(x0 + 32, sy + 10, h1, { size: 13.5, weight: 700, fill: T.text });
    s += text(x0 + 32, sy + 28, h2, { size: 12, fill: T.muted, mono: i > 0 });
  });
  y += 146;
  // preview card
  s += rect(x0, y, iw, 96, 14, T.input, { stroke: T.border });
  s += appIconArt(x0 + 16, y + 18, 60, a, T);
  s += text(x0 + 92, y + 38, a.name, { size: 17, weight: 700, fill: T.text });
  s += text(x0 + 92, y + 58, 'v1.3.4 · codeberg.org/tenacityteam/tenacity', { size: 12, fill: T.muted });
  s += trustBadge(x0 + 92, y + 78, a, T).s;
  s += pill(x0 + iw - 14, y + 16, 'Not installed', { bg: T.track, fg: T.muted, anchor: 'end', size: 11 }).s;
  y += 108;
  s += rect(x0, y, iw, 40, 11, T.accentSoft);
  s += avatar(x0 + 22, y + 20, 10, 'jo', T, { ringColor: T.accentSoft });
  s += text(x0 + 42, y + 25, 'Already listed by', { size: 12.5, fill: T.text });
  s += text(x0 + 42 + tw('Already listed by ', 12.5), y + 25, 'desk-collective / reviews', { size: 12.5, weight: 700, fill: T.accent });
  s += text(x0 + iw - 14, y + 25, 'Adding makes it your own source too', { size: 11.5, fill: T.muted, anchor: 'end' });
  y += 58;
  s += icon('chevRight', x0, y - 2, 14, T.accent, 1.8);
  s += text(x0 + 20, y + 10, 'Source settings', { size: 13, weight: 700, fill: T.accent });
  s += text(x0 + 20 + tw('Source settings', 13, { bold: true }) + 8, y + 10, 'prereleases, filters, pin, minimum age', { size: 12, fill: T.faint });
  const by = dy + dh - 58;
  const add = button(x0 + iw, by, 'Add source', T, { primary: true, anchor: 'end' });
  s += add.s + button(x0 + iw - add.w - 10, by, 'Add and install', T, { anchor: 'end', ic: 'download' }).s;
  return s;
}
function removeSourceDialog(T) {
  let s = sourcesView(T, {});
  s += scrim(T);
  const dw = 520, dh = 284, dx = (W - dw) / 2, dy = (H - dh) / 2, a = APPS.keepassxc;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  const x0 = dx + 30, iw = dw - 60;
  s += appIconArt(x0, dy + 28, 44, a, T);
  s += text(x0 + 58, dy + 48, 'Remove KeePassXC?', { size: 20, weight: 700, fill: T.text });
  s += text(x0 + 58, dy + 68, 'github.com/keepassxreboot/keepassxc', { size: 12, fill: T.muted, mono: true });
  s += para(x0, dy + 112, iw, 'KeePassXC 2.7.10 was installed by AppKata. You can uninstall it too, or keep it installed.', T, { size: 13.5, lh: 21, fill: T.text }).s;
  s += rect(x0, dy + 150, iw, 44, 11, T.accentSoft);
  [1, 2, 3].forEach((ti, i) => { s += avatar(x0 + 22 + i * 12, dy + 172, 9, TRUSTS[ti].auth[0], T, { ring: true, ringColor: T.accentSoft }); });
  s += para(x0 + 72, dy + 176.5, iw - 86, 'Also listed by 3 trusts, so it stays in the Catalog.', T, { size: 12.5, lh: 18, fill: T.text }).s;
  const by = dy + dh - 62;
  const r1 = button(x0 + iw, by, 'Remove and uninstall', T, { primary: true, danger: true, anchor: 'end', ic: 'trash' });
  const r2 = button(x0 + iw - r1.w - 10, by, 'Remove only', T, { anchor: 'end' });
  s += r1.s + r2.s + button(x0 + iw - r1.w - r2.w - 20, by, 'Cancel', T, { anchor: 'end' }).s;
  return s;
}

// ---------------------------------------------------------------- confirmations (req 5.8)
function confirmDialog(T, base, c) {
  // c: {title, body, action, ic, danger, app, warn: {title, lines, note}, extra: [label, ic], list}
  let s = base + scrim(T);
  const dw = c.warn ? 600 : 500, x0 = (W - dw) / 2 + 30, iw = dw - 60;
  const head = c.app ? 44 : 30;
  const body = para(x0, 0, iw, c.body, T, { size: 14, lh: 21, fill: T.text });
  const warnH = c.warn ? 30 + c.warn.lines.length * 19 + 34 + 16 : 0;
  const listH = c.list ? para(0, 0, iw, c.list, T, { size: 13, lh: 19 }).h + 14 : 0;
  const checkH = c.check ? 56 : 0;
  const dh = 30 + head + 22 + body.h + 18 + warnH + listH + checkH + 34 + 30 + 4;
  const dx = (W - dw) / 2, dy = (H - dh) / 2;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' }) + rect(dx + 0.5, dy + 0.5, dw - 1, dh - 1, 20, 'none', { stroke: T.border });
  let tx = x0;
  if (c.app) { s += appIconArt(x0, dy + 28, 40, APPS[c.app], T); tx += 54; }
  s += text(tx, dy + 30 + head / 2 + 7, c.title, { size: 20, weight: 700, fill: T.text });
  s += iconBtn(dx + dw - 44, dy + 30 + head / 2, 'x', T);
  let y = dy + 30 + head + 22;
  s += para(x0, y + 4, iw, c.body, T, { size: 14, lh: 21, fill: T.text }).s;
  y += body.h + 18;
  if (c.warn) {
    s += rect(x0, y, iw, warnH - 16, 11, T.warnSoft);
    s += icon('warn', x0 + 14, y + 12, 16, T.warn, 1.7) + text(x0 + 38, y + 25, c.warn.title, { size: 13, weight: 700, fill: T.text });
    c.warn.lines.forEach((l, i) => { s += text(x0 + 14, y + 48 + i * 19, l, { size: 13, fill: T.text }); });
    s += text(x0 + 14, y + 48 + c.warn.lines.length * 19 + 4, c.warn.note, { size: 12, fill: T.muted });
    y += warnH;
  }
  if (c.list) { s += para(x0, y, iw, c.list, T, { size: 13, lh: 19, fill: T.muted }).s; y += listH; }
  if (c.check) {
    s += checkbox(x0, y, true, T) + text(x0 + 28, y + 14, c.check[0], { size: 13, weight: 700, fill: T.text });
    s += text(x0 + 28, y + 33, c.check[1], { size: 11.5, fill: T.muted, mono: true });
    y += checkH;
  }
  const by = dy + dh - 64;
  const b1 = button(x0 + iw, by, c.action, T, { primary: true, danger: c.danger !== false, anchor: 'end', ic: c.ic || 'trash' });
  s += b1.s;
  let bx = x0 + iw - b1.w - 10;
  if (c.extra) { const b2 = button(bx, by, c.extra[0], T, { anchor: 'end', ic: c.extra[1] }); s += b2.s; bx -= b2.w + 10; }
  s += button(bx, by, 'Cancel', T, { anchor: 'end' }).s;
  return s;
}

// ---------------------------------------------------------------- Source settings (req 2.6.7)
function sourceSettingsDialog(T) {
  let s = sourcesView(T, {}) + scrim(T);
  const dw = 640, dh = 590, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60, right = x0 + iw, a = APPS.localsend;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' }) + rect(dx + 0.5, dy + 0.5, dw - 1, dh - 1, 20, 'none', { stroke: T.border });
  s += appIconArt(x0, dy + 30, 40, a, T);
  s += text(x0 + 54, dy + 44, 'LOCALSEND', { size: 12, weight: 700, fill: T.faint, ls: 0.8 });
  s += text(x0 + 54, dy + 66, 'Source settings', { size: 20, weight: 700, fill: T.text });
  s += iconBtn(dx + dw - 44, dy + 50, 'x', T);
  s += text(x0, dy + 106, 'https://github.com/localsend/localsend', { size: 12, fill: T.muted, mono: true });
  const row = (y, label, hint, ctlW) => {
    let r = text(x0, y + 16, label, { size: 14, weight: 700, fill: T.text });
    if (hint) r += para(x0, y + 34, iw - ctlW - 24, hint, T, { size: 12, lh: 16 }).s;
    return r;
  };
  let y = dy + 128;
  const sel = 'Detect automatically (GitHub)', sw = tw(sel, 12.5, { bold: true }) + 44;
  s += row(y, 'Forge', 'Which API to use for this project. Detection is right for almost every host.', sw);
  s += rect(right - sw, y + 14, sw, 28, 14, T.surface, { stroke: T.border }) + text(right - sw + 12, y + 32.5, sel, { size: 12.5, weight: 700, fill: T.text });
  s += icon('chevDown', right - 22, y + 21, 13, T.muted);
  y += 72;
  s += row(y, 'Track only', 'Follow new versions without offering to install them, for example when a project publishes tags but no files.', 40);
  s += rect(right - 38, y + 20, 38, 22, 11, T.track, { stroke: T.borderStrong }) + `<circle cx="${right - 27}" cy="${y + 31}" r="9" fill="#ffffff"/>`;
  y += 78;
  s += row(y, 'Include pre-releases', 'Beta and release-candidate versions.', 330);
  s += rect(right - 330, y + 10, 330, 32, 9, T.track);
  ['Default (Off)', 'Yes', 'No'].forEach((l, i) => {
    if (i === 0) s += rect(right - 327, y + 13, 108, 26, 7, T.segOn, { filter: 'seg' });
    s += text(right - 327 + i * 108 + 54, y + 30.5, l, { size: 12, weight: 700, fill: i === 0 ? T.text : T.muted, anchor: 'middle' });
  });
  y += 66;
  s += text(x0, y + 16, 'Download filter for Linux x86_64', { size: 14, weight: 700, fill: T.text });
  s += para(x0, y + 36, iw, 'A regular expression for the file name. Leave it empty to let AppKata choose. Other platforms keep their own filter.', T, { size: 12, lh: 16 }).s;
  s += input(x0, y + 68, iw, T, { value: 'linux-x86-64\\.AppImage$', mono: true, h: 38, size: 13, focus: true });
  s += `<circle cx="${x0 + 10}" cy="${y + 128}" r="10" fill="${T.okSoft}"/>` + icon('check', x0 + 4, y + 122, 12, T.ok, 2);
  s += text(x0 + 28, y + 132, 'LocalSend-1.18.2-linux-x86-64.AppImage', { size: 12, fill: T.text, mono: true });
  s += text(x0, y + 156, 'Picked by your filter from the latest release', { size: 11, fill: T.faint });
  const by = dy + dh - 64;
  const sv = button(right, by, 'Save', T, { primary: true, anchor: 'end' });
  s += sv.s + button(right - sv.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  s += text(x0, by + 22, 'Saving checks the project again.', { size: 12, fill: T.faint });
  return s;
}


// ---------------------------------------------------------------- more screens and dialogs
function detailMenu(T) {             // App Detail ⋯ menu (req 5.7.1, 4.9.5)
  let s = appsView(T, { detail: 'localsend' });
  const mw_ = 270, x = W - 28 - 48 - mw_ + 30, y = 100, mh = 186;
  s += iconBtn(W - 28 - 48, 81, 'dots', T, { active: true });
  s += rect(x, y, mw_, mh, 12, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, mw_ - 1, mh - 1, 12, 'none', { stroke: T.border });
  [['pin', 'Pin at 1.16.1', 'No updates until unpinned'], ['gear', 'Install options…', 'AppImage · portable'], ['open', 'Open project page', '']].forEach(([ic, l, n], i) => {
    const ry = y + 8 + i * 58;
    s += `<circle cx="${x + 25}" cy="${ry + 25}" r="15" fill="${T.accentSoft}"/>` + icon(ic, x + 17, ry + 17, 16, T.accent);
    s += text(x + 50, ry + (n ? 22 : 30), l, { size: 14, weight: 700, fill: T.text });
    if (n) s += text(x + 50, ry + 40, n, { size: 12, fill: T.muted });
  });
  return s;
}
function emptyState(T, view) {       // first run (req 6.7, 12.7)
  let s = headerBar(T, view, { badge: 0 });
  const cx = W / 2;
  if (view === 'apps') {
    s += text(32, 98, 'Apps', { size: 28, weight: 700, fill: T.text });
    s += text(cx, 380, 'No apps installed yet', { size: 17, weight: 700, fill: T.text, anchor: 'middle' });
    s += button(cx, 402, 'Browse the Catalog', T, { ic: 'grid', primary: true, anchor: 'middle' }).s;
  } else {
    s += text(32, 98, 'Catalog', { size: 28, weight: 700, fill: T.text });
    s += text(32 + tw('Catalog', 28, { bold: true }) + 14, 97, '0 apps · 0 sources, 0 trusts', { size: 14, fill: T.muted });
    s += logo(cx - 32, 300, 64, T);
    s += text(cx, 400, 'Add a source or a trust to fill your catalog', { size: 17, weight: 700, fill: T.text, anchor: 'middle' });
    s += para(cx - 260, 428, 520, 'A Source is an app you trust yourself: its git project. A Trust is a reviewer’s signed AppKata.md, which lists many apps.', T, { size: 13, lh: 19 }).s;
    const b1 = button(0, 0, 'Add source', T, { ic: 'plus' }), b2 = button(0, 0, 'Add trust', T, { ic: 'shieldCheck' });
    const bx = cx - (b1.w + b2.w + 10) / 2;
    s += button(bx, 480, 'Add source', T, { ic: 'plus', primary: true }).s + button(bx + b1.w + 10, 480, 'Add trust', T, { ic: 'shieldCheck' }).s;
  }
  return s;
}
function toastScene(T, err) {        // short-lived messages (req 5.5)
  let s = appsView(T);
  const msg = err ? 'Signal Desktop: apt-get install failed: dpkg was interrupted' : 'LocalSend 1.17.0 installed.';
  const w = tw(msg, 13, { bold: true }) + 64, x = (W - w) / 2, y = H - 28 - 44;
  s += rect(x, y, w, 44, 12, err ? T.err : T.tipBg, { filter: 'lift' });
  s += icon(err ? 'warn' : 'info', x + 18, y + 14, 16, err ? '#ffffff' : T.tipFg);
  s += text(x + 44, y + 27, msg, { size: 13, weight: 700, fill: err ? '#ffffff' : T.tipFg });
  return s;
}
function addTrustDialog(T) {         // req 7.6.2
  let s = sourcesView(T) + scrim(T);
  const dw = 600, dh = 560, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  s += text(x0, dy + 48, 'Add trust', { size: 20, weight: 700, fill: T.text }) + iconBtn(x0 + iw - 12, dy + 42, 'x', T);
  let y = dy + 76;
  s += text(x0, y + 14, 'Repository or AppKata.md URL', { size: 13, weight: 700, fill: T.muted });
  s += input(x0, y + 24, iw, T, { value: 'https://github.com/kenji-mori/app-reviews', mono: true, h: 42 });
  s += para(x0, y + 86, iw, 'AppKata looks for AppKata.md in the root or docs/ folder. The commit that last changed it must be signed (GPG or SSH).', T, { size: 12, lh: 16, fill: T.faint }).s;
  y += 126;
  s += text(x0, y + 16, 'Kenji’s app reviews', { size: 16, weight: 700, fill: T.text });
  s += text(x0, y + 38, 'AppKata.md · 21 apps · signed commit 8c41f2e', { size: 13, fill: T.muted });
  y += 54;
  s += text(x0, y + 18, 'Score', { size: 13, weight: 700, fill: T.text }) + stars(x0 + 50, y + 13, 3, 7.5, T, { color: T.accent }).s;
  s += text(x0 + 142, y + 18, 'How much its reviews count; change it any time.', { size: 12, fill: T.faint });
  y += 36;
  s += para(x0, y + 12, iw, 'Confirm the signing key. It becomes this Trust’s first Authority; later changes must be signed by an Authority.', T, { size: 13, lh: 18 }).s;
  y += 44;
  [['kj', 'Kenji Mori  <kenji@mori.dev>', 'SSH · SHA256:XC++CL5ElzWIYRbEamaekwKBL/S5MpSV…'], ['ay', 'Aya Mori  <aya@mori.dev>', 'SSH · SHA256:ZOQVEWsRDZA+pt9S0bk2wZJdK3915…']].forEach(([k, n, f], i) => {
    const ry = y + i * 72;
    s += rect(x0, ry, iw, 64, 12, T.input, { stroke: T.border });
    s += avatar(x0 + 29, ry + 32, 17, k, T, { ringColor: T.input });
    s += text(x0 + 60, ry + 27, n, { size: 13, weight: 700, fill: T.text });
    s += text(x0 + 60, ry + 46, f, { size: 11, fill: T.muted, mono: true });
  });
  const by = dy + dh - 62;
  const b = button(x0 + iw, by, 'Trust this signer', T, { primary: true, anchor: 'end', ic: 'shieldCheck' });
  s += b.s + button(x0 + iw - b.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  return s;
}
function syncScene(T) {              // sync in progress, with Cancel (req 9.2)
  let s = catalogView(T, { syncing: true });
  const x = W - 152 - 200, y = 50, w = 260, h = 92;
  s += rect(x, y, w, h, 12, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, w - 1, h - 1, 12, 'none', { stroke: T.border });
  s += text(x + 14, y + 26, 'Syncing github.com/syncthing/syncthing', { size: 13, fill: T.text });
  s += button(x + 14, y + 42, 'Cancel', T).s;
  return s;
}
function reviewFileScene(T) {        // first review: choose where AppKata.md goes (req 8.2)
  let s = appsView(T, { detail: 'localsend' }) + scrim(T);
  // the system's save dialog (GTK on Linux), drawn neutrally
  const dw = 760, dh = 470, dx = (W - dw) / 2, dy = (H - dh) / 2, bg = T.dark ? '#24262c' : '#fafafa', side = T.dark ? '#1d1f24' : '#efefef';
  s += rect(dx, dy, dw, dh, 12, bg, { filter: 'lift' }) + rect(dx + 0.5, dy + 0.5, dw - 1, dh - 1, 12, 'none', { stroke: T.border });
  s += text(dx + dw / 2, dy + 28, 'Where should your AppKata.md go?', { size: 14, weight: 700, fill: T.text, anchor: 'middle' });
  s += button(dx + 14, dy + 12, 'Cancel', T, { h: 30, size: 12.5 }).s + button(dx + dw - 14, dy + 12, 'Save', T, { primary: true, anchor: 'end', h: 30, size: 12.5 }).s;
  s += hline(dx, dx + dw, dy + 54.5, T.border);
  s += text(dx + 20, dy + 82, 'Name', { size: 13, fill: T.muted }) + input(dx + 70, dy + 64, 300, T, { value: 'AppKata.md', h: 30, size: 13, focus: true });
  s += rect(dx, dy + 106, 180, dh - 106, 0, side);
  ['Home', 'Documents', 'Downloads', 'src'].forEach((l, i) => {
    if (i === 0) s += rect(dx + 8, dy + 116 + i * 34, 164, 30, 7, T.accentSoft);
    s += icon('folder', dx + 18, dy + 123 + i * 34, 15, i === 0 ? T.accent : T.muted);
    s += text(dx + 42, dy + 136 + i * 34, l, { size: 13, fill: i === 0 ? T.accent : T.text, weight: i === 0 ? 700 : 400 });
  });
  ['bin', 'Desktop', 'Documents', 'Downloads', 'Music', 'Pictures', 'src'].forEach((l, i) => {
    s += icon('folder', dx + 200, dy + 122 + i * 32, 15, T.muted) + text(dx + 224, dy + 135 + i * 32, l, { size: 13, fill: T.text });
    s += text(dx + dw - 20, dy + 135 + i * 32, ['Oct 1', 'Sep 30', 'Sep 28', 'Oct 2', 'Jul 4', 'Sep 12', 'Oct 2'][i], { size: 12, fill: T.faint, anchor: 'end' });
  });
  s += text(dx + 200, dy + dh - 18, 'The first review asks once; change it later in Settings → Reviews.', { size: 11.5, fill: T.faint });
  return s;
}
function exeChoiceDialog(T) {        // Windows: an .exe AppKata couldn't classify (req 4.2.1, 4.9.2)
  let s = catalogView(T, { detail: 'kdenlive' }) + scrim(T);
  const dw = 680, dh = 360, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60, a = APPS.kdenlive;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  s += appIconArt(x0, dy + 28, 40, a, T) + text(x0 + 54, dy + 55, 'Install Kdenlive 25.08.1', { size: 20, weight: 700, fill: T.text });
  s += iconBtn(x0 + iw - 12, dy + 48, 'x', T);
  let y = dy + 92;
  s += text(x0, y + 22, 'AppKata couldn’t tell whether this download is a portable program or an installer.', { size: 14, fill: T.text });
  y += 44;
  s += rect(x0, y, iw, 76, 12, T.accentSoft, { stroke: T.accent, sw: 2 });
  s += `<circle cx="${x0 + 26}" cy="${y + 38}" r="10" fill="${T.accent}"/><circle cx="${x0 + 26}" cy="${y + 38}" r="4" fill="#ffffff"/>`;
  s += text(x0 + 50, y + 24, '.exe', { size: 14, weight: 700, fill: T.text });
  s += pill(x0 + 50 + tw('.exe', 14, { bold: true }) + 8, y + 11, 'Not sure', { bg: T.warnSoft, fg: T.warn, size: 10.5, h: 18 }).s;
  s += text(x0 + 50, y + 44, 'A Windows program: either portable or an installer.', { size: 12, fill: T.muted });
  s += text(x0 + 50, y + 62, 'kdenlive-25.08.1.exe', { size: 11, fill: T.faint, mono: true }) + text(x0 + iw - 16, y + 42, '118 MB', { size: 12, fill: T.faint, anchor: 'end' });
  y += 96;
  s += text(x0, y + 20, 'This file is', { size: 13, fill: T.text });
  const p1 = pill(x0 + 86, y + 5, 'A portable program', { bg: T.surface, fg: T.text, stroke: T.border, size: 12, h: 30 });
  s += p1.s + pill(x0 + 96 + p1.w, y + 5, 'An installer', { bg: T.accentSoft, fg: T.accent, stroke: T.accent, size: 12, h: 30 }).s;
  const by = dy + dh - 62;
  const b = button(x0 + iw, by, 'Install', T, { primary: true, anchor: 'end', ic: 'download' });
  s += b.s + button(x0 + iw - b.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  s += text(x0, by + 22, 'Install stays disabled until you pick one. Shown on Windows only.', { size: 12, fill: T.faint });
  return s;
}
function macMenuBar(T) {             // macOS: the menu-bar extra and a notification (req 1.7)
  const g = linGrad([[0, T.dark ? '#1e2a4a' : '#bfdbfe'], [1, T.dark ? '#3a2350' : '#e9d5ff']], 1, 1);
  let s = rect(0, 0, W, H, 0, `url(#${g})`);
  s += rect(0, 0, W, 28, 0, T.dark ? '#16181f' : '#f5f5f7', { op: 0.85 });
  s += text(20, 19, '', { size: 14, fill: T.text }) + text(44, 19, 'Finder', { size: 13, weight: 700, fill: T.text });
  let mx = 104;
  ['File', 'Edit', 'View', 'Go', 'Window', 'Help'].forEach(l => { s += text(mx, 19, l, { size: 13, fill: T.text }); mx += tw(l, 13) + 22; });
  s += text(W - 18, 19, 'Thu 2 Oct  14:05', { size: 13, fill: T.text, anchor: 'end' });
  const tx = W - 210;
  s += rect(tx - 6, 3, 28, 22, 5, T.dark ? '#ffffff' : '#000000', { op: 0.12 }) + logo(tx, 5, 18, T);
  s += `<circle cx="${tx + 19}" cy="8" r="4" fill="${T.accent}"/>`;
  const mw_ = 260, x = Math.min(tx - 6, W - 12 - mw_), y = 32, mh = 166;
  s += rect(x, y, mw_, mh, 10, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, mw_ - 1, mh - 1, 10, 'none', { stroke: T.border });
  s += text(x + 14, y + 24, 'AppKata · Last checked 14:00', { size: 12, fill: T.muted });
  s += rect(x + 5, y + 34, mw_ - 10, 28, 6, T.accent) + text(x + 14, y + 53, '3 updates available', { size: 13, weight: 700, fill: '#ffffff' });
  s += text(x + 14, y + 84, 'Open AppKata', { size: 13, fill: T.text }) + text(x + 14, y + 112, 'Check for updates', { size: 13, fill: T.text });
  s += hline(x + 10, x + mw_ - 10, y + 128.5, T.border);
  s += text(x + 14, y + 152, 'Quit AppKata', { size: 13, fill: T.text }) + text(x + mw_ - 14, y + 152, '⌘Q', { size: 13, fill: T.faint, anchor: 'end' });
  const nx = W - 380, ny = 44 + 200;
  s += rect(nx, ny, 360, 78, 16, T.raised, { filter: 'lift', op: 0.97 }) + rect(nx + 0.5, ny + 0.5, 359, 77, 16, 'none', { stroke: T.border });
  s += logo(nx + 14, ny + 18, 40, T);
  s += text(nx + 66, ny + 32, 'AppKata', { size: 13, weight: 700, fill: T.text }) + text(nx + 344, ny + 32, 'now', { size: 11.5, fill: T.faint, anchor: 'end' });
  s += text(nx + 66, ny + 52, '3 app updates: LocalSend, Signal Desktop, Zettlr', { size: 12.5, fill: T.muted });
  // dock
  s += rect(W / 2 - 220, H - 78, 440, 66, 18, T.dark ? '#ffffff' : '#ffffff', { op: T.dark ? 0.12 : 0.45 });
  ['localsend', 'keepassxc', 'syncthing', 'krita', 'obs'].forEach((k, i) => { s += appIconArt(W / 2 - 200 + i * 62, H - 68, 46, APPS[k], T); });
  s += logo(W / 2 - 200 + 5 * 62, H - 68, 46, T) + `<circle cx="${W / 2 - 177 + 5 * 62}" cy="${H - 16}" r="2.5" fill="${T.text}"/>`;
  return s;
}
const SOURCE_ERRORS = [       // Source errors on their rows (req 2.10)
  { key: 'joplin', chips: [['Track only', 'muted']], err: 'Moved to github.com/laurent22/joplin-app', errIc: 'info', action: 'Update URL' },
  { key: 'kdenlive', chips: [], err: 'Rate limited until 14:32 · add a GitLab token in Settings' },
  { key: 'tenacity', chips: [], err: 'No download for Linux x86_64', errIc: 'warn' },
  { key: 'flameshot', chips: [['Installed', 'ok']], err: 'Couldn’t reach the host', errIc: 'warn' },
  { key: 'krita', chips: [], err: 'Couldn’t read a version', errIc: 'warn' },
  { key: 'localsend', chips: [['Installed', 'ok']] },
];

// ---------------------------------------------------------------- AppKata.md settings stanza (req 10.3.1)
function settingsStanza(T, v = '') {
  // not an AppKata screen: the file a reviewer writes, open in a text editor (req 10.1, 10.3)
  const ed = T.dark ? '#16181f' : '#fbfbfd', gutter = T.dark ? '#1c1f27' : '#f1f2f6';
  let s = rect(0, 0, W, H, 0, ed);
  s += rect(0, 0, W, 44, 0, T.dark ? '#1f222b' : '#eceef3') + hline(0, W, 44.5, T.border);
  ['#f87171', '#fbbf24', '#34d399'].forEach((c, i) => { s += `<circle cx="${22 + i * 18}" cy="22" r="6" fill="${c}"/>`; });
  s += text(W / 2, 27, 'AppKata.md — ~/src/reviews', { size: 13, weight: 700, fill: T.muted, anchor: 'middle' });
  const FS = 12.5, mono = { mono: true, size: FS }, lh = 21, x0 = 70, top = 72;
  const code = T.dark ? '#c4b5fd' : '#6d28d9', head = T.accent, key = T.text, val = T.dark ? '#86efac' : '#15803d', no = T.dark ? '#fda4af' : '#be123c';
  const plat = T.dark ? '#fbbf24' : '#b45309', dim = T.muted;
  const opt = (k, v, c = val, p) => [['- ', dim], [k, key], ...(p ? [[` (${p})`, plat]] : []), [': ', dim], [v, c]];
  let L = [
    [['| App | Source | Tags | Trust | Rating |', dim]],
    [['|---|---|---|---|---|', dim]],
    [['| Zettlr | https://github.com/Zettlr/Zettlr | foss | 5 | 4 |', dim]],
    [],
    [['# Zettlr', head, true]],
    [],
    [['Good Markdown editor for long texts; citations work with Zotero.', T.text]],
    [],
    [['## Zettlr::Settings', head, true]],
    opt('Trust', '4'), opt('Rating', '4'), opt('Tags', 'foss'),
    opt('App menu', 'yes'),
    opt('Download filter', '`x86_64\\.AppImage$`', code, 'linux'),
    opt('Auto update', 'no', no, 'linux'), opt('Auto update', 'yes', val, 'windows'),
    opt('Flatpak', 'com.zettlr.Zettlr'), opt('Channel', 'flatpak'),
    [],
    [['## Zettlr[3.5.1]', head, true]],
    [],
    [['3.5 fixed the citation lag; I use it every day now.', T.text]],
    [],
    [['### Zettlr[3.5.1]::Details', head, true]],
    opt('Date', '2026-09-02', T.text), opt('Platform', 'linux x86_64', T.text), opt('Channel', 'GitHub release', T.text),
    opt('File', 'Zettlr-3.5.1-x86_64.AppImage', T.text), opt('SHA-256', '4f0c…9a1e', T.text),
    [],
    [['### Zettlr[3.5.1]::Settings', head, true]],
    opt('Trust', '5'), opt('Auto update', 'yes', val, 'linux'),
  ];
  let notes = [
    [0, 2, 'The table: the newest review', 'Trust, Rating and Tags for the latest version; it wins if the newest Settings disagree (10.3.3)'],
    [8, 18, 'The review of the app as a whole', 'Before the first version: its Trust, Rating and Tags, the install options, channels and the recommended channel (10.3.1, 16.1)'],
    [20, 23, 'A review of 3.5.1', 'Holds for 3.5.1 and later, until a newer review. Upstream versions only (10.3)'],
    [24, 29, 'Details', 'Optional: what the reviewer had installed (10.3.4, 8.4.5.1)'],
    [31, 33, 'Settings for 3.5.1 on', 'Only what changed; Rating, Tags and the other options carry forward (10.3)'],
  ];
  let foot = 'Track only and pre-releases are personal settings, so they aren’t in any Settings.';
  if (v === 'sandbox') {         // the sandbox a reviewer suggests (app-sandboxing.md)
    L = [
      [['| App | Source | Tags | Trust | Rating |', dim]],
      [['|---|---|---|---|---|', dim]],
      [['| Zettlr | https://github.com/Zettlr/Zettlr | foss | 4 | 4 |', dim]],
      [],
      [['# Zettlr', head, true]],
      [],
      [['Good Markdown editor for long texts; citations work with Zotero.', T.text]],
      [],
      [['## Zettlr::Settings', head, true]],
      opt('Trust', '4'), opt('Rating', '4'), opt('Tags', 'foss'),
      opt('Download filter', '`x86_64\\.AppImage$`', code, 'linux'),
      opt('Sandbox', 'offline-editor', val, 'linux'),
      opt('Sandbox folders', '+~/Zettlr', val, 'linux'),
      [],
      [['## Zettlr[3.6.0]', head, true]],
      [],
      [['3.6 checks grammar with LanguageTool, which needs the network.', T.text]],
      [],
      [['### Zettlr[3.6.0]::Settings', head, true]],
      opt('Sandbox network', 'yes', val, 'linux'),
      opt('Sandbox folders', '+~/Pictures', val, 'linux'),
    ];
    notes = [
      [8, 12, 'The review of the app as a whole', 'Trust, Rating, Tags and install options, as before (10.3.1)'],
      [13, 15, 'A template + an override', 'A built-in template by name, then just what differs (an extra folder). AppKata ships the templates; several Trusts → the strictest, and only what they all allow'],
      [16, 19, 'A review of 3.6.0', 'Why this version needs more'],
      [20, 23, 'More access from 3.6.0 on', 'A standing review badge; your grants are kept until you review'],
    ];
    foot = 'Suggestions only: what you choose for an app in AppKata always wins.';
  }
  s += rect(0, 45, 52, H - 45, 0, gutter);
  L.forEach((parts, i) => {
    const y = top + i * lh;
    s += text(38, y, String(i + 1), { size: 11.5, fill: T.faint, mono: true, anchor: 'end' });
    let x = x0;
    parts.forEach(([t, c, b]) => { s += text(x, y, t.replace(/ /g, ' '), { ...mono, fill: c, weight: b ? 700 : 400 }); x += tw(t, FS, { mono: true, bold: !!b }); });
  });
  // notes beside the file
  const nx = 640;
  notes.forEach(([r0, r1, t, d]) => {
    const y = top + r0 * lh - 16, h = Math.max(54, (r1 - r0) * lh + 8);
    s += `<path d="M${nx - 14},${y + 4}V${y + h - 4}" stroke="${T.accent}" stroke-width="2" opacity="0.6"/>`;
    s += rect(nx, y, W - nx - 28, Math.min(h, 62), 11, T.surface, { stroke: T.border });
    s += text(nx + 14, y + 22, t, { size: 13, weight: 700, fill: T.text });
    s += para(nx + 14, y + 41, W - nx - 56, d, T, { size: 11.5, lh: 14, max: 2 }).s;
  });
  s += text(x0, top + L.length * lh + 6, foot, { size: 12, fill: T.faint });
  return s;
}

// ---------------------------------------------------------------- tray (req 1.7)
function trayScene(T) {
  // desktop with a top panel and the tray menu, the window closed
  const g = linGrad([[0, T.dark ? '#1b1f3a' : '#c7d2fe'], [1, T.dark ? '#3b1d4a' : '#fbcfe8']], 1, 1);
  let s = rect(0, 0, W, H, 0, `url(#${g})`);
  s += `<circle cx="${W * 0.2}" cy="${H * 0.85}" r="380" fill="#ffffff" opacity="0.05"/><circle cx="${W * 0.85}" cy="${H * 0.25}" r="260" fill="#ffffff" opacity="0.06"/>`;
  s += rect(0, 0, W, 34, 0, T.dark ? '#0d0f15' : '#1b1f2b', { op: 0.92 });
  s += text(W / 2, 22, 'Wed Oct 1  14:05', { size: 13, weight: 700, fill: '#eceef4', anchor: 'middle' });
  s += text(18, 22, 'Activities', { size: 13, weight: 700, fill: '#eceef4' });
  // tray icons
  const tx = W - 150;
  s += icon('globe', tx + 60, 9, 16, '#eceef4') + icon('power', tx + 94, 9, 16, '#eceef4');
  s += rect(tx + 14, 4, 28, 26, 7, '#ffffff', { op: 0.16 });
  s += logo(tx + 18, 7, 20, T);
  s += `<circle cx="${tx + 38}" cy="10" r="5" fill="${T.accent}" stroke="#0d0f15" stroke-width="1.5"/>`;
  // menu
  const mw_ = 280, x = tx + 28 - mw_ + 40, y = 40, mh = 214;
  s += rect(x, y, mw_, mh, 14, T.raised, { filter: 'lift' }) + rect(x + 0.5, y + 0.5, mw_ - 1, mh - 1, 14, 'none', { stroke: T.border });
  s += logo(x + 16, y + 14, 26, T);
  s += text(x + 52, y + 28, 'AppKata', { size: 14, weight: 700, fill: T.text });
  s += text(x + 52, y + 44, 'Last checked 14:00', { size: 11.5, fill: T.muted });
  s += hline(x + 12, x + mw_ - 12, y + 56.5, T.border);
  s += rect(x + 6, y + 62, mw_ - 12, 38, 9, T.accentSoft);
  s += icon('update', x + 18, y + 73, 16, T.accent);
  s += text(x + 46, y + 86, '3 updates available', { size: 13.5, weight: 700, fill: T.accent });
  s += icon('window', x + 18, y + 113, 16, T.muted);
  s += text(x + 46, y + 126, 'Open AppKata', { size: 13.5, weight: 700, fill: T.text });
  s += icon('sync', x + 18, y + 147, 16, T.muted);
  s += text(x + 46, y + 160, 'Check for updates', { size: 13.5, weight: 700, fill: T.text });
  s += hline(x + 12, x + mw_ - 12, y + 176.5, T.border);
  s += icon('power', x + 18, y + 186, 16, T.err);
  s += text(x + 46, y + 199, 'Quit AppKata', { size: 13.5, weight: 700, fill: T.err });
  // notification
  const nx = W - 400, ny = H - 130;
  s += rect(nx, ny, 370, 96, 16, T.raised, { filter: 'lift' }) + rect(nx + 0.5, ny + 0.5, 369, 95, 16, 'none', { stroke: T.border });
  s += logo(nx + 18, ny + 20, 34, T);
  s += text(nx + 66, ny + 34, '3 app updates available', { size: 14, weight: 700, fill: T.text });
  s += text(nx + 66, ny + 54, 'LocalSend, Signal Desktop and Zettlr', { size: 12.5, fill: T.muted });
  s += text(nx + 66, ny + 76, 'Open Apps', { size: 12.5, weight: 700, fill: T.accent });
  return s;
}


// ---------------------------------------------------------------- Audit (req 13)
const AUDIT = [
  ['Today', [
    ['you', 'app', 'apps', 'You installed', 'KeePassXC', [['version', '2.7.10'], ['file', 'KeePassXC-2.7.10-x86_64.AppImage']], 'github.com/keepassxreboot/keepassxc', '09:41:07'],
    ['you', 'app', 'apps', 'You updated', 'LocalSend', [['version', '1.17.0'], ['from', '1.16.1']], 'github.com/localsend/localsend', '09:30:52'],
    ['sync', 'trust', 'shieldCheck', 'Sync applied signed changes from', 'mara-dev / foss-picks', [['commit', 'c41e7d3'], ['apps', '38']], 'github.com/mara-dev/foss-picks', '07:00:12']]],
  ['Yesterday', [
    ['sync', 'trust', 'shieldCheck', 'Sync refused a change to', 'desk-collective / reviews', [['reason', 'unknown-signer']], '', '07:00:09'],
    ['sync', 'authority', 'key', 'Sync found a new signer,', 'nadia@desk.coop', [['trust', 'desk-collective / reviews'], ['changes', '3']], '', '07:00:09'],
    ['you', 'review', 'pencil', 'You reviewed', 'LocalSend', [['trust', '4'], ['rating', '5'], ['commit', 'c41e7d3'], ['signed', 'true'], ['pushed', 'true']], 'github.com/localsend/localsend', '19:45:17']]],
  ['Monday, September 28, 2026', [
    ['you', 'app', 'apps', 'You pinned', 'Ventoy', [['version', '1.0.99']], 'github.com/ventoy/Ventoy', '12:30:02'],
    ['you', 'authority', 'key', 'You disabled', 'Ade Bello', [['trust', 'desk-collective / reviews']], '', '14:22:40']]],
];
function auditView(T, days = AUDIT) {
  let s = headerBar(T, 'audit');
  const x = 32, w = W - 64;
  s += text(x, 98, 'Audit', { size: 28, weight: 700, fill: T.text });
  s += text(x + tw('Audit', 28, { bold: true }) + 14, 97, '214 entries · newest first', { size: 14, fill: T.muted });
  s += input(W - 32 - 260, 72, 260, T, { ic: 'filter', placeholder: 'Filter by app, trust, key…', h: 38 });
  let cx = x;
  ['All', 'Apps', 'Sources', 'Trusts', 'Authorities', 'Reviews', 'Settings'].forEach((t, i) => {
    const p = pill(cx, 128, t, { bg: i === 0 ? T.accentSoft : T.surface, fg: i === 0 ? T.accent : T.muted, stroke: i === 0 ? T.accent : T.border, size: 12, h: 28 });
    s += p.s; cx += p.w + 8;
  });
  let y = 176;
  for (const [day, rows] of days) {
    if (y > H) break;
    s += text(x, y + 10, day.toUpperCase(), { size: 11, weight: 700, fill: T.faint, ls: 1.2 });
    y += 22;
    for (const [actor, kind, ic, verb, subject, details, url, time] of rows) {
      if (y > H) break;
      s += rect(x, y, w, 64, 12, T.surface, { stroke: T.border });
      s += `<circle cx="${x + 29}" cy="${y + 28}" r="15" fill="${actor === 'sync' ? T.track : T.accentSoft}"/>`;
      s += icon(ic, x + 21.5, y + 20.5, 15, actor === 'sync' ? T.muted : T.accent);
      s += text(x + 58, y + 26, verb + ' ', { size: 14, fill: T.text });
      s += text(x + 58 + tw(verb + ' ', 14), y + 26, subject, { size: 14, weight: 700, fill: T.text });
      let dx = x + 58;
      for (const [k, v] of details) {
        const lab = `${k} ${v}`, dw = tw(lab, 11, { mono: true }) + 16;
        s += rect(dx, y + 36, dw, 20, 6, T.input, { stroke: T.border });
        s += text(dx + 8, y + 50, lab, { size: 11, fill: T.muted, mono: true });
        dx += dw + 6;
      }
      if (url) s += text(dx + 2, y + 50, url, { size: 11, fill: T.faint, mono: true });
      s += pill(x + w - 92, y + 16, actor === 'sync' ? 'Sync' : 'You', { bg: actor === 'sync' ? T.track : T.accentSoft, fg: actor === 'sync' ? T.muted : T.accent, anchor: 'end', size: 11, h: 20 }).s;
      s += text(x + w - 16, y + 30, time, { size: 12, fill: T.faint, mono: true, anchor: 'end' });
      y += 70;
    }
    y += 14;
  }
  return s;
}

// ---------------------------------------------------------------- Explore (req 7.7)
const EXPLORE = [
  ['keepassxreboot', 'keepassxc', 'KeePassXC is a cross-platform community-driven port of the Windows application “KeePass Password Safe”.', '25.1k', 'C++', '2 days ago', 'source'],
  ['bitwarden', 'clients', 'Bitwarden client apps (web, browser extension, desktop, and cli).', '10.4k', 'TypeScript', '5 hours ago', ''],
  ['keeweb', 'keeweb', 'Free cross-platform password manager compatible with KeePass', '13.0k', 'HTML', '147 days ago', 'archived'],
  ['authpass', 'authpass', 'Password Manager based on Flutter for all platforms. KeePass 2.x (kdbx 3.x) compatible.', '1.8k', 'Dart', '3 months ago', 'trusts'],
  ['passbolt', 'passbolt_api', 'Passbolt Community Edition (CE) API. The JSON API for the open source password manager.', '5.2k', 'PHP', '4 days ago', ''],
];
function exploreDialog(T) {
  let s = sourcesView(T, {});
  s += scrim(T);
  const dw = 760, dh = 640, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  s += text(x0, dy + 46, 'Explore', { size: 21, weight: 700, fill: T.text });
  s += iconBtn(x0 + iw - 12, dy + 39, 'x', T);
  let y = dy + 76;
  const sw = 420, segW = (sw - 6) / 4;
  s += rect(x0, y, sw, 34, 10, T.track);
  ['GitHub', 'GitLab', 'Codeberg', 'ngit'].forEach((l, i) => {
    if (i === 0) s += rect(x0 + 3, y + 3, segW, 28, 8, T.segOn, { filter: 'seg' });
    s += text(x0 + 3 + i * segW + segW / 2, y + 22, l, { size: 13, weight: 700, fill: i === 0 ? T.text : T.muted, anchor: 'middle' });
  });
  y += 50;
  s += input(x0, y, iw - 90, T, { ic: 'search', value: 'password manager', focus: true, h: 40 });
  s += button(x0 + iw, y + 3, 'Search', T, { primary: true, anchor: 'end' }).s;
  y += 56;
  EXPLORE.forEach(([owner, name, desc, stars, lang, upd, flag], row) => {
    s += rect(x0, y, iw, 74, 12, T.input, { stroke: T.border });
    s += text(x0 + 14, y + 24, owner + ' / ', { size: 14, fill: T.muted });
    const nx = x0 + 14 + tw(owner + ' / ', 14);
    s += text(nx, y + 24, name, { size: 14, weight: 700, fill: T.text });
    const cx = nx + tw(name, 14, { bold: true }) + 8;
    if (flag === 'archived') s += pill(cx, y + 11, 'Archived', { bg: T.track, fg: T.muted, size: 10.5, h: 18 }).s;
    if (flag === 'trusts') s += pill(cx, y + 11, 'In your trusts', { bg: T.accentSoft, fg: T.accent, size: 10.5, h: 18 }).s;
    const dl = wrap(desc, iw - 120, 12, 1);
    s += text(x0 + 14, y + 44, dl[0], { size: 12, fill: T.muted });
    s += icon('star', x0 + 14, y + 52, 12, T.star);
    s += text(x0 + 30, y + 62, `${stars}   ${lang}   updated ${upd}`, { size: 11, fill: T.faint });
    // icon-only actions, labelled by tooltips (req 7.7.3)
    const added = flag === 'source', bx = x0 + iw - 12 - 32, by = y + 21;
    s += added ? rect(bx, by, 32, 32, 9, T.track) + icon('check', bx + 8, by + 8, 16, T.faint)
               : rect(bx, by, 32, 32, 9, T.accent) + icon('plus', bx + 8, by + 8, 16, '#ffffff');
    s += rect(bx - 40, by, 32, 32, 9, T.surface, { stroke: T.border }) + icon('open', bx - 32, by + 8, 16, T.muted);
    if (row === 1) {
      const lab = 'Add source', tw_ = tw(lab, 12, { bold: true }) + 20;
      s += rect(bx - 48 - tw_, by + 3, tw_, 26, 7, T.tipBg) + text(bx - 48 - tw_ / 2, by + 20.5, lab, { size: 12, weight: 700, fill: T.tipFg, anchor: 'middle' });
      s += cursor(bx + 18, by + 18);
    }
    y += 82;
  });
  s += button(x0 + iw, dy + dh - 58, 'Close', T, { anchor: 'end' }).s;
  return s;
}

// ---------------------------------------------------------------- App Detail: versions (req 5.7.5)
const ZETTLR_VERSIONS = [['3.6.0', 'Sep 22, 2026', 'newest'], ['3.5.1', 'Aug 30, 2026', 'installed'], ['3.5.0', 'Aug 11, 2026', 'kept'],
  ['3.4.4', 'Jul 2, 2026', 'kept'], ['3.4.3', 'Jun 14, 2026'], ['3.4.2', 'May 28, 2026'], ['3.4.1', 'May 3, 2026']];
function versionsDetail(T) {
  let s = appsView(T, { detail: 'zettlr' });
  const px = W - PANEL_W, x0 = px + 28, pw = PANEL_W - 56;
  // the panel, scrolled down to Versions
  s += rect(px, 53, PANEL_W, H - 53, 0, T.surface) + `<path d="M${px + 0.5},53 V${H}" stroke="${T.border}"/>`;
  s += text(x0, 86, 'APP DETAILS', { size: 11, weight: 700, fill: T.faint, ls: 1.2 });
  s += iconBtn(x0 + pw - 12, 81, 'x', T) + iconBtn(x0 + pw - 48, 81, 'dots', T) + iconBtn(x0 + pw - 84, 81, 'pencil', T);
  s += rect(px + PANEL_W - 14, 120, 5, 120, 2.5, T.borderStrong);           // the scroll bar
  let y = 120;
  s += text(x0, y + 4, 'Versions', { size: 14, weight: 700, fill: T.text });
  s += icon('play', x0 + pw - 140, y - 5, 10, T.ok) + text(x0 + pw - 126, y + 3, 'installed', { size: 11, fill: T.faint });
  s += icon('star', x0 + pw - 62, y - 6, 11, T.star) + text(x0 + pw - 47, y + 3, 'newest', { size: 11, fill: T.faint });
  y += 16;
  const rows = ZETTLR_VERSIONS;
  s += rect(x0, y, pw, rows.length * 38 + 8 + 34, 12, T.input);
  rows.forEach(([v, d, flag], i) => {
    const ry = y + 4 + i * 38, mine = flag === 'installed', top = flag === 'newest';
    if (mine) s += rect(x0 + 2, ry, pw - 4, 36, 9, T.okSoft);
    if (mine) s += icon('play', x0 + 12, ry + 13, 10, T.ok);
    s += text(x0 + 30, ry + 23, v, { size: 13, weight: mine || top ? 700 : 400, fill: mine ? T.ok : T.text, mono: true });
    if (top) s += icon('star', x0 + 30 + tw(v, 13, { mono: true, bold: true }) + 8, ry + 11, 13, T.star);
    if (flag === 'kept') s += pill(x0 + 30 + tw(v, 13, { mono: true }) + 8, ry + 9, 'Kept', { bg: T.track, fg: T.muted, size: 10, h: 18 }).s;
    s += text(x0 + pw - 86, ry + 23, d, { size: 12, fill: T.faint, anchor: 'end' });
    if (mine) s += text(x0 + pw - 14, ry + 23, 'Installed', { size: 12, weight: 700, fill: T.ok, anchor: 'end' });
    else {      // icon-only, labelled by tooltips (req 5.7.5.1)
      const kept = flag === 'kept';
      s += tipBtn(x0 + pw - (kept ? 72 : 38), ry + 4, top ? 'update' : 'download', T, { accent: top, size: 28 });
      if (kept) s += tipBtn(x0 + pw - 38, ry + 4, 'trash', T, { danger: true, size: 28 });
      if (i === 2) s += tipLeft(x0 + pw - 78, ry + 18, 'Remove this version', T) + cursor(x0 + pw - 24, ry + 20);
    }
  });
  s += text(x0 + 30, y + 4 + rows.length * 38 + 21, 'Show next 5 older', { size: 12, weight: 700, fill: T.accent });
  y += rows.length * 38 + 8 + 34 + 18;
  s += text(x0, y, 'Installing an older version pins it there. Kept versions reinstall without downloading.', { size: 11, fill: T.faint });
  y += 28;
  s += text(x0, y + 4, 'Reviews', { size: 14, weight: 700, fill: T.text });
  s += trustBadge(x0 + pw - 150, y - 1, APPS.zettlr, T).s;
  y += 18;
  s += rect(x0, y, pw, 50, 11, T.input);
  s += avatar(x0 + 21, y + 25, 11, 'mara', T, { ringColor: T.input });
  s += text(x0 + 104, y + 21, 'mara-dev / foss-picks', { size: 12.5, weight: 700, fill: T.accent });
  s += chip(x0 + 104, y + 28, 'foss', T, { size: 10, h: 17 }).s;
  s += icon('shield', x0 + pw - 150, y + 17, 15, T.ok, 1.6) + text(x0 + pw - 131, y + 29, '4', { size: 12.5, weight: 700, fill: T.text });
  s += stars(x0 + pw - 84, y + 25, 4, 4.6, T).s;
  return s;
}


// ---------------------------------------------------------------- Settings (req 11)
const SETTINGS = [
  ['section', 'GENERAL'],
  ['seg', 'Theme', '', ['Match system', 'Dark', 'Light']],
  ['toggle', 'Start in the tray at login', 'Keeps checking for updates; closing the window always leaves AppKata in the tray.', false],
  ['toggle', 'Open appkata:// links', 'A “Get it on AppKata” link opens Add source with the project filled in.', true],
  ['section', 'REVIEWS'],
  ['path', 'Your AppKata.md', 'Where your reviews are saved.', '~/src/reviews/AppKata.md'],
  ['toggle', 'Commit reviews automatically', 'When the file is in a git repository.', true],
  ['toggle', 'Push reviews automatically', 'Only signed commits are pushed.', true],
  ['section', 'UPDATES'],
  ['select', 'Check for updates', '', 'Every 6 hours'],
  ['toggle', 'Notify me about updates', '', true],
  ['toggle', 'Include prereleases', 'For apps without their own setting.', false],
  ['days', 'Minimum age', 'Offer a release only once it’s this old. Applies to every app.', '20'],
  ['section', 'PORTABLE APPS', 'portable'],
  ['note', 'AppImages, tarballs and other apps that run without installing. Changes apply to new installs and updates; apps already installed stay where they are.'],
  ['path', 'Install folder', 'Each app gets a folder here, with its versions side by side.', '~/bin/apps'],
  ['toggle', 'Add to the app menu', 'A launcher entry for each app.', true],
  ['toggle', 'Stable name for the current version', 'LocalSend.AppImage → LocalSend-1.18.2-x86_64.AppImage, so launchers and links survive updates.', true],
  ['toggle', 'Command links', 'A short command per app (e.g. localsend) in a folder on your PATH.', true],
  ['path', 'Command links folder', '', '~/bin'],
  ['days', 'Keep older versions', 'Kept versions reinstall instantly from the App Detail panel; remove them there.', '2', 'per app'],
  ['section', 'ACCOUNTS AND TOKENS', 'accounts'],
  ['note', 'A token raises a forge’s rate limit (GitHub allows 60 requests an hour without one). Tokens are only sent to their own host and are never exported.'],
  ['token', 'github.com', '••••x7Qe'],
  ['addtoken'],
  ['section', 'NOSTR RELAYS'],
  ['relay', 'wss://relay.ngit.dev'], ['relay', 'wss://nos.lol'], ['relay', 'wss://relay.damus.io'],
  ['addrelay'],
  ['section', 'DATA', 'data'],
  ['info', 'Database', 'Sources, Trusts, the Audit and the cache.', '~/.local/share/appkata/appkata.db', ['Open folder']],
  ['info', 'App log', 'AppKata.log and AppKata-prev.log, 2 MB each.', '~/.local/state/appkata', ['Show', 'Open folder']],
  ['info', 'Import and export', 'Sources, Trusts with their Authorities, and settings, as JSON. Import also takes a list of URLs.', '', ['Import…', 'Export…']],
];
// Windows (req 11.1.4, 15.4, 15.6): who apps are for, two install folders, Start menu, .cmd links
const SETTINGS_WIN = SETTINGS.flatMap(r =>
  r[1] === 'Your AppKata.md' ? [['path', r[1], r[2], 'C:\\Users\\you\\src\\reviews\\AppKata.md']]
  : r[0] === 'note' && r[1].startsWith('AppImages') ? [['note', 'Portable .zip and .exe apps, which run without installing. Changes apply to new installs and updates; apps already installed stay where they are.'],
    ['select', 'Install apps for', 'Everyone on this computer, or just you. Each app can differ, in its Install options.', 'Just me']]
  : r[1] === 'Install folder' ? [['path', 'Install folder for me', 'Apps only you use. Each gets a folder here, with its versions side by side.', 'C:\\Users\\you\\AppData\\Local\\Programs'],
    ['path', 'Install folder for everyone', 'Apps every account uses. Only you and administrators can change what’s in it.', 'C:\\Programs']]
  : r[1] === 'Add to the app menu' ? [['toggle', 'Add to the Start menu', 'A Start-menu shortcut for each app.', true]]
  : r[1] === 'Stable name for the current version' ? [['toggle', r[1], '<app>\\current → the current version’s folder, so shortcuts and command links survive updates.', true]]
  : r[1] === 'Command links' ? [['toggle', r[1], 'A short command per app (e.g. localsend.cmd) in a folder AppKata adds to your PATH.', true]]
  : r[1] === 'Command links folder' ? [['path', r[1], '', 'C:\\Users\\you\\AppData\\Local\\AppKata\\bin']]
  : r[1] === 'Database' ? [['info', r[1], r[2], 'C:\\Users\\you\\AppData\\Local\\AppKata\\appkata.db', r[4]]]
  : r[1] === 'App log' ? [['info', r[1], r[2], 'C:\\Users\\you\\AppData\\Local\\AppKata\\Logs', r[4]]]
  : [r]);
function settingsRow(r, x0, iw, y, T) {
  let s = '';
  const kind = r[0], ctlX = x0 + 320, ctlW = iw - 320, right = x0 + iw;
  const label = (lab, hint) => {
    let h = 0;
    if (lab) s += text(x0, y + (hint ? 18 : 25), lab, { size: 14, weight: 700, fill: T.text });
    if (hint) { const p = para(x0, y + 36, 300, hint, T, { size: 12, lh: 16 }); s += p.s; h = p.h; }
    return Math.max(44, (hint ? 30 + h : 40) + 6);
  };
  if (kind === 'section') { s += text(x0, y + 26, r[1], { size: 11, weight: 700, fill: T.faint, ls: 1.2 }); return { s, h: 36 }; }
  if (kind === 'note') { const p = para(x0, y + 14, iw, r[1], T, { size: 12, lh: 17 }); return { s: p.s, h: p.h + 10 }; }
  if (kind === 'warnnote') {
    const p = para(x0 + 40, y + 26, iw - 56, r[1], T, { size: 12, lh: 17, fill: T.text });
    s += rect(x0, y + 6, iw, p.h + 26, 11, T.warnSoft) + icon('warn', x0 + 14, y + 17, 16, T.warn, 1.7) + p.s;
    return { s, h: p.h + 40 };
  }
  if (kind === 'seg') {
    const h = label(r[1], r[2]), sw = 330, sx = right - sw;
    s += rect(sx, y + 6, sw, 32, 9, T.track);
    r[3].forEach((l, i) => {
      const on = r[4] != null ? i === r[4] : (i === 1) === T.dark && i > 0 || (!T.dark && i === 2);
      if (on) s += rect(sx + 3 + i * 108, y + 9, 108, 26, 7, T.segOn, { filter: 'seg' });
      s += text(sx + 3 + i * 108 + 54, y + 26.5, l, { size: 12, weight: 700, fill: on ? T.text : T.muted, anchor: 'middle' });
    });
    return { s, h };
  }
  if (kind === 'toggle') {
    const h = label(r[1], r[2]), on = r[3], ty = y + h / 2 - 11;
    s += rect(right - 38, ty, 38, 22, 11, on ? T.accent : T.track, on ? {} : { stroke: T.borderStrong });
    s += `<circle cx="${on ? right - 11 : right - 27}" cy="${ty + 11}" r="9" fill="#ffffff"/>`;
    return { s, h };
  }
  if (kind === 'path') {
    const h = label(r[1], r[2]), by = y + h / 2 - 19;
    s += input(ctlX, by, ctlW - 40, T, { value: r[3], mono: true, h: 38, size: 13 }) + tipBtn(right - 32, by + 3, 'folder', T);   // tooltip "Browse…"

    return { s, h };
  }
  if (kind === 'select') {
    const h = label(r[1], r[2]), lw = tw(r[3], 12.5, { bold: true }) + 44, sx = right - lw;
    s += rect(sx, y + 8, lw, 28, 14, T.surface, { stroke: T.border }) + text(sx + 12, y + 26.5, r[3], { size: 12.5, weight: 700, fill: T.text });
    s += icon('chevDown', right - 22, y + 15, 13, T.muted);
    return { s, h };
  }
  if (kind === 'days') {
    const h = label(r[1], r[2]), by = y + h / 2 - 19;
    const unit = r[4] || 'days';
    s += input(right - 80 - 12 - tw(unit, 13), by, 80, T, { value: r[3], h: 38 }) + text(right - tw(unit, 13), by + 24, unit, { size: 13, fill: T.muted });
    return { s, h };
  }
  if (kind === 'token') {
    s += icon('key', x0, y + 12, 16, T.muted) + text(x0 + 26, y + 25, r[1], { size: 13, weight: 700, fill: T.text });
    s += text(x0 + 200, y + 25, r[2], { size: 12, fill: T.muted, mono: true });
    s += tipBtn(right - 32, y + 3, 'trash', T, { danger: true });
    return { s, h: 38 };
  }
  if (kind === 'addtoken') {
    s += input(x0, y + 4, 170, T, { placeholder: 'github.com', h: 38 });
    s += input(x0 + 178, y + 4, iw - 178 - 44, T, { placeholder: 'Paste a token', mono: true, h: 38 });
    s += tipBtn(right - 32, y + 7, 'plus', T, { disabled: true });
    return { s, h: 48 };
  }
  if (kind === 'relay') {
    s += text(x0, y + 22, r[1], { size: 13, fill: T.text, mono: true }) + tipBtn(right - 32, y + 1, 'trash', T, { danger: true });
    return { s, h: 36 };
  }
  if (kind === 'addrelay') {
    s += input(x0, y + 4, iw - 44, T, { placeholder: 'wss://relay.example.com', mono: true, h: 38 });
    s += tipBtn(right - 32, y + 7, 'plus', T, { disabled: true });
    return { s, h: 48 };
  }
  if (kind === 'info') {
    const h = label(r[1], r[2]), by = y + h / 2 - 17;
    let bx = right;
    for (const l of [...r[4]].reverse()) {
      if (l === 'Open folder' || l === 'Show') { s += tipBtn(bx - 32, by + 1, l === 'Show' ? 'open' : 'folder', T); bx -= 40; continue; }
      const b = button(bx, by, l, T, { anchor: 'end', ic: l === 'Import…' ? 'download' : l === 'Export…' ? 'save' : null }); s += b.s; bx -= b.w + 8;
    }
    if (r[3]) s += text(bx - 4, by + 21, r[3], { size: 12, fill: T.muted, mono: true, anchor: 'end' });
    return { s, h };
  }
  return { s, h: 0 };
}
function settingsDialog(T, from = '', rows = SETTINGS) {
  const SETTINGS = rows;
  let s = catalogView(T);
  s += scrim(T);
  const dw = 760, dh = 728, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60 - 16;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  s += text(x0, dy + 46, 'Settings', { size: 21, weight: 700, fill: T.text });
  s += iconBtn(dx + dw - 42, dy + 39, 'x', T);
  const top = dy + 70, bottom = dy + dh - 76;
  const c = nid('cl');
  defs.push(`<clipPath id="${c}"><rect x="${dx}" y="${top}" width="${dw}" height="${bottom - top}"/></clipPath>`);
  let i = from ? SETTINGS.findIndex(r => r[0] === 'section' && r[2] === from) : 0;
  let y = top - (i === 0 ? 14 : 4), body = '';
  for (; i < SETTINGS.length && y < bottom; i++) {
    const r = settingsRow(SETTINGS[i], x0, iw, y, T);
    body += r.s; y += r.h;
  }
  s += `<g clip-path="url(#${c})">${body}</g>`;
  // the scroll bar shows where in the list this is
  const pos = from === 'portable' ? 0.42 : from === 'sandbox' ? 0.5 : from === 'accounts' ? 0.6 : from === 'data' ? 0.78 : 0;
  s += rect(dx + dw - 22, top + 8 + pos * (bottom - top - 160), 5, 140, 2.5, T.borderStrong);
  s += button(dx + dw - 30, dy + dh - 58, 'Close', T, { anchor: 'end', primary: true }).s;
  return s;
}

function aboutDialog(T) {
  let s = appsView(T) + scrim(T);
  const dw = 440, dh = 336, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 28;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' }) + rect(dx + 0.5, dy + 0.5, dw - 1, dh - 1, 20, 'none', { stroke: T.border });
  s += logo(x0, dy + 28, 64, T);
  s += text(x0 + 80, dy + 56, 'AppKata', { size: 22, weight: 700, fill: T.text });
  s += text(x0 + 80, dy + 80, 'Version 0.1.0', { size: 13, fill: T.muted });
  s += para(x0, dy + 122, dw - 56, 'A FOSS app store built on git. Apps come from your Sources and from Trusts.', T, { size: 13, lh: 18, fill: T.text }).s;
  [['License', 'GNU GPL, version 3 or later'], ['Project', 'github.com/MojoKata/AppKata'], ['Runs on', 'Linux, macOS, and Windows 10 and later'], ['Built with', 'Python and Qt (PySide6)']]
    .forEach(([k, v], i) => {
      s += text(x0, dy + 176 + i * 23, k, { size: 12, fill: T.faint });
      s += text(x0 + 76, dy + 176 + i * 23, v, i === 1 ? { size: 12, weight: 700, fill: T.accent } : { size: 12, fill: T.text });
    });
  const cb = button(x0, dy + dh - 62, 'Check for updates', T, { ic: 'sync' });
  s += cb.s + button(x0 + cb.w + 8, dy + dh - 62, 'Close', T, { primary: true }).s;
  return s;
}

// ---------------------------------------------------------------- Install options (req 4.9)
function installDialog(T, o = {}) {
  let s = catalogView(T, { detail: 'krita' });
  s += scrim(T);
  const a = APPS.krita, dw = 680, dh = 588 + (o.sandbox ? 112 : 0), dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  s += appIconArt(x0, dy + 28, 40, a, T);
  s += text(x0 + 54, dy + 55, 'Install Krita 5.2.11', { size: 20, weight: 700, fill: T.text });
  s += iconBtn(x0 + iw - 12, dy + 48, 'x', T);
  let y = dy + 92;
  s += para(x0, y + 14, iw, 'This release can be installed two ways on Linux x86_64. Choose one; AppKata keeps to it for updates.', T, { size: 14, lh: 20, fill: T.text }).s;
  y += 52;
  const cards = [
    ['AppImage', 'Portable', 'Runs from your install folder; no admin password. Updates replace the file.', 'krita-5.2.11-x86_64.AppImage', '312 MB', true],
    ['.deb package', 'System package', 'Installed for all users with apt; needs your admin password.', 'krita_5.2.11_amd64.deb', '201 MB', false]];
  cards.forEach(([kind, cat, desc, file, size, on], i) => {
    const cy = y + i * 84;
    s += rect(x0, cy, iw, 76, 12, on ? T.accentSoft : T.input, { stroke: on ? T.accent : T.border, sw: on ? 2 : 1 });
    s += `<circle cx="${x0 + 26}" cy="${cy + 38}" r="10" fill="${on ? T.accent : 'none'}" stroke="${on ? 'none' : T.borderStrong}" stroke-width="1.6"/>`;
    if (on) s += `<circle cx="${x0 + 26}" cy="${cy + 38}" r="4" fill="#ffffff"/>`;
    s += text(x0 + 50, cy + 24, kind, { size: 14, weight: 700, fill: T.text });
    let px = x0 + 50 + tw(kind, 14, { bold: true }) + 8;
    const p1 = pill(px, cy + 11, cat, { bg: i === 0 ? T.okSoft : T.track, fg: i === 0 ? T.ok : T.muted, size: 10.5, h: 18 });
    s += p1.s;
    if (i === 0) s += pill(px + p1.w + 6, cy + 11, 'Recommended', { bg: T.accentSoft, fg: T.accent, size: 10.5, h: 18 }).s;
    s += text(x0 + 50, cy + 44, desc, { size: 12, fill: T.muted });
    s += text(x0 + 50, cy + 62, file, { size: 11, fill: T.faint, mono: true });
    s += text(x0 + iw - 16, cy + 42, size, { size: 12, fill: T.faint, anchor: 'end' });
  });
  y += 176;
  s += rect(x0, y, iw, 96, 12, T.input, { stroke: T.border });
  s += icon('folder', x0 + 16, y + 12, 14, T.muted) + text(x0 + 36, y + 24, 'Installs to ~/bin/apps/krita', { size: 12, fill: T.muted, mono: true });
  s += checkbox(x0 + 16, y + 40, true, T) + text(x0 + 44, y + 54, 'Add to the app menu', { size: 13, weight: 700, fill: T.text });
  s += checkbox(x0 + 220, y + 40, false, T) + text(x0 + 248, y + 54, 'Command', { size: 13, weight: 700, fill: T.text });
  s += text(x0 + 248 + tw('Command ', 13, { bold: true }), y + 54, 'krita', { size: 12.5, fill: T.text, mono: true });
  s += text(x0 + 248 + tw('Command ', 13, { bold: true }) + tw('krita ', 12.5, { mono: true }), y + 54, 'in ~/bin', { size: 13, fill: T.text });
  s += checkbox(x0 + 440, y + 40, true, T) + text(x0 + 468, y + 54, 'Stable name link', { size: 13, weight: 700, fill: T.text });
  s += text(x0 + 16, y + 82, 'Options recommended by mara-dev / foss-picks', { size: 12, fill: T.accent });
  y += 108;
  if (o.sandbox) {   // app-sandboxing.md
    const right = x0 + iw;
    s += rect(x0, y, iw, 100, 12, T.input, { stroke: T.border });
    s += icon('shieldCheck', x0 + 16, y + 14, 16, T.ok) + text(x0 + 40, y + 27, 'Sandbox', { size: 13, weight: 700, fill: T.text });
    s += dropdown(right - 16 - 220, y + 8, 220, 'Offline editor', T, { ic: 'shieldCheck', icColor: T.accent, h: 30 });
    let px = x0 + 16;
    [['Its own home folder', 'lock'], ['~/Pictures', 'folder'], ['No network', 'ban']].forEach(([l, ic]) => {
      const p = pill(px, y + 48, l, { bg: T.track, fg: T.muted, ic, size: 11.5 }); s += p.s; px += p.w + 6;
    });
    s += icon('chevRight', px + 2, y + 52, 12, T.accent, 2) + text(px + 16, y + 63, 'Customize…', { size: 12, weight: 700, fill: T.accent });
    const sug = 'Offline editor, suggested by mara-dev / foss-picks';
    s += text(x0 + 16, y + 88, sug, { size: 12, fill: T.accent });
    s += text(x0 + 16 + tw(sug, 12), y + 88, '\u00a0· unpacked to run sandboxed: 312 MB → about 870 MB', { size: 12, fill: T.muted });
    y += 112;
  }
  // "Disable the app's own updater" — its own option; required (and on) when sandboxed (app-sandboxing.md)
  s += rect(x0, y, iw, 80, 12, T.input, { stroke: T.border });
  s += checkbox(x0 + 16, y + 14, !!o.sandbox, T, o.sandbox ? { disabled: true } : {}) + text(x0 + 44, y + 28, 'Disable the app’s own updater — AppKata updates it', { size: 13, weight: 700, fill: T.text });
  s += para(x0 + 16, y + 50, iw - 32, o.sandbox
    ? 'Required with the sandbox on: the read-only install folder blocks self-update, so AppKata takes it over.'
    : 'AppKata takes over updates. Without this, AppKata installs the app and shows new releases but leaves updating to the app.', T, { size: 12, lh: 16, fill: o.sandbox ? T.warn : T.muted }).s;
  const by = dy + dh - 58;
  const ib = button(x0 + iw, by, 'Install', T, { primary: true, anchor: 'end', ic: 'download' });
  s += ib.s + button(x0 + iw - ib.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  const t1 = 'You can change this later from the app’s ';
  s += text(x0, by + 22, t1, { size: 12, fill: T.faint }) + icon('more', x0 + tw(t1, 12) + 2, by + 11, 13, T.faint);
  s += text(x0 + tw(t1, 12) + 19, by + 22, 'menu.', { size: 12, fill: T.faint });
  return s;
}

// ---------------------------------------------------------------- Install options on Windows (req 4.9, 15.4, 15.11.1)
function installDialogWindows(T) {
  let s = appsView(T, { detail: 'keepassxc' }) + scrim(T);
  const a = APPS.keepassxc, dw = 680, dh = 752, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  s += appIconArt(x0, dy + 28, 40, a, T);
  s += text(x0 + 54, dy + 55, 'Install options for KeePassXC', { size: 20, weight: 700, fill: T.text });
  s += iconBtn(x0 + iw - 12, dy + 48, 'x', T);
  let y = dy + 88;
  s += para(x0, y + 14, iw, 'This release can be installed two ways on Windows x86_64. Choose one; AppKata keeps to it for updates.', T, { size: 14, lh: 20, fill: T.text }).s;
  y += 50;
  const cards = [
    ['zip archive', 'Portable', 'Runs from your install folder; no admin password. Updates replace the file.', 'KeePassXC-2.7.10-Win64.zip', '33 MB', true],
    ['.msi installer', 'System package', 'Installed by its own installer, which Windows lists in Settings → Apps.', 'KeePassXC-2.7.10-Win64.msi', '38 MB', false]];
  cards.forEach(([kind, cat, desc, file, size, on], i) => {
    const cy = y + i * 80;
    s += rect(x0, cy, iw, 72, 12, on ? T.accentSoft : T.input, { stroke: on ? T.accent : T.border, sw: on ? 2 : 1 });
    s += `<circle cx="${x0 + 26}" cy="${cy + 36}" r="10" fill="${on ? T.accent : 'none'}" stroke="${on ? 'none' : T.borderStrong}" stroke-width="1.6"/>`;
    if (on) s += `<circle cx="${x0 + 26}" cy="${cy + 36}" r="4" fill="#ffffff"/>`;
    s += text(x0 + 50, cy + 22, kind, { size: 14, weight: 700, fill: T.text });
    const px = x0 + 50 + tw(kind, 14, { bold: true }) + 8;
    const p1 = pill(px, cy + 9, cat, { bg: i === 0 ? T.okSoft : T.track, fg: i === 0 ? T.ok : T.muted, size: 10.5, h: 18 });
    s += p1.s;
    if (i === 0) s += pill(px + p1.w + 6, cy + 9, 'Recommended', { bg: T.accentSoft, fg: T.accent, size: 10.5, h: 18 }).s;
    s += text(x0 + 50, cy + 42, desc, { size: 12, fill: T.muted });
    s += text(x0 + 50, cy + 60, file, { size: 11, fill: T.faint, mono: true });
    s += text(x0 + iw - 16, cy + 40, size, { size: 12, fill: T.faint, anchor: 'end' });
  });
  y += 168;
  s += rect(x0, y, iw, 74, 12, T.input, { stroke: T.border });
  s += icon('folder', x0 + 16, y + 12, 14, T.muted) + text(x0 + 36, y + 24, 'Installs to C:\\Users\\you\\AppData\\Local\\Programs\\keepassxc', { size: 12, fill: T.muted, mono: true });
  s += checkbox(x0 + 16, y + 40, true, T) + text(x0 + 44, y + 54, 'Add to the app menu', { size: 13, weight: 700, fill: T.text });
  s += checkbox(x0 + 210, y + 40, true, T) + text(x0 + 238, y + 54, 'Command', { size: 13, weight: 700, fill: T.text });
  s += text(x0 + 238 + tw('Command ', 13, { bold: true }), y + 54, 'keepassxc', { size: 12.5, fill: T.text, mono: true });
  s += text(x0 + 238 + tw('Command ', 13, { bold: true }) + tw('keepassxc ', 12.5, { mono: true }), y + 54, 'in …\\bin', { size: 13, fill: T.text });
  s += checkbox(x0 + 490, y + 40, true, T) + text(x0 + 518, y + 54, 'Stable name link', { size: 13, weight: 700, fill: T.text });
  y += 86;            // who it's for (req 15.4)
  s += rect(x0, y, iw, 76, 12, T.input, { stroke: T.border });
  s += text(x0 + 16, y + 28, 'Install for', { size: 13, weight: 700, fill: T.text });
  const p1 = pill(x0 + 100, y + 12, 'Just me', { bg: T.accentSoft, fg: T.accent, stroke: T.accent, size: 12, h: 30 });
  s += p1.s + pill(x0 + 110 + p1.w, y + 12, 'Everyone on this computer', { bg: T.surface, fg: T.text, stroke: T.border, size: 12, h: 30 }).s;
  s += text(x0 + 16, y + 62, 'Only you can use it. No administrator rights are needed.', { size: 12, fill: T.muted });
  y += 88;            // Mark of the Web (req 15.11.1)
  s += rect(x0, y, iw, 70, 12, T.input, { stroke: T.border });
  s += checkbox(x0 + 16, y + 14, false, T) + text(x0 + 44, y + 28, 'Mark downloads as from the internet', { size: 13, weight: 700, fill: T.text });
  s += text(x0 + 16, y + 54, 'Windows SmartScreen then checks this app’s installers and programs, as it does a browser download.', { size: 12, fill: T.muted });
  y += 82;
  s += rect(x0, y, iw, 76, 12, T.input, { stroke: T.border });
  s += checkbox(x0 + 16, y + 14, false, T) + text(x0 + 44, y + 28, 'This app updates itself', { size: 13, weight: 700, fill: T.text });
  s += para(x0 + 16, y + 48, iw - 32, 'AppKata installs it and shows new releases, but leaves updating to the app. AppKata can’t turn an app’s own updater off.', T, { size: 12, lh: 16 }).s;
  const by = dy + dh - 58;
  const sb = button(x0 + iw, by, 'Save', T, { primary: true, anchor: 'end' });
  s += sb.s + button(x0 + iw - sb.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  s += text(x0, by + 22, 'Applies from the next update.', { size: 12, fill: T.faint });
  return s;
}


// ---------------------------------------------------------------- package channels (req 16)
// Patches the sample data for one scene: { APPS: {key: {...}}, INSTALLED: {key: {...} | null}, STATE: {...} }
function withData(patch, draw) {
  return T => {
    const saved = [];
    for (const [tbl, obj] of [['APPS', APPS], ['INSTALLED', INSTALLED], ['STATE', STATE]]) {
      for (const [k, v] of Object.entries(patch[tbl] || {})) {
        saved.push([obj, k, obj[k]]);
        if (v === null) delete obj[k]; else obj[k] = tbl === 'APPS' ? { ...obj[k], ...v } : v;
      }
    }
    try { return draw(T); } finally { for (const [obj, k, v] of saved.reverse()) { if (v === undefined) delete obj[k]; else obj[k] = v; } }
  };
}
function radio(x, cy, on, T) {
  return `<circle cx="${x}" cy="${cy}" r="9" fill="${on ? T.accent : 'none'}" stroke="${on ? 'none' : T.borderStrong}" stroke-width="1.6"/>` +
    (on ? `<circle cx="${x}" cy="${cy}" r="3.6" fill="#ffffff"/>` : '');
}
// Install options with channels: Flathub, the release's AppImage and the distro's package (req 16.3)
function installChannelsDialog(T) {
  let s = catalogView(T, { detail: 'localsend' });
  s += scrim(T);
  const a = APPS.localsend, dw = 700, dh = 640, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  s += appIconArt(x0, dy + 28, 40, a, T);
  s += text(x0 + 54, dy + 55, 'Install LocalSend 1.18.2', { size: 20, weight: 700, fill: T.text });
  s += iconBtn(x0 + iw - 12, dy + 48, 'x', T);
  let y = dy + 92;
  s += para(x0, y + 14, iw, 'LocalSend can be installed three ways on Ubuntu 24.04 (x86_64). Choose one; AppKata keeps to it for updates.', T, { size: 14, lh: 20, fill: T.text }).s;
  y += 52;
  const cards = [
    { kind: 'Flathub', pills: [['Flatpak', T.track, T.muted], ['Verified', T.okSoft, T.ok, 'shieldCheck'], ['Recommended', T.surface, T.accent]], size: '48 MB', on: true,
      mono: 'org.localsend.localsend_app · 1.18.2',
      desc: 'Built by Flathub from upstream v1.18.2 · sandboxed · per user, no admin password',
      foot: [['Recommended by mara-dev / foss-picks', T.accent], ['\u00a0· GNOME Software updates Flatpaks automatically', T.warn]] },
    { kind: 'AppImage', pills: [['Portable', T.okSoft, T.ok], ['GitHub release', T.track, T.muted]], size: '92 MB',
      mono: 'LocalSend-1.18.2-linux-x86-64.AppImage',
      desc: 'Runs from your install folder; no admin password. AppKata updates it.' },
    { kind: 'Ubuntu package', pills: [['System package', T.track, T.muted], ['universe', T.track, T.muted]], size: '41 MB',
      mono: 'localsend 1.14.0-1 · apt',
      desc: 'Installed for all users with apt; needs your admin password. Ubuntu’s updates keep it current.',
      foot: [['4 releases behind the project (1.18.2)', T.faint]] },
  ];
  cards.forEach(c => {
    const ch = c.foot ? 94 : 76;
    s += rect(x0, y, iw, ch, 12, c.on ? T.accentSoft : T.input, { stroke: c.on ? T.accent : T.border, sw: c.on ? 2 : 1 });
    s += radio(x0 + 26, y + 30, c.on, T);
    s += text(x0 + 50, y + 24, c.kind, { size: 14, weight: 700, fill: T.text });
    let px = x0 + 50 + tw(c.kind, 14, { bold: true }) + 8;
    c.pills.forEach(([l, bg, fg, ic]) => { const p = pill(px, y + 11, l, { bg, fg, ic, size: 10.5, h: 18 }); s += p.s; px += p.w + 6; });
    s += text(x0 + iw - 16, y + 24, c.size, { size: 12, fill: T.faint, anchor: 'end' });
    s += text(x0 + 50, y + 44, c.mono, { size: 11, fill: T.faint, mono: true });
    s += text(x0 + 50, y + 63, c.desc, { size: 12, fill: T.muted });
    if (c.foot) {
      let fx = x0 + 50;
      c.foot.forEach(([t, col]) => { s += text(fx, y + 81, t, { size: 11.5, fill: col, weight: col === T.accent ? 700 : 400 }); fx += tw(t, 11.5, { bold: col === T.accent }); });
    }
    y += ch + 8;
  });
  y += 4;
  // who updates it (req 16.5): the system was detected updating Flatpaks, so it keeps doing that by default
  s += rect(x0, y, iw, 108, 12, T.input, { stroke: T.border });
  s += text(x0 + 16, y + 26, 'Updates', { size: 13, weight: 700, fill: T.text });
  s += radio(x0 + 26, y + 52, true, T) + text(x0 + 44, y + 57, 'Let GNOME Software update it', { size: 13, weight: 700, fill: T.text });
  s += text(x0 + 44 + tw('Let GNOME Software update it ', 13, { bold: true }), y + 57, '(detected: automatic Flatpak updates are on)', { size: 12, fill: T.muted });
  s += radio(x0 + 26, y + 82, false, T) + text(x0 + 44, y + 87, 'AppKata updates it', { size: 13, weight: 700, fill: T.text });
  s += text(x0 + 44 + tw('AppKata updates it ', 13, { bold: true }), y + 87, '— GNOME Software keeps updating it too; AppKata can’t turn that off', { size: 12, fill: T.muted });
  y += 120;
  s += text(x0, y + 8, 'Portable options appear when you choose the AppImage.', { size: 12, fill: T.faint });
  const by = dy + dh - 58;
  const ib = button(x0 + iw, by, 'Install', T, { primary: true, anchor: 'end', ic: 'download' });
  s += ib.s + button(x0 + iw - ib.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  const t1 = 'You can change this later from the app’s ';
  s += text(x0, by + 22, t1, { size: 12, fill: T.faint }) + icon('more', x0 + tw(t1, 12) + 2, by + 11, 13, T.faint);
  s += text(x0 + tw(t1, 12) + 19, by + 22, 'menu.', { size: 12, fill: T.faint });
  return s;
}
// Installed from Flathub and updated by GNOME Software; a distro package nothing updates (req 16.5, 16.6)
const systemUpdatedScene = withData({
  APPS: { localsend: { ver: '1.18.2' } },
  INSTALLED: {
    localsend: { from: '1.18.2', type: 'Flatpak', system: 'GNOME Software',
      channel: [['Flathub · verified', null, null, 'shieldCheck'], ['Flatpak', null, null, null]],
      perms: [['network', false], ['~/Downloads', false], ['+ Home folder since 1.18.0', true]] },
    keepassxc: { from: '2.7.6', type: '.deb · Ubuntu', notUpdated: 'Ubuntu doesn’t update this automatically' },
  },
}, T => {
  INSTALLED.localsend.channel = [['Flathub · verified', T.okSoft, T.ok, 'shieldCheck'], ['Flatpak', T.track, T.muted, null]];
  return appsView(T, { detail: 'localsend', upd: ['appkata', 'signal', 'zettlr'], rest: ['flameshot', 'inkscape', 'keepassxc', 'localsend', 'syncthing', 'ventoy', 'vscodium'] });
});
// The installed version is avoided by a Trust (req 10.6.5)
const versionAvoidedScene = withData({
  INSTALLED: { xz: { from: '5.6.1', to: '5.6.2', type: 'tar.gz',
    avoid: { by: 'desk-collective', from: '5.6.0', note: 'Backdoored release tarballs' } } },
  STATE: { xz: 'update' },
}, T => appsView(T, { detail: 'xz', upd: ['xz', 'appkata', 'localsend', 'signal'], rest: ['flameshot', 'inkscape', 'keepassxc', 'syncthing', 'ventoy', 'vscodium'] }));

// Explore on Flathub: each match needs a git project URL to become a Source (req 16.2)
const FLATHUB = [
  ['Joplin', 'net.cozic.joplin_desktop', 'A note taking and to-do application with synchronisation', true, 'github.com/laurent22/joplin', 'source'],
  ['Xournal++', 'com.github.xournalpp.xournalpp', 'Handwriting notetaking software with PDF annotation support', true, 'github.com/xournalpp/xournalpp', 'trusts'],
  ['Notesnook', 'com.notesnook.Notesnook', 'Private, end-to-end encrypted note-taking', true, 'github.com/streetwriters/notesnook', ''],
  ['Pocket Notes', 'io.example.PocketNotes', 'Quick sticky notes (community packaging)', false, null, ''],
  ['Folio', 'com.toolstack.Folio', 'Take notes in Markdown', true, 'github.com/toolstack/Folio', ''],
];
function exploreFlathubDialog(T) {
  let s = sourcesView(T, {});
  s += scrim(T);
  const dw = 760, dh = 676, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' });
  s += text(x0, dy + 46, 'Explore', { size: 21, weight: 700, fill: T.text });
  s += iconBtn(x0 + iw - 12, dy + 39, 'x', T);
  let y = dy + 76;
  const segs = ['GitHub', 'GitLab', 'Codeberg', 'ngit', 'Flathub', 'Ubuntu'], sw = 600, segW = (sw - 6) / segs.length, on = 4;
  s += rect(x0, y, sw, 34, 10, T.track);
  segs.forEach((l, i) => {
    if (i === on) s += rect(x0 + 3 + i * segW, y + 3, segW, 28, 8, T.segOn, { filter: 'seg' });
    s += text(x0 + 3 + i * segW + segW / 2, y + 22, l, { size: 13, weight: 700, fill: i === on ? T.text : T.muted, anchor: 'middle' });
  });
  y += 50;
  s += input(x0, y, iw - 90, T, { ic: 'search', value: 'notes', focus: true, h: 40 });
  s += button(x0 + iw, y + 3, 'Search', T, { primary: true, anchor: 'end' }).s;
  y += 56;
  FLATHUB.forEach(([name, id, desc, verified, git, flag], row) => {
    s += rect(x0, y, iw, 78, 12, T.input, { stroke: T.border });
    s += text(x0 + 14, y + 24, name, { size: 14, weight: 700, fill: T.text });
    let cx = x0 + 14 + tw(name, 14, { bold: true }) + 8;
    s += text(cx, y + 24, id, { size: 11.5, fill: T.faint, mono: true });
    cx += tw(id, 11.5, { mono: true }) + 8;
    if (verified) { const p = pill(cx, y + 11, 'Verified', { bg: T.okSoft, fg: T.ok, ic: 'shieldCheck', size: 10.5, h: 18 }); s += p.s; cx += p.w + 6; }
    if (flag === 'trusts') s += pill(cx, y + 11, 'In your trusts', { bg: T.accentSoft, fg: T.accent, size: 10.5, h: 18 }).s;
    s += text(x0 + 14, y + 44, desc, { size: 12, fill: T.muted });
    if (git) {
      s += icon('branch', x0 + 14, y + 53, 13, T.faint);
      s += text(x0 + 32, y + 64, git, { size: 11.5, fill: T.text, mono: true });
      s += text(x0 + 38 + tw(git, 11.5, { mono: true }), y + 64, 'from its AppStream data', { size: 11, fill: T.faint });
    } else {
      s += icon('warn', x0 + 14, y + 53, 13, T.warn);
      s += text(x0 + 32, y + 64, 'No project link found.', { size: 11.5, fill: T.warn });
      s += text(x0 + 36 + tw('No project link found.', 11.5), y + 64, 'Enter git URL…', { size: 11.5, weight: 700, fill: T.accent });
    }
    const bx = x0 + iw - 12 - 32, by = y + 23;
    if (flag === 'source') s += rect(bx, by, 32, 32, 9, T.track) + icon('check', bx + 8, by + 8, 16, T.faint);
    else if (!git) s += rect(bx, by, 32, 32, 9, T.track) + icon('plus', bx + 8, by + 8, 16, T.faint);
    else s += rect(bx, by, 32, 32, 9, T.accent) + icon('plus', bx + 8, by + 8, 16, '#ffffff');
    s += rect(bx - 40, by, 32, 32, 9, T.surface, { stroke: T.border }) + icon('open', bx - 32, by + 8, 16, T.muted);
    if (!git) {
      s += tipLeft(bx - 48, by + 16, 'No project link found; enter its git URL to add it', T);
      s += cursor(bx + 18, by + 18);
    }
    y += 86;
  });
  s += text(x0, dy + dh - 36, 'Flathub’s own search. A match becomes a Source once its git project is known.', { size: 12, fill: T.faint });
  s += button(x0 + iw, dy + dh - 58, 'Close', T, { anchor: 'end' }).s;
  return s;
}

// ---------------------------------------------------------------- AppKata installing itself (req 2.11.3.1)
function selfInstallScene(T) {
  let s = emptyState(T, 'catalog') + scrim(T);
  const dw = 560, x0 = (W - dw) / 2 + 30, iw = dw - 60, dh = 384, dx = (W - dw) / 2, dy = (H - dh) / 2;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' }) + rect(dx + 0.5, dy + 0.5, dw - 1, dh - 1, 20, 'none', { stroke: T.border });
  s += text(x0, dy + 56, 'Install AppKata?', { size: 20, weight: 700, fill: T.text });
  s += iconBtn(dx + dw - 44, dy + 50, 'x', T);
  let y = dy + 88;
  s += logo(x0, y, 48, T);
  s += para(x0 + 62, y + 18, iw - 62, 'AppKata 0.1.0 is running from where it was downloaded. Install it to keep it in your app menu and let it update itself.', T, { size: 14, lh: 20, fill: T.text }).s;
  y += 70;
  s += rect(x0, y, iw, 134, 12, T.input, { stroke: T.border });
  s += icon('folder', x0 + 16, y + 13, 14, T.muted) + text(x0 + 36, y + 25, 'Installs to ~/bin/apps/appkata/AppKata.AppImage', { size: 12, fill: T.muted, mono: true });
  s += para(x0 + 16, y + 50, iw - 32, 'Adds AppKata to the app menu with its icon, and points appkata:// links and starting at login at the installed copy.', T, { size: 12, lh: 16, fill: T.muted }).s;
  s += checkbox(x0 + 16, y + 84, true, T) + text(x0 + 44, y + 98, 'Delete the downloaded file', { size: 13, weight: 700, fill: T.text });
  s += text(x0 + 44, y + 116, '~/Downloads/AppKata-0.1.0-x86_64.AppImage', { size: 11.5, fill: T.muted, mono: true });
  const by = dy + dh - 64;
  const b1 = button(x0 + iw, by, 'Install', T, { primary: true, anchor: 'end', ic: 'download' });
  s += b1.s + button(x0 + iw - b1.w - 10, by, 'Run from here', T, { anchor: 'end' }).s;
  const t1 = 'You can install it later from the ';
  s += text(x0, by + 22, t1, { size: 12, fill: T.faint }) + icon('more', x0 + tw(t1, 12) + 2, by + 11, 13, T.faint);
  s += text(x0 + tw(t1, 12) + 19, by + 22, 'menu.', { size: 12, fill: T.faint });
  return s;
}

// ---------------------------------------------------------------- app sandboxing (docs/app-sandboxing.md)
// Portable apps and AppImages on Linux, run in bubblewrap: Off / Standard / Strict and what each app may use
const SANDBOXED = {
  keepassxc: { from: '2.7.10', type: 'AppImage', sandbox: { level: 'Standard', x11: true,
    access: [['Its own home folder', 'lock'], ['~/Documents/Passwords', 'folder'], ['No network', 'ban']] } },
  localsend: { from: '1.16.1', to: '1.17.0', type: 'AppImage', sandbox: { level: 'Standard', access: [] } },
  zettlr: { from: '3.5.1', to: '3.6.0', type: 'AppImage', sandbox: { level: 'Standard',
    access: [['Its own home folder', 'lock'], ['~/Documents', 'folder'], ['~/Zettlr', 'folder'], ['No network', 'ban']] } },
  inkscape: { from: '1.4.1', to: '1.4.2', type: 'AppImage', held: 'Held · 5 days left', sandbox: { level: 'Standard', access: [] } },
  syncthing: { from: '2.0.9', type: 'tar.gz', auto: true, by: 'Kenji’s app reviews', sandbox: { level: 'Off', access: [] } },
  ventoy: { from: '1.0.99', to: '1.1.07', type: 'tar.gz', pinned: true, sandbox: { level: 'Off', access: [] } },
};
function sandboxScene(patch, draw) {
  return withData({ INSTALLED: { ...SANDBOXED, ...patch } }, draw);
}
// The six built-in templates (docs/app-sandboxing.md): name, summary, the chips the summary shows.
const TEMPLATES = {
  'Strict': ['Private home only. No network, no devices.', [['Strict', 'lock']]],
  'Offline editor': ['A documents folder, no network, display only.',
    [['Standard', 'shieldCheck'], ['~/Documents/Passwords', 'folder'], ['~/Downloads · ro', 'folder'], ['No network', 'ban']]],
  'Online app': ['Network and the file picker; no folders of its own.', [['Standard', 'shieldCheck'], ['Network', 'globe']]],
  'Messenger / calls': ['Network, camera and microphone for calls.', [['Standard', 'shieldCheck'], ['Network', 'globe'], ['Camera', 'camera'], ['Microphone', 'wave']]],
  'Media player': ['A media folder (read-only); plays sound.', [['Standard', 'shieldCheck'], ['~/Music · ro', 'folder'], ['Play sound', 'wave']]],
  'Developer tool': ['A projects folder it can write and run code in.', [['Standard', 'shieldCheck'], ['~/Projects', 'folder'], ['Network', 'globe'], ['Runs code', 'code']]],
  'CLI tool': ['The directory it’s run in; nothing else of your home.', [['Standard', 'shieldCheck'], ['Current folder', 'folder'], ['Runs code', 'code']]],
};
// a dropdown control: a rounded box with a leading icon, a value and a chevron
function dropdown(x, y, w, value, T, o = {}) {
  let s = rect(x, y, w, o.h || 34, 9, T.input, { stroke: T.border });
  let tx = x + 14;
  if (o.ic) { s += icon(o.ic, x + 12, y + (o.h || 34) / 2 - 8, 16, o.icColor || T.muted); tx += 26; }
  s += text(tx, y + (o.h || 34) / 2 + 4.5, value, { size: 13, weight: 700, fill: T.text });
  s += icon('chevDown', x + w - 24, y + (o.h || 34) / 2 - 7, 14, T.muted);
  return s;
}
// the per-app Sandbox dialog (App Detail ▸ Sandbox ▸ Change…): a template dropdown, a live summary,
// and a collapsed Customize disclosure (the groups open in A25). app-sandboxing.md.
function sandboxDialog(T) {
  let s = appsView(T, { detail: 'keepassxc' }) + scrim(T);
  const a = APPS.keepassxc, tpl = 'Offline editor', [summary, chips] = TEMPLATES[tpl];
  const dw = 620, dh = 456, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60, right = x0 + iw;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' }) + rect(dx + 0.5, dy + 0.5, dw - 1, dh - 1, 20, 'none', { stroke: T.border });
  s += appIconArt(x0, dy + 30, 40, a, T);
  s += text(x0 + 54, dy + 44, 'KEEPASSXC', { size: 12, weight: 700, fill: T.faint, ls: 0.8 });
  s += text(x0 + 54, dy + 66, 'Sandbox', { size: 20, weight: 700, fill: T.text });
  s += iconBtn(dx + dw - 44, dy + 50, 'x', T);
  let y = dy + 104;
  // template dropdown + customized state + reset
  s += text(x0, y + 5, 'Template', { size: 13, weight: 700, fill: T.text });
  const sx = x0 + 86, selW = 250;
  s += dropdown(sx, y - 12, selW, tpl, T, { ic: 'shieldCheck', icColor: T.accent });
  s += text(sx + selW + 12, y + 5, '· customized', { size: 12, fill: T.muted });
  s += icon('refresh', right - 128, y - 3, 13, T.accent) + text(right, y + 5, 'Reset to template', { size: 12, weight: 700, fill: T.accent, anchor: 'end' });
  y += 28;
  s += text(sx, y + 4, 'suggested by mara-dev / foss-picks', { size: 12, fill: T.accent });
  y += 34;
  // live summary
  s += para(x0, y + 10, iw, summary + ' Plus ~/Downloads, which you added.', T, { size: 13, lh: 18, fill: T.text }).s;
  y += 34;
  let cx = x0;
  chips.forEach(([l, ic]) => {
    const warn = false, bg = ic === 'shieldCheck' ? T.okSoft : T.track, fg = ic === 'shieldCheck' ? T.ok : T.muted;
    const p = pill(cx, y, l, { bg, fg, ic, size: 11.5 }); if (cx + p.w > right) { cx = x0; y += 28; } s += p.s; cx += p.w + 6;
  });
  y += 46;
  s += hline(x0, right, y, T.border); y += 18;
  // collapsed Customize disclosure
  s += icon('chevRight', x0, y - 2, 14, T.muted, 2) + text(x0 + 24, y + 9, 'Customize', { size: 14, weight: 700, fill: T.text });
  s += text(right, y + 9, 'Files · Connections · Devices & media · Advanced', { size: 12, fill: T.faint, anchor: 'end' });
  y += 34;
  s += hline(x0, right, y, T.border); y += 20;
  // its home folder
  s += text(x0, y + 10, 'Its home folder', { size: 13, weight: 700, fill: T.text });
  s += text(right - 40, y + 10, '~/.local/share/appkata/sandboxes/keepassxc', { size: 11.5, fill: T.muted, mono: true, anchor: 'end' });
  s += tipBtn(right - 30, y - 5, 'folder', T, { size: 30 });
  const by = dy + dh - 58;
  const sv = button(right, by, 'Save', T, { primary: true, anchor: 'end' });
  s += sv.s + button(right - sv.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  s += text(x0, by + 20, 'Applies the next time KeePassXC starts.', { size: 12, fill: T.faint });
  return s;
}
// the Customize section expanded, scrolled to Connections / Devices / Advanced so the Landlock
// controls (the defense-in-depth layer inside bwrap) are visible. app-sandboxing.md.
function sandboxAdvanced(T) {
  let s = appsView(T, { detail: 'keepassxc' }) + scrim(T);
  const dw = 620, dh = 700, dx = (W - dw) / 2, dy = (H - dh) / 2, x0 = dx + 30, iw = dw - 60, right = x0 + iw;
  s += rect(dx, dy, dw, dh, 20, T.surface, { filter: 'lift' }) + rect(dx + 0.5, dy + 0.5, dw - 1, dh - 1, 20, 'none', { stroke: T.border });
  s += text(x0, dy + 40, 'Customize sandbox', { size: 18, weight: 700, fill: T.text });
  s += text(x0, dy + 60, 'KeePassXC · Offline editor', { size: 12, fill: T.muted });
  s += iconBtn(dx + dw - 44, dy + 36, 'x', T);
  const top = dy + 80, bottom = dy + dh - 64;
  const c = nid('cl'); defs.push(`<clipPath id="${c}"><rect x="${dx}" y="${top}" width="${dw}" height="${bottom - top}"/></clipPath>`);
  let y = top + 8, body = '';
  const header = (t) => { body += text(x0, y + 14, t, { size: 11, weight: 700, fill: T.faint, ls: 1.2 }); y += 30; };
  const toggle = (label, hint, on, o = {}) => {
    body += icon(o.ic || 'gear', x0, y + 6, 16, o.warn ? T.warn : T.muted);
    body += text(x0 + 26, y + 11, label, { size: 13.5, weight: 700, fill: T.text });
    if (o.badge) { const p = pill(x0 + 26 + tw(label, 13.5, { bold: true }) + 8, y, o.badge, { bg: T.accentSoft, fg: T.accent, size: 10, h: 17 }); body += p.s; }
    const h = para(x0 + 26, y + 30, iw - 90, hint, T, { size: 11.5, lh: 15, fill: o.warn ? T.warn : T.muted });
    body += h.s;
    body += rect(right - 38, y + 2, 38, 22, 11, on ? T.accent : T.track, on ? {} : { stroke: T.borderStrong });
    body += `<circle cx="${on ? right - 11 : right - 27}" cy="${y + 13}" r="9" fill="#ffffff"/>`;
    y += Math.max(44, 30 + h.h + 10);
  };
  header('CONNECTIONS');
  toggle('Network', 'Off for this app; turn on only if it needs the internet.', false, { ic: 'globe' });
  toggle('Limit to ports', 'When network is on, allow only these (Landlock, kernel ≥ 6.7): 443. Blocks everything else.', true, { ic: 'globe', badge: 'Landlock' });
  toggle('Desktop services (portals)', 'File chooser, notifications and opening links. Nothing else on the session bus.', true, { ic: 'panel' });
  header('DEVICES & MEDIA');
  toggle('Play sound', 'Send audio to the speakers.', false, { ic: 'wave' });
  toggle('Microphone / recording', 'Record audio. Routed so the app is seen as sandboxed, not given the raw socket.', false, { ic: 'wave' });
  toggle('Camera', 'Through the camera portal, with the system’s permission.', false, { ic: 'camera' });
  header('SERVICES · what the app may use on the session bus');
  toggle('Tray icon', 'Let it show a status-bar icon (StatusNotifierItem) and own its own bus name.', false, { ic: 'panel' });
  toggle('Media keys', 'Play/pause and track info on the keyboard and lock screen (MPRIS).', false, { ic: 'play' });
  toggle('Keep the screen awake', 'Inhibit the screensaver while it’s doing something (video, a transfer).', false, { ic: 'clock' });
  toggle('Password service', 'Offer or use the secret service (org.freedesktop.secrets) for other apps.', true, { ic: 'key' });
  header('ADVANCED · extra hardening inside bwrap (Landlock)');
  toggle('Block running programs it writes', 'A second lock (Landlock) that holds even if the sandbox has a bug: the app can write its data but not execute anything it drops there.', true, { ic: 'shield', badge: 'Landlock' });
  toggle('Let it change its own files', 'Only for apps that update themselves or keep settings beside the program. It could then change its own code.', false, { ic: 'warn', warn: true });
  // shown from the top: Connections (networking) + Devices, with Services/Advanced below the fold
  s += `<g clip-path="url(#${c})">${body}</g>`;
  s += rect(dx + dw - 20, top + 8, 5, 150, 2.5, T.borderStrong);     // scroll position: near the top
  const by = dy + dh - 50;
  const sv = button(right, by, 'Save', T, { primary: true, anchor: 'end' });
  s += sv.s + button(right - sv.w - 10, by, 'Cancel', T, { anchor: 'end' }).s;
  return s;
}
// Settings → Sandbox, after Portable apps
const SETTINGS_SANDBOX = SETTINGS.flatMap(r => r[0] === 'section' && r[2] === 'accounts' ? [
  ['section', 'SANDBOX', 'sandbox'],
  ['note', 'Runs portable apps and AppImages in a sandbox (bubblewrap): their own home folder, their files read-only, and only the folders and network you allow. Flatpaks have their own sandbox.'],
  ['warnnote', 'This session lets any app capture the screen, read the clipboard and type into other windows — true on X11 (Mint’s default Cinnamon) and on wlroots Wayland (e.g. sway). The sandbox protects your files, not those; a GNOME/mutter Wayland session closes it, and AppKata will too in a later release.'],
  ['info', 'System support', 'A one-time setup this system needs before the sandbox can run (asks for your password once).', 'Not enabled', ['Set up…']],
  ['seg', 'New GUI apps', 'Reviewed apps follow their review; unreviewed GUI apps use Strict. Each app can differ, in its Install options.', ['Off', 'Standard', 'Strict'], 1],
  ['select', 'Apps no Trust has reviewed', '', 'Strict'],
  ['select', 'Command-line tools', 'The CLI tool template: they see only the folder they’re run in.', 'CLI tool'],
  ['toggle', 'Follow reviewers’ suggestions', 'The strictest suggestion of your Trusts, until you choose for an app.', true],
  ['toggle', 'Badge apps when reviews suggest a change', 'A new version keeps your grants and flags the app for review; it never widens access on its own.', true],
  ['info', 'Built-in templates', 'Offline editor · Online app · Messenger · Media player · Developer tool · CLI tool · Strict. Each app picks one, then tweaks.', '', ['Browse…']],
  ['info', 'Sandbox home folders', 'Each sandboxed app’s settings and files.', '~/.local/share/appkata/sandboxes', ['Open folder']],
  r] : [r]);
// Audit entries about sandboxes
const AUDIT_SANDBOX = [
  ['Today', [
    ['you', 'app', 'apps', 'You updated', 'Zettlr', [['version', '3.6.0'], ['from', '3.5.1']], 'github.com/Zettlr/Zettlr', '10:12:50'],
    ['you', 'app', 'shieldCheck', 'You allowed more access for', 'Zettlr', [['network', 'on'], ['folder', '~/Pictures']], '', '10:12:44'],
    ['sync', 'app', 'clock', 'Sync held the update to', 'Zettlr 3.6.0', [['asks', 'network, ~/Pictures'], ['by', 'mara-dev / foss-picks']], '', '07:00:14']]],
  ['Yesterday', [
    ['you', 'app', 'shieldCheck', 'You changed the sandbox of', 'KeePassXC', [['network', 'off'], ['folder', '~/Downloads read-only']], '', '21:03:11'],
    ['you', 'app', 'apps', 'You installed', 'Krita', [['version', '5.2.11'], ['sandbox', 'Standard'], ['folder', '~/Pictures']], 'invent.kde.org/graphics/krita', '18:40:02']]],
  ['Monday, September 28, 2026', [
    ['you', 'app', 'shieldCheck', 'You turned off the sandbox of', 'Syncthing', [['sandbox', 'Off']], '', '12:30:02']]],
];

// ---------------------------------------------------------------- output
const SCREENS = [
  ['A01-apps', T => appsView(T, { hoverTrash: 'keepassxc' }), ['dark', 'light']],
  ['A02-apps-detail', T => appsView(T, { detail: 'localsend', pencilHover: true }), ['dark', 'light']],
  ['A03-review-dialog', T => reviewDialog(T), ['dark', 'light']],
  ['A04-review-avoid-unsigned', T => reviewDialog(T, { app: 'signal', trust: 0, rating: 2, tags: ['saas', 'tracking'], unsigned: true,
    md: ['Needs a phone number and a Signal account; the desktop app', 'can’t be used on its own.', '', '- Crash reports go to a hosted endpoint by default.', '- **My call:** avoid until linking works without a phone.'].map(l => [l, T.text]) }), ['dark']],
  ['C01-catalog', T => catalogView(T), ['dark', 'light']],
  ['C02-catalog-detail', T => catalogView(T, { detail: 'krita' }), ['dark', 'light']],
  ['C03-catalog-foreign', T => catalogView(T, { detail: 'obs' }), ['dark']],
  ['C04-catalog-search-veto', T => catalogView(T, { search: 'vpn', keys: ['freevpnx', 'turbovpn', 'syncthing'], detail: 'turbovpn',
    note: '1 app hidden by a trusted reviewer is shown because it matches your search.' }), ['dark', 'light']],
  ['C05-catalog-tags', T => catalogView(T, { tagsHover: 'keepassxc' }), ['dark', 'light']],
  ['C06-install-options', T => installDialog(T), ['dark', 'light']],
  ['C08-catalog-empty', T => emptyState(T, 'catalog'), ['dark', 'light']],
  ['C09-install-windows-exe', T => exeChoiceDialog(T), ['dark']],
  ['C07-catalog-all-tags', T => catalogView(T, { allTags: true, busyTile: 'krita' }), ['dark', 'light']],
  ['S01-sources', T => sourcesView(T, { hover: { trust: 2, i: 1 } }), ['dark', 'light']],
  ['S02-trust-detail', T => sourcesView(T, { trust: 2 }), ['dark', 'light']],
  ['S03-source-menu', T => sourcesView(T, { menu: 6 }), ['dark']],
  ['S04-add-source', T => addSourceDialog(T), ['dark', 'light']],
  ['S05-remove-source', T => removeSourceDialog(T), ['dark']],
  ['S06-source-in-trusts', T => sourcesView(T, { trustHover: 0 }), ['dark', 'light']],
  ['A06-appkata-restart', T => appsView(T, { detail: 'appkata', selfUpdated: true }), ['dark', 'light']],
  ['A07-apps-installing', T => appsView(T, { busy: true }), ['dark', 'light']],
  ['A08-apps-detail-installing', T => appsView(T, { busy: true, detail: 'localsend' }), ['dark']],
  ['A09-app-updates-itself', T => appsView(T, { detail: 'syncthing' }), ['dark', 'light']],
  ['A10-confirm-uninstall', T => confirmDialog(T, appsView(T), { app: 'keepassxc', title: 'Uninstall KeePassXC?', action: 'Uninstall',
    body: 'KeePassXC 2.7.10 will be removed. Your settings and documents in your home folder are kept.' }), ['dark', 'light']],
  ['A11-confirm-remove-version', T => confirmDialog(T, versionsDetail(T), { app: 'zettlr', title: 'Remove Zettlr 3.5.0?', action: 'Remove version',
    body: 'This kept version will be deleted. You can still download it again from the list of versions.' }), ['dark']],
  ['A13-app-detail-menu', T => detailMenu(T), ['dark', 'light']],
  ['A14-apps-empty', T => emptyState(T, 'apps'), ['dark']],
  ['A15-toast-done', T => toastScene(T, false), ['dark', 'light']],
  ['A16-toast-error', T => toastScene(T, true), ['dark']],
  ['A05-apps-detail-versions', T => versionsDetail(T), ['dark', 'light']],
  ['S07-explore', T => exploreDialog(T), ['dark', 'light']],
  ['S08-source-settings', T => sourceSettingsDialog(T), ['dark', 'light']],
  ['S09-source-highlight', T => sourcesView(T, { highlight: 'syncthing' }), ['dark']],
  ['S14-add-trust', T => addTrustDialog(T), ['dark', 'light']],
  ['S15-trusts-collapsed', T => sourcesView(T, { collapsed: true }), ['dark']],
  ['S16-source-errors', T => sourcesView(T, { sources: SOURCE_ERRORS }), ['dark', 'light']],
  ['S10-confirm-remove-trust', T => confirmDialog(T, sourcesView(T, { trust: 1 }), { title: 'Remove mara-dev / foss-picks?', action: 'Remove trust',
    body: 'Its 38 reviews leave your Catalog, and its Authorities are removed with it.', extra: ['Keep updating as my sources', 'branch'],
    warn: { title: 'No other origin, so no more updates:', lines: ['Zettlr 3.5.1'], note: 'Keep updating as my sources adds them as your own Sources first.' } }), ['dark', 'light']],
  ['S11-confirm-remove-authority', T => confirmDialog(T, sourcesView(T, { trust: 2 }), { title: 'Remove Ade Bello?', action: 'Remove authority',
    body: 'Changes signed only by this key will no longer be accepted for desk-collective / reviews.' }), ['dark']],
  ['S12-confirm-trust-signer', T => confirmDialog(T, sourcesView(T, { trust: 2 }), { title: 'Trust nadia@desk.coop?', action: 'Trust signer', ic: 'shieldCheck', danger: false,
    body: 'Their signed changes to desk-collective / reviews will be accepted, including the ones waiting now.' }), ['dark']],
  ['S13-confirm-ignore-signer', T => confirmDialog(T, sourcesView(T, { trust: 2 }), { title: 'Ignore nadia@desk.coop?', action: 'Ignore', ic: 'ban',
    body: 'The changes they signed stay unapplied. If they sign again, AppKata asks again.' }), ['dark']],
  ['U01-audit', T => auditView(T), ['dark', 'light']],
  ['X01-app-menu', T => catalogView(T, { menu: true }), ['dark', 'light']],
  ['X02-tray', T => trayScene(T), ['dark', 'light']],
  ['X11-sync-progress', T => syncScene(T), ['dark']],
  ['X12-choose-review-file', T => reviewFileScene(T), ['dark']],
  ['X13-macos-menu-bar', T => macMenuBar(T), ['dark', 'light']],
  ['X10-appkata-md-settings', T => settingsStanza(T), ['dark', 'light']],
  // Package channels and versioned reviews (req 16, 10.3)
  ['C10-install-channels', withData({ APPS: { localsend: { ver: '1.18.2' } }, INSTALLED: { localsend: null }, STATE: { localsend: null } }, T => installChannelsDialog(T)), ['dark', 'light']],
  ['A17-apps-detail-system-updated', systemUpdatedScene, ['dark']],
  ['A18-apps-version-avoided', versionAvoidedScene, ['dark']],
  ['A19-review-dialog-version', withData({ APPS: { localsend: { ver: '2.0.1' } }, INSTALLED: { localsend: { from: '2.0.1', type: 'Flatpak' } } },
    T => reviewDialog(T, { tags: ['foss', 'donation', 'offline'], trust: 4, rating: 5,
      md: [['2.0 adds opt-out usage statistics. Still my pick for LAN', T.text], ['transfers, but I trust it a little less.', T.text]],
      version: { value: '2.0.1 · Installed', note: 'New review of 2.0.1. Your review of 1.18.2 (2026-03-04) stays in AppKata.md; Trust, Rating and Tags start from it.',
        details: ['- Date: 2026-10-05', '- Platform: linux x86_64', '- Channel: Flathub org.localsend.localsend_app 2.0.1', '- Commit: 3f9c…e21a'] } })), ['dark']],
  ['S17-explore-flathub', T => exploreFlathubDialog(T), ['dark']],
  ['X03-settings', T => settingsDialog(T), ['dark', 'light']],
  ['X04-settings-portable', T => settingsDialog(T, 'portable'), ['dark', 'light']],
  ['X05-settings-data', T => settingsDialog(T, 'accounts'), ['dark']],
  ['X06-about', T => aboutDialog(T), ['dark', 'light']],
  ['X14-install-appkata', T => selfInstallScene(T), ['dark', 'light']],
  ['X07-confirm-remove-token', T => confirmDialog(T, settingsDialog(T, 'accounts'), { title: 'Remove the token for github.com?', action: 'Remove token',
    body: 'AppKata will use github.com without a token, with its lower rate limit.' }), ['dark']],
  ['X08-confirm-remove-relay', T => confirmDialog(T, settingsDialog(T, 'accounts'), { title: 'Remove wss://nos.lol?', action: 'Remove relay',
    body: 'Explore will stop searching this relay for ngit repositories.' }), ['dark']],
  ['X09-confirm-quit', T => confirmDialog(T, appsView(T, { busy: true }), { title: 'Quit while installing?', action: 'Quit AppKata', ic: 'power',
    body: 'The install in progress is stopped. A download picks up where it left off the next time you install or update.',
    list: 'Installing: LocalSend (Downloading 45%), AppKata (Waiting), Signal Desktop (Waiting)' }), ['dark']],
  // App sandboxing on Linux (docs/app-sandboxing.md)
  ['C11-install-sandbox', T => installDialog(T, { sandbox: true }), ['dark', 'light']],
  ['A20-apps-detail-sandbox', sandboxScene({}, T => appsView(T, { detail: 'keepassxc' })), ['dark', 'light']],
  ['A21-sandbox-dialog', sandboxScene({}, T => sandboxDialog(T)), ['dark', 'light']],
  ['A25-sandbox-advanced', sandboxScene({}, T => sandboxAdvanced(T)), ['dark']],
  ['A22-update-review-badge', sandboxScene({ zettlr: { from: '3.6.0', type: 'AppImage', sandbox: SANDBOXED.zettlr.sandbox,
    reviewBadge: { ver: '3.6.0', by: 'mara-dev / foss-picks', what: ['the network', '~/Pictures'] } } },
    T => appsView(T, { detail: 'zettlr', upd: ['appkata', 'localsend', 'signal'], rest: ['flameshot', 'inkscape', 'keepassxc', 'syncthing', 'ventoy', 'zettlr'] })), ['dark']],
  ['A23-confirm-uninstall-sandbox', sandboxScene({}, T => confirmDialog(T, appsView(T), { app: 'keepassxc', title: 'Uninstall KeePassXC?', action: 'Uninstall',
    body: 'KeePassXC 2.7.10 will be removed. The folders you let it use are kept.',
    check: ['Also delete its sandbox home folder (24 MB)', '~/.local/share/appkata/sandboxes/keepassxc'] })), ['dark']],
  ['A24-sandbox-setup-needed', sandboxScene({
    keepassxc: { from: '2.7.10', type: 'AppImage', setupNeeded: true },
  }, T => appsView(T, { detail: 'keepassxc' })), ['dark']],
  ['X15-settings-sandbox', T => settingsDialog(T, 'sandbox', SETTINGS_SANDBOX), ['dark', 'light']],
  ['X16-appkata-md-sandbox', T => settingsStanza(T, 'sandbox'), ['dark']],
  ['U02-audit-sandbox', T => auditView(T, AUDIT_SANDBOX), ['dark']],
  // Windows only (req 15)
  ['W01-close-app', onWindows(T => confirmDialog(T, appsView(T), { app: 'keepassxc', title: 'Close KeePassXC to continue', action: 'Try again', ic: 'sync', danger: false,
    body: 'KeePassXC is running (KeePassXC.exe). Windows can’t replace or remove a running program’s files. Close it, then try again.' })), ['dark', 'light']],
  ['W02-install-options', onWindows(T => installDialogWindows(T)), ['dark', 'light']],
  ['W03-msvcrt', onWindows(T => confirmDialog(T, appsView(T, { detail: 'flameshot' }), { app: 'flameshot', title: 'Install the Visual C++ run-time?',
    action: 'Install run-time', ic: 'download', danger: false,
    body: 'Flameshot needs the Microsoft Visual C++ Run-time, which isn’t on this computer. AppKata downloads it from Microsoft and installs it for every account on this computer, so Windows asks for administrator rights once.' }), 'flameshot'), ['dark', 'light']],
  ['W04-msvcrt-chip', onWindows(T => appsView(T, { detail: 'flameshot', msvcrtTip: true }), 'flameshot'), ['dark', 'light']],
  ['W05-settings-windows', onWindows(T => settingsDialog(T, 'portable', SETTINGS_WIN)), ['dark', 'light']],
];

const only = process.argv[2];
for (const [name, draw, themes] of SCREENS) for (const theme of themes) {
  if (only && !name.includes(only)) continue;
  defs = []; uid = 0;
  const T = THEMES[theme];
  const body = draw(T);
  const frame = name === 'X02-tray' || name === 'X13-macos-menu-bar' ? `<g transform="translate(${PAD} ${PAD})"><g clip-path="url(#trayclip)">${body}</g></g>` : windowFrame(T, body);
  if (name === 'X02-tray' || name === 'X13-macos-menu-bar') defs.push(`<clipPath id="trayclip"><rect width="${W}" height="${H}" rx="14"/></clipPath>`);
  const bgG = `<rect width="${W + PAD * 2}" height="${H + PAD * 2}" fill="${T.backdrop[0]}"/>`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W + PAD * 2}" height="${H + PAD * 2}" viewBox="0 0 ${W + PAD * 2} ${H + PAD * 2}">` +
    `<defs>${baseDefs(T)}${defs.join('')}</defs>${name === 'X02-tray' || name === 'X13-macos-menu-bar' ? bgG : ''}${frame}</svg>`;
  fs.mkdirSync(path.join(OUT, 'src', 'svg', theme), { recursive: true });
  fs.mkdirSync(path.join(OUT, 'mocks', theme), { recursive: true });
  fs.writeFileSync(path.join(OUT, 'src', 'svg', theme, `${name}.svg`), svg);
  const png = new Resvg(svg, { fitTo: { mode: 'zoom', value: 2 }, font: { loadSystemFonts: true, defaultFontFamily: SANS } }).render().asPng();
  fs.writeFileSync(path.join(OUT, 'mocks', theme, `${name}.png`), png);
  console.log('wrote', `${theme}/${name}`);
}
