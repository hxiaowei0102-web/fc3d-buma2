# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 暴力穷举（双窗口：300期/500期，v1 移植自百十个杀一码）
=============================================
公式池：59特征 × 单/双/三特征线性组合，输出 mod 45 = 不组对索引 ≈ 4074万规格。
numpy 向量化批量计算窗口期输出（常数 0..44 广播，语义与原逐规格循环逐桶一致），
流式维护每个「下一期预测对」桶里的最优公式。

【命中判定】（与旧版不组二/云端晓炜两码不组口径一致）
  预测对 (a,b) 命中 = (a,b) 不是当期同现对（开奖号中去重后任意两个数字组成同现对）。
  向量化：M[t, v] = 当期同现对索引是否含 v；命中数 = Σ (M[t, out[t]] == False)。
  随机基线 ≈ 94.6%（当期同现对期望 2.43 / 45）。

【硬约束】
  两个数字不重复：公式输出 ∈ [0,45) 查 PAIRS → (a,b) 且 a<b，天然满足。

【分桶设计】
  每公式按 v_next（用窗口末行=当前最新一期开奖算出的下一期预测对）分桶，
  每桶只留窗口命中率最高的公式；取命中最高的一桶 = 唯一主推（无备用，永不换公式）。
  conf = 窗口内「输出对与上期同现」的期数，仅作同分裁决的稳定性弱代理（不剔除）。

产物：
  best_pair.json       最近 300 期窗口（主窗口，预测跟踪沿用）
  best_pair_500.json   最近 500 期窗口（副窗口，页面按钮切换展示）
