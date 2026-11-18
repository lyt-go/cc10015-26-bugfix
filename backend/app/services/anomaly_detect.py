"""异常检测业务规则：状态流转、字段校验与筛选口径都收在这里。

检测信号表（anomaly_detect_signal）约定：
- 每次检测产出一条完整信号，零方差判定与规则版本在同一事务里原子写入，
  读取侧只读落库结果、不重算，避免刷新后同一越界值被改判为正常。
- 同一输入（规则 + 规则版本 + 监控序列）指纹去重，重复检测返回同一条信号。
- 零方差与样本不足都显式落信号，绝不静默当成正常样本；样本不足不生成已确认告警。
- 没有数据、计算失败或中断时写入完整的待重试信号并说明原因，可重试；
  中断时事务回滚，信号表只保留完整历史，不留空数据残留。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "anomaly_detect"
LIST_FIELDS = ["规则编号", "监控指标", "检测算法", "基线窗口", "波动阈值", "告警级别", "静默时段", "规则版本"]
REQUIRED_FIELDS = ["规则编号", "监控指标", "检测算法"]
STATUS_ORDER = ["草稿", "待校验", "已生效", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "标记生效": "已生效", "停用规则": "已停用"}
NEGATIVE_ACTIONS = ["停用规则"]

# 异常检测信号表
SIGNAL_MODULE = "anomaly_detect_signal"
SIGNAL_AUDIT_MODULE = "anomaly_detect_signal_audit"
# 落库前必须齐全的键；缺键即视为中断残留的半成品，按事务残留处理
SIGNAL_REQUIRED_KEYS = ["信号编号", "规则ID", "规则编号", "监控指标", "规则版本", "零方差", "判定", "状态", "指纹"]
MIN_SAMPLES = 3
DEFAULT_WINDOW = 7
DEFAULT_THRESHOLD = 0.3
DEFAULT_RULE_VERSION = "V001"

# 判定结论
VERDICT_NORMAL = "正常"
VERDICT_BREACH = "越界"
VERDICT_ZERO_VARIANCE_BREACH = "零方差越界"
VERDICT_INSUFFICIENT = "数据不足"
VERDICT_PENDING_RETRY = "待重试"
# 信号状态
STATE_CONFIRMED = "已确认"
STATE_REVIEW = "待复核"
STATE_RETRY = "待重试"
FINAL_STATES = {STATE_CONFIRMED, STATE_REVIEW}


def _parse_int(value: Any, default: int) -> int:
    """宽松解析整数：兼容 '7'、'7.0'、7 等写法，失败回默认值。"""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _parse_float(value: Any, default: float) -> float:
    """宽松解析浮点：兼容 '0.3'、0.3 等写法，失败回默认值。"""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _fingerprint(rule_id: int, rule_version: str, values: list[float]) -> str:
    """同一输入得到同一指纹：规则、规则版本与监控序列共同决定一条信号。"""
    payload = json.dumps(
        {"rule": rule_id, "version": rule_version, "values": list(values)},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


class AnomalyDetectService:
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
            rows = [row for row in rows if keyword.casefold() in str(row.get("规则编号", "")).casefold()]
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
            return None, f"检测规则 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于异常检测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"检测规则已{action}"

    # ------------------------------------------------------------------
    # 异常检测信号表
    # ------------------------------------------------------------------
    def list_signals(
        self,
        *,
        keyword: str | None = None,
        verdict: str | None = None,
        state: str | None = None,
        rule_version: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """信号工作台数据源；详情接口读同一张表，保证列表与详情一致。"""
        rows = list(store.rows(SIGNAL_MODULE))
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("规则编号", "")).casefold()]
        if verdict:
            rows = [row for row in rows if row.get("判定") == verdict]
        if state:
            rows = [row for row in rows if row.get("状态") == state]
        if rule_version:
            rows = [row for row in rows if str(row.get("规则版本", "")) == rule_version]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_signal(self, signal_id: int) -> dict[str, Any] | None:
        return store.find(SIGNAL_MODULE, signal_id)

    def _find_signal_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        return store.find_by_field(SIGNAL_MODULE, "指纹", fingerprint)

    def _new_signal(
        self,
        entry: dict[str, Any],
        values: list[float],
        *,
        verdict: str,
        state: str,
        reason: str,
        latest: float | None,
        mean: float | None,
        std: float | None,
        deviation: float | None,
        zero_variance: bool,
        is_anomaly: bool,
        window: int,
        threshold: float,
        retries: int = 0,
    ) -> dict[str, Any]:
        """组装一条完整信号：零方差判定与规则版本在这里同时落字段。"""
        signal_id = store.next_id(SIGNAL_MODULE)
        rule_version = str(entry.get("规则版本") or DEFAULT_RULE_VERSION)
        return {
            "id": signal_id,
            "信号编号": f"SIG-{signal_id:04d}",
            "规则ID": int(entry.get("id", 0)),
            "规则编号": str(entry.get("规则编号") or ""),
            "监控指标": str(entry.get("监控指标") or ""),
            "基线窗口": window,
            "波动阈值": threshold,
            "规则版本": rule_version,
            "最新值": latest,
            "基线均值": mean,
            "基线标准差": std,
            "偏离度": deviation,
            "零方差": zero_variance,
            "判定": verdict,
            "告警级别": str(entry.get("告警级别") or ""),
            "状态": state,
            "原因": reason,
            "指纹": _fingerprint(int(entry.get("id", 0)), rule_version, values),
            "检测时间": datetime.now().isoformat(timespec="seconds"),
            "重试次数": retries,
            "is_anomaly": is_anomaly,
        }

    def _write_retry_signal(
        self, entry: dict[str, Any], values: list[float], reason: str,
    ) -> dict[str, Any]:
        """没有数据、失败或中断时落一条完整的待重试信号，说明原因、等待重试。"""
        fingerprint = _fingerprint(int(entry.get("id", 0)), str(entry.get("规则版本") or DEFAULT_RULE_VERSION), values)
        existing = self._find_signal_by_fingerprint(fingerprint)
        if existing is not None:
            existing["原因"] = reason
            existing["检测时间"] = datetime.now().isoformat(timespec="seconds")
            return existing
        signal = self._new_signal(
            entry, values,
            verdict=VERDICT_PENDING_RETRY, state=STATE_RETRY, reason=reason,
            latest=values[-1] if values else None, mean=None, std=None, deviation=None,
            zero_variance=False, is_anomaly=False,
            window=_parse_int(entry.get("基线窗口"), DEFAULT_WINDOW),
            threshold=_parse_float(entry.get("波动阈值"), DEFAULT_THRESHOLD),
        )
        with store.transaction(SIGNAL_MODULE) as rows:
            rows.append(signal)
        return signal

    def _evaluate(
        self, entry: dict[str, Any], values: list[float],
    ) -> dict[str, Any]:
        """纯计算：读基线窗口与波动阈值，处理零方差边界，返回信号字段。"""
        window = max(_parse_int(entry.get("基线窗口"), DEFAULT_WINDOW), 1)
        threshold = max(_parse_float(entry.get("波动阈值"), DEFAULT_THRESHOLD), 0.0)
        latest = values[-1]
        if len(values) < MIN_SAMPLES:
            return {
                "verdict": VERDICT_INSUFFICIENT, "state": STATE_REVIEW,
                "reason": f"样本不足（{len(values)}<{MIN_SAMPLES}），不生成已确认告警",
                "latest": latest, "mean": None, "std": None, "deviation": None,
                "zero_variance": False, "is_anomaly": False,
                "window": window, "threshold": threshold,
            }
        # 使用最近 window 个点计算基线（最新值之前）
        baseline = values[-window - 1:-1] if len(values) > window else values[:-1]
        if not baseline:
            return {
                "verdict": VERDICT_INSUFFICIENT, "state": STATE_REVIEW,
                "reason": "基线窗口内没有可用样本，不生成已确认告警",
                "latest": latest, "mean": None, "std": None, "deviation": None,
                "zero_variance": False, "is_anomaly": False,
                "window": window, "threshold": threshold,
            }
        mean = sum(baseline) / len(baseline)
        variance = sum((x - mean) ** 2 for x in baseline) / len(baseline)
        std = variance ** 0.5
        mean = round(mean, 4)
        std = round(std, 4)
        if std == 0:
            # 零方差边界：基线窗口内数据完全相同，标准差为 0，不能按偏差 0 静默判正常
            if latest == mean:
                return {
                    "verdict": VERDICT_NORMAL, "state": STATE_CONFIRMED,
                    "reason": "零标准差：最新值与基线完全一致",
                    "latest": latest, "mean": mean, "std": std, "deviation": 0.0,
                    "zero_variance": True, "is_anomaly": False,
                    "window": window, "threshold": threshold,
                }
            return {
                "verdict": VERDICT_ZERO_VARIANCE_BREACH, "state": STATE_CONFIRMED,
                "reason": "零标准差：基线窗口内数据完全相同，最新值越界",
                "latest": latest, "mean": mean, "std": std, "deviation": None,
                "zero_variance": True, "is_anomaly": True,
                "window": window, "threshold": threshold,
            }
        deviation = round(abs(latest - mean) / std, 4)
        if deviation > threshold:
            return {
                "verdict": VERDICT_BREACH, "state": STATE_CONFIRMED,
                "reason": f"偏差 {deviation:.4f} 超过波动阈值 {threshold}",
                "latest": latest, "mean": mean, "std": std, "deviation": deviation,
                "zero_variance": False, "is_anomaly": True,
                "window": window, "threshold": threshold,
            }
        return {
            "verdict": VERDICT_NORMAL, "state": STATE_CONFIRMED,
            "reason": f"偏差 {deviation:.4f} 未超过波动阈值 {threshold}",
            "latest": latest, "mean": mean, "std": std, "deviation": deviation,
            "zero_variance": False, "is_anomaly": False,
            "window": window, "threshold": threshold,
        }

    def run_detection(self, entry_id: int, values: list[float]) -> dict[str, Any]:
        """对历史监控数据执行异常检测，并把信号完整写入异常检测信号表。

        零方差越界信号与人工复核信号的取舍：基线全等而最新值越界时选择生成
        零方差越界信号（高等级越界 + 零标准差原因），因为原缺陷就是漏告警；
        样本不足等不确定场景走待复核，不生成已确认告警。
        """
        entry = self.get_entry(entry_id)
        if not entry:
            return {"ok": False, "retryable": False, "message": f"检测规则 {entry_id} 不存在或已归档"}
        try:
            values = [float(v) for v in (values or [])]
        except (TypeError, ValueError):
            return {"ok": False, "retryable": True, "reason": "输入非法",
                    "message": "监控序列含有无法解析的取值，请修正后重试"}
        if not values:
            signal = self._write_retry_signal(entry, values, "没有监控数据，请补充数据后重试")
            return {"ok": False, "retryable": True, "reason": "没有数据",
                    "message": "没有监控数据，已记录待重试信号，请补充数据后重试",
                    "signal": signal}
        try:
            outcome = self._evaluate(entry, values)
        except Exception as exc:  # 计算中断：事务回滚，沿用当前完整信号历史
            signal = self._write_retry_signal(entry, values, f"检测中断：{exc}，请重试")
            return {"ok": False, "retryable": True, "reason": "检测中断",
                    "message": f"检测中断：{exc}，已保留完整信号历史，请重试",
                    "signal": signal}
        fingerprint = _fingerprint(entry_id, str(entry.get("规则版本") or DEFAULT_RULE_VERSION), values)
        existing = self._find_signal_by_fingerprint(fingerprint)
        if existing is not None and existing.get("状态") in FINAL_STATES:
            # 同一输入重复检测得到相同信号，不重复落库
            return self._detection_result(existing, reused=True)
        if existing is not None:
            # 同指纹的待重试记录：原地改写为本次结论，不产生重复记录
            self._apply_outcome(existing, entry, values, outcome)
            return self._detection_result(existing, reused=True)
        signal = self._new_signal(
            entry, values,
            verdict=outcome["verdict"], state=outcome["state"], reason=outcome["reason"],
            latest=outcome["latest"], mean=outcome["mean"], std=outcome["std"],
            deviation=outcome["deviation"], zero_variance=outcome["zero_variance"],
            is_anomaly=outcome["is_anomaly"],
            window=outcome["window"], threshold=outcome["threshold"],
        )
        try:
            with store.transaction(SIGNAL_MODULE) as rows:
                # 零方差判定与规则版本必须随同一条记录同时写入
                missing = [key for key in SIGNAL_REQUIRED_KEYS if key not in signal]
                if missing:
                    raise ValueError(f"信号记录不完整，回滚：缺 {missing}")
                rows.append(signal)
        except Exception as exc:
            return {"ok": False, "retryable": True, "reason": "写入失败",
                    "message": f"信号写入失败已回滚：{exc}，请重试"}
        return self._detection_result(signal, reused=False)

    def _apply_outcome(
        self,
        signal: dict[str, Any],
        entry: dict[str, Any],
        values: list[float],
        outcome: dict[str, Any],
    ) -> None:
        """把检测结论原地写进既有信号：零方差判定与规则版本一起改写。"""
        rule_version = str(entry.get("规则版本") or DEFAULT_RULE_VERSION)
        signal.update({
            "监控指标": str(entry.get("监控指标") or ""),
            "基线窗口": outcome["window"],
            "波动阈值": outcome["threshold"],
            "规则版本": rule_version,
            "最新值": outcome["latest"],
            "基线均值": outcome["mean"],
            "基线标准差": outcome["std"],
            "偏离度": outcome["deviation"],
            "零方差": outcome["zero_variance"],
            "判定": outcome["verdict"],
            "状态": outcome["state"],
            "原因": outcome["reason"],
            "指纹": _fingerprint(int(entry.get("id", 0)), rule_version, values),
            "检测时间": datetime.now().isoformat(timespec="seconds"),
            "is_anomaly": outcome["is_anomaly"],
        })

    def _detection_result(self, signal: dict[str, Any], *, reused: bool) -> dict[str, Any]:
        message = signal.get("原因") or "异常检测完成"
        if reused:
            message = f"同一输入已检测，返回既有信号 {signal.get('信号编号')}：{message}"
        return {
            "ok": True,
            "retryable": False,
            "is_anomaly": bool(signal.get("is_anomaly")),
            "mean": signal.get("基线均值"),
            "std": signal.get("基线标准差"),
            "latest": signal.get("最新值"),
            "deviation": signal.get("偏离度"),
            "threshold": signal.get("波动阈值"),
            "zero_variance": bool(signal.get("零方差")),
            "verdict": signal.get("判定"),
            "state": signal.get("状态"),
            "rule_version": signal.get("规则版本"),
            "reused": reused,
            "signal": signal,
            "message": message,
        }

    def retry_signal(self, signal_id: int, values: list[float]) -> tuple[dict[str, Any] | None, str]:
        """重试待重试信号：沿用同一条记录更新，不产生重复或残留。"""
        signal = self.get_signal(signal_id)
        if signal is None:
            return None, f"检测信号 {signal_id} 不存在或已归档"
        if signal.get("状态") != STATE_RETRY:
            return None, f"信号 {signal.get('信号编号')} 已终态（{signal.get('状态')}），无需重试"
        entry = self.get_entry(int(signal.get("规则ID", 0)))
        if entry is None:
            signal["原因"] = "关联检测规则不存在或已归档，无法重试"
            return None, signal["原因"]
        try:
            values = [float(v) for v in (values or [])]
        except (TypeError, ValueError):
            signal["原因"] = "重试输入含有无法解析的取值，请修正后重试"
            return signal, signal["原因"]
        signal["重试次数"] = int(signal.get("重试次数", 0)) + 1
        if not values:
            signal["原因"] = "重试时仍没有监控数据，请补充数据后再试"
            signal["检测时间"] = datetime.now().isoformat(timespec="seconds")
            return signal, signal["原因"]
        try:
            outcome = self._evaluate(entry, values)
        except Exception as exc:
            signal["原因"] = f"重试中断：{exc}，请再次重试"
            signal["检测时间"] = datetime.now().isoformat(timespec="seconds")
            return signal, signal["原因"]
        self._apply_outcome(signal, entry, values, outcome)
        return signal, f"信号 {signal.get('信号编号')} 重试完成：{outcome['verdict']}"

    def process_pending(self) -> dict[str, Any]:
        """处理信号表里的待办记录：清理中断残留的半成品（事务回滚）并留档核对。"""
        rows = store.rows(SIGNAL_MODULE)
        residue_ids = {
            int(row.get("id", 0))
            for row in rows
            if any(key not in row for key in SIGNAL_REQUIRED_KEYS)
        }
        audits: list[dict[str, Any]] = []
        removed = 0
        if residue_ids:
            residue_rows = [row for row in rows if int(row.get("id", 0)) in residue_ids]
            with store.transaction(SIGNAL_MODULE):
                removed = store.delete_ids(SIGNAL_MODULE, residue_ids)
            for row in residue_rows:
                audits.append({
                    "信号编号": row.get("信号编号", "未知"),
                    "规则编号": row.get("规则编号", ""),
                    "规则版本": row.get("规则版本", ""),
                    "处理": "残留回滚",
                    "原因": "记录不完整，按事务残留清理",
                    "时间": datetime.now().isoformat(timespec="seconds"),
                })
            store.rows(SIGNAL_AUDIT_MODULE).extend(audits)
        awaiting = [
            {"信号编号": row.get("信号编号"), "原因": row.get("原因", "")}
            for row in store.rows(SIGNAL_MODULE)
            if row.get("状态") == STATE_RETRY
        ]
        return {
            "ok": True,
            "removed": removed,
            "awaiting_retry": awaiting,
            "audits": audits,
            "message": f"残留回滚 {removed} 条，待重试 {len(awaiting)} 条，均已留档核对",
        }
