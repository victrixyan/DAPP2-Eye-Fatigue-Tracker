// ── API client ──

async function apiGet(path) {
  const response = await fetch(path);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }
  return response.json();
}

async function apiPost(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }
  return response.json();
}

// ── User store (local auth only) ──

function getUsers() {
  return JSON.parse(localStorage.getItem("eft_users") || "{}");
}

function saveUsers(users) {
  localStorage.setItem("eft_users", JSON.stringify(users));
}

function saveSession(username) {
  localStorage.setItem("eft_user", username);
}

function getSession() {
  return localStorage.getItem("eft_user");
}

function clearSession() {
  localStorage.removeItem("eft_user");
}

function requireAuth() {
  const username = getSession();
  if (!username) {
    window.location.href = "index.html";
    return null;
  }
  return username;
}

// ── Auth ──

function handleRegister() {
  const name          = document.getElementById("reg-name")?.value.trim();
  const lastname      = document.getElementById("reg-lastname")?.value.trim();
  const usernameInput = document.getElementById("reg-username")?.value.trim();
  const password      = document.getElementById("reg-password")?.value;
  const confirm       = document.getElementById("reg-confirm")?.value;
  const errorEl       = document.getElementById("register-error");

  if (!name || !lastname || !usernameInput || !password || !confirm) {
    showError(errorEl, "Please fill in all fields.");
    return;
  }
  if (password !== confirm) {
    showError(errorEl, "Passwords do not match.");
    return;
  }

  const username = usernameInput.toLowerCase();
  const users    = getUsers();

  if (users[username]) {
    showError(errorEl, "Username already taken.");
    return;
  }

  users[username] = { name, lastname, password };
  saveUsers(users);
  saveSession(username);
  window.location.href = "dashboard.html";
}

function handleLogin() {
  const username = document.getElementById("username")?.value.trim().toLowerCase();
  const password = document.getElementById("password")?.value;
  const errorEl  = document.getElementById("login-error");

  if (!username || !password) {
    showError(errorEl, "Please fill in all fields.");
    return;
  }

  const users = getUsers();
  if (!users[username] || users[username].password !== password) {
    showError(errorEl, "Incorrect username or password.");
    return;
  }

  saveSession(username);
  window.location.href = "dashboard.html";
}

function signOut() {
  clearSession();
  window.location.href = "index.html";
}

function handleNewSession() {
  window.location.href = "adjust_device.html";
}

// ── Utilities ──