"""
import json
import numpy as np
from engine import load_data
from formulas import feat_list, formula_name, PAIRS, co_occur_pairs, MOD, NF, COEFFS, TRIPLE_COEFFS

CSV = 'data/fc3d-history.csv'
WINDOW = 300          # 主窗口（网格扫描样本外最优：97.5%命中且稳，2026-09-02固化）
WINDOW_500 = 500      # 副窗口（样本外最稳：极差1.67pp，对照参考）
JSON_MAIN = 'best_pair.json'
JSON_500 = 'best_pair_500.json'


def search_best(hh, tt, oo, window=WINDOW, verbose=True):
    N = len(hh)
    if N < window + 1:
        raise ValueError(
            f"数据量不足：仅 {N} 期，至少需要 {window+1} 期（{window}期被预测 + 1期上期）。")
    start = N - window
    if verbose:
        print(f"穷举窗口: 第 {start+1}..{N} 条数据，共 {window} 期")

    # 特征矩阵 (window, NF)：第 k 期特征用第 k-1 期(上期)+k-2 期(前2期)
    rows = [
        feat_list(
            hh[start + k - 1], tt[start + k - 1], oo[start + k - 1],
            prev=(hh[start + k - 2], tt[start + k - 2], oo[start + k - 2]) if start + k - 2 >= 0 else None
        )
        for k in range(window)
    ]
    F = np.array(rows, dtype=np.int64)
    # 窗口末行特征 = 用当前最新一期开奖(start+window-1)算下一期预测
    F_next = np.array([feat_list(hh[start + window - 1], tt[start + window - 1],
                                 oo[start + window - 1],
                                 prev=(hh[start + window - 2], tt[start + window - 2],
                                       oo[start + window - 2]))], dtype=np.int64)

    # 当期同现布尔矩阵 M (window,45)；上期同现布尔矩阵 Mp (window,45)
    M = np.zeros((window, MOD), dtype=bool)
    Mp = np.zeros((window, MOD), dtype=bool)
    for k in range(window):
        for i in co_occur_pairs(hh[start + k], tt[start + k], oo[start + k]):
            M[k, i] = True
        if k >= 1:
            for i in co_occur_pairs(hh[start + k - 1], tt[start + k - 1], oo[start + k - 1]):
                Mp[k, i] = True

    # 45 桶：best[v] = (hits, conf, name, v)。所有桶均可发布（不再剔除撞上期）
    best = [None] * MOD
    total = 0
    ar = np.arange(window)

    # ============ 广播批量穷举（2026-09-02 优化：原逐规格 ~12min/窗口 → 批量 ~2.7min/窗口）============
    # 原理：40.74M 规格中，同一「特征组合×系数」的 45 个常数输出只需算一次 (window,45) 矩阵，
    #       Python 迭代从 40.74M 次 numpy 往返 降为 95万批 × 45 次轻量桶比较。
    # 语义与逐规格完全一致（prof5 全45桶验证 0 差异）：out=(Σc*F+const)%45、hits/conf 同口径、
    #       v_next=(Σc*F_next+const)%45 分桶、桶内按 (hits,-conf,-len(name),name) 字典序保留。
    Fm = F % MOD
    Fnm = [int(x % MOD) for x in F_next[0]]
    CN = np.arange(MOD, dtype=np.int64)

    def _upd(v, h, cf, terms, ci):
        """桶内更新：与原版比较元组 (hits, -conf, -len(name), name) 完全一致"""
        cur = best[v]
        if cur is None:
            best[v] = (h, cf, formula_name(terms, ci))
        else:
            ch, cc, cn = cur
            if h > ch or (h == ch and cf < cc):
                best[v] = (h, cf, formula_name(terms, ci))
            elif h == ch and cf == cc:
                nm = formula_name(terms, ci)
                if len(nm) < len(cn) or (len(nm) == len(cn) and nm > cn):
                    best[v] = (h, cf, nm)

    # -- 单特征: NF × |COEFFS| 批 --
    for i in range(NF):
        Fi = Fm[:, i]; fin = Fnm[i]
        for c in COEFFS:
            base = (Fi * c) % MOD
            outs = (base[:, None] + CN[None, :]) % MOD
            hits = window - M[ar[:, None], outs].sum(axis=0)
            confs = Mp[ar[:, None], outs].sum(axis=0)
            vn = (fin * c + CN) % MOD
            terms = ((c, i),)
            hl = hits.tolist(); cl = confs.tolist(); vl = vn.tolist()
            for ci in range(MOD):
                _upd(vl[ci], hl[ci], cl[ci], terms, ci)
            total += MOD

    # -- 双特征: C(NF,2) × |COEFFS|² 批 --
    for i in range(NF):
        Fi = Fm[:, i]; fin = Fnm[i]
        for j in range(i + 1, NF):
            Fj = Fm[:, j]; fjn = Fnm[j]
            for c1 in COEFFS:
                p1 = (Fi * c1) % MOD
                for c2 in COEFFS:
                    base = (p1 + (Fj * c2)) % MOD
                    outs = (base[:, None] + CN[None, :]) % MOD
                    hits = window - M[ar[:, None], outs].sum(axis=0)
                    confs = Mp[ar[:, None], outs].sum(axis=0)
                    bn = (fin * c1 + fjn * c2) % MOD
                    vn = (bn + CN) % MOD
                    terms = ((c1, i), (c2, j))
                    hl = hits.tolist(); cl = confs.tolist(); vl = vn.tolist()
                    for ci in range(MOD):
                        _upd(vl[ci], hl[ci], cl[ci], terms, ci)
                    total += MOD

    # -- 三特征: C(NF,3) × |TRIPLE_COEFFS|³ 批 --
    for i in range(NF):
        Fi = Fm[:, i]; fin = Fnm[i]
        for j in range(i + 1, NF):
            Fj = Fm[:, j]; fjn = Fnm[j]
            for k in range(j + 1, NF):
                Fk = Fm[:, k]; fkn = Fnm[k]
                for c1 in TRIPLE_COEFFS:
                    p1 = (Fi * c1) % MOD
                    for c2 in TRIPLE_COEFFS:
                        p2 = (Fj * c2) % MOD
                        for c3 in TRIPLE_COEFFS:
                            base = (p1 + p2 + (Fk * c3)) % MOD
                            outs = (base[:, None] + CN[None, :]) % MOD
                            hits = window - M[ar[:, None], outs].sum(axis=0)
                            confs = Mp[ar[:, None], outs].sum(axis=0)
                            bn = (fin * c1 + fjn * c2 + fkn * c3) % MOD
                            vn = (bn + CN) % MOD
                            terms = ((c1, i), (c2, j), (c3, k))
                            hl = hits.tolist(); cl = confs.tolist(); vl = vn.tolist()
                            for ci in range(MOD):
                                _upd(vl[ci], hl[ci], cl[ci], terms, ci)
                            total += MOD

    ranked = sorted([(b[0], -b[1], len(b[2]), b[2], i) for i, b in enumerate(best) if b],
                    key=lambda x: (-x[0], x[1], x[2], x[3]))
    if verbose:
        print(f"  遍历公式规格: {total:,} 条 | 有公式的桶: {sum(1 for b in best if b)}/45")
    out = []
    for hits, neg_conf, _, name, v in ranked[:1]:   # 唯一主推（无备用）
        pair = PAIRS[v]
        out.append({'name': name, 'pair': f"{pair[0]}{pair[1]}",
                    'rate': hits / window, 'hits': hits, 'conf': -neg_conf,
                    'next_pair': f"{pair[0]}{pair[1]}"})
        if verbose:
            print(f"  top: {name}  预测不组 {pair[0]}{pair[1]}  "
                  f"命中 {hits}/{window} = {hits/window*100:.2f}%  (上期冲突{-neg_conf}期)")
    return out, total


def build_result(tops, pool_size, issues, window):
    """组装 best_pair*.json 结构。tops 仅含唯一主推（无备用）。"""
    main = tops[0]
    return {
        'window': window,
        'data_info': {'n_issues': len(issues), 'first': issues[0], 'last': issues[-1]},
        'pool_size': pool_size,
        'main': main,
        'rate': round(main['rate'] * 100, 2),
    }


def run_multi(verbose=True):
    """双窗口穷举：300→best_pair.json(主)，500→best_pair_500.json(副)。"""
    issues, hh, tt, oo = load_data(CSV)
    N = len(issues)
    if verbose:
        print(f"数据 {N} 期：{issues[0]} ~ {issues[-1]}")

    r_main = r_sub = None
    if N >= WINDOW + 1:
        tops, pool = search_best(hh, tt, oo, WINDOW, verbose)
        r_main = build_result(tops, pool, issues, WINDOW)
        with open(JSON_MAIN, 'w', encoding='utf-8') as f:
            json.dump(r_main, f, ensure_ascii=False, indent=2)
        if verbose:
            print(f"已写入 {JSON_MAIN}")

    if N >= WINDOW_500 + 1:
        tops, pool = search_best(hh, tt, oo, WINDOW_500, verbose)
        r_sub = build_result(tops, pool, issues, WINDOW_500)
        with open(JSON_500, 'w', encoding='utf-8') as f:
            json.dump(r_sub, f, ensure_ascii=False, indent=2)
        if verbose:
            print(f"已写入 {JSON_500}")
    else:
        if verbose:
            print(f"数据 {N} 期 < {WINDOW_500}+1，跳过500期窗口")
    return r_main, r_sub


def _combo_str(r):
    m = r['main']
    return f"{m['name']} → 不组{m['pair']} ({r['rate']}%)"


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    r_main, r_sub = run_multi()
    if r_main:
        print(f"\n主窗口{WINDOW}期: {_combo_str(r_main)}")
    if r_sub:
        print(f"副窗口{WINDOW_500}期: {_combo_str(r_sub)}")


if __name__ == '__main__':
    main()
