// ═══════════════════════════════════════════════════════════════
//  TOW Intelligence Dashboard — vanilla JS SPA  (Chart.js 4 edition)
//  13 charts across 5 data tabs, no build step required.
// ═══════════════════════════════════════════════════════════════

const API = window.location.origin;
const TOKEN_KEY = "tow_token";
const USER_KEY  = "tow_user";

// ── AUTH HELPERS ──────────────────────────────────────────────────
function saveAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}
function getToken()  { return localStorage.getItem(TOKEN_KEY); }
function getUser()   { try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); } catch { return null; } }
function clearAuth() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); }
function isAdmin()   { const u = getUser(); return u && ["admin","super_admin"].includes(u.role); }
function isAnalyst() { const u = getUser(); return u && ["analyst","admin","super_admin"].includes(u.role); }

// ── API FETCH ─────────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  const token = getToken();
  const res = await fetch(API + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) { logout(); return null; }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ── CACHE ─────────────────────────────────────────────────────────
const _cache = {};
async function cachedFetch(key, path, ttl = 60000) {
  const now = Date.now();
  if (_cache[key] && now - _cache[key].ts < ttl) return _cache[key].data;
  const data = await apiFetch(path);
  _cache[key] = { data, ts: now };
  return data;
}
function invalidateCache(key) { delete _cache[key]; }

// ══════════════════════════════════════════════════════════════════
//  CHART ENGINE
// ══════════════════════════════════════════════════════════════════

const _charts = new Map();  // id → Chart instance

/** Create (or recreate) a Chart.js instance on a canvas. */
function mkChart(id, cfg) {
  if (_charts.has(id)) {
    try { _charts.get(id).destroy(); } catch {}
  }
  const canvas = document.getElementById(id);
  if (!canvas) return null;
  const chart = new Chart(canvas, cfg);   // eslint-disable-line no-undef
  _charts.set(id, chart);
  return chart;
}

// ── Design tokens matching the green theme ────────────────────────
const CL = {
  green:   "#2E7D32",  greenL:   "#A5D6A7",  greenFill: "rgba(46,125,50,.13)",
  yellow:  "#F9A825",  yellowL:  "rgba(249,168,37,.25)",
  red:     "#C62828",  redL:     "rgba(198,40,40,.2)",
  blue:    "#1565C0",  blueL:    "rgba(21,101,192,.2)",
  purple:  "#6A1B9A",  orange:   "#E65100",
  teal:    "#00796B",  pink:     "#C2185B",
  brown:   "#5D4037",  indigo:   "#283593",
  grid:    "#D8E8D8",  text:     "#4A6A4A",   text2: "#7A9A7A",
};

// Ordered palette for multi-series / categorical charts
const PALETTE = [
  CL.green, CL.blue, CL.orange, CL.purple,
  CL.teal, CL.pink, CL.brown, CL.indigo, CL.yellow,
];

/** Shared Chart.js defaults for every chart. */
function baseOpts(extra = {}) {
  const { plugins: extraPlugins = {}, ...rest } = extra;
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 450 },
    plugins: {
      legend: {
        labels: {
          color: CL.text,
          font: { size: 11, family: "inherit" },
          boxWidth: 12,
          padding: 10,
        },
      },
      tooltip: {
        backgroundColor: "#1A2E1A",
        titleColor: "#fff",
        bodyColor: "#A5D6A7",
        cornerRadius: 6,
        padding: 8,
      },
      ...extraPlugins,
    },
    ...rest,
  };
}

// ── Shared scale presets ──────────────────────────────────────────
const scaleX = { grid: { display: false }, ticks: { color: CL.text, maxRotation: 28 } };
const scaleY = { grid: { color: CL.grid }, ticks: { color: CL.text }, beginAtZero: true };
const scaleXh = { grid: { color: CL.grid }, ticks: { color: CL.text } };            // horiz bar x
const scaleYh = { grid: { display: false }, ticks: { color: CL.text, font: { size: 11 } } }; // horiz bar y

// ── Primitive chart builders ──────────────────────────────────────

/** Doughnut / pie with arbitrary labels + colors. */
function drawDonut(id, labels, values, colors) {
  if (!labels.length || values.every(v => !v)) return;
  mkChart(id, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderWidth: 2,
        borderColor: "#fff",
        hoverOffset: 6,
      }],
    },
    options: baseOpts({
      cutout: "62%",
      plugins: {
        legend: { position: "bottom", labels: { color: CL.text, font: { size: 11 }, boxWidth: 12, padding: 10 } },
        tooltip: { backgroundColor: "#1A2E1A", titleColor: "#fff", bodyColor: "#A5D6A7", cornerRadius: 6 },
      },
    }),
  });
}

/** Horizontal bar chart — single dataset. */
function drawHBar(id, labels, values, colors) {
  if (!labels.length) return;
  const bg = Array.isArray(colors) ? colors : labels.map((_, i) => PALETTE[i % PALETTE.length]);
  mkChart(id, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: bg,
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: baseOpts({
      indexAxis: "y",
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: "#1A2E1A", titleColor: "#fff", bodyColor: "#A5D6A7", cornerRadius: 6 },
      },
      scales: { x: scaleXh, y: scaleYh },
    }),
  });
}

