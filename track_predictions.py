# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 每日预测跟踪（真正的每日预测留痕+自动验证）
=============================================
职责：
1. **验证历史预测**：predictions_log.csv 中 status=pending 的预测，
   若对应期号已开奖（CSV中已出现），自动回填实际开奖并判定命中/失误。
2. **追加今日新预测**：把当天系统报出的不组两码写入日志，供次日开奖后自动验证。
3. **累计统计**：输出真实累计命中率（全部验证过的预测）。

设计要点：
- 幂等：同一期号不重复记录（upsert by issue）；已验证不重复验证。
- 预测依据：第i期预测只用第i-1期(上期)及第i-2期(前2期)数据，不偷看未来。
- 回填历史：首次启用时，用固定公式把最近 N 期历史预测全部回填验证，
  让跟踪从第一天就有真实样本。
- 预测规则（v2，去掉撞上期约束）：每期永远报唯一主公式的预测对，永不切换、永不跳过。
"""
import csv, json, os
from datetime import datetime, timezone, timedelta
from engine import load_data, get_next_issue
from formulas import make_predictor, co_occur_pairs, P2I

CSV_PATH = 'data/fc3d-history.csv'
LOG_PATH = 'predictions_log.csv'          # 300期主窗口 跟踪日志
LOG_500_PATH = 'predictions_log_500.csv'  # 500期副窗口 独立跟踪日志
HEADER = ['issue', 'pair', 'prev_issue', 'prev_draw', 'draw',
          'formula_main', 'formula_backup', 'hit', 'status', 'source',
          'predicted_at', 'verified_at']
STATUS = {'PENDING': 'pending', 'HIT': 'hit', 'MISS': 'miss', 'SKIP': 'skip'}
BJT = timezone(timedelta(hours=8))
PAIR_TXT = lambda a, b: f"{a}{b}"


def _now_bjt():
    return datetime.now(BJT).strftime('%Y-%m-%d %H:%M')


def _load_log(path=LOG_PATH):
    rows = {}
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r.get('issue'):
                    for k in ('predicted_at', 'verified_at', 'draw', 'formula_main', 'formula_backup'):
                        if k not in r or r[k] is None:
                            r[k] = ''
                    rows[r['issue']] = r
    return rows


def _save_log(rows, path=LOG_PATH):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        for iss in sorted(rows.keys(), key=int):
            w.writerow({k: rows[iss].get(k, '') for k in HEADER})


def _predict_pair(fn, pb, ps, pg, prev):
    return fn(pb, ps, pg, prev)


def _resolve_pair(main_name, pb, ps, pg, prev):
    """永远报唯一主公式的预测对（v2：去掉撞上期约束，无备用、无跳过）"""
    return make_predictor(main_name)(pb, ps, pg, prev), False


def backfill_history(main_name, n=500, path=LOG_PATH):
    """用固定公式回填最近n期历史预测并验证。返回新增的已验证记录数。"""
    issues, hh, tt, oo = load_data(CSV_PATH)
    N = len(issues)
    rows = _load_log(path)
    added = 0
    start = max(2, N - n)
    for i in range(start, N):
        target = issues[i]
        prev_issue = issues[i-1]
        prev_draw = (hh[i-1], tt[i-1], oo[i-1])
        prev2 = (hh[i-2], tt[i-2], oo[i-2])
        if target in rows:
            continue
        pair, _ = _resolve_pair(main_name, *prev_draw, prev2)
        draw = (hh[i], tt[i], oo[i])
        hit = P2I[pair] not in co_occur_pairs(*draw)
        status = STATUS['HIT'] if hit else STATUS['MISS']
        rows[target] = {
            'issue': target, 'pair': PAIR_TXT(*pair),
            'prev_issue': prev_issue, 'prev_draw': ''.join(map(str, prev_draw)),
            'draw': ''.join(map(str, draw)),
            'formula_main': main_name, 'formula_backup': '',
            'hit': '1' if hit else '0',
            'status': status, 'source': 'backfill',
            'predicted_at': '回填', 'verified_at': '回填',
        }
        added += 1
    _save_log(rows, path)
    return added


def verify_pending(path=LOG_PATH):
    """验证所有 pending 预测：对应期号已开奖 → 回填判定。返回 (验证数, 命中数, 失误数)"""
    issues, hh, tt, oo = load_data(CSV_PATH)
    draw_map = {iss: (h, t, o) for iss, h, t, o in zip(issues, hh, tt, oo)}
    rows = _load_log(path)
    verified = hit = miss = 0
    for iss, row in rows.items():
        if row.get('status') != STATUS['PENDING']:
            continue
        if iss not in draw_map:
            continue
        draw = draw_map[iss]
        pair_txt = row.get('pair', '')
        row['draw'] = ''.join(map(str, draw))
        if not pair_txt:
            row['status'] = STATUS['SKIP']
            row['verified_at'] = _now_bjt()
            continue
        a, b = int(pair_txt[0]), int(pair_txt[1])
        h = P2I[(a, b)] not in co_occur_pairs(*draw)
        row['hit'] = '1' if h else '0'
        row['status'] = STATUS['HIT'] if h else STATUS['MISS']
        row['verified_at'] = _now_bjt()
        verified += 1
        if h:
            hit += 1
        else:
            miss += 1
    _save_log(rows, path)
    return verified, hit, miss


def add_prediction(main_name, issue=None, path=LOG_PATH):
    """追加今日新预测（开奖前落盘）。幂等：该期已记录则跳过。返回 1/0。"""
    rows = _load_log(path)
    issues, hh, tt, oo = load_data(CSV_PATH)
    latest = issues[-1]
    if issue is None:
        issue = get_next_issue(latest)
    if issue in rows:
        return 0
    prev_draw = (hh[-1], tt[-1], oo[-1])
    prev2 = (hh[-2], tt[-2], oo[-2])
    pair, _ = _resolve_pair(main_name, *prev_draw, prev2)
    rows[issue] = {
        'issue': issue,
        'pair': PAIR_TXT(*pair),
        'prev_issue': latest, 'prev_draw': ''.join(map(str, prev_draw)),
        'draw': '', 'formula_main': main_name, 'formula_backup': '',
        'hit': '', 'status': STATUS['PENDING'],
        'source': 'live', 'predicted_at': _now_bjt(), 'verified_at': '',
    }
    _save_log(rows, path)
    return 1


def summarize(path=LOG_PATH):
    """统计真实累计命中率（仅已验证预测）。区分 live / backfill。"""
    rows = _load_log(path)
    verified = [r for r in rows.values() if r.get('status') in (STATUS['HIT'], STATUS['MISS'])]
    pending = [r for r in rows.values() if r.get('status') == STATUS['PENDING']]
    skips = [r for r in rows.values() if r.get('status') == STATUS['SKIP']]
    n = len(verified)
    if n == 0:
        return {'total': len(rows), 'pending': len(pending), 'verified': 0,
                'hit_rate': 0, 'hits': 0, 'misses': 0, 'skips': len(skips),
                'max_miss_streak': 0, 'recent30': 0, 'recent30_n': 0,
                'live': {'verified': 0, 'hit_rate': 0, 'hits': 0},
                'backfill': {'verified': 0, 'hit_rate': 0, 'hits': 0}}
    hits = sum(1 for r in verified if r.get('hit') == '1')
    mx = cur = 0
    for r in sorted(verified, key=lambda x: int(x['issue'])):
        if r.get('hit') == '1':
            cur = 0
        else:
            cur += 1
            mx = max(mx, cur)
    recent = sorted(verified, key=lambda x: int(x['issue']))[-30:]
    recent_hits = sum(1 for r in recent if r.get('hit') == '1')
    live = [r for r in verified if r.get('source') == 'live']
    backfill = [r for r in verified if r.get('source') != 'live']
    def _seg(seg):
        if not seg:
            return {'verified': 0, 'hit_rate': 0, 'hits': 0}
        h = sum(1 for r in seg if r.get('hit') == '1')
        return {'verified': len(seg), 'hit_rate': round(h/len(seg)*100, 2), 'hits': h}
    return {
        'total': len(rows), 'pending': len(pending), 'verified': n,
        'hit_rate': round(hits/n*100, 2), 'hits': hits, 'misses': n-hits,
        'skips': len(skips), 'max_miss_streak': mx,
        'recent30': round(recent_hits/len(recent)*100, 2) if recent else 0,
        'recent30_n': len(recent),
        'live': _seg(live), 'backfill': _seg(backfill),
    }


def main(combo_path='best_pair.json', log_path=LOG_PATH, label=''):
    """对指定窗口跑完整跟踪。返回 track_changed:bool。"""
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    with open(combo_path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    main_name = d['main']['name']
    tag = f'[{label}] ' if label else ''
    print("=" * 50)
    print(f"{tag}每日预测跟踪 · 更新 ({combo_path})")
    print("=" * 50)
    track_changed = False

    if not os.path.exists(log_path):
        backfilled = backfill_history(main_name, n=500, path=log_path)
        print(f"{tag}[初始化] 首次启用，回填 {backfilled} 条历史预测作为基准（最近500期）")
        if backfilled:
            track_changed = True
    else:
        print(f"{tag}[初始化] 日志已存在，跳过历史回填（只做真实每日跟踪）")

    verified, hit, miss = verify_pending(path=log_path)
    if verified:
        print(f"{tag}[验证] 验证 {verified} 条预测: 命中 {hit} | 失误 {miss}")
        track_changed = True
    else:
        print(f"{tag}[验证] 无待验证预测")

    added = add_prediction(main_name, path=log_path)
    if added:
        print(f"{tag}[新增] 已记录今日新预测（开奖前落盘）")
        track_changed = True
    else:
        print(f"{tag}[新增] 今日预测已存在，跳过")

    s = summarize(path=log_path)
    print("-" * 50)
    print(f"{tag}累计已验证: {s['verified']} 期 | 待开奖: {s['pending']} 期 | 跳过: {s['skips']} 期")
    print(f"{tag}不组命中率: {s['hit_rate']}% ({s['hits']}/{s['verified']})")
    print(f"{tag}最大连错: {s['max_miss_streak']} 期 | 近30期 {s['recent30']}%")
    lv, bk = s['live'], s['backfill']
    print(f"{tag}[真实跟踪] {lv['verified']}期 命中{lv['hit_rate']}% | [历史回填] {bk['verified']}期 命中{bk['hit_rate']}%")
    return track_changed


def run_both():
    """300期主窗口 + 500期副窗口 各自独立跟踪。返回是否任一有变化。"""
    c1 = main('best_pair.json', LOG_PATH, '300')
    try:
        if os.path.exists('best_pair_500.json'):
            c2 = main('best_pair_500.json', LOG_500_PATH, '500')
        else:
            print("[500] best_pair_500.json 不存在，跳过500期跟踪")
            c2 = False
    except Exception as e:
        print(f"[500] ⚠ 500期跟踪异常: {str(e)[:80]}")
        c2 = False
    return c1 or c2


if __name__ == '__main__':
    run_both()
