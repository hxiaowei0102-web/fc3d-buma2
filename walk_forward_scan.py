# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 最优窗口期数测算（样本外 walk-forward）
=============================================
问题：线上主窗口=300期、副窗口=500期（4074万公式池穷举选公式）。
      300/500 是不是「长期最稳」的窗口期数？窗口太小=过拟合噪声、
      窗口太大=对近期漂移不敏感。用样本外网格扫描找最优。

方法（与百十个杀一码 analyze_window.py 同源）：
  对每个候选窗口 W，把最近 3×SEG_LEN 期切成 3 段；
  每段用「段前 W 期」(再加前2期做特征) 跑线上同款穷举选公式
  （45桶内命中最高 = 唯一主推，无备用）→ 用固定公式逐期预测段内
  SEG_LEN 期（样本外，未参与选公式），完全复刻线上判定（v2：不撞期、不切换、不跳过）：
    命中=预测对∉当期同现对。统计：段内命中率/最大连错/逐段命中率。

  样本外表现最好且段间波动最小的 W = 推荐固化的主窗口。

用法：python walk_forward_scan.py            # 跑全部 W（多核并行）
      python walk_forward_scan.py 200 300    # 只跑指定 W
汇总：python sum_window_scan.py
"""
import json
import os
import sys
import time
from multiprocessing import Pool

from engine import load_data
from formulas import make_predictor, co_occur_pairs, P2I
from bruteforce import search_best

CSV = 'data/fc3d-history.csv'
SEG_LEN = 120          # 每段样本外评估期数
N_SEG = 3              # 段数（最近 3*120=360 期做样本外）
WINDOWS = (100, 150, 200, 250, 300, 400, 500)   # 候选窗口网格
OUT_DIR = 'results'


def eval_seg(hh, tt, oo, seg_start, seg_end, main_name):
    """固定公式逐期评估样本外 [seg_start, seg_end]，复刻线上 backtest 判定（v2：永不跳过）。
    返回 {n, valid, hits, misses, skips, rate, max_miss_streak}"""
    fn_main = make_predictor(main_name)
    n = valid = hits = misses = 0
    mx = cur = 0
    for i in range(seg_start, seg_end + 1):
        n += 1
        pb, ps, pg = hh[i - 1], tt[i - 1], oo[i - 1]
        prev = (hh[i - 2], tt[i - 2], oo[i - 2])
        pair = fn_main(pb, ps, pg, prev)
        valid += 1
        co_now = co_occur_pairs(hh[i], tt[i], oo[i])
        hit = P2I[pair] not in co_now
        if hit:
            hits += 1
            cur = 0
        else:
            misses += 1
            cur += 1
            mx = max(mx, cur)
    return {
        'n': n, 'valid': valid, 'hits': hits, 'misses': misses, 'skips': 0,
        'rate': round(hits / valid * 100, 2) if valid else 0.0,
        'max_miss_streak': mx,
    }


def run_one_window(args):
    """对单个 W 跑完 3 段。返回 {W, segs, avg}。独立进程执行。"""
    W, issues, hh, tt, oo, seg_starts = args
    t_start = time.time()
    res = {'W': W, 'n_total': len(hh), 'segs': {}}
    print(f"[W={W}] 开始 {time.strftime('%H:%M:%S')}", flush=True)
    for si, seg_start in enumerate(seg_starts):
        seg_end = seg_start + SEG_LEN - 1
        fit_start = seg_start - W - 2      # 拟合窗口（前 W 期 + 2 期特征支撑）
        if fit_start < 0:
            print(f"[W={W}] 段{si+1} 数据不足，跳过", flush=True)
            continue
        # 复刻线上 search_best：拟合段前 W 期，45桶内取唯一主推（无备用）
        tops, total = search_best(
            hh[fit_start:seg_start], tt[fit_start:seg_start],
            oo[fit_start:seg_start], window=W, verbose=False)
        if not tops:
            continue
        main_name = tops[0]['name']
        oos = eval_seg(hh, tt, oo, seg_start, seg_end, main_name)
        res['segs'][f'seg{si+1}'] = {
            'range': f"{issues[seg_start]}~{issues[seg_end]}",
            'main': main_name, 'main_pair': tops[0]['pair'],
            'oos': oos,
        }
        print(f"[W={W}] 段{si+1} [{issues[seg_start]}~{issues[seg_end]}] "
              f"样本外 {oos['rate']}% ({oos['hits']}/{oos['valid']}) "
              f"跳{oos['skips']} 耗时{time.time()-t_start:.0f}s", flush=True)
    segs = res['segs']
    if segs:
        rates = [s['oos']['rate'] for s in segs.values()]
        valid_sum = sum(s['oos']['valid'] for s in segs.values())
        hit_sum = sum(s['oos']['hits'] for s in segs.values())
        skip_sum = sum(s['oos']['skips'] for s in segs.values())
        res['avg'] = {
            'rate': round(hit_sum / valid_sum * 100, 2) if valid_sum else 0.0,
            'hits': hit_sum, 'valid': valid_sum, 'skips': skip_sum,
            'seg_rates': {k: round(r, 2) for k, r in zip(segs.keys(), rates)},
            'min_seg': min(rates), 'max_seg': max(rates),
            'spread': round(max(rates) - min(rates), 2),
        }
    print(f"[W={W}] 完成 avg={res.get('avg', {}).get('rate')}% "
          f"耗时{time.time()-t_start:.0f}s", flush=True)
    return res


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    want = [int(a) for a in sys.argv[1:]] or list(WINDOWS)
    issues, hh, tt, oo = load_data(CSV)
    end = len(hh) - 1
    # 3 段：seg1(最远) seg2 seg3(最近)，每段 SEG_LEN 期
    seg_starts = [end - N_SEG * SEG_LEN + 1,
                  end - (N_SEG - 1) * SEG_LEN + 1,
                  end - (N_SEG - 2) * SEG_LEN + 1]
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"数据 {len(hh)} 期 ({issues[0]}~{issues[-1]}) | 样本外段: "
          + " | ".join(f"{issues[s]}~{issues[s+SEG_LEN-1]}" for s in seg_starts))
    print(f"扫描窗口: {want} | 每窗口 {N_SEG} 段 × {SEG_LEN} 期 = {N_SEG*SEG_LEN} 期样本外")

    tasks = [(W, issues, hh, tt, oo, seg_starts) for W in want]
    n_proc = min(len(want), 8)   # 每窗口1进程，上限8（穷举为CPU密集）
    results = []
    if n_proc <= 1:
        for t in tasks:
            results.append(run_one_window(t))
    else:
        with Pool(n_proc) as pool:
            results = pool.map(run_one_window, tasks)

    for r in results:
        p = os.path.join(OUT_DIR, f'window_pair_{r["W"]}.json')
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
    print(f"\n✓ 已写 {OUT_DIR}/window_pair_*.json 共 {len(results)} 个窗口")


if __name__ == '__main__':
    main()