/** Vertical bar chart — one or more datasets. */
function drawVBar(id, labels, datasets, yPrefix = "") {
  if (!labels.length) return;
  mkChart(id, {
    type: "bar",
    data: { labels, datasets },
    options: baseOpts({
      plugins: {
        legend: {
          display: datasets.length > 1,
          labels: { color: CL.text, font: { size: 11 }, boxWidth: 12 },
        },
        tooltip: {
          backgroundColor: "#1A2E1A", titleColor: "#fff", bodyColor: "#A5D6A7", cornerRadius: 6,
          callbacks: yPrefix ? { label: ctx => `${yPrefix}${ctx.formattedValue}` } : {},
        },
      },
      scales: {
        x: scaleX,
        y: { ...scaleY, ticks: { ...scaleY.ticks, callback: v => yPrefix + v } },
      },
    }),
  });
}

// ── High-level semantic helpers ───────────────────────────────────

/** Doughnut with semantic colours for positive / neutral / negative. */
function drawSentimentDonut(id, splitData) {
  const map = { positive: CL.green, neutral: CL.yellow, negative: CL.red };
  const entries = Object.entries(splitData).filter(([, v]) => v > 0);
  if (!entries.length) return;
  drawDonut(
    id,
    entries.map(([k]) => k.charAt(0).toUpperCase() + k.slice(1)),
    entries.map(([, v]) => v),
    entries.map(([k]) => map[k] || CL.blue)
  );
}

/**
 * Vertical bar chart for star ratings 1–5.
 * starCounts: { 1: N, 2: M, 3: P, 4: Q, 5: R }
 */
function drawStarBar(id, starCounts) {
  const labels = ["1 ★", "2 ★", "3 ★", "4 ★", "5 ★"];
  const values = [1, 2, 3, 4, 5].map(s => starCounts[s] || 0);
  // traffic-light gradient: red → orange → yellow → lime → green
  const colors = ["#B71C1C", "#E65100", "#F9A825", "#7CB342", "#2E7D32"];
  drawVBar(id, labels, [{
    label: "Reviews",
    data: values,
    backgroundColor: colors,
    borderRadius: 6,
    borderSkipped: false,
  }]);
}

/** Count occurrences of a field across an array of objects. */
function countBy(arr, field) {
  return arr.reduce((acc, item) => {
    const k = item[field];
    if (k != null && k !== "") acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});
}

// ══════════════════════════════════════════════════════════════════
//  APP BOOT
// ══════════════════════════════════════════════════════════════════

function showApp() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  const user = getUser();
  if (user) {
    document.getElementById("user-role-badge").textContent = user.role;
    document.getElementById("user-email-short").textContent = (user.email || "").split("@")[0];
  }
  if (isAdmin()) document.getElementById("ingest-btn").classList.remove("hidden");
  connectWebSocket();
  loadTab("overview");
}

function logout() {
  clearAuth();
  wsClose();
  document.getElementById("app").classList.add("hidden");
  document.getElementById("login-screen").classList.remove("hidden");
}

// ── Login form ────────────────────────────────────────────────────
document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email    = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const err      = document.getElementById("login-error");
  err.textContent = "";
  try {
    const body = new URLSearchParams({ username: email, password });
    const res  = await fetch(API + "/auth/login", { method: "POST", body });
    if (!res.ok) { err.textContent = "Invalid email or password."; return; }
    const data = await res.json();
    saveAuth(data.access_token, { email, role: data.role });
    showApp();
  } catch {
    err.textContent = "Cannot connect to server.";
  }
});

// ── Tab routing ───────────────────────────────────────────────────
const TAB_TITLES = {
  "overview":         ["Overview",          "Real-time competitive intelligence"],
  "app-experience":   ["App Experience",    "App Store & Play Store analytics"],
  "product-quality":  ["Product Quality",   "Catalogue, pricing & stock intelligence"],
  "store-experience": ["Store Reviews",     "Google Maps & in-store review analytics"],
  "market-intel":     ["Market Intel",      "News, signals, competitors & pricing"],
  "explorer":         ["Review Explorer",   "Full-text search across all review sources"],
  "live-feed":        ["Live Feed",         "Real-time event stream via WebSocket"],
};

document.querySelectorAll(".nav-item").forEach(el => {
  el.addEventListener("click", () => { switchTab(el.dataset.tab); loadTab(el.dataset.tab); });
});

function switchTab(tab) {
  document.querySelectorAll(".nav-item").forEach(n =>
    n.classList.toggle("active", n.dataset.tab === tab)
  );
  document.querySelectorAll(".tab-panel").forEach(p => {
    const id = p.id.replace("tab-", "");
    p.classList.toggle("hidden", id !== tab);
    p.classList.toggle("active",  id === tab);
  });
  const [title, sub] = TAB_TITLES[tab] || ["Dashboard", ""];
  document.getElementById("tab-title").textContent = title;
  document.getElementById("tab-sub").textContent   = sub;
}

async function loadTab(tab) {
  switch (tab) {
    case "overview":         await loadOverview();         break;
    case "app-experience":   await loadAppExperience();    break;
    case "product-quality":  await loadProductQuality();   break;
    case "store-experience": await loadStoreExperience();  break;
    case "market-intel":     await loadMarketIntel();      break;
  }
}

