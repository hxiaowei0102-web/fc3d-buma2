# -*- coding: utf-8 -*-
"""汇总 results/window_pair_*.json 为「窗口期数 × 样本外表现」对比表"""
import json
import glob
import sys

sys.stdout.reconfigure(encoding='utf-8')

rows = []
for p in sorted(glob.glob('results/window_pair_*.json'),
                key=lambda x: int(x.split('_')[-1].split('.')[0])):
    d = json.load(open(p, encoding='utf-8'))
    W = d['W']
    if not d.get('avg'):
        continue
    a = d['avg']
    segs = d['segs']
    # 每段命中率，未跑/无效段记 '-'
    seg_rates = {k: v['oos']['rate'] for k, v in segs.items()}
    rows.append((W, a['rate'], a['hits'], a['valid'], a['skips'],
                 a['min_seg'], a['max_seg'], a['spread'], seg_rates))

print("=" * 100)
print(f"{'窗口W':>6} | {'样本外命中率':>10} | {'命中/有效':>14} | {'跳过':>4} | "
      f"{'段内最低':>7} | {'最高':>7} | {'极差':>6} | {'段1':>5} {'段2':>5} {'段3':>5}")
print("-" * 100)
for W, rate, hits, valid, skips, mn, mx, spread, segs in rows:
    print(f"{W:>6} | {rate:>9.2f}% | {hits:>6}/{valid:<7} | {skips:>4} | "
          f"{mn:>6.2f}% | {mx:>6.2f}% | {spread:>5.2f} | "
          + " ".join(f"{segs.get(k, 0):>5.2f}" for k in ('seg1', 'seg2', 'seg3')))
print("=" * 100)
print("随机基线（任意不组对）：约 94.6%")
if rows:
    # 最优 = 命中率最高且极差最小（双目标，命中优先再比稳）
    best = max(rows, key=lambda r: (r[1], -r[7]))
    print(f"\n样本外命中率最高: W={best[0]} ({best[1]}%)")
    # 最稳（极差最小且命中率不差于最高者过多）
    top_rate = max(r[1] for r in rows)
    stable = min(rows, key=lambda r: (r[7], -(r[1] - top_rate)))
    print(f"最稳(极差最小): W={stable[0]} (命中{stable[1]}% 极差{stable[7]}pp)")
    # 与当前线上 200 对比
    cur = [r for r in rows if r[0] == 200]
    if cur:
        print(f"线上当前 W=200: 样本外 {cur[0][1]}% (极差 {cur[0][7]}pp)")
