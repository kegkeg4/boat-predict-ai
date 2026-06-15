const dateInput = document.querySelector("#adminDate");
const reloadButton = document.querySelector("#adminReload");
const batchSaveButton = document.querySelector("#adminBatchSave");
const statusText = document.querySelector("#adminStatus");
const tableBody = document.querySelector("#adminTableBody");
const tableFoot = document.querySelector("#adminTableFoot");
const coverageBox = document.querySelector("#adminCoverage");
const LEARNING_LOG_KEY = "boat-predict-learning-log-v1";
let backfillPollTimer = null;

function toInputDate(date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")
  ].join("-");
}

function formatDateLabel(dateText) {
  const [, month, day] = dateText.split("-");
  return `${Number(month)}/${Number(day)}`;
}

function formatYen(value) {
  const amount = Math.round(Number(value) || 0);
  return `${amount.toLocaleString("ja-JP")}円`;
}

function formatSignedYen(value) {
  const amount = Math.round(Number(value) || 0);
  return `${amount >= 0 ? "" : "-"}${Math.abs(amount).toLocaleString("ja-JP")}`;
}

function setMoneyClass(element, value) {
  element.classList.toggle("plus", value > 0);
  element.classList.toggle("minus", value < 0);
}

function renderCoverage(payload) {
  const coverage = payload.coverage || {};
  const expected = coverage.expectedRaces || 0;
  const saved = coverage.savedRaces || payload.races || 0;
  const missing = coverage.missingRaces || 0;
  const missingVenues = coverage.missingVenues || [];
  if (!expected || !missing) {
    coverageBox.hidden = true;
    coverageBox.innerHTML = "";
    return;
  }
  const venueText = missingVenues
    .map((row) => `${row.venue} ${row.saved}/${row.expected}`)
    .join("、");
  coverageBox.hidden = false;
  coverageBox.innerHTML = `
    <div>
      <p class="eyebrow">DATA COVERAGE</p>
      <h2>保存済み ${saved} / 想定 ${expected} レース</h2>
      <p>この日の全開催場に対して、まだ ${missing} レース分の予測ログが保存されていません。未保存分は収支に含めず、数字を確定させないようにしています。</p>
    </div>
    <span>${venueText}</span>
  `;
}