// ══════════════════════════════════════════════════════════════════
//  TAB: OVERVIEW
// ══════════════════════════════════════════════════════════════════
async function loadOverview() {
  const [summary, appSum, prodSum, alerts] = await Promise.all([
    cachedFetch("summary",      "/dashboard/summary"),
    cachedFetch("app-summary",  "/dashboard/app-summary"),
    cachedFetch("prod-summary", "/dashboard/product-summary"),
    cachedFetch("alerts",       "/alerts?only_unack=true&hours=48"),
  ]);
  if (!summary) return;

  // ── KPI tiles ─────────────────────────────────────────────────
  document.getElementById("kv-reviews").textContent = (summary.review_count || 0).toLocaleString();
  document.getElementById("ks-reviews").textContent = summary.avg_rating
    ? `★ ${summary.avg_rating.toFixed(2)} avg` : "no ratings yet";
  document.getElementById("kv-app").textContent = appSum
    ? (appSum.total_app_reviews || 0).toLocaleString() : "—";
  document.getElementById("ks-app").textContent = appSum?.avg_star_rating
    ? `★ ${appSum.avg_star_rating.toFixed(1)} avg` : "app + play store";
  document.getElementById("kv-alerts").textContent   = (summary.unacknowledged_alerts || 0).toLocaleString();
  document.getElementById("kv-news").textContent     = (summary.news_24h || 0).toLocaleString();
  document.getElementById("kv-intel").textContent    = (summary.intel_24h || 0).toLocaleString();
  document.getElementById("kv-products").textContent = prodSum
    ? (prodSum.total_products || 0).toLocaleString() : "—";
  document.getElementById("ks-products").textContent = prodSum
    ? `${prodSum.in_stock || 0} in stock` : "in catalogue";

  // ── Charts ────────────────────────────────────────────────────
  // 1. Store sentiment donut
  drawSentimentDonut("chart-sentiment-donut", summary.sentiment_split || {});

  // 2. App topic horizontal bar
  if (appSum) {
    const topics = appSum.topic_split || {};
    const sorted = Object.entries(topics).sort((a, b) => b[1] - a[1]);
    drawHBar(
      "chart-topics-bar",
      sorted.map(([k]) => k.replace(/_/g, " ")),
      sorted.map(([, v]) => v),
      sorted.map((_, i) => PALETTE[i % PALETTE.length])
    );
  }

  // ── Text widgets ──────────────────────────────────────────────
  renderKeywords("keyword-cloud", summary.top_keywords || []);
  renderAlerts("recent-alerts-list", (alerts || []).slice(0, 6));

  // Alert banner
  const unack = summary.unacknowledged_alerts || 0;
  const banner = document.getElementById("alert-banner");
  if (unack > 0) {
    banner.textContent = `⚠ ${unack} unacknowledged alert${unack !== 1 ? "s" : ""} require attention.`;
    banner.classList.remove("hidden");
  } else {
    banner.classList.add("hidden");
  }
}

// ══════════════════════════════════════════════════════════════════
//  TAB: APP EXPERIENCE
// ══════════════════════════════════════════════════════════════════
let _appReviews = [];  // cached so charts + list share same fetch

async function loadAppExperience() {
  const [sum, rows] = await Promise.all([
    cachedFetch("app-summary",  "/dashboard/app-summary"),
    cachedFetch("app-reviews",  "/app-reviews?limit=500"),
  ]);
  if (!sum) return;

  _appReviews = rows || [];

  // ── KPIs ──────────────────────────────────────────────────────
  document.getElementById("app-avg-stars").textContent = sum.avg_star_rating
    ? `★ ${sum.avg_star_rating.toFixed(1)}` : "—";
  document.getElementById("app-total").textContent   = (sum.total_app_reviews || 0).toLocaleString();
  document.getElementById("app-safety").textContent  = sum.safety_complaint_count || 0;
  document.getElementById("app-nps").textContent     = sum.nps_proxy != null
    ? `${sum.nps_proxy > 0 ? "+" : ""}${sum.nps_proxy}%` : "—";

  // ── Charts ────────────────────────────────────────────────────
  // 3. Star rating distribution (computed from raw reviews)
  const starCounts = countBy(_appReviews, "star_rating");
  drawStarBar("chart-app-stars", starCounts);

  // 4. Sentiment donut
  drawSentimentDonut("chart-app-sentiment", sum.sentiment_split || {});

  // 5. Platform donut (App Store vs Play Store)
  const platEntries = Object.entries(sum.platform_split || {}).filter(([, v]) => v > 0);
  if (platEntries.length) {
    const platColors = { app_store: "#1565C0", play_store: "#2E7D32" };
    drawDonut(
      "chart-app-platform",
      platEntries.map(([k]) => k === "app_store" ? "App Store" : "Play Store"),
      platEntries.map(([, v]) => v),
      platEntries.map(([k]) => platColors[k] || CL.orange)
    );
  }

  // 6. Topic horizontal bar
  const topics = sum.topic_split || {};
  const topicSorted = Object.entries(topics).sort((a, b) => b[1] - a[1]);
  drawHBar(
    "chart-app-topics",
    topicSorted.map(([k]) => k.replace(/_/g, " ")),
    topicSorted.map(([, v]) => v),
    topicSorted.map((_, i) => PALETTE[i % PALETTE.length])
  );

  // ── Review list ───────────────────────────────────────────────
  renderAppReviews("app-reviews-list", _appReviews);

  // Wire filters (re-render list only; charts are pre-drawn)
  ["app-filter-platform", "app-filter-topic", "app-filter-sentiment"].forEach(id => {
    document.getElementById(id).onchange = filterAndRenderAppReviews;
  });
}

