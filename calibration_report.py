#!/usr/bin/env python3
"""
BOAT PREDICT AI - 予測校正 & 回収率レポート

learning.json を読み込み、保存済みの予測ログから以下を出力します。
  1. データ概要
  2. 戦略別サマリー（本命/狙い目/穴: 1点的中率・レース単位の的中率・回収率）
  3. 予測確率の校正（予測確率の十分位ごとに、実際の的中率と回収率）
  4. 期待値スコア(valueScore)帯別の回収率（買い目しきい値が機能しているかの検証）

依存ライブラリなし（標準ライブラリのみ）。Render 上でもそのまま動きます。

使い方:
  python3 calibration_report.py /var/data/boat-predict/learning.json
  python3 calibration_report.py learning.json --source server-backfill
  python3 calibration_report.py learning.json --date 2026-06-15 --csv out.csv
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict

STRATEGY_ORDER = ["honmei", "nerai", "ana"]
STRATEGY_LABEL = {"honmei": "本命", "nerai": "狙い目", "ana": "穴"}
STAKE_PER_PICK = 100  # 1点あたりの賭け金（円）


# --- server.py と同じチケット正規化（int / {"boat":n} / "1" すべて対応） ---
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
        elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
            parts.append(str(int(value.strip())))
    return "-".join(parts)


# --- server.py の pick_value_score と同じフォールバック ---
def pick_value_score(pick):
    try:
        value = pick.get("valueScore")
        if value is not None:
            return float(value)
        probability = float(pick.get("probability") or 0)
        odds = float(pick.get("estimatedOdds") or pick.get("actualOdds") or 0)
        return probability * odds
    except (TypeError, ValueError):
        return 0.0


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp_probability(value):
    return max(0.001, min(0.999, value))


def normalized_model_probability(probability, denominator):
    if probability <= 0:
        return 0.0
    return clamp_probability(probability / denominator)


def binary_logloss(probability, hit):
    probability = clamp_probability(probability)
    return -math.log(probability if hit else 1 - probability)


def load_events(path):
    with open(path, encoding="utf-8") as handle:
        store = json.load(handle)
    events = store.get("events", {})
    if isinstance(events, dict):
        return [e for e in events.values() if isinstance(e, dict)]
    if isinstance(events, list):
        return [e for e in events if isinstance(e, dict)]
    return []


def extract_rows(events, date=None, venue=None, source=None):
    """各 pick を 1 行に展開。1点=100円賭けた前提で hit / 払戻 / 賭け金 を持たせる。"""
    rows = []
    for event in events:
        if date and event.get("date") != date:
            continue
        if venue and event.get("venue") != venue:
            continue
        ev_source = event.get("source") or (
            "server-backfill" if event.get("phase") == "server-backfill" else "prediction-screen"
        )
        if source and ev_source != source:
            continue
        result_key = normalize_ticket(event.get("result"))
        if not result_key:
            continue  # 結果が取れていないレースは校正対象外
        payout = int(safe_float(event.get("payout"), 0))
        picks = event.get("picks") if isinstance(event.get("picks"), list) else []
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            odds_source = pick.get("oddsSource")
            actual_odds = pick.get("actualOdds")
            estimated_odds = safe_float(pick.get("estimatedOdds"))
            if not odds_source:
                if isinstance(actual_odds, bool):
                    odds_source = "official" if actual_odds else "estimated"
                elif safe_float(actual_odds) > 0:
                    odds_source = "official"
                else:
                    odds_source = "estimated"
            official_odds = (
                estimated_odds
                if odds_source == "official" and estimated_odds > 0
                else safe_float(actual_odds)
            )
            market_probability = safe_float(pick.get("marketProbability"))
            if market_probability <= 0 and odds_source == "official" and official_odds > 0:
                market_probability = 1 / official_odds
            ticket_key = normalize_ticket(pick.get("ticket"))
            hit = bool(ticket_key) and ticket_key == result_key
            rows.append({
                "event_key": event.get("key"),
                "date": event.get("date"),
                "venue": event.get("venue"),
                "source": ev_source,
                "strategy": pick.get("strategyKey") or "?",
                "prob": safe_float(pick.get("probability")),
                "odds": estimated_odds or safe_float(actual_odds),
                "oddsSource": odds_source,
                "marketProb": market_probability,
                "valueScore": pick_value_score(pick),
                "hit": hit,
                "stake": STAKE_PER_PICK,
                "return": payout if hit else 0,
            })
    return rows


def pct(part, whole):
    return (100.0 * part / whole) if whole else 0.0


def roi_pct(returns, stake):
    return (100.0 * returns / stake) if stake else 0.0


def quantile_edges(values, nbins):
    """値を昇順に並べて nbins 等個数のビン境界（インデックス）を返す。"""
    s = sorted(values)
    n = len(s)
    edges = []
    for i in range(1, nbins):
        idx = int(round(i * n / nbins))
        idx = max(0, min(n - 1, idx))
        edges.append(s[idx])
    return edges


def bin_index(value, edges):
    for i, edge in enumerate(edges):
        if value < edge:
            return i
    return len(edges)


# ----------------------------- 出力セクション -----------------------------
def section_overview(rows, events_count):
    print("=" * 72)
    print(" 1. データ概要")
    print("=" * 72)
    by_source = defaultdict(int)
    by_strategy = defaultdict(int)
    dates = set()
    venues = set()
    for r in rows:
        by_source[r["source"]] += 1
        by_strategy[r["strategy"]] += 1
        if r["date"]:
            dates.add(r["date"])
        if r["venue"]:
            venues.add(r["venue"])
    print(f"  対象イベント(レース)数 : {events_count}")
    print(f"  対象 pick(買い目)数    : {len(rows)}")
    if dates:
        print(f"  期間                   : {min(dates)} 〜 {max(dates)}  ({len(dates)}日)")
    print(f"  会場数                 : {len(venues)}")
    print(f"  ソース内訳             : " + " / ".join(f"{k}:{v}" for k, v in sorted(by_source.items())))
    print(f"  戦略内訳               : " + " / ".join(
        f"{STRATEGY_LABEL.get(k, k)}:{v}" for k, v in sorted(by_strategy.items())))
    print()


def section_by_strategy(rows):
    print("=" * 72)
    print(" 2. 戦略別サマリー  （1点=100円, 回収率100%=トントン）")
    print("=" * 72)
    print("  戦略     点数   1点的中率   R単位的中率   回収率    的中時平均配当")
    print("  ----     ----   ---------   -----------   ------    ------------")
    # レース単位の any-hit を出すため、戦略×イベントで集計
    for strat in STRATEGY_ORDER + sorted(set(r["strategy"] for r in rows) - set(STRATEGY_ORDER) - {"?"}):
        sub = [r for r in rows if r["strategy"] == strat]
        if not sub:
            continue
        picks = len(sub)
        hits = sum(1 for r in sub if r["hit"])
        stake = sum(r["stake"] for r in sub)
        returns = sum(r["return"] for r in sub)
        # レース単位（その戦略の何点かのうち1つでも当たったレースの割合）
        ev_hit = defaultdict(bool)
        for r in sub:
            ev_hit[r["event_key"]] = ev_hit[r["event_key"]] or r["hit"]
        races = len(ev_hit)
        race_hits = sum(1 for v in ev_hit.values() if v)
        avg_payout = (sum(r["return"] for r in sub if r["hit"]) / hits) if hits else 0
        print("  {:<6} {:>6} {:>10}% {:>11}% {:>8}% {:>13}".format(
            STRATEGY_LABEL.get(strat, strat),
            picks,
            f"{pct(hits, picks):.2f}",
            f"{pct(race_hits, races):.1f}",
            f"{roi_pct(returns, stake):.1f}",
            f"{avg_payout:,.0f}円",
        ))
    # 全体
    picks = len(rows)
    hits = sum(1 for r in rows if r["hit"])
    stake = sum(r["stake"] for r in rows)
    returns = sum(r["return"] for r in rows)
    print("  {:<6} {:>6} {:>10}% {:>11}  {:>8}%".format(
        "全体", picks, f"{pct(hits, picks):.2f}", "-", f"{roi_pct(returns, stake):.1f}"))
    print()


def section_calibration(rows, nbins=10):
    print("=" * 72)
    print(" 3. 予測確率の校正  （平均予測確率 ≒ 実際の的中率 なら校正OK）")
    print("=" * 72)
    probs = [r["prob"] for r in rows if r["prob"] > 0]
    if not probs:
        print("  picks に有効な probability がありません。")
        print()
        return
    lo, hi = min(probs), max(probs)
    print(f"  予測確率の生スケール: 最小 {lo:.2f} / 最大 {hi:.2f} / 平均 {sum(probs)/len(probs):.2f}")
    if hi > 1.5:
        scale_note = ("※ 値が 1 を超えています。確率(0〜1)ではなくスコア/％の可能性大。"
                      "下表は『平均予測確率』を実際の的中率と直接比べてください。")
        denom = 100.0 if hi <= 100 else None
    else:
        scale_note = "※ 0〜1 スケールとみなして比較します。"
        denom = 1.0
    print("  " + scale_note)
    if denom == 100.0:
        print("  （参考: 予測確率を /100 した『想定確率%』も併記します）")
    print()
    edges = quantile_edges([r["prob"] for r in rows], nbins)
    buckets = defaultdict(list)
    for r in rows:
        buckets[bin_index(r["prob"], edges)].append(r)
    header = "  bin  点数   予測確率レンジ        平均予測   実的中率   回収率"
    if denom == 100.0:
        header += "   想定確率(/100)"
    print(header)
    print("  ---  ----   --------------        --------   --------   ------" +
          ("   ------------" if denom == 100.0 else ""))
    for i in sorted(buckets):
        sub = buckets[i]
        ps = [r["prob"] for r in sub]
        n = len(sub)
        hits = sum(1 for r in sub if r["hit"])
        stake = sum(r["stake"] for r in sub)
        returns = sum(r["return"] for r in sub)
        mean_p = sum(ps) / n
        line = "  {:>3} {:>5}   {:>7.2f} 〜 {:>7.2f}     {:>7.2f}   {:>7.2f}%  {:>6.1f}%".format(
            i + 1, n, min(ps), max(ps), mean_p, pct(hits, n), roi_pct(returns, stake))
        if denom == 100.0:
            line += "      {:>7.2f}%".format(mean_p / denom)
        print(line)
    print()


def section_valuescore(rows):
    print("=" * 72)
    print(" 5. 期待値スコア(valueScore)帯別の回収率")
    print("    買い目しきい値が『回収率の高い買い目』を選べているかの検証")
    print("=" * 72)
    vs = [r["valueScore"] for r in rows if r["valueScore"] > 0]
    if not vs:
        print("  valueScore を計算できる pick がありません。")
        print()
        return
    print(f"  valueScore の生スケール: 最小 {min(vs):.1f} / 最大 {max(vs):.1f} / 平均 {sum(vs)/len(vs):.1f}")
    print()

    # (A) 既存しきい値まわりの固定帯（buildBetDecision の 72/96/115 を直接検証）
    print("  (A) 判定しきい値まわりの固定帯  ※valueScore はソースで尺度差あり、参考値")
    fixed = [("< 72", lambda v: v < 72),
             ("72〜96", lambda v: 72 <= v < 96),
             ("96〜115", lambda v: 96 <= v < 115),
             ("115〜150", lambda v: 115 <= v < 150),
             (">=150", lambda v: v >= 150)]
    print("      帯           点数   的中率    回収率")
    print("      ---           ----   ------    ------")
    for label, cond in fixed:
        sub = [r for r in rows if cond(r["valueScore"])]
        if not sub:
            continue
        n = len(sub)
        hits = sum(1 for r in sub if r["hit"])
        stake = sum(r["stake"] for r in sub)
        returns = sum(r["return"] for r in sub)
        print("      {:<12} {:>5}  {:>6.2f}%  {:>7.1f}%".format(
            label, n, pct(hits, n), roi_pct(returns, stake)))
    print()

    # (B) 十分位（スケールに依存しない）。回収率が右肩上がりならエッジあり。
    print("  (B) valueScore 十分位（尺度非依存）。回収率が高帯ほど上がるならエッジあり")
    edges = quantile_edges([r["valueScore"] for r in rows], 10)
    buckets = defaultdict(list)
    for r in rows:
        buckets[bin_index(r["valueScore"], edges)].append(r)
    print("      bin   点数   valueScoreレンジ      的中率    回収率")
    print("      ---   ----   ----------------      ------    ------")
    for i in sorted(buckets):
        sub = buckets[i]
        n = len(sub)
        hits = sum(1 for r in sub if r["hit"])
        stake = sum(r["stake"] for r in sub)
        returns = sum(r["return"] for r in sub)
        scores = [r["valueScore"] for r in sub]
        print("      {:>3}  {:>5}   {:>7.1f} 〜 {:>7.1f}    {:>6.2f}%  {:>7.1f}%".format(
            i + 1, n, min(scores), max(scores), pct(hits, n), roi_pct(returns, stake)))
    print()


def section_market_comparison(rows):
    print("=" * 72)
    print(" 4. 市場オッズ比較  （log損失は低いほど良い）")
    print("=" * 72)
    usable = [
        r for r in rows
        if r["prob"] > 0 and (r["marketProb"] > 0 or r["odds"] > 0)
    ]
    if not usable:
        print("  公式オッズ由来の市場確率を計算できる pick がありません。公式オッズ取得後のログが必要です。")
        print()
        return
    denominator = 100.0 if max(r["prob"] for r in usable) > 1.5 else 1.0
    for r in usable:
        r["modelProb"] = normalized_model_probability(r["prob"], denominator)
        market_probability = r["marketProb"] or (1 / r["odds"] if r["odds"] > 0 else 0)
        r["marketProbNorm"] = clamp_probability(market_probability)
        r["marketEdge"] = r["modelProb"] - r["marketProbNorm"]
    model_ll = sum(binary_logloss(r["modelProb"], r["hit"]) for r in usable) / len(usable)
    market_ll = sum(binary_logloss(r["marketProbNorm"], r["hit"]) for r in usable) / len(usable)
    print(f"  対象点数               : {len(usable)}")
    print("  対象                   : oddsSource=official の買い目のみ")
    print(f"  モデル平均log損失      : {model_ll:.4f}")
    print(f"  市場オッズ平均log損失  : {market_ll:.4f}")
    if model_ll < market_ll:
        print("  判定                   : モデル確率が市場より良い可能性あり")
    else:
        print("  判定                   : 現状は市場オッズの方が確率として優秀")
    print()

    print("  戦略別: モデル vs 市場 log損失")
    print("      戦略       点数    モデルLL   市場LL    回収率")
    print("      ----       ----    --------   ------    ------")
    for strat in STRATEGY_ORDER + sorted(set(r["strategy"] for r in usable) - set(STRATEGY_ORDER) - {"?"}):
        sub = [r for r in usable if r["strategy"] == strat]
        if not sub:
            continue
        stake = sum(r["stake"] for r in sub)
        returns = sum(r["return"] for r in sub)
        sub_model_ll = sum(binary_logloss(r["modelProb"], r["hit"]) for r in sub) / len(sub)
        sub_market_ll = sum(binary_logloss(r["marketProbNorm"], r["hit"]) for r in sub) / len(sub)
        print("      {:<8} {:>5}    {:>8.4f}   {:>6.4f}  {:>7.1f}%".format(
            STRATEGY_LABEL.get(strat, strat),
            len(sub),
            sub_model_ll,
            sub_market_ll,
            roi_pct(returns, stake),
        ))
    print()

    print("  モデル優位度(modelProb - marketProb)帯別の回収率")
    print("      bin   点数   優位度レンジ          的中率    回収率")
    print("      ---   ----   ------------          ------    ------")
    edges = quantile_edges([r["marketEdge"] for r in usable], 10)
    buckets = defaultdict(list)
    for r in usable:
        buckets[bin_index(r["marketEdge"], edges)].append(r)
    for i in sorted(buckets):
        sub = buckets[i]
        edges_values = [r["marketEdge"] for r in sub]
        hits = sum(1 for r in sub if r["hit"])
        stake = sum(r["stake"] for r in sub)
        returns = sum(r["return"] for r in sub)
        print("      {:>3}  {:>5}   {:>7.3f} 〜 {:>7.3f}    {:>6.2f}%  {:>7.1f}%".format(
            i + 1,
            len(sub),
            min(edges_values),
            max(edges_values),
            pct(hits, len(sub)),
            roi_pct(returns, stake),
        ))
    print()


def section_howto():
    print("=" * 72)
    print(" 読み方メモ")
    print("=" * 72)
    print("  ・回収率 100% = トントン。控除率25%があるため、エッジが無いと自然に75%前後へ収束します。")
    print("  ・校正(3節): 『平均予測確率』と『実的中率』が一致していれば確率は正しい。")
    print("    乖離が大きい＝probability が確率になっていない（スコアのまま）サイン。")
    print("  ・市場比較(4節): 公式オッズ由来の市場確率より log損失が低いかを確認します。")
    print("  ・価値検証(5節B): valueScore が高い帯ほど回収率が高い、という右肩上がりが出れば、")
    print("    しきい値で買い目を絞る意味がある。全帯フラットに負けていればエッジ無し＝")
    print("    しきい値を緩めて買い増しても改善しない（むしろ悪化する）。")
    print("  ・サンプルが数百以下だと3連単は分散が大きく結論を出せません。点数を確認のこと。")
    print()


def write_csv(rows, path):
    import csv
    fields = ["event_key", "date", "venue", "source", "strategy",
              "prob", "odds", "oddsSource", "marketProb", "valueScore", "hit", "stake", "return"]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in fields})


def main():
    parser = argparse.ArgumentParser(description="BOAT PREDICT AI 校正/回収率レポート")
    parser.add_argument("path", nargs="?",
                        default=os.environ.get("BOAT_LEARNING_PATH", "learning.json"),
                        help="learning.json のパス")
    parser.add_argument("--date", help="日付で絞り込み (YYYY-MM-DD)")
    parser.add_argument("--venue", help="会場名で絞り込み")
    parser.add_argument("--source", choices=["prediction-screen", "server-backfill"],
                        help="ソースで絞り込み")
    parser.add_argument("--bins", type=int, default=10, help="校正のビン数 (既定10)")
    parser.add_argument("--csv", help="pick 単位の明細を CSV 出力するパス")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        sys.exit(f"learning.json が見つかりません: {args.path}\n"
                 f"  例: python3 {os.path.basename(sys.argv[0])} /var/data/boat-predict/learning.json")

    events = load_events(args.path)
    # 絞り込み後のイベント数（結果ありのみ）
    filtered_events = [
        e for e in events
        if (not args.date or e.get("date") == args.date)
        and (not args.venue or e.get("venue") == args.venue)
        and normalize_ticket(e.get("result"))
    ]
    rows = extract_rows(events, date=args.date, venue=args.venue, source=args.source)

    print()
    filt = []
    if args.date:
        filt.append(f"date={args.date}")
    if args.venue:
        filt.append(f"venue={args.venue}")
    if args.source:
        filt.append(f"source={args.source}")
    print(f"learning.json: {args.path}" + (f"   フィルタ: {', '.join(filt)}" if filt else ""))
    if not rows:
        sys.exit("対象 pick がありません。フィルタ条件、または結果(result)の有無を確認してください。")

    section_overview(rows, len(filtered_events))
    section_by_strategy(rows)
    section_calibration(rows, nbins=args.bins)
    section_market_comparison(rows)
    section_valuescore(rows)
    section_howto()

    if args.csv:
        write_csv(rows, args.csv)
        print(f"pick 明細を CSV 出力しました: {args.csv}")


if __name__ == "__main__":
    main()
