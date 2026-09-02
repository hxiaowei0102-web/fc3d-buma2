# -*- coding: utf-8 -*-
"""
福彩3D 百十个杀一码 — 联网补抓（多源降级链 + CSV兜底）
=============================================
按降级链逐个尝试抓取最新开奖，抓到比本地CSV新的期号就追加进CSV；
全部失败则不中断，使用现有CSV。所有日期/期号校验严格。
"""
import csv, json, re, os

CSV_PATH = 'data/fc3d-history.csv'


# ============ HTTP ============
def _http_get(url, referer=None, timeout=20, retries=3, retry_delay=2):
    """带重试的 HTTP 获取：默认最多重试3次（间隔2秒），抗瞬断/限频/超时。
    部分源(如17500)会间歇性超时，重试后成功率显著提升。"""
    from urllib.request import urlopen, Request
    import time
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    if referer:
        headers['Referer'] = referer
    last_err = None
    for i in range(retries):
        try:
            req = Request(url, headers=headers)
            return urlopen(req, timeout=timeout).read().decode('utf-8', errors='ignore')
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(retry_delay)
    raise last_err


# ============ 各源解析（统一返回 [(issue,b,s,g,next_code), ...]） ============
def _parse_huiniao(data):
    return [(it['code'], int(it['one']), int(it['two']), int(it['three']), it.get('next_code'))
            for it in data['data']['data']['list']]


def _parse_apihz(data):
    if data.get('code') != 200:
        return []
    nums = str(data.get('number', '')).split('|')
    if len(nums) != 3:
        return []
    try:
        return [(data['qihao'], int(nums[0]), int(nums[1]), int(nums[2]), None)]
    except (KeyError, ValueError):
        return []


def _parse_17500(raw):
    draws = []
    lines = [l for l in raw.strip().split('\n') if l.strip()]
    for l in lines[-6:]:
        p = l.split()
        if len(p) >= 5 and re.match(r'^20\d{5}$', p[0]):
            draws.append((p[0], int(p[2]), int(p[3]), int(p[4]), None))
    return draws


def _parse_cwl(data):
    """中国福彩网官方接口：result[] 每项 {code:'2026234', red:'6,9,5'}"""
    draws = []
    for it in (data.get('result') or []):
        code = it.get('code', '')
        red = it.get('red', '')
        if not (re.match(r'^20\d{5}$', code) and red):
            continue
        nums = red.split(',')
        if len(nums) != 3:
            continue
        try:
            b, s, g = int(nums[0]), int(nums[1]), int(nums[2])
        except ValueError:
            continue
        if all(0 <= x <= 9 for x in (b, s, g)):
            draws.append((code, b, s, g, None))
    return draws


def _parse_html_3d(raw):
    """通用HTML兜底：抓 20xxxxx 期号 + 紧跟的三个0-9数字"""
    draws = []
    for m in re.finditer(r'(20\d{5})[^\d]{0,30}?(\d)\D+(\d)\D+(\d)', raw):
        issue, b, s, g = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        if 0 <= b <= 9 and 0 <= s <= 9 and 0 <= g <= 9:
            draws.append((issue, b, s, g, None))
    # 去重保序
    seen, out = set(), []
    for d in draws:
        if d[0] not in seen:
            seen.add(d[0]); out.append(d)
    return out


DATA_SOURCES = [
    {'name': 'cwl官方', 'kind': 'json',
     'url': 'https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=3d&issueCount=5',
     'referer': 'https://www.cwl.gov.cn/',
     'parser': _parse_cwl},
    {'name': 'huiniao', 'kind': 'json',
     'url': 'https://api.huiniao.top/interface/home/lotteryHistory?type=fcsd&page=1&limit=5',
     'parser': _parse_huiniao},
    {'name': '17500', 'kind': 'txt17500',
     'url': 'http://www.17500.cn/getData/3d.TXT'},
    {'name': 'apihz', 'kind': 'json',
     'url': 'https://cn.apihz.cn/api/caipiao/fucai3d.php?id=88888888&key=88888888',
     'parser': _parse_apihz},
]
# 2026-09-02 实测：cwl官方(最权威,新增第一主力)/huiniao(主力)/17500(备用,间歇超时已加重试)/apihz(兜底公共key限频)；
# cz89/55128/kjapi 等 2026-08 实测已失效移除


