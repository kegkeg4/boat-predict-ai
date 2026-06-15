#!/usr/bin/env python3
import base64
import json
import hashlib
import os
import re
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
DETAIL_FETCH_TIMEOUT_SECONDS = float(os.environ.get("BOAT_DETAIL_FETCH_TIMEOUT", "3"))
ADMIN_BACKFILL_WORKERS = int(os.environ.get("BOAT_ADMIN_BACKFILL_WORKERS", "4"))
ADMIN_BACKFILL_RESULT_TIMEOUT = float(os.environ.get("BOAT_ADMIN_RESULT_TIMEOUT", "16"))
ADMIN_BACKFILL_SIGNAL_TIMEOUT = float(os.environ.get("BOAT_ADMIN_SIGNAL_TIMEOUT", "2"))
BACKGROUND_SYNC_INTERVAL_SECONDS = int(os.environ.get("BOAT_BACKGROUND_SYNC_INTERVAL", "1800"))
CACHE_DIR = Path(os.environ.get("BOAT_DATA_DIR", Path(__file__).with_name(".official-cache")))
PROGRAM_CACHE_FILE = CACHE_DIR / "programs.json"
SCHEDULE_CACHE_FILE = CACHE_DIR / "schedules.json"
RESULTS_CACHE_FILE = CACHE_DIR / "results.json"
LEARNING_FILE = CACHE_DIR / "learning.json"
SCHEDULE_CACHE_VERSION = 2
JST = timezone(timedelta(hours=9))
BOATRACE_JCDS = [f"{number:02d}" for number in range(1, 25)]
VENUE_NAMES = [
    "桐生", "戸田", "江戸川", "平和島", "多摩川", "浜名湖",
    "蒲郡", "常滑", "津", "三国", "びわこ", "住之江",
    "尼崎", "鳴門", "丸亀", "児島", "宮島", "徳山",
    "下関", "若松", "芦屋", "福岡", "唐津", "大村",
]
cache = {}
fetch_locks = {}
fetch_locks_guard = threading.Lock()
program_cache_lock = threading.Lock()
venue_status_cache_lock = threading.Lock()
venue_status_cache = {}
results_cache_lock = threading.Lock()
results_cache = {}
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
admin_backfill_lock = threading.Lock()
admin_backfill_status = {
    "active": False,
    "date": None,
    "startedAt": None,
    "finishedAt": None,
    "currentVenue": "",
    "completedVenues": 0,
    "totalVenues": 0,
    "savedEvents": 0,
    "message": "待機中",
}
admin_backfill_done = set()


def read_learning_store():
    try:
        return json.loads(LEARNING_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"events": {}, "weights": {}, "updatedAt": None}


def save_learning_store(store):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = LEARNING_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    temporary.replace(LEARNING_FILE)


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
                if incoming_source == "server-backfill":
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
    return "-".join(str(int(value)) for value in ticket if isinstance(value, (int, float)))


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
                "net": 0,
            },
        )
        row["races"] += 1
        totals["races"] += 1
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
    solid = sorted(tickets, key=lambda item: (-item["baseScore"], item["ticket"]))[:5]
    solid_keys = {tuple(item["ticket"]) for item in solid}
    value_candidates = [item for item in tickets if tuple(item["ticket"]) not in solid_keys]
    nerai = sorted(value_candidates, key=lambda item: (-item["valueScore"], item["ticket"]))[:1]
    used_keys = solid_keys | {tuple(item["ticket"]) for item in nerai}
    ana_candidates = [
        item for item in tickets
        if tuple(item["ticket"]) not in used_keys
        and (item["actualOdds"] or 0) >= 30
    ] or [item for item in tickets if tuple(item["ticket"]) not in used_keys]
    ana = sorted(ana_candidates, key=lambda item: (-(item["actualOdds"] or 0), -item["valueScore"], item["ticket"]))[:1]
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
                "strategyKey": strategy_key,
                "strategyLabel": strategy_label,
                "strategyIndex": index,
            })
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
    result_payload = load_result(date, jcd, race, timeout=result_timeout)
    if not result_payload.get("available"):
        return None
    signals = load_signals(date, jcd, race, timeout=signal_timeout)
    picks = build_server_prediction_picks(racers, signals)
    if not picks:
        return None
    venue = VENUE_NAMES[int(jcd) - 1]
    result = result_payload.get("result") or {}
    result_key = normalize_ticket(result.get("result"))
    hit_index = next(
        (index for index, pick in enumerate(picks) if normalize_ticket(pick.get("ticket")) == result_key),
        -1,
    )
    exacta_hit = any(
        len(pick.get("ticket") or []) >= 2
        and pick["ticket"][0] == result["result"][0]
        and pick["ticket"][1] == result["result"][1]
        for pick in picks
    )
    leader_hit = any(
        pick.get("ticket") and pick["ticket"][0] == result["result"][0]
        for pick in picks
    )
    weather = ((signals.get("beforeinfo") or {}).get("weather") or result_payload.get("weather") or {})
    return {
        "key": f"{date}-{venue}-{race}",
        "date": date,
        "venue": venue,
        "race": race,
        "result": result["result"],
        "payout": result["payout"],
        "picks": picks,
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


def run_admin_backfill(date):
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
                if f"{date}-{venue}-{race}" not in existing_keys
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
                    max_workers=2,
                    timeout=ADMIN_BACKFILL_RESULT_TIMEOUT,
                )
            except Exception:
                pass
            workers = max(1, min(ADMIN_BACKFILL_WORKERS, len(race_numbers)))
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