function formatTime(seconds) {
  const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function formatDate(date) {
  return date.toLocaleDateString("en-GB", {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
}

function parseUkDate(dateStr) {
  const [day, month, year] = dateStr.split("/").map(Number);
  return new Date(year, month - 1, day);
}

function showError(el, message) {
  if (!el) return;
  el.textContent = message;
  el.classList.add("visible");
}

function sessionEndTimeLabel(startTime, duration) {
  const [sh, sm, ss] = startTime.split(":").map(Number);
  const [dh, dm, ds] = duration.split(":").map(Number);
  let total = sh * 3600 + sm * 60 + ss + dh * 3600 + dm * 60 + ds;
  const h = Math.floor(total / 3600) % 24;
  total %= 3600;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// ── Dashboard charts ──

let fatigueChart = null;
let dashboardHistory = null;

function anchorZeroPoint(labels, values) {
  return {
    labels: ["0", ...labels],
    values: [0, ...values],
  };
}

function formatFatigueScore(score) {
  if (score == null || score === "-" || Number.isNaN(Number(score))) return "-";
  const n = Number(score);
  return n % 1 === 0 ? String(n) : n.toFixed(1);
}

function buildDayView(sessions) {
  const today = formatDate(new Date());
  const rows  = sessions.filter((s) => s.date === today);
  const labels = rows.map((s) => sessionEndTimeLabel(s.start_time, s.duration));
  const values = rows.map((s) => s.latest_fatigue_score);
  return anchorZeroPoint(labels, values);
}

function mondayOfWeek(date) {
  const d = new Date(date);
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function buildWeekView(sessions) {
  const labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const monday = mondayOfWeek(new Date());
  const values = labels.map((_, i) => {
    const dayDate = new Date(monday);
    dayDate.setDate(monday.getDate() + i);
    const dayStr = formatDate(dayDate);
    const dayRows = sessions.filter((s) => s.date === dayStr);
    if (!dayRows.length) return 0;
    const avg = dayRows.reduce((a, s) => a + s.latest_fatigue_score, 0) / dayRows.length;
    return +avg.toFixed(1);
  });
  return anchorZeroPoint(labels, values);
}

function buildMonthView(sessions) {
  const now   = new Date();
  const month = now.getMonth();
  const year  = now.getFullYear();
  const byDay = {};

  sessions.forEach((s) => {
    const d = parseUkDate(s.date);
    if (d.getMonth() === month && d.getFullYear() === year) {
      const key = d.getDate();
      if (!byDay[key]) byDay[key] = { sum: 0, count: 0 };
      byDay[key].sum += s.latest_fatigue_score;
      byDay[key].count += 1;
    }
  });

  const days = Object.keys(byDay).map(Number).sort((a, b) => a - b);
  const labels = days.map((d) => String(d));
  const values = days.map((d) => +(byDay[d].sum / byDay[d].count).toFixed(1));
  return anchorZeroPoint(labels, values);
}

function renderCalendar(sessions) {
  const grid = document.getElementById("calendar-grid");
  if (!grid) return;

  const now        = new Date();
  const year       = now.getFullYear();
  const month      = now.getMonth();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const sessionDays = new Set(
    sessions
      .filter((s) => {
        const d = parseUkDate(s.date);
        return d.getMonth() === month && d.getFullYear() === year;
      })
      .map((s) => parseUkDate(s.date).getDate())
  );

  grid.innerHTML = "";
  for (let day = 1; day <= daysInMonth; day++) {
    const cell = document.createElement("div");
    cell.className = "calendar-day";
    if (sessionDays.has(day)) cell.classList.add("active");
    cell.textContent = String(day);
    grid.appendChild(cell);
  }
}

function showTrendsEmpty(show) {
  const empty = document.getElementById("trends-empty");
  const canvas = document.getElementById("chart-fatigue");
  const container = document.getElementById("trends-chart-container");
  if (!empty || !canvas) return;

  empty.hidden = !show;
  if (container) container.classList.toggle("is-empty", show);

  if (show && fatigueChart) {
    fatigueChart.destroy();
    fatigueChart = null;
  }
}

function renderFatigueChart(labels, values, animate) {
  const canvas = document.getElementById("chart-fatigue");
  if (!canvas) return;

  const hasData = values.length > 1;

  if (fatigueChart) fatigueChart.destroy();

  fatigueChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Fatigue Score",
        data: values,
        borderColor: "#3D2D7A",
        backgroundColor: "transparent",
        borderWidth: 3,
        fill: false,
        tension: 0.4,
        pointRadius: hasData ? 6 : 0,
        pointBackgroundColor: "#3D2D7A",
        pointBorderColor: "#FFFFFF",
        pointBorderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: animate ? { duration: 1200, easing: "easeOutQuart" } : false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          display: hasData,
          grid: { display: false },
          ticks: { font: { size: 11 }, color: "#7B6BA8" },
        },
        y: {
          display: hasData,
          grid: { color: "rgba(196,181,224,0.4)" },
          ticks: { font: { size: 11 }, color: "#7B6BA8" },
          beginAtZero: true,
          max: 10,
        },
      },
    },
  });
}

function setTrend(view, btn) {
  if (!dashboardHistory) return;

  if (!dashboardHistory.sessions.length) {
    showTrendsEmpty(true);
    return;
  }

  showTrendsEmpty(false);

  document.querySelectorAll("#trend-toggle button").forEach((b) =>
    b.classList.remove("active")
  );
  if (btn) btn.classList.add("active");

  let chartData;
  if (view === "week") chartData = buildWeekView(dashboardHistory.sessions);
  else if (view === "month") chartData = buildMonthView(dashboardHistory.sessions);
  else chartData = buildDayView(dashboardHistory.sessions);

  renderFatigueChart(chartData.labels, chartData.values, true);
}

