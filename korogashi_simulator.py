#!/usr/bin/env python3
"""BOAT PREDICT AI - コロガシ・シミュレータ（プレイマネー）。"""
import argparse
import csv
import json
import os
import sys
from collections import Counter


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
            if normalized.lstrip("-").isdigit():
                parts.append(str(int(normalized)))
    return "-".join(parts)


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_events(path):
    with open(path, encoding="utf-8") as handle:
        store = json.load(handle)
    events = store.get("events", {})
    if isinstance(events, dict):
        return [event for event in events.values() if isinstance(event, dict)]
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]
    return []


def order_events(events, venue=None, date_from=None, date_to=None, source=None):
    filtered = []
    for event in events:
        date = event.get("date") or ""
        if date_from and date < date_from:
            continue
        if date_to and date > date_to:
            continue
        if venue and event.get("venue") != venue:
            continue
        event_source = event.get("source") or (
            "server-backfill" if event.get("phase") == "server-backfill" else "prediction-screen"
        )
        if source and event_source != source:
            continue
        if not normalize_ticket(event.get("result")):
            continue
        filtered.append(event)
    if venue:
        return sorted(filtered, key=lambda item: (item.get("date") or "", int(item.get("race") or 0)))
    return sorted(filtered, key=lambda item: (item.get("date") or "", int(item.get("race") or 0), item.get("venue") or ""))


def pick_score(pick, field):
    return safe_float(pick.get(field), -1.0)


def select_ticket(event, mode):
    picks = event.get("picks") if isinstance(event.get("picks"), list) else []
    strategy = "honmei" if mode == "honmei1" else mode
    candidates = [
        pick for pick in picks
        if isinstance(pick, dict)
        and pick.get("strategyKey") == strategy
        and normalize_ticket(pick.get("ticket"))
    ]
    if not candidates:
        return None
    if mode == "honmei1":
        indexed = [
            pick for pick in candidates
            if int(safe_float(pick.get("strategyIndex"), -1)) == 0
        ]
        if indexed:
            return indexed[0]
    return sorted(
        candidates,
        key=lambda pick: (
            -pick_score(pick, "valueScore"),
            -pick_score(pick, "probability"),
            safe_float(pick.get("strategyIndex"), 99),
            normalize_ticket(pick.get("ticket")),
        ),
    )[0]


def race_outcome(event, pick):
    ticket_key = normalize_ticket(pick.get("ticket") if isinstance(pick, dict) else None)
    result_key = normalize_ticket((event.get("result") or [])[:3])
    payout = int(safe_float(event.get("payout"), 0))
    if not ticket_key or not result_key or payout <= 0:
        return None
    return {
        "ticket": ticket_key,
        "result": result_key,
        "payout": payout,
        "hit": ticket_key == result_key,
    }


def is_miokuri(event):
    decision = event.get("betDecision") or {}
    return decision.get("buy") is False or decision.get("key") == "miokuri"


def yen(value):
    return f"{round(value):,}円"


def pct(value):
    return f"{value:.1f}%"


def bar(count, max_count):
    if count <= 0 or max_count <= 0:
        return ""
    width = max(1, round(count / max_count * 18))
    return "█" * width


def start_run(run_id, bankroll, start_event=None):
    return {
        "id": run_id,
        "start": bankroll,
        "balance": float(bankroll),
        "legs": 0,
        "bets": 0,
        "peak": float(bankroll),
        "peakEvent": start_event,
        "status": "running",
        "endEvent": None,
    }


def close_run(run, status, event=None):
    run["status"] = status
    run["endEvent"] = event
    return dict(run)


