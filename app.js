const venues = [
  { name: "桐生", water: "淡水・静水面", home: 1.03 },
  { name: "戸田", water: "淡水・狭水面", home: 1.08 },
  { name: "江戸川", water: "汽水・難水面", home: 1.18 },
  { name: "平和島", water: "海水・風影響", home: 1.12 },
  { name: "多摩川", water: "淡水・静水面", home: 1.02 },
  { name: "浜名湖", water: "汽水・広水面", home: 1.04 },
  { name: "蒲郡", water: "汽水・静水面", home: 1.03 },
  { name: "常滑", water: "海水・風影響", home: 1.09 },
  { name: "津", water: "淡水・風影響", home: 1.08 },
  { name: "三国", water: "淡水・追い風傾向", home: 1.08 },
  { name: "びわこ", water: "淡水・うねり注意", home: 1.10 },
  { name: "住之江", water: "淡水・硬水面", home: 1.04 },
  { name: "尼崎", water: "淡水・静水面", home: 1.03 },
  { name: "鳴門", water: "海水・潮位影響", home: 1.11 },
  { name: "丸亀", water: "海水・ナイター", home: 1.07 },
  { name: "児島", water: "海水・潮位影響", home: 1.10 },
  { name: "宮島", water: "海水・潮位差大", home: 1.14 },
  { name: "徳山", water: "海水・イン優勢", home: 1.05 },
  { name: "下関", water: "海水・ナイター", home: 1.06 },
  { name: "若松", water: "海水・潮流あり", home: 1.10 },
  { name: "芦屋", water: "淡水・イン優勢", home: 1.04 },
  { name: "福岡", water: "汽水・うねりあり", home: 1.15 },
  { name: "唐津", water: "淡水・追い風傾向", home: 1.08 },
  { name: "大村", water: "海水・イン優勢", home: 1.03 }
];
const venueCourseProfiles = {
  戸田: {
    key: "anti-inner",
    innerPenalty: 5.8,
    centerBoost: 2.2,
    outsideBoost: 2.6,
    roughBoost: 1.2,
    upsetBonus: 12,
    note: "狭水面で1マークが窮屈。イン過信を下げ、センターまくりを加点"
  },
  江戸川: {
    key: "rough-river",
    innerPenalty: 4.8,
    centerBoost: 2.0,
    outsideBoost: 3.0,
    roughBoost: 2.0,
    upsetBonus: 14,
    note: "潮・流れ・波の影響が大きい難水面。ダッシュ勢と波乱を加点"
  },
  平和島: {
    key: "anti-inner-wind",
    innerPenalty: 4.0,
    centerBoost: 1.8,
    outsideBoost: 2.3,
    roughBoost: 1.5,
    upsetBonus: 10,
    note: "1マーク側が窮屈で風の影響も受けやすい。外の攻めを加点"
  },
  福岡: {
    key: "rough-estuary",
    innerPenalty: 2.4,
    centerBoost: 1.4,
    outsideBoost: 1.9,
    roughBoost: 1.5,
    upsetBonus: 8,
    note: "うねりが出やすい水面。内の安定だけで決めず展開を加味"
  },
  鳴門: {
    key: "tide",
    innerPenalty: 1.5,
    centerBoost: 1.0,
    outsideBoost: 1.5,
    roughBoost: 1.2,
    upsetBonus: 6,
    note: "潮位影響を加味し、外の連動を少し加点"
  },
  徳山: {
    key: "inner-strong",
    innerBoost: 2.0,
    centerBoost: -.4,
    outsideBoost: -.8,
    upsetBonus: -5,
    note: "イン優勢寄り。1コースの信頼をやや加点"
  },
  芦屋: {
    key: "inner-strong",
    innerBoost: 2.2,
    centerBoost: -.4,
    outsideBoost: -.9,
    upsetBonus: -5,
    note: "イン優勢寄り。1コースの信頼をやや加点"
  },
  大村: {
    key: "inner-strong",
    innerBoost: 3.0,
    centerBoost: -.7,
    outsideBoost: -1.2,
    upsetBonus: -8,
    note: "全国的にインが強い傾向を重視し、1コースを加点"
  }
};
const OFFICIAL_SIGNAL_WEIGHT = .35;
const PROGRAM_CACHE_KEY = "boat-predict-official-programs-v1";
const VENUE_STATUS_CACHE_KEY = "boat-predict-venue-status-v2";
const PREDICTION_CACHE_KEY = "boat-predict-prediction-snapshots-v1";
const RESULT_CACHE_KEY = "boat-predict-official-results-v1";
const LEARNING_LOG_KEY = "boat-predict-learning-log-v1";
const LEARNING_WEIGHTS_KEY = "boat-predict-learning-weights-v1";
const PLAN_MODE_KEY = "boat-predict-plan-mode";
const PROGRAM_CACHE_MS = 6 * 60 * 60 * 1000;
const VENUE_STATUS_CACHE_MS = 6 * 60 * 60 * 1000;
const PREDICTION_CACHE_MS = 30 * 24 * 60 * 60 * 1000;
const RESULT_CACHE_MS = 30 * 24 * 60 * 60 * 1000;
const PERFORMANCE_BET_UNIT_YEN = 100;
const RESULT_UNAVAILABLE_CACHE_MS = 15 * 1000;
const REQUEST_TIMEOUT_MS = 10000;
const MAIN_PROGRAM_TIMEOUT_MS = 25000;
const BACKGROUND_PROGRAM_TIMEOUT_MS = 6000;
const SIGNAL_TIMEOUT_MS = 7000;
const RESULT_TIMEOUT_MS = 9000;
const RESULT_BATCH_TIMEOUT_MS = 16000;
const STRATEGY_CONFIG = {
  honmei: { label: "本命", count: 5 },
  nerai: { label: "狙い目", count: 1 },
  ana: { label: "穴", count: 1 }
};
const BET_MODE_CONFIG = {
  kenjitsu: { label: "堅実", strategyKeys: ["honmei"] },
  shobu: { label: "勝負", strategyKeys: ["honmei", "nerai"] },
  ana: { label: "穴狙い", strategyKeys: ["ana"] },
  miokuri: { label: "見送り", strategyKeys: [] }
};
const GRADE_FALLBACK_STATS = {
  A1: { national: 6.2, local: 5.9, motor: 32, start: 0.16 },
  A2: { national: 5.4, local: 5.1, motor: 31, start: 0.17 },
  B1: { national: 4.3, local: 4.1, motor: 30, start: 0.18 },
  B2: { national: 3.5, local: 3.3, motor: 29, start: 0.20 }
};
const officialMarks = ["◎", "○", "△", "×"];
const raceCutoffTimes = ["10:35", "11:04", "11:33", "12:02", "12:31", "13:00", "13:29", "13:58", "14:27", "14:56", "15:25", "15:54"];
const officialRacerProfiles = {
  3072: ["西田 靖", "B1", 4.16, 4.74, 37.84, 0.15],
  3305: ["小野 信樹", "B1", 3.99, 4.00, 41.59, 0.17],
  3340: ["池田 雷太", "B1", 4.47, 4.28, 34.55, 0.19],
  3388: ["今垣 光太郎", "A1", 6.47, 6.36, 35.58, 0.15],
  3564: ["桑原 啓", "B1", 4.53, 5.22, 27.84, 0.18],
  3596: ["河上 年昭", "B1", 3.64, 5.02, 32.50, 0.17],
  3800: ["牧 宏次", "B1", 5.57, 5.05, 37.30, 0.15],
  3804: ["中渡 修作", "B1", 5.00, 5.56, 30.09, 0.17],
  3873: ["別府 昌樹", "A2", 2.87, 8.33, 48.31, 0.16],
  3915: ["繁野谷 圭介", "A2", 5.35, 6.07, 34.19, 0.17],
  4007: ["榮田 将彦", "B1", 4.52, 0.00, 39.52, 0.12],
  4034: ["西原 明生", "B1", 3.51, 4.25, 26.26, 0.18],
  4064: ["原田 篤志", "A1", 6.26, 4.82, 35.04, 0.16],
  4119: ["泥谷 一毅", "A2", 5.85, 6.10, 47.17, 0.17],
  4120: ["柘植 政浩", "A2", 5.65, 6.48, 56.12, 0.18],
  4137: ["君島 秀三", "A1", 6.65, 6.13, 47.87, 0.14],
  4271: ["川崎 公靖", "B1", 4.21, 4.48, 29.20, 0.16],
  4331: ["三好 勇人", "A2", 6.05, 5.46, 41.41, 0.15],
  4358: ["松本 庸平", "B1", 3.68, 3.53, 38.64, 0.20],
  4370: ["山口 達也", "A1", 6.25, 5.81, 43.37, 0.14],
  4407: ["鹿島 敏弘", "B1", 5.15, 5.01, 32.52, 0.18],
  4415: ["下出 卓矢", "A2", 6.27, 6.34, 48.48, 0.13],
  4486: ["野村 誠", "B1", 5.51, 5.39, 37.25, 0.17],
  4506: ["稗田 聖也", "B1", 6.52, 5.17, 32.73, 0.14],
  4537: ["渡邉 和将", "A1", 6.89, 6.26, 44.19, 0.14],
  4619: ["伏田 裕隆", "A2", 4.79, 4.75, 36.28, 0.16],
  4640: ["山ノ内 雅人", "A2", 6.10, 6.05, 39.60, 0.15],
  4660: ["宇田川 信一", "B2", 4.14, 3.52, 35.29, 0.22],
  4771: ["下寺 秀和", "A1", 7.15, 6.75, 43.88, 0.15],
  4872: ["山下 流心", "B1", 4.48, 3.72, 32.56, 0.16],
  4890: ["石川 諒", "B1", 5.89, 5.00, 29.91, 0.13],
  4957: ["竹之内 極", "B1", 5.35, 4.28, 35.83, 0.17],
  5041: ["荒牧 凪沙", "B1", 4.50, 4.90, 36.13, 0.16],
  5044: ["渡邉 健", "B1", 4.00, 3.70, 35.71, 0.14],
  5175: ["島崎 丈一朗", "B2", 5.00, 5.00, 44.71, 0.21],
  5183: ["中野 孝二", "B1", 4.77, 4.55, 41.44, 0.16],
  5234: ["塚越 海斗", "A2", 6.95, 6.63, 32.48, 0.16],
  5259: ["野田 昇吾", "B1", 3.22, 2.63, 39.22, 0.15],
  5427: ["港 理樹", "B2", 2.60, 2.00, 29.00, null],
  5445: ["一ノ木 匠", "B2", 1.69, 0.00, 30.84, null]
};
const officialPrograms = {
  "2026-06-10-01": {
    cutoffs: ["15:23", "16:00", "16:37", "17:06", "17:30", "17:57", "18:21", "18:47", "19:16", "19:43", "20:09", "20:38"],
    lineups: [
      [3072, 4271, 4407, 5259, 3305, 4370],
      [3800, 4415, 3340, 3873, 5445, 5183],
      [4506, 3596, 4358, 5044, 4007, 3388],
      [4957, 3564, 5175, 4660, 4890, 4137],
      [4771, 3915, 3804, 3072, 5427, 4407],
      [4064, 4872, 5183, 4271, 4034, 3340],
      [4537, 4358, 4119, 3305, 5259, 5041],
      [4370, 4890, 4660, 3596, 4415, 5445],
      [5044, 4007, 3564, 5175, 3804, 5427],
      [3388, 4506, 3800, 4771, 3915, 4957],
      [4137, 4537, 3873, 4119, 4872, 4064],
      [5234, 4486, 4619, 4331, 4120, 4640]
    ]
  }
};
const verifiedOfficialResults = {
  "2026-06-08-01": [
    { result: [1, 3, 4], payout: 2300 },
    { result: [4, 1, 2], payout: 6690 },
    { result: [3, 1, 4], payout: 6220 },
    { result: [1, 4, 2], payout: 2940 },
    { result: [1, 3, 2], payout: 2250 },
    { result: [6, 4, 5], payout: 80060 },
    { result: [3, 1, 4], payout: 1190 },
    { result: [3, 5, 2], payout: 2690 },
    { result: [1, 2, 3], payout: 790 },
    { result: [1, 2, 6], payout: 2380 },
    { result: [3, 4, 6], payout: 10990 },
    { result: [1, 4, 5], payout: 910 }
  ],
  "2026-06-09-01": [
    { result: [1, 3, 2], payout: 1030 },
    { result: [3, 1, 2], payout: 6820 },
    { result: [1, 5, 6], payout: 2130 },
    { result: [1, 3, 6], payout: 2720 },
    { result: [1, 2, 4], payout: 660 },
    { result: [1, 2, 5], payout: 690 },
    { result: [1, 3, 5], payout: 1080 },
    { result: [3, 5, 2], payout: 4380 },
    { result: [1, 3, 4], payout: 1560 },
    { result: [2, 5, 1], payout: 60650 },
    { result: [1, 2, 5], payout: 1180 },
    { result: [1, 3, 6], payout: 2310 }
  ]
};

const venueSelect = document.querySelector("#venue");
const dateInput = document.querySelector("#raceDate");
const raceSelector = document.querySelector("#raceSelector");
const recentDates = document.querySelector("#recentDates");
const predictButton = document.querySelector("#predictButton");
const dashboard = document.querySelector("#dashboard");
const loadingState = document.querySelector("#loadingState");
const unavailableState = document.querySelector("#unavailableState");
const warmupStatus = document.querySelector("#warmupStatus");
const freePlanButton = document.querySelector("#freePlanButton");
const premiumPlanButton = document.querySelector("#premiumPlanButton");
let selectedRace = 8;
let rankingMode = "solid";
let currentData = null;
let predictionRequestId = 0;
let activeProgramController = null;
let performanceRefreshTimer = null;
let performanceRefreshInFlight = false;
let selectedResultRefreshInFlight = false;
let performanceRenderTimer = null;
let performanceCache = { key: "", totals: null };
let predictionByRaceCache = {};
let isPremiumMode = localStorage.getItem(PLAN_MODE_KEY) === "premium";
let venueStatusByDate = loadStoredVenueStatus();
const dynamicPrograms = loadStoredPrograms();
const dynamicResults = loadStoredResults();
const dynamicRaceSignals = {};
const resultUnavailableCache = {};
const resultRequestCache = {};
const postedLearningEventKeys = new Set();
let learningWeights = loadStoredLearningWeights();

function loadStoredLearningWeights() {
  try {
    return JSON.parse(localStorage.getItem(LEARNING_WEIGHTS_KEY) || "{}");
  } catch {
    return {};
  }
}

function loadStoredPrograms() {
  try {
    const stored = JSON.parse(localStorage.getItem(PROGRAM_CACHE_KEY) || "{}");
    return Object.fromEntries(
      Object.entries(stored)
        .filter(([, item]) =>
          item?.savedAt
          && Date.now() - item.savedAt < PROGRAM_CACHE_MS
          && item.program?.available
        )
        .map(([key, item]) => [key, item.program])
    );
  } catch {
    return {};
  }
}

function loadStoredVenueStatus() {
  try {
    const stored = JSON.parse(localStorage.getItem(VENUE_STATUS_CACHE_KEY) || "{}");
    return Object.fromEntries(
      Object.entries(stored)
        .filter(([, item]) => item?.savedAt && Date.now() - item.savedAt < VENUE_STATUS_CACHE_MS)
        .map(([date, item]) => [date, item.venues || {}])
    );
  } catch {
    return {};
  }
}

function storeVenueStatus(date, venuesPayload) {
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(VENUE_STATUS_CACHE_KEY) || "{}");
  } catch {
    stored = {};
  }
  stored[date] = { savedAt: Date.now(), venues: venuesPayload };
  localStorage.setItem(VENUE_STATUS_CACHE_KEY, JSON.stringify(stored));
}