# ============ 本地CSV ============
def load_existing_rows():
    rows, out_of_order, prev = {}, False, None
    try:
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                iss = row['issue']
                try:
                    b, s, g = int(row['hundreds']), int(row['tens']), int(row['ones'])
                except (KeyError, ValueError):
                    continue
                rows[iss] = (b, s, g)
                if prev is not None and iss < prev:
                    out_of_order = True
                prev = iss
    except FileNotFoundError:
        pass
    return rows, out_of_order


def fetch_latest():
    rows, _ = load_existing_rows()
    local_last = max(rows.keys(), key=int) if rows else None
    if local_last:
        print(f"  本地最新期号: {local_last}")

    for src in DATA_SOURCES:
        try:
            raw = _http_get(src['url'], referer=src.get('referer'))
            if src['kind'] == 'json':
                draws = src['parser'](json.loads(raw))
            elif src['kind'] == 'txt17500':
                draws = _parse_17500(raw)
            elif src['kind'] == 'html':
                draws = _parse_html_3d(raw)
            else:
                draws = []

            if not draws:
                print(f"  [{src['name']}] 无数据, 尝试下一个...")
                continue
            src_latest = max(int(d[0]) for d in draws)
            if local_last and src_latest <= int(local_last):
                print(f"  [{src['name']}] 期号{src_latest}<=本地{local_last}, 无新数据, 跳过")
                continue
            print(f"  [{src['name']}] ✓ 获取{len(draws)}条, 最新{max(d[0] for d in draws)}")
            return {src['name']: draws}
        except Exception as e:
            print(f"  [{src['name']}] ✗ {str(e)[:70]}")
    print("  ❌ 所有数据源均失败或无新数据，使用现有CSV")
    return {}


def append_to_csv(new_draws, local_last=None):
    """只追加比本地最新期号更新的期号，防止乱序/伪造旧期倒灌污染历史"""
    rows, was_oos = load_existing_rows()
    if local_last is None:
        local_last = max(rows.keys(), key=int) if rows else None
    added = 0
    for item in new_draws:
        issue, b, s, g = item[0], item[1], item[2], item[3]
        if not (isinstance(issue, str) and issue.startswith('20') and 7 <= len(issue) <= 8):
            continue
        if not all(isinstance(x, int) and 0 <= x <= 9 for x in [b, s, g]):
            continue
        # 防倒灌：必须严格晚于本地最新期号
        if local_last and int(issue) <= int(local_last):
            continue
        if issue in rows:
            if rows[issue] != (b, s, g):
                print(f"  ⚠ 期号{issue}不一致 {rows[issue]} vs {(b,s,g)}，保留原值")
            continue
        rows[issue] = (b, s, g)
        added += 1
        print(f"  新增: {issue} = {b}{s}{g}")
    if added == 0 and not was_oos:
        return 0
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    with open(CSV_PATH, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['issue', 'hundreds', 'tens', 'ones'])
        for iss in sorted(rows.keys()):
            b, s, g = rows[iss]
            w.writerow([iss, b, s, g])
    return added


def sync_data():
    """一键：抓数据 → 追加CSV。返回 (next_code, added)"""
    print("[同步] 多源降级抓取最新开奖...")
    rows, _ = load_existing_rows()
    local_last = max(rows.keys(), key=int) if rows else None
    fetched = fetch_latest()
    next_code = None
    added = 0
    if fetched:
        _, draws = list(fetched.items())[0]
        latest_draw = max(draws, key=lambda d: int(d[0]))
        if len(latest_draw) > 4 and latest_draw[4]:
            next_code = str(latest_draw[4])
            print(f"  下期期号(数据源): {next_code}")
        added = append_to_csv(draws, local_last=local_last)
        print(f"  新增{added}期")
    else:
        print("  无新数据，沿用现有CSV")
    return next_code, added


if __name__ == '__main__':
    sync_data()