const FAQ_CONTENT = {
  cvs: {
    title: "What is Computer Vision Syndrome?",
    answer:
      "Computer Vision Syndrome (CVS) is a group of eye and vision problems caused by prolonged screen use. Common symptoms include eye strain, dryness, blurred vision, headaches, and neck or shoulder discomfort.",
  },
  "eye-health": {
    title: "How to improve eye health?",
    answer:
      "😌 Continue taking regular breaks\n" +
      "👀 Blink consciously and completely\n" +
      "📏 Follow the 20-20-20 rule: Every 20 minutes\n" +
      "👀 Look at something 20 feet away for 20 seconds\n" +
      "💻 Position screen 20-26 inches from eyes",
  },
};

function closeFaqModal() {
  const overlay = document.getElementById("faq-overlay");
  if (overlay) overlay.hidden = true;
}

function openFaqModal(key) {
  const content = FAQ_CONTENT[key];
  const overlay = document.getElementById("faq-overlay");
  const titleEl = document.getElementById("faq-modal-title");
  const answerEl = document.getElementById("faq-modal-answer");
  if (!content || !overlay || !titleEl || !answerEl) return;

  titleEl.textContent = content.title;
  answerEl.textContent = content.answer;
  overlay.hidden = false;
}

function initInfoCards() {
  const overlay = document.getElementById("faq-overlay");
  const modal = document.getElementById("faq-modal");
  if (!overlay) return;

  document.querySelectorAll(".info-card[data-faq]").forEach((card) => {
    const show = () => openFaqModal(card.dataset.faq);

    card.addEventListener("click", (event) => {
      event.stopPropagation();
      show();
    });

    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        show();
      }
    });
  });

  overlay.addEventListener("click", closeFaqModal);

  if (modal) {
    modal.addEventListener("click", (event) => event.stopPropagation());
  }
}

async function initDashboard() {
  const username = requireAuth();
  if (!username) return;

  const users = getUsers();
  const user  = users[username];
  if (!user) {
    clearSession();
    window.location.href = "index.html";
    return;
  }

  const nameEl = document.getElementById("profile-name");
  if (nameEl) nameEl.textContent = `${user.name} ${user.lastname}`;

  document.getElementById("profile-username").textContent = username;

  try {
    dashboardHistory = await apiGet(`/api/history/${encodeURIComponent(username)}`);
  } catch {
    dashboardHistory = { sessions: [], total_sessions: 0, last_session: null };
  }

  document.getElementById("total-sessions").textContent =
    dashboardHistory.total_sessions;

  const last = dashboardHistory.last_session;
  if (last) {
    document.getElementById("last-recording").textContent = last.date;
    document.getElementById("latest-fatigue").textContent =
      formatFatigueScore(last.latest_fatigue_score);
  } else {
    document.getElementById("last-recording").textContent = "No recordings yet";
    document.getElementById("latest-fatigue").textContent = "-";
  }

  renderCalendar(dashboardHistory.sessions);

  if (!dashboardHistory.sessions.length) {
    showTrendsEmpty(true);
  } else {
    setTrend("day", document.querySelector("#trend-toggle button.active"));
  }

  initInfoCards();
}

// ── Camera adjust (pre-calibration) ──

let blinkPollInterval = null;

function updateBlinkDisplay(state) {
  const el = document.getElementById("blink-state");
  if (!el) return;
  el.textContent = state;
  el.classList.toggle("open", state === "OPEN");
}

async function handleAdjustNext() {
  const btn = document.getElementById("btn-next");
  if (btn) btn.disabled = true;

  if (blinkPollInterval) {
    clearInterval(blinkPollInterval);
    blinkPollInterval = null;
  }

  try {
    await apiPost("/api/session/stop-adjust");
  } catch (err) {
    console.error(err);
  }

  window.location.href = "calibration.html";
}

