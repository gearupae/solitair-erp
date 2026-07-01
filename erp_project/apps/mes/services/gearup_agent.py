"""Gearup Agent — MES AI: delays, NL queries, template drafts, cost estimates."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db.models import F
from django.utils import timezone

from apps.mes.models import (
    Part,
    PartScan,
    ProductionOrder,
    RoutingOperation,
    WorkCenter,
)
from apps.mes.services.station_queue import get_station_queue

logger = logging.getLogger(__name__)

MES_AGENT_MODEL = 'gpt-4o-mini'


def build_mes_snapshot(company) -> dict:
    """Compact live MES context for Gearup Agent prompts."""
    today = timezone.localdate()
    open_statuses = (
        ProductionOrder.STATUS_RELEASED,
        ProductionOrder.STATUS_IN_PRODUCTION,
        ProductionOrder.STATUS_ON_HOLD,
    )

    orders = list(
        ProductionOrder.objects.filter(
            company=company,
            is_active=True,
            status__in=open_statuses,
        )
        .order_by(F('due_date').asc(nulls_last=True), 'po_number')[:20]
    )

    po_rows = []
    for po in orders:
        parts = Part.objects.filter(production_order=po, is_active=True)
        total = parts.count()
        done = parts.filter(status=Part.STATUS_DONE).count()
        po_rows.append(
            {
                'po_number': po.po_number,
                'reference': po.reference or '',
                'status': po.status,
                'due_date': po.due_date.isoformat() if po.due_date else None,
                'days_to_due': (po.due_date - today).days if po.due_date else None,
                'quantity': po.quantity,
                'parts_total': total,
                'parts_done': done,
                'parts_progress_pct': round(done * 100 / total, 1) if total else 0,
            },
        )

    stations = WorkCenter.objects.filter(
        company=company,
        is_active=True,
        is_production_step=True,
    ).order_by('sequence_order', 'name')

    queue_summary = []
    for wc in stations:
        try:
            q = get_station_queue(company, wc.pk)
            queue_summary.append(
                {
                    'code': wc.code,
                    'name': wc.name,
                    'waiting_parts': q['count'],
                    'std_time_minutes': None,
                },
            )
        except ValueError:
            continue

    routing_std = {}
    for op in RoutingOperation.objects.filter(
        company=company,
        is_active=True,
        production_order__status__in=open_statuses,
    ).select_related('work_center'):
        code = op.work_center.code
        routing_std.setdefault(code, []).append(op.std_time_minutes)

    for row in queue_summary:
        times = routing_std.get(row['code'], [])
        if times:
            row['std_time_minutes'] = round(sum(times) / len(times), 1)

    slow_scans = _recent_slow_operations(company, limit=8)

    work_centers = list(
        WorkCenter.objects.filter(company=company, is_active=True).values(
            'code', 'name', 'cost_per_hour', 'sequence_order', 'is_production_step',
        ),
    )

    return {
        'as_of': timezone.now().isoformat(),
        'today': today.isoformat(),
        'open_production_orders': po_rows,
        'station_queues': queue_summary,
        'slow_operations': slow_scans,
        'work_centers': work_centers,
    }


def _recent_slow_operations(company, limit: int = 8) -> list[dict]:
    """Pair IN/OUT scans at same station; flag when dwell exceeds routing std time."""
    since = timezone.now() - timedelta(days=14)
    scans = (
        PartScan.objects.filter(
            company=company,
            timestamp__gte=since,
        )
        .select_related('part', 'part__production_order', 'work_center')
        .order_by('-timestamp')[:200]
    )

    rows = []
    seen = set()
    for scan_out in scans:
        if scan_out.scan_type != PartScan.SCAN_OUT:
            continue
        key = (scan_out.part_id, scan_out.work_center_id)
        if key in seen:
            continue
        scan_in = (
            PartScan.objects.filter(
                company=company,
                part_id=scan_out.part_id,
                work_center_id=scan_out.work_center_id,
                scan_type=PartScan.SCAN_IN,
                timestamp__lt=scan_out.timestamp,
            )
            .order_by('-timestamp')
            .first()
        )
        if not scan_in:
            continue
        dwell_min = (scan_out.timestamp - scan_in.timestamp).total_seconds() / 60
        std = (
            RoutingOperation.objects.filter(
                company=company,
                production_order=scan_out.part.production_order_id,
                work_center=scan_out.work_center,
                is_active=True,
            )
            .values_list('std_time_minutes', flat=True)
            .first()
        ) or 15
        if dwell_min <= std * 1.25:
            continue
        seen.add(key)
        rows.append(
            {
                'po_number': scan_out.part.production_order.po_number,
                'barcode': scan_out.part.barcode,
                'station': scan_out.work_center.code,
                'std_minutes': std,
                'actual_minutes': round(dwell_min, 1),
                'over_by_minutes': round(dwell_min - std, 1),
            },
        )
        if len(rows) >= limit:
            break
    return rows


def _heuristic_delay_alerts(snapshot: dict) -> list[dict]:
    alerts = []
    queues = sorted(snapshot.get('station_queues', []), key=lambda x: -x.get('waiting_parts', 0))
    if queues and queues[0]['waiting_parts'] > 0:
        top = queues[0]
        alerts.append(
            {
                'severity': 'warning',
                'title': f"Bottleneck: {top['code']} ({top['name']})",
                'detail': f"{top['waiting_parts']} parts waiting — highest queue on the floor.",
            },
        )

    today = date.fromisoformat(snapshot['today'])
    for po in snapshot.get('open_production_orders', []):
        due_raw = po.get('due_date')
        if not due_raw:
            continue
        due = date.fromisoformat(due_raw)
        days = po.get('days_to_due')
        progress = po.get('parts_progress_pct', 0)
        if days is not None and days <= 3 and progress < 80:
            alerts.append(
                {
                    'severity': 'danger' if days < 0 else 'warning',
                    'title': f"{po['po_number']} at risk",
                    'detail': (
                        f"Due {'overdue' if days < 0 else 'in ' + str(days) + ' day(s)'} "
                        f"with only {progress:.0f}% parts complete."
                    ),
                },
            )
    return alerts[:6]


def _ai_available() -> bool:
    from apps.inventory.utils import is_ai_available
    return is_ai_available()


def run_delay_prediction(company) -> dict:
    snapshot = build_mes_snapshot(company)
    fallback_alerts = _heuristic_delay_alerts(snapshot)

    if not _ai_available():
        summary = fallback_alerts[0]['detail'] if fallback_alerts else 'No delays detected from live queue data.'
        return {
            'ok': True,
            'ai_used': False,
            'summary': summary,
            'alerts': fallback_alerts,
            'predictions': [],
        }

    from apps.core.openai_gateway import call_openai_json

    system = """You are Gearup Agent for a manufacturing execution system (MES).
