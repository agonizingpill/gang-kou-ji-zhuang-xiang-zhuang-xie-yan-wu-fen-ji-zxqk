"""Source records and completion rules for gate-correction."""

GATE_CORRECTIONS = {
    'gate-correction': {
        'title': '重复进闸冲正复核',
        'reference_label': '闸口冲正单号',
        'outcomes': {
            'corrected': ('重复进闸已冲正', ('balanced',)),
            'dispute': ('移交闸口复查', None),
        },
        'sql': """
SELECT c.container_no AS source_key,c.container_no AS subject,
       CONCAT(v.call_no,' · 有效进闸 ',COUNT(g.id),' 条，唯一时点 ',COUNT(DISTINCT g.event_time),' 个') AS source_summary,
       CASE WHEN COUNT(g.id)>COUNT(DISTINCT g.event_time) THEN 'duplicate' ELSE 'balanced' END AS readiness
FROM container_checks c JOIN vessel_calls v ON v.id=c.vessel_id
LEFT JOIN gate_events g ON g.container_id=c.id AND g.event_type='in' AND g.status<>'reversed'
GROUP BY c.id,v.call_no
""",
    },
}
