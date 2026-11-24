"""Source records and completion rules for customs-release."""

CUSTOMS_RELEASE = {
    'customs-release': {
        'title': '海关放行交接',
        'reference_label': '放行回执或改配船次',
        'outcomes': {
            'released': ('已查验放行', ('released',)),
            'rollover': ('已登记改配下班船', None),
        },
        'sql': """
SELECT c.container_no AS source_key,CONCAT(c.container_no,' · ',v.call_no) AS subject,
       CONCAT('离港 ',v.etd,' · 查验 ',c.customs_status,' · 封签 ',c.seal_status) AS source_summary,
       CASE WHEN c.customs_status='finished' AND c.seal_status='intact' THEN 'released' ELSE 'held' END AS readiness
FROM container_checks c JOIN vessel_calls v ON v.id=c.vessel_id
""",
    },
}
