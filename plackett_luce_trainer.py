#!/usr/bin/env python3
"""
BOAT PREDICT AI - Plackett-Luce trainer

learning.json に保存された racers 特徴量だけを使い、3連単の着順確率を
Plackett-Luce 形式で学習します。公式オッズは特徴量に入れません。

目的:
  1. オッズ無しの独立シグナルに判別力があるかを見る
  2. 学習済みモデルの AUC / 結果順位 / topN 的中率を確認する
  3. 公式オッズが保存されている場合だけ、市場AUCと比較する

使い方:
  python3 plackett_luce_trainer.py .official-cache/learning.json
  python3 plackett_luce_trainer.py /var/data/boat-predict/learning.json --epochs 200
"""
import argparse
import json
import math
import os
import random
import sys
from collections import defaultdict
from itertools import permutations


GRADE_SCORE = {"A1": 3.0, "A2": 2.0, "B1": 1.0, "B2": 0.0}
FEATURES = [
    "bias",
    "boat1",
    "boat2",
    "boat3",
    "boat4",
    "boat5",
    "boat6",
    "grade",
    "start",
    "national",
    "local",
    "motor",
    "exhibition",
    "wind",
    "wave",
]
FEATURE_SETS = {
    "lane": ["bias", "boat1", "boat2", "boat3", "boat4", "boat5", "boat6"],
    "skill": ["bias", "grade", "start", "national", "local", "motor", "exhibition", "wind", "wave"],
    "full": FEATURES,
}


def safe_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


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
        elif isinstance(value, str) and value.strip().isdigit():
            parts.append(str(int(value.strip())))
    return "-".join(parts)


def load_events(path):
    with open(path, encoding="utf-8") as handle:
        store = json.load(handle)
    events = store.get("events", {})
    if isinstance(events, dict):
        events = events.values()
    usable = []
    for event in events:
        if not isinstance(event, dict):
            continue
        racers = event.get("racers")
        result = event.get("result")
        if not isinstance(racers, list) or len(racers) != 6:
            continue
        if not isinstance(result, list) or len(result) < 3:
            continue
        boats = {int(r.get("boat") or 0) for r in racers}
        result_boats = [int(value) for value in result[:3] if str(value).isdigit()]
        if boats != {1, 2, 3, 4, 5, 6} or len(result_boats) != 3:
            continue
        usable.append({**event, "result": result_boats})
    return sorted(usable, key=lambda event: (event.get("date") or "", event.get("venue") or "", int(event.get("race") or 0)))


def raw_features(event, racer):
    boat = int(racer.get("boat") or 0)
    vector = {
        "bias": 1.0,
        "boat1": 1.0 if boat == 1 else 0.0,
        "boat2": 1.0 if boat == 2 else 0.0,
        "boat3": 1.0 if boat == 3 else 0.0,
        "boat4": 1.0 if boat == 4 else 0.0,
        "boat5": 1.0 if boat == 5 else 0.0,
        "boat6": 1.0 if boat == 6 else 0.0,
        "grade": GRADE_SCORE.get(str(racer.get("grade") or "").upper(), 0.5),
        "start": safe_float(racer.get("start"), 0.18),
        "national": safe_float(racer.get("national")),
        "local": safe_float(racer.get("local")),
        "motor": safe_float(racer.get("motor")),
        "exhibition": safe_float(racer.get("exhibition")),
        "wind": safe_float(event.get("wind")),
        "wave": safe_float(event.get("wave")),
    }
    return [vector[name] for name in FEATURES]


def fit_scaler(events):
    columns = [[] for _ in FEATURES]
    for event in events:
        for racer in event["racers"]:
            values = raw_features(event, racer)
            for index, value in enumerate(values):
                columns[index].append(value)
    means = []
    scales = []
    for name, values in zip(FEATURES, columns):
        if name == "bias" or name.startswith("boat"):
            means.append(0.0)
            scales.append(1.0)
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
        means.append(mean)
        scales.append(math.sqrt(variance) or 1.0)
    return means, scales


def event_feature_map(event, means, scales):
    mapped = {}
    for racer in event["racers"]:
        boat = int(racer.get("boat") or 0)
        raw = raw_features(event, racer)
        mapped[boat] = [
            (value - means[index]) / scales[index]
            for index, value in enumerate(raw)
        ]
    return mapped


def dot(weights, features):
    return sum(weight * value for weight, value in zip(weights, features))


def softmax_scores(weights, features_by_boat, remaining):
    raw = {boat: dot(weights, features_by_boat[boat]) for boat in remaining}
    max_raw = max(raw.values())
    exp_values = {boat: math.exp(raw[boat] - max_raw) for boat in remaining}
    total = sum(exp_values.values())
    return {boat: exp_values[boat] / total for boat in remaining}