Analyze live production data: open orders, station queue depths, routing std-times, and slow operations.
Identify delay risks and bottlenecks. Be specific — cite PO numbers and station codes.
Return JSON only with keys:
- summary: one sentence executive headline for the shop floor
- predictions: array of {po_number, risk, bottleneck_station, message, confidence}
- alerts: array of {severity: warning|danger|info, title, detail}
Max 5 predictions and 5 alerts. Plain English."""

    schema = {
        'type': 'object',
        'properties': {
            'summary': {'type': 'string'},
            'predictions': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'po_number': {'type': 'string'},
                        'risk': {'type': 'string'},
                        'bottleneck_station': {'type': 'string'},
                        'message': {'type': 'string'},
                        'confidence': {'type': 'string'},
                    },
                    'required': ['po_number', 'message'],
                },
            },
            'alerts': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'severity': {'type': 'string'},
                        'title': {'type': 'string'},
                        'detail': {'type': 'string'},
                    },
                    'required': ['title', 'detail'],
                },
            },
        },
        'required': ['summary', 'predictions', 'alerts'],
    }

    try:
        data = call_openai_json(
            system=system,
            user_payload=snapshot,
            temperature=0.2,
            feature='mes_agent_delay',
            model=MES_AGENT_MODEL,
            json_schema=schema,
            json_schema_name='mes_delay_prediction',
        )
        return {
            'ok': True,
            'ai_used': True,
            'summary': data.get('summary') or '',
            'predictions': data.get('predictions') or [],
            'alerts': data.get('alerts') or fallback_alerts,
        }
    except Exception as exc:
        logger.warning('MES delay prediction AI failed: %s', exc)
        return {
            'ok': True,
            'ai_used': False,
            'summary': fallback_alerts[0]['detail'] if fallback_alerts else 'Analysis unavailable.',
            'predictions': [],
            'alerts': fallback_alerts,
            'error': str(exc),
        }


def run_nl_query(company, question: str) -> dict:
    question = (question or '').strip()
    if not question:
        return {'ok': False, 'message': 'Enter a question.'}

    snapshot = build_mes_snapshot(company)
    if not _ai_available():
        return {
            'ok': True,
            'ai_used': False,
            'answer': _fallback_nl_answer(question, snapshot),
        }

    from apps.core.openai_gateway import call_openai_json

    system = """You are Gearup Agent answering natural-language questions about live MES data