def simulate(ordered_events, *, bankroll, ticket, skip_miokuri, max_legs, mode):
    run_id = 0
    balance = 0.0
    current = None
    runs = []
    bet_log = []
    total_invested = 0.0
    skipped = Counter()

    def ensure_run(event):
        nonlocal run_id, balance, current, total_invested
        if current is not None:
            return
        run_id += 1
        balance = float(bankroll)
        total_invested += bankroll
        current = start_run(run_id, bankroll, event)

    def finish_run(status, event):
        nonlocal balance, current
        if current is None:
            return True
        runs.append(close_run(current, status, event))
        current = None
        balance = 0.0
        if mode == "oneshot":
            return False
        return True

    for event in ordered_events:
        if skip_miokuri and is_miokuri(event):
            skipped["miokuri"] += 1
            continue
        pick = select_ticket(event, ticket)
        if not pick:
            skipped["no_pick"] += 1
            continue
        outcome = race_outcome(event, pick)
        if not outcome:
            skipped["invalid_result"] += 1
            continue

        ensure_run(event)
        bet = (int(balance) // 100) * 100
        if bet < 100:
            if not finish_run("bust", event):
                break
            continue

        remainder = balance - bet
        before = balance
        hit = outcome["hit"]
        if hit:
            balance = remainder + bet * (outcome["payout"] / 100.0)
            current["legs"] += 1
        else:
            balance = remainder

        current["balance"] = balance
        current["bets"] += 1
        if balance > current["peak"]:
            current["peak"] = balance
            current["peakEvent"] = event

        bet_log.append({
            "run_id": current["id"],
            "date": event.get("date"),
            "venue": event.get("venue"),
            "race": event.get("race"),
            "ticket": outcome["ticket"],
            "result": outcome["result"],
            "payout": outcome["payout"],
            "bet": bet,
            "hit": hit,
            "balance_before": before,
            "balance_after": balance,
            "leg": current["legs"],
        })

        if hit and max_legs and current["legs"] >= max_legs:
            if not finish_run("take_profit", event):
                break
            continue

        if not hit and balance < 100:
            if not finish_run("bust", event):
                break

    else:
        if current is not None and current.get("bets", 0) > 0:
            runs.append(close_run(current, "survived", ordered_events[-1] if ordered_events else None))

    if mode == "oneshot" and runs and runs[-1]["status"] in ("bust", "take_profit"):
        total_returned = runs[-1]["balance"]
    else:
        total_returned = sum(run["balance"] for run in runs if run["status"] in ("take_profit", "survived"))

    return {
        "events": ordered_events,
        "runs": runs,
        "betLog": bet_log,
        "skipped": skipped,
        "totalInvested": total_invested,
        "totalReturned": total_returned,
        "net": total_returned - total_invested,
        "finalBalance": runs[-1]["balance"] if runs else bankroll,
    }


def group_by_date(events):
    grouped = {}
    for event in events:
        grouped.setdefault(event.get("date") or "", []).append(event)
    return [(date, grouped[date]) for date in sorted(grouped)]


def simulate_daily_challenge(ordered_events, *, bankroll, ticket, skip_miokuri, max_legs):
    all_runs = []
    all_bets = []
    skipped = Counter()
    daily_rows = []
    run_offset = 0
    for date, day_events in group_by_date(ordered_events):
        day_stats = simulate(
            day_events,
            bankroll=bankroll,
            ticket=ticket,
            skip_miokuri=skip_miokuri,
            max_legs=max_legs,
            mode="oneshot",
        )
        skipped.update(day_stats["skipped"])
        for run in day_stats["runs"]:
            run["day"] = date
            run["id"] += run_offset
            all_runs.append(run)
        for bet in day_stats["betLog"]:
            bet = dict(bet)
            bet["run_id"] += run_offset
            all_bets.append(bet)
        run_offset += len(day_stats["runs"])
        run = day_stats["runs"][-1] if day_stats["runs"] else start_run(0, bankroll)
        daily_rows.append({
            "date": date,
            "status": run.get("status"),
            "bets": run.get("bets", 0),
            "legs": run.get("legs", 0),
            "peak": run.get("peak", bankroll),
            "balance": run.get("balance", bankroll),
            "peakEvent": run.get("peakEvent"),
        })
    total_invested = bankroll * len([row for row in daily_rows if row["bets"] > 0])
    total_returned = sum(row["balance"] for row in daily_rows if row["status"] in ("take_profit", "survived"))
    return {
        "events": ordered_events,
        "runs": all_runs,
        "betLog": all_bets,
        "skipped": skipped,
        "dailyRows": daily_rows,
        "totalInvested": total_invested,
        "totalReturned": total_returned,
        "net": total_returned - total_invested,
        "finalBalance": daily_rows[-1]["balance"] if daily_rows else bankroll,
    }


def event_label(event):
    if not event:
        return "-"
    return f"{event.get('date')} {event.get('venue')} {event.get('race')}R"


def render_settings(events, args):
    dates = [event.get("date") for event in events if event.get("date")]
    print("=" * 72)
    print(" 1. 設定")
    print("=" * 72)
    print(f"  元手                 : {yen(args.bankroll)}")
    print(f"  買い目               : {args.ticket}")
    print(f"  チャレンジ           : {args.challenge}")
    print(f"  内部モード           : {args.mode}")
    print(f"  見送り除外           : {'ON' if args.skip_miokuri else 'OFF'}")
    print(f"  利確段数             : {args.max_legs if args.max_legs else '無制限'}")
    print(f"  会場                 : {args.venue or '全会場'}")
    print(f"  期間                 : {(min(dates) if dates else '-') } 〜 {(max(dates) if dates else '-')}")
    print(f"  対象レース数         : {len(events)}")
    print()


def render_restart_report(stats, args):
    runs = stats["runs"]
    busts = [run for run in runs if run["status"] == "bust"]
    profits = [run for run in runs if run["status"] == "take_profit"]
    survived = [run for run in runs if run["status"] == "survived"]
    max_peak_run = max(runs, key=lambda run: run["peak"], default=None)
    max_legs_run = max(runs, key=lambda run: run["legs"], default=None)
    roi = (stats["totalReturned"] / stats["totalInvested"] * 100) if stats["totalInvested"] else 0

    print("=" * 72)
    print(" 2. サマリー")
    print("=" * 72)
    print(f"  チャレンジ回数       : {len(runs)}")
    print(f"  バスト回数           : {len(busts)}")
    print(f"  利確回数             : {len(profits)}")
    print(f"  期間終了で生存       : {len(survived)}")
    print(f"  累計投入額           : {yen(stats['totalInvested'])}")
    print(f"  累計回収額           : {yen(stats['totalReturned'])}")
    print(f"  月間収支             : {yen(stats['net'])}")
    print(f"  回収率               : {pct(roi)}")
    print(f"  最終残高             : {yen(stats['finalBalance'])}")
    if max_peak_run:
        print(f"  最高到達額           : {yen(max_peak_run['peak'])} / {event_label(max_peak_run.get('peakEvent'))}")
    if max_legs_run:
        print(f"  最高連勝             : {max_legs_run['legs']}連勝 / {event_label(max_legs_run.get('peakEvent'))}")
    print()

    if stats.get("dailyRows"):
        print("=" * 72)
        print(" 3. 日別チャレンジ結果")
        print("=" * 72)
        print("  日付         状態          賭け数  連勝  最高到達額      最終残高")
        print("  ----------   ----------    ------  ----  ------------    ----------")
        for row in stats["dailyRows"]:
            print("  {:<10}   {:<10}    {:>6}  {:>4}  {:>12}    {:>10}".format(
                row["date"],
                row["status"],
                row["bets"],
                row["legs"],
                yen(row["peak"]),
                yen(row["balance"]),
            ))
        print()

    print("=" * 72)
    print(" 4. 連勝段数の分布")
    print("=" * 72)
    distribution = Counter(run["legs"] for run in runs)
    max_count = max(distribution.values(), default=0)
    for legs in sorted(distribution):
        label = f"{legs}連勝"
        print(f"  {label:<8} : {bar(distribution[legs], max_count):<18} {distribution[legs]}回")
    print()


def render_oneshot_report(stats):
    runs = stats["runs"]
    run = runs[-1] if runs else start_run(1, 0)
    bust_event = run.get("endEvent") if run.get("status") == "bust" else None
    print("=" * 72)
    print(" 2. 結果")
    print("=" * 72)
    print(f"  状態                 : {run.get('status')}")
    print(f"  賭けたレース数       : {run.get('bets', 0)}")
    print(f"  連勝段数             : {run.get('legs', 0)}")
    print(f"  ピーク残高           : {yen(run.get('peak', 0))} / {event_label(run.get('peakEvent'))}")
    print(f"  最終残高             : {yen(run.get('balance', 0))}")
    if bust_event:
        print(f"  バスト地点           : {event_label(bust_event)}")
    print()


def render_notes():
    print("=" * 72)
    print(" 読み方メモ")
    print("=" * 72)
    print("  ・コロガシは1回でも外すと賭け金が消える、的中率依存の強い遊び方です。")
    print("  ・このシミュレーションはプレイマネー前提です。リアル資金の購入導線ではありません。")
    print("  ・現状モデルが-EVの場合、すぐ飛ぶ結果が多く出るのは想定どおりです。")
    print("  ・見送り除外ON/OFFや本命/狙い目/穴を切り替えると、ゲーム性の違いを比較できます。")
    print()


def render_report(stats, args):
    render_settings(stats["events"], args)
    if args.challenge in ("daily", "restart"):
        render_restart_report(stats, args)
    else:
        render_oneshot_report(stats)
    if stats["skipped"]:
        print("  スキップ内訳         : " + " / ".join(f"{key}:{value}" for key, value in sorted(stats["skipped"].items())))
        print()
    render_notes()


def write_csv(bet_log, path):
    fields = [
        "run_id", "date", "venue", "race", "ticket", "result", "payout",
        "bet", "hit", "balance_before", "balance_after", "leg",
    ]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in bet_log:
            writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="BOAT PREDICT AI コロガシ・シミュレータ")
    parser.add_argument("path", nargs="?", default=os.environ.get("BOAT_LEARNING_PATH", "learning.json"))
    parser.add_argument("--bankroll", type=int, default=1000)
    parser.add_argument("--ticket", choices=["honmei1", "nerai", "ana"], default="honmei1")
    parser.add_argument("--mode", choices=["restart", "oneshot"], default="restart")
    parser.add_argument(
        "--challenge",
        choices=["daily", "survival", "restart"],
        default="daily",
        help="daily=毎日元手リセット / survival=月間持ち越し / restart=飛ぶたび元手リセット",
    )
    parser.add_argument("--max-legs", type=int, default=0)
    parser.add_argument("--skip-miokuri", dest="skip_miokuri", action="store_true", default=True)
    parser.add_argument("--no-skip-miokuri", dest="skip_miokuri", action="store_false")
    parser.add_argument("--venue")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--source", choices=["prediction-screen", "server-backfill"])
    parser.add_argument("--csv")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        sys.exit(f"learning.json が見つかりません: {args.path}")
    if args.bankroll < 100:
        sys.exit("--bankroll は100円以上にしてください。")
    if args.max_legs < 0:
        sys.exit("--max-legs は0以上にしてください。")

    events = order_events(
        load_events(args.path),
        venue=args.venue,
        date_from=args.date_from,
        date_to=args.date_to,
        source=args.source,
    )
    if not events:
        sys.exit("対象レースがありません。期間・会場・source・learning.json を確認してください。")

    if args.challenge == "daily":
        args.mode = "oneshot"
        stats = simulate_daily_challenge(
            events,
            bankroll=args.bankroll,
            ticket=args.ticket,
            skip_miokuri=args.skip_miokuri,
            max_legs=args.max_legs,
        )
    elif args.challenge == "survival":
        args.mode = "oneshot"
        stats = simulate(
            events,
            bankroll=args.bankroll,
            ticket=args.ticket,
            skip_miokuri=args.skip_miokuri,
            max_legs=args.max_legs,
            mode="oneshot",
        )
    else:
        args.mode = "restart"
        stats = simulate(
            events,
            bankroll=args.bankroll,
            ticket=args.ticket,
            skip_miokuri=args.skip_miokuri,
            max_legs=args.max_legs,
            mode="restart",
        )
    render_report(stats, args)
    if args.csv:
        write_csv(stats["betLog"], args.csv)
        print(f"CSVを書き出しました: {args.csv}")


if __name__ == "__main__":
    main()