function renderPerformance(payload) {
  const totals = payload.totals || {};
  const rows = payload.rows || [];
  const betModes = totals.betModes || {};
  renderCoverage(payload);
  document.querySelector("#adminTableTitle").textContent = `${formatDateLabel(payload.date)} 日別・会場別収支`;
  document.querySelector("#adminRaceCount").textContent = totals.races || 0;
  const totalMap = [
    ["#adminHonmeiTotal", totals.honmei?.net || 0],
    ["#adminNeraiTotal", totals.nerai?.net || 0],
    ["#adminAnaTotal", totals.ana?.net || 0],
    ["#adminNetTotal", totals.net || 0],
  ];
  totalMap.forEach(([selector, value]) => {
    const element = document.querySelector(selector);
    element.textContent = formatYen(value);
    setMoneyClass(element, value);
  });
  const modeOrder = ["recommended", "kenjitsu", "shobu", "ana", "miokuri"];
  const modeGrid = document.querySelector("#adminBetModeGrid");
  if (modeGrid) {
    modeGrid.innerHTML = modeOrder.map((key) => {
      const mode = betModes[key] || {};
      const net = mode.net || 0;
      const stake = mode.stake || 0;
      const returned = mode.return || 0;
      const races = mode.races || 0;
      const hits = mode.hits || 0;
      return `
        <article class="${net >= 0 ? "plus" : "minus"}">
          <small>${mode.label || key}</small>
          <strong>${formatYen(net)}</strong>
          <span>${races}R / 的中 ${hits} / 投資 ${formatYen(stake)} / 回収 ${formatYen(returned)}</span>
        </article>
      `;
    }).join("");
  }

  if (!rows.length) {
    tableBody.innerHTML = `<tr><td colspan="5" class="admin-empty">この日の保存済み予測成績はまだありません。</td></tr>`;
    tableFoot.innerHTML = "";
    return;
  }

  tableBody.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.venue}</td>
      <td class="${row.honmei.net >= 0 ? "plus" : "minus"}">${formatSignedYen(row.honmei.net)}</td>
      <td class="${row.nerai.net >= 0 ? "plus" : "minus"}">${formatSignedYen(row.nerai.net)}</td>
      <td class="${row.ana.net >= 0 ? "plus" : "minus"}">${formatSignedYen(row.ana.net)}</td>
      <td class="${row.net >= 0 ? "plus" : "minus"}">${formatSignedYen(row.net)}</td>
    </tr>
  `).join("");
  tableFoot.innerHTML = `
    <tr>
      <th>集計</th>
      <th class="${totals.honmei.net >= 0 ? "plus" : "minus"}">${formatSignedYen(totals.honmei.net)}</th>
      <th class="${totals.nerai.net >= 0 ? "plus" : "minus"}">${formatSignedYen(totals.nerai.net)}</th>
      <th class="${totals.ana.net >= 0 ? "plus" : "minus"}">${formatSignedYen(totals.ana.net)}</th>
      <th class="${totals.net >= 0 ? "plus" : "minus"}">${formatSignedYen(totals.net)}</th>
    </tr>
  `;
}

async function syncLocalLearningLog() {
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(LEARNING_LOG_KEY) || "{}");
  } catch {
    stored = {};
  }
  const events = Object.values(stored).filter((event) =>
    event && typeof event === "object" && event.date === dateInput.value
  );
  if (!events.length) return 0;
  const response = await fetch("/api/learning", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events })
  });
  if (!response.ok) throw new Error(`ローカル保存同期エラー ${response.status}`);
  return events.length;
}

async function loadPerformance() {
  statusText.textContent = "集計中...";
  reloadButton.disabled = true;
  try {
    statusText.textContent = "保存済みの収支データを集計中...";
    const response = await fetch(`/api/admin/performance?date=${encodeURIComponent(dateInput.value)}`, {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`管理データ取得エラー ${response.status}`);
    const payload = await response.json();
    renderPerformance(payload);
    statusText.textContent = `${formatDateLabel(dateInput.value)} の収支を表示中`;
  } catch (error) {
    statusText.textContent = "管理データの取得に失敗しました。";
    coverageBox.hidden = true;
    coverageBox.innerHTML = "";
    tableBody.innerHTML = `<tr><td colspan="5" class="admin-empty">${error.message}</td></tr>`;
    tableFoot.innerHTML = "";
  } finally {
    reloadButton.disabled = false;
  }
}

function renderBackfillStatus(status) {
  if (!status?.active) {
    if (status?.message && status.message !== "待機中") {
      statusText.textContent = status.message;
    }
    batchSaveButton.disabled = false;
    return false;
  }
  batchSaveButton.disabled = true;
  const total = status.totalVenues || 0;
  const completed = status.completedVenues || 0;
  const venue = status.currentVenue ? ` / ${status.currentVenue}` : "";
  statusText.textContent = `一括集計中 ${completed}/${total}場${venue} / 保存 ${status.savedEvents || 0}件`;
  return true;
}

async function pollBackfillStatus() {
  try {
    const response = await fetch("/api/admin/backfill-status", {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`status ${response.status}`);
    const status = await response.json();
    const active = renderBackfillStatus(status);
    if (active) {
      backfillPollTimer = setTimeout(pollBackfillStatus, 3000);
    } else {
      await loadPerformance();
    }
  } catch (error) {
    statusText.textContent = `一括集計の状態確認に失敗しました。${error.message ? ` (${error.message})` : ""}`;
    batchSaveButton.disabled = false;
  }
}

async function startBackfill() {
  clearTimeout(backfillPollTimer);
  batchSaveButton.disabled = true;
  statusText.textContent = "サーバー側で全会場の一括集計を開始します...";
  try {
    const response = await fetch(`/api/admin/backfill?date=${encodeURIComponent(dateInput.value)}&force=1`, {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`backfill ${response.status}`);
    const status = await response.json();
    renderBackfillStatus(status);
    backfillPollTimer = setTimeout(pollBackfillStatus, 1500);
  } catch (error) {
    statusText.textContent = `一括集計の開始に失敗しました。${error.message ? ` (${error.message})` : ""}`;
    batchSaveButton.disabled = false;
  }
}

const initialDate = new URLSearchParams(window.location.search).get("date");
dateInput.value = /^\d{4}-\d{2}-\d{2}$/.test(initialDate || "") ? initialDate : toInputDate(new Date());
reloadButton.addEventListener("click", loadPerformance);
batchSaveButton.addEventListener("click", startBackfill);
dateInput.addEventListener("change", loadPerformance);
loadPerformance();
pollBackfillStatus();
