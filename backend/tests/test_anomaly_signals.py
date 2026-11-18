"""异常检测信号表缺陷修复的回归测试。

覆盖：零方差边界、幂等、样本不足、无数据重试、中断回滚、
列表与详情一致、残留清理留档、指标定义跨模块复算消息阈值。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.store import store
from app.services.anomaly_detect import AnomalyDetectService
from app.services.metric_def import MetricDefService


def _clear_all():
    for k in list(store._tables.keys()):
        store._tables[k] = []


def _make_rule(ad: AnomalyDetectService, **overrides):
    values = {
        "规则编号": "AD-100",
        "监控指标": "点击率",
        "检测算法": "moving_average",
        "基线窗口": "7",
        "波动阈值": "0.3",
        "告警级别": "高",
        "静默时段": "0",
        "规则版本": "V026",
    }
    values.update(overrides)
    entry, missing = ad.create_entry(values)
    assert not missing, missing
    return entry


def test_zero_variance_breach_is_anomaly_and_persisted():
    """基线窗口完全相等、最新值突然越界：必须判异常并完整落信号表。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    result = ad.run_detection(entry["id"], [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.9])
    assert result["ok"], result
    assert result["is_anomaly"] is True
    assert result["verdict"] == "零方差越界"
    assert result["zero_variance"] is True
    signals = store.rows("anomaly_detect_signal")
    assert len(signals) == 1
    signal = signals[0]
    # 零方差判定与规则版本同时写入同一条记录
    assert signal["零方差"] is True
    assert signal["规则版本"] == "V026"
    assert signal["最新值"] == 0.9
    assert signal["判定"] == "零方差越界"
    assert signal["状态"] == "已确认"
    assert signal["告警级别"] == "高"
    assert "零标准差" in signal["原因"]
    assert signal["is_anomaly"] is True


def test_zero_variance_in_bounds_is_normal_but_marked():
    """基线全等且最新值一致：判正常，但零方差标记显式落库，不是静默跳过。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    result = ad.run_detection(entry["id"], [0.5, 0.5, 0.5, 0.5])
    assert result["ok"]
    assert result["is_anomaly"] is False
    assert result["verdict"] == "正常"
    signal = store.rows("anomaly_detect_signal")[0]
    assert signal["零方差"] is True
    assert signal["判定"] == "正常"


def test_same_input_returns_same_signal():
    """同一输入重复检测得到相同信号，不重复落库。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    values = [0.10, 0.12, 0.11, 0.13, 0.15, 0.14, 0.55]
    first = ad.run_detection(entry["id"], values)
    second = ad.run_detection(entry["id"], values)
    assert first["ok"] and second["ok"]
    assert first["signal"]["id"] == second["signal"]["id"]
    assert first["verdict"] == second["verdict"] == "越界"
    assert len(store.rows("anomaly_detect_signal")) == 1


def test_insufficient_samples_not_silently_normal():
    """样本不足：显式落数据不足信号、待复核，不生成已确认告警。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    result = ad.run_detection(entry["id"], [0.1, 0.9])
    assert result["ok"]
    assert result["is_anomaly"] is False
    assert result["verdict"] == "数据不足"
    assert result["state"] == "待复核"
    signal = store.rows("anomaly_detect_signal")[0]
    assert signal["判定"] == "数据不足"
    assert signal["状态"] != "已确认"


def test_no_data_records_retry_signal_and_retry_completes():
    """没有数据：记录待重试信号并说明原因；补数据重试后同一条记录转终态。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    result = ad.run_detection(entry["id"], [])
    assert result["ok"] is False
    assert result["retryable"] is True
    assert "没有监控数据" in result["message"]
    signals = store.rows("anomaly_detect_signal")
    assert len(signals) == 1
    signal = signals[0]
    assert signal["状态"] == "待重试"
    assert signal["原因"]
    # 重试：沿用同一条记录，不产生重复
    updated, message = ad.retry_signal(signal["id"], [0.5, 0.5, 0.5, 0.9])
    assert updated is not None, message
    assert updated["id"] == signal["id"]
    assert updated["状态"] == "已确认"
    assert updated["判定"] == "零方差越界"
    assert updated["重试次数"] == 1
    assert len(store.rows("anomaly_detect_signal")) == 1


