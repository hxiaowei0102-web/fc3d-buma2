# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 特征引擎 + 公式库（移植自百十个杀一码 v3 扩展版）
=============================================
特征 v1(34单期) + 单期派生9 + 跨期16（前2期三码/差分/近2期和/积）= 59 特征。
系数 (1,2,3,5) × 常数0-44，单/双/三特征线性组合 ≈ 4074万规格。
所有特征均由「上期」「上上期」计算，第i期预测只用第i-1期及更早数据，不偷看未来。

【玩法定义】两码不组 = 预测一对不同数字 (a,b)，断言下期三位开奖中 a、b 不会同时出现。
- 公式输出 v ∈ [0,45) → 查 PAIRS[v] = (a,b)，天然保证两个数字不同（a<b）。
- 命中 = 预测对 ∉ 当期同现对集合（当期出现过的任意两个不同数字组成同现对；
  开奖含重复位/豹子号时按去重后的数字集合计算——与旧版/云端「晓炜两码不组」口径一致）。
- 随机基线：当期同现对期望 2.43 个 / 45 对 → 命中率 ≈ 94.6%。
"""
from engine import load_data

FEAT_NAMES = [
    # ===== v1 单期特征（34个，上期三码 b,s,g）=====
    'b', 's', 'g',
    'b2', 's2', 'g2',
    'b3', 's3', 'g3',
    'S', 'S10', 'P', 'mx', 'mn', 'md',
    'd1', 'd2', 'd3',
    'bs', 'bg', 'sg', 'bsg',
    'S2', 'P2',
    'sum2', 'sum3', 'sum4',
    'bp', 'gp', 'sp',
    'bo', 'so', 'go', 'So',
    # ===== v2 单期派生（9个）=====
    'd12', 'd13', 'd23',      # 跨度两两乘积尾
    'mxmn', 'mxmd', 'mnmd',   # 大×小 / 大+中 / 小+中
    'S3',                     # 和值³尾
    'dsum',                   # 三差值和
    'bsg2',                   # 两两积之和尾
    # ===== v2 跨期特征（16个，前2期 bL,sL,gL）=====
    'bL', 'sL', 'gL',         # 前2期三码
    'SL', 'S10L', 'PL',       # 前2期和值 / 和尾 / 跨度
    'db', 'ds', 'dg',         # 各位较前2期差分
    'dS',                     # 和值较前2期差分
    'bh', 'sh', 'gh',         # 近2期各位之和尾
    'bpr', 'spr', 'gpr',      # 近2期各位之积尾
]
_IDX = {n: i for i, n in enumerate(FEAT_NAMES)}
NF = len(FEAT_NAMES)

# 系数集（与杀一码一致）
COEFFS = (1, 2, 3, 5)

# ===== 两码不组：45 个不组对 =====
# (a,b) 且 a<b，共 C(10,2)=45 个。公式输出 0..44 即 PAIRS[v]，天然「两个数字不重复」
PAIRS = [(a, b) for a in range(10) for b in range(a + 1, 10)]
P2I = {p: i for i, p in enumerate(PAIRS)}
MOD = 45          # 输出模（45 对索引）
N_PAIRS = len(PAIRS)
assert N_PAIRS == 45


def co_occur_pairs(b, s, g):
    """当期开奖 (b,s,g) 的「同现对」：出现过的任意两个不同数字组成（去重后）。
    返回 set(对索引)。开奖含重复位/豹子不影响（455 -> {45}；555 -> 空）。"""
    ds = {b, s, g}
    out = set()
    for a in ds:
        for c in ds:
            if a < c:
                out.add(P2I[(a, c)])
    return out


def feat_list(b, s, g, prev=None):
    """特征向量。prev=(bL,sL,gL) 为前2期三码，缺省时跨期特征用0（安全退化）"""
    if prev is None:
        bL = sL = gL = 0
    else:
        bL, sL, gL = prev
    mx = max(b, s, g); mn = min(b, s, g); md = b + s + g - mx - mn
    S = b + s + g; P = mx - mn
    SL = bL + sL + gL; PL = max(bL, sL, gL) - min(bL, sL, gL)
    d1 = abs(b - s); d2 = abs(b - g); d3 = abs(s - g)
    return [
        # v1
        b, s, g,
        b * b % 10, s * s % 10, g * g % 10,
        b * b * b % 10, s * s * s % 10, g * g * g % 10,
        S, S % 10, P, mx, mn, md,
        d1, d2, d3,
        b * s % 10, b * g % 10, s * g % 10, b * s * g % 10,
        S * S % 10, P * P % 10,
        (b + s) % 10, (s + g) % 10, (b + g) % 10,
        (1 if g == 0 else b ** g) % 10, (1 if b == 0 else g ** b) % 10, (1 if g == 0 else s ** g) % 10,
        b % 2, s % 2, g % 2, S % 2,
        # v2 单期派生
        (d1 * d2) % 10, (d1 * d3) % 10, (d2 * d3) % 10,
        (mx * mn) % 10, (mx + md) % 10, (mn + md) % 10,
        (S * S * S) % 10,
        (d1 + d2 + d3) % 10,
        (b * s + s * g + g * b) % 10,
        # v2 跨期
        bL, sL, gL,
        SL, SL % 10, PL,
        (b - bL) % 10, (s - sL) % 10, (g - gL) % 10,
        (S - SL) % 10,
        (b + bL) % 10, (s + sL) % 10, (g + gL) % 10,
        (b * bL) % 10, (s * sL) % 10, (g * gL) % 10,
    ]


def eval_linear(feats, terms, const):
    v = const
    for c, idx in terms:
        v += c * feats[idx]
    return v % MOD


def formula_name(terms, const):
    return '+'.join(f'{c}*{FEAT_NAMES[idx]}' for c, idx in terms) + f'+{const}'


def parse_linear(name):
    terms = []
    const = 0
    for part in name.split('+'):
        part = part.strip()
        if '*' in part:
            c_str, feat = part.split('*', 1)
            terms.append((int(c_str), _IDX[feat]))
        elif part.isdigit():
            const += int(part)
        else:
            terms.append((1, _IDX[part]))
    return terms, const


# 三特征组合系数（小子集控规模：C(59,3)×27×45 ≈ 3949万）
TRIPLE_COEFFS = (1, 2, 3)
CONST_RANGE = range(MOD)   # 常数 0..44（覆盖全部45个输出对）


def iter_specs(include_single=True, include_pair=True, include_triple=True):
    """流式生成全部规格（单/双/三特征），不占内存。总量约4074万。"""
    if include_single:
        for idx in range(NF):
            for c in COEFFS:
                for const in CONST_RANGE:
                    yield (((c, idx),), const)
    if include_pair:
        for i in range(NF):
            for j in range(i + 1, NF):
                for c1 in COEFFS:
                    for c2 in COEFFS:
                        for const in CONST_RANGE:
                            yield (((c1, i), (c2, j)), const)
    if include_triple:
        for i in range(NF):
            for j in range(i + 1, NF):
                for k in range(j + 1, NF):
                    for c1 in TRIPLE_COEFFS:
                        for c2 in TRIPLE_COEFFS:
                            for c3 in TRIPLE_COEFFS:
                                for const in CONST_RANGE:
                                    yield (((c1, i), (c2, j), (c3, k)), const)


def pair_of(v):
    """输出值(0..44) -> (a,b)"""
    return PAIRS[v % MOD]


def make_predictor(name):
    """把公式名编译为 (b,s,g,prev)->(a,b) 的可调用函数，用于回测与预测"""
    terms, const = parse_linear(name)

    def fn(b, s, g, prev=None, terms=terms, const=const):
        return pair_of(eval_linear(feat_list(b, s, g, prev), terms, const))
    return fn


def spec_count():
    """估算规格总数（含重复表达）"""
    n1 = NF * len(COEFFS) * MOD
    n2 = NF * (NF - 1) // 2 * len(COEFFS) ** 2 * MOD
    n3 = NF * (NF - 1) * (NF - 2) // 6 * len(TRIPLE_COEFFS) ** 3 * MOD
    return n1 + n2 + n3


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    issues, h, t, o = load_data()
    print(f"特征数: {NF} | 不组对数: {N_PAIRS}")
    print(f"规格估算(去重前): {spec_count():,}")
    f = make_predictor('1*bL+2*dg+3')
    print(f"示例: 1*bL+2*dg+3 对(上期2,9,6, 前2期3,7,3) → 预测不组对 {f(2, 9, 6, (3, 7, 3))}")
    # 验证同现对
    for draw in [(4, 5, 5), (5, 5, 5), (1, 2, 3), (0, 7, 3)]:
        idxs = co_occur_pairs(*draw)
        print(f"开奖{''.join(map(str, draw))} 同现对: {sorted(PAIRS[i] for i in idxs)}")
