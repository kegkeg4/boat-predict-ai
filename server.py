#!/usr/bin/env python3
import base64
from html import escape
import json
import hashlib
import os
import re
import signal
import threading
import time
import socket
from itertools import permutations
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


OFFICIAL_BASE = "https://www.boatrace.jp"
USER_AGENT = "Mozilla/5.0 BOAT-PREDICT-AI/1.0"
CACHE_SECONDS = 21600
PAST_RESULT_CACHE_SECONDS = int(os.environ.get("BOAT_PAST_RESULT_CACHE_SECONDS", str(30 * 24 * 60 * 60)))
FETCH_TIMEOUT_SECONDS = float(os.environ.get("BOAT_FETCH_TIMEOUT", "8"))
PROGRAM_INDEX_TIMEOUT_SECONDS = float(os.environ.get("BOAT_PROGRAM_INDEX_TIMEOUT", "14"))
DETAIL_FETCH_TIMEOUT_SECONDS = float(os.environ.get("BOAT_DETAIL_FETCH_TIMEOUT", "3"))
CACHE_FLUSH_INTERVAL_SECONDS = int(os.environ.get("BOAT_CACHE_FLUSH_INTERVAL", "30"))
FETCH_MEMORY_CACHE_MAX_ENTRIES = int(os.environ.get("BOAT_FETCH_MEMORY_CACHE_MAX_ENTRIES", "300"))
FETCH_LOCKS_MAX_ENTRIES = int(os.environ.get("BOAT_FETCH_LOCKS_MAX_ENTRIES", "1000"))
HTML_CACHE_MAX_AGE_SECONDS = int(os.environ.get("BOAT_HTML_CACHE_MAX_AGE_SECONDS", str(14 * 24 * 60 * 60)))
HTML_CACHE_CLEANUP_INTERVAL_SECONDS = int(os.environ.get("BOAT_HTML_CACHE_CLEANUP_INTERVAL", str(6 * 60 * 60)))
HTML_CACHE_MAX_FILES = int(os.environ.get("BOAT_HTML_CACHE_MAX_FILES", "2500"))
LEARNING_MEMORY_CACHE_MAX_BYTES = int(os.environ.get("BOAT_LEARNING_MEMORY_CACHE_MAX_BYTES", str(5 * 1024 * 1024)))
ADMIN_BACKFILL_WORKERS = int(os.environ.get("BOAT_ADMIN_BACKFILL_WORKERS", "2"))
RESULT_FETCH_WORKERS = int(os.environ.get("BOAT_RESULT_FETCH_WORKERS", "2"))
VENUE_FALLBACK_WORKERS = int(os.environ.get("BOAT_VENUE_FALLBACK_WORKERS", "4"))
PROGRAM_CACHE_MAX_ENTRIES = int(os.environ.get("BOAT_PROGRAM_CACHE_MAX_ENTRIES", "1200"))
RESULTS_CACHE_MAX_ENTRIES = int(os.environ.get("BOAT_RESULTS_CACHE_MAX_ENTRIES", "1200"))
SIGNALS_CACHE_MAX_ENTRIES = int(os.environ.get("BOAT_SIGNALS_CACHE_MAX_ENTRIES", "5000"))
WORKER_STATUS_LOG_SECONDS = int(os.environ.get("BOAT_WORKER_STATUS_LOG_SECONDS", "300"))
ADMIN_BACKFILL_RESULT_TIMEOUT = float(os.environ.get("BOAT_ADMIN_RESULT_TIMEOUT", "16"))
ADMIN_BACKFILL_SIGNAL_TIMEOUT = float(os.environ.get("BOAT_ADMIN_SIGNAL_TIMEOUT", "2"))
BACKFILL_RANGE_GAP_SECONDS = float(os.environ.get("BOAT_BACKFILL_RANGE_GAP_SECONDS", "5"))
BACKFILL_RANGE_MAX_DAYS = int(os.environ.get("BOAT_BACKFILL_RANGE_MAX_DAYS", "14"))
BACKFILL_RANGE_MAX_DAYS_BACK = int(os.environ.get("BOAT_BACKFILL_RANGE_MAX_DAYS_BACK", "35"))
BACKGROUND_SYNC_INTERVAL_SECONDS = int(os.environ.get("BOAT_BACKGROUND_SYNC_INTERVAL", "1800"))
PAY_WARM_INTERVAL_SECONDS = int(os.environ.get("BOAT_PAY_WARM_INTERVAL", "45"))
TODAY_RECORD_INTERVAL_SECONDS = int(os.environ.get("BOAT_TODAY_RECORD_INTERVAL", "900"))
RESULT_BOARD_CACHE_SECONDS = int(os.environ.get("BOAT_RESULT_BOARD_CACHE_SECONDS", "20"))
SIGNALS_CACHE_SECONDS = int(os.environ.get("BOAT_SIGNALS_CACHE_SECONDS", "180"))
PROGRAM_UNAVAILABLE_CACHE_SECONDS = int(os.environ.get("BOAT_PROGRAM_UNAVAILABLE_CACHE_SECONDS", "5"))
CACHE_DIR = Path(os.environ.get("BOAT_DATA_DIR", Path(__file__).with_name(".official-cache")))
PROGRAM_CACHE_FILE = CACHE_DIR / "programs.json"
SCHEDULE_CACHE_FILE = CACHE_DIR / "schedules.json"
RESULTS_CACHE_FILE = CACHE_DIR / "results.json"
SIGNALS_CACHE_FILE = CACHE_DIR / "signals.json"
LEARNING_FILE = CACHE_DIR / "learning.json"
BACKFILL_RANGE_FILE = CACHE_DIR / "backfill_range.json"
SCHEDULE_CACHE_VERSION = 2
JST = timezone(timedelta(hours=9))
BOATRACE_JCDS = [f"{number:02d}" for number in range(1, 25)]
VENUE_NAMES = [
    "桐生", "戸田", "江戸川", "平和島", "多摩川", "浜名湖",
    "蒲郡", "常滑", "津", "三国", "びわこ", "住之江",
    "尼崎", "鳴門", "丸亀", "児島", "宮島", "徳山",
    "下関", "若松", "芦屋", "福岡", "唐津", "大村",
]
MANFUNE_YEN = 10000
cache = {}
cache_lock = threading.Lock()
fetch_locks = {}
fetch_lock_access = {}
fetch_locks_guard = threading.Lock()
program_cache_lock = threading.Lock()
venue_status_cache_lock = threading.Lock()
venue_status_cache = {}
results_cache_lock = threading.Lock()
results_cache = {}
signals_cache_lock = threading.Lock()
signals_cache = {}
cache_flush_lock = threading.Lock()
dirty_cache_files = set()
prefetch_lock = threading.Lock()
prefetching_programs = set()
warmup_lock = threading.Lock()
warmup_status = {
    "active": False,
    "date": "",
    "currentJcd": "",
    "completedVenues": 0,
    "totalVenues": len(BOATRACE_JCDS),
    "completedRaces": 0,
    "totalRaces": len(BOATRACE_JCDS) * 12,
    "startedAt": None,
    "finishedAt": None,
}
learning_lock = threading.Lock()
learning_cache_lock = threading.Lock()
learning_store_cache = {"mtime": None, "store": None}
result_board_cache_lock = threading.Lock()
result_board_cache = {}
admin_backfill_lock = threading.Lock()
pay_refresh_lock = threading.Lock()
pay_refreshing_dates = set()
result_enrich_lock = threading.Lock()
result_enriching = set()
worker_activity_lock = threading.Lock()
worker_activity = {}
worker_last_log = {}
admin_backfill_status = {
    "active": False,
    "rangeActive": False,
    "date": None,
    "startedAt": None,
    "finishedAt": None,
    "currentVenue": "",
    "completedVenues": 0,
    "totalVenues": 0,
    "savedEvents": 0,
    "message": "待機中",
    "range": {
        "from": None,
        "to": None,
        "totalDays": 0,
        "completedDays": 0,
        "currentDate": None,
        "savedEventsTotal": 0,
        "message": "待機中",
        "startedAt": None,
        "finishedAt": None,
    },
}
admin_backfill_done = set()
admin_backfill_range_cancel = threading.Event()


def current_rss_mb():
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        match = re.search(r"^VmRSS:\s+(\d+)\s+kB", status, re.MULTILINE)
        if match:
            return round(int(match.group(1)) / 1024, 1)
    except Exception:
        pass
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if value > 10_000_000:
            return round(value / (1024 * 1024), 1)
        return round(value / 1024, 1)
    except Exception:
        return None


def runtime_sizes_snapshot():
    try:
        learning_size = LEARNING_FILE.stat().st_size
    except OSError:
        learning_size = 0
    with cache_lock:
        html_memory_entries = len(cache)
    with fetch_locks_guard:
        fetch_lock_entries = len(fetch_locks)
    with program_cache_lock:
        program_entries = len(program_cache) if "program_cache" in globals() else 0
    with results_cache_lock:
        result_entries = len(results_cache)
    with signals_cache_lock:
        signal_entries = len(signals_cache)
    with worker_activity_lock:
        workers = {key: value for key, value in worker_activity.items() if value}
    return {
        "rssMb": current_rss_mb(),
        "learningMb": round(learning_size / (1024 * 1024), 2),
        "htmlMemory": html_memory_entries,
        "fetchLocks": fetch_lock_entries,
        "programCache": program_entries,
        "resultsCache": result_entries,
        "signalsCache": signal_entries,
        "workers": workers,
    }


def log_runtime_status(label, force=False):
    if os.environ.get("BOAT_RUNTIME_LOG", "1") == "0":
        return
    now = time.time()
    if not force:
        last = worker_last_log.get(label, 0)
        if now - last < WORKER_STATUS_LOG_SECONDS:
            return
    worker_last_log[label] = now
    snapshot = runtime_sizes_snapshot()
    print(
        "[runtime]",
        datetime.now(JST).isoformat(timespec="seconds"),
        label,
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )


def mark_worker_start(name):
    with worker_activity_lock:
        worker_activity[name] = worker_activity.get(name, 0) + 1
    log_runtime_status(f"{name}:start", force=True)


def mark_worker_end(name):
    with worker_activity_lock:
        current = worker_activity.get(name, 0)
        if current <= 1:
            worker_activity.pop(name, None)
        else:
            worker_activity[name] = current - 1
    log_runtime_status(f"{name}:end", force=True)


