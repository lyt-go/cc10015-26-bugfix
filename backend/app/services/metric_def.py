"""指标定义业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "metric_def"
LIST_FIELDS = ["指标编号", "指标名称", "计算公式", "统计粒度", "时间窗口", "基准取值", "精度位数", "口径版本"]
REQUIRED_FIELDS = ["指标编号", "指标名称", "计算公式"]
STATUS_ORDER = ["草稿", "待校验", "已生效", "已废弃"]
ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "标记废弃": "已废弃"}
NEGATIVE_ACTIONS = []

SIGNAL_MODULE = "anomaly_detect_signal"


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _parse_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


class MetricDefService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("指标编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"指标定义 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于指标定义可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"指标定义已{action}"

    def recalc_message_thresholds(self) -> dict[str, Any]:
        """跨模块联动：读取异常检测信号表中的指标标识和基线窗口，复算消息阈值。

        按指标标识（信号表的监控指标 ↔ 指标编号/指标名称）匹配信号，
        取该指标最新信号的基线窗口，用窗口内越界信号占比上调基准取值，
        结果连同来源信号一起写回指标定义，保证可核对。
        """
        signals = store.rows(SIGNAL_MODULE)
        updated: list[dict[str, Any]] = []
        for row in store.rows(MODULE):
            keys = {str(row.get("指标编号") or ""), str(row.get("指标名称") or "")} - {""}
            related = [s for s in signals if str(s.get("监控指标") or "") in keys]
            if not related:
                continue
            latest = related[-1]
            window = max(_parse_int(latest.get("基线窗口"), _parse_int(row.get("时间窗口"), 7)), 1)
            base = _parse_float(row.get("基准取值"), 0.0)
            precision = max(_parse_int(row.get("精度位数"), 4), 0)
            breaches = sum(1 for s in related if s.get("is_anomaly"))
            threshold = round(base * (1 + breaches / window), precision)
            row["消息阈值"] = threshold
            row["消息阈值来源"] = f"异常检测信号表/{latest.get('信号编号', '')}"
            updated.append({
                "指标编号": row.get("指标编号"),
                "指标名称": row.get("指标名称"),
                "基线窗口": window,
                "越界信号数": breaches,
                "消息阈值": threshold,
            })
        return {
            "ok": True,
            "updated": updated,
            "message": f"已按异常检测信号表复算 {len(updated)} 个指标的消息阈值",
        }
