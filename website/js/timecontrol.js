// The time controls of one map, bound to a Slot (slot.js):
//
//   - a drop-down for products with a few isolated timesteps (e.g. aerial
//     survey years), a calendar with the dates without data in view grayed
//     out for products with many (e.g. Landsat), a month grid for monthly
//     products, plus a time-of-day drop-down when a day has several
//     timesteps (hourly, 3-hourly); a plain label for single-timestep
//     (pre-built) products
//   - previous / next timestep with data in view, and "Latest" (the default)
//   - filters (e.g. max cloud cover)
//   - "Advanced": an end date (a window of images, mosaicked) and how the
//     images in the window are combined (latest / median / average pixel)

import { dayOf, keyLabel } from "./time.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]);
const LIST_MAX = 40; // "auto" widget: a drop-down up to this many timesteps

export class TimeControl {
  /** host: element to render into; compact: smaller (grid slots). */
  constructor(host, slot, { compact = false } = {}) {
    this.host = host;
    this.slot = slot;
    this.compact = compact;
    this.el = document.createElement("div");
    this.el.className = "time-control" + (compact ? " compact" : "");
    host.append(this.el);
    this.builtFor = null;
  }

  /** Re-render from the slot's state. */
  render() {
    const slot = this.slot;
    const p = slot.product;
    const time = p?.time;
    // Nothing to pick while the image cannot be shown at all (locked, cloud only, elsewhere).
    this.el.hidden = !time || !!slot.blocker();
    if (!time) {
      this.builtFor = null;
      this.el.innerHTML = "";
      return;
    }
    const key = `${p.id}|${slot.steps ? (this.widget() === "list" ? slot.steps.keys?.join() : "cal") : "none"}`;
    if (key !== this.builtFor) this.build();
    this.update();
  }

  /** "fixed" (one timestep), "list" or "calendar". */
  widget() {
    const time = this.slot.time;
    const a = time.availability;
    if (a.type === "list" && a.values.length === 1) return "fixed";
    if (time.widget === "list" || time.widget === "calendar") return time.widget;
    const n = this.slot.steps?.size ?? 0;
    return a.type === "list" || (n && n <= LIST_MAX && time.step !== "hour") ? "list" : "calendar";
  }