async function initAdjustDevice() {
  const username = requireAuth();
  if (!username) return;

  const btn = document.getElementById("btn-next");
  if (btn) btn.onclick = handleAdjustNext;

  try {
    await apiPost("/api/session/start-adjust", { uid: username });
  } catch (err) {
    updateBlinkDisplay("ERROR");
    console.error(err);
    return;
  }

  blinkPollInterval = setInterval(async () => {
    try {
      const data = await apiGet("/api/session/blink-state");
      updateBlinkDisplay(data.state);
    } catch (err) {
      console.error(err);
    }
  }, 150);

  window.addEventListener("beforeunload", () => {
    fetch("/api/session/stop-adjust", { method: "POST", keepalive: true });
  });
}

// ── Calibration ──

let calibInterval = null;

async function handleEndCalibration() {
  if (calibInterval) clearInterval(calibInterval);
  try {
    await apiPost("/api/session/cancel-calibration");
  } catch (err) {
    console.error(err);
  }
  window.location.href = "dashboard.html";
}

async function finishCalibration() {
  if (calibInterval) clearInterval(calibInterval);
  const statusEl = document.getElementById("calib-status");
  const doneEl   = document.getElementById("calib-complete");
  if (statusEl) statusEl.textContent = "Complete";
  if (doneEl) doneEl.style.display = "block";

  try {
    await apiPost("/api/session/end-calibration");
    setTimeout(() => { window.location.href = "loading.html"; }, 1500);
  } catch (err) {
    if (statusEl) statusEl.textContent = "Error ending calibration";
    console.error(err);
  }
}

async function initCalibration() {
  const username = requireAuth();
  if (!username) return;

  const DURATION = 5 * 60;
  let remaining  = DURATION;

  const timerEl  = document.getElementById("calib-timer");
  const barEl    = document.getElementById("calib-bar");
  const pctEl    = document.getElementById("calib-percent");

  try {
    await apiPost("/api/session/start-calibration", { uid: username });
  } catch (err) {
    document.getElementById("calib-status").textContent =
      "Could not start calibration";
    console.error(err);
    return;
  }

  calibInterval = setInterval(() => {
    remaining--;

    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const s = String(remaining % 60).padStart(2, "0");
    timerEl.textContent = `${m}:${s}`;

    const pct = Math.round(((DURATION - remaining) / DURATION) * 100);
    barEl.style.width = `${pct}%`;
    pctEl.textContent = `${pct}%`;

    if (remaining <= 0) {
      finishCalibration();
    }
  }, 1000);
}

// ── Loading / model training wait ──

async function initLoading() {
  const username = requireAuth();
  if (!username) return;

  const textEl = document.querySelector(".loading-text");

  const poll = async () => {
    try {
      const status = await apiGet("/api/session/model-status");
      if (status.ready) {
        await apiPost("/api/session/start-live");
        window.location.href = "session.html";
        return;
      }
      if (status.training_error) {
        textEl.textContent = `Training failed: ${status.training_error}`;
        return;
      }
      setTimeout(poll, 1000);
    } catch (err) {
      textEl.textContent = "Waiting for model...";
      setTimeout(poll, 2000);
    }
  };

  poll();
}

// ── Live session ──

const SESSION_SMOOTH_WINDOW_SECONDS = 60;
const SESSION_CHART_ANCHOR_SECONDS = 120;

let sessionChart          = null;
let sessionWs             = null;
let timerSeconds          = 0;
let sessionPaused         = false;
let sessionSeconds        = [0];
let sessionRawValues      = [0];
let wsKeepalive           = null;
let sessionTimerInterval  = null;
let telemetryPollInterval = null;
let sessionActive         = false;

function parseElapsed(elapsed) {
  const parts = elapsed.split(":").map(Number);
  return parts[0] * 3600 + parts[1] * 60 + parts[2];
}

function updateSessionTimerDisplay() {
  const el = document.getElementById("session-timer");
  if (el) el.textContent = formatTime(timerSeconds);
}

