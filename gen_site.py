# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 生成自包含静态网页
=============================================
风格复刻 D:\\百十个杀一码\\gen_site.py（紫色渐变头部+黄色横幅+蓝色数字方块+绿红回测表），
适配「两码不组」玩法：
- 预测卡片展示两个数字方块 = 不组两码（a,b 两个数字不同）
- 命中语义：开奖号中 a、b 不同时出现 → ✓中；同时出现 → ✗错
- 双窗口切换（300期/500期），各窗口独立公式 + 独立跟踪日志
- 随机基线 ≈ 94.6%（当期平均同现 2.43/45 对）
"""
import json
import datetime
from datetime import timezone, timedelta
import backtest
import track_predictions
from engine import load_data

BJT = timezone(timedelta(hours=8))
CSV_PATH = 'data/fc3d-history.csv'

# 特征名 → 白话说明（与百十个杀一码一致）
FEAT_ZH = {
    'b': '上期百位', 's': '上期十位', 'g': '上期个位',
    'b2': '百位²尾', 's2': '十位²尾', 'g2': '个位²尾',
    'b3': '百位³尾', 's3': '十位³尾', 'g3': '个位³尾',
    'S': '和值', 'S10': '和尾', 'P': '跨度', 'mx': '最大码', 'mn': '最小码', 'md': '中间码',
    'd1': '|百-十|', 'd2': '|百-个|', 'd3': '|十-个|',
    'bs': '百×十尾', 'bg': '百×个尾', 'sg': '十×个尾', 'bsg': '三码积尾',
    'S2': '和值²尾', 'P2': '跨度²尾',
    'sum2': '(百+十)尾', 'sum3': '(十+个)尾', 'sum4': '(百+个)尾',
    'bp': '百^个尾', 'gp': '个^百尾', 'sp': '十^个尾',
    'bo': '百奇偶', 'so': '十奇偶', 'go': '个奇偶', 'So': '和奇偶',
    'd12': '|百-十|×|百-个|尾', 'd13': '|百-十|×|十-个|尾', 'd23': '|百-个|×|十-个|尾',
    'mxmn': '大×小尾', 'mxmd': '大+中', 'mnmd': '小+中',
    'S3': '和值³尾', 'dsum': '三差值和', 'bsg2': '两两积和尾',
    'bL': '前2期百位', 'sL': '前2期十位', 'gL': '前2期个位',
    'SL': '前2期和值', 'S10L': '前2期和尾', 'PL': '前2期跨度',
    'db': '百位较前2期差', 'ds': '十位较前2期差', 'dg': '个位较前2期差',
    'dS': '和值较前2期差',
    'bh': '近2期百位和尾', 'sh': '近2期十位和尾', 'gh': '近2期个位和尾',
    'bpr': '近2期百位积尾', 'spr': '近2期十位积尾', 'gpr': '近2期个位积尾',
}

WINDOW_CONFIG = [
    {'file': 'best_pair.json', 'win': 300, 'label': '300期', 'log': 'predictions_log.csv'},
    {'file': 'best_pair_500.json', 'win': 500, 'label': '500期', 'log': 'predictions_log_500.csv'},
]


def explain(formula):
    parts = []
    for seg in formula.split('+'):
        seg = seg.strip()
        if '*' in seg:
            c, f = seg.split('*', 1)
            zh = FEAT_ZH.get(f, f)
            parts.append(zh if c == '1' else f'{c}×{zh}')
        elif seg.isdigit():
            if seg != '0':
                parts.append(seg)
        else:
            parts.append(FEAT_ZH.get(seg, seg))
    return ' + '.join(parts) + '，结果查45对表( mod 45 )得两码'


def build_data():
    issues, hh, tt, oo = load_data(CSV_PATH)
    latest = issues[-1]
    last_draw = ''.join(map(str, [hh[-1], tt[-1], oo[-1]]))

    windows = {}
    pool_main = None
    for cfg in WINDOW_CONFIG:
        try:
            with open(cfg['file'], 'r', encoding='utf-8') as f:
                bf = json.load(f)
            main = bf['main']
            pool_main = pool_main or bf.get('pool_size')
        except Exception:
            continue
        bt = backtest.run_backtest(CSV_PATH, main['name'], n=cfg['win'])
        s = bt['summary']
        rows = [{
            'issue': r['issue'], 'draw': ''.join(map(str, r['draw'])),
            'pair': r['pair'] or '-', 'hit': r['hit'], 'status': r['status'],
        } for r in bt['results']]
        pn = backtest.predict_next(CSV_PATH, main['name'])
        windows[cfg['win']] = {
            'window': cfg['win'],
            'main': main,
            'formula_main': main['name'],
            'formula_backup': '',
            'explain_main': explain(main['name']),
            'explain_backup': '',
            's': {'rate': s['pair_hit_rate'], 'hits': s['hits'],
                  'valid': s['valid_periods'], 'total': s['total_periods'],
                  'skips': s['skips']},
            'max_miss_streak': s['max_miss_streak'],
            'rows': rows,
            'next_issue': pn['next_issue'],
            'last_issue': pn['last_issue'],
            'last_draw': pn['last_draw'],
            'pred_pair': pn['pair'],
            'pred_source': pn['source'],
        }
        # 独立跟踪看板（同百十个方案：每窗口独立 pending 优先，公式重算兜底）
        d = windows[cfg['win']]
        try:
            tk_rows = sorted(track_predictions._load_log(cfg['log']).values(),
                             key=lambda x: int(x['issue']))
            d['track'] = _track_block(tk_rows, cfg['log'])
            pend = [r for r in tk_rows if r.get('status') == 'pending']
            if pend:
                lp = pend[-1]
                d['pair'], d['src'] = lp.get('pair', ''), 'track'
            else:
                d['pair'], d['src'] = d['pred_pair'], 'formula'
        except Exception as e:
            d['track'] = {'summary': None, 'rows': [], 'error': str(e)[:60]}
            d['pair'], d['src'] = d['pred_pair'], 'formula'
    d300 = windows.get(300)          # 主窗口（固化300）
    d_base = windows.get(500) or d300
    base = d300 or d_base             # 页面基准信息取主窗口300
    return {
        'data_info': {'n_issues': len(issues), 'first': issues[0], 'last': issues[-1]},
        'next_issue': base['next_issue'] if base else '',
        'last_issue': latest,
        'last_draw': last_draw,
        'updated': datetime.datetime.now(BJT).strftime('%Y-%m-%d %H:%M'),
        'pool_size': pool_main,
        'windows': windows,
    }


def _track_block(tk_rows, log_path):
    try:
        track_sum = track_predictions.summarize(path=log_path)
    except Exception:
        track_sum = None
    recent30 = tk_rows[-30:][::-1]
    return {
        'summary': track_sum,
        'rows': [{
            'issue': r['issue'], 'pair': r.get('pair', ''),
            'draw': r.get('draw', ''), 'status': r.get('status', ''),
            'source': r.get('source', ''),
            'hit': r.get('hit', ''),
            'predicted_at': r.get('predicted_at', ''),
            'verified_at': r.get('verified_at', ''),
        } for r in recent30],
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>福彩3D 两码不组 · 暴力穷举300/500期</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #f0f2f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 14px; color: #333; }
.container { max-width: 480px; margin: 0 auto; padding: 10px; }
.header { background: linear-gradient(135deg, #5b3cc4 0%, #7b5fe0 100%); color: #fff; padding: 14px 16px; border-radius: 10px; margin-bottom: 10px; }
.header h1 { font-size: 1.1rem; }
.header .sub { font-size: .72rem; opacity: .85; margin-top: 2px; line-height: 1.5; }
.banner { background: #fff8e1; border: 1.5px solid #ffc107; border-radius: 8px; padding: 12px; text-align: center; margin-bottom: 8px; }
.banner .issue { font-size: 1.4rem; font-weight: 700; color: #e65100; }
.banner .last { font-size: .75rem; color: #856404; margin-top: 2px; }
.banner .time { font-size: .65rem; color: #999; }
.win-switch { display: flex; gap: 6px; margin-bottom: 8px; }
.wb { flex: 1; padding: 9px 0; border: 1.5px solid #d5d5e0; background: #fff; border-radius: 8px; font-size: .85rem; font-weight: 700; color: #666; cursor: pointer; transition: all .15s; }
.wb.on { background: #5b3cc4; border-color: #5b3cc4; color: #fff; box-shadow: 0 1px 5px rgba(91,60,196,.3); }
.wb:active { transform: scale(.97); }
.pair-grid { display: flex; justify-content: center; gap: 14px; align-items: center; margin: 12px 0; }
.pair-card { background: #fff; border-radius: 10px; padding: 14px 18px; text-align: center; box-shadow: 0 1px 5px rgba(0,0,0,.07); }
.pair-card .pos-label { font-size: .72rem; color: #888; }
.pair-card .num { width: 54px; height: 54px; border-radius: 12px; display: inline-flex; align-items: center; justify-content: center; font-size: 1.7rem; font-weight: 800; background: #e3f2fd; color: #1565c0; margin-top: 8px; box-shadow: inset 0 -2px 0 rgba(21,101,192,.18); }
.pair-sep { font-size: 1.2rem; color: #bbb; font-weight: 700; }
.pair-badge { text-align: center; font-size: .68rem; color: #6a1b9a; background: #f3e5f5; border-radius: 12px; display: inline-block; padding: 3px 10px; margin-bottom: 8px; }
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin-bottom: 8px; }
.stat { background: #fff; border-radius: 6px; padding: 8px 4px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,.05); }
.stat .val { font-size: 1.1rem; font-weight: 700; }
.stat .val.g { color: #2e7d32; }
.stat .val.o { color: #e65100; }
.stat .lbl { font-size: .62rem; color: #999; margin-top: 1px; }
.stat-main { background: #e8f5e9; }
.stat-main .val { font-size: 1.25rem; }
.table-wrap { background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.06); margin-bottom: 8px; }
.table-wrap h3 { font-size: .85rem; padding: 8px 12px; border-bottom: 1px solid #eee; }
.scroll { max-height: 440px; overflow: auto; -webkit-overflow-scrolling: touch; }
.tbl { width: 100%; border-collapse: collapse; font-size: .7rem; }
.tbl th { background: #fafafa; position: sticky; top: 0; padding: 6px 4px; font-size: .64rem; color: #666; white-space: nowrap; }
.tbl td { padding: 5px 3px; text-align: center; border-bottom: 1px solid #f0f0f0; }
.tbl td.pair { font-weight: 700; color: #1565c0; }
.tr-hit { border-left: 3px solid #4caf50; }
.tr-miss { border-left: 3px solid #f44336; }
.badge-y { color: #2e7d32; font-weight: 700; }
.badge-n { color: #c62828; font-weight: 700; }
.info { background: #fff; border-radius: 8px; padding: 12px; box-shadow: 0 1px 4px rgba(0,0,0,.06); margin-bottom: 8px; }
.info h3 { font-size: .85rem; margin-bottom: 6px; }
.algo { font-size: .68rem; padding: 6px 8px; background: #f5f5f5; border-radius: 4px; line-height: 1.6; margin-bottom: 5px; }
.algo b { color: #5b3cc4; }
.algo .f { color: #333; }
.algo .zh { color: #999; font-size: .64rem; display: block; margin-top: 2px; }
.foot { text-align: center; font-size: .65rem; color: #bbb; padding: 10px 0; line-height: 1.6; }
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>福彩3D 两码不组</h1>
  <div class="sub">暴力穷举 · 预测两码不同时出现 · <span id="subWin">300</span>/500期双窗口可切换</div>
</div>
<div class="banner">
  <div class="issue" id="predIssue">-</div>
  <div class="last" id="lastInfo"></div>
  <div class="time" id="updateTime"></div>
</div>
<div class="win-switch">
  <button class="wb on" id="winBtn300" onclick="switchWin(300)">近300期</button>
  <button class="wb" id="winBtn500" onclick="switchWin(500)">近500期</button>
</div>
<div class="pair-grid">
  <div class="pair-card"><div class="pos-label">不组数字一</div><span class="num" id="pk1">-</span></div>
  <div class="pair-sep">/</div>
  <div class="pair-card"><div class="pos-label">不组数字二</div><span class="num" id="pk2">-</span></div>
</div>
<div style="text-align:center"><span class="pair-badge" id="srcBadge">-</span></div>
<div class="stats">
  <div class="stat stat-main"><div class="val g" id="sRate">-</div><div class="lbl">★窗口内回测命中</div></div>
  <div class="stat"><div class="val" id="sHits">-</div><div class="lbl">命中/验证</div></div>
  <div class="stat"><div class="val" id="sStreak">-</div><div class="lbl">连错max</div></div>
  <div class="stat"><div class="val" id="sTotal">-</div><div class="lbl">回测期数</div></div>
</div>
<div class="stats" style="grid-template-columns:repeat(3,1fr)">
  <div class="stat"><div class="val" id="sPool">-</div><div class="lbl">穷举公式数</div></div>
  <div class="stat"><div class="val" id="sBase">94.6%</div><div class="lbl">随机基线</div></div>
  <div class="stat"><div class="val" id="winVal">300</div><div class="lbl">当前窗口</div></div>
</div>
<div class="table-wrap">
  <h3>回测明细 <span style="font-size:.65rem;color:#999">(逐期真实预测 · 最新在前)</span></h3>
  <div class="scroll">
    <table class="tbl">
      <thead><tr><th>期号</th><th>开奖</th><th>不组两码</th><th>结果</th></tr></thead>
      <tbody id="btBody"></tbody>
    </table>
  </div>
</div>
<div class="info">
  <h3>最优公式（暴力穷举·<span id="algoWin">300</span>期窗口）</h3>
  <div id="algoList"></div>
  <div style="font-size:.68rem;color:#888;margin-top:8px;line-height:1.6">
    命中 = 开奖号中预测两码<b>不同时出现</b>。随机基线 ≈ 94.6%（当期平均同现 2.43/45 对）。
    公式输出 ∈ 0..44 查 45 对表，天然保证两数字不同。本窗口命中 <b id="allVal">-</b>。
  </div>
</div>
<div class="table-wrap">
  <h3>📈 每日预测跟踪 · 近<span id="tkWin">300</span>期 <span style="font-size:.65rem;color:#999">(开奖前记录 · 开奖后回填 · 各窗口独立)</span></h3>
  <div class="stats" style="margin:8px 4px;grid-template-columns:1fr 1fr 1fr">
    <div class="stat stat-main"><div class="val g" id="tkAll">-</div><div class="lbl">★命中率(已验证)</div></div>
    <div class="stat"><div class="val" id="tkVerified">-</div><div class="lbl">已验证期数</div></div>
    <div class="stat"><div class="val" id="tkPending">-</div><div class="lbl">待开奖</div></div>
  </div>
  <div class="stats" style="margin:8px 4px;grid-template-columns:1fr 1fr 1fr">
    <div class="stat"><div class="val o" id="tkLive">-</div><div class="lbl">真实跟踪命中</div></div>
    <div class="stat"><div class="val" id="tkMaxMiss">-</div><div class="lbl">最大连错</div></div>
    <div class="stat"><div class="val" id="tkRecent30">-</div><div class="lbl">近30期命中</div></div>
  </div>
  <div style="padding:0 12px 8px;font-size:.62rem;color:#999;line-height:1.6">
    预测在<b>开奖前落盘</b>（第i期只用第i-1/i-2期数据），开奖后自动回填判定。<b>真实跟踪</b>从启用日起逐期累计，
    是唯一的样本外指标；历史回填=公式拟合窗口，数字偏乐观。<br>300期与500期<b>各自独立跟踪</b>（独立日志、独立公式），
    切换上方窗口即切换对应跟踪看板。
  </div>
  <div class="scroll" style="max-height:280px">
    <table class="tbl">
      <thead><tr><th>期号</th><th>不组两码</th><th>开奖</th><th>结果</th><th>类型</th></tr></thead>
      <tbody id="tkBody"></tbody>
    </table>
  </div>
</div>
<div class="foot">
  仅供研究参考 · 不构成投注建议 · 近N期为暴力穷举最优结果，属历史拟合，样本外会回落<br>
  数据截止 <span id="dataInfo"></span> 期
</div>
</div>
<script>
const P = __DATA__;
const W = P.windows || {};
let CUR = (300 in W) ? 300 : ((500 in W) ? 500 : null);

function render(w) {
  const D = W[w];
  if (!D) return;
  CUR = w;
  const pair = D.pair || '';
  document.getElementById('pk1').textContent = pair ? pair[0] : '-';
  document.getElementById('pk2').textContent = pair ? pair[1] : '-';
  document.getElementById('srcBadge').textContent = (D.src === 'track' ? '★开奖前真实记录' : '主公式计算');
  document.getElementById('sRate').textContent = D.s.rate + '%';
  document.getElementById('sHits').textContent = D.s.hits + '/' + D.s.valid;
  document.getElementById('sStreak').textContent = D.max_miss_streak + '期';
  document.getElementById('sTotal').textContent = D.s.total + '期';
  document.getElementById('sPool').textContent = P.pool_size >= 10000 ? (P.pool_size/10000).toFixed(1) + '万' : P.pool_size;
  document.getElementById('winVal').textContent = w;
  document.getElementById('subWin').textContent = w;
  document.getElementById('algoWin').textContent = w;
  document.getElementById('tkWin').textContent = w;
  document.getElementById('allVal').textContent = D.s.rate + '%';
  document.getElementById('winBtn500').className = 'wb' + (w === 500 ? ' on' : '');
  document.getElementById('winBtn300').className = 'wb' + (w === 300 ? ' on' : '');
  let algoHtml =
    '<div class="algo"><b>主公式</b> <span class="f">' + D.formula_main + '</span><span class="zh">' + D.explain_main + '</span></div>';
  document.getElementById('algoList').innerHTML = algoHtml;
  const tbody = document.getElementById('btBody');
  tbody.innerHTML = '';
  D.rows.forEach(function(r) {
    const tr = document.createElement('tr');
    tr.className = r.hit ? 'tr-hit' : 'tr-miss';
    tr.innerHTML =
      '<td>' + r.issue + '</td><td><b>' + r.draw + '</b></td>' +
      '<td class="pair">' + r.pair + '</td>' +
      '<td class="' + (r.hit === true ? 'badge-y' : 'badge-n') + '">' + (r.hit ? '✓中' : '✗错') + '</td>';
    tbody.appendChild(tr);
  });
  renderTrack(D);
}
function renderTrack(D) {
  const tk = D.track || {};
  const s = tk.summary;
  if (s) {
    document.getElementById('tkAll').textContent = s.hit_rate + '%';
    document.getElementById('tkVerified').textContent = s.verified + '期';
    document.getElementById('tkPending').textContent = s.pending + '期';
    document.getElementById('tkLive').textContent = s.live && s.live.verified > 0 ? (s.live.hit_rate + '%/' + s.live.verified + '期') : '0%';
    document.getElementById('tkMaxMiss').textContent = s.max_miss_streak + '期';
    document.getElementById('tkRecent30').textContent = s.recent30 + '%';
  }
  const tbody = document.getElementById('tkBody');
  tbody.innerHTML = '';
  (tk.rows || []).forEach(function(r) {
    const tr = document.createElement('tr');
    let cls = '', lbl = r.status;
    if (r.status === 'hit') { cls = 'tr-hit'; lbl = '✓命中'; }
    else if (r.status === 'miss') { cls = 'tr-miss'; lbl = '✗失误'; }
    else { cls = 'tr-miss'; lbl = '⏳待开奖'; }   // 历史遗留 skip 行按旧数据处理
    tr.className = cls;
    tr.innerHTML =
      '<td>' + r.issue + '</td><td class="pair">' + (r.pair || '-') + '</td>' +
      '<td><b>' + (r.draw || '-') + '</b></td>' +
      '<td class="' + (r.status === 'hit' ? 'badge-y' : 'badge-n') + '">' + lbl + '</td>' +
      '<td>' + (r.source === 'live' ? '真实' : '回填') + '</td>';
    tbody.appendChild(tr);
  });
}
function switchWin(w) { if (W[w]) render(w); }

render(CUR);
document.getElementById('predIssue').textContent = P.next_issue;
document.getElementById('lastInfo').textContent = '上期 ' + P.last_issue + ' = ' + P.last_draw;
document.getElementById('updateTime').textContent = '更新 ' + P.updated;
document.getElementById('dataInfo').textContent = P.data_info.last;
</script>
</body>
</html>
"""


def main(out_path='index.html'):
    data = build_data()
    data_json = json.dumps(data, ensure_ascii=False)
    html = HTML_TEMPLATE.replace('__DATA__', data_json)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✅ 已生成 {out_path} ({len(html)} 字节)")
    for w, d in data.get('windows', {}).items():
        print(f"  [{w}期] 不组{d['pair']}({d.get('src','')}) | "
              f"命中{d['s']['rate']}% ({d['s']['hits']}/{d['s']['valid']}) | "
              f"连错{d['max_miss_streak']}期")
    print(f"数据: {data['data_info']['first']}~{data['data_info']['last']} | 下期 {data['next_issue']}")


if __name__ == '__main__':
    main()