function filterAndRenderAppReviews() {
  const platform  = document.getElementById("app-filter-platform").value;
  const topic     = document.getElementById("app-filter-topic").value;
  const sentiment = document.getElementById("app-filter-sentiment").value;
  const filtered  = _appReviews.filter(r => {
    if (platform  && r.source !== platform) return false;
    if (sentiment && r.sentiment !== sentiment) return false;
    if (topic && !(r.topic || "").toLowerCase().includes(topic)) return false;
    return true;
  });
  renderAppReviews("app-reviews-list", filtered);
}

async function loadAppReviews() {
  const platform  = document.getElementById("app-filter-platform").value;
  const topic     = document.getElementById("app-filter-topic").value;
  const sentiment = document.getElementById("app-filter-sentiment").value;
  const params    = new URLSearchParams({ limit: 100 });
  if (platform)  params.set("source", platform);
  if (topic)     params.set("topic", topic);
  if (sentiment) params.set("sentiment", sentiment);
  const rows = await apiFetch(`/app-reviews?${params}`);
  renderAppReviews("app-reviews-list", rows || []);
}

function renderAppReviews(containerId, reviews) {
  const el = document.getElementById(containerId);
  if (!reviews.length) { el.innerHTML = '<div class="empty-state">No app reviews found.</div>'; return; }
  el.innerHTML = reviews.map(r => {
    const stars    = r.star_rating ? "★".repeat(r.star_rating) + "☆".repeat(5 - r.star_rating) : "";
    const topics   = (r.topic || "").split(",").map(t => t.trim()).filter(Boolean);
    const topicTag = topics.map(t => `<span class="review-tag">${esc(t)}</span>`).join(" ");
    const src      = r.source === "app_store" ? "🍎 App Store" : "🤖 Play Store";
    return `<div class="review-card sentiment-${r.sentiment || "neutral"}">
      <div class="review-meta">
        <span>${src}</span>
        <span class="review-stars">${stars}</span>
        <strong>${esc(r.reviewer || "Anonymous")}</strong>
        <span>${r.review_date ? r.review_date.split("T")[0] : ""}</span>
        ${topicTag}
      </div>
      <div class="review-text">${esc(r.review_text)}</div>
      ${r.summary ? `<div class="review-text" style="color:var(--text-3);font-size:12px;margin-top:4px;">💡 ${esc(r.summary)}</div>` : ""}
    </div>`;
  }).join("");
}

// ══════════════════════════════════════════════════════════════════
//  TAB: PRODUCT QUALITY
// ══════════════════════════════════════════════════════════════════
let _allProducts = [];

async function loadProductQuality() {
  const [prodSum, prods] = await Promise.all([
    cachedFetch("prod-summary", "/dashboard/product-summary"),
    cachedFetch("products",     "/products?limit=1000"),
  ]);

  _allProducts = prods || [];

  if (prodSum) {
    document.getElementById("prod-total").textContent    = (prodSum.total_products || 0).toLocaleString();
    document.getElementById("prod-in-stock").textContent = (prodSum.in_stock || 0).toLocaleString();
    document.getElementById("prod-oos").textContent      = (prodSum.out_of_stock || 0).toLocaleString();
    document.getElementById("prod-disc").textContent     = prodSum.avg_discount_pct != null
      ? `${prodSum.avg_discount_pct.toFixed(1)}%` : "—";

    // ── Charts ──────────────────────────────────────────────────
    // 7. Stock status donut
    const inStock  = prodSum.in_stock || 0;
    const outStock = prodSum.out_of_stock || 0;
    if (inStock + outStock > 0) {
      drawDonut(
        "chart-prod-stock",
        ["In Stock", "Out of Stock"],
        [inStock, outStock],
        [CL.green, CL.red]
      );
    }

    // 8. Avg price by category (vertical bar)
    const cats      = prodSum.categories || [];
    const catsWithP = cats.filter(c => c.avg_price != null);
    if (catsWithP.length) {
      drawVBar(
        "chart-prod-prices",
        catsWithP.map(c => c.category),
        [{
          label: "Avg Price (₹)",
          data: catsWithP.map(c => Math.round(c.avg_price)),
          backgroundColor: catsWithP.map((_, i) => PALETTE[i % PALETTE.length]),
          borderRadius: 5,
          borderSkipped: false,
        }],
        "₹"
      );
    }

    // 9. Products per category (horizontal bar)
    const catsSorted = [...cats].sort((a, b) => b.count - a.count);
    drawHBar(
      "chart-cat-bar",
      catsSorted.map(c => c.category),
      catsSorted.map(c => c.count),
      catsSorted.map((_, i) => PALETTE[i % PALETTE.length])
    );

    renderDiscounts("top-discounts-list", prodSum.top_discounted || []);
  }

  renderProductTable(_allProducts);

  // Populate category filter
  const cats = [...new Set(_allProducts.map(p => p.category).filter(Boolean))].sort();
  const catSel = document.getElementById("prod-filter-cat");
  catSel.innerHTML = '<option value="">All Categories</option>' +
    cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");

  document.getElementById("prod-search").oninput        = filterProducts;
  document.getElementById("prod-filter-cat").onchange   = filterProducts;
  document.getElementById("prod-filter-stock").onchange = filterProducts;
}

