# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 回测引擎（固定公式回看）
=============================================
固定公式预测「不组两码」，应用到过去N期，逐期真实预测记录。
第 i 期预测仅用第 i-1 期数据，不偷看未来。结果排序近期→远期。

预测规则（v2，去掉撞上期约束）：每期永远报唯一主公式的预测对，永不切换、永不跳过。
命中 = 预测对 ∉ 当期同现对（开奖号去重后任意两个数字组成的对）。
"""
import json
from engine import load_data, get_next_issue
from formulas import make_predictor, co_occur_pairs, P2I

PAIR_TXT = lambda a, b: f"{a}{b}"


def load_combo(path='best_pair.json'):
    """读取 best_pair.json，返回主公式名（str）。v2：无备用。"""
    with open(path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    return d['main']['name']


def _predict_pair(fn, pb, ps, pg, prev):
    """公式输出 (a,b) 元组"""
    return fn(pb, ps, pg, prev)


def run_backtest(csv_path, main_name, n=200):
    issues, hh, tt, oo = load_data(csv_path)
    N = len(issues)
    start = max(2, N - n)
    fn_main = make_predictor(main_name)
    results = []
    for i in range(start, N):
        pb, ps, pg = hh[i-1], tt[i-1], oo[i-1]
        prev = (hh[i-2], tt[i-2], oo[i-2])
        pair = fn_main(pb, ps, pg, prev)     # 永远报主推，不撞期判定、不切换、不跳过
        co_now_idx = co_occur_pairs(hh[i], tt[i], oo[i])
        hit = P2I[pair] not in co_now_idx
        results.append({
            'issue': issues[i], 'draw': [hh[i], tt[i], oo[i]],
            'pair': PAIR_TXT(*pair), 'hit': hit,
            'status': 'hit' if hit else 'miss',
        })

    total = len(results)
    valid = [r for r in results if r['hit'] is not None]
    hits = sum(1 for r in valid if r['hit'])
    skips = total - len(valid)   # 恒为0（v2 永不跳过）
    # 最大连错（对 valid 序列）
    mx = cur = 0
    for r in valid:
        if r['hit']:
            cur = 0
        else:
            cur += 1
            mx = max(mx, cur)
    # 当前连中/连错
    cur_hit = cur_miss = 0
    for r in reversed(valid):
        if r['hit']:
            cur_hit += 1
            if cur_miss: break
        else:
            cur_miss += 1
            if cur_hit: break
    summary = {
        'pair_hit_rate': round(hits/len(valid)*100, 2) if valid else 0,
        'total_periods': total, 'valid_periods': len(valid), 'hits': hits,
        'misses': len(valid)-hits, 'skips': skips,
        'max_miss_streak': mx, 'cur_hit': cur_hit, 'cur_miss': cur_miss,
        'window': f"最近{total}期",
    }
    results.reverse()  # 近期→远期
    return {'results': results, 'summary': summary}


def predict_next(csv_path, main_name):
    """预测下一期不组两码。返回 {'next_issue','last_issue','last_draw','pair','source'}"""
    issues, hh, tt, oo = load_data(csv_path)
    latest = issues[-1]
    pb, ps, pg = hh[-1], tt[-1], oo[-1]
    prev = (hh[-2], tt[-2], oo[-2])
    pair = make_predictor(main_name)(pb, ps, pg, prev)
    return {
        'next_issue': get_next_issue(latest),
        'last_issue': latest,
        'last_draw': [pb, ps, pg],
        'pair': PAIR_TXT(*pair),
        'source': 'main',
    }


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main = load_combo()
    print(f"主公式: {main}")
    bt = run_backtest('data/fc3d-history.csv', main, n=300)
    s = bt['summary']
    print(f"300期回测: 不组命中 {s['pair_hit_rate']}% ({s['hits']}/{s['valid_periods']}) "
          f"跳过{s['skips']} | 最大连错{s['max_miss_streak']}期")
    pn = predict_next('data/fc3d-history.csv', main)
    print(f"下一期 {pn['next_issue']} 不组: {pn['pair']}")