def read_learning_store():
    try:
        stat = LEARNING_FILE.stat()
        mtime = stat.st_mtime_ns
        size = stat.st_size
    except OSError:
        mtime = None
        size = 0
    cacheable = bool(LEARNING_MEMORY_CACHE_MAX_BYTES and size <= LEARNING_MEMORY_CACHE_MAX_BYTES)
    if cacheable:
        with learning_cache_lock:
            if learning_store_cache["store"] is not None and learning_store_cache["mtime"] == mtime:
                return learning_store_cache["store"]
    try:
        store = json.loads(LEARNING_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        store = {"events": {}, "weights": {}, "updatedAt": None}
    with learning_cache_lock:
        if cacheable:
            learning_store_cache["mtime"] = mtime
            learning_store_cache["store"] = store
        else:
            learning_store_cache["mtime"] = None
            learning_store_cache["store"] = None
    return store


def save_learning_store(store):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = LEARNING_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    temporary.replace(LEARNING_FILE)
    try:
        stat = LEARNING_FILE.stat()
        mtime = stat.st_mtime_ns
        size = stat.st_size
    except OSError:
        mtime = None
        size = 0
    with learning_cache_lock:
        if LEARNING_MEMORY_CACHE_MAX_BYTES and size <= LEARNING_MEMORY_CACHE_MAX_BYTES:
            learning_store_cache["mtime"] = mtime
            learning_store_cache["store"] = store
        else:
            learning_store_cache["mtime"] = None
            learning_store_cache["store"] = None
    with result_board_cache_lock:
        result_board_cache.clear()


def prune_saved_at_mapping(mapping, max_entries):
    if not max_entries or len(mapping) <= max_entries:
        return
    removable = sorted(
        mapping,
        key=lambda key: (mapping.get(key) or {}).get("savedAt", 0),
    )[: len(mapping) - max_entries]
    for key in removable:
        mapping.pop(key, None)


def prune_fetch_locks():
    if not FETCH_LOCKS_MAX_ENTRIES or len(fetch_locks) <= FETCH_LOCKS_MAX_ENTRIES:
        return
    overflow = len(fetch_locks) - FETCH_LOCKS_MAX_ENTRIES
    for key in sorted(fetch_lock_access, key=fetch_lock_access.get):
        lock = fetch_locks.get(key)
        if lock is None or lock.locked():
            continue
        fetch_locks.pop(key, None)
        fetch_lock_access.pop(key, None)
        overflow -= 1
        if overflow <= 0:
            break


def recompute_learning_weights(events):
    venue_stats = {}
    for event in events.values():
        venue = event.get("venue") or ""
        if not venue:
            continue
        stats = venue_stats.setdefault(
            venue,
            {
                "races": 0,
                "hits": 0,
                "leaderHits": 0,
                "exactaHits": 0,
                "innerOverrated": 0,
                "thirdMisses": 0,
                "highPayoutHits": 0,
            },
        )
        stats["races"] += 1
        if event.get("hitIndex", -1) >= 0:
            stats["hits"] += 1
        if event.get("leaderHit"):
            stats["leaderHits"] += 1
        if event.get("exactaHit"):
            stats["exactaHits"] += 1
        result = event.get("result") or []
        predicted_leader = event.get("predictedLeader")
        if predicted_leader == 1 and result and result[0] != 1:
            stats["innerOverrated"] += 1
        if event.get("exactaHit") and event.get("hitIndex", -1) < 0:
            stats["thirdMisses"] += 1
        if event.get("hitIndex", -1) >= 0 and event.get("payout", 0) >= 5000:
            stats["highPayoutHits"] += 1
    weights = {}
    for venue, stats in venue_stats.items():
        races = max(1, stats["races"])
        weights[venue] = {
            "samples": stats["races"],
            "hitRate": round(stats["hits"] / races, 4),
            "leaderHitRate": round(stats["leaderHits"] / races, 4),
            "exactaHitRate": round(stats["exactaHits"] / races, 4),
            "innerPenaltyAdjust": round(min(3, stats["innerOverrated"] / races * 6), 3),
            "thirdCoverageBoost": round(min(3, stats["thirdMisses"] / races * 5), 3),
            "valueBoost": round(min(2, stats["highPayoutHits"] / races * 4), 3),
        }
    return weights


def get_learning():
    with learning_lock:
        store = read_learning_store()
    return {
        "updatedAt": store.get("updatedAt"),
        "weights": store.get("weights", {}),
        "events": len(store.get("events", {})),
    }


def record_learning_events(events):
    if not isinstance(events, list):
        return {"error": "events must be list"}
    with learning_lock:
        store = read_learning_store()
        stored_events = store.setdefault("events", {})
        for event in events:
            if not isinstance(event, dict):
                continue
            key = event.get("key")
            if not key:
                continue
            incoming_source = event.get("source") or (
                "server-backfill" if event.get("phase") == "server-backfill" else "prediction-screen"
            )
            event["source"] = incoming_source
            existing = stored_events.get(key)
            if isinstance(existing, dict):
                existing_source = existing.get("source") or (
                    "server-backfill" if existing.get("phase") == "server-backfill" else "prediction-screen"
                )
                if incoming_source == "server-backfill" and existing_source == "prediction-screen":
                    continue
                if existing_source == "prediction-screen" and incoming_source != "prediction-screen":
                    continue
                if existing_source == incoming_source:
                    existing_saved_at = str(existing.get("savedAt") or "")
                    incoming_saved_at = str(event.get("savedAt") or "")
                    if existing_saved_at and incoming_saved_at and existing_saved_at > incoming_saved_at:
                        continue
            stored_events[key] = event
        store["weights"] = recompute_learning_weights(stored_events)
        store["updatedAt"] = datetime.now(JST).isoformat(timespec="seconds")
        save_learning_store(store)
    return get_learning()


def normalize_ticket(ticket):
    if not isinstance(ticket, list):
        return ""
    parts = []
    for value in ticket:
        if isinstance(value, dict):
            value = value.get("boat")
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            parts.append(str(int(value)))
        elif isinstance(value, str):
            normalized = value.strip()
            if normalized.isdigit():
                parts.append(str(int(normalized)))
    return "-".join(parts)


def normalize_payout_ticket(ticket):
    if isinstance(ticket, list):
        return normalize_ticket(ticket)
    normalized = str(ticket or "").translate(str.maketrans("１２３４５６－＝", "123456-="))
    normalized = normalized.replace("=", "-")
    normalized = re.sub(r"\s+", "", normalized)
    parts = re.findall(r"[1-6]", normalized)
    return "-".join(parts)


def extract_payout_value(payouts, bet_type, result_key):
    if not isinstance(payouts, list) or not result_key:
        return 0
    for payout in payouts:
        if not isinstance(payout, dict) or payout.get("type") != bet_type:
            continue
        if normalize_payout_ticket(payout.get("ticket")) != result_key:
            continue
        try:
            return int(payout.get("payout") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def payout_multiplier(payout):
    try:
        value = float(payout)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return round(value / 100, 1)


def pick_value_score(pick):
    try:
        value = pick.get("valueScore")
        if value is not None:
            return float(value)
        probability = float(pick.get("probability") or 0)
        odds = float(pick.get("estimatedOdds") or pick.get("actualOdds") or 0)
        return probability * odds
    except (TypeError, ValueError):
        return 0


def normalize_bet_decision(event, picks):
    labels = {
        "kenjitsu": "堅実/絞り",
        "shobu": "勝負",
        "ana": "穴狙い",
        "miokuri": "見送り",
    }
    decision = event.get("betDecision") if isinstance(event.get("betDecision"), dict) else {}
    key = decision.get("key")
    if key in labels:
        return {
            "key": key,
            "label": decision.get("label") or labels[key],
            "buy": bool(decision.get("buy")),
            "strategyKeys": decision.get("strategyKeys") if isinstance(decision.get("strategyKeys"), list) else [],
        }
    if not picks:
        return {"key": "miokuri", "label": labels["miokuri"], "buy": False, "strategyKeys": []}
    try:
        water_risk = float(event.get("wind") or 0) + float(event.get("wave") or 0) * 0.7
    except (TypeError, ValueError):
        water_risk = 0
    best = max(picks, key=pick_value_score)
    best_score = pick_value_score(best)
    positive_count = sum(
        1
        for pick in picks
        if pick_value_score(pick) >= 100 and float(pick.get("estimatedOdds") or 0) >= 7
    )
    top_ana = next((pick for pick in picks if pick.get("strategyKey") == "ana"), None)
    top_ana_score = pick_value_score(top_ana) if top_ana else 0
    top_ana_odds = float((top_ana or {}).get("estimatedOdds") or 0)
    if best_score < 72:
        return {"key": "miokuri", "label": labels["miokuri"], "buy": False, "strategyKeys": []}
    if top_ana and top_ana_odds >= 25 and top_ana_score >= 88:
        return {"key": "ana", "label": labels["ana"], "buy": True, "strategyKeys": ["ana"]}
    if best_score >= 115 and positive_count >= 1 and water_risk <= 10:
        return {"key": "shobu", "label": labels["shobu"], "buy": True, "strategyKeys": ["honmei", "nerai"]}
    if best_score >= 96 and water_risk <= 10:
        return {"key": "kenjitsu", "label": labels["kenjitsu"], "buy": True, "strategyKeys": ["honmei"]}
    return {"key": "miokuri", "label": labels["miokuri"], "buy": False, "strategyKeys": []}


def result_board_strategy_templates():
    return {
        "honmei": {"label": "本命", "betType": "3連単"},
        "nerai": {"label": "狙い目", "betType": "3連単"},
        "ana": {"label": "穴", "betType": "3連単"},
        "nirentan": {"label": "2連単", "betType": "2連単"},
    }


def build_result_board(date, jcd):
    venue_index = int(jcd) - 1
    venue = VENUE_NAMES[venue_index] if 0 <= venue_index < len(VENUE_NAMES) else jcd
    cache_key = f"{date}-{jcd}"
    now = time.time()
    with result_board_cache_lock:
        cached = result_board_cache.get(cache_key)
        if cached and now - cached.get("savedAt", 0) < RESULT_BOARD_CACHE_SECONDS:
            return cached["payload"]
    store = read_learning_store()
    events = store.get("events") or {}
    events_by_race = {
        race: events.get(f"{date}-{venue}-{race}")
        for race in range(1, 13)
        if isinstance(events.get(f"{date}-{venue}-{race}"), dict)
    }

    templates = result_board_strategy_templates()
    summary = {
        key: {
            "label": config["label"],
            "betType": config["betType"],
            "points": 0,
            "hitRaces": 0,
            "races": 0,
            "hitRate": 0,
            "roi": 0,
            "available": key != "nirentan",
        }
        for key, config in templates.items()
    }
    internal = {
        key: {"stake": 0, "return": 0}
        for key in templates
    }
    rows = []
    for race in range(1, 13):
        event = events_by_race.get(race)
        row = {
            "race": race,
            "status": "unconfirmed",
            "result": "",
            "hits": [],
        }
        if not event:
            rows.append(row)
            continue
        result_key = normalize_ticket(event.get("result"))
        result2t_key = normalize_ticket((event.get("result") or [])[:2])
        payout3t = int(event.get("payout") or 0)
        payout2t = int(event.get("payout2t") or 0)
        if not payout2t:
            payout2t = extract_payout_value(event.get("payouts"), "2連単", result2t_key)
        if not result_key or not payout3t:
            rows.append(row)
            continue
        row["status"] = "confirmed"
        row["result"] = result_key
        strategy_picks = {
            "honmei": [],
            "nerai": [],
            "ana": [],
            "nirentan": [],
        }
        for pick in (event.get("picks") if isinstance(event.get("picks"), list) else []):
            if not isinstance(pick, dict):
                continue
            strategy_key = pick.get("strategyKey")
            ticket_key = normalize_ticket(pick.get("ticket"))
            if strategy_key in ("honmei", "nerai", "ana") and len(ticket_key.split("-")) == 3:
                strategy_picks[strategy_key].append(ticket_key)
        for pick in (event.get("exactaPicks") if isinstance(event.get("exactaPicks"), list) else []):
            if not isinstance(pick, dict):
                continue
            ticket_key = normalize_ticket(pick.get("ticket"))
            if len(ticket_key.split("-")) == 2:
                strategy_picks["nirentan"].append(ticket_key)

        for key, tickets in strategy_picks.items():
            unique_tickets = list(dict.fromkeys(ticket for ticket in tickets if ticket))
            if not unique_tickets:
                continue
            summary[key]["points"] = max(summary[key]["points"], len(unique_tickets))
            payout = payout2t if key == "nirentan" else payout3t
            result_for_type = result2t_key if key == "nirentan" else result_key
            if key == "nirentan" and not payout:
                continue
            summary[key]["available"] = True
            summary[key]["races"] += 1
            internal[key]["stake"] += len(unique_tickets) * 100
            hit = result_for_type in unique_tickets
            if hit:
                summary[key]["hitRaces"] += 1
                internal[key]["return"] += payout
                multiplier = payout_multiplier(payout)
                if multiplier is not None:
                    tier = "rainbow" if payout >= MANFUNE_YEN else "gold" if multiplier >= 50 else ""
                    row["hits"].append({
                        "group": key,
                        "label": summary[key]["label"],
                        "betType": summary[key]["betType"],
                        "ticket": result_for_type,
                        "prediction": f"{summary[key]['label']} {summary[key]['betType']}",
                        "multiplier": multiplier,
                        "tier": tier,
                        "manfune": payout >= MANFUNE_YEN,
                    })
        rows.append(row)

    for key, item in summary.items():
        races = item["races"]
        stake = internal[key]["stake"]
        returned = internal[key]["return"]
        item["hitRate"] = round(item["hitRaces"] / races * 100) if races else 0
        item["roi"] = round(returned / stake * 100) if stake else 0
        if key == "nirentan" and not races:
            item["available"] = False
    payload = {
        "date": date,
        "jcd": jcd,
        "venue": venue,
        "races": rows,
        "summary": summary,
        "note": "保存済みの予測ログだけで集計しています。当選時は払戻を倍率換算して表示します。",
    }
    with result_board_cache_lock:
        result_board_cache[cache_key] = {
            "savedAt": time.time(),
            "payload": payload,
        }
    return payload


def build_korogashi_month(date, jcd):
    try:
        selected_day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        selected_day = datetime.now(JST).date()
    month = selected_day.strftime("%Y-%m")
    period_start = selected_day.replace(day=1)
    period_end = selected_day
    store = read_learning_store()
    events_by_day = {}
    venue_order = {name: index for index, name in enumerate(VENUE_NAMES)}
    for event in (store.get("events") or {}).values():
        if not isinstance(event, dict):
            continue
        event_date = str(event.get("date") or "")
        if not event_date.startswith(month):
            continue
        try:
            event_day = datetime.strptime(event_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if event_day < period_start or event_day > period_end:
            continue
        venue = event.get("venue") or "不明"
        try:
            race_number = int(event.get("race") or 0)
        except (TypeError, ValueError):
            continue
        if not 1 <= race_number <= 12:
            continue
        exacta_picks = []
        confidence = 0
        for pick in (event.get("exactaPicks") if isinstance(event.get("exactaPicks"), list) else []):
            ticket_key = normalize_ticket(pick.get("ticket") if isinstance(pick, dict) else [])
            if len(ticket_key.split("-")) == 2:
                exacta_picks.append(ticket_key)
                try:
                    confidence += float(pick.get("valueScore") or 0) + float(pick.get("probability") or 0) * 3
                except (TypeError, ValueError):
                    pass
        if not exacta_picks:
            continue
        result = event.get("result") if isinstance(event.get("result"), list) else []
        result2t_key = normalize_ticket(result[:2])
        payout2t = int(event.get("payout2t") or 0)
        if not payout2t:
            payout2t = extract_payout_value(event.get("payouts"), "2連単", result2t_key)
        if not result2t_key or not payout2t:
            continue
        events_by_day.setdefault(event_date, []).append({
            "venue": venue,
            "venueOrder": venue_order.get(venue, 999),
            "race": race_number,
            "confidence": confidence,
            "tickets": list(dict.fromkeys(exacta_picks)),
            "result": result2t_key,
            "payout": payout2t,
            "savedAt": event.get("savedAt") or "",
        })

    daily = []
    total_start = 0
    total_return = 0
    total_bets = 0
    total_hits = 0
    max_balance = 0
    max_streak = 0
    best_day = None
    for day in sorted(events_by_day):
        races = sorted(events_by_day[day], key=lambda item: (-item["confidence"], item["venueOrder"], item["race"], item["savedAt"]))
        balance = 1000
        started = False
        stopped = False
        streak = 0
        max_day_streak = 0
        history = []
        for item in races:
            if balance <= 0:
                stopped = True
                break
            tickets = item["tickets"]
            if not tickets:
                continue
            started = True
            before = balance
            stake_per_point = before / len(tickets)
            hit = item["result"] in tickets
            if hit:
                balance = round(stake_per_point * (item["payout"] / 100))
                streak += 1
                total_hits += 1
            else:
                balance = 0
                streak = 0
                stopped = True
            max_day_streak = max(max_day_streak, streak)
            max_streak = max(max_streak, streak)
            max_balance = max(max_balance, balance)
            total_bets += 1
            history.append({
                "venue": item["venue"],
                "race": item["race"],
                "tickets": tickets,
                "result": item["result"],
                "hit": hit,
                "payout": item["payout"],
                "multiplier": payout_multiplier(item["payout"]),
                "before": round(before),
                "after": round(balance),
            })
            if stopped:
                break
        if not started:
            continue
        total_start += 1000
        total_return += balance
        day_row = {
            "date": day,
            "start": 1000,
            "end": round(balance),
            "net": round(balance - 1000),
            "bets": len(history),
            "hits": sum(1 for item in history if item["hit"]),
            "maxStreak": max_day_streak,
            "stopped": stopped,
            "history": history,
        }
        daily.append(day_row)
        if best_day is None or day_row["end"] > best_day["end"]:
            best_day = day_row

    return {
        "date": date,
        "month": month,
        "periodStart": period_start.strftime("%Y-%m-%d"),
        "periodEnd": period_end.strftime("%Y-%m-%d"),
        "monthlyReset": True,
        "jcd": "",
        "venue": "全会場",
        "daily": daily,
        "summary": {
            "days": len(daily),
            "startTotal": round(total_start),
            "returnTotal": round(total_return),
            "net": round(total_return - total_start),
            "bets": total_bets,
            "hits": total_hits,
            "hitRate": round(total_hits / total_bets * 100) if total_bets else 0,
            "maxBalance": round(max_balance),
            "maxStreak": max_streak,
            "bestDay": best_day,
        },
        "note": "月末で締め、翌月1日に0円へリセットします。各日1,000円スタート。2連単3点へ残高を均等配分し、的中時は払戻を次レースへ全額コロガシ。外れた日は0円で終了します。",
    }


VENUE_SLUGS = [
    "kiryu", "toda", "edogawa", "heiwajima", "tamagawa", "hamanako",
    "gamagori", "tokoname", "tsu", "mikuni", "biwako", "suminoe",
    "amagasaki", "naruto", "marugame", "kojima", "miyajima", "tokuyama",
    "shimonoseki", "wakamatsu", "ashiya", "fukuoka", "karatsu", "omura",
]
VENUE_DESCRIPTIONS = {
    "kiryu": "群馬県、淡水の湖水面のナイター場。標高が高く、冬場はモーターが伸びやすい。イン1着率は全国平均並みだが、季節や気象で配当が荒れやすい。",
    "toda": "埼玉県、淡水の河川水面。1マークの幅が狭く全国屈指の『イン受難』水面で、イン1着率が50%を下回ることもある。センター（3・4コース）のまくりが決まりやすく、本命党には難しい。",
    "edogawa": "東京都、全国で唯一の河川（汽水）水面。風と潮、川の流れで荒れやすい全国屈指の難水面。イン1着率は低め（約46%）で、2コースの差しや高配当が出やすい。",
    "heiwajima": "東京都、海水水面。イン1着率は全国ワースト級で、万舟率・平均配当が高い。5・6コースの連対も見られ、穴狙い傾向が強い。",
    "tamagawa": "東京都、淡水の静水面。難水面の多い関東では比較的インを信頼しやすく買い目を絞りやすい。ただし悪天候や格下のイン戦では荒れることがある。",
    "hamanako": "静岡県、汽水の湖水面。全国最大級の広い水面で乗りやすく、スピード戦やまくり差しが多い。インを優遇する番組が少なくイン1着率は平均以下、強風時は荒れやすい。",
    "gamagori": "愛知県、海水のプール水面で干満の影響が少ないナイター場。1マーク明けのコース幅が全国一広くスピードを保ちやすい。近年はイン勝率が低下傾向で、多彩な決まり手が出やすい。",
    "tokoname": "愛知県、海水水面（水門で水位変動は小さい）。バック側が広くインが有利で、追い風時は特にイン逃げが決まりやすい。一般戦は前づけで枠なりが崩れやすい。",
    "tsu": "三重県のナイター場。風の影響を受けやすく、風向き次第で展開や難度が変わりやすい水面。",
    "mikuni": "福井県、淡水水面。『あらし』と呼ばれる強風が吹くと大きく荒れ、配当が跳ねやすい。風が穏やかな日はインが安定する、風次第の水面。",
    "biwako": "滋賀県、琵琶湖の淡水水面。標高が高く水質が硬めで、比叡おろしなどの風で荒れやすい。イン1着率は低めで難水面寄り。",
    "suminoe": "大阪府、淡水水面。整備された静水で『日本一の競走水面』とも称され、インが安定して堅い決着が出やすい。公営ナイター発祥で売上も全国トップ級。",
    "amagasaki": "兵庫県、淡水のプール水面。建物に囲まれ風の影響が少なく穏やかで、インがやや有利な堅めの水面。",
    "naruto": "徳島県、海水水面。干満差やうねりが1コースの逃げを阻害し、2コースの差しが決まりやすい。季節風の影響も受けやすい。",
    "marugame": "香川県、海水のナイター場。瀬戸内で干満差があり、基本はイン優勢だが、風や潮で展開が変わる。",
    "kojima": "岡山県、海水水面。瀬戸内特有の干満差・潮の動きで水面が変化し、読みづらい展開も出やすい。",
    "miyajima": "広島県、海水水面。干満差が大きく潮流や風の影響を受けやすく、水面状況で狙い目が変わる。",
    "tokuyama": "山口県、海水のナイター場。1マークの幅が狭くインのターンがしやすいため、全国屈指のイン1着率を誇る鉄板水面。",
    "shimonoseki": "山口県、海水のナイター場。イン1着率が高く初心者にも予想しやすい鉄板寄りの水面。",
    "wakamatsu": "福岡県、海水のナイター場。干満差やうねりで荒れることがあり、水面状況で狙いが変わる玄人向けの場。",
    "ashiya": "福岡県、淡水水面。スタートが揃いやすい穏やかな水面で、イン1着率は全国トップクラスの鉄板水面。",
    "fukuoka": "福岡県、那珂川河口の汽水水面。海からのうねりや潮の影響で水面が難しく、玄人向けとされる。",
    "karatsu": "佐賀県、淡水のナイター場。比較的素直な水面だが、冬場の季節風で荒れることがある。",
    "omura": "長崎県、海水水面で日本最古のボートレース場。1コースの1着率が全国一（60%超）で、最も堅い鉄板水面として知られる。スタートが見やすく波乱が少ない。",
}
SLUG_TO_JCD = {
    slug: f"{index + 1:02d}"
    for index, slug in enumerate(VENUE_SLUGS)
}
JCD_TO_SLUG = {
    f"{index + 1:02d}": slug
    for index, slug in enumerate(VENUE_SLUGS)
}
SEO_SITEMAP_CACHE = {"savedAt": 0, "body": ""}


def venue_name_from_jcd(jcd):
    try:
        index = int(jcd) - 1
    except (TypeError, ValueError):
        return str(jcd or "")
    return VENUE_NAMES[index] if 0 <= index < len(VENUE_NAMES) else str(jcd or "")


def seo_public_origin(handler):
    configured = os.environ.get("BOAT_PUBLIC_ORIGIN", "").rstrip("/")
    if configured:
        return configured
    host = handler.headers.get("Host", "localhost:4174")
    scheme = "https" if "onrender.com" in host or os.environ.get("RENDER") else "http"
    return f"{scheme}://{host}"


def seo_escape(value):
    return escape(str(value or ""), quote=True)


def seo_ticket_text(ticket):
    if isinstance(ticket, str):
        return ticket
    if isinstance(ticket, list):
        return "-".join(str(int(value)) for value in ticket if isinstance(value, (int, float)))
    return ""


def seo_latest_events():
    store = read_learning_store()
    latest = {}
    for event in (store.get("events") or {}).values():
        if not isinstance(event, dict):
            continue
        date = event.get("date")
        venue = event.get("venue")
        race = event.get("race")
        if not date or not venue or not race:
            continue
        try:
            race_number = int(race)
        except (TypeError, ValueError):
            continue
        if not 1 <= race_number <= 12:
            continue
        key = (date, venue, race_number)
        current = latest.get(key)
        if not current or str(current.get("savedAt") or "") <= str(event.get("savedAt") or ""):
            latest[key] = event
    return latest


def seo_event_for(date, venue, race):
    return seo_latest_events().get((date, venue, int(race)))


def seo_events_for_day(date, venue):
    events = seo_latest_events()
    return {
        race: event
        for (event_date, event_venue, race), event in events.items()
        if event_date == date and event_venue == venue
    }


def seo_dates_for_venue(venue, limit=30):
    dates = sorted(
        {
            date
            for (date, event_venue, _race), _event in seo_latest_events().items()
            if event_venue == venue
        },
        reverse=True,
    )
    return dates[:limit]


def seo_event_has_content(event):
    if not isinstance(event, dict):
        return False
    return bool(event.get("result") or event.get("picks") or event.get("exactaPicks"))


def seo_prediction_summary(event):
    picks = event.get("picks") if isinstance(event.get("picks"), list) else []
    exacta_picks = event.get("exactaPicks") if isinstance(event.get("exactaPicks"), list) else []
    groups = []
    for key, label in (("honmei", "本命3連単"), ("nerai", "狙い目3連単"), ("ana", "穴3連単")):
        tickets = [
            normalize_ticket(pick.get("ticket"))
            for pick in picks
            if isinstance(pick, dict) and pick.get("strategyKey") == key
        ]
        tickets = [ticket for ticket in tickets if ticket]
        if tickets:
            groups.append((label, tickets))
    exacta_tickets = [
        normalize_ticket(pick.get("ticket"))
        for pick in exacta_picks
        if isinstance(pick, dict)
    ]
    exacta_tickets = [ticket for ticket in exacta_tickets if ticket]
    if exacta_tickets:
        groups.append(("2連単3点", exacta_tickets))
    return groups


def seo_result_text(event):
    result_key = normalize_ticket(event.get("result"))
    if not result_key:
        return "結果待ち"
    multiplier = payout_multiplier(event.get("payout"))
    if multiplier is None:
        return result_key
    return f"{result_key} / ×{multiplier:.1f}"


def seo_page_shell(title, description, canonical, robots, body):
    safe_title = seo_escape(title)
    safe_description = seo_escape(description)
    safe_canonical = seo_escape(canonical)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <meta name="description" content="{safe_description}">
  <meta name="robots" content="{seo_escape(robots)}">
  <link rel="canonical" href="{safe_canonical}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{safe_title}">
  <meta property="og:description" content="{safe_description}">
  <meta property="og:url" content="{safe_canonical}">
  <style>
    body{{margin:0;background:#f4f7fb;color:#13243a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.75}}
    .wrap{{max-width:980px;margin:0 auto;padding:28px 18px 46px}}
    .hero,.card{{background:#fff;border:1px solid #dfe8f2;border-radius:18px;padding:22px;margin:16px 0;box-shadow:0 14px 34px rgba(19,36,58,.06)}}
    .eyebrow{{color:#7f8fa3;font-size:12px;font-weight:900;letter-spacing:.16em;text-transform:uppercase}}
    h1{{font-size:clamp(28px,4vw,44px);line-height:1.18;margin:8px 0 12px;letter-spacing:-.04em}}
    h2{{font-size:22px;margin:0 0 12px}}
    a{{color:#0877f9;text-decoration:none;font-weight:800}}
    .answer{{font-size:18px;font-weight:800;background:#edf6ff;border-radius:14px;padding:16px}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}}
    .item{{border:1px solid #e3ebf3;border-radius:14px;padding:14px;background:#fbfdff}}
    .item small{{display:block;color:#8392a4;font-weight:900;font-size:11px;letter-spacing:.08em}}
    .item b{{display:block;margin-top:5px;font-size:20px}}
    ul{{padding-left:20px}}
    li{{margin:6px 0}}
    footer{{margin-top:26px;color:#6e7f92;font-size:13px}}
  </style>
</head>
<body>
  <main class="wrap">{body}</main>
</body>
</html>"""


def render_seo_race(origin, slug, date, race):
    jcd = SLUG_TO_JCD.get(slug)
    if not jcd or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        return None, 404
    try:
        race_number = int(race)
    except (TypeError, ValueError):
        return None, 404
    if not 1 <= race_number <= 12:
        return None, 404
    venue = venue_name_from_jcd(jcd)
    event = seo_event_for(date, venue, race_number)
    has_content = seo_event_has_content(event)
    robots = "index,follow" if has_content else "noindex,follow"
    canonical = f"{origin}/boatrace/{slug}/{date}/{race_number}"
    title = f"{venue} {race_number}R 予想・結果 {date}｜競艇AI予測"
    if not has_content:
        description = f"{date} {venue}{race_number}Rの競艇AI予測ページです。保存済み予測または確定結果が入り次第、内容を表示します。"
        body = f"""
<section class="hero">
  <p class="eyebrow">BOATRACE AI PREDICTION</p>
  <h1>{seo_escape(venue)} {race_number}R 予想・結果</h1>
  <p class="answer">このページはまだ保存済み予測または確定結果がありません。検索向けには noindex で公開しています。</p>
</section>
{seo_internal_links(slug, date, race_number)}
{seo_footer()}"""
        return seo_page_shell(title, description, canonical, robots, body), 200

    result_text = seo_result_text(event)
    hit_text = "的中判定あり" if event.get("hitIndex", -1) >= 0 or event.get("exactaHit") else "的中なし"
    description = f"{date} {venue}{race_number}Rの競艇AI予測と確定結果。結果は{result_text}、判定は{hit_text}。"
    prediction_groups = seo_prediction_summary(event)
    prediction_html = "".join(
        f"<div class=\"item\"><small>{seo_escape(label)}</small><b>{seo_escape(' / '.join(tickets))}</b></div>"
        for label, tickets in prediction_groups
    ) or "<p>保存済み買い目はありません。</p>"
    result_html = f"""
<div class="grid">
  <div class="item"><small>確定結果</small><b>{seo_escape(result_text)}</b></div>
  <div class="item"><small>的中判定</small><b>{seo_escape(hit_text)}</b></div>
  <div class="item"><small>2連単</small><b>{seo_escape(normalize_ticket((event.get('result') or [])[:2]) or '結果待ち')}</b></div>
</div>"""
    answer = f"{date} {venue}{race_number}Rの競艇AI予測です。確定結果は{result_text}、AI予測の判定は{hit_text}です。"
    body = f"""
<section class="hero">
  <p class="eyebrow">BOATRACE AI PREDICTION</p>
  <h1>{seo_escape(venue)} {race_number}R 予想・結果</h1>
  <p class="answer">{seo_escape(answer)}</p>
</section>
<section class="card">
  <h2>予測買い目</h2>
  <div class="grid">{prediction_html}</div>
</section>
<section class="card">
  <h2>確定結果と予測比較</h2>
  {result_html}
</section>
{seo_internal_links(slug, date, race_number)}
{seo_footer()}"""
    return seo_page_shell(title, description, canonical, robots, body), 200


def render_seo_day(origin, slug, date):
    jcd = SLUG_TO_JCD.get(slug)
    if not jcd or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        return None, 404
    venue = venue_name_from_jcd(jcd)
    events = seo_events_for_day(date, venue)
    has_content = bool(events)
    robots = "index,follow" if has_content else "noindex,follow"
    canonical = f"{origin}/boatrace/{slug}/{date}/"
    title = f"{venue} 予想・結果一覧 {date}｜競艇AI予測"
    description = f"{date} {venue}の競艇AI予測と確定結果一覧。12レースの的中判定、回収率、当選倍率を確認できます。"
    race_links = []
    for race in range(1, 13):
        event = events.get(race)
        result = seo_result_text(event) if event else "保存データなし"
        race_links.append(
            f"<li><a href=\"/boatrace/{slug}/{date}/{race}\">{race}R 予想・結果</a> - {seo_escape(result)}</li>"
        )
    board = build_result_board(date, jcd)
    summary_html = "".join(
        f"<div class=\"item\"><small>{seo_escape(item.get('label'))}</small><b>回収率 {int(item.get('roi') or 0)}%</b></div>"
        for item in (board.get("summary") or {}).values()
    )
    body = f"""
<section class="hero">
  <p class="eyebrow">DAILY BOATRACE AI</p>
  <h1>{seo_escape(venue)} {seo_escape(date)} 予想・結果一覧</h1>
  <p class="answer">{seo_escape(date)}の{seo_escape(venue)}競艇AI予測一覧です。保存済みの予測と確定結果があるレースだけを検索対象にしています。</p>
</section>
<section class="card"><h2>的中率・回収率サマリー</h2><div class="grid">{summary_html}</div></section>
<section class="card"><h2>12レース一覧</h2><ul>{''.join(race_links)}</ul></section>
{seo_internal_links(slug, date, None)}
{seo_footer()}"""
    return seo_page_shell(title, description, canonical, robots, body), 200


SEO_VENUE_STATS_MIN_RACES = 10


def seo_venue_stats(venue):
    events = seo_latest_events()
    lane = {i: 0 for i in range(1, 7)}
    races = 0
    manfune = 0
    for (date, ev_venue, race), event in events.items():
        if ev_venue != venue:
            continue
        result = event.get("result") or []
        try:
            payout = int(event.get("payout") or 0)
        except (TypeError, ValueError):
            payout = 0
        if not result or payout <= 0:
            continue
        try:
            winner = int(result[0])
        except (TypeError, ValueError, IndexError):
            continue
        if not 1 <= winner <= 6:
            continue
        races += 1
        lane[winner] += 1
        if payout >= MANFUNE_YEN:
            manfune += 1
    return {"races": races, "lane": lane, "manfune": manfune}


def render_seo_venue(origin, slug):
    jcd = SLUG_TO_JCD.get(slug)
    if not jcd:
        return None, 404
    venue = venue_name_from_jcd(jcd)
    dates = seo_dates_for_venue(venue)
    robots = "index,follow" if dates else "noindex,follow"
    canonical = f"{origin}/boatrace/{slug}/"
    feature = VENUE_DESCRIPTIONS.get(slug, "")
    title = f"{venue}競艇場の特徴とAI予測｜ボートレース予想・結果検証"
    description = (feature or f"{venue}の競艇AI予測ハブ。") + "直近開催日の予測・確定結果・回収率を保存済みデータから確認できます。"
    date_links = "".join(
        f"<li><a href=\"/boatrace/{slug}/{date}/\">{seo_escape(date)} {seo_escape(venue)} 予想・結果一覧</a></li>"
        for date in dates
    ) or "<li>保存済みデータはまだありません。</li>"
    feature_card = f"""
<section class="card">
  <h2>{seo_escape(venue)}競艇場の特徴</h2>
  <p>{seo_escape(feature)}</p>
</section>""" if feature else ""
    stats = seo_venue_stats(venue)
    stats_card = ""
    if stats["races"] >= SEO_VENUE_STATS_MIN_RACES:
        lane_items = "".join(
            f"<div class=\"item\"><small>{lane}号艇</small><b>{round(stats['lane'][lane] / stats['races'] * 100)}%</b></div>"
            for lane in range(1, 7)
        )
        manfune_rate = round(stats["manfune"] / stats["races"] * 100, 1)
        stats_card = f"""
<section class="card">
  <h2>{seo_escape(venue)}の枠別1着率（当サイト集計・{stats['races']}レース）</h2>
  <p>保存済みの確定結果から集計した{seo_escape(venue)}の枠別1着率です。サンプル{stats['races']}レース、万舟率（払戻1万円以上）は{manfune_rate}%。</p>
  <div class="grid">{lane_items}</div>
</section>"""
    body = f"""
<section class="hero">
  <p class="eyebrow">VENUE HUB</p>
  <h1>{seo_escape(venue)}競艇場 AI予測と特徴</h1>
  <p class="answer">{seo_escape(feature) or seo_escape(venue) + "のボートレース予想と結果検証ページです。"}</p>
</section>
{feature_card}
{stats_card}
<section class="card">
  <h2>{seo_escape(venue)}の直近開催日</h2>
  <ul>{date_links}</ul>
</section>
<section class="card">
  <h2>予測方法</h2>
  <p>出走表、モーター、スタート、展示、気象、会場傾向、過去結果の学習ログをもとにAI予測を表示します。的中を保証するものではなく、検証可能な予測ログとして公開しています。</p>
</section>
{seo_footer()}"""
    return seo_page_shell(title, description, canonical, robots, body), 200


def seo_internal_links(slug, date, race):
    links = [f"<a href=\"/boatrace/{slug}/\">会場ページ</a>"]
    if date:
        links.append(f"<a href=\"/boatrace/{slug}/{date}/\">同日の12レース一覧</a>")
    if race:
        if race > 1:
            links.append(f"<a href=\"/boatrace/{slug}/{date}/{race - 1}\">前のレース</a>")
        if race < 12:
            links.append(f"<a href=\"/boatrace/{slug}/{date}/{race + 1}\">次のレース</a>")
    links.append("<a href=\"/\">インタラクティブ版を見る</a>")
    return f"<nav class=\"card\"><h2>関連リンク</h2><p>{' / '.join(links)}</p></nav>"


def seo_footer():
    return """
<footer>
  <p>BOAT PREDICT AI は競艇・ボートレースの予測と検証を目的とした情報サイトです。予測は的中を保証するものではありません。</p>
  <p>20歳未満の方は舟券を購入できません。投票は余裕資金の範囲で行い、のめり込みにご注意ください。</p>
</footer>"""


def render_seo_page(origin, slug, date=None, race=None):
    if slug not in SLUG_TO_JCD:
        return None, 404
    if date and race:
        return render_seo_race(origin, slug, date, race)
    if date:
        return render_seo_day(origin, slug, date)
    return render_seo_venue(origin, slug)


def build_sitemap_xml(origin, max_days=60):
    now = time.time()
    if SEO_SITEMAP_CACHE["body"] and now - SEO_SITEMAP_CACHE["savedAt"] < 600:
        return SEO_SITEMAP_CACHE["body"]
    events = seo_latest_events()
    rows = []
    day_keys = set()
    venue_slugs = set()
    cutoff = datetime.now(JST).date() - timedelta(days=max_days)
    for (date, venue, race), event in events.items():
        if not seo_event_has_content(event):
            continue
        try:
            if datetime.strptime(date, "%Y-%m-%d").date() < cutoff:
                continue
        except ValueError:
            continue
        if venue not in VENUE_NAMES:
            continue
        jcd = f"{VENUE_NAMES.index(venue) + 1:02d}"
        slug = JCD_TO_SLUG.get(jcd)
        if not slug:
            continue
        lastmod = (event.get("savedAt") or date)[:10]
        rows.append((f"{origin}/boatrace/{slug}/{date}/{race}", lastmod))
        day_keys.add((slug, date, lastmod))
        venue_slugs.add(slug)
    for slug, date, lastmod in sorted(day_keys):
        rows.append((f"{origin}/boatrace/{slug}/{date}/", lastmod))
    for slug in sorted(venue_slugs):
        rows.append((f"{origin}/boatrace/{slug}/", datetime.now(JST).strftime("%Y-%m-%d")))
    body = "\n".join(
        f"  <url><loc>{seo_escape(loc)}</loc><lastmod>{seo_escape(lastmod)}</lastmod></url>"
        for loc, lastmod in sorted(set(rows))
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>
"""
    SEO_SITEMAP_CACHE.update({"savedAt": now, "body": xml})
    return xml


def get_admin_performance(date):
    store = read_learning_store()
    events = [
        event
        for event in store.get("events", {}).values()
        if isinstance(event, dict) and event.get("date") == date
    ]
    venue_order = {name: index for index, name in enumerate(VENUE_NAMES)}
    venue_status = {}
    try:
        venue_status = load_venues_status(date).get("venues", {})
    except Exception:
        venue_status = {}
    strategies = {
        "honmei": {"label": "本命"},
        "nerai": {"label": "狙い目"},
        "ana": {"label": "穴"},
    }
    rows = {}
    totals = {
        "honmei": {"stake": 0, "return": 0, "net": 0, "hits": 0},
        "nerai": {"stake": 0, "return": 0, "net": 0, "hits": 0},
        "ana": {"stake": 0, "return": 0, "net": 0, "hits": 0},
        "betModes": {
            "recommended": {"label": "推奨だけ", "stake": 0, "return": 0, "net": 0, "hits": 0, "races": 0},
            "kenjitsu": {"label": "堅実/絞り", "stake": 0, "return": 0, "net": 0, "hits": 0, "races": 0},
            "shobu": {"label": "勝負", "stake": 0, "return": 0, "net": 0, "hits": 0, "races": 0},
            "ana": {"label": "穴狙い", "stake": 0, "return": 0, "net": 0, "hits": 0, "races": 0},
            "miokuri": {"label": "見送り", "stake": 0, "return": 0, "net": 0, "hits": 0, "races": 0},
        },
        "net": 0,
        "races": 0,
    }
    for event in events:
        venue = event.get("venue") or "不明"
        row = rows.setdefault(
            venue,
            {
                "venue": venue,
                "races": 0,
                "honmei": {"stake": 0, "return": 0, "net": 0, "hits": 0},
                "nerai": {"stake": 0, "return": 0, "net": 0, "hits": 0},
                "ana": {"stake": 0, "return": 0, "net": 0, "hits": 0},
                "recommended": {"stake": 0, "return": 0, "net": 0, "hits": 0, "races": 0},
                "sources": {},
                "net": 0,
            },
        )
        row["races"] += 1
        totals["races"] += 1
        source = event.get("source") or ("server-backfill" if event.get("phase") == "server-backfill" else "prediction-screen")
        row["sources"][source] = row["sources"].get(source, 0) + 1
        result_key = normalize_ticket(event.get("result"))
        payout = int(event.get("payout") or 0)
        picks = event.get("picks") if isinstance(event.get("picks"), list) else []
        for strategy_key in strategies:
            strategy_picks = [
                pick for pick in picks
                if isinstance(pick, dict) and pick.get("strategyKey") == strategy_key
            ]
            stake = len(strategy_picks) * 100
            hit = any(normalize_ticket(pick.get("ticket")) == result_key for pick in strategy_picks)
            returned = payout if hit else 0
            net = returned - stake
            row[strategy_key]["stake"] += stake
            row[strategy_key]["return"] += returned
            row[strategy_key]["net"] += net
            row[strategy_key]["hits"] += 1 if hit else 0
            totals[strategy_key]["stake"] += stake
            totals[strategy_key]["return"] += returned
            totals[strategy_key]["net"] += net
            totals[strategy_key]["hits"] += 1 if hit else 0
            row["net"] += net
            totals["net"] += net
        decision = normalize_bet_decision(event, picks)
        selected_keys = set(decision.get("strategyKeys") or [])
        recommended_picks = [
            pick for pick in picks
            if isinstance(pick, dict) and pick.get("strategyKey") in selected_keys
        ]
        recommended_stake = len(recommended_picks) * 100
        recommended_hit = any(normalize_ticket(pick.get("ticket")) == result_key for pick in recommended_picks)
        recommended_return = payout if recommended_hit else 0
        recommended_net = recommended_return - recommended_stake
        if decision.get("buy") and recommended_stake > 0:
            for mode_key in ("recommended", decision.get("key")):
                mode = totals["betModes"].get(mode_key)
                if not mode:
                    continue
                mode["races"] += 1
                mode["stake"] += recommended_stake
                mode["return"] += recommended_return
                mode["net"] += recommended_net
                mode["hits"] += 1 if recommended_hit else 0
            row["recommended"]["races"] += 1
            row["recommended"]["stake"] += recommended_stake
            row["recommended"]["return"] += recommended_return
            row["recommended"]["net"] += recommended_net
            row["recommended"]["hits"] += 1 if recommended_hit else 0
        else:
            totals["betModes"]["miokuri"]["races"] += 1
    expected_rows = []
    saved_by_venue = {
        venue: set(
            int(event.get("race"))
            for event in events
            if event.get("venue") == venue and str(event.get("race", "")).isdigit()
        )
        for venue in set(event.get("venue") or "不明" for event in events)
    }
    for jcd, status in venue_status.items():
        if not status.get("available"):
            continue
        index = int(jcd) - 1
        venue = VENUE_NAMES[index] if 0 <= index < len(VENUE_NAMES) else jcd
        expected = int(status.get("races") or 0)
        saved = len(saved_by_venue.get(venue, set()))
        missing = max(0, expected - saved)
        expected_rows.append({
            "venue": venue,
            "jcd": jcd,
            "expected": expected,
            "saved": saved,
            "missing": missing,
        })
    expected_races = sum(row["expected"] for row in expected_rows)
    saved_races = sum(row["saved"] for row in expected_rows)
    return {
        "date": date,
        "races": totals["races"],
        "rows": sorted(rows.values(), key=lambda row: venue_order.get(row["venue"], 999)),
        "totals": totals,
        "coverage": {
            "expectedRaces": expected_races,
            "savedRaces": saved_races,
            "missingRaces": max(0, expected_races - saved_races),
            "venues": sorted(expected_rows, key=lambda row: venue_order.get(row["venue"], 999)),
            "missingVenues": [
                row for row in sorted(expected_rows, key=lambda item: venue_order.get(item["venue"], 999))
                if row["missing"] > 0
            ],
        },
    }


def update_admin_backfill_status(**updates):
    with admin_backfill_lock:
        admin_backfill_status.update(updates)


def get_admin_backfill_status():
    with admin_backfill_lock:
        return dict(admin_backfill_status)


def existing_learning_keys():
    store = read_learning_store()
    return set((store.get("events") or {}).keys())


def server_boat_score(racer, signals):
    boat = int(racer.get("boat") or 0)
    grade_bonus = {"A1": 9, "A2": 5, "B1": 0, "B2": -3}.get(racer.get("grade"), 0)
    score = (
        float(racer.get("national") or 0) * 9
        + float(racer.get("local") or 0) * 3
        + float(racer.get("motor") or 0) * 1.4
        + grade_bonus
        - float(racer.get("start") or 0.18) * 22
    )
    if boat == 1:
        score += 11
    elif boat == 2:
        score += 5
    elif boat == 3:
        score += 2
    elif boat >= 5:
        score -= 2
    expect_scores = (signals.get("expect") or {}).get("scores") or {}
    score += float(expect_scores.get(boat, 0)) * 0.35
    beforeinfo = (signals.get("beforeinfo") or {}).get("racers") or {}
    exhibitions = [
        float(item.get("exhibition"))
        for item in beforeinfo.values()
        if item.get("exhibition") is not None
    ]
    exhibition = beforeinfo.get(boat, {}).get("exhibition")
    if exhibitions and exhibition is not None:
        fastest = min(exhibitions)
        score += max(-6, min(6, (fastest - float(exhibition)) * 18))
    return score


def build_server_prediction_picks(racers, signals):
    def clamp_value(value, lower, upper):
        return max(lower, min(upper, value))

    scored = [
        {**racer, "score": server_boat_score(racer, signals)}
        for racer in racers
        if racer.get("boat")
    ]
    if len(scored) != 6:
        return []
    by_boat = {int(racer["boat"]): racer for racer in scored}
    odds = (signals.get("odds") or {}).get("odds") or {}
    tickets = []
    for ticket in permutations(range(1, 7), 3):
        first, second, third = ticket
        base_score = (
            by_boat[first]["score"] * 0.58
            + by_boat[second]["score"] * 0.27
            + by_boat[third]["score"] * 0.15
        )
        odds_key = "-".join(str(value) for value in ticket)
        actual_odds = float(odds.get(odds_key) or 0)
        value_score = base_score + min(actual_odds, 120) * 0.08
        tickets.append({
            "ticket": list(ticket),
            "baseScore": base_score,
            "valueScore": value_score,
            "actualOdds": actual_odds or None,
        })
    base_values = [item["baseScore"] for item in tickets]
    min_base = min(base_values)
    max_base = max(base_values)
    base_spread = max(1, max_base - min_base)
    boat_scores = sorted((racer["score"] for racer in scored), reverse=True)
    leader_gap = boat_scores[0] - boat_scores[1] if len(boat_scores) >= 2 else 0
    confidence_bonus = clamp_value((leader_gap - 1.5) / 8, 0, 1) * 18
    for item in tickets:
        strength = (item["baseScore"] - min_base) / base_spread
        odds = item["actualOdds"] or 0
        odds_bonus = clamp_value((odds - 7) * 0.22, 0, 22) if odds else 0
        item["adminValueScore"] = round(74 + strength * 18 + confidence_bonus + odds_bonus, 1)
    solid = sorted(tickets, key=lambda item: (-item["baseScore"], item["ticket"]))[:5]
    solid_keys = {tuple(item["ticket"]) for item in solid}
    value_candidates = [item for item in tickets if tuple(item["ticket"]) not in solid_keys]
    nerai = sorted(value_candidates, key=lambda item: (-item["valueScore"], item["ticket"]))[:3]
    used_keys = solid_keys | {tuple(item["ticket"]) for item in nerai}
    ana_primary = sorted(
        [
            item for item in tickets
            if tuple(item["ticket"]) not in used_keys
            and (item["actualOdds"] or 0) >= 30
        ],
        key=lambda item: (-(item["actualOdds"] or 0), -item["valueScore"], item["ticket"]),
    )
    ana = ana_primary[:3]
    if len(ana) < 3:
        ana_used = used_keys | {tuple(item["ticket"]) for item in ana}
        ana_filler = sorted(
            [item for item in tickets if tuple(item["ticket"]) not in ana_used],
            key=lambda item: (-(item["actualOdds"] or 0), -item["valueScore"], item["ticket"]),
        )
        ana = ana + ana_filler[: 3 - len(ana)]
    groups = [
        ("honmei", "本命", solid),
        ("nerai", "狙い目", nerai),
        ("ana", "穴", ana),
    ]
    picks = []
    for strategy_key, strategy_label, group in groups:
        for index, item in enumerate(group):
            picks.append({
                "ticket": item["ticket"],
                "probability": round(max(3, min(60, item["baseScore"] / 2)), 1),
                "estimatedOdds": item["actualOdds"] or None,
                "actualOdds": item["actualOdds"] or None,
                "oddsSource": "official" if item["actualOdds"] else "missing",
                "marketProbability": round(1 / item["actualOdds"], 6) if item["actualOdds"] else None,
                "valueScore": item["adminValueScore"],
                "strategyKey": strategy_key,
                "strategyLabel": strategy_label,
                "strategyIndex": index,
            })
    return picks


def build_server_exacta_picks(trifecta_picks, racers):
    picks = []
    seen = set()
    for pick in trifecta_picks:
        ticket = pick.get("ticket") if isinstance(pick, dict) else []
        if not isinstance(ticket, list) or len(ticket) < 2:
            continue
        exacta = [int(ticket[0]), int(ticket[1])]
        key = tuple(exacta)
        if key in seen:
            continue
        seen.add(key)
        picks.append({
            "ticket": exacta,
            "probability": round(min(70, max(1, float(pick.get("probability") or 0) * 1.8)), 1),
            "estimatedOdds": None,
            "actualOdds": None,
            "valueScore": round(float(pick.get("valueScore") or 0) * 0.92, 1),
            "strategyKey": "exacta",
            "strategyLabel": "2連単",
            "strategyIndex": len(picks),
        })
        if len(picks) >= 3:
            break
    if len(picks) >= 3:
        return picks
    ordered = sorted(
        [racer for racer in racers if racer.get("boat")],
        key=lambda racer: (-(float(racer.get("national") or 0) + float(racer.get("local") or 0)), int(racer.get("boat") or 9)),
    )
    for first in ordered:
        for second in ordered:
            if first.get("boat") == second.get("boat"):
                continue
            exacta = [int(first["boat"]), int(second["boat"])]
            key = tuple(exacta)
            if key in seen:
                continue
            seen.add(key)
            picks.append({
                "ticket": exacta,
                "probability": 0,
                "estimatedOdds": None,
                "actualOdds": None,
                "valueScore": 0,
                "strategyKey": "exacta",
                "strategyLabel": "2連単",
                "strategyIndex": len(picks),
            })
            if len(picks) >= 3:
                return picks
    return picks


def build_admin_backfill_event(
    date,
    jcd,
    race,
    result_timeout=ADMIN_BACKFILL_RESULT_TIMEOUT,
    signal_timeout=ADMIN_BACKFILL_SIGNAL_TIMEOUT,
):
    program = load_program(date, jcd, race, should_prefetch=False)
    race_info = next((item for item in program.get("races", []) if item.get("race") == race), None)
    if not race_info:
        return None
    racers = race_info.get("racers") or []
    if len(racers) != 6:
        return None
    racers = [
        {
            "boat": index + 1,
            "registration": racer.get("registration"),
            "name": racer.get("name"),
            "grade": racer.get("grade", ""),
            "start": racer.get("start"),
            "national": racer.get("national"),
            "local": racer.get("local"),
            "motor": racer.get("motor"),
        }
        for index, racer in enumerate(racers)
    ]
    result_payload = load_result(date, jcd, race, timeout=result_timeout, include_weather=True)
    if not result_payload.get("available"):
        return None
    signals = load_signals(date, jcd, race, timeout=signal_timeout)
    odds3t = (signals.get("odds") or {}).get("odds") or {}
    beforeinfo_racers = (signals.get("beforeinfo") or {}).get("racers") or {}
    for racer in racers:
        beforeinfo = beforeinfo_racers.get(racer["boat"], {})
        if beforeinfo.get("exhibition") is not None:
            racer["exhibition"] = beforeinfo.get("exhibition")
    picks = build_server_prediction_picks(racers, signals)
    if not picks:
        return None
    exacta_picks = build_server_exacta_picks(picks, racers)
    venue = VENUE_NAMES[int(jcd) - 1]
    result = result_payload.get("result") or {}
    result_key = normalize_ticket(result.get("result"))
    result2t_key = normalize_ticket((result.get("result") or [])[:2])
    payout2t = extract_payout_value(result_payload.get("payouts"), "2連単", result2t_key)
    hit_index = next(
        (index for index, pick in enumerate(picks) if normalize_ticket(pick.get("ticket")) == result_key),
        -1,
    )
    exacta_hit = any(
        normalize_ticket(pick.get("ticket")) == result2t_key
        for pick in exacta_picks
    )
    leader_hit = any(
        pick.get("ticket") and pick["ticket"][0] == result["result"][0]
        for pick in picks
    )
    weather = choose_weather(
        (signals.get("beforeinfo") or {}).get("weather"),
        result_payload.get("weather"),
    )
    bet_decision = normalize_bet_decision({
        "wind": weather.get("windSpeed"),
        "wave": weather.get("waveHeight"),
    }, picks)
    return {
        "key": f"{date}-{venue}-{race}",
        "date": date,
        "venue": venue,
        "race": race,
        "result": result["result"],
        "payout": result["payout"],
        "payout2t": payout2t,
        "payouts": result_payload.get("payouts") or [],
        "picks": picks,
        "exactaPicks": exacta_picks,
        "racers": racers,
        "odds3t": odds3t,
        "betDecision": bet_decision,
        "predictedLeader": picks[0]["ticket"][0] if picks else None,
        "weather": weather.get("weather"),
        "wind": weather.get("windSpeed"),
        "wave": weather.get("waveHeight"),
        "phase": "server-backfill",
        "source": "server-backfill",
        "hitIndex": hit_index,
        "exactaHit": exacta_hit,
        "leaderHit": leader_hit,
        "savedAt": datetime.now(JST).isoformat(timespec="seconds"),
    }


def run_admin_backfill(date, force=False):
    mark_worker_start("admin_backfill")
    update_admin_backfill_status(
        active=True,
        date=date,
        startedAt=datetime.now(JST).isoformat(timespec="seconds"),
        finishedAt=None,
        currentVenue="",
        completedVenues=0,
        totalVenues=0,
        savedEvents=0,
        message="開催場を確認中",
    )
    saved_events = []
    try:
        venues_payload = load_venues_status(date)
        active_jcds = [
            jcd for jcd, status in (venues_payload.get("venues") or {}).items()
            if status.get("available")
        ]
        active_jcds.sort()
        update_admin_backfill_status(totalVenues=len(active_jcds))
        existing_keys = existing_learning_keys()
        for index, jcd in enumerate(active_jcds):
            venue = VENUE_NAMES[int(jcd) - 1]
            update_admin_backfill_status(
                currentVenue=venue,
                completedVenues=index,
                message=f"{venue}を集計中",
            )
            races = int((venues_payload.get("venues") or {}).get(jcd, {}).get("races") or 12)
            race_numbers = [
                race for race in range(1, min(12, races) + 1)
                if force or f"{date}-{venue}-{race}" not in existing_keys
            ]
            venue_events = []
            if not race_numbers:
                update_admin_backfill_status(completedVenues=index + 1)
                continue
            update_admin_backfill_status(
                currentVenue=f"{venue} 結果先読み",
                message=f"{venue}の確定結果をまとめて取得中",
            )
            try:
                load_results(
                    date,
                    jcd,
                    race_numbers,
                    max_workers=RESULT_FETCH_WORKERS,
                    timeout=ADMIN_BACKFILL_RESULT_TIMEOUT,
                )
            except Exception:
                pass
            workers = max(1, min(ADMIN_BACKFILL_WORKERS, len(race_numbers)))
            log_runtime_status(f"admin_backfill:{venue}:workers={workers}:races={len(race_numbers)}", force=True)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(build_admin_backfill_event, date, jcd, race): race
                    for race in race_numbers
                }
                for completed_races, future in enumerate(as_completed(futures), start=1):
                    try:
                        event = future.result()
                        if event:
                            venue_events.append(event)
                    except Exception:
                        pass
                    update_admin_backfill_status(
                        currentVenue=f"{venue} {completed_races}/{len(race_numbers)}R",
                        message=f"{venue}を集計中",
                    )
            if venue_events:
                record_learning_events(venue_events)
                saved_events.extend(venue_events)
                existing_keys.update(event["key"] for event in venue_events if event.get("key"))
                update_admin_backfill_status(savedEvents=len(saved_events))
            update_admin_backfill_status(completedVenues=index + 1)
        admin_backfill_done.add(date)
        update_admin_backfill_status(
            active=False,
            finishedAt=datetime.now(JST).isoformat(timespec="seconds"),
            currentVenue="",
            savedEvents=len(saved_events),
            message=f"{len(saved_events)}件を保存しました",
        )
    except Exception as error:
        update_admin_backfill_status(
            active=False,
            finishedAt=datetime.now(JST).isoformat(timespec="seconds"),
            message=f"集計エラー: {error}",
        )
    finally:
        mark_worker_end("admin_backfill")


def schedule_admin_backfill(date, force=False):
    with admin_backfill_lock:
        if admin_backfill_status.get("active") or admin_backfill_status.get("rangeActive"):
            return dict(admin_backfill_status)
        if not force and date in admin_backfill_done:
            return dict(admin_backfill_status)
        admin_backfill_status.update({
            "active": True,
            "date": date,
            "message": "集計開始待ち",
            "startedAt": datetime.now(JST).isoformat(timespec="seconds"),
            "finishedAt": None,
        })
    thread = threading.Thread(target=run_admin_backfill, args=(date, force), daemon=True)
    thread.start()
    return get_admin_backfill_status()


def backfill_range_state_path():
    return BACKFILL_RANGE_FILE


def save_backfill_range_state(state):
    write_json_atomic(backfill_range_state_path(), state)


def load_backfill_range_state():
    try:
        return json.loads(backfill_range_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def clear_backfill_range_state(reset_status=False):
    try:
        backfill_range_state_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass
    if reset_status:
        with admin_backfill_lock:
            admin_backfill_status["rangeActive"] = False
            admin_backfill_status["range"] = {
                "from": None,
                "to": None,
                "totalDays": 0,
                "completedDays": 0,
                "currentDate": None,
                "savedEventsTotal": 0,
                "message": "待機中",
                "startedAt": None,
                "finishedAt": datetime.now(JST).isoformat(timespec="seconds"),
            }


def daterange_list(from_date, to_date):
    start = datetime.strptime(from_date, "%Y-%m-%d").date()
    end = datetime.strptime(to_date, "%Y-%m-%d").date()
    days = []
    current = start
    while current <= end:
        days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def validate_backfill_range(from_date, to_date):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", from_date or ""):
        return False, "開始日の形式が不正です"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", to_date or ""):
        return False, "終了日の形式が不正です"
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date()
        end = datetime.strptime(to_date, "%Y-%m-%d").date()
    except ValueError:
        return False, "日付が不正です"
    today = datetime.now(JST).date()
    if start > end:
        return False, "開始日は終了日以前にしてください"
    if end > today:
        return False, "終了日は今日以前にしてください"
    if (end - start).days + 1 > BACKFILL_RANGE_MAX_DAYS:
        return False, f"1回の範囲は最大{BACKFILL_RANGE_MAX_DAYS}日までです"
    if (today - start).days > BACKFILL_RANGE_MAX_DAYS_BACK:
        return False, f"開始日は直近{BACKFILL_RANGE_MAX_DAYS_BACK}日以内にしてください"
    return True, ""


def update_backfill_range_status(**updates):
    with admin_backfill_lock:
        current = dict(admin_backfill_status.get("range") or {})
        current.update(updates)
        admin_backfill_status["range"] = current


def run_backfill_range_worker(pending, force=True, state=None):
    pending = list(pending or [])
    state = dict(state or {})
    total_days = int(state.get("totalDays") or len(pending))
    completed_days = total_days - len(pending)
    saved_total = int(state.get("savedEventsTotal") or 0)
    started_at = state.get("startedAt") or datetime.now(JST).isoformat(timespec="seconds")
    with admin_backfill_lock:
        admin_backfill_status["rangeActive"] = True
        admin_backfill_status["range"] = {
            "from": state.get("from") or (pending[0] if pending else None),
            "to": state.get("to") or (pending[-1] if pending else None),
            "totalDays": total_days,
            "completedDays": completed_days,
            "currentDate": pending[0] if pending else None,
            "savedEventsTotal": saved_total,
            "message": "連続集計を開始します",
            "startedAt": started_at,
            "finishedAt": None,
        }
    admin_backfill_range_cancel.clear()
    while pending:
        target_date = pending[0]
        if admin_backfill_range_cancel.is_set():
            update_backfill_range_status(
                currentDate=target_date,
                message="連続集計を停止しました",
                finishedAt=datetime.now(JST).isoformat(timespec="seconds"),
            )
            save_backfill_range_state({
                **state,
                "pending": pending,
                "force": force,
                "savedEventsTotal": saved_total,
                "startedAt": started_at,
            })
            with admin_backfill_lock:
                admin_backfill_status["rangeActive"] = False
            return
        update_backfill_range_status(currentDate=target_date, message=f"{target_date}を集計中")
        try:
            run_admin_backfill(target_date, force=force)
            with admin_backfill_lock:
                saved_today = int(admin_backfill_status.get("savedEvents") or 0)
            saved_total += saved_today
            pending.pop(0)
            completed_days += 1
            save_backfill_range_state({
                **state,
                "pending": pending,
                "force": force,
                "savedEventsTotal": saved_total,
                "startedAt": started_at,
            })
            update_backfill_range_status(
                completedDays=completed_days,
                currentDate=pending[0] if pending else target_date,
                savedEventsTotal=saved_total,
                message=f"{target_date} 完了 / 保存 {saved_today}件",
            )
        except Exception as error:
            pending.pop(0)
            completed_days += 1
            save_backfill_range_state({
                **state,
                "pending": pending,
                "force": force,
                "savedEventsTotal": saved_total,
                "startedAt": started_at,
                "lastError": f"{target_date}: {error}",
            })
            update_backfill_range_status(
                completedDays=completed_days,
                currentDate=pending[0] if pending else target_date,
                message=f"{target_date}でエラー: {error}",
            )
        if pending:
            time.sleep(max(0, BACKFILL_RANGE_GAP_SECONDS))
    clear_backfill_range_state()
    with admin_backfill_lock:
        range_state = dict(admin_backfill_status.get("range") or {})
        range_state.update({
            "completedDays": total_days,
            "currentDate": None,
            "savedEventsTotal": saved_total,
            "message": f"連続集計完了 / 保存 {saved_total}件",
            "finishedAt": datetime.now(JST).isoformat(timespec="seconds"),
        })
        admin_backfill_status["range"] = range_state
        admin_backfill_status["rangeActive"] = False


def schedule_backfill_range(from_date, to_date, force=True):
    ok, message = validate_backfill_range(from_date, to_date)
    if not ok:
        return False, {"error": message}
    pending = daterange_list(from_date, to_date)
    if not force:
        pending = [date for date in pending if date not in admin_backfill_done]
    state = {
        "from": from_date,
        "to": to_date,
        "force": force,
        "pending": pending,
        "startedAt": datetime.now(JST).isoformat(timespec="seconds"),
        "totalDays": len(pending),
        "savedEventsTotal": 0,
    }
    with admin_backfill_lock:
        if admin_backfill_status.get("active") or admin_backfill_status.get("rangeActive"):
            return True, dict(admin_backfill_status)
        admin_backfill_status["rangeActive"] = True
        admin_backfill_status["range"] = {
            "from": from_date,
            "to": to_date,
            "totalDays": len(pending),
            "completedDays": 0,
            "currentDate": pending[0] if pending else None,
            "savedEventsTotal": 0,
            "message": "連続集計開始待ち",
            "startedAt": state["startedAt"],
            "finishedAt": None,
        }
    if not pending:
        clear_backfill_range_state(reset_status=True)
        return True, get_admin_backfill_status()
    save_backfill_range_state(state)
    thread = threading.Thread(target=run_backfill_range_worker, args=(pending, force, state), daemon=True)
    thread.start()
    return True, get_admin_backfill_status()


def cancel_backfill_range():
    admin_backfill_range_cancel.set()
    update_backfill_range_status(message="停止要求を受け付けました。実行中の日付が終わったら停止します。")
    return get_admin_backfill_status()


def resume_backfill_range_on_startup():
    state = load_backfill_range_state()
    if not state or not state.get("pending"):
        return
    thread = threading.Thread(
        target=run_backfill_range_worker,
        args=(state.get("pending", []), bool(state.get("force", True)), state),
        daemon=True,
    )
    thread.start()


def record_today_completed_once():
    """Record only today's completed races that are not yet in the learning log."""
    date = current_jst_date()
    with admin_backfill_lock:
        if admin_backfill_status.get("active") or admin_backfill_status.get("rangeActive"):
            return 0
    try:
        venues_payload = load_venues_status(date)
    except Exception:
        return 0
    active_jcds = sorted(
        jcd
        for jcd, status in (venues_payload.get("venues") or {}).items()
        if status.get("available")
    )
    if not active_jcds:
        return 0
    mark_worker_start("today_record")
    existing_keys = existing_learning_keys()
    saved = 0
    try:
        for jcd in active_jcds:
            with admin_backfill_lock:
                if admin_backfill_status.get("active") or admin_backfill_status.get("rangeActive"):
                    break
            try:
                venue = VENUE_NAMES[int(jcd) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            try:
                program = load_program(date, jcd, 1, should_prefetch=False)
            except Exception:
                continue
            target_races = []
            for race_info in program.get("races", []):
                race = race_info.get("race")
                if not race:
                    continue
                if not is_server_race_completed(date, race_info.get("cutoff")):
                    continue
                if f"{date}-{venue}-{race}" in existing_keys:
                    continue
                target_races.append(race)
            if not target_races:
                continue
            log_runtime_status(f"today_record:{venue}:races={len(target_races)}", force=True)
            venue_events = []
            workers = max(1, min(ADMIN_BACKFILL_WORKERS, len(target_races)))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(build_admin_backfill_event, date, jcd, race): race
                    for race in target_races
                }
                for future in as_completed(futures):
                    try:
                        event = future.result()
                    except Exception:
                        event = None
                    if event:
                        venue_events.append(event)
            if venue_events:
                record_learning_events(venue_events)
                saved += len(venue_events)
                existing_keys.update(
                    event["key"] for event in venue_events if event.get("key")
                )
            time.sleep(1.0)
        return saved
    finally:
        mark_worker_end("today_record")


def admin_auto_backfill_worker():
    while True:
        try:
            record_today_completed_once()
        except Exception:
            pass
        now = datetime.now(JST)
        target = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if now.hour >= 2 and target not in admin_backfill_done:
            schedule_admin_backfill(target)
        time.sleep(TODAY_RECORD_INTERVAL_SECONDS)


def schedule_admin_auto_backfill():
    thread = threading.Thread(target=admin_auto_backfill_worker, daemon=True)
    thread.start()


def read_program_cache():
    try:
        payload = json.loads(PROGRAM_CACHE_FILE.read_text(encoding="utf-8"))
        prune_saved_at_mapping(payload, PROGRAM_CACHE_MAX_ENTRIES)
        return payload
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


program_cache = read_program_cache()


def save_program_cache():
    request_cache_save("program")


def read_schedule_cache():
    try:
        return json.loads(SCHEDULE_CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_schedule_cache():
    request_cache_save("schedule")


venue_status_cache.update(read_schedule_cache())


def read_results_cache():
    try:
        payload = json.loads(RESULTS_CACHE_FILE.read_text(encoding="utf-8"))
        prune_saved_at_mapping(payload, RESULTS_CACHE_MAX_ENTRIES)
        return payload
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_results_cache():
    request_cache_save("results")


def get_result_cache_seconds(date, payload=None):
    if date < current_jst_date():
        if payload and payload.get("available"):
            return PAST_RESULT_CACHE_SECONDS
        return 0
    if payload and payload.get("available"):
        return CACHE_SECONDS
    return 45


def get_cached_result(date, jcd, race):
    cache_key = f"{date}-{jcd}"
    with results_cache_lock:
        cached = results_cache.get(cache_key)
    if not cached:
        return None
    payload = (cached.get("payload") or {}).get("results", {}).get(str(race))
    if not payload:
        return None
    age = time.time() - cached.get("savedAt", 0)
    if age < get_result_cache_seconds(date, payload):
        return payload
    return None


def get_stored_result(date, jcd, race):
    cache_key = f"{date}-{jcd}"
    with results_cache_lock:
        cached = results_cache.get(cache_key)
    if not cached:
        return None
    return (cached.get("payload") or {}).get("results", {}).get(str(race))


def get_stored_results_for_venue(date, jcd):
    cache_key = f"{date}-{jcd}"
    with results_cache_lock:
        cached = results_cache.get(cache_key)
    if not cached:
        return {}
    return dict((cached.get("payload") or {}).get("results", {}))


def store_result_payload(date, jcd, race, payload):
    cache_key = f"{date}-{jcd}"
    with results_cache_lock:
        cached = results_cache.get(cache_key, {}).get("payload", {})
        merged_results = dict(cached.get("results", {}))
        merged_results[str(race)] = payload
        results_cache[cache_key] = {
            "savedAt": time.time(),
            "payload": {
                "date": date,
                "jcd": jcd,
                "results": merged_results,
            },
        }
        prune_saved_at_mapping(results_cache, RESULTS_CACHE_MAX_ENTRIES)
    save_results_cache()


results_cache.update(read_results_cache())


def read_signals_cache():
    try:
        payload = json.loads(SIGNALS_CACHE_FILE.read_text(encoding="utf-8"))
        prune_saved_at_mapping(payload, SIGNALS_CACHE_MAX_ENTRIES)
        return payload
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_signals_cache():
    request_cache_save("signals")


def get_signals_cache_seconds(date, payload=None):
    if payload and not payload.get("available"):
        return 45
    today = current_jst_date()
    if date < today:
        return PAST_RESULT_CACHE_SECONDS
    if date > today:
        return CACHE_SECONDS
    return SIGNALS_CACHE_SECONDS


def get_cached_signals(date, jcd, race):
    cache_key = f"{date}-{jcd}-{race}"
    with signals_cache_lock:
        cached = signals_cache.get(cache_key)
    if not cached:
        return None
    payload = cached.get("payload")
    if time.time() - cached.get("savedAt", 0) > get_signals_cache_seconds(date, payload):
        return None
    return payload


def store_signals_payload(date, jcd, race, payload):
    cache_key = f"{date}-{jcd}-{race}"
    with signals_cache_lock:
        signals_cache[cache_key] = {
            "savedAt": time.time(),
            "payload": payload,
        }
        prune_saved_at_mapping(signals_cache, SIGNALS_CACHE_MAX_ENTRIES)
    save_signals_cache()


signals_cache.update(read_signals_cache())


def write_json_atomic(path, payload):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        temporary.replace(path)
    except OSError:
        pass


def request_cache_save(name):
    with cache_flush_lock:
        dirty_cache_files.add(name)


def flush_cache_file(name):
    if name == "program":
        with program_cache_lock:
            prune_saved_at_mapping(program_cache, PROGRAM_CACHE_MAX_ENTRIES)
            snapshot = dict(program_cache)
        write_json_atomic(PROGRAM_CACHE_FILE, snapshot)
    elif name == "schedule":
        with venue_status_cache_lock:
            snapshot = dict(venue_status_cache)
        write_json_atomic(SCHEDULE_CACHE_FILE, snapshot)
    elif name == "results":
        with results_cache_lock:
            prune_saved_at_mapping(results_cache, RESULTS_CACHE_MAX_ENTRIES)
            snapshot = dict(results_cache)
        write_json_atomic(RESULTS_CACHE_FILE, snapshot)
    elif name == "signals":
        with signals_cache_lock:
            prune_saved_at_mapping(signals_cache, SIGNALS_CACHE_MAX_ENTRIES)
            snapshot = dict(signals_cache)
        write_json_atomic(SIGNALS_CACHE_FILE, snapshot)


def flush_dirty_caches_once():
    with cache_flush_lock:
        targets = sorted(dirty_cache_files)
        dirty_cache_files.clear()
    for target in targets:
        try:
            flush_cache_file(target)
        except Exception:
            with cache_flush_lock:
                dirty_cache_files.add(target)


def cache_flush_worker():
    while True:
        time.sleep(CACHE_FLUSH_INTERVAL_SECONDS)
        flush_dirty_caches_once()


def schedule_cache_flush_worker():
    thread = threading.Thread(target=cache_flush_worker, daemon=True)
    thread.start()


def cleanup_html_cache_once():
    if not HTML_CACHE_MAX_AGE_SECONDS and not HTML_CACHE_MAX_FILES:
        return 0
    try:
        files = list(CACHE_DIR.glob("*.html"))
    except OSError:
        return 0
    now = time.time()
    removed = 0
    survivors = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        if HTML_CACHE_MAX_AGE_SECONDS and now - stat.st_mtime > HTML_CACHE_MAX_AGE_SECONDS:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        else:
            survivors.append((stat.st_mtime, path))
    if HTML_CACHE_MAX_FILES and len(survivors) > HTML_CACHE_MAX_FILES:
        for _, path in sorted(survivors)[: len(survivors) - HTML_CACHE_MAX_FILES]:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def html_cache_cleanup_worker():
    while True:
        try:
            cleanup_html_cache_once()
        except Exception:
            pass
        time.sleep(max(60, HTML_CACHE_CLEANUP_INTERVAL_SECONDS))


def schedule_html_cache_cleanup_worker():
    thread = threading.Thread(target=html_cache_cleanup_worker, daemon=True)
    thread.start()


def schedule_program_prefetch(date, jcd):
    thread = threading.Thread(
        target=warm_program_races,
        args=(date, jcd),
        daemon=True,
    )
    thread.start()


def warm_program_races(date, jcd, progress_callback=None):
    prefetch_key = f"{date}-{jcd}"
    with prefetch_lock:
        if prefetch_key in prefetching_programs:
            return
        prefetching_programs.add(prefetch_key)
    try:
        for race in range(1, 13):
            try:
                payload = load_program(date, jcd, race, should_prefetch=False)
            except Exception:
                continue
            if race == 1 and not payload.get("available"):
                break
            if progress_callback:
                progress_callback(jcd, race)
    finally:
        with prefetch_lock:
            prefetching_programs.discard(prefetch_key)


def current_jst_date():
    return datetime.now(JST).strftime("%Y-%m-%d")


def jst_date_offset(days):
    return (datetime.now(JST) + timedelta(days=days)).strftime("%Y-%m-%d")


def count_cached_detailed_races(date):
    now = time.time()
    total = 0
    with program_cache_lock:
        for jcd in BOATRACE_JCDS:
            stored = program_cache.get(f"{date}-{jcd}")
            if not stored or now - stored.get("savedAt", 0) >= CACHE_SECONDS:
                continue
            total += sum(
                1
                for race in stored.get("payload", {}).get("races", [])
                if race.get("detailed")
            )
    return total


def count_checked_venues(date):
    now = time.time()
    with venue_status_cache_lock:
        cached_status = venue_status_cache.get(date)
        if cached_status and now - cached_status.get("savedAt", 0) < CACHE_SECONDS:
            return len(cached_status.get("payload", {}).get("venues", {}))
    with program_cache_lock:
        return sum(
            1
            for jcd in BOATRACE_JCDS
            if (
                (stored := program_cache.get(f"{date}-{jcd}"))
                and now - stored.get("savedAt", 0) < CACHE_SECONDS
            )
        )


def update_warmup_status(**updates):
    with warmup_lock:
        warmup_status.update(updates)


def get_warmup_status():
    with warmup_lock:
        status = dict(warmup_status)
    if status["date"]:
        status["completedRaces"] = count_cached_detailed_races(status["date"])
        status["checkedVenues"] = count_checked_venues(status["date"])
    return status


def schedule_startup_warmup():
    thread = threading.Thread(target=startup_warmup_today, daemon=True)
    thread.start()


def startup_warmup_today():
    date = current_jst_date()
    warmup_dates = [jst_date_offset(offset) for offset in range(3)]
    update_warmup_status(
        active=True,
        date=date,
        currentJcd="",
        completedVenues=0,
        completedRaces=count_cached_detailed_races(date),
        startedAt=datetime.now(JST).isoformat(timespec="seconds"),
        finishedAt=None,
    )
    checked = 0
    for warmup_date in warmup_dates:
        try:
            venues_payload = load_venues_status(warmup_date)
            if warmup_date == date:
                checked = len(venues_payload.get("venues", {}))
                update_warmup_status(
                    currentJcd="",
                    completedVenues=checked,
                    completedRaces=count_cached_detailed_races(date),
                )
        except Exception:
            if warmup_date == date:
                checked = count_checked_venues(date)
    update_warmup_status(
        currentJcd="",
        completedVenues=checked,
        completedRaces=count_cached_detailed_races(date),
    )
    update_warmup_status(
        active=False,
        currentJcd="",
        completedVenues=count_checked_venues(date),
        completedRaces=count_cached_detailed_races(date),
        finishedAt=datetime.now(JST).isoformat(timespec="seconds"),
    )


def is_server_race_completed(date, cutoff):
    if not cutoff:
        return date < current_jst_date()
    today = current_jst_date()
    if date < today:
        return True
    if date > today:
        return False
    match = re.search(r"(\d{1,2}):(\d{2})", str(cutoff))
    if not match:
        return False
    now = datetime.now(JST)
    cutoff_dt = now.replace(
        hour=int(match.group(1)),
        minute=int(match.group(2)),
        second=0,
        microsecond=0,
    )
    return now >= cutoff_dt + timedelta(minutes=3)


def should_warm_signals(date, cutoff):
    if date != current_jst_date() or not cutoff:
        return False
    match = re.search(r"(\d{1,2}):(\d{2})", str(cutoff))
    if not match:
        return False
    now = datetime.now(JST)
    cutoff_dt = now.replace(
        hour=int(match.group(1)),
        minute=int(match.group(2)),
        second=0,
        microsecond=0,
    )
    return now - timedelta(minutes=20) <= cutoff_dt <= now + timedelta(minutes=90)


def warm_completed_results_once(date=None):
    target_date = date or current_jst_date()
    try:
        venues_payload = load_venues_status(target_date)
    except Exception:
        return
    try:
        load_pay_results(target_date, timeout=FETCH_TIMEOUT_SECONDS)
    except Exception:
        pass
    active_jcds = [
        jcd for jcd, status in (venues_payload.get("venues") or {}).items()
        if status.get("available")
    ]
    active_jcds.sort()
    for jcd in active_jcds:
        try:
            program = load_program(target_date, jcd, 1, should_prefetch=False)
            completed_races = [
                race["race"]
                for race in program.get("races", [])
                if is_server_race_completed(target_date, race.get("cutoff"))
            ]
            missing_races = [
                race for race in completed_races
                if not get_cached_result(target_date, jcd, race)
            ]
            if missing_races:
                load_results(target_date, jcd, missing_races)
            for race in completed_races:
                payload = get_stored_result(target_date, jcd, race)
                if payload and payload.get("available") and not has_payout_type(payload, "2連単"):
                    schedule_result_enrich(target_date, jcd, race)
        except Exception:
            pass
        time.sleep(0.6)


def result_warmer_worker():
    while True:
        mark_worker_start("result_warmer")
        try:
            for offset in (-1, 0):
                warm_completed_results_once(jst_date_offset(offset))
        finally:
            mark_worker_end("result_warmer")
        time.sleep(BACKGROUND_SYNC_INTERVAL_SECONDS)


def pay_warmer_worker():
    while True:
        mark_worker_start("pay_warmer")
        try:
            load_pay_results(current_jst_date(), timeout=min(FETCH_TIMEOUT_SECONDS, 8))
        except Exception:
            pass
        finally:
            mark_worker_end("pay_warmer")
        time.sleep(max(20, PAY_WARM_INTERVAL_SECONDS))


def background_data_sync_once():
    today = current_jst_date()
    for offset in (-1, 0, 1):
        target_date = jst_date_offset(offset)
        try:
            venues_payload = load_venues_status(target_date)
        except Exception:
            venues_payload = {"venues": {}}
        if offset <= 0:
            try:
                load_pay_results(target_date, timeout=FETCH_TIMEOUT_SECONDS)
            except Exception:
                pass
        if target_date != today:
            continue
        active_jcds = [
            jcd for jcd, status in (venues_payload.get("venues") or {}).items()
            if status.get("available")
        ]
        for jcd in sorted(active_jcds):
            try:
                program = load_program(target_date, jcd, 1, should_prefetch=False)
            except Exception:
                program = {"races": []}
            for race in program.get("races", []):
                if not should_warm_signals(target_date, race.get("cutoff")):
                    continue
                try:
                    load_signals(target_date, jcd, race.get("race"), timeout=DETAIL_FETCH_TIMEOUT_SECONDS)
                except Exception:
                    pass
                time.sleep(0.15)
            time.sleep(0.2)


def background_data_sync_worker():
    while True:
        mark_worker_start("background_sync")
        try:
            background_data_sync_once()
        finally:
            mark_worker_end("background_sync")
        time.sleep(BACKGROUND_SYNC_INTERVAL_SECONDS)


def schedule_background_data_sync():
    thread = threading.Thread(target=background_data_sync_worker, daemon=True)
    thread.start()


def schedule_result_warmer():
    thread = threading.Thread(target=result_warmer_worker, daemon=True)
    thread.start()


def schedule_pay_warmer():
    thread = threading.Thread(target=pay_warmer_worker, daemon=True)
    thread.start()


def get_fetch_lock(path):
    with fetch_locks_guard:
        lock = fetch_locks.get(path)
        if lock is None:
            prune_fetch_locks()
            lock = fetch_locks.setdefault(path, threading.Lock())
        fetch_lock_access[path] = time.time()
        return lock


def get_memory_cached_html(path, cache_seconds):
    if cache_seconds <= 0:
        return None
    with cache_lock:
        cached = cache.get(path)
    if cached and time.time() - cached[0] < cache_seconds:
        return cached[1]
    return None


def remember_memory_cached_html(path, text, cache_seconds):
    if cache_seconds <= 0 or not FETCH_MEMORY_CACHE_MAX_ENTRIES:
        return
    with cache_lock:
        cache[path] = (time.time(), text)
        overflow = len(cache) - FETCH_MEMORY_CACHE_MAX_ENTRIES
        if overflow > 0:
            oldest_keys = sorted(cache, key=lambda key: cache[key][0])[:overflow]
            for key in oldest_keys:
                cache.pop(key, None)


def fetch_html(path, cache_seconds=CACHE_SECONDS, timeout=FETCH_TIMEOUT_SECONDS):
    cached = get_memory_cached_html(path, cache_seconds)
    if cached:
        return cached
    with get_fetch_lock(path):
        cached = get_memory_cached_html(path, cache_seconds)
        if cached:
            return cached
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{hashlib.sha256(path.encode()).hexdigest()}.html"
        stale_text = None
        if cache_file.exists():
            stale_text = cache_file.read_text(encoding="utf-8")
            if time.time() - cache_file.stat().st_mtime < cache_seconds:
                remember_memory_cached_html(path, stale_text, cache_seconds)
                return stale_text
        request = Request(f"{OFFICIAL_BASE}{path}", headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
        except Exception:
            if stale_text and cache_seconds > 0:
                remember_memory_cached_html(path, stale_text, cache_seconds)
                return stale_text
            raise
        remember_memory_cached_html(path, text, cache_seconds)
        cache_file.write_text(text, encoding="utf-8")
        return text


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.active_link = None
        self.tbody_classes = []
        self.current_tbody = ""

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "tbody":
            self.current_tbody = attributes.get("class", "")
            self.tbody_classes.append(self.current_tbody)
        elif tag == "tr":
            self.row = {"cells": [], "tbody": self.current_tbody}
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"text": [], "links": [], "classes": attributes.get("class", "")}
        elif tag == "a" and self.cell is not None:
            self.active_link = {"href": attributes.get("href", ""), "text": []}
            self.cell["links"].append(self.active_link)
        elif tag == "br" and self.cell is not None:
            self.cell["text"].append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)
            if self.active_link is not None:
                self.active_link["text"].append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.cell["text"] = normalize_text("".join(self.cell["text"]))
            for link in self.cell["links"]:
                link["text"] = normalize_text("".join(link["text"]))
            self.row["cells"].append(self.cell)
            self.cell = None
            self.active_link = None
        elif tag == "a":
            self.active_link = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == "tbody":
            self.current_tbody = ""


def normalize_text(value):
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def parse_race_index(html_text):
    parser = TableParser()
    parser.feed(html_text)
    races = []
    for row in parser.rows:
        cells = row["cells"]
        if len(cells) < 9:
            continue
        race_link = next(
            (link for link in cells[0]["links"] if "racelist?rno=" in link["href"]),
            None,
        )
        if not race_link:
            continue
        match = re.search(r"rno=(\d+)", race_link["href"])
        if not match:
            continue
        racers = []
        for cell in cells[3:9]:
            profile = next(
                (link for link in cell["links"] if "toban=" in link["href"]),
                None,
            )
            if not profile:
                racers = []
                break
            registration_match = re.search(r"toban=(\d+)", profile["href"])
            grade_match = re.search(r"\b(A1|A2|B1|B2)\b", cell["text"])
            racers.append(
                {
                    "name": profile["text"],
                    "registration": int(registration_match.group(1)),
                    "grade": grade_match.group(1) if grade_match else "",
                }
            )
        if len(racers) == 6:
            races.append(
                {
                    "race": int(match.group(1)),
                    "cutoff": cells[1]["text"],
                    "racers": racers,
                }
            )
    return sorted(races, key=lambda item: item["race"])


def parse_daily_venue_index(html_text, compact_date):
    active = {}
    for raw_url in re.findall(r"(?:raceindex|racelist)\?[^\"'<> ]+", html_text):
        url = raw_url.replace("&amp;", "&")
        params = dict(re.findall(r"(jcd|hd|rno)=(\d+)", url))
        if params.get("hd") != compact_date:
            continue
        jcd = params.get("jcd", "").zfill(2)
        if jcd not in BOATRACE_JCDS:
            continue
        if "raceindex?" in url:
            active.setdefault(jcd, 12)
            continue
        race = int(params.get("rno") or 0)
        active[jcd] = max(active.get(jcd, 0), race)
    if not active:
        return {}
    return {
        jcd: {
            "jcd": jcd,
            "available": jcd in active,
            "races": active.get(jcd, 0),
            "cached": False,
            "source": "daily-index",
        }
        for jcd in BOATRACE_JCDS
    }


def first_number(value):
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def parse_racelist(html_text):
    parser = TableParser()
    parser.feed(html_text)
    racers = []
    for row in parser.rows:
        if "is-fs12" not in row["tbody"]:
            continue
        cells = row["cells"]
        if len(cells) < 9:
            continue
        profile = next(
            (
                link
                for link in cells[2]["links"]
                if "toban=" in link["href"] and link["text"]
            ),
            None,
        )
        if not profile:
            continue
        registration_match = re.search(r"toban=(\d+)", profile["href"])
        grade_match = re.search(r"\b(A1|A2|B1|B2)\b", cells[2]["text"])
        start_values = re.findall(r"0\.\d+", cells[3]["text"])
        motor_values = re.findall(r"\d+(?:\.\d+)?", cells[6]["text"])
        racers.append(
            {
                "boat": len(racers) + 1,
                "registration": int(registration_match.group(1)),
                "name": profile["text"],
                "grade": grade_match.group(1) if grade_match else "",
                "start": float(start_values[-1]) if start_values else None,
                "national": first_number(cells[4]["text"]),
                "local": first_number(cells[5]["text"]),
                "motor": float(motor_values[1]) if len(motor_values) > 1 else None,
            }
        )
        if len(racers) == 6:
            break
    return racers


def parse_result(html_text):
    parser = TableParser()
    parser.feed(html_text)
    placements = []
    seen_ranks = set()
    seen_boats = set()
    payout = None
    rank_map = {"１": 1, "２": 2, "３": 3, "1": 1, "2": 2, "3": 3}
    for row in parser.rows:
        cells = row["cells"]
        if len(cells) >= 2 and cells[0]["text"] in rank_map:
            rank = rank_map[cells[0]["text"]]
            boat_text = normalize_text(cells[1]["text"]).translate(
                str.maketrans("１２３４５６", "123456")
            )
            boat_text = boat_text.replace("号艇", "").strip()
            if not re.fullmatch(r"[1-6]", boat_text):
                continue
            boat = int(boat_text)
            if rank in seen_ranks or boat in seen_boats:
                continue
            seen_ranks.add(rank)
            seen_boats.add(boat)
            placements.append((rank, boat))
        if len(cells) >= 3 and cells[0]["text"] == "3連単":
            payout_match = re.search(r"[\d,]+", cells[2]["text"])
            if payout_match:
                payout = int(payout_match.group().replace(",", ""))
    placements.sort()
    result = [boat for _, boat in placements[:3]]
    if [rank for rank, _ in placements[:3]] != [1, 2, 3]:
        return None
    if len(result) != 3 or len(set(result)) != 3 or payout is None:
        return None
    return {"result": result, "payout": payout}


def parse_pay_results(html_text, compact_date):
    results = {}
    td_pattern = re.compile(r"<td\b([^>]*)>(.*?)</td>", re.S)
    cells = []
    href_pattern = re.compile(
        rf'data-href="[^"]*raceresult\?rno=(\d+)&jcd=(\d{{2}})&hd={re.escape(compact_date)}"'
    )
    for attributes, body in td_pattern.findall(html_text):
        href_match = href_pattern.search(attributes)
        if not href_match:
            continue
        cells.append({
            "race": int(href_match.group(1)),
            "jcd": href_match.group(2),
            "body": body,
        })
    for index in range(len(cells) - 2):
        combo_cell, payout_cell, popularity_cell = cells[index:index + 3]
        if (
            combo_cell["race"] != payout_cell["race"]
            or combo_cell["race"] != popularity_cell["race"]
            or combo_cell["jcd"] != payout_cell["jcd"]
            or combo_cell["jcd"] != popularity_cell["jcd"]
        ):
            continue
        boats = [
            int(value)
            for value in re.findall(r'numberSet1_number[^>]*>\s*(\d)\s*</span>', combo_cell["body"])
        ]
        payout_match = re.search(r"(?:&yen;|¥)\s*([\d,]+)", payout_cell["body"])
        popularity_values = re.findall(r">\s*(\d{1,3})\s*<", popularity_cell["body"])
        if len(boats) != 3 or len(set(boats)) != 3 or not payout_match:
            continue
        payout = int(payout_match.group(1).replace(",", ""))
        popularity = int(popularity_values[-1]) if popularity_values else None
        jcd = combo_cell["jcd"]
        race = combo_cell["race"]
        results.setdefault(jcd, {})[race] = {
            "date": f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:]}",
            "jcd": jcd,
            "race": race,
            "available": True,
            "result": {"result": boats, "payout": payout},
            "weather": {"available": False},
            "payouts": [
                {
                    "type": "3連単",
                    "ticket": boats,
                    "payout": payout,
                    "popularity": popularity,
                }
            ],
            "source": "pay",
        }
    return results


def load_pay_results(date, timeout=FETCH_TIMEOUT_SECONDS):
    compact_date = date.replace("-", "")
    cache_seconds = PAST_RESULT_CACHE_SECONDS if date < current_jst_date() else 20
    html_text = fetch_html(
        f"/owpc/pc/race/pay?hd={compact_date}",
        cache_seconds=cache_seconds,
        timeout=timeout,
    )
    parsed = parse_pay_results(html_text, compact_date)
    for jcd, race_map in parsed.items():
        for race, payload in race_map.items():
            store_result_payload(date, jcd, race, payload)
    return parsed


def schedule_pay_refresh(date):
    if date > current_jst_date():
        return
    with pay_refresh_lock:
        if date in pay_refreshing_dates:
            return
        pay_refreshing_dates.add(date)

    def worker():
        try:
            load_pay_results(date, timeout=min(FETCH_TIMEOUT_SECONDS, 8))
        except Exception:
            pass
        finally:
            with pay_refresh_lock:
                pay_refreshing_dates.discard(date)

    threading.Thread(target=worker, daemon=True).start()


def schedule_result_enrich(date, jcd, race, timeout=DETAIL_FETCH_TIMEOUT_SECONDS):
    if date > current_jst_date():
        return
    key = f"{date}-{jcd}-{race}"
    with result_enrich_lock:
        if key in result_enriching:
            return
        result_enriching.add(key)

    def worker():
        try:
            base = get_stored_result(date, jcd, race) or get_pay_result(
                date,
                jcd,
                race,
                timeout=timeout,
                allow_live=False,
            )
            if not base or not base.get("available"):
                return
            detail_payload = fetch_raceresult_payload(date, jcd, race, timeout=timeout)
            merged = merge_result_weather(base, detail_payload)
            store_result_payload(date, jcd, race, merged)
        except Exception:
            pass
        finally:
            with result_enrich_lock:
                result_enriching.discard(key)

    threading.Thread(target=worker, daemon=True).start()


def get_cached_pay_results(date):
    grouped = {}
    with results_cache_lock:
        snapshot = dict(results_cache)
    prefix = f"{date}-"
    for cache_key, cached in snapshot.items():
        if not cache_key.startswith(prefix):
            continue
        jcd = cache_key.split("-", 3)[-1]
        race_map = {}
        for race_text, payload in ((cached.get("payload") or {}).get("results") or {}).items():
            if isinstance(payload, dict) and payload.get("available"):
                race_map[int(race_text)] = payload
        if race_map:
            grouped[jcd] = race_map
    return grouped


def merge_pay_venue_status(date, venues_status):
    if date > current_jst_date():
        return venues_status
    pay_results = get_cached_pay_results(date)
    if not pay_results:
        schedule_pay_refresh(date)
        return venues_status
    merged = dict(venues_status or {})
    for jcd, race_map in pay_results.items():
        race_count = max(race_map.keys()) if race_map else 0
        current = dict(merged.get(jcd) or {})
        merged[jcd] = {
            **current,
            "jcd": jcd,
            "available": True,
            "races": max(int(current.get("races") or 0), race_count),
            "payResults": len(race_map),
            "source": "pay",
        }
    return merged


def get_pay_result(date, jcd, race, timeout=FETCH_TIMEOUT_SECONDS, allow_live=True):
    cached = get_stored_result(date, jcd, race)
    if cached and cached.get("available"):
        return cached
    if not allow_live:
        schedule_pay_refresh(date)
        return None
    try:
        return (load_pay_results(date, timeout=timeout).get(jcd) or {}).get(race)
    except Exception:
        return None


def parse_payouts(html_text):
    parser = TableParser()
    parser.feed(html_text)
    payout_types = {"単勝", "複勝", "2連単", "2連複", "3連単", "3連複", "拡連複"}
    payouts = []
    current_type = ""
    for row in parser.rows:
        cells = row["cells"]
        if len(cells) < 3:
            continue
        first = cells[0]["text"].replace("　", "").strip()
        offset = 0
        if first in payout_types:
            current_type = first
        elif current_type and re.search(r"[1-6１２３４５６不成立]", first):
            offset = -1
        else:
            current_type = ""
            continue
        ticket_index = 1 + offset
        payout_index = 2 + offset
        popularity_index = 3 + offset
        if ticket_index < 0 or payout_index >= len(cells):
            continue
        ticket_text = normalize_text(cells[ticket_index]["text"]).translate(
            str.maketrans("１２３４５６－＝", "123456-=")
        )
        ticket_text = re.sub(r"\s+", "", ticket_text)
        payout_match = re.search(r"[\d,]+", cells[payout_index]["text"])
        if not ticket_text or "不成立" in ticket_text or not re.search(r"[1-6]", ticket_text) or not payout_match:
            continue
        popularity = None
        if 0 <= popularity_index < len(cells):
            popularity_match = re.search(r"\d+", cells[popularity_index]["text"])
            if popularity_match:
                popularity = int(popularity_match.group())
        payouts.append({
            "type": current_type,
            "ticket": ticket_text,
            "payout": int(payout_match.group().replace(",", "")),
            "popularity": popularity,
        })
    return payouts


def strip_tags(value):
    return normalize_text(re.sub(r"<[^>]+>", " ", value).replace("&nbsp;", " "))


def parse_pcexpect(html_text):
    focus_match = re.search(
        r'<span class="title6_mainLabel">予想フォーカス</span>.*?</div>\s*<div class="state2">',
        html_text,
        re.S,
    )
    focus_html = focus_match.group(0) if focus_match else ""
    tickets = []
    for row_html in re.findall(r'<div class="numberSet2_row">(.*?)</div>', focus_html, re.S):
        boats = [
            int(match)
            for match in re.findall(r'numberSet2_number is-type([1-6])', row_html)
        ]
        if 2 <= len(boats) <= 3:
            tickets.append(boats)
    confidence_match = re.search(r"state2_lv is-lv(\d+)", html_text)
    scores = {boat: 0 for boat in range(1, 7)}
    for index, ticket in enumerate(tickets):
        weight = max(1, 10 - index)
        if len(ticket) >= 1:
            scores[ticket[0]] += weight * 4
        if len(ticket) >= 2:
            scores[ticket[1]] += weight * 2
        if len(ticket) >= 3:
            scores[ticket[2]] += weight
    order = sorted(scores, key=lambda boat: (-scores[boat], boat))
    return {
        "available": bool(tickets),
        "tickets": tickets,
        "confidence": int(confidence_match.group(1)) if confidence_match else None,
        "scores": scores,
        "order": order,
    }


def parse_beforeinfo(html_text):
    parser = TableParser()
    parser.feed(html_text)
    racers = {}
    for row in parser.rows:
        cells = [cell["text"] for cell in row["cells"]]
        if len(cells) < 8 or not re.fullmatch(r"[1-6]", cells[0]):
            continue
        boat = int(cells[0])
        exhibition = first_number(cells[4])
        tilt = first_number(cells[5])
        racers[boat] = {
            "boat": boat,
            "name": cells[2],
            "weight": first_number(cells[3]),
            "exhibition": exhibition,
            "tilt": tilt,
            "parts": cells[7],
        }
    return {
        "available": any(
            racer.get("exhibition") is not None for racer in racers.values()
        ),
        "racers": racers,
        "weather": parse_weather(html_text),
    }


def parse_weather(html_text):
    start_match = re.search(r'<div[^>]*class="[^"]*\bweather1\b[^"]*"[^>]*>', html_text)
    if not start_match:
        return {"available": False}
    start = start_match.start()
    end_match = re.search(r'<div[^>]*class="[^"]*\bweather1_stand\b[^"]*"[^>]*>', html_text[start:])
    end = start + end_match.start() if end_match else -1
    block = html_text[start:end if end >= 0 else start + 5000]
    observed_match = re.search(r"水面気象情報\s*([0-9:]+)現在", strip_tags(block))
    direction_match = re.search(r"is-direction(\d+)", block)
    weather_match = re.search(
        r'is-weather[^"]*">.*?weather1_bodyUnitLabelTitle">([^<]+)</span>',
        block,
        re.S,
    )
    wind_match = re.search(
        r'is-wind[^"]*">.*?weather1_bodyUnitLabelData">([^<]+)</span>',
        block,
        re.S,
    )
    temperature_match = re.search(
        r'is-temperature[^"]*">.*?weather1_bodyUnitLabelData">([^<]+)</span>',
        block,
        re.S,
    )
    water_temperature_match = re.search(
        r'is-waterTemperature[^"]*">.*?weather1_bodyUnitLabelData">([^<]+)</span>',
        block,
        re.S,
    )
    wave_match = re.search(
        r'is-wave[^"]*">.*?weather1_bodyUnitLabelData">([^<]+)</span>',
        block,
        re.S,
    )
    direction_code = int(direction_match.group(1)) if direction_match else None
    direction_names = {
        1: "北", 2: "北北東", 3: "北東", 4: "東北東",
        5: "東", 6: "東南東", 7: "南東", 8: "南南東",
        9: "南", 10: "南南西", 11: "南西", 12: "西南西",
        13: "西", 14: "西北西", 15: "北西", 16: "北北西",
    }
    weather = {
        "available": True,
        "observedAt": observed_match.group(1) if observed_match else "",
        "weather": normalize_text(weather_match.group(1)) if weather_match else "",
        "temperature": first_number(temperature_match.group(1)) if temperature_match else None,
        "windSpeed": first_number(wind_match.group(1)) if wind_match else None,
        "windDirection": direction_names.get(direction_code, ""),
        "windDirectionCode": direction_code,
        "waterTemperature": first_number(water_temperature_match.group(1)) if water_temperature_match else None,
        "waveHeight": first_number(wave_match.group(1)) if wave_match else None,
    }
    weather["available"] = any(
        weather.get(key) not in (None, "")
        for key in ("weather", "temperature", "windSpeed", "windDirection", "waveHeight")
    )
    return weather


def parse_odds3t(html_text):
    tbody_match = re.search(
        r'<tbody class="is-p3-0">(.*?)</tbody>',
        html_text,
        re.S,
    )
    if not tbody_match:
        return {"available": False, "odds": {}, "firstPopularity": []}
    rows = re.findall(r"<tr>(.*?)</tr>", tbody_match.group(1), re.S)
    current_second = {}
    odds = {}
    for row_html in rows:
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", row_html, re.S)
        index = 0
        for first in range(1, 7):
            if index >= len(cells):
                break
            attrs, content = cells[index]
            if "rowspan" in attrs:
                second = int(strip_tags(content))
                current_second[first] = second
                index += 1
            second = current_second.get(first)
            if second is None or index + 1 >= len(cells):
                break
            third = first_number(strip_tags(cells[index][1]))
            price = first_number(strip_tags(cells[index + 1][1]))
            index += 2
            if third is None or price is None:
                continue
            ticket = f"{first}-{second}-{int(third)}"
            odds[ticket] = price
    first_best = {}
    for ticket, price in odds.items():
        first = int(ticket.split("-")[0])
        first_best[first] = min(first_best.get(first, price), price)
    first_popularity = [
        boat
        for boat, _price in sorted(first_best.items(), key=lambda item: (item[1], item[0]))
    ]
    return {
        "available": bool(odds),
        "odds": odds,
        "firstPopularity": first_popularity,
    }


def load_signals(date, jcd, race, timeout=FETCH_TIMEOUT_SECONDS):
    cached = get_cached_signals(date, jcd, race)
    if cached:
        return cached
    compact_date = date.replace("-", "")
    paths = {
        "expect": (f"/owpc/pc/race/pcexpect?rno={race}&jcd={jcd}&hd={compact_date}", 600),
        "beforeinfo": (f"/owpc/pc/race/beforeinfo?rno={race}&jcd={jcd}&hd={compact_date}", 45),
        "odds": (f"/owpc/pc/race/odds3t?rno={race}&jcd={jcd}&hd={compact_date}", 300),
    }
    html = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            name: executor.submit(fetch_html, path, cache_seconds, timeout)
            for name, (path, cache_seconds) in paths.items()
        }
        for name, future in futures.items():
            try:
                html[name] = future.result()
            except Exception:
                html[name] = ""
    payload = {
        "date": date,
        "jcd": jcd,
        "race": race,
        "expect": parse_pcexpect(html["expect"]) if html["expect"] else {"available": False},
        "beforeinfo": parse_beforeinfo(html["beforeinfo"]) if html["beforeinfo"] else {"available": False, "racers": {}},
        "odds": parse_odds3t(html["odds"]) if html["odds"] else {"available": False, "odds": {}, "firstPopularity": []},
    }
    payload["available"] = any(
        payload.get(key, {}).get("available")
        for key in ("expect", "beforeinfo", "odds")
    )
    store_signals_payload(date, jcd, race, payload)
    return payload


def load_program(date, jcd, selected_race, should_prefetch=True):
    program_key = f"{date}-{jcd}"
    recent_payload = None
    stale_payload = None
    with program_cache_lock:
        stored = program_cache.get(program_key)
        if stored:
            stored_age = time.time() - stored.get("savedAt", 0)
            stale_payload = stored.get("payload")
        if stored and stored_age < CACHE_SECONDS:
            if not stored["payload"].get("available"):
                if stored_age < PROGRAM_UNAVAILABLE_CACHE_SECONDS:
                    return stored["payload"]
            else:
                recent_payload = stored["payload"]
                stored_race = next(
                    (
                        race
                        for race in stored["payload"].get("races", [])
                        if race["race"] == selected_race
                    ),
                    None,
                )
                if stored_race and stored_race.get("detailed"):
                    if should_prefetch:
                        schedule_program_prefetch(date, jcd)
                    return stored["payload"]
                if stored_race and len(stored_race.get("racers", [])) == 6:
                    if should_prefetch:
                        schedule_program_prefetch(date, jcd)
                    return stored["payload"]
        elif stale_payload and stale_payload.get("available"):
            recent_payload = stale_payload

    compact_date = date.replace("-", "")
    index_path = f"/owpc/pc/race/raceindex?hd={compact_date}&jcd={jcd}"
    detail_path = (
        f"/owpc/pc/race/racelist?rno={selected_race}"
        f"&jcd={jcd}&hd={compact_date}"
    )
    if recent_payload and recent_payload.get("races"):
        races = [dict(race) for race in recent_payload["races"]]
        try:
            detail_html = fetch_html(detail_path, timeout=DETAIL_FETCH_TIMEOUT_SECONDS)
        except Exception:
            detail_html = ""
    else:
        with ThreadPoolExecutor(max_workers=2) as executor:
            index_future = executor.submit(fetch_html, index_path, CACHE_SECONDS, PROGRAM_INDEX_TIMEOUT_SECONDS)
            detail_future = executor.submit(fetch_html, detail_path, CACHE_SECONDS, DETAIL_FETCH_TIMEOUT_SECONDS)
            try:
                index_html = index_future.result()
            except Exception:
                if stale_payload and stale_payload.get("available"):
                    return stale_payload
                raise
            try:
                detail_html = detail_future.result()
            except Exception:
                detail_html = ""
        races = parse_race_index(index_html)
    if not races:
        try:
            races = parse_race_index(fetch_html(index_path, cache_seconds=0, timeout=PROGRAM_INDEX_TIMEOUT_SECONDS))
        except Exception:
            races = []
    if not races:
        if stale_payload and stale_payload.get("available"):
            return stale_payload
        payload = {"date": date, "jcd": jcd, "available": False, "races": []}
        if date > current_jst_date():
            with program_cache_lock:
                program_cache[program_key] = {
                    "savedAt": time.time(),
                    "payload": payload,
                }
                prune_saved_at_mapping(program_cache, PROGRAM_CACHE_MAX_ENTRIES)
            save_program_cache()
        return payload

    selected = next(
        (race for race in races if race["race"] == selected_race), None
    )
    if selected:
        details = parse_racelist(detail_html)
        if len(details) == 6:
            selected["racers"] = details
            selected["detailed"] = True
    for race in races:
        race.setdefault("detailed", False)
    payload = {
        "date": date,
        "jcd": jcd,
        "available": True,
        "races": races,
    }
    with program_cache_lock:
        previous = program_cache.get(program_key, {}).get("payload")
        if previous:
            previous_details = {
                race["race"]: race
                for race in previous.get("races", [])
                if race.get("detailed")
            }
            for index, race in enumerate(payload["races"]):
                if not race.get("detailed") and race["race"] in previous_details:
                    payload["races"][index] = previous_details[race["race"]]
        program_cache[program_key] = {
            "savedAt": time.time(),
            "payload": payload,
        }
        prune_saved_at_mapping(program_cache, PROGRAM_CACHE_MAX_ENTRIES)
    save_program_cache()
    if should_prefetch:
        schedule_program_prefetch(date, jcd)
    return payload


def fetch_raceresult_payload(date, jcd, race, timeout=FETCH_TIMEOUT_SECONDS):
    compact_date = date.replace("-", "")
    path = f"/owpc/pc/race/raceresult?rno={race}&jcd={jcd}&hd={compact_date}"
    result_cache_seconds = CACHE_SECONDS if date < current_jst_date() else 60
    html_text = fetch_html(path, cache_seconds=result_cache_seconds, timeout=timeout)
    result = parse_result(html_text)
    return {
        "date": date,
        "jcd": jcd,
        "race": race,
        "available": result is not None,
        "result": result,
        "weather": parse_weather(html_text),
        "payouts": parse_payouts(html_text),
        "source": "raceresult",
    }


def merge_result_weather(primary, detail):
    if not isinstance(primary, dict) or not isinstance(detail, dict):
        return primary
    weather = detail.get("weather") or {}
    if not weather.get("available") and not detail.get("payouts"):
        return primary
    merged = dict(primary)
    if weather.get("available"):
        merged["weather"] = weather
    if detail.get("payouts"):
        merged["payouts"] = detail["payouts"]
    merged["source"] = f"{primary.get('source') or 'result'}+raceresult-weather"
    return merged


def is_weather_available(weather):
    if not isinstance(weather, dict):
        return False
    if weather.get("available"):
        return True
    return any(
        weather.get(key) not in (None, "")
        for key in ("weather", "temperature", "windSpeed", "windDirection", "waveHeight")
    )


def choose_weather(*candidates):
    fallback = {}
    for weather in candidates:
        if not isinstance(weather, dict):
            continue
        if not fallback:
            fallback = weather
        if is_weather_available(weather):
            return weather
    return fallback


def has_payout_type(payload, payout_type):
    for payout in (payload or {}).get("payouts") or []:
        if payout.get("type") == payout_type:
            return True
    return False


def load_result(date, jcd, race, timeout=FETCH_TIMEOUT_SECONDS, include_weather=False, allow_live=True):
    cached = get_cached_result(date, jcd, race)
    if cached and (
        not include_weather
        or (
            (cached.get("weather") or {}).get("available")
            and has_payout_type(cached, "2連単")
        )
    ):
        return cached
    pay_payload = get_pay_result(date, jcd, race, timeout=min(timeout, 12), allow_live=allow_live)
    if pay_payload:
        needs_detail = include_weather and (
            not (pay_payload.get("weather") or {}).get("available")
            or not has_payout_type(pay_payload, "2連単")
        )
        if needs_detail and allow_live:
            try:
                detail_payload = fetch_raceresult_payload(date, jcd, race, timeout=timeout)
                pay_payload = merge_result_weather(pay_payload, detail_payload)
                store_result_payload(date, jcd, race, pay_payload)
            except Exception:
                pass
        elif needs_detail:
            schedule_result_enrich(date, jcd, race)
        return pay_payload
    if not allow_live:
        schedule_pay_refresh(date)
        return {
            "date": date,
            "jcd": jcd,
            "race": race,
            "available": False,
            "result": None,
            "weather": {"available": False},
            "source": "pending-pay-refresh",
        }
    payload = fetch_raceresult_payload(date, jcd, race, timeout=timeout)
    store_result_payload(date, jcd, race, payload)
    return payload


def normalize_race_list(races):
    normalized = []
    for race in races or range(1, 13):
        try:
            race_number = int(race)
        except (TypeError, ValueError):
            continue
        if 1 <= race_number <= 12 and race_number not in normalized:
            normalized.append(race_number)
    return normalized or list(range(1, 13))


def load_results(date, jcd, races=None, max_workers=RESULT_FETCH_WORKERS, timeout=FETCH_TIMEOUT_SECONDS):
    target_races = normalize_race_list(races)
    cache_key = f"{date}-{jcd}"
    if date <= current_jst_date():
        schedule_pay_refresh(date)
    else:
        try:
            pay_results = load_pay_results(date, timeout=min(timeout, 12)).get(jcd, {})
        except Exception:
            pay_results = {}
        for race in target_races:
            payload = pay_results.get(race)
            if payload:
                store_result_payload(date, jcd, race, payload)
    with results_cache_lock:
        cached = results_cache.get(cache_key)
        if cached:
            cached_results = cached.get("payload", {}).get("results", {})
            fresh_results = {
                str(race): cached_results[str(race)]
                for race in target_races
                if str(race) in cached_results
                and time.time() - cached.get("savedAt", 0) < get_result_cache_seconds(date, cached_results[str(race)])
            }
            if len(fresh_results) == len(target_races):
                return {
                    "date": date,
                    "jcd": jcd,
                    "results": fresh_results,
                }
            results = dict(cached_results)
        else:
            results = {}
    if date == current_jst_date():
        missing = [
            race for race in target_races
            if str(race) not in results
        ]
        for race in missing:
            results[str(race)] = {
                "date": date,
                "jcd": jcd,
                "race": race,
                "available": False,
                "result": None,
                "weather": {"available": False},
                "source": "pending-pay-refresh",
            }
        for race in target_races:
            payload = results.get(str(race))
            if payload and payload.get("available") and not has_payout_type(payload, "2連単"):
                schedule_result_enrich(date, jcd, race)
        return {
            "date": date,
            "jcd": jcd,
            "results": {
                str(race): results[str(race)]
                for race in target_races
                if str(race) in results
            },
            "staleWhileRevalidate": True,
        }
    missing_races = [
        race for race in target_races
        if str(race) not in results
        or not get_cached_result(date, jcd, race)
    ]
    workers = max(1, min(max_workers, len(missing_races) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(load_result, date, jcd, race, timeout): race
            for race in missing_races
        }
        for future in as_completed(futures):
            race = futures[future]
            try:
                results[str(race)] = future.result()
            except Exception as error:
                results[str(race)] = {
                    "date": date,
                    "jcd": jcd,
                    "race": race,
                    "available": False,
                    "result": None,
                    "weather": {"available": False},
                    "error": str(error),
                }
    payload = {
        "date": date,
        "jcd": jcd,
        "results": {
            str(race): results[str(race)]
            for race in target_races
            if str(race) in results
        },
    }
    with results_cache_lock:
        cached = results_cache.get(cache_key, {}).get("payload", {})
        merged_results = dict(cached.get("results", {}))
        merged_results.update(results)
        results_cache[cache_key] = {
            "savedAt": time.time(),
            "payload": {
                "date": date,
                "jcd": jcd,
                "results": merged_results,
            },
        }
    save_results_cache()
    return payload


def load_venues_status(date):
    cached = None
    cached_payload = {}
    with venue_status_cache_lock:
        cached = venue_status_cache.get(date)
        cached_payload = cached.get("payload", {}) if cached else {}
    if (
        cached
        and cached_payload.get("version") == SCHEDULE_CACHE_VERSION
        and time.time() - cached.get("savedAt", 0) < CACHE_SECONDS
    ):
        merged_venues = merge_pay_venue_status(date, cached_payload.get("venues", {}))
        if merged_venues != cached_payload.get("venues", {}):
            payload = dict(cached_payload)
            payload["venues"] = merged_venues
            with venue_status_cache_lock:
                venue_status_cache[date] = {
                    "savedAt": cached.get("savedAt", time.time()),
                    "payload": payload,
                }
            save_schedule_cache()
            return payload
        return cached_payload
    compact_date = date.replace("-", "")
    try:
        index_html = fetch_html(
            f"/owpc/pc/race/index?hd={compact_date}",
            cache_seconds=CACHE_SECONDS,
            timeout=12,
        )
        venues_status = parse_daily_venue_index(index_html, compact_date)
        if venues_status:
            venues_status = merge_pay_venue_status(date, venues_status)
            payload = {
                "date": date,
                "venues": venues_status,
                "source": "daily-index",
                "version": SCHEDULE_CACHE_VERSION,
            }
            with venue_status_cache_lock:
                venue_status_cache[date] = {
                    "savedAt": time.time(),
                    "payload": payload,
                }
            save_schedule_cache()
            return payload
    except Exception:
        pass
    venues_status = {}
    now = time.time()
    with ThreadPoolExecutor(max_workers=VENUE_FALLBACK_WORKERS) as executor:
        futures = {}
        for jcd in BOATRACE_JCDS:
            program_key = f"{date}-{jcd}"
            with program_cache_lock:
                stored = program_cache.get(program_key)
                if stored and now - stored.get("savedAt", 0) < CACHE_SECONDS:
                    payload = stored.get("payload", {})
                    venues_status[jcd] = {
                        "jcd": jcd,
                        "available": bool(payload.get("available")),
                        "races": len(payload.get("races", [])),
                        "cached": True,
                    }
                    continue
            path = f"/owpc/pc/race/raceindex?hd={compact_date}&jcd={jcd}"
            futures[executor.submit(fetch_html, path)] = jcd
        for future in as_completed(futures):
            jcd = futures[future]
            try:
                races = parse_race_index(future.result())
            except Exception:
                races = []
            venues_status[jcd] = {
                "jcd": jcd,
                "available": bool(races),
                "races": len(races),
                "cached": False,
            }
    venues_status = merge_pay_venue_status(date, venues_status)
    payload = {
        "date": date,
        "venues": venues_status,
        "source": "raceindex-fallback",
        "version": SCHEDULE_CACHE_VERSION,
    }
    with venue_status_cache_lock:
        venue_status_cache[date] = {
            "savedAt": time.time(),
            "payload": payload,
        }
    save_schedule_cache()
    return payload


class AppHandler(SimpleHTTPRequestHandler):
    def is_admin_request(self, path):
        return path in ("/admin", "/admin.html", "/admin.js") or path.startswith("/api/admin/")

    def require_admin_auth(self):
        password = os.environ.get("ADMIN_PASSWORD", "boatadmin")
        expected = "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()
        if self.headers.get("Authorization") == expected:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="BOAT PREDICT AI Admin"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Authentication required".encode("utf-8"))
        return False

    def end_headers(self):
        if self.path == "/" or self.path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if self.is_admin_request(parsed.path) and not self.require_admin_auth():
            return
        if parsed.path == "/admin":
            self.path = "/admin.html"
            return super().do_GET()
        if parsed.path == "/api/warmup":
            return self.send_json(get_warmup_status())
        if parsed.path == "/api/learning":
            return self.send_json(get_learning())
        if parsed.path == "/api/admin/backfill-status":
            return self.send_json(get_admin_backfill_status())
        if parsed.path == "/api/admin/backfill":
            query = parse_qs(parsed.query)
            date = query.get("date", [""])[0]
            force = query.get("force", ["0"])[0] == "1"
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                return self.send_json({"error": "invalid parameters"}, 400)
            return self.send_json(schedule_admin_backfill(date, force=force))
        if parsed.path == "/api/admin/backfill-range":
            query = parse_qs(parsed.query)
            from_date = query.get("from", [""])[0]
            to_date = query.get("to", [""])[0]
            force = query.get("force", ["1"])[0] != "0"
            ok, payload = schedule_backfill_range(from_date, to_date, force=force)
            return self.send_json(payload, 200 if ok else 400)
        if parsed.path == "/api/admin/backfill-range/cancel":
            return self.send_json(cancel_backfill_range())
        if parsed.path == "/api/admin/performance":
            query = parse_qs(parsed.query)
            date = query.get("date", [""])[0]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                return self.send_json({"error": "invalid parameters"}, 400)
            return self.send_json(get_admin_performance(date))
        if parsed.path == "/api/result-board":
            query = parse_qs(parsed.query)
            date = query.get("date", [""])[0]
            jcd = query.get("jcd", [""])[0].zfill(2)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"\d{2}", jcd):
                return self.send_json({"error": "invalid parameters"}, 400)
            return self.send_json(build_result_board(date, jcd))
        if parsed.path == "/api/korogashi-month":
            query = parse_qs(parsed.query)
            date = query.get("date", [""])[0]
            jcd = query.get("jcd", [""])[0].zfill(2)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"\d{2}", jcd):
                return self.send_json({"error": "invalid parameters"}, 400)
            return self.send_json(build_korogashi_month(date, jcd))
        if parsed.path == "/sitemap.xml":
            return self.send_xml(build_sitemap_xml(seo_public_origin(self)))
        if parsed.path == "/robots.txt":
            origin = seo_public_origin(self)
            return self.send_text(
                "User-agent: *\n"
                "Allow: /\n"
                "Disallow: /api/\n"
                "Disallow: /admin\n"
                f"Sitemap: {origin}/sitemap.xml\n",
                content_type="text/plain; charset=utf-8",
                cache_control="public, max-age=600",
            )
        seo_match = re.fullmatch(
            r"/boatrace/([a-z]+)(?:/(\d{4}-\d{2}-\d{2})(?:/(\d{1,2})/?)?)?/?",
            parsed.path,
        )
        if seo_match:
            html_text, status = render_seo_page(
                seo_public_origin(self),
                seo_match.group(1),
                seo_match.group(2),
                seo_match.group(3),
            )
            if status == 404:
                return self.send_error(404)
            return self.send_html(html_text, status=status)
        if parsed.path not in ("/api/program", "/api/result", "/api/results", "/api/signals", "/api/venues"):
            return super().do_GET()
        query = parse_qs(parsed.query)
        date = query.get("date", [""])[0]
        jcd = query.get("jcd", [""])[0].zfill(2)
        race = query.get("race", ["1"])[0]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            return self.send_json({"error": "invalid parameters"}, 400)
        if parsed.path == "/api/venues":
            try:
                return self.send_json(load_venues_status(date))
            except Exception as error:
                return self.send_json({"error": str(error)}, 502)
        if not re.fullmatch(r"\d{2}", jcd):
            return self.send_json({"error": "invalid parameters"}, 400)
        if parsed.path != "/api/results" and (
            not race.isdigit() or not 1 <= int(race) <= 12
        ):
            return self.send_json({"error": "invalid parameters"}, 400)
        try:
            if parsed.path == "/api/result":
                allow_live = date != current_jst_date()
                self.send_json(load_result(date, jcd, int(race), include_weather=True, allow_live=allow_live))
            elif parsed.path == "/api/results":
                requested_races = []
                for value in query.get("races", []):
                    requested_races.extend(value.split(","))
                self.send_json(load_results(date, jcd, requested_races))
            elif parsed.path == "/api/signals":
                self.send_json(load_signals(date, jcd, int(race)))
            else:
                self.send_json(load_program(date, jcd, int(race)))
        except Exception as error:
            self.send_json({"error": str(error)}, 502)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/learning":
            return self.send_json({"error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            self.send_json(record_learning_events(payload.get("events", [])))
        except Exception as error:
            self.send_json({"error": str(error)}, 400)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def send_text(self, text, status=200, content_type="text/plain; charset=utf-8", cache_control="no-store"):
        body = (text or "").encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", cache_control)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def send_html(self, html_text, status=200):
        self.send_text(
            html_text,
            status=status,
            content_type="text/html; charset=utf-8",
            cache_control="public, max-age=300",
        )

    def send_xml(self, xml_text, status=200):
        self.send_text(
            xml_text,
            status=status,
            content_type="application/xml; charset=utf-8",
            cache_control="public, max-age=600",
        )


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "4174"))
    server = ThreadingHTTPServer((host, port), AppHandler)
    shutdown_requested = threading.Event()

    def graceful_shutdown(signum, frame):
        if shutdown_requested.is_set():
            return
        shutdown_requested.set()
        try:
            flush_dirty_caches_once()
        finally:
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        local_ip = "このMacのWi-Fi IP"
    print(f"BOAT PREDICT AI: http://127.0.0.1:{port}/")
    print(f"SMARTPHONE URL: http://{local_ip}:{port}/")
    schedule_cache_flush_worker()
    if os.environ.get("BOAT_HTML_CACHE_CLEANUP", "1") != "0":
        schedule_html_cache_cleanup_worker()
    if os.environ.get("BOAT_STARTUP_WARMUP", "1") != "0":
        schedule_startup_warmup()
    if os.environ.get("BOAT_RESULT_WARMER", "1") != "0":
        schedule_background_data_sync()
        schedule_result_warmer()
    if os.environ.get("BOAT_PAY_WARMER", "1") != "0":
        schedule_pay_warmer()
    if os.environ.get("BOAT_AUTO_BACKFILL", "1") != "0":
        schedule_admin_auto_backfill()
    resume_backfill_range_on_startup()
    try:
        server.serve_forever()
    finally:
        flush_dirty_caches_once()
