// ── User store — persists in localStorage across page loads ──
function getUsers() {
  return JSON.parse(localStorage.getItem("eft_users") || "{}");
}

function saveUsers(users) {
  localStorage.setItem("eft_users", JSON.stringify(users));
}

// ── Auth helpers ──
function saveSession(username) {
  localStorage.setItem("eft_user", username);
}

function getSession() {
  return localStorage.getItem("eft_user");
}

function clearSession() {
  localStorage.removeItem("eft_user");
}

// ── Register ──
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

  users[username] = {
    name,
    lastname,
    password,
    firstRecording: formatDate(new Date()),
    lastRecording: null,
    calibrated: false,
  };

  saveUsers(users);
  saveSession(username);
  window.location.href = "calibration.html";
}

// ── Login ──
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

// ── Dashboard init ──
function initDashboard() {
  const username = getSession();
  if (!username) {
    window.location.href = "index.html";
    return;
  }

  const users = getUsers();
  const user  = users[username];

  if (!user) {
    window.location.href = "index.html";
    return;
  }

  document.getElementById("profile-name").textContent =
    `${user.name} ${user.lastname}`;
  document.getElementById("profile-username").textContent = username;
  document.getElementById("first-recording").textContent =
    user.firstRecording;
  document.getElementById("last-recording").textContent =
    user.lastRecording || "No recordings yet";
  document.getElementById("session-date").textContent =
    formatDate(new Date());

  initCharts("week");
}

// ── Session timer ──
let timerInterval = null;
let timerSeconds  = 0;
let isPaused      = false;

function startSession() {
  if (timerInterval) return;
  isPaused = false;
  timerInterval = setInterval(() => {
    timerSeconds++;
    document.getElementById("session-timer").textContent =
      formatTime(timerSeconds);
  }, 1000);
}

function pauseSession() {
  if (isPaused) {
    timerInterval = setInterval(() => {
      timerSeconds++;
      document.getElementById("session-timer").textContent =
        formatTime(timerSeconds);
    }, 1000);
    isPaused = false;
    document.querySelector(".btn-pause").textContent = "Pause";
  } else {
    clearInterval(timerInterval);
    timerInterval = null;
    isPaused = true;
    document.querySelector(".btn-pause").textContent = "Resume";
  }
}

function endSession() {
  clearInterval(timerInterval);
  timerInterval = null;
  timerSeconds  = 0;
  isPaused      = false;
  document.getElementById("session-timer").textContent = "00:00:00";
  document.querySelector(".btn-pause").textContent = "Pause";

  const username = getSession();
  const users    = getUsers();
  if (username && users[username]) {
    users[username].lastRecording = formatDate(new Date());
    saveUsers(users);
    document.getElementById("last-recording").textContent =
      users[username].lastRecording;
  }
}

// ── Charts ──
let blinkChart   = null;
let fatigueChart = null;

const chartData = {
  week: {
    labels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    blink:   [3.2, 3.8, 2.9, 4.1, 3.5, 2.7, 3.9],
    fatigue: [4.1, 6.2, 3.8, 7.6, 5.3, 3.1, 4.8],
  },
  day: {
    labels: ["9am", "10am", "11am", "12pm", "1pm", "2pm", "3pm"],
    blink:   [3.1, 3.4, 3.9, 4.2, 3.7, 4.5, 3.8],
    fatigue: [2.1, 3.5, 5.2, 6.8, 4.3, 7.1, 5.9],
  },
  session: {
    labels: ["0m", "5m", "10m", "15m", "20m", "25m", "30m"],
    blink:   [3.0, 3.2, 3.5, 3.8, 4.1, 4.4, 4.6],
    fatigue: [1.0, 2.5, 3.8, 5.0, 6.2, 7.0, 7.6],
  },
};

function initCharts(view) {
  const d = chartData[view];

  const commonOptions = {
    responsive: true,
    plugins: { legend: { display: false } },
    scales: {
      x: {
        grid: { display: false },
        ticks: { font: { size: 11 }, color: "#7B6BA8" },
      },
      y: {
        grid: { color: "rgba(196,181,224,0.3)" },
        ticks: { font: { size: 11 }, color: "#7B6BA8" },
      },
    },
  };

  if (blinkChart)   blinkChart.destroy();
  if (fatigueChart) fatigueChart.destroy();

  blinkChart = new Chart(document.getElementById("chart-blink"), {
    type: "bar",
    data: {
      labels: d.labels,
      datasets: [{
        data: d.blink,
        backgroundColor: "#4A3080",
        borderRadius: 4,
      }],
    },
    options: commonOptions,
  });

  fatigueChart = new Chart(document.getElementById("chart-fatigue"), {
    type: "bar",
    data: {
      labels: d.labels,
      datasets: [{
        data: d.fatigue,
        backgroundColor: "#4A3080",
        borderRadius: 4,
      }],
    },
    options: commonOptions,
  });
}

// ── Trend toggle ──
function setTrend(view, btn) {
  document.querySelectorAll("#trend-toggle button").forEach(b =>
    b.classList.remove("active")
  );
  btn.classList.add("active");
  initCharts(view);
}

// ── Sign out ──
function signOut() {
  clearSession();
  window.location.href = "index.html";
}

// ── Calibration ──
function initCalibration() {
  const username = getSession();
  if (!username) {
    window.location.href = "index.html";
    return;
  }

  const DURATION = 5 * 60;
  let remaining  = DURATION;

  const timerEl  = document.getElementById("calib-timer");
  const barEl    = document.getElementById("calib-bar");
  const pctEl    = document.getElementById("calib-percent");
  const statusEl = document.getElementById("calib-status");
  const doneEl   = document.getElementById("calib-complete");

  const interval = setInterval(() => {
    remaining--;

    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const s = String(remaining % 60).padStart(2, "0");
    timerEl.textContent = `${m}:${s}`;

    const pct = Math.round(((DURATION - remaining) / DURATION) * 100);
    barEl.style.width = `${pct}%`;
    pctEl.textContent = `${pct}%`;

    if (remaining <= 0) {
      clearInterval(interval);
      timerEl.textContent  = "00:00";
      barEl.style.width    = "100%";
      pctEl.textContent    = "100%";
      statusEl.textContent = "Complete";
      doneEl.style.display = "block";

      const users = getUsers();
      if (users[username]) {
        users[username].calibrated = true;
        saveUsers(users);
      }

      setTimeout(() => {
        window.location.href = "loading.html";
      }, 2000);
    }
  }, 1000);
}

// ── Utility functions ──
function formatTime(seconds) {
  const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function formatDate(date) {
  return date.toLocaleDateString("en-GB", {
    day: "2-digit", month: "2-digit", year: "numeric"
  });
}

function showError(el, message) {
  if (!el) return;
  el.textContent = message;
  el.classList.add("visible");
}

// ── Auto-init ──
function autoInit() {
  if (document.getElementById("calib-timer")) {
    initCalibration();
  }
  if (document.getElementById("session-timer")) {
    initDashboard();
  }
}

document.addEventListener("DOMContentLoaded", autoInit);