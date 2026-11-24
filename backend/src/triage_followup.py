"""Source records and completion rules for triage-followup."""

TRIAGE_FOLLOWUP = {
    'triage-followup': {
        'title': '分流恢复验收',
        'reference_label': '分级复核指令号',
        'outcomes': {
            'graded': ('已恢复人工定级', ('graded',)),
            'reassign': ('转交调度值班', None),
        },
        'sql': """
SELECT c.case_no AS source_key,c.case_no AS subject,
       CONCAT(v.call_no,' · ',c.status,' · ',COALESCE(c.final_level,c.requested_level),' · ',COALESCE(c.exception_reason,'')) AS source_summary,
       CASE WHEN c.final_level IS NOT NULL AND c.status<>'blocked' THEN 'graded' ELSE 'ungraded' END AS readiness
FROM delay_cases c JOIN vessel_calls v ON v.id=c.vessel_id
""",
    },
}