function startSessionClock() {
  if (sessionTimerInterval) return;
  sessionTimerInterval = setInterval(() => {
    if (!sessionPaused) {
      timerSeconds += 1;
      updateSessionTimerDisplay();
    }
  }, 1000);
}

function stopSessionClock() {
  if (sessionTimerInterval) clearInterval(sessionTimerInterval);
  sessionTimerInterval = null;
}

function stopTelemetryPolling() {
  if (telemetryPollInterval) clearInterval(telemetryPollInterval);
  telemetryPollInterval = null;
}

function movingAverageTrailing(values, windowSize) {
  return values.map((_, index) => {
    const start = Math.max(0, index - windowSize + 1);
    const slice = values.slice(start, index + 1);
    return slice.reduce((sum, value) => sum + value, 0) / slice.length;
  });
}

function buildSessionChartSeries(seconds, smoothedValues) {
  const anchor = SESSION_CHART_ANCHOR_SECONDS;
  const lastSecond = seconds[seconds.length - 1];

  if (lastSecond < anchor) {
    return seconds.map((second, index) => ({
      x: second,
      y: smoothedValues[index],
    }));
  }

  const points = [];
  for (let index = 0; index < seconds.length; index += 1) {
    const second = seconds[index];
    if (second >= anchor) {
      points.push({
        x: second - anchor,
        y: smoothedValues[index],
      });
    }
  }
  return points;
}

function initSessionChart() {
  const canvas = document.getElementById("chart-session");
  if (!canvas) return;

  sessionSeconds = [0];
  sessionRawValues = [0];

  if (sessionChart) sessionChart.destroy();

  sessionChart = new Chart(canvas, {
    type: "line",
    data: {
      datasets: [{
        label: "Fatigue Score",
        data: [{ x: 0, y: 0 }],
        borderColor: "#3D2D7A",
        backgroundColor: "transparent",
        borderWidth: 3,
        fill: false,
        tension: 0.35,
        pointRadius: 4,
        pointBackgroundColor: "#3D2D7A",
        pointBorderColor: "#FFFFFF",
        pointBorderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      animation: { duration: 400 },
      plugins: { legend: { display: false } },
      scales: {
        x: {
          type: "linear",
          grid: { display: false },
          ticks: {
            font: { size: 11 },
            color: "#7B6BA8",
            maxTicksLimit: 12,
            callback: (value) => formatTime(Math.round(value)),
          },
        },
        y: {
          grid: { color: "rgba(196,181,224,0.4)" },
          ticks: { font: { size: 11 }, color: "#7B6BA8" },
          beginAtZero: true,
          suggestedMax: 5,
          max: 10,
        },
      },
    },
  });
}

function updateSessionChart(elapsed, fatigue) {
  const second = elapsed != null ? parseElapsed(elapsed) : timerSeconds;

  if (sessionSeconds[sessionSeconds.length - 1] !== second) {
    sessionSeconds.push(second);
    sessionRawValues.push(fatigue);
  } else {
    sessionRawValues[sessionRawValues.length - 1] = fatigue;
  }

  const smoothed = movingAverageTrailing(
    sessionRawValues,
    SESSION_SMOOTH_WINDOW_SECONDS
  );
  const points = buildSessionChartSeries(sessionSeconds, smoothed);

  if (!sessionChart) return;

  sessionChart.data.datasets[0].data = points;

  const peak = Math.max(...points.map((point) => point.y), 1);
  sessionChart.options.scales.y.suggestedMax = Math.min(10, Math.ceil(peak * 1.15));
  sessionChart.update("none");
}

function applyTelemetry(msg) {
  if (sessionPaused) return;
  if (msg.fatigue == null) return;

  const fatigueEl = document.getElementById("current-fatigue");
  if (fatigueEl) fatigueEl.textContent = formatFatigueScore(msg.fatigue);

  if (msg.elapsed) {
    timerSeconds = parseElapsed(msg.elapsed);
    updateSessionTimerDisplay();
  }

  updateSessionChart(msg.elapsed || formatTime(timerSeconds), Number(msg.fatigue));
}

async function syncLiveTelemetry() {
  try {
    const data = await apiGet("/api/session/live-telemetry");
    sessionPaused = data.paused;

    const btn = document.getElementById("btn-pause");
    if (btn) {
      btn.textContent = sessionPaused ? "Continue" : "Pause";
      btn.classList.toggle("continue", sessionPaused);
    }

    applyTelemetry({
      type: "telemetry",
      fatigue: data.fatigue,
      elapsed: data.elapsed,
    });
  } catch (err) {
    console.error(err);
  }
}

function connectSessionWebSocket() {
  const wsProtocol = location.protocol === "https:" ? "wss:" : "ws:";
  sessionWs = new WebSocket(`${wsProtocol}//${location.host}/ws/session`);

  sessionWs.onopen = () => syncLiveTelemetry();

  sessionWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "telemetry") applyTelemetry(msg);
    } catch (err) {
      console.error(err);
    }
  };

  sessionWs.onclose = () => {
    if (!sessionActive) return;
    setTimeout(connectSessionWebSocket, 2000);
  };

  if (wsKeepalive) clearInterval(wsKeepalive);
  wsKeepalive = setInterval(() => {
    if (sessionWs && sessionWs.readyState === WebSocket.OPEN) {
      sessionWs.send("ping");
    }
  }, 25000);
}

