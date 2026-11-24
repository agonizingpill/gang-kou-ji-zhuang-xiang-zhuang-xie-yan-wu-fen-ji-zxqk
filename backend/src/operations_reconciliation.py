"""Additional operational reconciliation rules for this project."""

RECONCILIATION_VIEWS = {
    'gate-evidence-chain': (
        '装船进闸凭证核对',
        '逐箱核对有效进闸凭证与查验状态，区分未放行、缺凭证和已齐备。',
        ['箱号', '挂靠', '查验状态', '箱检状态', '有效进闸凭证数', '最近进闸时间', '装船前核对'],
        """
SELECT c.container_no, v.call_no, c.customs_status, c.check_state,
       COUNT(DISTINCT g.event_time), MAX(g.event_time),
       CASE WHEN c.customs_status <> 'finished' THEN '查验待放行'
            WHEN COUNT(g.id) = 0 THEN '待补进闸凭证'
            WHEN COUNT(g.id)>COUNT(DISTINCT g.event_time) THEN '进闸记录重复待冲正'
            ELSE '进闸凭证齐备' END
FROM container_checks c JOIN vessel_calls v ON v.id = c.vessel_id
LEFT JOIN gate_events g ON g.container_id = c.id AND g.status <> 'reversed' AND g.event_type = 'in'
GROUP BY c.id, v.call_no, v.etd ORDER BY v.etd, c.container_no
""",
    ),
    'triage-recovery-queue': (
        '分流阻断恢复队列',
        '结合案件状态与最近模型任务，区分业务输入待修、模型失败待重跑和待人工定级。',
        ['案件', '挂靠', '案件状态', '最新任务', '任务状态', '阻断或失败说明', '下一步'],
        """
SELECT c.case_no, v.call_no, c.status, j.id, j.status, COALESCE(NULLIF(c.exception_reason,''),j.error),
       CASE WHEN c.status = 'blocked' THEN '修复业务输入'
            WHEN j.status = 'failed' THEN '核查任务后重跑'
            WHEN c.final_level IS NOT NULL THEN '人工定级已记账'
            WHEN j.id IS NULL THEN '待发起模型分流'
            WHEN j.result IS NOT NULL THEN '待人工定级'
            ELSE '等待模型任务' END
FROM delay_cases c JOIN vessel_calls v ON v.id = c.vessel_id
LEFT JOIN analysis_jobs j ON j.id = (SELECT MAX(a.id) FROM analysis_jobs a WHERE a.case_id = c.id)
ORDER BY CASE WHEN c.status = 'blocked' OR j.status = 'failed' THEN 0 ELSE 1 END, c.updated_at DESC, c.id
""",
    ),
}
