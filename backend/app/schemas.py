"""接口出入参模型：列表分页、动作结果与各模块的明细结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    """登记或修改一条业务记录时提交的字段集合。"""

    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    """状态动作使用独立契约，避免与登记的 values 载荷混用。"""

    action: str
    remark: str | None = None


class DetectPayload(BaseModel):
    """执行异常检测的输入：一段历史监控序列，最后一个点为最新值。"""

    values: list[float] = Field(default_factory=list)



class ExperimentEntry(BaseModel):
    """实验方案明细结构。"""

    field_0: str | None = None  # 方案编号
    field_1: str | None = None  # 实验名称
    field_2: str | None = None  # 对照组说明
    field_3: str | None = None  # 实验组说明
    field_4: str | None = None  # 样本总量
    field_5: str | None = None  # 分流比例
    field_6: str | None = None  # 启动日期
    field_7: str | None = None  # 预期时长

class SampleGroupEntry(BaseModel):
    """样本分群明细结构。"""

    field_0: str | None = None  # 分群编号
    field_1: str | None = None  # 分群名称
    field_2: str | None = None  # 筛选条件
    field_3: str | None = None  # 样本基数
    field_4: str | None = None  # 分群日期
    field_5: str | None = None  # 更新方式
    field_6: str | None = None  # 有效天数
    field_7: str | None = None  # 负责人

class MetricDefEntry(BaseModel):
    """指标定义明细结构。"""

    field_0: str | None = None  # 指标编号
    field_1: str | None = None  # 指标名称
    field_2: str | None = None  # 计算公式
    field_3: str | None = None  # 统计粒度
    field_4: str | None = None  # 时间窗口
    field_5: str | None = None  # 基准取值
    field_6: str | None = None  # 精度位数
    field_7: str | None = None  # 口径版本

class AbResultEntry(BaseModel):
    """分析报告明细结构。"""

    field_0: str | None = None  # 报告编号
    field_1: str | None = None  # 实验编号
    field_2: str | None = None  # 分析指标
    field_3: str | None = None  # 对照组均值
    field_4: str | None = None  # 实验组均值
    field_5: str | None = None  # 置信水平
    field_6: str | None = None  # 效果方向
    field_7: str | None = None  # 生成时间

class SegmentCompareEntry(BaseModel):
    """对比任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 分群A
    field_2: str | None = None  # 分群B
    field_3: str | None = None  # 对比指标
    field_4: str | None = None  # 时间范围
    field_5: str | None = None  # 差异阈值
    field_6: str | None = None  # 显著性水平
    field_7: str | None = None  # 比较方法

class DrillDownEntry(BaseModel):
    """下钻维度明细结构。"""

    field_0: str | None = None  # 维度编号
    field_1: str | None = None  # 维度名称
    field_2: str | None = None  # 下钻层级
    field_3: str | None = None  # 基准指标
    field_4: str | None = None  # 父级维度
    field_5: str | None = None  # 子级维度
    field_6: str | None = None  # 数据来源
    field_7: str | None = None  # 刷新间隔

class DataFilterEntry(BaseModel):
    """筛选规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 数据来源
    field_2: str | None = None  # 筛选字段
    field_3: str | None = None  # 筛选算子
    field_4: str | None = None  # 筛选阈值
    field_5: str | None = None  # 逻辑组合
    field_6: str | None = None  # 输出集合
    field_7: str | None = None  # 规则版本

class AttrAnalysisEntry(BaseModel):
    """归因任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 目标指标
    field_2: str | None = None  # 候选因子
    field_3: str | None = None  # 归因模型
    field_4: str | None = None  # 分析窗口
    field_5: str | None = None  # 贡献度阈值
    field_6: str | None = None  # 交互项数
    field_7: str | None = None  # 任务批次