function filterProducts() {
  const q     = document.getElementById("prod-search").value.toLowerCase();
  const cat   = document.getElementById("prod-filter-cat").value;
  const stock = document.getElementById("prod-filter-stock").value;
  const filtered = _allProducts.filter(p => {
    if (q && !p.product_name.toLowerCase().includes(q)) return false;
    if (cat && p.category !== cat) return false;
    const s = (p.stock_status || "").toLowerCase();
    if (stock === "in_stock"    && s === "out_of_stock") return false;
    if (stock === "out_of_stock" && s !== "out_of_stock") return false;
    return true;
  });
  renderProductTable(filtered);
}

function renderProductTable(products) {
  const tbody = document.getElementById("products-tbody");
  if (!products.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No products found.</td></tr>`;
    return;
  }
  tbody.innerHTML = products.slice(0, 300).map(p => {
    const s = (p.stock_status || "").toLowerCase();
    const stockClass = s === "out_of_stock" ? "stock-out" : p.stock_status ? "stock-in" : "stock-na";
    return `<tr>
      <td>${esc(p.product_name)}</td>
      <td>${esc(p.brand || "—")}</td>
      <td>${esc(p.category || "—")}</td>
      <td>${p.min_price_inr != null ? `₹${p.min_price_inr}` : "—"}</td>
      <td>${p.discount_pct  != null ? `${p.discount_pct}%`  : "—"}</td>
      <td><span class="stock-badge ${stockClass}">${esc(p.stock_status || "—")}</span></td>
    </tr>`;
  }).join("");
}

function renderDiscounts(containerId, items) {
  const el = document.getElementById(containerId);
  if (!items.length) { el.innerHTML = '<div class="empty-state">No discount data.</div>'; return; }
  el.innerHTML = items.map(d =>
    `<div class="discount-item">
      <div>
        <div class="disc-name">${esc(d.name || "")}</div>
        <div class="disc-cat">${esc(d.category || "")}</div>
      </div>
      <span class="disc-price">${d.price != null ? `₹${d.price}` : ""}</span>
      <span class="disc-badge">${d.discount_pct || 0}% OFF</span>
    </div>`
  ).join("");
}

// ══════════════════════════════════════════════════════════════════
//  TAB: STORE REVIEWS
// ══════════════════════════════════════════════════════════════════
let _storeReviews = [];

async function loadStoreExperience() {
  const [summary, rows] = await Promise.all([
    cachedFetch("summary",      "/dashboard/summary"),
    cachedFetch("store-reviews","/reviews?limit=500"),
  ]);

  _storeReviews = rows || [];

  if (summary) {
    const split = summary.sentiment_split || {};
    const total = Object.values(split).reduce((a, b) => a + b, 0) || 1;
    const pos   = split.positive || 0;
    const neg   = split.negative || 0;
    document.getElementById("store-total").textContent      = (summary.review_count || 0).toLocaleString();
    document.getElementById("store-avg-rating").textContent = summary.avg_rating
      ? `★ ${summary.avg_rating.toFixed(2)}` : "—";
    document.getElementById("store-positive").textContent   = `${Math.round(pos / total * 100)}%`;
    document.getElementById("store-negative").textContent   = `${Math.round(neg / total * 100)}%`;

    // ── Charts ──────────────────────────────────────────────────
    // 10. Rating distribution bar (from raw reviews)
    const ratingCounts = countBy(
      _storeReviews.filter(r => r.rating),
      "rating"  // may be float; we'll round
    );
    // Build integer buckets 1–5
    const starMap = {};
    _storeReviews.forEach(r => {
      if (r.rating) {
        const bucket = Math.round(r.rating);
        starMap[bucket] = (starMap[bucket] || 0) + 1;
      }
    });
    drawStarBar("chart-store-ratings", starMap);

    // 11. Sentiment donut
    drawSentimentDonut("chart-store-sentiment", split);
  }

  renderStoreReviewList(_storeReviews);

  document.getElementById("store-filter-sentiment").onchange = filterAndRenderStoreReviews;
  document.getElementById("store-filter-rating").oninput     = filterAndRenderStoreReviews;
  let _debounce;
  document.getElementById("store-search").oninput = () => {
    clearTimeout(_debounce);
    _debounce = setTimeout(filterAndRenderStoreReviews, 350);
  };
}

function filterAndRenderStoreReviews() {
  const search    = document.getElementById("store-search").value.toLowerCase();
  const sentiment = document.getElementById("store-filter-sentiment").value;
  const minRating = parseFloat(document.getElementById("store-filter-rating").value) || 0;
  const filtered  = _storeReviews.filter(r => {
    if (sentiment && r.sentiment !== sentiment) return false;
    if (minRating && (r.rating || 0) < minRating) return false;
    if (search && !(r.review_text || "").toLowerCase().includes(search)) return false;
    return true;
  });
  renderStoreReviewList(filtered);
}

async function loadStoreReviews() {
  const sentiment = document.getElementById("store-filter-sentiment").value;
  const minRating = document.getElementById("store-filter-rating").value;
  const params    = new URLSearchParams({ limit: 100 });
  if (sentiment) params.set("sentiment", sentiment);
  if (minRating) params.set("min_rating", minRating);
  const rows = await apiFetch(`/reviews?${params}`);
  renderStoreReviewList(rows || []);
}

function renderStoreReviewList(reviews) {
  const el = document.getElementById("store-reviews-list");
  if (!reviews.length) { el.innerHTML = '<div class="empty-state">No reviews found.</div>'; return; }
  el.innerHTML = reviews.map(r => {
    const stars = r.rating
      ? "★".repeat(Math.round(r.rating)) + "☆".repeat(5 - Math.round(r.rating)) : "";
    return `<div class="review-card sentiment-${r.sentiment || "neutral"}">
      <div class="review-meta">
        <span class="review-stars">${stars}</span>
        <strong>${esc(r.reviewer_name || "Anonymous")}</strong>
        <span>${esc(r.store_location || "")}</span>
        <span>${esc(r.source || "")}</span>
        ${r.sentiment ? `<span class="review-tag tag-${r.sentiment}">${r.sentiment}</span>` : ""}
      </div>
      <div class="review-text">${esc(r.review_text)}</div>
    </div>`;
  }).join("");
}

// ══════════════════════════════════════════════════════════════════
//  TAB: MARKET INTEL
// ══════════════════════════════════════════════════════════════════
async function loadMarketIntel() {
  const [news, intel, competitors, pricing] = await Promise.all([
    cachedFetch("news",        "/news?days=30&limit=50"),
    cachedFetch("intel",       "/intel?limit=50"),
    cachedFetch("competitors", "/competitors"),
    cachedFetch("pricing",     "/pricing"),
  ]);

  // ── Charts ──────────────────────────────────────────────────────
  // 12. Price comparison grouped bar (top 8 by abs diff)
  const priceRows = (pricing || [])
    .filter(p => p.tow_price != null && p.competitor_price != null)
    .sort((a, b) => Math.abs(b.price_diff_pct) - Math.abs(a.price_diff_pct))
    .slice(0, 8);
  if (priceRows.length) {
    drawVBar(
      "chart-pricing",
      priceRows.map(p => truncate(p.product_name, 18)),
      [
        {
          label: "TOW (₹)",
          data: priceRows.map(p => p.tow_price),
          backgroundColor: CL.green,
          borderRadius: 4,
        },
        {
          label: "Competitor (₹)",
          data: priceRows.map(p => p.competitor_price),
          backgroundColor: CL.red,
          borderRadius: 4,
        },
      ],
      "₹"
    );
  }

  // 13. News by relevance tag (horizontal bar)
  const tagCounts = {};
  (news || []).forEach(n => {
    const t = n.relevance_tag || "other";
    tagCounts[t] = (tagCounts[t] || 0) + 1;
  });
  const tagSorted = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]);
  if (tagSorted.length) {
    drawHBar(
      "chart-news-tags",
      tagSorted.map(([k]) => k.replace(/_/g, " ")),
      tagSorted.map(([, v]) => v),
      tagSorted.map((_, i) => PALETTE[i % PALETTE.length])
    );
  }

  // ── Lists ────────────────────────────────────────────────────────
  renderNews("news-list", news || []);
  renderIntel("intel-list", intel || []);
  renderCompetitors("competitor-list", competitors || []);
  renderPricing("pricing-list", pricing || []);
}

function renderNews(containerId, items) {
  const el = document.getElementById(containerId);
  if (!items.length) { el.innerHTML = '<div class="empty-state">No news found.</div>'; return; }
  el.innerHTML = items.map(n =>
    `<div class="news-item">
      <div class="news-headline">${esc(n.headline)}</div>
      <div class="news-meta">
        <span class="news-tag">${esc(n.relevance_tag)}</span>
        <span>${esc(n.source)}</span>
        <span>${n.created_at ? n.created_at.split("T")[0] : ""}</span>
      </div>
      ${n.summary ? `<div style="font-size:12px;color:var(--text-2);margin-top:4px;">${esc(n.summary.slice(0, 160))}…</div>` : ""}
    </div>`
  ).join("");
}

function renderIntel(containerId, items) {
  const el = document.getElementById(containerId);
  if (!items.length) { el.innerHTML = '<div class="empty-state">No intel signals found.</div>'; return; }
  el.innerHTML = items.map(i =>
    `<div class="intel-item">
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;">
        <span class="intel-type">${esc(i.intel_type)}</span>
        <span class="intel-subject">${esc(i.subject)}</span>
      </div>
      <div style="font-size:12px;color:var(--text-2);">${esc((i.detail || "").slice(0, 180))}…</div>
      ${i.strategic_implication
        ? `<div style="font-size:12px;color:var(--accent);margin-top:4px;">→ ${esc(i.strategic_implication.slice(0, 120))}</div>`
        : ""}
    </div>`
  ).join("");
}

function renderCompetitors(containerId, items) {
  const el = document.getElementById(containerId);
  if (!items.length) { el.innerHTML = '<div class="empty-state">No competitors found.</div>'; return; }
  el.innerHTML = items.map(c =>
    `<div class="comp-item">
      <div class="comp-name">${esc(c.competitor_name)}</div>
      <div class="comp-location">${esc(c.location || "")} ${c.category ? `· ${esc(c.category)}` : ""}</div>
      ${c.strengths ? `<div class="comp-strengths">✓ ${esc(c.strengths.slice(0, 100))}</div>` : ""}
      ${c.price_positioning ? `<div style="font-size:11px;color:var(--text-3);margin-top:3px;">Pricing: ${esc(c.price_positioning)}</div>` : ""}
    </div>`
  ).join("");
}

function renderPricing(containerId, items) {
  const el = document.getElementById(containerId);
  if (!items.length) { el.innerHTML = '<div class="empty-state">No pricing data found.</div>'; return; }
  const sorted = [...items].sort((a, b) => a.price_diff_pct - b.price_diff_pct);
  el.innerHTML = sorted.slice(0, 20).map(p => {
    const isThreat = p.price_diff_pct < -15;
    const sign     = p.price_diff_pct > 0 ? "+" : "";
    return `<div class="price-item">
      <div class="price-product">${esc(p.product_name)}</div>
      <div style="font-size:12px;color:var(--text-2);margin:2px 0;">
        ${esc(p.competitor_name)} · TOW: ₹${p.tow_price} vs ₹${p.competitor_price}
        <span class="price-diff ${isThreat ? "threat" : "ok"}">
          (${sign}${p.price_diff_pct.toFixed(1)}%)
        </span>
      </div>
    </div>`;
  }).join("");
}

// ══════════════════════════════════════════════════════════════════
//  TAB: EXPLORER
// ══════════════════════════════════════════════════════════════════
document.getElementById("exp-search-btn").addEventListener("click", runExplorer);
document.getElementById("exp-query").addEventListener("keydown", e => {
  if (e.key === "Enter") runExplorer();
});

async function runExplorer() {
  const q          = document.getElementById("exp-query").value.trim();
  const sourceType = document.getElementById("exp-source").value;
  const sentiment  = document.getElementById("exp-sentiment").value;
  const el         = document.getElementById("explorer-results");
  el.innerHTML     = '<div class="empty-state">Searching…</div>';

  const params = new URLSearchParams({ limit: 200 });
  if (sentiment) params.set("sentiment", sentiment);

  if (sourceType === "app") {
    const rows     = await apiFetch(`/app-reviews?${params}`);
    const filtered = (rows || []).filter(r =>
      !q || (r.review_text || "").toLowerCase().includes(q.toLowerCase()) ||
            (r.summary    || "").toLowerCase().includes(q.toLowerCase())
    );
    renderAppReviews("explorer-results", filtered);
  } else {
    const rows     = await apiFetch(`/reviews?${params}`);
    const filtered = (rows || []).filter(r =>
      !q || (r.review_text || "").toLowerCase().includes(q.toLowerCase())
    );
    renderStoreReviewList2("explorer-results", filtered);
  }
}

// renderStoreReviewList but for an arbitrary container id
function renderStoreReviewList2(containerId, reviews) {
  const el = document.getElementById(containerId);
  if (!reviews.length) { el.innerHTML = '<div class="empty-state">No reviews found.</div>'; return; }
  el.innerHTML = reviews.map(r => {
    const stars = r.rating
      ? "★".repeat(Math.round(r.rating)) + "☆".repeat(5 - Math.round(r.rating)) : "";
    return `<div class="review-card sentiment-${r.sentiment || "neutral"}">
      <div class="review-meta">
        <span class="review-stars">${stars}</span>
        <strong>${esc(r.reviewer_name || "Anonymous")}</strong>
        <span>${esc(r.store_location || "")}</span>
        <span>${esc(r.source || "")}</span>
        ${r.sentiment ? `<span class="review-tag tag-${r.sentiment}">${r.sentiment}</span>` : ""}
      </div>
      <div class="review-text">${esc(r.review_text)}</div>
    </div>`;
  }).join("");
}

// ══════════════════════════════════════════════════════════════════
//  WEBSOCKET LIVE FEED
// ══════════════════════════════════════════════════════════════════
let _ws = null;
let _wsPaused = false;

function wsClose() {
  if (_ws) { try { _ws.close(); } catch {} _ws = null; }
}

function connectWebSocket() {
  wsClose();
  const token = getToken();
  if (!token) return;
  const wsUrl    = `${location.origin.replace("http", "ws")}/ws?token=${token}`;
  const wsStatus = document.getElementById("ws-status");
  wsStatus.className = "ws-indicator ws-connecting";
  wsStatus.title     = "Connecting…";

  _ws = new WebSocket(wsUrl);
  _ws.onopen  = () => { wsStatus.className = "ws-indicator ws-connected";    wsStatus.title = "Connected"; };
  _ws.onclose = () => {
    wsStatus.className = "ws-indicator ws-disconnected"; wsStatus.title = "Disconnected";
    if (getToken()) setTimeout(connectWebSocket, 5000);
  };
  _ws.onerror = () => { wsStatus.className = "ws-indicator ws-disconnected"; wsStatus.title = "Error"; };
  _ws.onmessage = msg => {
    if (_wsPaused) return;
    try {
      const evt = JSON.parse(msg.data);
      if (evt.type !== "hello") {
        appendLiveEvent(evt);
        document.getElementById("live-badge").style.display = "inline-block";
      }
    } catch {}
  };
}

const EVENT_ICONS = { "review.created":"⭐","news.created":"📰","intel.created":"🧠","alert.created":"🚨" };
const EVENT_CLASS = { "review.created":"event-review","news.created":"event-news","intel.created":"event-intel","alert.created":"event-alert" };

function appendLiveEvent(evt) {
  const container   = document.getElementById("live-feed-container");
  if (!container) return;
  container.querySelector(".live-empty")?.remove();

  const icon    = EVENT_ICONS[evt.type] || "📡";
  const cls     = EVENT_CLASS[evt.type] || "";
  const payload = evt.payload || {};
  let text = "";
  if (evt.type === "review.created")
    text = `New review at <strong>${esc(payload.store || "store")}</strong> · Rating: ${payload.rating || "—"} · Sentiment: ${payload.sentiment || "—"}`;
  else if (evt.type === "news.created")
    text = `<strong>${esc(payload.headline || "News item")}</strong> [${esc(payload.tag || "")}]`;
  else if (evt.type === "intel.created")
    text = `Intel: <strong>${esc(payload.subject || "Signal")}</strong> [${esc(payload.type || "")}]`;
  else if (evt.type === "alert.created")
    text = `Alert: <strong>${esc(payload.subject || "")}</strong> · ${esc(payload.priority || "")}`;
  else
    text = JSON.stringify(payload).slice(0, 120);

  const el = document.createElement("div");
  el.className = `live-event ${cls}`;
  el.innerHTML = `
    <div class="live-event-icon">${icon}</div>
    <div class="live-event-body">
      <div class="live-event-type">${esc(evt.type)}</div>
      <div class="live-event-text">${text}</div>
      <div class="live-event-time">${new Date().toLocaleTimeString()}</div>
    </div>`;
  container.insertBefore(el, container.firstChild);

  const events = container.querySelectorAll(".live-event");
  if (events.length > 100) events[events.length - 1].remove();
}

document.getElementById("live-pause").addEventListener("change", e => { _wsPaused = e.target.checked; });
document.getElementById("live-clear").addEventListener("click", () => {
  document.getElementById("live-feed-container").innerHTML =
    '<div class="live-empty">Feed cleared. Waiting for new events…</div>';
});

// ══════════════════════════════════════════════════════════════════
//  SHARED RENDERERS
// ══════════════════════════════════════════════════════════════════
function renderKeywords(containerId, keywords) {
  const el = document.getElementById(containerId);
  if (!keywords.length) { el.innerHTML = '<div class="empty-state">No keywords.</div>'; return; }
  el.innerHTML = keywords.slice(0, 20)
    .map(([kw, cnt]) => `<span class="keyword-tag" title="${cnt} mentions">${esc(kw)}</span>`)
    .join("");
}

function renderAlerts(containerId, alerts) {
  const el = document.getElementById(containerId);
  if (!alerts.length) { el.innerHTML = '<div class="empty-state">No active alerts.</div>'; return; }
  el.innerHTML = alerts.map(a =>
    `<div class="alert-item ${a.priority}">
      <span class="alert-priority priority-${a.priority}">${a.priority}</span>
      <div class="alert-text">
        <div class="alert-subject">${esc(a.subject)}</div>
        <div class="alert-detail">${esc((a.detail || "").slice(0, 120))}</div>
      </div>
      <div class="alert-time">${relativeTime(a.created_at)}</div>
    </div>`
  ).join("");
}

// ══════════════════════════════════════════════════════════════════
//  TOPBAR ACTIONS
// ══════════════════════════════════════════════════════════════════
document.getElementById("refresh-btn").addEventListener("click", () => {
  Object.keys(_cache).forEach(k => delete _cache[k]);
  const active = document.querySelector(".nav-item.active");
  if (active) loadTab(active.dataset.tab);
});

document.getElementById("logout-btn").addEventListener("click", logout);

document.getElementById("scan-btn").addEventListener("click", async () => {
  if (!isAnalyst()) return alert("Requires analyst role.");
  const res = await apiFetch("/alerts/scan", { method: "POST" });
  if (res) {
    invalidateCache("alerts"); invalidateCache("summary");
    alert(`Alert scan complete. ${res.new_alerts} new alert(s) raised.`);
    loadTab("overview");
  }
});

document.getElementById("ingest-btn").addEventListener("click", async () => {
  if (!isAdmin()) return alert("Requires admin role.");
  const btn = document.getElementById("ingest-btn");
  btn.textContent = "⬆ Ingesting…"; btn.disabled = true;
  try {
    const res = await apiFetch("/admin/ingest", { method: "POST" });
    if (res) {
      Object.keys(_cache).forEach(k => delete _cache[k]);
      alert("Ingest complete!\n" + Object.entries(res).map(([k, v]) => `${k}: ${v}`).join(" | "));
      loadTab("overview");
    }
  } finally { btn.textContent = "⬆ Ingest"; btn.disabled = false; }
});

document.getElementById("view-all-alerts").addEventListener("click", () => {
  switchTab("market-intel"); loadTab("market-intel");
});

// ══════════════════════════════════════════════════════════════════
//  UTILITIES
// ══════════════════════════════════════════════════════════════════
function esc(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function relativeTime(iso) {
  if (!iso) return "";
  const m = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function truncate(str, n) {
  if (!str) return "";
  return str.length > n ? str.slice(0, n) + "…" : str;
}

// ══════════════════════════════════════════════════════════════════
//  BOOT
// ══════════════════════════════════════════════════════════════════
(function init() {
  if (getToken()) showApp();
})();
