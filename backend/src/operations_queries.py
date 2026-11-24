"""Business queries over authoritative project records."""

from .operations_reconciliation import RECONCILIATION_VIEWS

VIEWS = {
    'customs-holds': (
        '查验积压与船期',
        '按挂靠汇总海关状态和封签问题，优先处理阻塞箱量最大的船期。',
        ['挂靠', '船名', '离港时点', '箱量', '查验未放行', '封签待核', '处置建议'],
        """
SELECT v.call_no,v.vessel_name,v.etd,COUNT(c.id),
       SUM(CASE WHEN c.id IS NOT NULL AND c.customs_status <> 'finished' THEN 1 ELSE 0 END) AS holds,
       SUM(CASE WHEN c.id IS NOT NULL AND c.seal_status <> 'intact' THEN 1 ELSE 0 END),
       CASE WHEN SUM(CASE WHEN c.id IS NOT NULL AND c.customs_status <> 'finished' THEN 1 ELSE 0 END)>0 THEN '等待查验结果' ELSE '按船期作业' END
FROM vessel_calls v LEFT JOIN container_checks c ON v.id=c.vessel_id
GROUP BY v.id,v.call_no,v.vessel_name,v.etd ORDER BY holds DESC,v.etd,v.id
""",
    ),
    'gate-congestion': (
        '闸口拥堵分布',
        '分闸口和作业日统计有效停留，冲正记录单列；高于 60 分钟的有效记录列为拥堵。',
        ['闸口', '作业日', '有效事件', '冲正事件', '平均停留 分', '拥堵事件'],
        """
SELECT gate_code,CAST(event_time AS DATE),SUM(CASE WHEN status <> 'reversed' THEN 1 ELSE 0 END),
       SUM(CASE WHEN status='reversed' THEN 1 ELSE 0 END),
       AVG(CASE WHEN status <> 'reversed' THEN dwell_min END),
       SUM(CASE WHEN status <> 'reversed' AND dwell_min>60 THEN 1 ELSE 0 END) AS congestion
FROM gate_events GROUP BY gate_code,CAST(event_time AS DATE) ORDER BY congestion DESC,CAST(event_time AS DATE) DESC,gate_code
""",
    ),
    'dispatch-sla': (
        '调度交接时限',
        '把案件等级、责任人和到期时间放在同一交接表，区分未完成逾期和完成后超时。',
        ['案件', '等级', '指令号', '责任人', '到期', '完成时间', '时限判定'],
        """
SELECT c.case_no,COALESCE(c.final_level,c.requested_level),a.id,a.assignee,a.due_at,a.completed_at,
       CASE WHEN a.completed_at>a.due_at THEN '超时完成' WHEN a.completed_at IS NOT NULL THEN '准时完成'
            WHEN a.due_at<CURRENT_TIMESTAMP THEN '逾期待接班' ELSE '时限内' END
FROM dispatch_actions a JOIN delay_cases c ON a.case_id=c.id ORDER BY a.due_at,a.id
""",
    ),
    **RECONCILIATION_VIEWS,
}