async function handlePause() {
  const btn = document.getElementById("btn-pause");
  if (sessionPaused) {
    try {
      await apiPost("/api/session/resume");
      sessionPaused = false;
      btn.textContent = "Pause";
      btn.classList.remove("continue");
    } catch (err) {
      console.error(err);
    }
  } else {
    try {
      await apiPost("/api/session/pause");
      sessionPaused = true;
      btn.textContent = "Continue";
      btn.classList.add("continue");
    } catch (err) {
      console.error(err);
    }
  }
}

async function handleEndSession() {
  sessionActive = false;
  stopSessionClock();
  stopTelemetryPolling();
  if (wsKeepalive) clearInterval(wsKeepalive);
  if (sessionWs) sessionWs.close();

  try {
    await apiPost("/api/session/end");
  } catch (err) {
    console.error(err);
  }

  window.location.href = "dashboard.html";
}

async function initSession() {
  const username = requireAuth();
  if (!username) return;

  document.getElementById("profile-username").textContent = username;

  let status;
  try {
    status = await apiGet("/api/session/status");
  } catch (err) {
    console.error(err);
    return;
  }

  if (status.phase === "training") {
    window.location.href = "loading.html";
    return;
  }
  if (status.phase !== "live") {
    window.location.href = "dashboard.html";
    return;
  }

  sessionPaused = status.paused;
  const btn = document.getElementById("btn-pause");
  if (btn) {
    btn.textContent = sessionPaused ? "Continue" : "Pause";
    btn.classList.toggle("continue", sessionPaused);
  }

  initSessionChart();
  sessionActive = true;
  await syncLiveTelemetry();
  startSessionClock();
  connectSessionWebSocket();
  telemetryPollInterval = setInterval(syncLiveTelemetry, 1000);
  initInfoCards();
}

// ── Page bootstrap ──

function autoInit() {
  if (document.getElementById("blink-state") &&
      document.getElementById("btn-next")) {
    initAdjustDevice();
    return;
  }

  if (document.getElementById("calib-timer")) {
    const endBtn = document.querySelector(".btn-end-calib");
    if (endBtn) endBtn.onclick = handleEndCalibration;
    initCalibration();
    return;
  }

  if (document.getElementById("chart-fatigue") &&
      document.getElementById("calendar-grid")) {
    initDashboard();
    return;
  }

  if (document.querySelector(".loading-text") &&
      document.getElementById("tree-svg")) {
    initLoading();
    return;
  }

  if (document.getElementById("chart-session")) {
    initSession();
  }
}

document.addEventListener("DOMContentLoaded", autoInit);
