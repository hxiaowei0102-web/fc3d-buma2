# -*- coding: utf-8 -*-
"""
福彩3D 两码不组 — 云端全自动更新入口（GitHub Actions 定时运行）
=============================================
流程：多源降级抓取最新开奖 → 追加到CSV → 双窗口(300主/500副)暴力穷举
      → 生成 static/index.html（部署到 GitHub Pages，页面按钮切换两窗口）→ 每日预测跟踪
幂等设计：数据与公式均无变化（且跟踪无新增）时不重写页面（含时间戳），
         workflow 的 git diff 检测不到任何变化即跳过提交与部署，零无效更新。
注意：①预测跟踪必须在 best_pair*.json 写入之后执行，否则会用旧公式记录预测。
     ②页面生成必须在预测跟踪之后执行（跟踪先写入本下期 pending，页面再嵌入），
       否则主卡片会显示"上一期"的旧预测对（曾现 2026237 页面显示 2026236 的 59/14 bug）。
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

    def _old_main(path):
        """读旧 best_pair*.json 的 (name, pair, hits)。返回 None 表示文件缺失。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                m = json.load(f).get('main', {})
                return (m.get('name'), m.get('pair'), m.get('hits'))
        except Exception:
            return None

    def _new_sig(r, combo_path):
        """比较新旧 (name, pair, hits)：任一变化都视为公式结果变化。
        只比 name 会漏掉『同公式但窗口滚动致 v_next 桶漂移、pair/hits 变化』→ 页面 stale。"""
        if r is None:
            return False
        old = _old_main(combo_path)
        if old is None:
            return True
        nm = r['main']['name']
        return (nm, r['main']['pair'], r['main']['hits']) != old

    formula_changed = _new_sig(r_main, COMBO_JSON) or _new_sig(r_sub, COMBO_500_JSON)

    # 步骤顺序（重要）：[3]跟踪 → [4]页面。
    # 跟踪先验证昨日 + 写入今日(next_issue)的 pending 预测；
    # 页面后生成，build_data 用 pred_pair(公式重算) 为主卡片，仅在跟踪已含
    # 本下期 pending 时优先采用，天然与公式一致、永不落后一期。
    print("\n[3/6] 双窗口每日预测跟踪（300 主 + 500 副 各自验证昨日 + 记录今日）")
    track_changed = False
    try:
        import track_predictions
        track_changed = track_predictions.run_both()
    except Exception as e:
        print(f"  ⚠ 预测跟踪异常（不影响主流程）: {str(e)[:80]}")

    gen_site_run = False
    data_or_formula = (added > 0) or formula_changed
    if not data_or_formula and not track_changed:
        print("\n[4/6] 数据/公式/跟踪均无变化，跳过页面生成（零无效更新）")
    else:
        print("\n[4/6] 生成网页（含300/500双窗口 + 最新跟踪看板）")
        os.makedirs('static', exist_ok=True)
        import gen_site
        gen_site.main(out_path=OUT_HTML)
        gen_site_run = True

    print("\n[5/6] 完成产物状态确认")
    if gen_site_run:
        print("  ✅ 页面已按最新数据/公式/跟踪重新生成")
    else:
        print("  — 无任何变化，页面保持原样（零无效更新）")

    print("\n[6/6] 完成")
    print(f"  总耗时 {time.time()-t0:.1f} 秒")


if __name__ == '__main__':
    main()
