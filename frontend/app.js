"use strict";
// Plain JS, no build step. Served by FastAPI at /ui/, so API calls are same-origin (no CORS).
const $ = (s) => document.querySelector(s);
const money = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2 });
const when = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

// Tiny element builder. Uses textContent, so API data can never inject HTML.
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") el.className = v;
    else el.setAttribute(k, v);
  }
  el.append(...kids.flat().filter((x) => x != null));
  return el;
}
const on = (el, fn) => (el.addEventListener("click", fn), el);

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
  on(b, () => {
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
on($("#logout"), logout);

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
  $("#centers").replaceChildren(...(centers.length
    ? centers.map(centerCard)
    : [h("p", { class: "placeholder" }, "No centers yet. Run: python -m app.scripts.seed")]));
}

function centerCard(c) {
  return h("article", { class: "card" },
    h("div", { class: "card-head" }, h("strong", {}, c.name), h("span", { class: "sub" }, c.location)),
    c.tests.length
      ? c.tests.map((t) => h("div", { class: "test" },
          h("span", { class: "t-name" }, t.name),
          h("span", { class: "t-price" }, money.format(t.price)),
          on(h("button", { class: "btn ghost sm", type: "button" }, "Book"), () => openBooking(c, t))))
      : h("p", { class: "empty" }, "No tests offered yet."));
}

// ---------- booking dialog ----------
const dlg = $("#dlg");
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); }); // click on backdrop

// Value for <input type="datetime-local" min=...> (local time, minute precision).
function localNow() {
  return new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function openBooking(center, test) {
  const input = h("input", { type: "datetime-local", min: localNow(), required: "" });
  const confirm = h("button", { class: "btn", type: "button" }, "Confirm booking");
  const close = on(h("button", { class: "btn ghost", type: "button" }, "Cancel"), () => dlg.close());

  on(confirm, () => {
    if (!input.value) return toast("Pick a date and time", true);
    run(confirm, async () => {
      // datetime-local is local time without a zone; the API requires a timezone.
      const appointment_at = new Date(input.value).toISOString();
      const b = await api("/bookings", {
        method: "POST", body: { center_id: center.id, test_id: test.id, appointment_at },
      });
      dlg.close();
      toast(`Booking #${b.id} created for ${money.format(b.amount)}`);
      await loadBookings();
    });
  });

  dlg.replaceChildren(h("div", { class: "dlg-body" },
    h("h3", {}, `Book ${test.name}`),
    h("p", { class: "sub" }, `${center.name} - ${center.location}`),
    h("div", { class: "summary" }, h("span", {}, "Price"), h("strong", {}, money.format(test.price))),
    h("label", {}, "Appointment time", input),
    h("div", { class: "dlg-actions" }, close, confirm)));
  dlg.showModal();
}

// ---------- bookings ----------
function renderBookings(rows) {
  $("#count").textContent = rows.length;
  $("#bookings").replaceChildren(...(rows.length
    ? rows.map(bookingItem)
    : [h("p", { class: "placeholder" }, "No bookings yet. Choose a test above to get started.")]));
}

function bookingItem(b) {
  const actions = h("div", { class: "b-actions" });
  const act = (label, cls, fn) => {
    const btn = h("button", { class: `btn sm ${cls}`, type: "button" }, label);
    actions.append(on(btn, () => run(btn, fn)));
  };
  if (b.status === "PENDING") act("Pay now", "", () => pay(b));
  if (b.status === "PENDING" || b.status === "CONFIRMED") act("Cancel", "danger", () => cancel(b));

  return h("article", { class: "booking" },
    h("div", { class: "b-main" },
      h("strong", {}, names.test[b.test_id] || `Test ${b.test_id}`),
      h("span", { class: "sub" },
        `${names.center[b.center_id] || "Center " + b.center_id} - ${when(b.appointment_at)} - #${b.id}`)),
    h("div", { class: "b-amount" }, money.format(b.amount)),
    h("div", { class: "b-status" }, h("span", { class: `badge ${b.status}` }, b.status)),
    actions);
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