function storeProgram(key) {
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(PROGRAM_CACHE_KEY) || "{}");
  } catch {
    stored = {};
  }
  stored[key] = { savedAt: Date.now(), program: dynamicPrograms[key] };
  localStorage.setItem(PROGRAM_CACHE_KEY, JSON.stringify(stored));
  invalidatePerformanceCache();
}

function loadStoredResults() {
  try {
    const stored = JSON.parse(localStorage.getItem(RESULT_CACHE_KEY) || "{}");
    return Object.fromEntries(
      Object.entries(stored)
        .filter(([, item]) =>
          item?.savedAt
          && Date.now() - item.savedAt < RESULT_CACHE_MS
          && isValidOfficialResult(item.result)
        )
        .map(([key, item]) => [key, item.result])
    );
  } catch {
    return {};
  }
}

function storeResult(key, result) {
  if (!isValidOfficialResult(result)) return;
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(RESULT_CACHE_KEY) || "{}");
  } catch {
    stored = {};
  }
  stored[key] = { savedAt: Date.now(), result };
  const entries = Object.entries(stored)
    .filter(([, item]) => item?.savedAt && Date.now() - item.savedAt < RESULT_CACHE_MS)
    .sort((a, b) => b[1].savedAt - a[1].savedAt)
    .slice(0, 2500);
  try {
    localStorage.setItem(RESULT_CACHE_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch {
    // Storage can be full on mobile; prediction must continue without local result cache.
  }
}

function getPredictionSnapshotKey(dateString = dateInput.value, venueIndex = venueSelect.value, race = selectedRace) {
  return `${dateString}-${venueIndex}-${race}`;
}

function readPredictionSnapshotStore() {
  try {
    return JSON.parse(localStorage.getItem(PREDICTION_CACHE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writePredictionSnapshotStore(store) {
  try {
    const entries = Object.entries(store)
      .filter(([, item]) => item?.savedAt && Date.now() - item.savedAt < PREDICTION_CACHE_MS)
      .sort(([, a], [, b]) => (b.savedAt || 0) - (a.savedAt || 0))
      .slice(0, 40);
    localStorage.setItem(PREDICTION_CACHE_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch (error) {
    try {
      localStorage.removeItem(PREDICTION_CACHE_KEY);
    } catch {
      // Prediction cache is optional. Never block race rendering.
    }
  }
}

function getCachedPredictionSnapshot() {
  const item = readPredictionSnapshotStore()[getPredictionSnapshotKey()];
  if (!item?.data || !item.savedAt) return null;
  if (Date.now() - item.savedAt > PREDICTION_CACHE_MS) return null;
  if (!Array.isArray(item.data.racers) || !Array.isArray(item.data.ranking)) return null;
  return item.data;
}

function storePredictionSnapshot(data) {
  try {
    if (!data?.racers?.length || !data?.ranking?.length) return;
    const store = readPredictionSnapshotStore();
    store[getPredictionSnapshotKey()] = {
      savedAt: Date.now(),
      data
    };
    writePredictionSnapshotStore(store);
  } catch {
    // Prediction cache is a speed boost only; live prediction must keep working.
  }
}

function createTimeoutError() {
  const error = new Error("公式データ取得がタイムアウトしました");
  error.name = "TimeoutError";
  return error;
}

async function fetchWithTimeout(url, options = {}) {
  const { signal, timeoutMs = REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  if (signal?.aborted) throw new DOMException("aborted", "AbortError");
  let timeoutId;
  return Promise.race([
    fetch(url, { ...fetchOptions, signal }),
    new Promise((_, reject) => {
      timeoutId = setTimeout(() => reject(createTimeoutError()), timeoutMs);
    })
  ]).finally(() => clearTimeout(timeoutId));
}

function invalidatePerformanceCache() {
  performanceCache = { key: "", totals: null };
  predictionByRaceCache = {};
}

async function loadLearningWeights() {
  try {
    const response = await fetchWithTimeout("/api/learning", { timeoutMs: 5000 });
    if (!response.ok) throw new Error(`learning ${response.status}`);
    const payload = await response.json();
    learningWeights = payload.weights || {};
    localStorage.setItem(LEARNING_WEIGHTS_KEY, JSON.stringify(learningWeights));
    invalidatePerformanceCache();
    if (currentData) {
      const updatedData = buildRaceData();
      if (updatedData) {
        currentData = updatedData;
        renderRace(updatedData);
      }
    }
  } catch (error) {
    if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
  }
}

async function postLearningEvents(events) {
  if (!events.length) return;
  try {
    const response = await fetchWithTimeout("/api/learning", {
      method: "POST",
      timeoutMs: 6000,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events })
    });
    if (!response.ok) throw new Error(`learning post ${response.status}`);
    const payload = await response.json();
    learningWeights = payload.weights || learningWeights;
    localStorage.setItem(LEARNING_WEIGHTS_KEY, JSON.stringify(learningWeights));
    invalidatePerformanceCache();
  } catch (error) {
    if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
  }
}

function setPlanMode(mode) {
  isPremiumMode = mode === "premium";
  localStorage.setItem(PLAN_MODE_KEY, isPremiumMode ? "premium" : "free");
  applyPlanMode();
  if (currentData) {
    renderRace(currentData);
    if (isPremiumMode) {
      scheduleDailyPerformanceRefresh(predictionRequestId);
    } else {
      clearTimeout(performanceRefreshTimer);
    }
  }
}

function applyPlanMode() {
  document.body.classList.toggle("is-premium", isPremiumMode);
  freePlanButton?.classList.toggle("active", !isPremiumMode);
  premiumPlanButton?.classList.toggle("active", isPremiumMode);
  document.querySelectorAll(".premium-feature").forEach((section) => {
    section.classList.toggle("is-locked", !isPremiumMode);
    let lock = section.querySelector(":scope > .premium-lock");
    if (!lock) {
      lock = document.createElement("div");
      lock.className = "premium-lock";
      lock.innerHTML = `
        <span>PREMIUM</span>
        <strong>プレミアムで開放</strong>
        <p>本命5点・狙い目1点・穴1点、成績分析・展示後再計算を利用できます。</p>
        <a href="#plans">プランを見る</a>
      `;
      section.append(lock);
    }
  });
}

async function refreshWarmupStatus() {
  if (!warmupStatus) return;
  try {
    const response = await fetchWithTimeout("/api/warmup", { timeoutMs: 5000 });
    if (!response.ok) throw new Error(`warmup status ${response.status}`);
    const status = await response.json();
    warmupStatus.classList.toggle("is-error", false);
    warmupStatus.classList.toggle("is-warming", Boolean(status.active));
    if (status.active) {
      warmupStatus.lastChild.textContent =
        `開催確認中 ${status.checkedVenues || status.completedVenues}/${status.totalVenues}場`;
    } else if (status.finishedAt) {
      warmupStatus.lastChild.textContent =
        `開催確認済み ${status.checkedVenues || status.completedVenues}場`;
    } else {
      warmupStatus.lastChild.textContent = "データ更新済み";
    }
  } catch {
    warmupStatus.classList.toggle("is-warming", false);
    warmupStatus.classList.toggle("is-error", true);
    warmupStatus.lastChild.textContent = "取得サーバー未接続";
  }
}

function hashString(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function seededRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state += 0x6D2B79F5;
    let result = state;
    result = Math.imul(result ^ (result >>> 15), result | 1);
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
  };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function formatDate(dateString) {
  return new Intl.DateTimeFormat("ja-JP", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short"
  }).format(new Date(`${dateString}T12:00:00`));
}

function toInputDate(date) {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0")
  ].join("-");
}

function dateFromOffset(offset) {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return toInputDate(date);
}

function isPastDate(dateString = dateInput.value) {
  if (!dateString) return false;
  const selectedDate = new Date(`${dateString}T00:00:00`);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return selectedDate < today;
}

function getDayResults(dateString = dateInput.value) {
  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  return verifiedOfficialResults[`${dateString}-${jcd}`] || null;
}

function isValidOfficialResult(official) {
  if (!official || !Array.isArray(official.result) || official.result.length !== 3) {
    return false;
  }
  const boats = official.result.map(Number);
  return boats.every((boat) => Number.isInteger(boat) && boat >= 1 && boat <= 6)
    && new Set(boats).size === 3;
}

function getProgramKey(dateString = dateInput.value) {
  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  return `${dateString}-${jcd}`;
}

function getOfficialProgramRace(race = selectedRace) {
  const key = getProgramKey();
  const dynamicRace = dynamicPrograms[key]?.races
    .find((item) => item.race === race);
  if (dynamicRace) {
    return {
      ...dynamicRace,
      racers: normalizeOfficialRacers(dynamicRace.racers || [])
    };
  }
  const program = officialPrograms[key];
  if (!program) return null;
  const registrations = program.lineups[race - 1];
  if (!registrations) return null;
  return {
    cutoff: program.cutoffs[race - 1],
    racers: registrations.map((registration, index) => {
      const [name, grade, national, local, motor, start] = officialRacerProfiles[registration];
      return { boat: index + 1, registration, name, grade, national, local, motor, start };
    })
  };
}

function normalizeOfficialRacers(racers) {
  return racers.map((racer, index) => {
    const registration = Number(racer.registration);
    const profile = officialRacerProfiles[registration] || [];
    const grade = racer.grade || profile[1] || "B1";
    const fallback = GRADE_FALLBACK_STATS[grade] || GRADE_FALLBACK_STATS.B1;
    const national = Number.isFinite(racer.national) ? racer.national : Number.isFinite(profile[2]) ? profile[2] : fallback.national;
    const local = Number.isFinite(racer.local) ? racer.local : Number.isFinite(profile[3]) ? profile[3] : fallback.local;
    const motor = Number.isFinite(racer.motor) ? racer.motor : Number.isFinite(profile[4]) ? profile[4] : fallback.motor;
    const start = Number.isFinite(racer.start) ? racer.start : Number.isFinite(profile[5]) ? profile[5] : fallback.start;
    return {
      ...racer,
      boat: Number.isInteger(racer.boat) ? racer.boat : index + 1,
      registration,
      name: racer.name || profile[0] || `登録${registration || index + 1}`,
      grade,
      national,
      local,
      motor,
      start,
      statsFallback: !Number.isFinite(racer.national) || !Number.isFinite(racer.local) || !Number.isFinite(racer.motor)
    };
  });
}

async function loadOfficialProgram(signal) {
  return loadOfficialProgramForRace(selectedRace, signal, MAIN_PROGRAM_TIMEOUT_MS);
}

async function loadOfficialProgramForRace(race, signal, timeoutMs = REQUEST_TIMEOUT_MS) {
  const key = getProgramKey();
  const cached = dynamicPrograms[key];
  const cachedRace = cached?.races.find((item) => item.race === race);
  const hasUsableCachedRace = cachedRace && Array.isArray(cachedRace.racers) && cachedRace.racers.length === 6;
  if (cachedRace?.detailed || hasUsableCachedRace) return cached;
  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  let program;
  try {
    const response = await fetchWithTimeout(
      `/api/program?date=${encodeURIComponent(dateInput.value)}&jcd=${jcd}&race=${race}`,
      { signal, timeoutMs }
    );
    if (!response.ok) throw new Error(`公式データ取得エラー: ${response.status}`);
    program = await response.json();
    if (program.error) throw new Error(program.error);
  } catch (error) {
    if (cachedRace && Array.isArray(cachedRace.racers) && cachedRace.racers.length >= 6) {
      return cached;
    }
    throw error;
  }
  if (!cached) {
    dynamicPrograms[key] = program;
  } else {
    program.races.forEach((loadedRace) => {
      const index = cached.races.findIndex((item) => item.race === loadedRace.race);
      if (index >= 0) {
        if (loadedRace.detailed || !cached.races[index].detailed) {
          cached.races[index] = loadedRace;
        }
      } else {
        cached.races.push(loadedRace);
      }
    });
    cached.races.sort((a, b) => a.race - b.race);
    cached.available = program.available;
  }
  storeProgram(key);
  return dynamicPrograms[key];
}

function getRaceSignalKey(race = selectedRace) {
  return `${getProgramKey()}-${race}`;
}

function getRaceSignals(race = selectedRace) {
  return dynamicRaceSignals[getRaceSignalKey(race)] || null;
}

async function loadRaceSignals(signal, race = selectedRace) {
  const key = getRaceSignalKey(race);
  if (dynamicRaceSignals[key]) return dynamicRaceSignals[key];
  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  const response = await fetchWithTimeout(
    `/api/signals?date=${encodeURIComponent(dateInput.value)}&jcd=${jcd}&race=${race}`,
    { signal, timeoutMs: SIGNAL_TIMEOUT_MS }
  );
  if (!response.ok) throw new Error(`公式シグナル取得エラー: ${response.status}`);
  const payload = await response.json();
  if (payload.error) throw new Error(payload.error);
  dynamicRaceSignals[key] = payload;
  return payload;
}

async function refreshRaceSignals(data, requestId) {
  try {
    await loadRaceSignals(activeProgramController.signal);
    if (requestId !== predictionRequestId) return;
    const updatedData = buildRaceData();
    if (!updatedData) return;
    currentData = updatedData;
    storePredictionSnapshot(updatedData);
    renderRace(updatedData);
    renderOfficialResult(updatedData);
  } catch (error) {
    if (error.name !== "AbortError") console.warn(error);
  }
}

function getRaceCutoff(race) {
  return getOfficialProgramRace(race)?.cutoff || raceCutoffTimes[race - 1];
}

function renderRecentDates() {
  const dateOptions = [
    { offset: -2, label: "2日前" },
    { offset: -1, label: "前日" },
    { offset: 0, label: "今日" },
    { offset: 1, label: "翌日" }
  ];
  recentDates.innerHTML = dateOptions.map(({ offset, label }) => {
    const date = dateFromOffset(offset);
    const hasResults = Boolean(getDayResults(date));
    const day = Number(date.slice(-2));
    return `
      <button class="recent-date${date === dateInput.value ? " active" : ""}${hasResults ? " has-results" : ""}" type="button" data-date="${date}">
        <span>${label} ${day}日</span>
        ${hasResults ? "<b>結果あり</b>" : ""}
      </button>
    `;
  }).join("");
  recentDates.querySelectorAll("[data-date]").forEach((button) => {
    button.addEventListener("click", () => {
      dateInput.value = button.dataset.date;
      dateInput.dispatchEvent(new Event("change"));
    });
  });
}

function renderVenueOptions() {
  const selected = venueSelect.value || "0";
  const statuses = venueStatusByDate[dateInput.value] || {};
  const statusValues = Object.values(statuses);
  const activeCount = statusValues.filter((status) => status.available).length;
  venueSelect.innerHTML = "";
  venues.forEach((venue, index) => {
    const jcd = String(index + 1).padStart(2, "0");
    const status = statuses[jcd];
    const marker = status?.available ? "● " : status ? "　 " : "";
    const suffix = status?.available ? "（本日開催）" : "";
    const option = document.createElement("option");
    option.value = index;
    option.textContent = `${marker}${String(index + 1).padStart(2, "0")} ${venue.name}${suffix}`;
    option.dataset.available = status?.available ? "true" : "false";
    venueSelect.append(option);
  });
  venueSelect.value = selected;
  const hint = document.querySelector("#venueStatusHint");
  if (hint) {
    hint.textContent = statusValues.length
      ? `● 開催あり ${activeCount}場 / ${formatDate(dateInput.value)}`
      : "開催場を確認中...";
  }
}

async function refreshVenueStatus(date = dateInput.value) {
  if (!date) return;
  if (venueStatusByDate[date]) {
    renderVenueOptions();
  }
  try {
    const response = await fetchWithTimeout(`/api/venues?date=${encodeURIComponent(date)}`, { timeoutMs: 7000 });
    if (!response.ok) throw new Error(`venues ${response.status}`);
    const payload = await response.json();
    venueStatusByDate[date] = payload.venues || {};
    storeVenueStatus(date, venueStatusByDate[date]);
    if (date === dateInput.value) renderVenueOptions();
  } catch (error) {
    if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
  }
}

function boatBadge(number, small = false) {
  return `<span class="${small ? "table-boat" : "ticket-boat"} boat-${number}">${number}</span>`;
}

function buildRacerComment(racer) {
  if (Number.isFinite(racer.venueImpact) && Math.abs(racer.venueImpact) >= 2) {
    return racer.venueImpact > 0
      ? `会場特性がプラス。${racer.venueNote || "コース形状と水面傾向が展開に向きます。"}`
      : `会場特性がマイナス。${racer.venueNote || "コース形状から過信は禁物です。"}`;
  }
  if (Number.isFinite(racer.weatherImpact) && Math.abs(racer.weatherImpact) >= 1.8) {
    return racer.weatherImpact > 0
      ? `天候・風・波の水面補正がプラス。${racer.weatherNote || "展開条件が向く可能性があります。"}`
      : `天候・風・波の水面補正がマイナス。${racer.weatherNote || "水面対応が鍵になります。"}`;
  }
  if (racer.exhibitionAvailable && racer.exhibition <= 6.70 && racer.motor >= 40) {
    return "展示気配とモーターが良好。スタートが決まれば上位争い。";
  }
  if (racer.local >= racer.national + .45) {
    return "当地相性が強み。水面への対応力を高く評価したい。";
  }
  if (racer.start <= .14) {
    return "平均STが優秀。先手を取れる展開なら一発に注意。";
  }
  if (racer.grade === "A1" && racer.motor < 33) {
    return "選手力は上位だが機力は控えめ。展開を突けるかが鍵。";
  }
  if (racer.boat === 1) {
    return "インの利を生かしたい。スタート遅れがなければ残り目。";
  }
  if (racer.motor >= 42) {
    return "モーター気配は上位。外枠でも連下候補から外しにくい。";
  }
  if (racer.exhibitionAvailable && racer.exhibition >= 6.85) {
    return "展示タイムはやや重め。直前気配の上積みを確認したい。";
  }
  return "総合力は拮抗。展開とスタート次第で着順が動きそう。";
}

function calculateWeatherImpact(boat, wind, wave, direction, weatherLabel) {
  if (!Number.isFinite(wind) && !Number.isFinite(wave) && !weatherLabel) {
    return { score: 0, note: "" };
  }
  let score = 0;
  const notes = [];
  if (Number.isFinite(wind)) {
    if (wind >= 5) {
      const penalty = (wind - 4) * (boat >= 4 ? 1.7 : boat === 1 ? .35 : .8);
      score -= penalty;
      notes.push(boat >= 4 ? "強風で外枠のターン流れを警戒" : "強風でも内寄りは相対的に安定");
    } else if (wind <= 2 && boat <= 2) {
      score += .35;
      notes.push("風が弱く内枠の安定感を評価");
    }
    if (direction?.includes("追")) {
      score += boat >= 3 ? .6 : -.15;
      notes.push(boat >= 3 ? "追い風でダッシュ勢の伸びを加点" : "追い風でインの起こしに注意");
    }
    if (direction?.includes("向")) {
      score += boat === 1 ? .55 : boat >= 4 ? -.45 : .05;
      notes.push(boat === 1 ? "向かい風でインの先マイを加点" : "向かい風で外の伸びを慎重評価");
    }
  }
  if (Number.isFinite(wave) && wave >= 3) {
    const penalty = (wave - 2) * (boat >= 4 ? .75 : boat === 1 ? .2 : .4);
    score -= penalty;
    notes.push(boat >= 4 ? "波高で外枠の旋回ロスを警戒" : "波高でも内寄りは相対的に安定");
  }
  if (weatherLabel?.includes("雨")) {
    score += boat <= 2 ? .25 : -.25;
    notes.push(boat <= 2 ? "雨水面で内寄りの安定感を評価" : "雨水面で外の握り込みを慎重評価");
  }
  return { score: clamp(score, -5, 3), note: notes[0] || "" };
}

function getVenueCourseProfile(venue) {
  return venueCourseProfiles[venue.name] || {
    key: "standard",
    innerPenalty: 0,
    innerBoost: 0,
    centerBoost: 0,
    outsideBoost: 0,
    roughBoost: .6,
    upsetBonus: 0,
    note: "標準的な会場補正"
  };
}

function calculateVenueCourseImpact(venue, boat, wind, wave) {
  const profile = getVenueCourseProfile(venue);
  let score = 0;
  if (boat === 1) score += (profile.innerBoost || 0) - (profile.innerPenalty || 0);
  if (boat >= 2 && boat <= 3) score += profile.centerBoost || 0;
  if (boat >= 4) score += profile.outsideBoost || 0;
  const rough = (Number.isFinite(wind) && wind >= 4) || (Number.isFinite(wave) && wave >= 3);
  if (rough && profile.roughBoost) {
    score += boat === 1 ? -profile.roughBoost : profile.roughBoost * (boat >= 4 ? 1.15 : .75);
  }
  return {
    score: clamp(score, -7, 6),
    note: profile.note || ""
  };
}

function permutations(items, length) {
  if (length === 0) return [[]];
  return items.flatMap((item) =>
    permutations(items.filter((candidate) => candidate !== item), length - 1)
      .map((rest) => [item, ...rest])
  );
}

function setupControls() {
  renderVenueOptions();
  venueSelect.value = "0";

  const today = new Date();
  const tomorrow = new Date(today);
  const historyStart = new Date(today);
  tomorrow.setDate(today.getDate() + 1);
  historyStart.setDate(today.getDate() - 7);
  const todayString = toInputDate(today);
  dateInput.min = toInputDate(historyStart);
  dateInput.max = toInputDate(tomorrow);
  dateInput.value = isDayCompleted(todayString) ? toInputDate(tomorrow) : todayString;
  dateInput.addEventListener("change", () => {
    renderVenueOptions();
    refreshVenueStatus(dateInput.value);
    renderRecentDates();
    updateRaceButtonStates();
    updateActionButton();
    runPrediction(true);
  });
  venueSelect.addEventListener("change", () => {
    renderRecentDates();
    updateRaceButtonStates();
    updateActionButton();
    runPrediction(true);
  });

  for (let race = 1; race <= 12; race += 1) {
    const button = document.createElement("button");
    button.className = `race-button${race === selectedRace ? " active" : ""}`;
    button.type = "button";
    button.dataset.race = race;
    button.innerHTML = `<span class="race-number">${race}R</span><span class="race-result"></span>`;
    button.addEventListener("click", () => {
      selectedRace = race;
      updateRaceButtonStates();
      updateActionButton();
      runPrediction(true);
    });
    raceSelector.append(button);
  }
  renderRecentDates();
  refreshVenueStatus(dateInput.value);
  updateRaceButtonStates();
}

function isDayCompleted(dateString) {
  const now = new Date();
  const selectedDate = new Date(`${dateString}T00:00:00`);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (selectedDate < today) return true;
  if (selectedDate > today) return false;
  const [hour, minute] = getRaceCutoff(12).split(":").map(Number);
  const finalCutoff = new Date(selectedDate);
  finalCutoff.setHours(hour, minute, 0, 0);
  return now >= finalCutoff;
}

function getPredictionPhase(race) {
  const now = new Date();
  const selectedDate = new Date(`${dateInput.value}T00:00:00`);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const exhibitionAvailable = getOfficialProgramRace(race)?.racers
    .every((racer) => Number.isFinite(racer.exhibition)) || false;
  if (isRaceCompleted(race)) {
    return {
      key: "completed",
      label: exhibitionAvailable ? "終了後検証・展示反映済み" : "終了後検証・展示データ未取得",
      exhibitionAvailable
    };
  }
  if (selectedDate > today) {
    return { key: "advance", label: "前夜予測・展示タイム未反映", exhibitionAvailable: false };
  }
  const [hour, minute] = getRaceCutoff(race).split(":").map(Number);
  const cutoff = new Date(selectedDate);
  cutoff.setHours(hour, minute, 0, 0);
  const exhibitionRelease = new Date(cutoff.getTime() - 25 * 60 * 1000);
  if (now >= exhibitionRelease) {
    return {
      key: exhibitionAvailable ? "live" : "waiting",
      label: exhibitionAvailable ? "直前予測・展示タイム反映済み" : "直前予測・展示データ取得待ち",
      exhibitionAvailable
    };
  }
  return { key: "waiting", label: "事前予測・展示タイム待ち", exhibitionAvailable: false };
}

function updateRaceButtonStates() {
  document.querySelectorAll(".race-button").forEach((button) => {
    const race = Number(button.dataset.race);
    const completed = isRaceCompleted(race);
    const official = getVerifiedResult(race);
    button.classList.toggle("completed", completed);
    button.classList.toggle("verified", Boolean(official));
    button.classList.toggle("active", race === selectedRace);
    button.querySelector(".race-result").textContent = official ? official.result.join("-") : "";
    const stateLabel = official
      ? `確定着順 ${official.result.join("-")}`
      : completed ? "終了・公式結果未取得" : "予測公開中";
    button.title = `${race}R ${stateLabel}`;
    button.setAttribute("aria-label", `${race}R ${stateLabel}`);
  });
}

function updateActionButton() {
  predictButton.innerHTML = isRaceCompleted(selectedRace)
    ? '<span class="button-spark">✓</span>予測と結果を表示'
    : '<span class="button-spark">✦</span>AI予測を実行';
}

function isRaceCompleted(race) {
  if (!dateInput.value) return false;
  const now = new Date();
  const selectedDate = new Date(`${dateInput.value}T00:00:00`);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (selectedDate < today) return true;
  if (selectedDate > today) return false;
  const [hour, minute] = getRaceCutoff(race).split(":").map(Number);
  const cutoff = new Date(selectedDate);
  cutoff.setHours(hour, minute, 0, 0);
  return now >= cutoff;
}

function getVerifiedResult(race) {
  const dynamic = dynamicResults[`${getProgramKey()}-${race}`];
  if (isValidOfficialResult(dynamic)) return dynamic;
  const dayResults = getDayResults();
  const stored = dayResults?.[race - 1] || null;
  return isValidOfficialResult(stored) ? stored : null;
}

async function loadOfficialResult(signal) {
  return loadOfficialResultForRace(selectedRace, signal);
}

function mergeResultWeather(race, weather) {
  if (!weather?.available) return;
  const key = getRaceSignalKey(race);
  const current = dynamicRaceSignals[key] || {
    date: dateInput.value,
    jcd: String(Number(venueSelect.value) + 1).padStart(2, "0"),
    race,
    expect: { available: false },
    beforeinfo: { available: false, racers: {}, weather: { available: false } },
    odds: { available: false, odds: {}, firstPopularity: [] }
  };
  dynamicRaceSignals[key] = {
    ...current,
    beforeinfo: {
      ...(current.beforeinfo || {}),
      weather,
    }
  };
}

async function loadOfficialResultForRace(race, signal) {
  if (!isRaceCompleted(race)) return null;
  const key = `${getProgramKey()}-${race}`;
  if (isValidOfficialResult(dynamicResults[key])) return dynamicResults[key];
  const unavailableAt = resultUnavailableCache[key];
  if (unavailableAt && Date.now() - unavailableAt < RESULT_UNAVAILABLE_CACHE_MS) return null;
  if (resultRequestCache[key]) return resultRequestCache[key];
  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  resultRequestCache[key] = (async () => {
    try {
      const response = await fetchWithTimeout(
        `/api/result?date=${encodeURIComponent(dateInput.value)}&jcd=${jcd}&race=${race}`,
        { signal, timeoutMs: RESULT_TIMEOUT_MS }
      );
      if (!response.ok) throw new Error(`公式結果取得エラー: ${response.status}`);
      const payload = await response.json();
      if (payload.error) throw new Error(payload.error);
      return applyOfficialResultPayload(race, payload);
    } finally {
      delete resultRequestCache[key];
    }
  })();
  return resultRequestCache[key];
}

function applyOfficialResultPayload(race, payload) {
  if (!payload) return null;
  if (payload.error) return null;
  const key = `${getProgramKey()}-${race}`;
  mergeResultWeather(race, payload.weather);
  if (payload.available && isValidOfficialResult(payload.result)) {
    dynamicResults[key] = {
      ...payload.result,
      payouts: Array.isArray(payload.payouts) ? payload.payouts : []
    };
    storeResult(key, dynamicResults[key]);
    delete resultUnavailableCache[key];
    invalidatePerformanceCache();
    renderManshuBanner();
    return payload.result;
  }
  resultUnavailableCache[key] = Date.now();
  return null;
}

async function loadOfficialResultsForDay(signal, races = []) {
  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  const raceList = [...new Set(races.map(Number).filter((race) => race >= 1 && race <= 12))];
  const raceQuery = raceList.length ? `&races=${encodeURIComponent(raceList.join(","))}` : "";
  const response = await fetchWithTimeout(
    `/api/results?date=${encodeURIComponent(dateInput.value)}&jcd=${jcd}${raceQuery}`,
    { signal, timeoutMs: RESULT_BATCH_TIMEOUT_MS }
  );
  if (!response.ok) throw new Error(`公式結果一括取得エラー: ${response.status}`);
  const payload = await response.json();
  Object.entries(payload.results || {}).forEach(([raceText, resultPayload]) => {
    const race = Number(raceText);
    if (Number.isInteger(race) && race >= 1 && race <= 12) {
      applyOfficialResultPayload(race, resultPayload);
    }
  });
  return payload;
}

function buildRaceData(race = selectedRace) {
  const venue = venues[Number(venueSelect.value)];
  const officialRace = getOfficialProgramRace(race);
  if (!officialRace || !officialRace.racers?.length) return null;
  const signals = getRaceSignals(race);
  const officialScoresByBoat = signals?.expect?.scores || {};
  const officialOrderFromFocus = signals?.expect?.order || [];
  const beforeinfo = signals?.beforeinfo?.racers || {};
  const officialWeather = signals?.beforeinfo?.weather || {};
  const oddsMap = signals?.odds?.odds || {};
  const marketPopularity = signals?.odds?.firstPopularity || [];
  const weather = {
    label: officialWeather.weather || "公式未取得",
    icon: officialWeather.weather?.includes("雨") ? "☂" : officialWeather.weather?.includes("晴") ? "☀" : officialWeather.weather ? "☁" : "?"
  };
  const wind = Number.isFinite(officialWeather.windSpeed) ? officialWeather.windSpeed : null;
  const wave = Number.isFinite(officialWeather.waveHeight) ? officialWeather.waveHeight : null;
  const temperature = Number.isFinite(officialWeather.temperature) ? officialWeather.temperature : null;
  const direction = officialWeather.windDirection || "";
  const venueProfile = getVenueCourseProfile(venue);
  const learnedVenue = learningWeights[venue.name] || {};
  const phase = getPredictionPhase(race);
  const hasExhibition = officialRace.racers.every((racer) =>
    Number.isFinite(beforeinfo[racer.boat]?.exhibition)
  );
  if (hasExhibition) {
    phase.exhibitionAvailable = true;
    phase.label = "直前予測・展示タイム反映済み";
  }

  const racers = officialRace.racers.map((officialRacer) => {
    const { boat, name, registration, grade, national, local, motor } = officialRacer;
    const live = beforeinfo[boat] || {};
    const exhibition = phase.exhibitionAvailable ? live.exhibition : null;
    const condition = null;
    const start = officialRacer.start ?? 0.25;
    const courseBase = [26, 17, 13, 10, 7, 5][boat - 1];
    const weatherImpact = calculateWeatherImpact(boat, wind, wave, direction, weather.label);
    const venueImpact = calculateVenueCourseImpact(venue, boat, wind, wave);
    const learningImpact = boat === 1
      ? -(learnedVenue.innerPenaltyAdjust || 0)
      : boat >= 3 ? (learnedVenue.thirdCoverageBoost || 0) * .35 : 0;
    const localBoost = (local - national) * 3.2 * venue.home;
    const gradeBoost = grade === "A1" ? 7 : grade === "A2" ? 3 : grade === "B2" ? -2 : 0;
    const baseModelScore = courseBase
      + national * 5.1
      + local * 2.2
      + motor * .22
      + gradeBoost
      + localBoost
      + (0.18 - start) * 26
      + weatherImpact.score
      + venueImpact.score
      + learningImpact;
    const exhibitionImpact = phase.exhibitionAvailable
      ? clamp((6.78 - exhibition) * 48, -6, 7)
      : 0;
    const modelScore = baseModelScore + exhibitionImpact;
    const officialSignal = Number(officialScoresByBoat[boat]) || (
      courseBase
      + national * 2.6
      + local * 1.6
      + motor * .18
      + gradeBoost
    );

    return {
      boat,
      name,
      registration,
      grade,
      national,
      local,
      motor,
      exhibition,
      exhibitionAvailable: phase.exhibitionAvailable,
      exhibitionImpact,
      weatherImpact: weatherImpact.score,
      weatherNote: weatherImpact.note,
      venueImpact: venueImpact.score,
      venueNote: venueImpact.note,
      learningImpact,
      tilt: live.tilt,
      parts: live.parts,
      condition,
      start,
      modelScore,
      officialSignal,
      comment: ""
    };
  });
  racers.forEach((racer) => { racer.comment = buildRacerComment(racer); });

  const officialOrder = [...racers].sort((a, b) => {
    const aFocusIndex = officialOrderFromFocus.indexOf(a.boat);
    const bFocusIndex = officialOrderFromFocus.indexOf(b.boat);
    if (aFocusIndex >= 0 || bFocusIndex >= 0) {
      return (aFocusIndex < 0 ? 99 : aFocusIndex) - (bFocusIndex < 0 ? 99 : bFocusIndex);
    }
    return b.officialSignal - a.officialSignal;
  });
  officialOrder.forEach((racer, index) => {
    racer.officialRank = index + 1;
    racer.officialMark = officialMarks[index] || "";
  });

  const normalize = (value, values) => {
    const min = Math.min(...values);
    const max = Math.max(...values);
    return (value - min) / Math.max(.001, max - min);
  };
  const modelScores = racers.map((racer) => racer.modelScore);
  const officialScores = racers.map((racer) => racer.officialSignal);
  racers.forEach((racer) => {
    const modelNormalized = normalize(racer.modelScore, modelScores);
    const officialNormalized = normalize(racer.officialSignal, officialScores);
    racer.rawScore = modelNormalized * (1 - OFFICIAL_SIGNAL_WEIGHT) * 100
      + officialNormalized * OFFICIAL_SIGNAL_WEIGHT * 100;
  });

  const minScore = Math.min(...racers.map((racer) => racer.rawScore));
  const maxScore = Math.max(...racers.map((racer) => racer.rawScore));
  racers.forEach((racer) => {
    racer.aiScore = Math.round(58 + ((racer.rawScore - minScore) / Math.max(1, maxScore - minScore)) * 34);
  });

  const exponentials = racers.map((racer) => Math.exp(racer.rawScore / 13));
  const total = exponentials.reduce((sum, value) => sum + value, 0);
  racers.forEach((racer, index) => {
    racer.probability = exponentials[index] / total * 100;
  });

  const popularityOrder = marketPopularity.length
    ? [...racers].sort((a, b) => {
      const aIndex = marketPopularity.indexOf(a.boat);
      const bIndex = marketPopularity.indexOf(b.boat);
      return (aIndex < 0 ? 99 : aIndex) - (bIndex < 0 ? 99 : bIndex);
    })
    : [...racers].sort((a, b) =>
      (b.national * 7 + (7 - b.boat) * 2) - (a.national * 7 + (7 - a.boat) * 2)
    );
  popularityOrder.forEach((racer, index) => { racer.popularity = index + 1; });

  return {
    venue,
    weather,
    wind,
    wave,
    temperature,
    direction,
    phase,
    racers,
    signals,
    oddsMap,
    venueProfile,
    learnedVenue,
    ranking: [...racers].sort((a, b) => b.rawScore - a.rawScore),
    officialOrder
  };
}

function getProgramReadinessMessage() {
  const program = dynamicPrograms[getProgramKey()];
  if (program && program.available === false) {
    return {
      title: "この会場は公式番組が出ていません",
      body: "選択した開催日では、公式出走表が公開されていないか開催がありません。会場または日付を変更してください。"
    };
  }
  const officialRace = getOfficialProgramRace();
  if (!officialRace) {
    return {
      title: "公式出走表を未取得です",
      body: "取得サーバーまたは公式サイトから番組をまだ取得できていません。少し待って再実行してください。"
    };
  }
  const hasDetailedStats = officialRace.racers.every((racer) =>
    Number.isFinite(racer.national)
    && Number.isFinite(racer.local)
    && Number.isFinite(racer.motor)
  );
  if (!hasDetailedStats) {
    return {
      title: "公式出走表は取得済みです",
      body: "出走選手一覧を取得済みです。詳細成績が一部未取得のため、級別ベースの暫定補正を使って予測を表示します。"
    };
  }
  return {
    title: "公式出走表を未取得です",
    body: "選手や成績を推測で表示せず、公式番組を取得できた開催だけ予測を表示します。"
  };
}

function renderRace(data) {
  const { venue, weather, wind, wave, temperature, direction, racers, ranking, phase, venueProfile } = data;
  const cutoffTime = getRaceCutoff(selectedRace);

  renderManshuBanner();
  document.querySelector("#summaryMeta").textContent = formatDate(dateInput.value).toUpperCase();
  document.querySelector("#summaryTitle").textContent = `${venue.name} ${selectedRace}R`;
  const isCompleted = isRaceCompleted(selectedRace);
  const timeLabel = isCompleted ? "締切済み" : "締切予定";
  document.querySelector("#summaryTime").textContent = `${timeLabel} ${cutoffTime}`;
  document.querySelector(".weather-icon").textContent = weather.icon;
  document.querySelector("#weatherValue").textContent =
    `${weather.label}${Number.isFinite(temperature) ? ` / ${temperature.toFixed(1)}℃` : ""}`;
  document.querySelector("#windValue").textContent =
    Number.isFinite(wind) ? `${direction || "風向未取得"} ${wind.toFixed(0)}m` : "公式未取得";
  document.querySelector("#waveValue").textContent =
    Number.isFinite(wave) ? `${wave.toFixed(0)}cm` : "公式未取得";
  document.querySelector("#waterValue").textContent = `${venue.water} / ${venueProfile?.key === "standard" ? "標準補正" : "会場補正あり"}`;
  const phaseElement = document.querySelector("#predictionPhase");
  phaseElement.className = `prediction-phase ${phase.key}`;
  phaseElement.textContent = phase.label;
  const officialAgreement = renderOfficialSignal(data);
  const officialLeaderMatch = data.officialOrder[0].boat === ranking[0].boat;

  const confidence = clamp(Math.round(
    55
    + (ranking[0].probability - ranking[1].probability) * 1.4
    - (Number.isFinite(wave) ? wave * .5 : 0)
    + (officialAgreement - 60) * .16
    - (officialLeaderMatch ? 0 : 8)
    + (phase.exhibitionAvailable ? 2 : -4)
  ), 48, 88);
  document.querySelector("#confidenceBadge").textContent = `信頼度 ${confidence}%`;
  const laneOne = racers.find((racer) => racer.boat === 1);
  const outsideWinChance = 100 - laneOne.probability;
  const raceType = laneOne.probability >= 28
    ? { key: "solid", label: "イン信頼", text: `1号艇の1着確率が${laneOne.probability.toFixed(1)}%。相手候補を絞る堅めの組み立て向きです。` }
    : outsideWinChance >= 78
      ? { key: "upset", label: "穴気配", text: `2〜6号艇の合計1着確率が${outsideWinChance.toFixed(1)}%。差し・まくり展開を警戒します。` }
      : { key: "balanced", label: "混戦", text: "インと外艇の評価差が小さく、オッズとのバランスを重視したいレースです。" };
  const raceTypeBadge = document.querySelector("#raceTypeBadge");
  raceTypeBadge.className = `race-type-badge ${raceType.key}`;
  raceTypeBadge.textContent = raceType.label;
  document.querySelector("#raceTypeDescription").textContent = raceType.text;
  const currentTendency = buildRaceRanking(data).find((item) => item.race === selectedRace);
  document.querySelector("#currentSolidScore").textContent = Math.round(currentTendency.solid);
  document.querySelector("#currentUpsetScore").textContent = Math.round(currentTendency.upset);
  document.querySelector("#predictionHeading").textContent = isCompleted ? "予測時点の着順評価" : "着順予測";
  document.querySelector("#ticketHeading").textContent = isCompleted ? "予測時点の本命・狙い・穴予測" : "本命・狙い・穴予測";
  updateActionButton();

  document.querySelector("#predictionRows").innerHTML = ranking.map((racer, index) => `
    <div class="prediction-row">
      <div class="rank">${index === 0 ? "<b>1</b>" : index + 1}<small>位</small></div>
      <span class="boat-number boat-${racer.boat}">${racer.boat}</span>
      <div class="racer-name">
        <strong>${racer.name}</strong>
        <span>${racer.grade} / ${racer.registration}</span>
      </div>
      <div class="score-info">
        <div class="score-bar"><span style="width:${racer.aiScore}%"></span></div>
        <div class="score-detail">AI総合評価 ${racer.aiScore} / 100</div>
      </div>
      <div class="win-rate">
        <strong>${racer.probability.toFixed(1)}%</strong>
        <span>1着確率</span>
      </div>
    </div>
  `).join("");

  const [first, second] = ranking;
  renderBetDecisionCard(data);
  renderTicketStrategies(data);

  const windComment = !Number.isFinite(wind)
    ? "気象・水面データは公式から未取得のため、予測スコアには入れていません。"
    : wind >= 4.5
    ? `${direction}からの強めの風で、外艇はターン流れに注意。`
    : `風は比較的穏やかで、コース実績が反映されやすい水面。`;
  const leadComment = first.boat === 1
    ? `1号艇 ${first.name}のイン先行を中心に予測。`
    : `${first.boat}号艇 ${first.name}の当地適性と機力を高く評価。`;
  const venueComment = venueProfile?.note && venueProfile.key !== "standard"
    ? `${venue.name}は${venueProfile.note}。`
    : "";
  const turnComment = first.boat === 1
    ? `第一ターンは1号艇の先マイ、${second.boat}号艇の差し残りを本線に見ます。`
    : first.boat <= 3
      ? `第一ターンは${first.boat}号艇の差し・まくり差しが決まる展開を想定。`
      : `第一ターンは外の攻めで隊形が崩れる展開を想定し、内の残りと外の連動を評価します。`;
  const profile = buildBetDecision(data);
  const strategyGroups = buildTicketStrategyGroups(data);
  const [honmeiGroup, neraiGroup, anaGroup] = strategyGroups;
  const formatPickReason = (group, label) => {
    const pick = group?.picks?.[0];
    if (!pick) return `${label}は、公式オッズや展示情報がそろい次第もう一度評価します。`;
    const ticket = pick.ticket.map((racer) => `${racer.boat}号艇`).join("→");
    const oddsLabel = pick.actualOdds ? "公式オッズ" : "推定オッズ";
    const leader = pick.ticket[0];
    const support = pick.ticket.slice(1).map((racer) => `${racer.boat}号艇`).join("・");
    return `${label}は${ticket}。${leader.name}の1着評価、${support}の2・3着残り、${oddsLabel}${pick.estimatedOdds.toFixed(1)}倍と期待値${Math.round(pick.valueScore)}を見て選んでいます。`;
  };
  const conditionComment = [
    venueComment,
    windComment,
    Number.isFinite(wave) ? `波高は${wave.toFixed(0)}cmで、旋回ロスと差し残りのバランスを補正。` : "波高は公式未取得のため、会場傾向と選手力を優先。",
    phase.exhibitionAvailable ? "展示タイムが出ているため直前気配を加点済み。" : "展示タイム未公開のため、展示後は舟足を加えて再計算します。"
  ].filter(Boolean).join("");
  document.querySelector("#scenarioText").textContent =
    `${leadComment}${conditionComment}${turnComment}\n`
    + `${formatPickReason(honmeiGroup, "本命")} ${formatPickReason(neraiGroup, "狙い目")} ${formatPickReason(anaGroup, "穴")}\n`
    + `${profile.label}として、的中率だけでなく期待値と回収率を優先します。トリガミになりやすい低配当は評価を下げ、荒れそうな条件では外艇や人気薄の3着残りまで見ています。`;

  const factors = [
    `${first.boat}号艇 当地勝率 ${first.local.toFixed(2)}`,
    `${first.boat}号艇 AI評価 ${first.aiScore}`,
    `公式本命 ${data.officialOrder[0].boat}号艇`,
    venueProfile?.key !== "standard" ? `会場特性 ${venueProfile.note}` : "会場特性 標準",
    `モーター上位 ${[...racers].sort((a,b) => b.motor - a.motor)[0].boat}号艇`,
    Number.isFinite(first.weatherImpact) && Math.abs(first.weatherImpact) >= .1
      ? `水面補正 ${first.weatherImpact >= 0 ? "+" : ""}${first.weatherImpact.toFixed(1)}`
      : "水面補正 影響小",
    phase.exhibitionAvailable ? `展示反映 ${first.exhibition.toFixed(2)}` : "展示公開後に再計算",
    Number.isFinite(wind) ? `公式風 ${direction || ""}${wind.toFixed(0)}m` : "風未取得",
    Number.isFinite(wave) ? `公式波高 ${wave.toFixed(0)}cm` : "波未取得",
    data.signals?.odds?.available ? "公式オッズ反映" : "オッズ未取得"
  ];
  if (data.learnedVenue?.samples) {
    factors.unshift(`学習補正 ${data.learnedVenue.samples}件 / 3着補正 +${(data.learnedVenue.thirdCoverageBoost || 0).toFixed(1)}`);
  }
  if (profile.key === "watch") factors.unshift("資金管理 見送り候補");
  if (profile.key === "go") factors.unshift("資金管理 勝負候補");
  document.querySelector("#keyFactors").innerHTML = factors.map((factor) => `<span class="factor">${factor}</span>`).join("");

  renderValuePicks(data);
  renderRaceRanking(data);
  renderDailyPerformance({ renderList: false });
  renderOfficialResult(data);

  document.querySelector("#racerTable").innerHTML = racers.map((racer) => `
    <tr>
      <td>${boatBadge(racer.boat, true)}</td>
      <td><b>${racer.name}</b></td>
      <td><span class="grade ${racer.grade}">${racer.grade}</span></td>
      <td>${racer.national.toFixed(2)}${racer.statsFallback ? '<small class="fallback-stat">暫定</small>' : ""}</td>
      <td>${racer.local.toFixed(2)}${racer.statsFallback ? '<small class="fallback-stat">暫定</small>' : ""}</td>
      <td>${racer.motor.toFixed(1)}%${racer.statsFallback ? '<small class="fallback-stat">暫定</small>' : ""}</td>
      <td>${racer.exhibitionAvailable ? racer.exhibition.toFixed(2) : '<span class="exhibition-pending">未公開</span>'}</td>
      <td><span class="exhibition-impact ${racer.exhibitionImpact > 1 ? "up" : racer.exhibitionImpact < -1 ? "down" : "flat"}">${racer.exhibitionAvailable ? `${racer.exhibitionImpact >= 0 ? "+" : ""}${racer.exhibitionImpact.toFixed(1)}` : "対象外"}</span></td>
      <td><span class="exhibition-impact ${racer.weatherImpact > .8 ? "up" : racer.weatherImpact < -.8 ? "down" : "flat"}">${racer.weatherImpact >= 0 ? "+" : ""}${racer.weatherImpact.toFixed(1)}</span></td>
      <td><span class="official-mark ${["main", "second", "third", "fourth"][racer.officialRank - 1] || ""}">${racer.officialMark || "―"}</span></td>
      <td class="ai-score">${racer.aiScore}</td>
      <td>
        <div class="popularity">
          <b>${racer.popularity}番人気</b>
          <span style="width:${Math.max(12, 62 - racer.popularity * 7)}px"></span>
        </div>
      </td>
      <td class="racer-comment"><b>AI要約</b>${racer.comment}</td>
    </tr>
  `).join("");
}

function getHighPayoutHits() {
  return Array.from({ length: 12 }, (_, index) => {
    const race = index + 1;
    const official = getVerifiedResult(race);
    const prediction = getPrimaryPredictionForRace(race);
    if (!official || !prediction) return null;
    const resultKey = official.result.join("-");
    const hitPick = prediction.picks.find((pick) => pick.ticket.join("-") === resultKey);
    return hitPick && official.payout >= 5000
      ? { race, ...official, hitPick }
      : null;
  }).filter(Boolean);
}

function renderManshuBanner() {
  const banner = document.querySelector("#rainbowManshuBanner");
  if (!banner) return;
  const hits = getHighPayoutHits();
  if (!hits.length) {
    banner.hidden = true;
    banner.innerHTML = "";
    return;
  }
  const top = [...hits].sort((a, b) => b.payout - a.payout)[0];
  const hasManshu = top.payout >= 10000;
  const bannerClass = hasManshu ? "rainbow-manshu-banner manshu" : "rainbow-manshu-banner gold-hit-banner";
  banner.className = bannerClass;
  banner.hidden = false;
  banner.innerHTML = `
    <div>
      <p class="eyebrow">${hasManshu ? "MANSHU HIT" : "HIGH PAYOUT HIT"}</p>
      <strong>${hasManshu ? "万舟的中" : "50倍超え的中"} ${hits.length}本</strong>
      <span>最高 ${top.race}R ${top.result.join("-")} / ${top.payout.toLocaleString("ja-JP")}円</span>
    </div>
    <div class="manshu-list">
      ${hits.map((item) => `<b>${item.race}R ${item.result.join("-")} ${item.payout.toLocaleString("ja-JP")}円</b>`).join("")}
    </div>
  `;
}

function renderOfficialSignal(data) {
  const officialTop = data.officialOrder.slice(0, 4);
  const aiTop = data.ranking.slice(0, 3).map((racer) => racer.boat);
  const overlap = officialTop.slice(0, 3).filter((racer) => aiTop.includes(racer.boat)).length;
  const sameLeader = data.officialOrder[0].boat === data.ranking[0].boat;
  const agreement = Math.min(
    sameLeader ? 100 : 82,
    Math.round(46 + overlap * 16 + (sameLeader ? 6 : 0))
  );
  const markClasses = ["main", "second", "third", "fourth"];
  document.querySelector("#officialFocusBoats").innerHTML = officialTop.map((racer, index) => `
    ${index ? "<i>›</i>" : ""}
    ${boatBadge(racer.boat, true)}
    <span class="official-mark ${markClasses[index]}">${racer.officialMark}</span>
  `).join("");
  document.querySelector("#officialAgreement").textContent = `${agreement}%`;
  document.querySelector("#officialAgreementLabel").textContent = sameLeader
    ? "本命・上位評価が一致"
    : overlap >= 2 ? "相手候補は一致・本命相違" : "評価が分散・要注意";
  const officialLeader = officialTop[0];
  const aiLeader = data.ranking[0];
  document.querySelector("#officialSummary").textContent = officialLeader.boat === aiLeader.boat
    ? `公式シグナルと当サイトAIは、ともに${officialLeader.boat}号艇を軸評価。独立モデルが一致しているため信頼度を加点しています。`
    : `公式シグナルは${officialLeader.boat}号艇、当サイトAIは${aiLeader.boat}号艇を軸評価。見解が割れているため買い目を広げ、信頼度を抑えます。`;

  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  const hd = dateInput.value.replaceAll("-", "");
  document.querySelector("#officialSourceLink").href =
    `https://www.boatrace.jp/owpc/pc/race/pcexpect?rno=${selectedRace}&jcd=${jcd}&hd=${hd}`;
  return agreement;
}

function formatPayoutTicket(ticketText) {
  const normalized = String(ticketText || "").replace(/[－ー]/g, "-");
  const parts = normalized.split(/[-=]/).filter(Boolean);
  const separator = normalized.includes("=") ? "=" : normalized.includes("-") ? "-" : "";
  if (!parts.length) return normalized || "―";
  return parts.map((part, index) => `
    ${index ? `<i>${separator}</i>` : ""}
    ${/^[1-6]$/.test(part) ? `<span class="payout-boat boat-${Number(part)}">${part}</span>` : `<b>${part}</b>`}
  `).join("");
}

function ensurePayoutBoardStyles() {
  if (document.querySelector("#payoutBoardCriticalStyles")) return;
  const style = document.createElement("style");
  style.id = "payoutBoardCriticalStyles";
  style.textContent = `
    .payout-board{grid-column:1/-1!important;display:block!important;width:100%!important;overflow:hidden!important;border:1px solid #123d68!important;border-radius:14px!important;background:#254e67!important;box-shadow:inset 0 0 0 1px rgba(255,255,255,.12)!important}
    .payout-board *{box-sizing:border-box!important}
    .payout-board-header{display:grid!important;grid-template-columns:1fr auto 1fr!important;align-items:center!important;gap:12px!important;padding:11px 14px!important;color:#fff!important;background:linear-gradient(180deg,#287cff,#004ab4 70%,#003374)!important;text-shadow:0 2px 2px rgba(0,0,0,.55)!important;font-weight:900!important}
    .payout-board-header span:first-child{color:#ffe36b!important;font-size:17px!important;letter-spacing:.08em!important}
    .payout-board-header b{padding:0 14px!important;font-size:22px!important}
    .payout-board-header span:last-child{font-size:19px!important;text-align:center!important}
    .payout-board-body{padding:9px 10px 10px!important;background:linear-gradient(180deg,#315d78,#264f68)!important}
    .payout-row{display:grid!important;grid-template-columns:118px minmax(120px,1fr) 130px 86px!important;align-items:center!important;min-height:44px!important;color:#fff!important;background:rgba(18,49,68,.42)!important;border-bottom:1px solid rgba(255,255,255,.06)!important;text-shadow:0 2px 2px rgba(0,0,0,.65)!important}
    .payout-type{align-self:stretch!important;display:grid!important;place-items:center!important;padding:9px!important;background:linear-gradient(180deg,#1d7df7,#0040ba)!important;font-size:18px!important;font-weight:900!important}
    .payout-row:nth-child(1) .payout-type,.payout-row:nth-child(2) .payout-type{background:linear-gradient(180deg,#7d55c8,#7d18ad)!important}
    .payout-row:nth-child(n+5) .payout-type{background:linear-gradient(180deg,#329d52,#0b6033)!important}
    .payout-ticket{display:flex!important;align-items:center!important;justify-content:center!important;gap:7px!important;padding:8px!important;font-size:22px!important;font-weight:900!important}
    .payout-ticket i{color:#f4f7fb!important;font-style:normal!important}
    .payout-boat{width:30px!important;height:34px!important;display:grid!important;place-items:center!important;flex:0 0 auto!important;border-radius:4px!important;font-size:22px!important;font-weight:900!important;box-shadow:0 2px 2px rgba(0,0,0,.35)!important}
    .payout-money{padding-right:12px!important;font-size:23px!important;font-weight:900!important;text-align:right!important;letter-spacing:.03em!important}
    .payout-popularity{color:#fff!important;font-size:15px!important;font-weight:900!important}
    .payout-summary{display:grid!important;grid-template-columns:repeat(3,1fr)!important;gap:1px!important;background:rgba(255,255,255,.15)!important}
    .payout-summary div{padding:10px 12px!important;background:rgba(8,31,47,.62)!important}
    .payout-summary small{display:block!important;margin-bottom:4px!important;color:#a9d7ff!important;font-size:8px!important;font-weight:900!important;letter-spacing:.12em!important}
    .payout-summary strong{color:#fff!important;font-size:13px!important}
    @media(max-width:700px){.payout-board-header{grid-template-columns:1fr auto!important}.payout-board-header span:last-child{grid-column:1/-1!important;font-size:14px!important;text-align:left!important}.payout-row{grid-template-columns:78px minmax(92px,1fr) 92px!important;min-height:38px!important}.payout-popularity{display:none!important}.payout-type{font-size:13px!important}.payout-ticket{gap:4px!important;font-size:16px!important}.payout-boat{width:24px!important;height:28px!important;font-size:16px!important}.payout-money{font-size:16px!important}.payout-summary{grid-template-columns:1fr!important}}
  `;
  document.head.append(style);
}

function buildResultPayoutRows(official) {
  const rows = Array.isArray(official.payouts) ? [...official.payouts] : [];
  if (!rows.some((row) => row.type === "3連単")) {
    rows.push({
      type: "3連単",
      ticket: official.result.join("-"),
      payout: official.payout,
      popularity: null,
    });
  }
  const order = ["2連単", "2連複", "3連単", "3連複", "拡連複", "単勝", "複勝"];
  return rows.sort((a, b) => {
    const typeDiff = order.indexOf(a.type) - order.indexOf(b.type);
    return typeDiff || String(a.ticket).localeCompare(String(b.ticket), "ja");
  });
}

function renderPayoutBoard(official, hitPick, predictedFirst) {
  ensurePayoutBoardStyles();
  const rows = buildResultPayoutRows(official);
  const resultKey = official.result.join("-");
  return `
    <div class="payout-board">
      <div class="payout-board-header">
        <span>${String(Number(venueSelect.value) + 1).padStart(2, "0")}# ${venues[Number(venueSelect.value)].name}</span>
        <b>${selectedRace}R</b>
        <span>払戻金</span>
      </div>
      <div class="payout-board-body">
        ${rows.map((row) => `
          <div class="payout-row type-${row.type.replace(/[連複単勝式]/g, "")}">
            <div class="payout-type">${row.type}</div>
            <div class="payout-ticket">${formatPayoutTicket(row.ticket)}</div>
            <div class="payout-money">${Number(row.payout || 0).toLocaleString("ja-JP")}円</div>
            <div class="payout-popularity">${row.popularity ? `${row.popularity}番人気` : ""}</div>
          </div>
        `).join("")}
      </div>
      <div class="payout-summary">
        <div><small>確定3連単</small><strong>${resultKey}</strong></div>
        <div><small>予測判定</small><strong>${hitPick ? `${hitPick.strategyLabel}${hitPick.strategyIndex + 1}点目で的中` : "7点は不的中"}</strong></div>
        <div><small>1着評価</small><strong>${official.result[0] === predictedFirst.boat ? "1着艇を的中" : `${official.result[0]}号艇が勝利`}</strong></div>
      </div>
    </div>
  `;
}

function renderOfficialResult(data) {
  const resultCard = document.querySelector("#resultCard");
  if (!isRaceCompleted(selectedRace)) {
    resultCard.hidden = true;
    return;
  }
  ensurePayoutBoardStyles();

  const official = getVerifiedResult(selectedRace);
  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  const hd = dateInput.value.replaceAll("-", "");
  if (!official) {
    const badge = document.querySelector("#resultHitBadge");
    badge.className = `result-hit-badge ${selectedResultRefreshInFlight ? "" : "miss"}`;
    badge.textContent = selectedResultRefreshInFlight ? "結果取得中" : "公式結果未取得";
    document.querySelector(".result-grid").innerHTML = `
      <div class="payout-board payout-board-empty">
        <div class="payout-board-header">
          <span>${String(Number(venueSelect.value) + 1).padStart(2, "0")}# ${venues[Number(venueSelect.value)].name}</span>
          <b>${selectedRace}R</b>
          <span>払戻金</span>
        </div>
        <div class="payout-empty-message">${selectedResultRefreshInFlight ? "公式結果を取得中です" : "公式結果未取得"}</div>
      </div>
    `;
    document.querySelector("#resultComment").innerHTML =
      (selectedResultRefreshInFlight
        ? `このレースの公式結果を優先して取得しています。`
        : `このレースは締切時刻を過ぎていますが、結果データをまだ取り込んでいません。推測値は表示しません。`) +
      ` <a href="https://www.boatrace.jp/owpc/pc/race/raceresult?rno=${selectedRace}&jcd=${jcd}&hd=${hd}" target="_blank" rel="noreferrer">公式結果を確認 ↗</a>`;
    resultCard.hidden = false;
    return;
  }

  const strategyGroups = buildTicketStrategyGroups(data);
  const valuePicks = strategyGroups.flatMap((group) =>
    group.picks.map((pick, index) => ({ ...pick, strategyKey: group.key, strategyLabel: group.label, strategyIndex: index }))
  );
  const resultKey = official.result.join("-");
  const hitIndex = valuePicks.findIndex((pick) =>
    pick.ticket.map((racer) => racer.boat).join("-") === resultKey
  );
  const hitPick = hitIndex >= 0 ? valuePicks[hitIndex] : null;
  const badge = document.querySelector("#resultHitBadge");
  badge.className = `result-hit-badge ${hitIndex >= 0 ? "hit" : "miss"}`;
  badge.textContent = hitPick ? `${hitPick.strategyLabel}${hitPick.strategyIndex + 1}点目で的中` : "7点は不的中";
  const predictedFirst = data.ranking[0];
  const winner = official.result[0];
  document.querySelector(".result-grid").innerHTML = renderPayoutBoard(official, hitPick, predictedFirst);
  document.querySelector("#resultComment").textContent = winner === predictedFirst.boat
    ? `AI本命の${predictedFirst.boat}号艇が1着。予測時点の評価と実際の結果が一致しました。`
    : `AI本命は${predictedFirst.boat}号艇でしたが、確定結果は${resultKey}。終了後も予測を上書きせず、外れ方を検証データとして残します。`;
  resultCard.hidden = false;
}

function renderTicket(ticket, label) {
  return `
    <span class="ticket-label">${label}</span>
    ${ticket.map((racer, index) => `${index ? '<span class="ticket-arrow">›</span>' : ""}${boatBadge(racer.boat)}`).join("")}
  `;
}

function uniquePicks(picks, usedKeys = new Set()) {
  const selected = [];
  picks.forEach((pick) => {
    const key = pick.ticket.map((racer) => racer.boat).join("-");
    if (!usedKeys.has(key)) {
      usedKeys.add(key);
      selected.push(pick);
    }
  });
  return selected;
}

function ensurePickCount(primary, fallback, count, usedKeys) {
  const selected = uniquePicks(primary, usedKeys).slice(0, count);
  if (selected.length < count) {
    selected.push(...uniquePicks(fallback, usedKeys).slice(0, count - selected.length));
  }
  if (selected.length < count) {
    selected.push(...fallback
      .filter((pick) => !selected.some((selectedPick) =>
        selectedPick.ticket.map((racer) => racer.boat).join("-") === pick.ticket.map((racer) => racer.boat).join("-")
      ))
      .slice(0, count - selected.length));
  }
  return selected;
}

function buildLeaderFormationPicks(scoredPicks, data, leader) {
  if (!leader) return [];
  const supportBoats = data.ranking
    .filter((racer) => racer.boat !== leader.boat)
    .map((racer) => ({
      boat: racer.boat,
      score: racer.probability * 2.4
        + racer.officialSignal * .08
        + racer.exhibitionImpact * 2.2
        + racer.weatherImpact * 1.2
        + racer.venueImpact * 1.5
        + (racer.motor - 35) * .12
        + (0.18 - racer.start) * 20
    }))
    .sort((a, b) => b.score - a.score)
    .map((item) => item.boat);
  const findPick = (secondBoat, thirdBoat) => scoredPicks.find((pick) =>
    pick.ticket[0].boat === leader.boat
    && pick.ticket[1].boat === secondBoat
    && pick.ticket[2].boat === thirdBoat
  );
  const secondCandidates = supportBoats.slice(0, 4);
  const thirdCandidates = supportBoats.slice(0, 5);
  const formation = [];
  secondCandidates.forEach((secondBoat) => {
    thirdCandidates.forEach((thirdBoat) => {
      if (secondBoat === thirdBoat) return;
      const pick = findPick(secondBoat, thirdBoat);
      if (pick) formation.push(pick);
    });
  });
  return formation.sort((a, b) => {
    const aSecondRank = supportBoats.indexOf(a.ticket[1].boat);
    const bSecondRank = supportBoats.indexOf(b.ticket[1].boat);
    const aThirdRank = supportBoats.indexOf(a.ticket[2].boat);
    const bThirdRank = supportBoats.indexOf(b.ticket[2].boat);
    const aCoverage = (10 - aSecondRank * 2) + (7 - aThirdRank);
    const bCoverage = (10 - bSecondRank * 2) + (7 - bThirdRank);
    return (b.pairProbability * 3 + bCoverage + b.footScore * .8 + b.valueScore * .35)
      - (a.pairProbability * 3 + aCoverage + a.footScore * .8 + a.valueScore * .35);
  });
}

function buildTicketStrategyGroups(data) {
  const candidates = buildTicketCandidates(data);
  const topBoats = new Set(data.ranking.slice(0, 3).map((racer) => racer.boat));
  const officialBoats = new Set(data.officialOrder.slice(0, 3).map((racer) => racer.boat));
  const laneOne = data.racers.find((racer) => racer.boat === 1);
  const predictedLeader = data.ranking[0];
  const learned = data.learnedVenue || {};
  const upsetSignal = laneOne ? 100 - laneOne.probability : 50;
  const withScores = candidates.map((pick) => {
    const agreement = pick.ticket.filter((racer) => officialBoats.has(racer.boat)).length;
    const topCount = pick.ticket.filter((racer) => topBoats.has(racer.boat)).length;
    const popularityRisk = pick.ticket.reduce((sum, racer) => sum + racer.popularity, 0);
    const outsideCount = pick.ticket.filter((racer) => racer.boat >= 4).length;
    const favoriteCount = pick.ticket.filter((racer) => racer.popularity <= 2).length;
    const firstPopularity = pick.ticket[0].popularity;
    const oddsScore = Math.log(Math.max(2, pick.estimatedOdds));
    const lowProbabilityBonus = clamp(3.2 - pick.probability, 0, 3.2);
    const edgeBonus = Math.max(0, pick.valueScore - 100);
    const torigamiPenalty = pick.estimatedOdds < 7 ? (7 - pick.estimatedOdds) * 9 : 0;
    return {
      ...pick,
      agreement,
      topCount,
      popularityRisk,
      outsideCount,
      favoriteCount,
      firstPopularity,
      oddsScore,
      lowProbabilityBonus,
      edgeBonus,
      torigamiPenalty,
      honmeiScore: pick.valueScore * 1.45 + pick.probability * 2.1 + agreement * 3 + topCount * 1.4 + pick.footScore * 1.2 + (learned.thirdCoverageBoost || 0) * .8 - torigamiPenalty,
      neraiScore: pick.valueScore * (1.8 + (learned.valueBoost || 0) * .08) + edgeBonus * 1.4 + oddsScore * 8 + topCount * 2 + pick.footScore * 1.5 - Math.abs(pick.probability - 1.8) * 3,
      anaScore: pick.valueScore * (.95 + (learned.valueBoost || 0) * .06) + oddsScore * 16 + lowProbabilityBonus * 8 + popularityRisk * 1.4 + outsideCount * 5 + Math.max(0, upsetSignal - 65) * .7 - favoriteCount * 3 - agreement * 1.2
    };
  });
  const usedKeys = new Set();
  const leaderAxisPool = [...withScores]
    .filter((pick) => pick.ticket[0].boat === predictedLeader.boat)
    .sort((a, b) => {
      const aPair = a.pairProbability * 2.2 + a.footScore * 1.4 + a.valueScore * .55 - a.torigamiPenalty;
      const bPair = b.pairProbability * 2.2 + b.footScore * 1.4 + b.valueScore * .55 - b.torigamiPenalty;
      return bPair - aPair;
    });
  const leaderFormationPool = buildLeaderFormationPicks(withScores, data, predictedLeader);
  const honmeiPool = [...withScores]
    .filter((pick) => pick.estimatedOdds >= 5 && (pick.valueScore >= 78 || pick.probability >= 1.5))
    .sort((a, b) => b.honmeiScore - a.honmeiScore);
  const honmeiPrimary = predictedLeader.probability >= 24
    ? [...leaderFormationPool, ...leaderAxisPool, ...honmeiPool]
    : honmeiPool;
  const honmei = ensurePickCount(honmeiPrimary, withScores, STRATEGY_CONFIG.honmei.count, usedKeys);

  const neraiPool = withScores
    .filter((pick) =>
      pick.valueScore >= 100
      && pick.estimatedOdds >= 7
      && pick.estimatedOdds <= 80
      && pick.probability >= .55
      && pick.topCount >= 1
    )
    .sort((a, b) => b.neraiScore - a.neraiScore);
  const neraiFallback = [...withScores]
    .filter((pick) => pick.estimatedOdds >= 5 && pick.topCount >= 1)
    .sort((a, b) => b.neraiScore - a.neraiScore);
  const nerai = ensurePickCount(neraiPool, neraiFallback, STRATEGY_CONFIG.nerai.count, usedKeys);

  const anaPool = withScores
    .filter((pick) =>
      pick.valueScore >= 85
      && pick.estimatedOdds >= 25
      && pick.probability <= 2.4
      && upsetSignal >= 58
      && (
        pick.outsideCount >= 1
        || pick.firstPopularity >= 3
        || pick.popularityRisk >= 11
      )
    )
    .sort((a, b) => b.anaScore - a.anaScore);
  const anaFallback = [...withScores]
    .filter((pick) => pick.estimatedOdds >= 15)
    .sort((a, b) => b.anaScore - a.anaScore);
  const ana = ensurePickCount(anaPool, anaFallback, STRATEGY_CONFIG.ana.count, usedKeys);

  return [
    { key: "honmei", label: STRATEGY_CONFIG.honmei.label, count: STRATEGY_CONFIG.honmei.count, picks: honmei },
    { key: "nerai", label: STRATEGY_CONFIG.nerai.label, count: STRATEGY_CONFIG.nerai.count, picks: nerai },
    { key: "ana", label: STRATEGY_CONFIG.ana.label, count: STRATEGY_CONFIG.ana.count, picks: ana }
  ];
}

function renderTicketGroup(mainSelector, subSelector, group, mainLabel) {
  const picks = group.picks;
  document.querySelector(mainSelector).innerHTML = picks[0]
    ? `${renderTicket(picks[0].ticket, mainLabel)}<small class="ticket-meta">${picks[0].probability.toFixed(2)}% / ${picks[0].actualOdds ? "公式" : "推定"}${picks[0].estimatedOdds.toFixed(1)}倍</small>`
    : "―";
  document.querySelector(subSelector).innerHTML = picks.slice(1, group.count).map((pick) => `
    <div class="sub-ticket">
      <span class="sub-ticket-combo">${pick.ticket.map((racer, index) => `${index ? "<i>–</i>" : ""}<b>${racer.boat}</b>`).join("")}</span>
      <small>${pick.probability.toFixed(2)}% / ${pick.estimatedOdds.toFixed(1)}倍</small>
    </div>
  `).join("");
}

function renderTicketStrategies(data) {
  const [honmei, nerai, ana] = buildTicketStrategyGroups(data);
  renderTicketGroup("#solidTicket", "#solidSubTickets", honmei, "本命");
  renderTicketGroup("#aimTicket", "#aimSubTickets", nerai, "狙い目");
  renderTicketGroup("#upsetTicket", "#upsetSubTickets", ana, "穴");
  const profile = buildBetDecision(data, [honmei, nerai, ana]);
  const note = document.querySelector("#ticketStrategyNote");
  if (note) {
    note.textContent = `${profile.label}: ${profile.text}`;
    note.className = `ticket-note ${profile.key}`;
  }
}

function renderBetDecisionCard(data) {
  const groups = buildTicketStrategyGroups(data);
  const decision = buildBetDecision(data, groups);
  const card = document.querySelector("#betDecisionCard");
  if (!card) return;
  card.className = `bet-decision-card ${decision.key}`;
  document.querySelector("#betDecisionLabel").textContent = decision.label;
  document.querySelector("#betDecisionAction").textContent = decision.buy
    ? `${decision.label}で買う`
    : "このレースは見送り推奨";
  document.querySelector("#betDecisionReason").textContent = decision.text;
  const buyPicks = groups
    .filter((group) => decision.strategyKeys.includes(group.key))
    .flatMap((group) => group.picks.map((pick, index) => ({ ...pick, label: `${group.label}${index + 1}` })));
  document.querySelector("#betDecisionTickets").innerHTML = decision.buy && buyPicks.length
    ? buyPicks.map((pick) => `
      <span>
        <b>${pick.label}</b>
        ${pick.ticket.map((racer) => racer.boat).join("-")}
        <small>${pick.estimatedOdds.toFixed(1)}倍</small>
      </span>
    `).join("")
    : `<span class="no-bet"><b>買い目なし</b><small>資金温存</small></span>`;
}

function buildTicketCandidates(data) {
  const { ranking } = data;
  const combinations = permutations(ranking, 3);
  const publicScores = ranking.map((racer) =>
    Math.exp(((7 - racer.popularity) * 1.15 + (7 - racer.boat) * .28) / 3.2)
  );
  const publicTotal = publicScores.reduce((sum, score) => sum + score, 0);
  const publicProbability = new Map(
    ranking.map((racer, index) => [racer.boat, publicScores[index] / publicTotal])
  );

  return combinations.map((ticket) => {
    const [first, second, third] = ticket;
    const firstChance = first.probability / 100;
    const secondShare = second.probability / Math.max(1, 100 - first.probability);
    const thirdShare = third.probability / Math.max(1, 100 - first.probability - second.probability);
    const probability = clamp(firstChance * secondShare * thirdShare * 100 * 1.9, .05, 24);
    const pairProbability = clamp(firstChance * secondShare * 100 * 1.35, .1, 42);

    const firstPublic = publicProbability.get(first.boat);
    const secondPublic = publicProbability.get(second.boat) / Math.max(.01, 1 - firstPublic);
    const thirdPublic = publicProbability.get(third.boat) / Math.max(.01, 1 - firstPublic - publicProbability.get(second.boat));
    const ticketKey = ticket.map((racer) => racer.boat).join("-");
    const actualOdds = data.oddsMap?.[ticketKey];
    const rawMarketChance = clamp(firstPublic * secondPublic * thirdPublic * 1.65, .0005, .35);
    const modelChance = probability / 100;
    const marketChance = modelChance * .72 + rawMarketChance * .28;
    const estimatedOdds = actualOdds || clamp(.76 / marketChance, 2.1, 250);
    const valueScore = probability * estimatedOdds;
    const footScore = ticket.reduce((sum, racer, index) => {
      const orderWeight = index === 0 ? 1.25 : index === 1 ? 1 : .8;
      return sum + (
        racer.exhibitionImpact * 1.8
        + racer.weatherImpact * 1.1
        + racer.venueImpact * 1.35
        + (racer.motor - 35) * .08
        + (0.18 - racer.start) * 18
      ) * orderWeight;
    }, 0);
    return { ticket, probability, pairProbability, estimatedOdds, valueScore, footScore, actualOdds: Boolean(actualOdds) };
  })
    .sort((a, b) => b.valueScore - a.valueScore);
}

function buildInvestmentProfile(data) {
  const candidates = buildTicketCandidates(data);
  const best = candidates[0] || null;
  const positiveCount = candidates.filter((pick) => pick.valueScore >= 100 && pick.estimatedOdds >= 7).length;
  const laneOne = data.racers.find((racer) => racer.boat === 1);
  const leaderGap = data.ranking[0].probability - data.ranking[1].probability;
  const waterRisk = (Number.isFinite(data.wind) ? data.wind : 0) + (Number.isFinite(data.wave) ? data.wave * .7 : 0);
  if (!best) {
    return { key: "watch", label: "見送り候補", text: "期待値を計算できる買い目がまだ不足しています。" };
  }
  if (best.valueScore >= 115 && positiveCount >= 3 && waterRisk <= 7) {
    return {
      key: "go",
      label: "勝負候補",
      text: `期待値${best.valueScore.toFixed(0)}、妙味候補${positiveCount}点。回収率重視で少点数に絞るレースです。`
    };
  }
  if (best.valueScore >= 100 || (leaderGap >= 10 && laneOne?.probability >= 30)) {
    return {
      key: "selective",
      label: "絞り候補",
      text: `最高期待値${best.valueScore.toFixed(0)}。本命寄りはトリガミを避け、オッズ確認後に買い目を絞ります。`
    };
  }
  return {
    key: "watch",
    label: "見送り候補",
    text: `最高期待値${best.valueScore.toFixed(0)}。的中率より回収率を優先し、無理に全レース買わない判断です。`
  };
}

function buildBetDecision(data, groups = buildTicketStrategyGroups(data), race = selectedRace) {
  const picks = groups.flatMap((group) =>
    group.picks.map((pick, index) => ({
      ...pick,
      strategyKey: group.key,
      strategyLabel: group.label,
      strategyIndex: index
    }))
  );
  const best = [...picks].sort((a, b) => b.valueScore - a.valueScore)[0] || null;
  const positiveCount = picks.filter((pick) => pick.valueScore >= 100 && pick.estimatedOdds >= 7).length;
  const laneOne = data.racers.find((racer) => racer.boat === 1);
  const leaderGap = data.ranking[0].probability - data.ranking[1].probability;
  const tendency = buildRaceRanking(data).find((item) => item.race === race) || { solid: 50, upset: 50 };
  const waterRisk = (Number.isFinite(data.wind) ? data.wind : 0) + (Number.isFinite(data.wave) ? data.wave * .7 : 0);
  const topHonmei = groups.find((group) => group.key === "honmei")?.picks?.[0];
  const topAna = groups.find((group) => group.key === "ana")?.picks?.[0];

  if (!best || best.valueScore < 78) {
    return { key: "miokuri", label: "見送り", buy: false, strategyKeys: [], text: "期待値が低く、買うほど回収率を削りやすいレースです。" };
  }
  if (topAna && tendency.upset >= 66 && topAna.estimatedOdds >= 25 && laneOne?.probability < 30 && topAna.valueScore >= 88) {
    return { key: "ana", label: "穴狙い", buy: true, strategyKeys: BET_MODE_CONFIG.ana.strategyKeys, text: `穴気配${Math.round(tendency.upset)}。高配当候補を穴1点だけに絞る判断です。` };
  }
  if (best.valueScore >= 115 && positiveCount >= 2 && waterRisk <= 8) {
    return { key: "shobu", label: "勝負", buy: true, strategyKeys: BET_MODE_CONFIG.shobu.strategyKeys, text: `期待値${best.valueScore.toFixed(0)}、妙味候補${positiveCount}点。本命5点＋狙い目1点で勝負します。` };
  }
  if (topHonmei && laneOne?.probability >= 30 && tendency.solid >= 66 && leaderGap >= 8 && waterRisk <= 7 && topHonmei.estimatedOdds >= 4.5) {
    return { key: "kenjitsu", label: "堅実", buy: true, strategyKeys: BET_MODE_CONFIG.kenjitsu.strategyKeys, text: `堅め度${Math.round(tendency.solid)}。本命5点だけで相手を絞るレースです。` };
  }
  return { key: "miokuri", label: "見送り", buy: false, strategyKeys: [], text: `最高期待値${best.valueScore.toFixed(0)}。買い条件が足りないため、無理に手を出さない判断です。` };
}

function renderValuePicks(data) {
  const visibleCount = isPremiumMode ? 5 : 3;
  const picks = buildTicketCandidates(data).slice(0, visibleCount);
  document.querySelector("#valuePicks").innerHTML = picks.map((pick, index) => `
    <article class="value-pick">
      <span class="value-rank">#${index + 1}</span>
      <div class="value-combination">
        ${pick.ticket.map((racer, ticketIndex) => `${ticketIndex ? "<i>›</i>" : ""}${boatBadge(racer.boat, true)}`).join("")}
      </div>
      <div class="value-stats">
        <div class="value-stat"><small>AI予測確率</small><strong>${pick.probability.toFixed(2)}%</strong></div>
        <div class="value-stat"><small>${pick.actualOdds ? "公式オッズ" : "推定オッズ"}</small><strong>${pick.estimatedOdds.toFixed(1)}</strong></div>
      </div>
      <div class="value-score"><span>期待値スコア</span><strong>${pick.valueScore.toFixed(0)}</strong></div>
      <span class="value-judgement${pick.valueScore < 100 ? " watch" : ""}">${pick.valueScore >= 100 ? "期待値あり" : "見送り寄り"}</span>
    </article>
  `).join("") + (!isPremiumMode ? `
    <article class="value-pick locked-pick">
      <span class="value-rank">PREMIUM</span>
      <strong>残り2点を開放</strong>
      <p>本命5点・狙い目1点・穴1点、公式オッズ反映・展示後の再計算はプレミアムで利用できます。</p>
      <a href="#plans">プランを見る</a>
    </article>
  ` : "");
}

function buildRaceRanking(data) {
  const profile = data.venueProfile || getVenueCourseProfile(data.venue);
  return Array.from({ length: 12 }, (_, index) => {
    const race = index + 1;
    const random = seededRandom(hashString(`${data.venue.name}-${dateInput.value}-${race}-pickup`));
    const venueInnerPenalty = profile.innerPenalty || 0;
    const venueInnerBoost = profile.innerBoost || 0;
    const laneOneStrength = clamp(43 + random() * 47 - data.wind * 1.2 - venueInnerPenalty * 2.8 + venueInnerBoost * 2.4, 22, 92);
    const upsetStrength = clamp(100 - laneOneStrength + random() * 18 + (profile.upsetBonus || 0), 18, 92);
    return { race, solid: laneOneStrength, upset: upsetStrength };
  });
}

function renderRaceRanking(data) {
  const rankings = buildRaceRanking(data)
    .sort((a, b) => b[rankingMode] - a[rankingMode])
    .slice(0, 6);
  const completedNote = rankings.some((item) => isRaceCompleted(item.race))
    ? " 終了レースは予測時点の評価として表示します。"
    : "";
  document.querySelector("#rankingDescription").textContent = (rankingMode === "solid"
    ? "1号艇の逃げ確率が高く、相手候補を絞りやすいレースを上位表示します。"
    : "2〜6号艇の1着可能性が高く、差し・まくりで配当妙味が出やすいレースを上位表示します。") + completedNote;
  document.querySelector("#raceRankingList").innerHTML = rankings.map((item, index) => `
    <button class="race-rank-item ${rankingMode}${item.race === selectedRace ? " selected" : ""}${isRaceCompleted(item.race) ? " completed" : ""}" type="button" data-race-pick="${item.race}">
      <span class="race-rank-head"><strong>${item.race}R</strong><span>#${index + 1}</span></span>
      <span class="race-rank-meter"><span style="width:${item[rankingMode]}%"></span></span>
      <span class="race-rank-label">${rankingMode === "solid" ? "イン信頼度" : "波乱期待度"} ${Math.round(item[rankingMode])}</span>
    </button>
  `).join("");
  document.querySelectorAll("[data-race-pick]").forEach((button) => {
    button.addEventListener("click", () => {
      selectedRace = Number(button.dataset.racePick);
      updateRaceButtonStates();
      updateActionButton();
      runPrediction(true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
}

function getPrimaryPredictionForRace(race) {
  const key = `${getPerformanceCacheKeyBase()}-${race}`;
  if (predictionByRaceCache[key]) return predictionByRaceCache[key];
  const raceData = buildRaceData(race);
  if (!raceData) return null;
  const groups = buildTicketStrategyGroups(raceData);
  const betDecision = buildBetDecision(raceData, groups, race);
  const picks = groups.flatMap((group) =>
    group.picks.map((pick, index) => ({
      ticket: pick.ticket.map((racer) => racer.boat),
      probability: pick.probability,
      estimatedOdds: pick.estimatedOdds,
      actualOdds: pick.actualOdds,
      strategyKey: group.key,
      strategyLabel: group.label,
      strategyIndex: index
    }))
  );
  const prediction = {
    data: raceData,
    betDecision,
    ticket: picks[0]?.ticket || raceData.ranking.slice(0, 3).map((racer) => racer.boat),
    groups: groups.map((group) => ({ key: group.key, label: group.label, picks: picks.filter((pick) => pick.strategyKey === group.key) })),
    picks
  };
  predictionByRaceCache[key] = prediction;
  return prediction;
}

function getPerformanceCacheKeyBase() {
  const program = dynamicPrograms[getProgramKey()];
  const detailedRaces = program?.races
    ?.filter((race) => race.detailed)
    .map((race) => race.race)
    .join(",") || "";
  return `${dateInput.value}-${venueSelect.value}-${detailedRaces}-${isPremiumMode ? "premium" : "free"}`;
}

function calculateDailyPerformance() {
  const totals = {
    predicted: 0,
    completed: 0,
    judged: 0,
    exactHits: 0,
    exactaHits: 0,
    leaderHits: 0,
    simulatedStake: 0,
    simulatedReturn: 0,
    simulatedNet: 0,
    strategy: {
      honmei: { label: STRATEGY_CONFIG.honmei.label, count: STRATEGY_CONFIG.honmei.count, stake: 0, return: 0, net: 0, hits: 0 },
      nerai: { label: STRATEGY_CONFIG.nerai.label, count: STRATEGY_CONFIG.nerai.count, stake: 0, return: 0, net: 0, hits: 0 },
      ana: { label: STRATEGY_CONFIG.ana.label, count: STRATEGY_CONFIG.ana.count, stake: 0, return: 0, net: 0, hits: 0 }
    },
    betModes: {
      recommended: { label: "推奨だけ", stake: 0, return: 0, net: 0, hits: 0, races: 0 },
      kenjitsu: { label: BET_MODE_CONFIG.kenjitsu.label, stake: 0, return: 0, net: 0, hits: 0, races: 0 },
      shobu: { label: BET_MODE_CONFIG.shobu.label, stake: 0, return: 0, net: 0, hits: 0, races: 0 },
      ana: { label: BET_MODE_CONFIG.ana.label, stake: 0, return: 0, net: 0, hits: 0, races: 0 },
      miokuri: { label: BET_MODE_CONFIG.miokuri.label, stake: 0, return: 0, net: 0, hits: 0, races: 0 }
    },
    rows: []
  };

  for (let race = 1; race <= 12; race += 1) {
    const prediction = getPrimaryPredictionForRace(race);
    if (!prediction) continue;
    totals.predicted += 1;
    const row = {
      race,
      prediction,
      betDecision: prediction.betDecision,
      official: null,
      status: isRaceCompleted(race) ? "completed" : "waiting",
      hitIndex: -1,
      exactaHit: false,
      leaderHit: false
    };
    totals.rows.push(row);
    if (!isRaceCompleted(race)) continue;
    totals.completed += 1;
    const official = getVerifiedResult(race);
    if (!official) continue;
    row.official = official;
    totals.judged += 1;
    const purchasedTickets = prediction.picks.length;
    row.simulatedStake = purchasedTickets * PERFORMANCE_BET_UNIT_YEN;
    row.simulatedReturn = 0;
    const resultKey = official.result.join("-");
    row.hitIndex = prediction.picks.findIndex((pick) => pick.ticket.join("-") === resultKey);
    row.hitPick = row.hitIndex >= 0 ? prediction.picks[row.hitIndex] : null;
    row.exactaHit = prediction.picks.some((pick) =>
      pick.ticket[0] === official.result[0] && pick.ticket[1] === official.result[1]
    );
    row.leaderHit = prediction.picks.some((pick) => pick.ticket[0] === official.result[0]);
    Object.values(totals.strategy).forEach((strategy) => {
      strategy.stake += strategy.count * PERFORMANCE_BET_UNIT_YEN;
      strategy.net -= strategy.count * PERFORMANCE_BET_UNIT_YEN;
    });
    if (row.hitIndex >= 0) {
      totals.exactHits += 1;
      row.simulatedReturn = official.payout;
      const strategy = totals.strategy[row.hitPick.strategyKey];
      if (strategy) {
        strategy.return += official.payout;
        strategy.net += official.payout;
        strategy.hits += 1;
      }
    }
    const decision = prediction.betDecision || BET_MODE_CONFIG.miokuri;
    const selectedStrategyKeys = new Set(decision.strategyKeys || []);
    const recommendedPicks = prediction.picks.filter((pick) => selectedStrategyKeys.has(pick.strategyKey));
    row.recommendedStake = recommendedPicks.length * PERFORMANCE_BET_UNIT_YEN;
    row.recommendedReturn = row.hitPick && selectedStrategyKeys.has(row.hitPick.strategyKey) ? official.payout : 0;
    row.recommendedNet = row.recommendedReturn - row.recommendedStake;
    if (decision.buy && row.recommendedStake > 0) {
      ["recommended", decision.key].forEach((modeKey) => {
        const mode = totals.betModes[modeKey];
        if (!mode) return;
        mode.races += 1;
        mode.stake += row.recommendedStake;
        mode.return += row.recommendedReturn;
        mode.net += row.recommendedNet;
        if (row.recommendedReturn > 0) mode.hits += 1;
      });
    } else {
      totals.betModes.miokuri.races += 1;
    }
    row.simulatedNet = row.simulatedReturn - row.simulatedStake;
    totals.simulatedStake += row.simulatedStake;
    totals.simulatedReturn += row.simulatedReturn;
    totals.simulatedNet += row.simulatedNet;
    if (row.leaderHit) {
      totals.leaderHits += 1;
    }
    if (row.exactaHit) {
      totals.exactaHits += 1;
    }
  }
  return totals;
}

function getPerformanceCacheKey() {
  const resultKey = Array.from({ length: 12 }, (_, index) => {
    const race = index + 1;
    const result = getVerifiedResult(race);
    return result ? `${race}:${result.result.join("-")}:${result.payout}` : `${race}:none`;
  }).join("|");
  return `${getPerformanceCacheKeyBase()}-${resultKey}`;
}

function getDailyPerformanceTotals() {
  const key = getPerformanceCacheKey();
  if (performanceCache.key === key && performanceCache.totals) {
    return performanceCache.totals;
  }
  const totals = calculateDailyPerformance();
  performanceCache = { key, totals };
  return totals;
}

function renderTicketText(ticket) {
  return ticket.join("-");
}

function formatYen(value) {
  return `${Math.round(value).toLocaleString("ja-JP")}円`;
}

function formatSignedYen(value) {
  const rounded = Math.round(value);
  return `${rounded >= 0 ? "+" : "-"}${Math.abs(rounded).toLocaleString("ja-JP")}円`;
}

function renderPerformanceRaceList(rows) {
  const list = document.querySelector("#performanceRaceList");
  if (!list) return;
  if (!rows.length) {
    list.innerHTML = `<p class="performance-empty">この条件では、まだ予測対象レースを取得できていません。</p>`;
    return;
  }
  list.innerHTML = rows.map((row) => {
    const isFetchingResult = performanceRefreshInFlight && row.status === "completed" && !row.official;
    const resultText = row.official
      ? renderTicketText(row.official.result)
      : row.status === "completed" ? (isFetchingResult ? "取得中" : "結果未取得") : "未終了";
    const hitLabel = row.official
      ? row.hitPick ? `${row.hitPick.strategyLabel}${row.hitPick.strategyIndex + 1}点目で的中` : "7点内不的中"
      : row.status === "completed" ? (isFetchingResult ? "取得中" : "判定待ち") : "レース前";
    const decision = row.betDecision || { key: "miokuri", label: "見送り", buy: false };
    const hitClass = row.official
      ? row.hitIndex >= 0 ? "hit" : "miss"
      : "pending";
    return `
      <article class="performance-race ${hitClass}">
        <div class="performance-race-head">
          <strong>${row.race}R</strong>
          <span>${decision.label} / ${hitLabel}</span>
        </div>
        <div class="performance-result">
          <small>確定</small>
          <b>${resultText}</b>
          ${row.official ? `<em>${row.exactaHit ? "2連単形OK / " : ""}${row.official.payout.toLocaleString("ja-JP")}円</em>` : ""}
        </div>
        ${row.official ? `
          <div class="performance-money ${row.simulatedNet >= 0 ? "plus" : "minus"}">
            <small>7点×${PERFORMANCE_BET_UNIT_YEN}円</small>
            <b>${formatSignedYen(row.simulatedNet)}</b>
            <span>投資 ${formatYen(row.simulatedStake)} / 回収 ${formatYen(row.simulatedReturn)}</span>
          </div>
          <div class="performance-money ${row.recommendedNet >= 0 ? "plus" : "minus"}">
            <small>${decision.buy ? `${decision.label}で買う` : "見送り推奨"}</small>
            <b>${decision.buy ? formatSignedYen(row.recommendedNet) : "0円"}</b>
            <span>${decision.buy ? `投資 ${formatYen(row.recommendedStake)} / 回収 ${formatYen(row.recommendedReturn)}` : "買わない判断として収支対象外"}</span>
          </div>
        ` : ""}
        <div class="performance-picks">
          ${row.prediction.picks.map((pick, index) => `
            <span class="${row.official && pick.ticket.join("-") === row.official.result.join("-") ? "matched" : ""}">
              ${pick.strategyLabel}${pick.strategyIndex + 1} ${renderTicketText(pick.ticket)}
            </span>
          `).join("")}
        </div>
      </article>
    `;
  }).join("");
}

function saveLearningLog(rows) {
  const judgedRows = rows.filter((row) => row.official);
  if (!judgedRows.length) return Promise.resolve({ events: 0 });
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(LEARNING_LOG_KEY) || "{}");
  } catch {
    stored = {};
  }
  const venue = venues[Number(venueSelect.value)].name;
  const serverEvents = [];
  let hasChanges = false;
  const normalizeLearningTicket = (ticket) => Array.isArray(ticket)
    ? ticket.map((value) => Number(value?.boat ?? value)).filter((value) => Number.isInteger(value) && value >= 1 && value <= 6)
    : [];
  const normalizeLearningPicks = (picks) => Array.isArray(picks)
    ? picks.map((pick) => ({
        ...pick,
        ticket: normalizeLearningTicket(pick.ticket)
      }))
    : [];
  judgedRows.forEach((row) => {
    const key = `${dateInput.value}-${venue}-${row.race}`;
    const normalizedPicks = normalizeLearningPicks(row.prediction.picks);
    const predictedLeader = normalizedPicks[0]?.ticket?.[0] || row.prediction.data?.ranking?.[0]?.boat || null;
    const event = {
      key,
      date: dateInput.value,
      venue,
      race: row.race,
      result: row.official.result,
      payout: row.official.payout,
      picks: normalizedPicks,
      predictedLeader,
      weather: row.prediction.data?.weather?.label,
      wind: row.prediction.data?.wind,
      wave: row.prediction.data?.wave,
      phase: row.prediction.data?.phase?.key,
      source: "prediction-screen",
      hitIndex: row.hitIndex,
      exactaHit: row.exactaHit,
      leaderHit: row.leaderHit,
      savedAt: new Date().toISOString()
    };
    if (JSON.stringify(stored[key]) !== JSON.stringify(event)) {
      stored[key] = { ...event };
      hasChanges = true;
    }
    if (!postedLearningEventKeys.has(key)) {
      postedLearningEventKeys.add(key);
      serverEvents.push(event);
    }
  });
  if (hasChanges) {
    localStorage.setItem(LEARNING_LOG_KEY, JSON.stringify(stored));
  }
  return postLearningEvents(serverEvents).then(() => ({ events: serverEvents.length }));
}

function renderDailyPerformance(options = {}) {
  const { renderList = true } = options;
  const totals = getDailyPerformanceTotals();
  const exactRate = totals.judged ? Math.round(totals.exactHits / totals.judged * 100) : 0;
  const exactaRate = totals.judged ? Math.round(totals.exactaHits / totals.judged * 100) : 0;
  const leaderRate = totals.judged ? Math.round(totals.leaderHits / totals.judged * 100) : 0;
  const targetHits = totals.judged ? Math.ceil(totals.judged * .4) : 0;
  const targetGap = Math.max(0, targetHits - totals.exactHits);
  const recoveryRate = totals.simulatedStake ? Math.round(totals.simulatedReturn / totals.simulatedStake * 100) : 0;
  document.querySelector("#dailyPredictedCount").textContent = totals.predicted;
  document.querySelector("#dailyJudgedCount").textContent = totals.judged;
  document.querySelector("#dailyExactHits").textContent = totals.exactHits;
  document.querySelector("#dailyExactRate").textContent = `${exactRate}%`;
  document.querySelector("#dailyTargetGap").textContent = targetGap;
  document.querySelector("#dailyTargetLabel").textContent = totals.judged
    ? exactRate >= 40 ? "達成中" : `あと${targetGap}本`
    : "集計待ち";
  document.querySelector("#dailyExactaHits").textContent = totals.exactaHits;
  document.querySelector("#dailyExactaRate").textContent = `${exactaRate}%`;
  document.querySelector("#dailyLeaderHits").textContent = totals.leaderHits;
  document.querySelector("#dailyLeaderRate").textContent = `${leaderRate}%`;
  document.querySelector("#simulatedTotalSummary").textContent =
    `全体 ${formatSignedYen(totals.simulatedNet)} / 回収率 ${recoveryRate}%`;
  document.querySelector("#simulatedTotalSummary").className = totals.simulatedNet >= 0 ? "plus" : "minus";
  document.querySelector("#strategyProfitGrid").innerHTML = Object.entries(totals.strategy).map(([key, strategy]) => {
    const rate = strategy.stake ? Math.round(strategy.return / strategy.stake * 100) : 0;
    return `
      <article class="${key} ${strategy.net >= 0 ? "plus" : "minus"}">
        <div class="strategy-profit-title">
          <small>${strategy.label}${strategy.count}点</small>
          <span>${strategy.label}だけ買った場合</span>
        </div>
        <strong>${formatSignedYen(strategy.net)}</strong>
        <div class="strategy-profit-metrics">
          <span><small>投資</small><b>${formatYen(strategy.stake)}</b></span>
          <span><small>回収</small><b>${formatYen(strategy.return)}</b></span>
          <span><small>回収率</small><b>${rate}%</b></span>
          <span><small>的中</small><b>${strategy.hits}回</b></span>
        </div>
      </article>
    `;
  }).join("");
  document.querySelector("#dailyPerformanceStatus").textContent = totals.completed > totals.judged
    ? "結果取得中"
    : totals.judged ? "判定済み" : "未判定";
  document.querySelector("#dailyPerformanceNote").textContent =
    `対象は${formatDate(dateInput.value)} ${venues[Number(venueSelect.value)].name}。3連単は本命5点・狙い目1点・穴1点の合計7点で集計します。`;
  document.querySelector("#simulatedProfitNote").textContent =
    `判定済み${totals.judged}レースで、本命だけは5点、狙い目だけ・穴だけは各1点を${PERFORMANCE_BET_UNIT_YEN}円ずつ購入した場合の仮想収支です。払戻は公式3連単の100円あたり払戻で計算しています。`;
  saveLearningLog(totals.rows);
  if (renderList) renderPerformanceRaceList(totals.rows);
}

function schedulePerformanceRender(options = {}) {
  clearTimeout(performanceRenderTimer);
  performanceRenderTimer = setTimeout(() => renderDailyPerformance(options), 120);
}

async function runWithConcurrency(items, limit, worker, afterEach) {
  const queue = [...items];
  const runners = Array.from({ length: Math.min(limit, queue.length) }, async () => {
    while (queue.length) {
      const item = queue.shift();
      await worker(item);
      afterEach?.(item);
    }
  });
  await Promise.all(runners);
}

async function refreshDailyPerformanceResults(requestId) {
  if (performanceRefreshInFlight) {
    renderDailyPerformance({ renderList: false });
    return;
  }
  performanceRefreshInFlight = true;
  const allRaces = Array.from({ length: 12 }, (_, index) => index + 1);
  try {
    renderDailyPerformance({ renderList: false });

    const completedRaces = allRaces
      .filter((race) => isRaceCompleted(race) && !getVerifiedResult(race));
    if (completedRaces.length) {
      await loadOfficialResultsForDay(activeProgramController.signal, completedRaces).catch((error) => {
        if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
        return null;
      });
      if (requestId !== predictionRequestId) return;
      updateRaceButtonStates();
      renderDailyPerformance({ renderList: false });
    }

    const remainingResultRaces = allRaces
      .filter((race) => isRaceCompleted(race) && !getVerifiedResult(race));
    if (remainingResultRaces.length) {
      await runWithConcurrency(
        remainingResultRaces,
        4,
        async (race) => {
          await loadOfficialResultForRace(race, activeProgramController.signal).catch((error) => {
            if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
            return null;
          });
        },
        () => {
          if (requestId === predictionRequestId) schedulePerformanceRender({ renderList: false });
        }
      );
      if (requestId !== predictionRequestId) return;
      updateRaceButtonStates();
      renderDailyPerformance({ renderList: false });
    }

    renderDailyPerformance();
  } finally {
    performanceRefreshInFlight = false;
  }
}

async function warmMissingPerformancePrograms(requestId, allRaces) {
  if (!isPremiumMode || isPastDate()) return;
  const key = getProgramKey();
  const missingProgramRaces = allRaces.filter((race) => {
    const cachedRace = dynamicPrograms[key]?.races.find((item) => item.race === race);
    return !(cachedRace?.detailed || (Array.isArray(cachedRace?.racers) && cachedRace.racers.length === 6));
  });
  if (!missingProgramRaces.length) return;
  await runWithConcurrency(
    missingProgramRaces,
    2,
    async (race) => {
      await loadOfficialProgramForRace(race, activeProgramController.signal, BACKGROUND_PROGRAM_TIMEOUT_MS).catch((error) => {
        if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
        return null;
      });
    },
    () => {
      if (requestId === predictionRequestId) schedulePerformanceRender({ renderList: false });
    }
  );
  if (requestId === predictionRequestId) renderDailyPerformance();
}

function getAdminBatchDate() {
  const params = new URLSearchParams(window.location.search);
  const date = params.get("adminBatch");
  return /^\d{4}-\d{2}-\d{2}$/.test(date || "") ? date : "";
}

function setBatchMessage(message) {
  loadingState.hidden = false;
  unavailableState.hidden = true;
  dashboard.hidden = true;
  predictButton.disabled = true;
  const title = loadingState.querySelector("h2");
  if (title) title.textContent = "全会場の収支を一括集計中";
  document.querySelector("#loadingMessage").textContent = message;
}

async function runAdminBatchSave() {
  const batchDate = getAdminBatchDate();
  if (!batchDate) return false;
  activeProgramController?.abort();
  activeProgramController = new AbortController();
  predictionRequestId += 1;
  isPremiumMode = true;
  localStorage.setItem(PLAN_MODE_KEY, "premium");
  applyPlanMode();
  dateInput.value = batchDate;
  renderRecentDates();
  setBatchMessage("開催場を確認しています...");
  await refreshVenueStatus(batchDate);
  const statuses = venueStatusByDate[batchDate] || {};
  const activeVenueIndexes = venues
    .map((venue, index) => ({ venue, index, status: statuses[String(index + 1).padStart(2, "0")] }))
    .filter((item) => item.status?.available);
  let savedEvents = 0;
  for (let venueIndex = 0; venueIndex < activeVenueIndexes.length; venueIndex += 1) {
    const item = activeVenueIndexes[venueIndex];
    venueSelect.value = String(item.index);
    renderVenueOptions();
    selectedRace = 1;
    updateRaceButtonStates();
    invalidatePerformanceCache();
    const venueLabel = `${venueIndex + 1}/${activeVenueIndexes.length} ${item.venue.name}`;
    setBatchMessage(`${venueLabel} の出走表・結果・展示情報を取得しています...`);
    try {
      await loadOfficialResultsForDay(activeProgramController.signal, allRaces).catch((error) => {
        if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
        return null;
      });
      for (let race = 1; race <= 12; race += 1) {
        setBatchMessage(`${venueLabel} ${race}R を保存中...`);
        await loadOfficialProgramForRace(race, activeProgramController.signal, BACKGROUND_PROGRAM_TIMEOUT_MS).catch((error) => {
          if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
          return null;
        });
        await loadRaceSignals(activeProgramController.signal, race).catch((error) => {
          if (error.name !== "AbortError" && error.name !== "TimeoutError") console.warn(error);
          return null;
        });
      }
      invalidatePerformanceCache();
      const totals = calculateDailyPerformance();
      const result = await saveLearningLog(totals.rows);
      savedEvents += result?.events || 0;
    } catch (error) {
      if (error.name === "AbortError") break;
      console.warn(error);
    }
  }
  setBatchMessage(`保存完了: ${savedEvents}件を同期しました。管理画面へ戻ります...`);
  window.location.href = `/admin.html?date=${encodeURIComponent(batchDate)}`;
  return true;
}

function scheduleDailyPerformanceRefresh(requestId) {
  renderDailyPerformance({ renderList: false });
  schedulePerformanceRender({ renderList: true });
  if (!isPremiumMode) {
    return;
  }
  clearTimeout(performanceRefreshTimer);
  performanceRefreshTimer = setTimeout(() => {
    if (requestId === predictionRequestId) {
      refreshDailyPerformanceResults(requestId);
    }
  }, isPastDate() ? 1200 : 1800);
}

function schedulePostPredictionFetches(data, requestId) {
  refreshOfficialResult(data, requestId).finally(() => {
    if (requestId === predictionRequestId) {
      scheduleDailyPerformanceRefresh(requestId);
    }
  });
  setTimeout(() => {
    if (requestId !== predictionRequestId) return;
    refreshRaceSignals(data, requestId);
  }, 900);
}

async function runPrediction(withLoading = true) {
  if (!dateInput.value) {
    dateInput.focus();
    return;
  }
  const requestId = ++predictionRequestId;
  activeProgramController?.abort();
  activeProgramController = new AbortController();
  document.querySelector("#unavailableState strong").textContent =
    "公式出走表を未取得です";
  document.querySelector("#unavailableState p").textContent =
    "選手や成績を推測で表示せず、公式番組を取得できた開催だけ予測を表示します。";
  const cachedPrediction = getCachedPredictionSnapshot();
  if (withLoading) {
    if (cachedPrediction) {
      try {
        currentData = cachedPrediction;
        unavailableState.hidden = true;
        loadingState.hidden = true;
        dashboard.hidden = false;
        predictButton.disabled = false;
        updateRaceButtonStates();
        renderRace(cachedPrediction);
      } catch (error) {
        console.warn(error);
        try {
          localStorage.removeItem(PREDICTION_CACHE_KEY);
        } catch {
          // Ignore unavailable storage.
        }
        dashboard.hidden = true;
        unavailableState.hidden = true;
        loadingState.hidden = false;
        predictButton.disabled = true;
        document.querySelector("#loadingMessage").textContent =
          "BOAT RACE公式の出走表を取得しています...";
      }
    } else {
      dashboard.hidden = true;
      unavailableState.hidden = true;
      loadingState.hidden = false;
      predictButton.disabled = true;
      document.querySelector("#loadingMessage").textContent =
        "BOAT RACE公式の出走表を取得しています...";
    }
  }
  let programLoadError = null;
  try {
    await loadOfficialProgram(activeProgramController.signal);
  } catch (error) {
    if (error.name !== "AbortError") {
      programLoadError = error;
      console.warn(error);
      document.querySelector("#unavailableState strong").textContent =
        error.name === "TimeoutError"
          ? "公式データ取得がタイムアウトしました"
          : error instanceof TypeError
          ? "取得サーバーに接続できません"
          : "公式出走表の取得に失敗しました";
      document.querySelector("#unavailableState p").textContent =
        error.name === "TimeoutError"
          ? "公式サイトまたは取得サーバーの応答が遅いため、一定時間で打ち切りました。少し待って再実行してください。"
          : error instanceof TypeError
          ? "ローカル取得サーバーが停止している可能性があります。サーバー起動後に画面を再読み込みしてください。"
          : "公式サイトへの接続または取得サーバーを確認し、少し待って再実行してください。";
    }
  }
  if (requestId !== predictionRequestId) return;
  const data = buildRaceData();
  const jcd = String(Number(venueSelect.value) + 1).padStart(2, "0");
  const hd = dateInput.value.replaceAll("-", "");
  document.querySelector("#officialProgramLink").href =
    `https://www.boatrace.jp/owpc/pc/race/raceindex?jcd=${jcd}&hd=${hd}`;
  if (!data) {
    if (!programLoadError) {
      const readiness = getProgramReadinessMessage();
      document.querySelector("#unavailableState strong").textContent = readiness.title;
      document.querySelector("#unavailableState p").textContent = readiness.body;
    }
    currentData = null;
    loadingState.hidden = true;
    dashboard.hidden = true;
    unavailableState.hidden = false;
    predictButton.disabled = false;
    return;
  }
  currentData = data;
  storePredictionSnapshot(data);
  unavailableState.hidden = true;
  updateRaceButtonStates();
  if (!withLoading) {
    renderRace(data);
    dashboard.hidden = false;
    schedulePostPredictionFetches(data, requestId);
    return;
  }

  renderRace(data);
  loadingState.hidden = true;
  dashboard.hidden = false;
  predictButton.disabled = false;
  dashboard.animate(
    [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "translateY(0)" }],
    { duration: 220, easing: "ease-out" }
  );
  schedulePostPredictionFetches(data, requestId);
}

async function refreshOfficialResult(data, requestId) {
  if (!isRaceCompleted(selectedRace)) return;
  selectedResultRefreshInFlight = true;
  renderOfficialResult(data);
  try {
    await loadOfficialResult(activeProgramController.signal);
    if (requestId !== predictionRequestId) return;
    const updatedData = buildRaceData();
    if (updatedData) {
      currentData = updatedData;
      storePredictionSnapshot(updatedData);
      renderRace(updatedData);
      data = updatedData;
    }
    updateRaceButtonStates();
    renderOfficialResult(data);
  } catch (error) {
    if (error.name !== "AbortError") console.warn(error);
  } finally {
    selectedResultRefreshInFlight = false;
    if (requestId === predictionRequestId) {
      renderOfficialResult(currentData || data);
    }
  }
}

async function bootstrap() {
  setupControls();
  applyPlanMode();
  loadLearningWeights();
  const handledBatch = await runAdminBatchSave();
  if (!handledBatch) {
    runPrediction(true);
  }
  refreshWarmupStatus();
  setInterval(refreshWarmupStatus, 60000);
}

bootstrap();
predictButton.addEventListener("click", () => runPrediction(true));
freePlanButton?.addEventListener("click", () => setPlanMode("free"));
premiumPlanButton?.addEventListener("click", () => setPlanMode("premium"));
document.querySelectorAll(".ranking-tab").forEach((button) => {
  button.addEventListener("click", () => {
    rankingMode = button.dataset.ranking;
    document.querySelectorAll(".ranking-tab").forEach((item) => item.classList.toggle("active", item === button));
    if (currentData) renderRaceRanking(currentData);
  });
});
