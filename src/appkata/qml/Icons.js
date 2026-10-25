.pragma library
// 16-unit icon paths, the same set as the mockups (screenshots/src/render.js).
function circle(cx, cy, r) {
    return `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`
}
function rrect(x, y, w, h, r) {
    return `M${x + r} ${y}H${x + w - r}A${r} ${r} 0 0 1 ${x + w} ${y + r}V${y + h - r}A${r} ${r} 0 0 1 ${x + w - r} ${y + h}` +
           `H${x + r}A${r} ${r} 0 0 1 ${x} ${y + h - r}V${y + r}A${r} ${r} 0 0 1 ${x + r} ${y}Z`
}
const shield = "M8 1.8L13.5 4V8C13.5 11 11.2 13.3 8 14.3C4.8 13.3 2.5 11 2.5 8V4Z"
const S = {
    grid: rrect(2, 2, 5, 5, 1.3) + rrect(9, 2, 5, 5, 1.3) + rrect(2, 9, 5, 5, 1.3) + rrect(9, 9, 5, 5, 1.3),
    apps: rrect(2, 2.5, 12, 3, 1) + rrect(2, 6.5, 12, 3, 1) + rrect(2, 10.5, 12, 3, 1),
    branch: circle(4.5, 3.5, 1.6) + circle(4.5, 12.5, 1.6) + circle(11.5, 5.5, 1.6) + " M4.5 5.1V10.9M11.5 7.1C11.5 9.5 8 9 4.5 10.9",
    chevDown: "M4 6L8 10L12 6", chevRight: "M6 4L10 8L6 12", chevLeft: "M10 4L6 8L10 12", chevUp: "M4 10L8 6L12 10",
    plus: "M8 3V13M3 8H13", x: "M4 4L12 12M12 4L4 12",
    minimize: "M4 8.5H12", maximize: rrect(3.5, 3.5, 9, 9, 1.2),
    restore: rrect(3, 5.5, 7.5, 7.5, 1.2) + " M5.5 5.5V4A1 1 0 0 1 6.5 3H12A1 1 0 0 1 13 4V9.5A1 1 0 0 1 12 10.5H10.5",
    pencil: "M10.5 2.5L13.5 5.5L5.5 13.5H2.5V10.5Z M9 4L12 7",
    panel: rrect(1.8, 2.8, 12.4, 10.4, 2) + " M10 3V13",
    check: "M3 8.5L6.5 12L13 4.5",
    warn: "M8 2L14.5 13.5H1.5Z M8 6.3V9.3",
    trash: "M3 4.5H13M6 4.5V2.8H10V4.5M4.5 4.5L5.3 13.5H10.7L11.5 4.5",
    refresh: "M13 8A5 5 0 1 1 11.5 4.4 M11.8 1.8V4.8H8.8",
    search: circle(7, 7, 4.5) + " M10.4 10.4L14 14",
    download: "M8 2.5V10.5M4.5 7L8 10.5L11.5 7 M2.5 13.5H13.5",
    update: circle(8, 8, 6) + " M8 11V5M5.4 7.4L8 4.8L10.6 7.4",
    open: "M9 3H13V7M13 3L7.5 8.5M11 9.5V13H3V5H6.5",
    shield: shield,
    shieldCheck: shield + " M5.5 8.2L7.3 10L10.6 6.4",
    pin: "M6 2H10L9.5 6.5L12 9H4L6.5 6.5Z M8 9V14",
    clock: circle(8, 8, 6) + " M8 4.8V8L10.2 9.6",
    key: circle(5, 10.5, 3) + " M7.2 8.4L13 2.6M11 4.6L12.8 6.4M9.6 6L11 7.4",
    info: circle(8, 8, 6) + " M8 7.2V11",
    filter: "M2 3.5H14M4.5 8H11.5M7 12.5H9",
    sort: "M4.5 2.5V13.5M2 11L4.5 13.5L7 11M11.5 13.5V2.5M9 5L11.5 2.5L14 5",
    sync: "M2.8 6.5A5.3 5.3 0 0 1 12.6 5M13.2 9.5A5.3 5.3 0 0 1 3.4 11 M12.8 2.2V5.2H9.8M3.2 13.8V10.8H6.2",
    gear: circle(8, 8, 2.2) + " M8 1.8V3.6M8 12.4V14.2M1.8 8H3.6M12.4 8H14.2M3.6 3.6L4.9 4.9M11.1 11.1L12.4 12.4M3.6 12.4L4.9 11.1M11.1 4.9L12.4 3.6",
    globe: circle(8, 8, 6) + " M2 8H14M8 2C10 4 10 12 8 14M8 2C6 4 6 12 8 14",
    lock: rrect(3, 7, 10, 7, 1.6) + " M5.5 7V5a2.5 2.5 0 0 1 5 0V7",
    folder: "M2 4.5A1.5 1.5 0 0 1 3.5 3H6.5L8 4.5H12.5A1.5 1.5 0 0 1 14 6V12A1.5 1.5 0 0 1 12.5 13.5H3.5A1.5 1.5 0 0 1 2 12Z",
    ban: circle(8, 8, 6) + " M3.8 12.2L12.2 3.8",
    copy: rrect(5, 5, 9, 9, 1.6) + " M3 11V3.6A1.6 1.6 0 0 1 4.6 2H11",
    window: rrect(2, 3, 12, 10, 2) + " M2 6H14",
    power: "M8 2V8 M4.6 4.2A5 5 0 1 0 11.4 4.2",
    star: "M8 1.5L9.9 5.6L14.3 6.1L11 9.1L11.9 13.5L8 11.3L4.1 13.5L5 9.1L1.7 6.1L6.1 5.6Z",
    link: "M9 3H13V7M13 3L7.5 8.5M11 9.5V13H3V5H6.5",
    bold: "M5 3H9a2.5 2.5 0 0 1 0 5H5Z M5 8H10a2.5 2.5 0 0 1 0 5H5Z",
    italic: "M7 3H12M4 13H9M10 3L6 13",
    list: "M6 4H14M6 8H14M6 12H14",
    audit: rrect(3, 2, 10, 12, 1.6) + " M5.5 5.5H10.5M5.5 8H10.5M5.5 10.5H8",
    log: "M3 2.5H10L13 5.5V13.5H3Z M10 2.5V5.5H13 M5.5 8H10.5M5.5 10.5H10.5",
    compass: circle(8, 8, 6) + " M10.5 5.5L9 9L5.5 10.5L7 7Z",
    star2: "M8 1.5L9.9 5.6L14.3 6.1L11 9.1L11.9 13.5L8 11.3L4.1 13.5L5 9.1L1.7 6.1L6.1 5.6Z",
    play: "M5 3.5L12 8L5 12.5Z",
    save: "M3 2.5H11L13.5 5V13.5H2.5V3Z M5 2.5V6H10V2.5 M5 13.5V9.5H11V13.5",
}
const F = {
    dots: circle(8, 3, 1.25) + circle(8, 8, 1.25) + circle(8, 13, 1.25),
    more: circle(3, 8, 1.3) + circle(8, 8, 1.3) + circle(13, 8, 1.3),
    warn: circle(8, 11.5, 0.7),
    info: circle(8, 5, 0.8),
    list: circle(3, 4, 0.9) + circle(3, 8, 0.9) + circle(3, 12, 0.9),
    play: "M5 3.5L12 8L5 12.5Z",
}
function stroke(name) { return S[name] || "M0 0" }
function fill(name) { return F[name] || "M0 0" }
// a five-point star of radius r around (cx, cy)
function starPath(cx, cy, r) {
    let d = ""
    for (let i = 0; i < 10; i++) {
        const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.45 : r
        d += (i ? "L" : "M") + (cx + rr * Math.cos(a)).toFixed(2) + " " + (cy + rr * Math.sin(a)).toFixed(2)
    }
    return d + "Z"
}