class AnomalyDetectEntry(BaseModel):
    """检测规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 监控指标
    field_2: str | None = None  # 检测算法
    field_3: str | None = None  # 基线窗口
    field_4: str | None = None  # 波动阈值
    field_5: str | None = None  # 告警级别
    field_6: str | None = None  # 静默时段
    field_7: str | None = None  # 规则版本

class ForecastModelEntry(BaseModel):
    """模型配置明细结构。"""

    field_0: str | None = None  # 模型编号
    field_1: str | None = None  # 预测对象
    field_2: str | None = None  # 历史窗口
    field_3: str | None = None  # 预测周期
    field_4: str | None = None  # 模型类型
    field_5: str | None = None  # 参数配置
    field_6: str | None = None  # 训练批次
    field_7: str | None = None  # 评估误差

class DataExportEntry(BaseModel):
    """导出任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 数据来源
    field_2: str | None = None  # 导出格式
    field_3: str | None = None  # 字段清单
    field_4: str | None = None  # 数据范围
    field_5: str | None = None  # 压缩方式
    field_6: str | None = None  # 分片大小
    field_7: str | None = None  # 导出批次

class CohortTrackEntry(BaseModel):
    """同期群定义明细结构。"""

    field_0: str | None = None  # 群组编号
    field_1: str | None = None  # 群组名称
    field_2: str | None = None  # 首次行为
    field_3: str | None = None  # 时间基准
    field_4: str | None = None  # 追踪周期
    field_5: str | None = None  # 留存窗口
    field_6: str | None = None  # 分析指标
    field_7: str | None = None  # 对比群组

class ChartConfigEntry(BaseModel):
    """图表配置明细结构。"""

    field_0: str | None = None  # 图表编号
    field_1: str | None = None  # 图表类型
    field_2: str | None = None  # 数据来源
    field_3: str | None = None  # 横轴字段
    field_4: str | None = None  # 纵轴字段
    field_5: str | None = None  # 分组字段
    field_6: str | None = None  # 刷新间隔
    field_7: str | None = None  # 分享链接

class InsightReportEntry(BaseModel):
    """洞察报告明细结构。"""

    field_0: str | None = None  # 报告编号
    field_1: str | None = None  # 分析主题
    field_2: str | None = None  # 数据来源
    field_3: str | None = None  # 关键发现
    field_4: str | None = None  # 建议措施
    field_5: str | None = None  # 影响范围
    field_6: str | None = None  # 生成时间
    field_7: str | None = None  # 报告版本

class DataFreshnessEntry(BaseModel):
    """新鲜度监控明细结构。"""

    field_0: str | None = None  # 监控编号
    field_1: str | None = None  # 数据表名
    field_2: str | None = None  # 最新分区
    field_3: str | None = None  # 期望刷新
    field_4: str | None = None  # 滞后时长
    field_5: str | None = None  # 告警阈值
    field_6: str | None = None  # 检查间隔
    field_7: str | None = None  # 通知方式

class MetricAliasEntry(BaseModel):
    """口径版本明细结构。"""

    field_0: str | None = None  # 版本编号
    field_1: str | None = None  # 指标编号
    field_2: str | None = None  # 变更说明
    field_3: str | None = None  # 旧口径
    field_4: str | None = None  # 新口径
    field_5: str | None = None  # 生效时间
    field_6: str | None = None  # 审批状态
    field_7: str | None = None  # 变更人

class ExprFactorEntry(BaseModel):
    """因子配置明细结构。"""

    field_0: str | None = None  # 因子编号
    field_1: str | None = None  # 因子名称
    field_2: str | None = None  # 因子层级
    field_3: str | None = None  # 取值集合
    field_4: str | None = None  # 分配比例
    field_5: str | None = None  # 互斥规则
    field_6: str | None = None  # 关联实验
    field_7: str | None = None  # 生效批次

class EvaluateBoardEntry(BaseModel):
    """看板配置明细结构。"""

    field_0: str | None = None  # 看板编号
    field_1: str | None = None  # 看板名称
    field_2: str | None = None  # 关联实验
    field_3: str | None = None  # 展示指标
    field_4: str | None = None  # 数据范围
    field_5: str | None = None  # 刷新策略
    field_6: str | None = None  # 消费范围
    field_7: str | None = None  # 看板版本
