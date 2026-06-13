#!/usr/bin/env python3
import json
import hashlib
import os
import re
import threading
import time
import socket
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
CACHE_DIR = Path(__file__).with_name(".official-cache")
PROGRAM_CACHE_FILE = CACHE_DIR / "programs.json"
JST = timezone(timedelta(hours=9))
BOATRACE_JCDS = [f"{number:02d}" for number in range(1, 25)]
cache = {}
fetch_locks = {}
fetch_locks_guard = threading.Lock()
program_cache_lock = threading.Lock()
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


def read_program_cache():
    try:
        return json.loads(PROGRAM_CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


program_cache = read_program_cache()


def save_program_cache():
    CACHE_DIR.mkdir(exist_ok=True)
    temporary = PROGRAM_CACHE_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(program_cache, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(PROGRAM_CACHE_FILE)


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
    update_warmup_status(
        active=True,
        date=date,
        currentJcd="",
        completedVenues=0,
        completedRaces=count_cached_detailed_races(date),
        startedAt=datetime.now(JST).isoformat(timespec="seconds"),
        finishedAt=None,
    )
    def progress(current_jcd, _race):
        update_warmup_status(
            currentJcd=current_jcd,
            completedRaces=count_cached_detailed_races(date),
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(warm_program_races, date, jcd, progress): jcd
            for jcd in BOATRACE_JCDS
        }
        completed = 0
        for future in as_completed(futures):
            completed += 1
            try:
                future.result()
            except Exception:
                pass
            update_warmup_status(
                currentJcd=futures[future],
                completedVenues=completed,
                completedRaces=count_cached_detailed_races(date),
            )
    update_warmup_status(
        active=False,
        currentJcd="",
        completedVenues=len(BOATRACE_JCDS),
        completedRaces=count_cached_detailed_races(date),
        finishedAt=datetime.now(JST).isoformat(timespec="seconds"),
    )


def get_fetch_lock(path):
    with fetch_locks_guard:
        return fetch_locks.setdefault(path, threading.Lock())


def fetch_html(path, cache_seconds=CACHE_SECONDS):
    cached = cache.get(path)
    if cached and time.time() - cached[0] < cache_seconds:
        return cached[1]
    with get_fetch_lock(path):
        cached = cache.get(path)
        if cached and time.time() - cached[0] < cache_seconds:
            return cached[1]
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file = CACHE_DIR / f"{hashlib.sha256(path.encode()).hexdigest()}.html"
        stale_text = None
        if cache_file.exists():
            stale_text = cache_file.read_text(encoding="utf-8")
            if time.time() - cache_file.stat().st_mtime < cache_seconds:
                cache[path] = (time.time(), stale_text)
                return stale_text
        request = Request(f"{OFFICIAL_BASE}{path}", headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=12) as response:
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


def load_signals(date, jcd, race):
    compact_date = date.replace("-", "")
    paths = {
        "expect": (f"/owpc/pc/race/pcexpect?rno={race}&jcd={jcd}&hd={compact_date}", 600),
        "beforeinfo": (f"/owpc/pc/race/beforeinfo?rno={race}&jcd={jcd}&hd={compact_date}", 45),
        "odds": (f"/owpc/pc/race/odds3t?rno={race}&jcd={jcd}&hd={compact_date}", 300),
    }
    html = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            name: executor.submit(fetch_html, path, cache_seconds)
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
    with program_cache_lock:
        stored = program_cache.get(program_key)
        if stored and time.time() - stored.get("savedAt", 0) < CACHE_SECONDS:
            if not stored["payload"].get("available"):
                return stored["payload"]
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

    compact_date = date.replace("-", "")
    detail_path = (
        f"/owpc/pc/race/racelist?rno={selected_race}"
        f"&jcd={jcd}&hd={compact_date}"
    )
    if recent_payload and recent_payload.get("races"):
        races = [dict(race) for race in recent_payload["races"]]
        try:
            detail_html = fetch_html(detail_path)
        except Exception:
            detail_html = ""
    else:
        index_path = f"/owpc/pc/race/raceindex?hd={compact_date}&jcd={jcd}"
        with ThreadPoolExecutor(max_workers=2) as executor:
            index_future = executor.submit(fetch_html, index_path)
            detail_future = executor.submit(fetch_html, detail_path)
            index_html = index_future.result()
            try:
                detail_html = detail_future.result()
            except Exception:
                detail_html = ""
        races = parse_race_index(index_html)
    if not races:
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


def load_result(date, jcd, race):
    compact_date = date.replace("-", "")
    path = f"/owpc/pc/race/raceresult?rno={race}&jcd={jcd}&hd={compact_date}"
    result_cache_seconds = CACHE_SECONDS if date < current_jst_date() else 60
    html_text = fetch_html(path, cache_seconds=result_cache_seconds)
    result = parse_result(html_text)
    weather = parse_weather(html_text)
    return {
        "date": date,
        "jcd": jcd,
        "race": race,
        "available": result is not None,
        "result": result,
        "weather": weather,
    }


def load_results(date, jcd):
    results = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(load_result, date, jcd, race): race
            for race in range(1, 13)
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
    return {
        "date": date,
        "jcd": jcd,
        "results": results,
    }


class AppHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path == "/" or self.path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/warmup":
            return self.send_json(get_warmup_status())
        if parsed.path not in ("/api/program", "/api/result", "/api/results", "/api/signals"):
            return super().do_GET()
        query = parse_qs(parsed.query)
        date = query.get("date", [""])[0]
        jcd = query.get("jcd", [""])[0].zfill(2)
        race = query.get("race", ["1"])[0]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"\d{2}", jcd):
            return self.send_json({"error": "invalid parameters"}, 400)
        if parsed.path != "/api/results" and (
            not race.isdigit() or not 1 <= int(race) <= 12
        ):
            return self.send_json({"error": "invalid parameters"}, 400)
        try:
            if parsed.path == "/api/result":
                self.send_json(load_result(date, jcd, int(race)))
            elif parsed.path == "/api/results":
                self.send_json(load_results(date, jcd))
            elif parsed.path == "/api/signals":
                self.send_json(load_signals(date, jcd, int(race)))
            else:
                self.send_json(load_program(date, jcd, int(race)))
        except Exception as error:
            self.send_json({"error": str(error)}, 502)

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
    server.serve_forever()
