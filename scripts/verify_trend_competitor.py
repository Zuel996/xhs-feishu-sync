"""线路 A 验证脚本: TrendCalculator + CompetitorAnalyzer + Pipeline离线模式。

用多日模拟数据验证:
- 日环比 (DoD) / 周环比 (WoW) 计算
- 3σ 异常检测
- 竞品排名 + 对比表
- PipelineRunner 离线模式（跳过飞书同步）
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.models import AccountSnapshot, NoteInfo, NoteSnapshot
from src.storage.sqlite import Database
from src.transformers.competitor import CompetitorAnalyzer, CompetitorRank
from src.transformers.trend_calculator import TrendCalculator

DB_PATH = "data/verify_line_a.db"

# ── 模拟数据 ──

ACCOUNTS = {
    "main_brand": {"followers_start": 35000, "growth_per_day": 60, "notes_per_day": 5},
    "competitor_a": {"followers_start": 52000, "growth_per_day": 20, "notes_per_day": 3},
    "competitor_b": {"followers_start": 28000, "growth_per_day": 45, "notes_per_day": 4},
}

NOTE_IDS = {
    "main_brand": [f"note_main_{i:03d}" for i in range(1, 51)],  # 10天×5篇
    "competitor_a": [f"note_comp_a_{i:03d}" for i in range(1, 31)],
    "competitor_b": [f"note_comp_b_{i:03d}" for i in range(1, 41)],
}


def build_test_data(db: Database, target_date: date):
    """构建10天多账号历史数据 (target_date-9 → target_date)。"""
    db.init()

    with db.session() as session:
        from src.storage.sqlite import AccountSnapshotRepo, NoteInfoRepo, NoteSnapshotRepo

        acc_repo = AccountSnapshotRepo(session)
        ni_repo = NoteInfoRepo(session)
        ns_repo = NoteSnapshotRepo(session)

        for day_offset in range(9, -1, -1):  # 从最早到最晚
            snap_date = target_date - timedelta(days=day_offset)
            days_from_start = 9 - day_offset  # 0..9

            for acc_id, cfg in ACCOUNTS.items():
                # 粉丝数线性增长
                followers = cfg["followers_start"] + cfg["growth_per_day"] * days_from_start
                following = 150 if acc_id == "main_brand" else (200 if acc_id == "competitor_a" else 180)
                total_likes = followers * 3 + days_from_start * 100
                total_collections = followers + days_from_start * 50

                # 笔记数据 — 每天固定几篇
                notes_today = []
                for n in range(cfg["notes_per_day"]):
                    note_idx = days_from_start * cfg["notes_per_day"] + n
                    note_id = NOTE_IDS[acc_id][note_idx]

                    # 笔记基础数据: 递增浏览量模拟自然增长
                    base_views = 5000 + note_idx * 200 + day_offset * 100
                    likes = int(base_views * 0.06)
                    favorites = int(base_views * 0.02)
                    comments = int(base_views * 0.005)
                    shares = int(base_views * 0.003)

                    # NoteInfo (幂等保存)
                    ni_repo.save(NoteInfo(
                        note_id=note_id,
                        account_id=acc_id,
                        title=f"笔记{note_id}",
                        note_type="image" if n % 2 == 0 else "video",
                        publish_date=snap_date,
                        url=f"https://example.com/{note_id}",
                    ))

                    note_snap = NoteSnapshot(
                        note_id=note_id,
                        account_id=acc_id,
                        snapshot_date=snap_date,
                        views=base_views,
                        likes=likes,
                        favorites=favorites,
                        comments=comments,
                        shares=shares,
                    )
                    ns_repo.save(note_snap)
                    notes_today.append(note_snap)

                # 当日总互动和总浏览
                total_interactions = sum(n.total_interactions for n in notes_today)
                total_views = sum(n.views for n in notes_today)

                acc_repo.save(AccountSnapshot(
                    account_id=acc_id,
                    snapshot_date=snap_date,
                    follower_count=followers,
                    following_count=following,
                    total_likes=total_likes,
                    total_collections=total_collections,
                    notes_published_today=cfg["notes_per_day"],
                    total_interactions_today=total_interactions,
                    total_views_today=total_views,
                ))

        session.commit()
        print(f"  ✓ 写入完成: {len(ACCOUNTS)} 账号 × 10 天 = {len(ACCOUNTS) * 10} 条快照")


# ── 验证函数 ──

def check(description: str, condition: bool, detail: str = ""):
    """验证检查。"""
    status = "✅" if condition else "❌"
    msg = f"  {status} {description}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    if not condition:
        print(f"     ⚠️ 断言失败!")
    return condition


def verify_trend_calculator(db: Database, target_date: date):
    """验证 TrendCalculator 的 DoD/WoW 计算和 3σ 异常检测。"""
    print("\n" + "=" * 60)
    print("📊 TrendCalculator 验证")
    print("=" * 60)

    calc = TrendCalculator(history_days=30, anomaly_std_threshold=3.0)
    passed = 0
    total = 0

    with db.session() as session:
        from src.storage.sqlite import AccountSnapshotRepo, NoteSnapshotRepo
        acc_repo = AccountSnapshotRepo(session)
        ns_repo = NoteSnapshotRepo(session)

        # ── 获取各账号快照 ──
        main_snap = acc_repo.get_by_account_date("main_brand", target_date)
        main_prev = acc_repo.get_previous("main_brand", target_date, offset_days=1)
        main_week = acc_repo.get_previous("main_brand", target_date, offset_days=7)
        main_history = acc_repo.get_history("main_brand", days=30)

        print(f"\n  main_brand: current={main_snap.follower_count}, "
              f"prev={main_prev.follower_count if main_prev else 'N/A'}, "
              f"week_ago={main_week.follower_count if main_week else 'N/A'}, "
              f"history={len(main_history)} days")

        # ── 测试1: 账号趋势计算 ──
        print("\n  ── 账号趋势 ──")
        trends = calc.calculate_account_trends(main_snap, main_prev, main_week, main_history)

        # DoD: 每天增长60粉丝
        total += 1; passed += check(
            "DoD 粉丝增量 = +60",
            trends.follower.dod_delta == 60,
            f"got {trends.follower.dod_delta}"
        )

        total += 1; passed += check(
            "Wow 粉丝增量 = +420 (7天×60)",
            trends.follower.wow_delta == 420,
            f"got {trends.follower.wow_delta}"
        )

        # DoD rate
        expected_dod_rate = round(60 / main_prev.follower_count * 100, 1)
        total += 1; passed += check(
            f"粉丝 DoD 增长率 = {expected_dod_rate}%",
            trends.follower.dod_rate == expected_dod_rate,
            f"got {trends.follower.dod_rate}%"
        )

        # Wow rate
        total += 1; passed += check(
            "粉丝 WoW 增长率 > 0",
            trends.follower.wow_rate > 0,
            f"got {trends.follower.wow_rate}%"
        )

        # 10天稳定增长(无突变) → 不触发异常
        total += 1; passed += check(
            "无异常标记（稳定增长）",
            not trends.has_anomaly,
            f"anomaly={trends.has_anomaly}, fields={trends.anomaly_fields}"
        )

        # ── 测试2: 3σ 异常检测 ──
        print("\n  ── 3σ 异常检测 ──")
        # 手动构造一个异常值: 在history均值±4σ处插入当前值
        history_values = [h.follower_count for h in main_history]
        import statistics
        mean = statistics.mean(history_values)
        std = statistics.stdev(history_values)
        anomalous_value = int(mean + 4 * std)  # 远超 3σ

        total += 1; passed += check(
            "历史数据 ≥ 7 天可计算 σ",
            len(history_values) >= 7,
            f"history={len(history_values)} days"
        )

        # 用 calc._calculate_trend 直接测异常值
        anomalous_trend = calc._calculate_trend(
            anomalous_value, main_snap.follower_count, main_prev.follower_count,
            history_values
        )
        total += 1; passed += check(
            "异常值触发 3σ 检测",
            anomalous_trend.is_anomalous,
            f"z_score ≈ {(anomalous_value - mean) / std:.1f} > 3.0"
        )

        # 正常值不触发
        normal_trend = calc._calculate_trend(
            main_snap.follower_count, main_prev.follower_count, main_week.follower_count,
            history_values
        )
        total += 1; passed += check(
            "正常值不触发异常",
            not normal_trend.is_anomalous,
            f"current={main_snap.follower_count}, mean={mean:.0f}, σ={std:.0f}"
        )

        # ── 测试3: 笔记趋势 ──
        print("\n  ── 笔记趋势 ──")
        note_snaps = ns_repo.get_all_for_date(target_date)
        main_notes = [n for n in note_snaps if n.account_id == "main_brand"]

        total += 1; passed += check(
            f"main_brand 当日有 {ACCOUNTS['main_brand']['notes_per_day']} 篇笔记",
            len(main_notes) == ACCOUNTS["main_brand"]["notes_per_day"],
            f"got {len(main_notes)}"
        )

        if main_notes:
            first_note = main_notes[0]
            prev_note = ns_repo.get_previous(first_note.note_id, target_date, offset_days=1)
            week_note = ns_repo.get_previous(first_note.note_id, target_date, offset_days=7)

            note_trends = calc.calculate_note_trends(first_note, prev_note, week_note)

            total += 1; passed += check(
                "笔记 views DoD > 0（自然增长）",
                note_trends.views.dod_delta > 0,
                f"DoD={note_trends.views.dod_delta}"
            )

            total += 1; passed += check(
                "笔记有 best_growing_metric",
                isinstance(note_trends.best_growing_metric, tuple),
                f"best={note_trends.best_growing_metric}"
            )

        # ── 测试4: 无历史数据的退化情况 ──
        print("\n  ── 边界情况 ──")
        empty_trends = calc.calculate_account_trends(main_snap, None, None, None)
        total += 1; passed += check(
            "无昨日数据时 DoD = current（previous=0 的退化）",
            empty_trends.follower.dod_delta == main_snap.follower_count,
            f"DoD={empty_trends.follower.dod_delta}"
        )
        total += 1; passed += check(
            "无历史数据时 has_anomaly = False",
            not empty_trends.has_anomaly,
            f"anomaly={empty_trends.has_anomaly}"
        )

    print(f"\n  📊 TrendCalculator: {passed}/{total} 通过")
    return passed, total


def verify_competitor_analyzer(db: Database, target_date: date):
    """验证 CompetitorAnalyzer 的排名和对比表。"""
    print("\n" + "=" * 60)
    print("📊 CompetitorAnalyzer 验证")
    print("=" * 60)

    analyzer = CompetitorAnalyzer()
    passed = 0
    total = 0

    with db.session() as session:
        from src.storage.sqlite import AccountSnapshotRepo, NoteSnapshotRepo
        acc_repo = AccountSnapshotRepo(session)
        ns_repo = NoteSnapshotRepo(session)

        # ── 获取全部账号当日快照 ──
        snapshots = []
        notes_by_acc = {}
        for acc_id in ACCOUNTS:
            snap = acc_repo.get_by_account_date(acc_id, target_date)
            if snap:
                snapshots.append(snap)
            all_notes = ns_repo.get_all_for_date(target_date)
            notes_by_acc[acc_id] = [n for n in all_notes if n.account_id == acc_id]

        print(f"\n  当日快照: {len(snapshots)} 个账号")
        for s in snapshots:
            n_count = len(notes_by_acc.get(s.account_id, []))
            print(f"    {s.account_id}: 粉丝={s.follower_count}, 笔记={n_count}篇, "
                  f"互动={s.total_interactions_today}, 浏览={s.total_views_today}")

        # ── 测试1: rank_by_followers ──
        print("\n  ── 粉丝排名 ──")
        rankings = analyzer.rank_by_followers(snapshots)
        total += 1; passed += check(
            "返回 3 个排名",
            len(rankings) == 3,
            f"got {len(rankings)}"
        )
        total += 1; passed += check(
            "第1名是 competitor_a（粉丝最多: 52000+）",
            rankings[0].account_id == "competitor_a" and rankings[0].rank == 1,
            f"rank1={rankings[0].account_id}({rankings[0].follower_count})"
        )
        total += 1; passed += check(
            "排名按粉丝数降序",
            all(rankings[i].follower_count >= rankings[i+1].follower_count
                for i in range(len(rankings)-1)),
            [f"{r.account_id}:{r.follower_count}" for r in rankings]
        )

        # ── 测试2: build_comparison ──
        print("\n  ── 竞品对比表 ──")
        comparison = analyzer.build_comparison(snapshots, notes_by_acc)

        total += 1; passed += check(
            "ComparisonTable 包含所有账号",
            len(comparison.rankings) == 3,
            f"got {len(comparison.rankings)}"
        )
        total += 1; passed += check(
            "sorted_by_rank 按排名升序",
            [r.rank for r in comparison.sorted_by_rank] == [1, 2, 3],
            f"ranks={[r.rank for r in comparison.sorted_by_rank]}"
        )
        total += 1; passed += check(
            "top_by_followers 按粉丝降序",
            comparison.top_by_followers[0].account_id == "competitor_a",
            f"top={comparison.top_by_followers[0].account_id}"
        )

        # 互动率验证
        total += 1; passed += check(
            "所有账号互动率 > 0",
            all(r.engagement_rate > 0 for r in comparison.rankings),
            [f"{r.account_id}:{r.engagement_rate:.1f}%" for r in comparison.rankings]
        )

        # ── 测试3: enrich_with_deltas ──
        print("\n  ── 增量补充 ──")
        # 获取昨日快照
        yesterday_snaps = {}
        week_snaps = {}
        for acc_id in ACCOUNTS:
            y = acc_repo.get_previous(acc_id, target_date, offset_days=1)
            w = acc_repo.get_previous(acc_id, target_date, offset_days=7)
            if y:
                yesterday_snaps[acc_id] = y
            if w:
                week_snaps[acc_id] = w

        enriched = analyzer.enrich_with_deltas(comparison.rankings, yesterday_snaps, week_snaps)

        total += 1; passed += check(
            "enrich 后 follower_dod ≠ 0",
            all(r.follower_dod != 0 for r in enriched),
            [f"{r.account_id}:dod={r.follower_dod}" for r in enriched]
        )

        # main_brand 每天增长60粉丝
        main_enriched = next(r for r in enriched if r.account_id == "main_brand")
        total += 1; passed += check(
            "main_brand follower_dod = +60",
            main_enriched.follower_dod == 60,
            f"got {main_enriched.follower_dod}"
        )
        total += 1; passed += check(
            "main_brand follower_wow = +420",
            main_enriched.follower_wow == 420,
            f"got {main_enriched.follower_wow}"
        )

        # ── 测试4: rank_change 展示 ──
        print("\n  ── 排名变化 ──")
        # competitor_b 增速快，可能排名上升
        comp_b = next(r for r in comparison.rankings if r.account_id == "competitor_b")
        total += 1; passed += check(
            "CompetitorRank.rank_change 属性正常",
            comp_b.rank_change in ("不变", "新") or comp_b.rank_change.startswith("+") or comp_b.rank_change.startswith("-"),
            f"rank_change='{comp_b.rank_change}'"
        )

        # ── 测试5: rank_changes_summary ──
        summary = analyzer.get_rank_changes_summary(comparison.rankings)
        total += 1; passed += check(
            "get_rank_changes_summary 返回类型正确",
            isinstance(summary, list),
            f"got {len(summary)} changes"
        )
        # 首次对比,previous_rank 都是 None → rank_change = "新"
        # 所以所有3个都会出现在summary中
        total += 1; passed += check(
            "首次对比有 3 条变化（都是新上榜）",
            len(summary) == 3,
            f"got {len(summary)} changes: {summary}"
        )

    print(f"\n  📊 CompetitorAnalyzer: {passed}/{total} 通过")
    return passed, total


def verify_pipeline_offline(target_date: date):
    """验证 PipelineRunner 离线模式不抛异常。"""
    print("\n" + "=" * 60)
    print("📊 Pipeline 离线模式验证")
    print("=" * 60)

    from src.loaders.sync_engine import SyncEngine

    passed = 0
    total = 0

    # 测试1: SyncEngine 离线模式初始化
    engine = SyncEngine()
    total += 1; passed += check(
        "SyncEngine 离线模式初始化不抛异常",
        True,
        f"enabled={engine.enabled}"
    )
    total += 1; passed += check(
        "SyncEngine.enabled = False（无飞书凭证）",
        not engine.enabled,
        f"enabled={engine.enabled}"
    )

    # 测试2: 各 sync 方法在离线模式下返回 0
    total += 1; passed += check(
        "sync_account_summary 返回 0",
        engine.sync_account_summary(None) == 0,
        ""
    )
    total += 1; passed += check(
        "sync_note_metrics 返回 0",
        engine.sync_note_metrics([]) == 0,
        ""
    )
    total += 1; passed += check(
        "sync_daily_snapshot 返回 0",
        engine.sync_daily_snapshot(None) == 0,
        ""
    )
    total += 1; passed += check(
        "sync_competitor_comparison 返回 0",
        engine.sync_competitor_comparison(None) == 0,
        ""
    )
    total += 1; passed += check(
        "sync_full_pipeline 返回全 0",
        engine.sync_full_pipeline(None, [], [], None, {}) == {
            "account_summary": 0, "note_metrics": 0, "daily_snapshot": 0
        },
        ""
    )

    print(f"\n  📊 Pipeline 离线模式: {passed}/{total} 通过")
    return passed, total


def verify_end_to_end(db: Database, target_date: date):
    """端到端验证: 从 SQLite 读取→趋势→竞品→离线同步。"""
    print("\n" + "=" * 60)
    print("📊 端到端集成验证")
    print("=" * 60)

    from src.loaders.sync_engine import SyncEngine
    from src.transformers.trend_calculator import TrendCalculator
    from src.transformers.competitor import CompetitorAnalyzer

    calc = TrendCalculator(history_days=30)
    analyzer = CompetitorAnalyzer()
    engine = SyncEngine()

    passed = 0
    total = 0

    with db.session() as session:
        from src.storage.sqlite import AccountSnapshotRepo, NoteSnapshotRepo
        acc_repo = AccountSnapshotRepo(session)
        ns_repo = NoteSnapshotRepo(session)

        # 模拟 Pipeline 的完整流程
        for acc_id in ACCOUNTS:
            snap = acc_repo.get_by_account_date(acc_id, target_date)
            prev = acc_repo.get_previous(acc_id, target_date, offset_days=1)
            week = acc_repo.get_previous(acc_id, target_date, offset_days=7)
            history = acc_repo.get_history(acc_id, days=30)

            # Step 1: 计算趋势
            trends = calc.calculate_account_trends(snap, prev, week, history)

            # Step 2: 笔记趋势
            all_notes = ns_repo.get_all_for_date(target_date)
            acc_notes = [n for n in all_notes if n.account_id == acc_id]
            note_trends_map = {}
            for ns in acc_notes:
                prev_n = ns_repo.get_previous(ns.note_id, target_date, offset_days=1)
                week_n = ns_repo.get_previous(ns.note_id, target_date, offset_days=7)
                note_trends_map[ns.note_id] = calc.calculate_note_trends(ns, prev_n, week_n)

            # Step 3: 离线同步（应返回 0 不抛异常）
            sync_result = engine.sync_full_pipeline(
                account_snapshot=snap,
                note_infos=[],  # 简化：不需要 NoteInfo
                note_snapshots=acc_notes,
                trends=trends,
                note_trends_map=note_trends_map,
            )

            total += 1; passed += check(
                f"{acc_id} 离线同步不抛异常",
                sync_result == {"account_summary": 0, "note_metrics": 0, "daily_snapshot": 0},
                f"result={sync_result}"
            )

        # 竞品对比
        snapshots = [acc_repo.get_by_account_date(aid, target_date) for aid in ACCOUNTS]
        snapshots = [s for s in snapshots if s is not None]
        notes_by_acc = {}
        all_notes = ns_repo.get_all_for_date(target_date)
        for acc_id in ACCOUNTS:
            notes_by_acc[acc_id] = [n for n in all_notes if n.account_id == acc_id]

        comparison = analyzer.build_comparison(snapshots, notes_by_acc)
        total += 1; passed += check(
            "竞品对比构建成功",
            comparison is not None and len(comparison.rankings) == 3,
            f"rankings={len(comparison.rankings)}"
        )

        cmp_result = engine.sync_competitor_comparison(comparison)
        total += 1; passed += check(
            "竞品离线同步返回 0",
            cmp_result == 0,
            f"result={cmp_result}"
        )

    print(f"\n  📊 端到端: {passed}/{total} 通过")
    return passed, total


# ── 主入口 ──

def main():
    target_date = date(2026, 7, 10)

    print("=" * 60)
    print("🚀 线路 A 验证: Trend + Competitor + Pipeline 离线模式")
    print(f"   目标日期: {target_date}")
    print(f"   测试数据库: {DB_PATH}")
    print("=" * 60)

    # 清理旧数据库
    db_path = Path(DB_PATH)
    if db_path.exists():
        db_path.unlink()
        print("\n  ♻️  清理旧数据库")

    # 构建测试数据
    db = Database(DB_PATH)
    print("\n📦 构建 10 天模拟数据...")
    build_test_data(db, target_date)

    # 逐项验证
    all_passed = 0
    all_total = 0

    p, t = verify_trend_calculator(db, target_date)
    all_passed += p; all_total += t

    p, t = verify_competitor_analyzer(db, target_date)
    all_passed += p; all_total += t

    p, t = verify_pipeline_offline(target_date)
    all_passed += p; all_total += t

    p, t = verify_end_to_end(db, target_date)
    all_passed += p; all_total += t

    # ── 总结 ──
    print("\n" + "=" * 60)
    print(f"🏁 线路 A 验证完成: {all_passed}/{all_total} 通过")
    print("=" * 60)

    if all_passed == all_total:
        print("✅ 全部验证通过！")
    else:
        print(f"⚠️ {all_total - all_passed} 项未通过，需要修复")

    # 清理
    db.engine.dispose()
    db_path.unlink()
    print(f"\n🧹 已清理测试数据库: {DB_PATH}")

    return 0 if all_passed == all_total else 1


if __name__ == "__main__":
    sys.exit(main())