  // #region tc-build
  build() {
    const slot = this.slot;
    const p = slot.product;
    const time = p.time;
    this.builtFor = `${p.id}|${slot.steps ? (this.widget() === "list" ? slot.steps.keys?.join() : "cal") : "none"}`;
    const w = this.widget();
    const sub = time.step === "hour" || time.step === "time";
    const filters = time.filters ?? [];
    const win = time.window;
    this.el.innerHTML = `
      <span class="tc-label">${esc(time.label)}</span>
      ${
        w === "fixed"
          ? `<span class="tc-fixed" title="Pre-built for this timestep only"></span>`
          : `<button type="button" class="icon-btn tc-prev" title="Previous timestep with data in view">&#9664;</button>
             ${w === "list" ? `<select class="tc-list" aria-label="${esc(time.label)}"></select>` : `<button type="button" class="tc-date" aria-haspopup="dialog"></button>`}
             ${sub && w === "calendar" ? `<select class="tc-hour" aria-label="Time of day (UTC)"></select>` : ""}
             <button type="button" class="icon-btn tc-next" title="Next timestep with data in view">&#9654;</button>
             <button type="button" class="tc-latest btn subtle" title="Follow the latest timestep with data in view">Latest</button>`
      }
      ${filters
        .map(
          (f) => `<label class="tc-filter" title="${esc(f.label)}">
            <span>${esc(f.label)}</span>
            <input type="range" data-filter="${f.id}" min="${f.min}" max="${f.max}" step="${f.step}" />
            <output></output></label>`,
        )
        .join("")}
      ${win ? `<button type="button" class="tc-adv btn subtle" aria-expanded="false">Advanced &#9662;</button>` : ""}
      <span class="tc-status" aria-live="polite"></span>
      ${
        win
          ? `<div class="tc-advanced" hidden>
              <label class="tc-window"><input type="checkbox" /> ${esc(win.label)}</label>
              <button type="button" class="tc-date2" aria-haspopup="dialog"></button>
              ${win.options
                .map(
                  (o) => `<label class="tc-option" title="${esc(o.help)}">${esc(o.label)}
                    <select data-option="${o.id}">${o.choices.map((c) => `<option value="${esc(c.value)}">${esc(c.label)}</option>`).join("")}</select></label>`,
                )
                .join("")}
              <span class="tc-help">Images from the start to the end date are mosaicked (up to ${win.max_days} days).</span>
            </div>`
          : ""
      }`;
    const $ = (s) => this.el.querySelector(s);
    $(".tc-prev")?.addEventListener("click", () => slot.step(-1));
    $(".tc-next")?.addEventListener("click", () => slot.step(1));
    $(".tc-latest")?.addEventListener("click", () => slot.setTime({ t: null, t2: null }));
    $(".tc-list")?.addEventListener("change", (e) => slot.setTime({ t: e.target.value }));
    $(".tc-date")?.addEventListener("click", (e) => this.openCalendar(e.currentTarget, "start"));
    $(".tc-date2")?.addEventListener("click", (e) => this.openCalendar(e.currentTarget, "end"));
    $(".tc-hour")?.addEventListener("change", (e) => slot.setTime({ t: e.target.value }));
    this.el.querySelectorAll("[data-filter]").forEach((input) => {
      input.addEventListener("input", () => (input.nextElementSibling.value = fmtFilter(filters.find((f) => f.id === input.dataset.filter), +input.value)));
      input.addEventListener("change", () => slot.setTime({ f: { [input.dataset.filter]: +input.value } }));
    });
    this.el.querySelectorAll("[data-option]").forEach((sel) =>
      sel.addEventListener("change", () => slot.setTime({ o: { [sel.dataset.option]: sel.value } })),
    );
    const adv = $(".tc-adv");
    adv?.addEventListener("click", () => {
      const panel = $(".tc-advanced");
      panel.hidden = !panel.hidden;
      adv.setAttribute("aria-expanded", String(!panel.hidden));
    });
    if (slot.sel.t2 && $(".tc-advanced")) {
      $(".tc-advanced").hidden = false;
      adv.setAttribute("aria-expanded", "true");
    }
    $(".tc-window input")?.addEventListener("change", (e) => {
      if (!e.target.checked) return slot.setTime({ t2: null });
      const t = slot.sel.t ?? slot.steps?.latest();
      if (t) slot.setTime({ t: addDays(t, -30, slot.steps), t2: t });
    });
  }
  // #endregion tc-build

  update() {
    const slot = this.slot;
    const time = slot.time;
    const { t, t2, auto, f, o } = slot.sel;
    const steps = slot.steps;
    const $ = (s) => this.el.querySelector(s);
    const fixed = $(".tc-fixed");
    if (fixed) fixed.textContent = t ? (steps?.label(t) ?? keyLabel(t, time.step)) : "";
    const list = $(".tc-list");
    if (list && steps) {
      const keys = steps.keys ?? [];
      const missing = t && !steps.has(t) ? [t] : [];
      const html = [...missing, ...[...keys].reverse()]
        .map((k) => `<option value="${esc(k)}"${missing.includes(k) ? " disabled" : ""}>${esc(steps.label(k))}${missing.includes(k) ? " (no data in view)" : ""}</option>`)
        .join("");
      if (list.dataset.html !== html) {
        list.innerHTML = html;
        list.dataset.html = html;
      }
      list.value = t ?? "";
    }
    const date = $(".tc-date");
    if (date) {
      const sub = time.step === "hour" || time.step === "time";
      date.textContent = t ? keyLabel(sub ? dayOf(t) : t, sub ? "day" : time.step) : "No date";
      date.innerHTML += ' <span class="caret">▾</span>';
      date.disabled = !steps;
    }
    const hour = $(".tc-hour");
    if (hour) {
      const keys = t && steps ? steps.inDay(dayOf(t)) : [];
      hour.innerHTML = keys.map((k) => `<option value="${esc(k)}">${k.slice(11, 16)} UTC</option>`).join("") || `<option>--:--</option>`;
      hour.value = t ?? "";
      hour.disabled = keys.length < 2;
    }
    const prev = $(".tc-prev");
    if (prev) prev.disabled = !steps || !steps.neighbor(t, -1);
    const next = $(".tc-next");
    if (next) next.disabled = !steps || !t || !steps.neighbor(t, 1);
    const latest = $(".tc-latest");
    if (latest) {
      latest.classList.toggle("active", !!auto);
      latest.setAttribute("aria-pressed", String(!!auto));
    }
    this.el.querySelectorAll("[data-filter]").forEach((input) => {
      const spec = time.filters.find((x) => x.id === input.dataset.filter);
      if (document.activeElement !== input) input.value = f[spec.id] ?? spec.default;
      input.nextElementSibling.value = fmtFilter(spec, +input.value);
    });
    this.el.querySelectorAll("[data-option]").forEach((sel) => (sel.value = o[sel.dataset.option]));
    const win = $(".tc-window input");
    if (win) win.checked = !!t2;
    const date2 = $(".tc-date2");
    if (date2) {
      date2.hidden = !t2;
      date2.textContent = t2 ? keyLabel(t2, time.step) : "";
      date2.innerHTML += ' <span class="caret">▾</span>';
    }
    this.el.querySelectorAll("[data-option]").forEach((s) => (s.disabled = !t2));
    const status = $(".tc-status");
    status.classList.toggle("error", !!slot.stepsError);
    status.textContent = slot.stepsError
      ? "Could not list dates"
      : slot.loadingSteps
        ? "Finding imagery…"
        : steps && this.widget() !== "fixed" && time.availability.type !== "zarr" && time.availability.type !== "list"
          ? `${steps.size} ${unit(time.step, steps.size)} in view${steps.size !== slot.raw?.size ? ` (of ${slot.raw?.size})` : ""}`
          : "";
    status.title = slot.stepsError ?? "";
  }

  // #region calendar
  /** Calendar popup for the start (or with `which` = "end", the window's end). */
  openCalendar(anchor, which) {
    const slot = this.slot;
    const time = slot.time;
    const steps = slot.steps;
    if (!steps) return;
    const sub = time.step === "hour" || time.step === "time";
    const monthly = time.step === "month";
    const win = which === "end" || !!slot.sel.t2;
    const cur = which === "end" ? slot.sel.t2 : slot.sel.t;
    let view = (cur ?? steps.latest() ?? new Date().toISOString()).slice(0, monthly ? 4 : 7); // "YYYY" or "YYYY-MM"
    const minEnd = which === "end" ? dayOf(slot.sel.t) : null;
    const maxEnd = which === "end" ? addDays(slot.sel.t, time.window.max_days) : null;
    const pick = (k) => {
      closeCalendar();
      if (which === "end") return slot.setTime({ t2: k });
      if (sub) {
        const keys = steps.inDay(k);
        const prevTime = slot.sel.t?.slice(11);
        return slot.setTime({ t: keys.find((x) => x.slice(11) === prevTime) ?? keys.at(-1) });
      }
      let t2 = slot.sel.t2;
      if (t2 && (t2 < k || addDays(k, time.window.max_days) < t2)) t2 = addDays(k, Math.min(30, time.window.max_days));
      slot.setTime({ t: k, t2 });
    };
    const popup = calendarPopup();
    const draw = () => {
      const html = [];
      if (monthly) {
        const y = +view;
        html.push(header(String(y)));
        html.push('<div class="cal-months">');
        for (let m = 1; m <= 12; m++) {
          const k = `${y}-${String(m).padStart(2, "0")}`;
          const ok = steps.has(k);
          html.push(`<button type="button" data-k="${k}" class="${k === cur ? "sel" : ""}" ${ok ? "" : "disabled"}>${keyLabel(k, "month", { short: true }).slice(0, 3)}</button>`);
        }
        html.push("</div>");
      } else {
        const [y, m] = view.split("-").map(Number);
        html.push(header(keyLabel(view, "month")));
        html.push('<div class="cal-grid"><span>Mo</span><span>Tu</span><span>We</span><span>Th</span><span>Fr</span><span>Sa</span><span>Su</span>');
        const first = new Date(Date.UTC(y, m - 1, 1));
        const lead = (first.getUTCDay() + 6) % 7;
        for (let i = 0; i < lead; i++) html.push("<span></span>");
        const n = new Date(Date.UTC(y, m, 0)).getUTCDate();
        for (let d = 1; d <= n; d++) {
          const k = `${view}-${String(d).padStart(2, "0")}`;
          const has = steps.hasDay(k);
          let ok = has;
          if (which === "end") ok = k >= minEnd && k <= maxEnd;
          else if (win) ok = true; // a window may start on any day
          const cls = [has ? "has" : "", k === (cur && dayOf(cur)) ? "sel" : "", which === "end" && k >= minEnd && k <= (cur ?? "") ? "inrange" : ""].join(" ");
          html.push(`<button type="button" data-k="${k}" class="${cls}" ${ok ? "" : "disabled"} title="${has ? "Imagery in view" : "No imagery in view"}">${d}</button>`);
        }
        html.push("</div>");
      }
      html.push(`<div class="cal-foot"><span class="cal-key"><i class="dot"></i> data in view</span>
        ${which === "end" ? "" : '<button type="button" class="btn subtle cal-latest">Latest</button>'}</div>`);
      popup.innerHTML = html.join("");
      popup.querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => pick(b.dataset.k)));
      popup.querySelector(".cal-prev").addEventListener("click", () => move(-1));
      popup.querySelector(".cal-next").addEventListener("click", () => move(1));
      popup.querySelector(".cal-prev-data")?.addEventListener("click", () => jump(-1));
      popup.querySelector(".cal-next-data")?.addEventListener("click", () => jump(1));
      popup.querySelector(".cal-latest")?.addEventListener("click", () => {
        closeCalendar();
        slot.setTime({ t: null, t2: null });
      });
      popup.querySelector(".cal-year")?.addEventListener("change", (e) => {
        view = monthly ? e.target.value : `${e.target.value}${view.slice(4)}`;
        draw();
      });
    };
    const header = (title) => {
      const y0 = +((steps.first?.() ?? "1950").slice(0, 4));
      const y1 = Math.max(+((steps.latest?.() ?? "2030").slice(0, 4)), new Date().getUTCFullYear());
      const years = [];
      for (let y = y1; y >= y0; y--) years.push(`<option ${String(y) === view.slice(0, 4) ? "selected" : ""}>${y}</option>`);
      return `<div class="cal-head">
        <button type="button" class="icon-btn cal-prev-data" title="Previous ${monthly ? "year" : "month"} with data">&#9198;</button>
        <button type="button" class="icon-btn cal-prev" title="Previous ${monthly ? "year" : "month"}">&#8249;</button>
        <span class="cal-title">${esc(monthly ? "" : title.replace(/ \d{4}$/, ""))}</span>
        <select class="cal-year" aria-label="Year">${years.join("")}</select>
        <button type="button" class="icon-btn cal-next" title="Next ${monthly ? "year" : "month"}">&#8250;</button>
        <button type="button" class="icon-btn cal-next-data" title="Next ${monthly ? "year" : "month"} with data">&#9197;</button>
      </div>`;
    };
    const move = (d) => {
      if (monthly) view = String(+view + d);
      else {
        const [y, m] = view.split("-").map(Number);
        const dt = new Date(Date.UTC(y, m - 1 + d, 1));
        view = dt.toISOString().slice(0, 7);
      }
      draw();
    };
    const jump = (d) => {
      // nearest month (year) with data, before / after the one shown
      const probe = monthly ? `${view}-${d < 0 ? "01" : "12"}` : `${view}-${d < 0 ? "01" : "31"}`;
      const k = steps.neighbor(d < 0 ? probe : `${probe}￿`, d);
      if (k) {
        view = k.slice(0, monthly ? 4 : 7);
        draw();
      }
    };
    draw();
    showCalendar(anchor, this);
  }
  // #endregion calendar
}

function unit(step, n) {
  const u = { year: "year", month: "month", day: "date", hour: "hour", time: "time" }[step];
  return n === 1 ? u : `${u}s`;
}

function fmtFilter(f, v) {
  return `≤ ${v}${f.unit}`;
}

/** The day `n` days after a key's day ("YYYY-MM-DD"). */
function addDays(key, n) {
  const d = new Date(`${dayOf(key)}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

// --------------------------------------------------------------------------
// The shared calendar popup
// --------------------------------------------------------------------------

let openFor = null;

function calendarPopup() {
  let el = document.getElementById("time-popup");
  if (!el) {
    el = document.createElement("div");
    el.id = "time-popup";
    el.className = "time-popup";
    el.setAttribute("role", "dialog");
    el.hidden = true;
    document.body.append(el);
  }
  return el;
}

function showCalendar(anchor, owner) {
  const el = calendarPopup();
  openFor = { anchor, owner };
  el.hidden = false;
  const b = anchor.getBoundingClientRect();
  const w = 300;
  el.style.left = `${Math.max(8, Math.min(b.left, window.innerWidth - w - 8))}px`;
  const below = window.innerHeight - b.bottom;
  if (below < 330 && b.top > below) {
    el.style.top = "";
    el.style.bottom = `${window.innerHeight - b.top + 4}px`;
  } else {
    el.style.bottom = "";
    el.style.top = `${b.bottom + 4}px`;
  }
  el.querySelector(".sel, .has, button[data-k]:not([disabled])")?.focus({ preventScroll: true });
}

export function closeCalendar() {
  const el = document.getElementById("time-popup");
  if (el && !el.hidden) {
    el.hidden = true;
    el.innerHTML = "";
    openFor?.anchor?.focus({ preventScroll: true });
  }
  openFor = null;
}

export const calendarOpen = () => !!openFor;

document.addEventListener("pointerdown", (e) => {
  const el = document.getElementById("time-popup");
  if (openFor && el && !el.contains(e.target) && !openFor.anchor.contains(e.target)) closeCalendar();
});
document.addEventListener("keydown", (e) => {
  if (openFor && e.key === "Escape") {
    e.preventDefault();
    closeCalendar();
  }
});
window.addEventListener("resize", closeCalendar);
