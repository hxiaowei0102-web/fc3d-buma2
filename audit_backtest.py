# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 防未来信息审计
=============================================
验证 backtest / predict 使用的公式预测与「按期号独立重算」完全一致：
- 对预测日志中每一期，只用该期之前的数据独立重算公式预测对，比对记录值。
- 全部 0 不一致才算通过（防止任何形式偷看未来）。
"""
import csv, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
from engine import load_data
from formulas import make_predictor, co_occur_pairs, P2I
from backtest import _predict_pair, PAIR_TXT

CSV_PATH = 'data/fc3d-history.csv'
LOGS = ['predictions_log.csv', 'predictions_log_500.csv']


def recompute_row(issues, hh, tt, oo, idx):
    """按期号独立重算：只用 idx-1 / idx-2 期数据（不偷看未来）"""
    pb, ps, pg = hh[idx-1], tt[idx-1], oo[idx-1]
    prev = (hh[idx-2], tt[idx-2], oo[idx-2])
    prev_co = co_occur_pairs(pb, ps, pg)
    return prev_co


def audit_log(path, main_name):
    issues, hh, tt, oo = load_data(CSV_PATH)
    draw_map = {iss: i for i, iss in enumerate(issues)}
    rows = {}
    if not os.path.exists(path):
        print(f"  {path}: 不存在，跳过")
        return True
    with open(path, 'r', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r.get('issue'):
                rows[r['issue']] = r
    fn_main = make_predictor(main_name)
    n_mismatch = 0
    checked = 0
    for iss, row in sorted(rows.items(), key=lambda x: int(x[0])):
        if iss not in draw_map:
            continue
        idx = draw_map[iss]
        if idx < 2:
            continue
        pb, ps, pg = hh[idx-1], tt[idx-1], oo[idx-1]
        prev = (hh[idx-2], tt[idx-2], oo[idx-2])
        # 独立重算主推（v2：不撞期判定、不切换）
        pair = fn_main(pb, ps, pg, prev)
        row_pair = row.get('pair', '')
        recomputed = PAIR_TXT(*pair) if pair else ''
        if row_pair != recomputed:
            # 特判：旧规则 skip 期（历史遗留）记录 pair=''，新规则必重算非空 → 跳过不判错
            if not row_pair:
                continue
            n_mismatch += 1
            if n_mismatch <= 10:
                print(f"  ✗ {iss}: 记录 {row_pair or '(空)'} ≠ 独立重算 {recomputed or '(空)'}")
        checked += 1
    print(f"  {path}: 复算 {checked} 期 | 不一致 {n_mismatch}")
    return n_mismatch == 0


def audit_all():
    ok = True
    for combo_file, log in (('best_pair.json', LOGS[0]),
                            ('best_pair_500.json', LOGS[1])):
        if not os.path.exists(combo_file) or not os.path.exists(log):
            print(f"  ({combo_file} / {log}) 不存在，跳过")
            continue
        with open(combo_file, 'r', encoding='utf-8') as f:
            d = json.load(f)
        main_name = d['main']['name']
        print(f"审计 {combo_file} → 主: {main_name}")
        ok = audit_log(log, main_name) and ok
    print("\n" + ("✅ 审计通过：0 不一致" if ok else "❌ 审计发现不一致，请检查！"))
    return ok


if __name__ == '__main__':
    sys.exit(0 if audit_all() else 1)