def schedule_admin_backfill(date, force=False):
    with admin_backfill_lock:
        if admin_backfill_status.get("active"):
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
    thread = threading.Thread(target=run_admin_backfill, args=(date,), daemon=True)
    thread.start()
    return get_admin_backfill_status()


def admin_auto_backfill_worker():
    while True:
        now = datetime.now(JST)
        target = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        if now.hour >= 2 and target not in admin_backfill_done:
            schedule_admin_backfill(target)
        time.sleep(1800)


def schedule_admin_auto_backfill():
    thread = threading.Thread(target=admin_auto_backfill_worker, daemon=True)
    thread.start()


def read_program_cache():
    try:
        return json.loads(PROGRAM_CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


program_cache = read_program_cache()


def save_program_cache():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = PROGRAM_CACHE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(program_cache, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(PROGRAM_CACHE_FILE)


def read_schedule_cache():
    try:
        return json.loads(SCHEDULE_CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_schedule_cache():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SCHEDULE_CACHE_FILE.with_suffix(".tmp")
    with venue_status_cache_lock:
        snapshot = dict(venue_status_cache)
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    temporary.replace(SCHEDULE_CACHE_FILE)


venue_status_cache.update(read_schedule_cache())


def read_results_cache():
    try:
        return json.loads(RESULTS_CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_results_cache():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = RESULTS_CACHE_FILE.with_suffix(".tmp")
    with results_cache_lock:
        snapshot = dict(results_cache)
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        temporary.replace(RESULTS_CACHE_FILE)


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
    save_results_cache()


results_cache.update(read_results_cache())


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
        except Exception:
            pass
        time.sleep(0.6)


def result_warmer_worker():
    while True:
        for offset in (-1, 0):
            warm_completed_results_once(jst_date_offset(offset))
        time.sleep(BACKGROUND_SYNC_INTERVAL_SECONDS)


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
                load_program(target_date, jcd, 1, should_prefetch=False)
            except Exception:
                pass
            time.sleep(0.2)


def background_data_sync_worker():
    while True:
        background_data_sync_once()
        time.sleep(BACKGROUND_SYNC_INTERVAL_SECONDS)


def schedule_background_data_sync():
    thread = threading.Thread(target=background_data_sync_worker, daemon=True)
    thread.start()


def schedule_result_warmer():
    thread = threading.Thread(target=result_warmer_worker, daemon=True)
    thread.start()


def get_fetch_lock(path):
    with fetch_locks_guard:
        return fetch_locks.setdefault(path, threading.Lock())


def fetch_html(path, cache_seconds=CACHE_SECONDS, timeout=FETCH_TIMEOUT_SECONDS):
    cached = cache.get(path)
    if cached and time.time() - cached[0] < cache_seconds:
        return cached[1]
    with get_fetch_lock(path):
        cached = cache.get(path)
        if cached and time.time() - cached[0] < cache_seconds:
            return cached[1]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{hashlib.sha256(path.encode()).hexdigest()}.html"
        stale_text = None
        if cache_file.exists():
            stale_text = cache_file.read_text(encoding="utf-8")
            if time.time() - cache_file.stat().st_mtime < cache_seconds:
                cache[path] = (time.time(), stale_text)
                return stale_text
        request = Request(f"{OFFICIAL_BASE}{path}", headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=timeout) as response:
                text = response.read().decode("utf-8", errors="replace")
        except Exception:
            if stale_text:
                cache[path] = (time.time(), stale_text)
                return stale_text
            raise
        cache[path] = (time.time(), text)
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


def merge_pay_venue_status(date, venues_status):
    if date > current_jst_date():
        return venues_status
    try:
        pay_results = load_pay_results(date, timeout=min(FETCH_TIMEOUT_SECONDS, 8))
    except Exception:
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


def get_pay_result(date, jcd, race, timeout=FETCH_TIMEOUT_SECONDS):
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
    start = html_text.find('<div class="weather1">')
    if start < 0:
        return {"available": False}
    end = html_text.find('<div class="weather1_stand">', start)
    block = html_text[start:end if end >= 0 else start + 5000]
    observed_match = re.search(r"水面気象情報\s*([0-9:]+)現在", strip_tags(block))
    direction_match = re.search(r"is-direction(\d+)", block)
    weather_match = re.search(
        r'is-weather">.*?weather1_bodyUnitLabelTitle">([^<]+)</span>',
        block,
        re.S,
    )
    wind_match = re.search(
        r'is-wind">.*?weather1_bodyUnitLabelData">([^<]+)</span>',
        block,
        re.S,
    )
    temperature_match = re.search(
        r'is-direction">.*?weather1_bodyUnitLabelData">([^<]+)</span>',
        block,
        re.S,
    )
    water_temperature_match = re.search(
        r'is-waterTemperature">.*?weather1_bodyUnitLabelData">([^<]+)</span>',
        block,
        re.S,
    )
    wave_match = re.search(
        r'is-wave">.*?weather1_bodyUnitLabelData">([^<]+)</span>',
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
    return {
        "date": date,
        "jcd": jcd,
        "race": race,
        "expect": parse_pcexpect(html["expect"]) if html["expect"] else {"available": False},
        "beforeinfo": parse_beforeinfo(html["beforeinfo"]) if html["beforeinfo"] else {"available": False, "racers": {}},
        "odds": parse_odds3t(html["odds"]) if html["odds"] else {"available": False, "odds": {}, "firstPopularity": []},
    }


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
                if stored_age < 60:
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
            index_future = executor.submit(fetch_html, index_path)
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
            races = parse_race_index(fetch_html(index_path, cache_seconds=0, timeout=FETCH_TIMEOUT_SECONDS))
        except Exception:
            races = []
    if not races:
        if stale_payload and stale_payload.get("available"):
            return stale_payload
        payload = {"date": date, "jcd": jcd, "available": False, "races": []}
        with program_cache_lock:
            program_cache[program_key] = {
                "savedAt": time.time(),
                "payload": payload,
            }
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
        save_program_cache()
    if should_prefetch:
        schedule_program_prefetch(date, jcd)
    return payload


def load_result(date, jcd, race, timeout=FETCH_TIMEOUT_SECONDS):
    cached = get_cached_result(date, jcd, race)
    if cached:
        return cached
    pay_payload = get_pay_result(date, jcd, race, timeout=min(timeout, 12))
    if pay_payload:
        return pay_payload
    compact_date = date.replace("-", "")
    path = f"/owpc/pc/race/raceresult?rno={race}&jcd={jcd}&hd={compact_date}"
    result_cache_seconds = CACHE_SECONDS if date < current_jst_date() else 60
    html_text = fetch_html(path, cache_seconds=result_cache_seconds, timeout=timeout)
    result = parse_result(html_text)
    weather = parse_weather(html_text)
    payouts = parse_payouts(html_text)
    payload = {
        "date": date,
        "jcd": jcd,
        "race": race,
        "available": result is not None,
        "result": result,
        "weather": weather,
        "payouts": payouts,
    }
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


def load_results(date, jcd, races=None, max_workers=6, timeout=FETCH_TIMEOUT_SECONDS):
    target_races = normalize_race_list(races)
    cache_key = f"{date}-{jcd}"
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
    with ThreadPoolExecutor(max_workers=10) as executor:
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
        if parsed.path == "/api/admin/performance":
            query = parse_qs(parsed.query)
            date = query.get("date", [""])[0]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                return self.send_json({"error": "invalid parameters"}, 400)
            return self.send_json(get_admin_performance(date))
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
                self.send_json(load_result(date, jcd, int(race)))
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


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "4174"))
    server = ThreadingHTTPServer((host, port), AppHandler)
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        local_ip = "このMacのWi-Fi IP"
    print(f"BOAT PREDICT AI: http://127.0.0.1:{port}/")
    print(f"SMARTPHONE URL: http://{local_ip}:{port}/")
    if os.environ.get("BOAT_STARTUP_WARMUP", "1") != "0":
        schedule_startup_warmup()
    if os.environ.get("BOAT_RESULT_WARMER", "1") != "0":
        schedule_background_data_sync()
    if os.environ.get("BOAT_AUTO_BACKFILL", "1") != "0":
        schedule_admin_auto_backfill()
    server.serve_forever()
