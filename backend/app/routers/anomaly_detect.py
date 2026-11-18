"""异常检测接口：维护检测规则，覆盖提交校验、标记生效、停用规则等动作。

异常检测信号表（/signals）提供列表、详情、重试与待办处理；
列表与详情读同一张表，保证工作台和详情页展示相同的业务数据。
"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, DetectPayload, EntryPayload, PageResult
from app.services.anomaly_detect import AnomalyDetectService

router = APIRouter(prefix="/api/anomaly_detect", tags=["异常检测"])

service = AnomalyDetectService()

LIST_FIELDS = ["规则编号", "监控指标", "检测算法", "基线窗口", "波动阈值", "告警级别", "静默时段", "规则版本"]
STATUSES = ["草稿", "待校验", "已生效", "已停用"]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已生效、已停用"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、规则编号关键字与状态过滤异常检测列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="anomaly_detect.csv"'})


@router.get("/signals", response_model=PageResult[dict])
def list_signals(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    verdict: str | None = Query(default=None, description="正常、越界、零方差越界、数据不足、待重试"),
    state: str | None = Query(default=None, description="已确认、待复核、待重试"),
    rule_version: str | None = Query(default=None, description="按规则版本过滤，如 V026"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """异常检测信号表列表：工作台数据源。必须声明在 /{entry_id} 之前。"""
    items, total = service.list_signals(
        keyword=keyword, verdict=verdict, state=state, rule_version=rule_version,
        page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/signals/process_pending", response_model=dict)
def process_pending_signals() -> dict:
    """处理信号表待办：残缺残留事务回滚并留档核对，待重试记录连同原因一并返回。"""
    return service.process_pending()


@router.get("/signals/{signal_id}", response_model=dict)
def get_signal(signal_id: int) -> dict:
    """信号详情：与列表读同一张表，保证工作台和详情页数据一致。"""
    signal = service.get_signal(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail=f"检测信号 {signal_id} 不存在或已归档")
    return signal


@router.post("/signals/{signal_id}/retry", response_model=ActionResult)
def retry_signal(signal_id: int, payload: DetectPayload) -> ActionResult:
    """重试待重试信号：沿用同一条记录原地更新；仍无数据时说明原因。"""
    signal, message = service.retry_signal(signal_id, payload.values)
    if signal is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=signal)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条检测规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"检测规则 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/detect", response_model=dict)
def run_detection(entry_id: int, payload: DetectPayload) -> dict:
    """对一条检测规则执行异常检测，结果完整写入异常检测信号表。"""
    return service.run_detection(entry_id, payload.values)


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条检测规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="检测规则已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条检测规则执行提交校验、标记生效、停用规则；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