def test_interrupted_detection_rolls_back_and_keeps_history(monkeypatch):
    """检测中断：事务回滚不留半截残留，已有完整信号历史不受影响。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    ok_result = ad.run_detection(entry["id"], [0.1, 0.2, 0.1, 0.2, 0.1])
    assert ok_result["ok"]
    history_before = list(store.rows("anomaly_detect_signal"))

    def boom(self, entry, values):
        raise RuntimeError("模拟中断")

    monkeypatch.setattr(AnomalyDetectService, "_evaluate", boom)
    failed = ad.run_detection(entry["id"], [0.3, 0.3, 0.3, 0.9])
    assert failed["ok"] is False
    assert failed["retryable"] is True
    assert "中断" in failed["message"]
    rows = store.rows("anomaly_detect_signal")
    # 完整历史保留 + 一条完整的待重试记录（带原因），没有缺字段的半成品
    assert len(rows) == len(history_before) + 1
    assert rows[-1]["状态"] == "待重试"
    assert "中断" in rows[-1]["原因"]
    for row in rows:
        for key in ("信号编号", "规则版本", "零方差", "判定", "状态", "指纹"):
            assert key in row


def test_list_and_detail_are_consistent():
    """工作台列表与详情页读同一张表，展示相同业务数据。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    ad.run_detection(entry["id"], [0.5, 0.5, 0.5, 0.9])
    items, total = ad.list_signals()
    assert total == 1
    detail = ad.get_signal(items[0]["id"])
    assert detail == items[0]


def test_process_pending_rolls_back_residue_with_audit():
    """V026 下发现未清残留：事务回滚删除并按版本留档核对。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    ad.run_detection(entry["id"], [0.5, 0.5, 0.5, 0.9])
    # 模拟中断留下的残缺残留（缺零方差/规则版本等关键字段）
    store.rows("anomaly_detect_signal").append(
        {"id": 999, "信号编号": "SIG-0999", "规则编号": "AD-100", "规则版本": "V026"}
    )
    report = ad.process_pending()
    assert report["ok"]
    assert report["removed"] == 1
    rows = store.rows("anomaly_detect_signal")
    assert len(rows) == 1 and rows[0]["判定"] == "零方差越界"
    audits = store.rows("anomaly_detect_signal_audit")
    assert len(audits) == 1
    assert audits[0]["规则版本"] == "V026"
    assert audits[0]["处理"] == "残留回滚"


def test_metric_def_recalc_reads_signal_table():
    """跨模块联动：指标定义读取信号表的指标标识和基线窗口，复算消息阈值。"""
    _clear_all()
    ad = AnomalyDetectService()
    md = MetricDefService()
    metric, missing = md.create_entry({
        "指标编号": "M-100",
        "指标名称": "点击率",
        "计算公式": "clicks / impressions",
        "统计粒度": "日",
        "时间窗口": "7",
        "基准取值": "0.10",
        "精度位数": "4",
        "口径版本": "v1",
    })
    assert not missing
    entry = _make_rule(ad, 监控指标="点击率", 基线窗口="4")
    ad.run_detection(entry["id"], [0.5, 0.5, 0.5, 0.5, 0.9])  # 零方差越界
    report = md.recalc_message_thresholds()
    assert report["ok"]
    assert len(report["updated"]) == 1
    updated = report["updated"][0]
    assert updated["指标编号"] == "M-100"
    assert updated["基线窗口"] == 4  # 来自信号表的基线窗口
    assert updated["越界信号数"] == 1
    # 0.10 * (1 + 1/4) = 0.125
    assert updated["消息阈值"] == 0.125
    assert metric["消息阈值"] == 0.125
    assert "异常检测信号表" in metric["消息阈值来源"]


def test_normal_breach_and_normal_case_still_work():
    """常规越界与正常样本的判定不回归。"""
    _clear_all()
    ad = AnomalyDetectService()
    entry = _make_rule(ad)
    breach = ad.run_detection(entry["id"], [0.10, 0.12, 0.11, 0.13, 0.15, 0.14, 0.55])
    assert breach["ok"] and breach["is_anomaly"] is True and breach["verdict"] == "越界"
    normal = ad.run_detection(entry["id"], [0.10, 0.12, 0.11, 0.13, 0.15, 0.14, 0.13])
    assert normal["ok"] and normal["is_anomaly"] is False and normal["verdict"] == "正常"
