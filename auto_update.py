# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 云端全自动更新入口（GitHub Actions 定时运行）
=============================================
流程：多源降级抓取最新开奖 → 追加到CSV → 双窗口(300主/500副)暴力穷举
      → 生成 static/index.html（部署到 GitHub Pages，页面按钮切换两窗口）→ 每日预测跟踪
幂等设计：数据与公式均无变化时不重写页面（含时间戳），
         workflow 的 git diff 检测不到任何变化即跳过提交与部署，零无效更新。
注意：预测跟踪必须放在 best_pair.json 写入之后执行，否则会用旧公式记录预测，
      导致跟踪日志与页面显示不一致。
"""
import sys, io, os, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

OUT_HTML = 'static/index.html'
COMBO_JSON = 'best_pair.json'
COMBO_500_JSON = 'best_pair_500.json'


def main():
    t0 = time.time()
    print("=" * 46)
    print("  福彩3D 两码不组 · 云端全自动更新")
    print(f"  时间(北京): {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 46)

    print("\n[1/6] 多源降级抓取 + 追加CSV")
    added = 0
    try:
        import fetch
        _, added = fetch.sync_data()
    except Exception as e:
        print(f"  ⚠ 数据同步异常，沿用现有CSV: {str(e)[:80]}")

    print("\n[2/6] 双窗口暴力穷举（300期主 + 500期副）")
    import bruteforce
    r_main, r_sub = bruteforce.run_multi(verbose=True)
    new_combo = r_main['main']['name'] if r_main else None
    new_combo_500 = r_sub['main']['name'] if r_sub else None

    def _old_combo(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f).get('main', {}).get('name')
        except Exception:
            return None
    formula_changed = (new_combo is not None and _old_combo(COMBO_JSON) != new_combo) or \
                      (new_combo_500 is not None and _old_combo(COMBO_500_JSON) != new_combo_500)

    gen_site_run = False
    if added == 0 and not formula_changed:
        print("\n[3/6] 数据与公式均无变化，跳过页面生成（零无效更新）")
    else:
        print("\n[3/6] 生成网页（含300/500双窗口）")
        os.makedirs('static', exist_ok=True)
        import gen_site
        gen_site.main(out_path=OUT_HTML)
        gen_site_run = True

    print("\n[4/6] 双窗口每日预测跟踪（300 主 + 500 副 各自验证昨日 + 记录今日）")
    track_changed = False
    try:
        import track_predictions
        track_changed = track_predictions.run_both()
    except Exception as e:
        print(f"  ⚠ 预测跟踪异常（不影响主流程）: {str(e)[:80]}")

    if track_changed and not gen_site_run:
        print("[5/6] 跟踪有新记录，补生成页面（含最新跟踪看板）")
        import gen_site
        gen_site.main(out_path=OUT_HTML)

    print("\n[6/6] 完成")
    print(f"  总耗时 {time.time()-t0:.1f} 秒")


if __name__ == '__main__':
    main()
