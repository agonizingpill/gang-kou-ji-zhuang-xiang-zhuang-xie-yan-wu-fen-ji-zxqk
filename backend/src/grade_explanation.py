"""船方申诉分级说明：按派工采用的那次推理重建多分类 LR 决策分差。

分差恒等式（可核回原判断）：
    decision_margin(领先等级, 次高等级)
      = 基础分差(截距差) + Σ 各特征对该分差的贡献
其中特征 k 的贡献 = (领先等级系数_k - 次高等级系数_k) × 标准化后的特征值_k，
标准化特征值_k = (原始特征值_k - scaler.mean_k) / scaler.scale_k。

说明只依据 analysis_jobs.result 中冻结的模型参数与特征快照重建，
不依赖当前内存模型；模型后续重训或案件重新分级都不影响已签原件。
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AnalysisJob, DelayCase, DispatchAction, GradeExplanation

ROUND = 6


class ExplanationUnavailable(Exception):
    """旧单缺少可追溯证据（推理结果未冻结模型参数/特征）。"""


def _coerce_matrix(value, rows, cols, name):
    if not isinstance(value, list) or len(value) != rows:
        raise ExplanationUnavailable(f"证据缺少有效的 {name}")
    matrix = []
    for row in value:
        if not isinstance(row, list) or len(row) != cols:
            raise ExplanationUnavailable(f"证据中的 {name} 维度不完整")
        try:
            matrix.append([float(x) for x in row])
        except (TypeError, ValueError):
            raise ExplanationUnavailable(f"证据中的 {name} 含非数值项")
    return matrix


def _coerce_vector(value, size, name):
    if not isinstance(value, list) or len(value) != size:
        raise ExplanationUnavailable(f"证据缺少有效的 {name}")
    try:
        return [float(x) for x in value]
    except (TypeError, ValueError):
        raise ExplanationUnavailable(f"证据中的 {name} 含非数值项")


def rebuild_evidence(job: AnalysisJob):
    """从冻结的 job.result 还原 scaler、类别、系数与原始特征。"""
    result = job.result or {}
    frozen = result.get("model_evidence")
    if not isinstance(frozen, dict):
        raise ExplanationUnavailable("该次推理未冻结模型参数，无法追溯分差构成")
    classes = frozen.get("classes")
    feature_keys = result.get("feature_keys") or frozen.get("feature_keys")
    if not isinstance(classes, list) or len(classes) < 2:
        raise ExplanationUnavailable("证据缺少完整的等级类别")
    if not isinstance(feature_keys, list) or not feature_keys:
        raise ExplanationUnavailable("证据缺少特征键清单")
    n_classes, n_features = len(classes), len(feature_keys)
    means = _coerce_vector(frozen.get("scaler_mean"), n_features, "scaler_mean")
    scales = _coerce_vector(frozen.get("scaler_scale"), n_features, "scaler_scale")
    if any(s == 0 for s in scales):
        raise ExplanationUnavailable("证据中的 scaler_scale 存在零值，无法标准化")
    intercepts = _coerce_vector(frozen.get("intercept"), n_classes, "intercept")
    coef = _coerce_matrix(frozen.get("coef"), n_classes, n_features, "coef")
    features = result.get("features")
    if not isinstance(features, dict):
        raise ExplanationUnavailable("证据缺少冻结的特征快照")
    try:
        raw = [float(features[k]) for k in feature_keys]
    except (KeyError, TypeError, ValueError):
        raise ExplanationUnavailable("特征快照与模型特征键对不上，无法追溯")
    return {
        "classes": classes,
        "feature_keys": feature_keys,
        "means": means,
        "scales": scales,
        "intercepts": intercepts,
        "coef": coef,
        "features": features,
        "raw": raw,
    }


def build_explanation_document(job: AnalysisJob, explained_level: str):
    """按冻结推理构造分级说明文档；逐特征贡献 + 基础分差可核回原分差。"""
    ev = rebuild_evidence(job)
    classes, feature_keys = ev["classes"], ev["feature_keys"]
    if explained_level not in classes:
        raise ExplanationUnavailable(f"派工采用的等级 {explained_level} 不在该次推理类别中")
    z = [(ev["raw"][k] - ev["means"][k]) / ev["scales"][k] for k in range(len(feature_keys))]
    decision = []
    for c in range(len(classes)):
        score = ev["intercepts"][c] + sum(ev["coef"][c][k] * z[k] for k in range(len(feature_keys)))
        decision.append(score)
    leader_idx = classes.index(explained_level)
    # 次高等级：除领先等级外决策分最高者
    runner_idx = max(
        (i for i in range(len(classes)) if i != leader_idx),
        key=lambda i: decision[i],
    )
    base_margin = ev["intercepts"][leader_idx] - ev["intercepts"][runner_idx]
    contributions = []
    for k, key in enumerate(feature_keys):
        coef_delta = ev["coef"][leader_idx][k] - ev["coef"][runner_idx][k]
        contribution = coef_delta * z[k]
        contributions.append({
            "feature_key": key,
            "feature_value": ev["features"][key],
            "standardized_value": round(z[k], ROUND),
            "leader_coef": round(ev["coef"][leader_idx][k], ROUND),
            "runner_coef": round(ev["coef"][runner_idx][k], ROUND),
            "coef_delta": round(coef_delta, ROUND),
            "margin_contribution": round(contribution, ROUND),
        })
    contributions.sort(key=lambda item: abs(item["margin_contribution"]), reverse=True)
    contribution_sum = sum(item["margin_contribution"] for item in contributions)
    original_margin = decision[leader_idx] - decision[runner_idx]
    recomputed_margin = round(base_margin + contribution_sum, ROUND)
    return {
        "analysis_job_id": job.id,
        "explained_level": explained_level,
        "runner_up_level": classes[runner_idx],
        "feature_keys": feature_keys,
        "frozen_features": ev["features"],
        "decision_scores": {classes[c]: round(decision[c], ROUND) for c in range(len(classes))},
        "base_margin": round(base_margin, ROUND),
        "contributions": contributions,
        "contribution_sum": round(contribution_sum, ROUND),
        "recomputed_margin": recomputed_margin,
        "original_margin": round(original_margin, ROUND),
        "reconciles": abs(recomputed_margin - round(original_margin, ROUND)) <= 10 ** (-ROUND + 2),
        "formula": "分差 = 基础分差(截距差) + Σ(领先等级系数-次高等级系数)×标准化特征值",
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }


def _idempotency_key(case_id: int, dispatch_action_id: int | None) -> str:
    return f"case-{case_id}:action-{dispatch_action_id or 0}"


def issue_for_case(db: Session, case: DelayCase, user, dispatch_action_id: int | None = None):
    """主管签发分级说明；重复请求（含中断重试）返回原单，不重复出单。"""
    action = None
    if dispatch_action_id is not None:
        action = db.get(DispatchAction, dispatch_action_id)
        if not action or action.case_id != case.id:
            raise HTTPException(404, "调度动作不存在或不属于该案件")
    key = _idempotency_key(case.id, dispatch_action_id)
    existing = db.execute(
        select(GradeExplanation).where(GradeExplanation.idempotency_key == key)
    ).scalar_one_or_none()
    if existing:
        return existing, True

    # 说明必须对得上派工当时采用的等级与那次推理
    job_id = action.analysis_job_id if action else None
    explained_level = action.graded_level_snapshot if action else None
    if not job_id:
        latest = db.execute(
            select(AnalysisJob).where(
                AnalysisJob.case_id == case.id, AnalysisJob.status == "succeeded"
            ).order_by(AnalysisJob.id.desc())
        ).scalars().first()
        job_id = latest.id if latest else None
        explained_level = explained_level or case.final_level
    if not explained_level:
        raise HTTPException(409, detail={"code": "NOT_TRACEABLE", "message": "案件缺少派工采用的等级，无法追溯分级说明"})
    job = db.get(AnalysisJob, job_id) if job_id else None
    if not job or job.status != "succeeded":
        raise HTTPException(409, detail={"code": "NOT_TRACEABLE", "message": "派工采用的推理任务不存在或未成功，无法追溯分级说明"})
    job_label = (job.result or {}).get("label")
    if job_label and job_label != explained_level:
        raise HTTPException(409, detail={
            "code": "LEVEL_MISMATCH",
            "message": f"派工采用等级 {explained_level} 与该次推理判定 {job_label} 不一致，不能据此签发说明",
        })
    try:
        document = build_explanation_document(job, explained_level)
    except ExplanationUnavailable as exc:
        raise HTTPException(409, detail={"code": "NOT_TRACEABLE", "message": f"旧单缺证据：{exc}"})

    record = GradeExplanation(
        case_id=case.id,
        dispatch_action_id=dispatch_action_id,
        analysis_job_id=job.id,
        explained_level=explained_level,
        runner_up_level=document["runner_up_level"],
        document=document,
        idempotency_key=key,
        issued_by=user.username,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        # 并发/中断重试：唯一键兜底，回查已签原件
        db.rollback()
        original = db.execute(
            select(GradeExplanation).where(GradeExplanation.idempotency_key == key)
        ).scalar_one()
        return original, True
    return record, False


def serialize(record: GradeExplanation):
    return {
        "id": record.id,
        "case_id": record.case_id,
        "dispatch_action_id": record.dispatch_action_id,
        "analysis_job_id": record.analysis_job_id,
        "explained_level": record.explained_level,
        "runner_up_level": record.runner_up_level,
        "issued_by": record.issued_by,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "document": record.document,
    }


def list_for_case(db: Session, case_id: int):
    rows = db.execute(
        select(GradeExplanation).where(GradeExplanation.case_id == case_id).order_by(GradeExplanation.id)
    ).scalars().all()
    return [serialize(r) for r in rows]


def traceability(db: Session, case: DelayCase):
    """供页面展示该案件当前是否具备可追溯的分级证据（不签发、不落库）。"""
    job = db.execute(
        select(AnalysisJob).where(
            AnalysisJob.case_id == case.id, AnalysisJob.status == "succeeded"
        ).order_by(AnalysisJob.id.desc())
    ).scalars().first()
    if not job:
        return {"traceable": False, "reason": "没有成功的模型推理任务"}
    try:
        rebuild_evidence(job)
    except ExplanationUnavailable as exc:
        return {"traceable": False, "reason": str(exc)}
    return {"traceable": True, "reason": "", "analysis_job_id": job.id}