(production orders, station queues, parts progress, due dates). Answer concisely in 2–4 sentences.
If the data does not contain the answer, say what is missing. No markdown bullets.
Return JSON: {"answer": "..."}"""

    try:
        data = call_openai_json(
            system=system,
            user_payload={'question': question, 'mes_data': snapshot},
            temperature=0.2,
            feature='mes_agent_ask',
            model=MES_AGENT_MODEL,
            json_schema={
                'type': 'object',
                'properties': {'answer': {'type': 'string'}},
                'required': ['answer'],
            },
            json_schema_name='mes_nl_answer',
        )
        return {'ok': True, 'ai_used': True, 'answer': data.get('answer') or ''}
    except Exception as exc:
        logger.warning('MES NL query failed: %s', exc)
        return {
            'ok': True,
            'ai_used': False,
            'answer': _fallback_nl_answer(question, snapshot),
        }


def _fallback_nl_answer(question: str, snapshot: dict) -> str:
    q = question.lower()
    queues = snapshot.get('station_queues', [])
    if 'stuck' in q or 'paint' in q or 'waiting' in q:
        for row in queues:
            if row['code'].lower() in q or row['name'].lower() in q:
                return f"{row['waiting_parts']} parts waiting at {row['code']} ({row['name']})."
        if queues:
            top = max(queues, key=lambda x: x.get('waiting_parts', 0))
            return f"Busiest station: {top['code']} with {top['waiting_parts']} parts waiting."
    if 'behind' in q or 'late' in q or 'overdue' in q:
        at_risk = [
            p for p in snapshot.get('open_production_orders', [])
            if p.get('days_to_due') is not None and p['days_to_due'] <= 0
        ]
        if at_risk:
            nums = ', '.join(p['po_number'] for p in at_risk[:5])
            return f"Orders past due: {nums}."
        return 'No open orders are past due date based on current data.'
    return 'Connect OpenAI for full natural-language answers. Try asking about a station code or overdue orders.'


def run_delay_classification(company) -> dict:
    snapshot = build_mes_snapshot(company)
    slow = snapshot.get('slow_operations', [])

    if not slow:
        return {
            'ok': True,
            'ai_used': False,
            'classifications': [],
            'summary': 'No operations significantly over standard time in the last 14 days.',
        }

    if not _ai_available():
        return {
            'ok': True,
            'ai_used': False,
            'classifications': [
                {
                    'po_number': row['po_number'],
                    'station': row['station'],
                    'likely_reason': 'Capacity / queue backlog',
                    'detail': f"Ran {row['actual_minutes']} min vs {row['std_minutes']} min std.",
                }
                for row in slow
            ],
            'summary': f'{len(slow)} slow operation(s) detected — likely queue or capacity related.',
        }

    from apps.core.openai_gateway import call_openai_json

    system = """Classify why manufacturing operations exceeded standard time.
Likely reasons: material_wait, machine_issue, rework, capacity_queue, staffing, unknown.
Use patterns in the data. Return JSON:
{"summary": "...", "classifications": [{"po_number", "station", "likely_reason", "detail"}]}"""

    try:
        data = call_openai_json(
            system=system,
            user_payload={'slow_operations': slow, 'station_queues': snapshot.get('station_queues')},
            temperature=0.2,
            feature='mes_agent_classify',
            model=MES_AGENT_MODEL,
            json_schema={
                'type': 'object',
                'properties': {
                    'summary': {'type': 'string'},
                    'classifications': {'type': 'array', 'items': {'type': 'object'}},
                },
                'required': ['summary', 'classifications'],
            },
            json_schema_name='mes_delay_classify',
        )
        return {
            'ok': True,
            'ai_used': True,
            'summary': data.get('summary') or '',
            'classifications': data.get('classifications') or [],
        }
    except Exception as exc:
        logger.warning('MES delay classify failed: %s', exc)
        return {
            'ok': True,
            'ai_used': False,
            'classifications': [
                {
                    'po_number': row['po_number'],
                    'station': row['station'],
                    'likely_reason': 'capacity_queue',
                    'detail': f"Ran {row['actual_minutes']} min vs {row['std_minutes']} min std.",
                }
                for row in slow
            ],
            'summary': f'{len(slow)} slow operation(s) — rule-based classification.',
        }


def run_draft_template(company, description: str) -> dict:
    description = (description or '').strip()
    if not description:
        return {'ok': False, 'message': 'Describe the product to draft a template.'}

    work_centers = list(
        WorkCenter.objects.filter(company=company, is_active=True, is_production_step=True)
        .order_by('sequence_order')
        .values('code', 'name', 'cost_per_hour'),
    )

    if not _ai_available():
        return {
            'ok': True,
            'ai_used': False,
            'template_name': description[:80],
            'bom_lines': [
                {'part_name': 'Main panel', 'material_type': 'panel', 'quantity': '1', 'unit': 'pcs'},
            ],
            'routing_steps': [
                {'work_center_code': wc['code'], 'std_time_minutes': 20}
                for wc in work_centers[:4]
            ],
            'notes': 'AI draft unavailable — configure OpenAI for full BOM/routing suggestions.',
        }

    from apps.core.openai_gateway import call_openai_json

    system = """Draft a manufacturing product template for engineer-to-order furniture (Depa-style).
