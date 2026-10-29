# -*- coding: utf-8 -*-
"""接口契约（唯一需要前端与后端共同遵守的文件）。

这一版只有字段定义，没有实现。审完再补路由。

三条设计原则：
1. 字段名与评测集一致（answer / clarify / refuse_noanswer / refuse_boundary），
   这样线上行为可以直接用 150 条题库打分，不用做名称映射。
2. 每个回答必须带 citations；拒答时 citations 可以只有「办理途径」，
   但不能为空——需求文档 FR-21 要求兜底必须给出官方途径。
3. 适用范围（校区/身份/学期）是请求参数而不是服务端猜的，对应 FR-16 的知识隔离。

依赖：pydantic v2 + fastapi（Anaconda 里已有 openai，通常已带 pydantic；待确认）。
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- 枚举

class Behavior(str, Enum):
    """回答行为的五档，与评测集 expect 字段一一对应。"""
    answer = 'answer'                      # 正常作答
    answer_with_caveat = 'answer_with_caveat'  # 作答但提示已过期/以现行文件为准
    clarify = 'clarify'                    # 条件不足或问法有歧义，反问
    refuse_noanswer = 'refuse_noanswer'    # 知识库无依据，拒答并给途径
    refuse_boundary = 'refuse_boundary'    # 请求越界（代办/查个人数据/投诉转办）


class IdentityType(str, Enum):
    guest = 'guest'
    student = 'student'
    teacher = 'teacher'
    staff = 'staff'


class BoundaryCategory(str, Enum):
    """FR-20 的越界类型，决定兜底话术模板。"""
    offline_required = 'offline_required'      # 需线下办理
    authorized_required = 'authorized_required'  # 需授权办理
    complaint = 'complaint'                    # 投诉建议类
    personal_data = 'personal_data'            # 查询个人业务数据


# ---------------------------------------------------------------- 请求

class Scope(BaseModel):
    """知识适用范围。服务端按此过滤，不用猜。"""
    campus: Optional[str] = Field(None, description='校区编码，按校方编码填写；为空表示不限校区')
    identity_type: IdentityType = Field(IdentityType.guest, description='提问者身份类型')
    term: Optional[str] = Field(None, description='学期，如 2026-2027-1；为空表示不限学期')


class HistoryTurn(BaseModel):
    """游客/无状态模式下的对话上下文。登录用户不传，服务端从会话里取。"""
    question: str = Field(..., max_length=500)
    answer: str = Field('', max_length=2000)
    chunk_id: Optional[str] = Field(None, description='上一轮命中的知识块，用于承接追问')


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description='用户问题原文')
    session_id: Optional[str] = Field(None, max_length=64,
                                      description='客户端生成的会话 ID；为空时服务端新建并返回')
    channel: str = Field('miniprogram', description='来源渠道：miniprogram / web')
    scope: Scope = Field(default_factory=Scope)
    history: List[HistoryTurn] = Field(default_factory=list,
                                       description='仅无状态模式使用，建议不超过 5 轮；登录后由服务端管理')
    client_ts: Optional[int] = Field(None, description='客户端时间戳（毫秒），用于统计端到端时延')


# ---------------------------------------------------------------- 回答

class Citation(BaseModel):
    """引用：必须能回溯到唯一某一条知识。"""
    chunk_id: str = Field(..., description='知识块 ID，如 hb-510')
    doc: str = Field(..., description='文件名称')
    article: str = Field('', description='条号，如 第二十二条')
    page_start: int = Field(0, description='起始页码')
    page_end: int = Field(0, description='结束页码')
    source: str = Field(..., description='可直接展示的出处串')
    excerpt: str = Field('', max_length=300, description='用于高亮的原文片段')
    version: int = Field(1, description='知识版本号')
    updated_at: Optional[str] = Field(None, description='该条知识的更新时间')


class OfficialChannel(BaseModel):
    """官方办理途径。取自知识库，不得由模型生成。"""
    unit: str = Field('', description='承办单位')
    window: str = Field('', description='服务窗口')
    phone: str = Field('', description='联系电话')
    service_hours: str = Field('', description='服务时段')
    url: Optional[str] = Field(None, description='官方入口链接')
    url_checked_at: Optional[str] = Field(None, description='链接最后核验日期')
    note: str = Field('', description='该事项的补充说明')


class BoundaryNotice(BaseModel):
    """FR-20：明确说明服务范围，不代为受理。"""
    category: BoundaryCategory
    message: str = Field(..., description='固定的边界说明话术')
    channel: OfficialChannel = Field(default_factory=OfficialChannel)


class AskResponse(BaseModel):
    trace_id: str = Field(..., description='请求追踪号，用于日志排查')
    session_id: str = Field(..., description='会话 ID，客户端需保存并在下一轮回传')
    behavior: Behavior
    answer: str = Field(..., max_length=4000, description='回答正文；拒答时为兜底话术')
    citations: List[Citation] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0, description='置信度，低于阈值时 behavior 应为 clarify 或拒答')
    suggestions: List[str] = Field(default_factory=list,
                                   description='推荐追问/相关问法，建议不超过 3 条（FR-15）')
    boundary: Optional[BoundaryNotice] = Field(None, description='仅在边界类回答时返回')
    degraded: bool = Field(False, description='模型或检索不可用时降级（FR-02/NFR-02）')
    knowledge_version: str = Field('', description='本次回答依据的知识库版本')
    latency_ms: int = Field(0, description='服务端处理耗时')


# ---------------------------------------------------------------- 反馈

class FeedbackRequest(BaseModel):
    session_id: str = Field(..., max_length=64)
    message_id: str = Field(..., max_length=64, description='对应回答的消息 ID')
    resolved: Optional[bool] = Field(None, description='是否已解决（FR-31）')
    score: Optional[int] = Field(None, ge=1, le=5, description='满意度 1-5')
    reason: str = Field('', max_length=300, description='原因/补充说明')
    chunk_id: Optional[str] = Field(None, description='该回答引用的知识块，便于定位知识缺陷')


class FeedbackResponse(BaseModel):
    ok: bool = True
    feedback_id: str


# ---------------------------------------------------------------- 其它

class HealthResponse(BaseModel):
    status: str
    index_fingerprint: str = Field('', description='索引指纹，与语料/模型配置绑定')
    model: str = Field('', description='当前嵌入模型别名')
    corpus_version: str = ''
    chunks: int = 0
    units: int = 0
    uptime_s: float = 0.0


class ErrorBody(BaseModel):
    """统一错误格式：小程序端只按 code 判断，不用解析 message。"""
    code: str = Field(..., description='机器可读错误码，如 BAD_REQUEST / INDEX_NOT_READY')
    message: str = Field(..., description='给用户看的说明')
    trace_id: str = ''
