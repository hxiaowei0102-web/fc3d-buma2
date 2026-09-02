# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 一键更新
=============================================
流程：联网补抓最新开奖(多源降级+CSV兜底) → 双窗口暴力穷举 → 回测 → 生成网页
"""
import sys, io, time, os, shutil
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

    print("\n[2/4] 双窗口暴力穷举（300期主 + 500期副）")
    import bruteforce
    bruteforce.main()

    print("\n[3/4] 回测")
    import backtest
    for win, f in ((300, 'best_pair.json'), (500, 'best_pair_500.json')):
        if os.path.exists(f):
            m = backtest.load_combo(f)
            s = backtest.run_backtest('data/fc3d-history.csv', m, n=win)['summary']
            print(f"  {win}期回测: 命中 {s['pair_hit_rate']}% ({s['hits']}/{s['valid_periods']}) "
                  f"连错{s['max_miss_streak']}期")

    print("\n[4/4] 生成网页（300/500双窗口回测）")
    os.makedirs('static', exist_ok=True)
    import gen_site
    gen_site.main(out_path='static/index.html')
    shutil.copy('static/index.html', 'index.html')  # 根目录同步，方便本地预览

    print(f"\n完成 ✓  总耗时 {time.time()-t0:.1f} 秒")
    print(f"本地预览: http://127.0.0.1:8899/index.html  (或 /static/index.html)")
