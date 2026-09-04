# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 一键更新（本地手动用）
=============================================
流程：联网补抓最新开奖(多源降级+CSV兜底) → 双窗口暴力穷举 → 回测 → 预测跟踪 → 生成网页
注意：与云端入口 auto_update.py 保持同一套流程（含预测跟踪、只产出 static/index.html，
      不再往根目录复制 index.html——根目录孤儿页曾导致手机预览读到过期页面）。
"""
import sys, io, time, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

if __name__ == '__main__':
    t0 = time.time()
    print("=" * 46)
    print("  福彩3D 两码不组 · 一键更新")
    print(f"  时间(北京): {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 46)

    print("\n[1/4] 同步最新数据（联网补抓 + CSV兜底）")
    try:
        import fetch
        fetch.sync_data()
    except Exception as e:
        print(f"  ⚠ 数据同步异常，沿用现有CSV: {str(e)[:80]}")

    print("\n[2/5] 双窗口暴力穷举（300期主 + 500期副）")
    import bruteforce
    bruteforce.main()

    print("\n[3/5] 回测")
    import backtest
    for win, f in ((300, 'best_pair.json'), (500, 'best_pair_500.json')):
        if os.path.exists(f):
            m = backtest.load_combo(f)
            s = backtest.run_backtest('data/fc3d-history.csv', m, n=win)['summary']
            print(f"  {win}期回测: 命中 {s['pair_hit_rate']}% ({s['hits']}/{s['valid_periods']}) "
                  f"连错{s['max_miss_streak']}期")

    print("\n[4/5] 双窗口每日预测跟踪（验证昨日 + 记录今日）")
    try:
        import track_predictions
        track_predictions.run_both()
    except Exception as e:
        print(f"  ⚠ 预测跟踪异常: {str(e)[:80]}")

    print("\n[5/5] 生成网页（300/500双窗口回测 + 最新跟踪看板）")
    os.makedirs('static', exist_ok=True)
    import gen_site
    gen_site.main(out_path='static/index.html')

    print(f"\n完成 ✓  总耗时 {time.time()-t0:.1f} 秒")
    print(f"本地预览: http://127.0.0.1:8899/static/index.html")