def train(events, means, scales, epochs=160, lr=0.035, l2=0.001, seed=7):
    rng = random.Random(seed)
    weights = [0.0 for _ in FEATURES]
    prepared = [
        (event_feature_map(event, means, scales), event["result"][:3])
        for event in events
    ]
    for epoch in range(1, epochs + 1):
        rng.shuffle(prepared)
        total_loss = 0.0
        for features_by_boat, result in prepared:
            remaining = [1, 2, 3, 4, 5, 6]
            for winner in result:
                probabilities = softmax_scores(weights, features_by_boat, remaining)
                total_loss += -math.log(max(1e-12, probabilities.get(winner, 1e-12)))
                gradient = list(features_by_boat[winner])
                expected = [0.0 for _ in FEATURES]
                for boat, probability in probabilities.items():
                    for index, value in enumerate(features_by_boat[boat]):
                        expected[index] += probability * value
                for index in range(len(weights)):
                    weights[index] += lr * (gradient[index] - expected[index] - l2 * weights[index])
                remaining.remove(winner)
        if epoch in (1, epochs) or epoch % max(20, epochs // 4) == 0:
            print(f"  epoch {epoch:>4}/{epochs}: train NLL {total_loss / max(1, len(prepared)):.4f}")
    return weights


def ticket_probability(weights, features_by_boat, ticket):
    probability = 1.0
    remaining = [1, 2, 3, 4, 5, 6]
    for boat in ticket:
        probabilities = softmax_scores(weights, features_by_boat, remaining)
        probability *= probabilities.get(boat, 0.0)
        if boat in remaining:
            remaining.remove(boat)
    return probability


def roc_auc(rows, score_key):
    positives = [row for row in rows if row["hit"]]
    negatives = [row for row in rows if not row["hit"]]
    if not positives or not negatives:
        return None
    ranked = sorted((row[score_key], 1 if row["hit"] else 0) for row in rows)
    rank_sum = 0.0
    rank = 1
    index = 0
    while index < len(ranked):
        score = ranked[index][0]
        end = index
        positives_in_tie = 0
        while end < len(ranked) and ranked[end][0] == score:
            positives_in_tie += ranked[end][1]
            end += 1
        average_rank = (rank + rank + (end - index) - 1) / 2
        rank_sum += positives_in_tie * average_rank
        rank += end - index
        index = end
    pos_count = len(positives)
    neg_count = len(negatives)
    return (rank_sum - pos_count * (pos_count + 1) / 2) / (pos_count * neg_count)


def pick_market_probability(pick):
    if pick.get("marketProbability"):
        return safe_float(pick.get("marketProbability"))
    if pick.get("oddsSource") == "official" and safe_float(pick.get("estimatedOdds")) > 0:
        return 1 / safe_float(pick.get("estimatedOdds"))
    actual = pick.get("actualOdds")
    if not isinstance(actual, bool) and safe_float(actual) > 0:
        return 1 / safe_float(actual)
    return 0.0


def evaluate(events, weights, means, scales):
    ticket_rows = []
    market_rows = []
    market_all_rows = []
    ranks = []
    top1_hits = 0
    top3_hits = 0
    top7_hits = 0
    for event in events:
        features_by_boat = event_feature_map(event, means, scales)
        result_key = normalize_ticket(event["result"][:3])
        all_tickets = []
        for ticket in permutations(range(1, 7), 3):
            probability = ticket_probability(weights, features_by_boat, ticket)
            key = normalize_ticket(list(ticket))
            all_tickets.append((probability, key))
            ticket_rows.append({"score": probability, "hit": key == result_key})
        odds3t = event.get("odds3t") if isinstance(event.get("odds3t"), dict) else {}
        inverse_sum = sum(1 / safe_float(odds) for odds in odds3t.values() if safe_float(odds) > 0)
        if inverse_sum > 0:
            for probability, key in all_tickets:
                odds = safe_float(odds3t.get(key))
                if odds <= 0:
                    continue
                market_probability = (1 / odds) / inverse_sum
                market_all_rows.append({
                    "model": probability,
                    "market": market_probability,
                    "hit": key == result_key,
                })
        ranked = sorted(all_tickets, key=lambda item: item[0], reverse=True)
        rank = next((index + 1 for index, item in enumerate(ranked) if item[1] == result_key), None)
        if rank:
            ranks.append(rank)
            top1_hits += 1 if rank <= 1 else 0
            top3_hits += 1 if rank <= 3 else 0
            top7_hits += 1 if rank <= 7 else 0
        picks = event.get("picks") if isinstance(event.get("picks"), list) else []
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            ticket = normalize_ticket(pick.get("ticket"))
            if not ticket:
                continue
            parts = [int(value) for value in ticket.split("-")]
            if len(parts) != 3:
                continue
            model_probability = ticket_probability(weights, features_by_boat, parts)
            market_probability = pick_market_probability(pick)
            row = {
                "model": model_probability,
                "market": market_probability,
                "hit": ticket == result_key,
            }
            if market_probability > 0:
                market_rows.append(row)
    return {
        "ticketAuc": roc_auc(ticket_rows, "score"),
        "marketModelAuc": roc_auc(market_rows, "model"),
        "marketAuc": roc_auc(market_rows, "market"),
        "allMarketModelAuc": roc_auc(market_all_rows, "model"),
        "allMarketAuc": roc_auc(market_all_rows, "market"),
        "marketRows": len(market_rows),
        "allMarketRows": len(market_all_rows),
        "events": len(events),
        "meanRank": sum(ranks) / len(ranks) if ranks else 0,
        "medianRank": sorted(ranks)[len(ranks) // 2] if ranks else 0,
        "top1": top1_hits / len(events) if events else 0,
        "top3": top3_hits / len(events) if events else 0,
        "top7": top7_hits / len(events) if events else 0,
    }


def split_events(events, train_ratio=0.8):
    dates = sorted({event.get("date") or "" for event in events})
    if len(dates) >= 2:
        cutoff_index = max(1, int(len(dates) * train_ratio))
        train_dates = set(dates[:cutoff_index])
        train_events = [event for event in events if (event.get("date") or "") in train_dates]
        test_events = [event for event in events if (event.get("date") or "") not in train_dates]
        if train_events and test_events:
            return train_events, test_events
    cutoff = max(1, int(len(events) * train_ratio))
    return events[:cutoff], events[cutoff:]


def print_metrics(title, metrics):
    print(title)
    print("  events              :", metrics["events"])
    print("  all-ticket AUC      :", f"{metrics['ticketAuc']:.4f}" if metrics["ticketAuc"] is not None else "n/a")
    print("  result mean rank    :", f"{metrics['meanRank']:.1f} / 120")
    print("  result median rank  :", f"{metrics['medianRank']} / 120")
    print("  top1 / top3 / top7  :", f"{metrics['top1']*100:.1f}% / {metrics['top3']*100:.1f}% / {metrics['top7']*100:.1f}%")
    if metrics["marketRows"]:
        print("  saved-pick rows     :", metrics["marketRows"])
        print("  model AUC on picks  :", f"{metrics['marketModelAuc']:.4f}" if metrics["marketModelAuc"] is not None else "n/a")
        print("  market AUC on picks :", f"{metrics['marketAuc']:.4f}" if metrics["marketAuc"] is not None else "n/a")
    if metrics["allMarketRows"]:
        print("  all-odds rows       :", metrics["allMarketRows"])
        print("  model AUC all odds  :", f"{metrics['allMarketModelAuc']:.4f}" if metrics["allMarketModelAuc"] is not None else "n/a")
        print("  market AUC all odds :", f"{metrics['allMarketAuc']:.4f}" if metrics["allMarketAuc"] is not None else "n/a")
    print()


def main():
    global FEATURES
    parser = argparse.ArgumentParser(description="Plackett-Luce trainer for BOAT PREDICT AI learning logs")
    parser.add_argument("path", nargs="?", default=os.environ.get("BOAT_LEARNING_PATH", ".official-cache/learning.json"))
    parser.add_argument("--epochs", type=int, default=160)
    parser.add_argument("--lr", type=float, default=0.035)
    parser.add_argument("--l2", type=float, default=0.001)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--features",
        choices=sorted(FEATURE_SETS),
        default="full",
        help="使用する特徴量セット。lane=枠だけ / skill=選手特徴だけ / full=全部",
    )
    parser.add_argument(
        "--compare-features",
        action="store_true",
        help="lane / skill / full を同じデータで順番に学習して比較する",
    )
    args = parser.parse_args()

    if not os.path.exists(args.path):
        sys.exit(f"learning.json が見つかりません: {args.path}")
    events = load_events(args.path)
    if len(events) < 30:
        print(f"racers入りの学習イベントが足りません: {len(events)}件")
        print("管理画面で過去日付を force 再集計して、racers入り learning.json を作ってから再実行してください。")
        return

    train_events, test_events = split_events(events)
    feature_modes = ["lane", "skill", "full"] if args.compare_features else [args.features]
    for mode in feature_modes:
        FEATURES = FEATURE_SETS[mode]
        print("=" * 72)
        print(f"feature mode: {mode}")
        print(f"loaded events: {len(events)}  train: {len(train_events)}  test: {len(test_events)}")
        print(f"features: {', '.join(FEATURES)}")
        means, scales = fit_scaler(train_events)
        weights = train(train_events, means, scales, epochs=args.epochs, lr=args.lr, l2=args.l2, seed=args.seed)
        print()
        print("learned weights")
        for name, weight in sorted(zip(FEATURES, weights), key=lambda item: -abs(item[1])):
            print(f"  {name:<12} {weight:>9.4f}")
        print()
        print_metrics("train metrics", evaluate(train_events, weights, means, scales))
        print_metrics("test metrics", evaluate(test_events, weights, means, scales))


if __name__ == "__main__":
    main()
