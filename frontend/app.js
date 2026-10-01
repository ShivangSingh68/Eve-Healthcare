"use strict";
// Plain JS, no build step. Served by FastAPI at /ui/, so API calls are same-origin (no CORS).
const $ = (s) => document.querySelector(s);
const money = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2 });
const when = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

// Tiny element builder. Uses textContent, so API data can never inject HTML.
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v);
  }
  el.append(...kids.flat().filter((x) => x != null));
  return el;
}

let toastTimer;
function toast(text, isError = false) {
  const t = $("#toast");
  t.textContent = text;
  t.className = "show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = ""), 4000);
}

function errorText(data, status) {
  const d = data && data.detail;
  if (Array.isArray(d)) return d.map((e) => `${e.loc.slice(1).join(".")}: ${e.msg}`).join("; ");
  return d || `Request failed (${status})`;
}

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  const token = localStorage.getItem("token");
  if (body) headers["Content-Type"] = "application/json";
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { method, headers, body: body && JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && auth) logout();
    throw new Error(errorText(data, res.status));
  }
  return data;
}

// Run an async action, show errors as toasts, disable the button meanwhile.
async function run(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; }
}

// ---------- auth ----------
let mode = "login";
document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    mode = b.dataset.mode;
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $("#nameRow").hidden = $("#pwHint").hidden = mode !== "signup";
    $("#authSubmit").textContent = mode === "signup" ? "Create account" : "Log in";
  })
);

$("#authForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  run($("#authSubmit"), async () => {
    if (mode === "signup") {
      await api("/auth/signup", { method: "POST", auth: false, body: f });
      toast("Account created");
    }
    const tok = await api("/auth/login", {
      method: "POST", auth: false, body: { email: f.email, password: f.password },
    });
    localStorage.setItem("token", tok.access_token);
    e.target.reset();
    await start();
  });
});

function logout() {
  localStorage.removeItem("token");
  $("#auth").hidden = false;
  $("#app").hidden = $("#who").hidden = true;
}
$("#logout").addEventListener("click", logout);

// ---------- data ----------
let centers = [];   // each: {id, name, location, tests: [{id, name, price}]}
const names = { center: {}, test: {} };

async function loadCenters() {
  const list = await api("/centers?limit=100", { auth: false });
  centers = await Promise.all(list.map((c) => api(`/centers/${c.id}`, { auth: false })));
  for (const c of centers) {
    names.center[c.id] = c.name;
    for (const t of c.tests) names.test[t.id] = t.name;
  }
  renderCenters();
}

async function loadBookings() {
  renderBookings(await api("/bookings?limit=100"));
}

async function start() {
  if (!localStorage.getItem("token")) return;
  try {
    const me = await api("/auth/me");
    $("#email").textContent = me.email;
    $("#auth").hidden = true;
    $("#app").hidden = $("#who").hidden = false;
    await loadCenters();
    await loadBookings();
  } catch (e) { toast(e.message, true); }
}

// ---------- centers ----------
function renderCenters() {
  const box = $("#centers");
  if (!centers.length) {
    box.replaceChildren(h("p", { class: "muted" }, "No centers yet. Run: python -m app.scripts.seed"));
    return;
  }
  box.replaceChildren(...centers.map(centerCard));
}

function centerCard(c) {
  return h("div", { class: "card" },
    h("strong", {}, c.name), h("div", { class: "muted" }, c.location),
    c.tests.length ? c.tests.map((t) => testRow(c, t)) : h("p", { class: "muted" }, "No tests offered."));
}

function testRow(center, test) {
  const wrap = h("div");
  const bookBtn = h("button", { class: "ghost" }, "Book");
  wrap.append(h("div", { class: "test" },
    h("span", {}, test.name), h("span", { class: "price" }, money.format(test.price)), bookBtn));
  bookBtn.addEventListener("click", () => {
    if (wrap.querySelector(".bookform")) return wrap.querySelector(".bookform").remove();
    const input = h("input", { type: "datetime-local", required: "" });
    const ok = h("button", {}, "Confirm");
    ok.addEventListener("click", () => {
      if (!input.value) return toast("Pick a date and time", true);
      run(ok, async () => {
        // datetime-local is local time without a zone; the API requires a timezone.
        const appointment_at = new Date(input.value).toISOString();
        const b = await api("/bookings", {
          method: "POST", body: { center_id: center.id, test_id: test.id, appointment_at },
        });
        toast(`Booking #${b.id} created (amount ${money.format(b.amount)})`);
        wrap.querySelector(".bookform").remove();
        await loadBookings();
      });
    });
    wrap.append(h("div", { class: "bookform" }, input, ok));
  });
  return wrap;
}

// ---------- bookings ----------
function renderBookings(rows) {
  const box = $("#bookings");
  if (!rows.length) return box.replaceChildren(h("p", { class: "muted" }, "No bookings yet."));
  box.replaceChildren(h("table", {},
    h("thead", {}, h("tr", {}, ...["#", "Test / Center", "Appointment", "Amount", "Status", ""].map((x) => h("th", {}, x)))),
    h("tbody", {}, ...rows.map(bookingRow))));
}

function bookingRow(b) {
  const actions = h("td", { class: "actions" });
  if (b.status === "PENDING") actions.append(action("Pay", "", () => pay(b)));
  if (b.status === "PENDING" || b.status === "CONFIRMED") actions.append(action("Cancel", "danger", () => cancel(b)));
  return h("tr", {},
    h("td", {}, String(b.id)),
    h("td", {}, `${names.test[b.test_id] || "Test " + b.test_id} @ ${names.center[b.center_id] || "Center " + b.center_id}`),
    h("td", {}, when(b.appointment_at)),
    h("td", { class: "price" }, money.format(b.amount)),
    h("td", {}, h("span", { class: `badge ${b.status}` }, b.status)),
    actions);
}

function action(label, cls, fn) {
  const btn = h("button", { class: cls || "ghost" }, label);
  btn.addEventListener("click", () => run(btn, fn));
  return btn;
}

async function pay(b) {
  const p = await api("/payments/", { method: "POST", body: { booking_id: b.id } });
  toast(`Payment ${p.status} - booking is now ${p.booking_status}`, p.status === "FAILED");
  await loadBookings();
}

async function cancel(b) {
  await api(`/bookings/${b.id}/cancel`, { method: "POST" });
  toast(`Booking #${b.id} cancelled`);
  await loadBookings();
}

start();