Given a short description, propose BOM lines and routing steps using available work centers.
material_type must be one of: panel, veneer, hardware, edge_tape, finish.
Return JSON:
{
  "template_name": "...",
  "template_code": "SHORT-CODE",
  "description": "...",
  "bom_lines": [{"part_name", "material_type", "quantity", "unit", "item_code_hint"}],
  "routing_steps": [{"work_center_code", "std_time_minutes", "sequence"}],
  "notes": "..."
}
Use realistic quantities for UAE joinery. 3–8 BOM lines, 2–6 routing steps."""

    try:
        data = call_openai_json(
            system=system,
            user_payload={'description': description, 'work_centers': work_centers},
            temperature=0.35,
            feature='mes_agent_draft',
            model=MES_AGENT_MODEL,
            json_schema={
                'type': 'object',
                'properties': {
                    'template_name': {'type': 'string'},
                    'template_code': {'type': 'string'},
                    'description': {'type': 'string'},
                    'bom_lines': {'type': 'array', 'items': {'type': 'object'}},
                    'routing_steps': {'type': 'array', 'items': {'type': 'object'}},
                    'notes': {'type': 'string'},
                },
                'required': ['template_name', 'bom_lines', 'routing_steps'],
            },
            json_schema_name='mes_template_draft',
        )
        return {'ok': True, 'ai_used': True, **data}
    except Exception as exc:
        logger.warning('MES template draft failed: %s', exc)
        return {'ok': False, 'message': str(exc)}


def run_cost_estimate(company, spec: str) -> dict:
    spec = (spec or '').strip()
    if not spec:
        return {'ok': False, 'message': 'Enter a rough spec to estimate cost.'}

    rates = {
        'work_centers': list(
            WorkCenter.objects.filter(company=company, is_active=True)
            .values('code', 'name', 'cost_per_hour'),
        ),
        'default_overhead_pct': 10,
        'currency': 'AED',
    }

    if not _ai_available():
        return {
            'ok': True,
            'ai_used': False,
            'material_cost': '0',
            'labour_cost': '0',
            'machine_cost': '0',
            'overhead_cost': '0',
            'total_cost': '0',
            'per_unit_cost': '0',
            'assumptions': ['Configure OpenAI for AI-powered estimates.'],
            'summary': 'Heuristic estimate unavailable without AI.',
        }

    from apps.core.openai_gateway import call_openai_json

    system = """Estimate manufacturing cost for engineer-to-order joinery in AED.
Use typical UAE material costs and provided work-center hourly rates.
Return JSON with string decimal fields:
material_cost, labour_cost, machine_cost, overhead_cost, total_cost, per_unit_cost,
assumptions (array of strings), summary (one sentence)."""

    try:
        data = call_openai_json(
            system=system,
            user_payload={'spec': spec, 'rates': rates},
            temperature=0.25,
            feature='mes_agent_estimate',
            model=MES_AGENT_MODEL,
            json_schema={
                'type': 'object',
                'properties': {
                    'material_cost': {'type': 'string'},
                    'labour_cost': {'type': 'string'},
                    'machine_cost': {'type': 'string'},
                    'overhead_cost': {'type': 'string'},
                    'total_cost': {'type': 'string'},
                    'per_unit_cost': {'type': 'string'},
                    'assumptions': {'type': 'array', 'items': {'type': 'string'}},
                    'summary': {'type': 'string'},
                },
                'required': ['total_cost', 'summary'],
            },
            json_schema_name='mes_cost_estimate',
        )
        return {'ok': True, 'ai_used': True, **data}
    except Exception as exc:
        logger.warning('MES cost estimate failed: %s', exc)
        return {'ok': False, 'message': str(exc)}
