"""AI review of employee HR/UAE compliance, documents, and payroll readiness."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from apps.inventory.utils import get_openai_api_key

CACHE_HOURS = 24
CACHE_PREFIX = 'employee_ai_eval:'


def _quantize(value) -> float:
    try:
        return float(Decimal(str(value or '0')).quantize(Decimal('0.01')))
    except Exception:
        return 0.0


def build_employee_snapshot(employee) -> dict:
    from apps.hr.models_extended import UAECompliance

    uc = None
    if employee.location == 'uae':
        uc, _ = UAECompliance.objects.get_or_create(employee=employee)

    leave_balances = []
    for lb in employee.leave_balances.filter(year=date.today().year).select_related('leave_type')[:10]:
        leave_balances.append({
            'type': lb.leave_type.name,
            'entitled': float(lb.entitled_days),
            'used': float(lb.used_days),
            'remaining': float(lb.remaining_days),
        })

    payroll_count = employee.payrolls.filter(is_active=True).count()

    snapshot = {
        'employee_code': employee.employee_code,
        'full_name': employee.full_name,
        'status': employee.status,
        'location': employee.location,
        'email': employee.email,
        'phone': employee.phone or '',
        'department': employee.department.name if employee.department_id else '',
        'designation': employee.designation.name if employee.designation_id else '',
        'date_of_joining': str(employee.date_of_joining) if employee.date_of_joining else '',
        'date_of_birth': str(employee.date_of_birth) if employee.date_of_birth else '',
        'probation_period_days': employee.probation_period_days,
        'is_in_probation': bool(getattr(employee, 'is_in_probation', False)),
        'basic_salary': _quantize(employee.basic_salary),
        'contract_type': employee.contract_type,
        'termination_type': employee.termination_type or '',
        'is_uae_national': bool(employee.is_uae_national),
        'emirates_id': employee.emirates_id or '',
        'visa_number': employee.visa_number or '',
        'visa_expiry': str(employee.visa_expiry) if employee.visa_expiry else '',
        'leave_balances': leave_balances,
        'payroll_record_count': payroll_count,
        'updated_at': employee.updated_at.isoformat() if employee.updated_at else '',
    }

    if uc:
        snapshot['uae_compliance'] = {
            'emirates_id_expiry': str(uc.emirates_id_expiry) if uc.emirates_id_expiry else '',
            'emirates_id_expiry_status': uc.emirates_id_expiry_status,
            'visa_type': uc.visa_type,
            'visa_expiry_status': uc.visa_expiry_status,
            'passport_number': uc.passport_number or '',
            'passport_expiry': str(uc.passport_expiry) if uc.passport_expiry else '',
            'passport_expiry_status': uc.passport_expiry_status,
            'labour_card_number': uc.labour_card_number or '',
            'labour_card_expiry': str(uc.labour_card_expiry) if uc.labour_card_expiry else '',
            'labour_card_expiry_status': uc.labour_card_expiry_status,
            'medical_insurance_provider': uc.medical_insurance_provider or '',
            'medical_insurance_expiry': str(uc.medical_insurance_expiry) if uc.medical_insurance_expiry else '',
            'medical_insurance_expiry_status': uc.medical_insurance_expiry_status,
            'bank_iban': uc.bank_iban or '',
            'bank_routing_code': uc.bank_routing_code or '',
            'iloe_applicable': bool(uc.iloe_applicable),
            'gratuity_applicable': bool(uc.gratuity_applicable),
        }

    return snapshot


def _cache_key(employee, snapshot: dict) -> str:
    raw = f"{employee.pk}|{snapshot.get('updated_at')}|{snapshot.get('status')}"
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]
    return f'{CACHE_PREFIX}{employee.pk}:{digest}'


def _normalize_flags(raw_flags: list) -> list[dict]:
    allowed_categories = {'compliance', 'documents', 'payroll', 'general'}
    allowed_severity = {'green', 'red', 'amber'}
    out = []
    for row in raw_flags or []:
        if not isinstance(row, dict):
            continue
        severity = str(row.get('severity', 'amber')).lower()
        if severity not in allowed_severity:
            severity = 'amber'
        category = str(row.get('category', 'general')).lower()
        if category not in allowed_categories:
            category = 'general'
        title = str(row.get('title', '')).strip()[:200]
        detail = str(row.get('detail', '')).strip()[:500]
        if not title:
            continue
        out.append({
            'severity': severity,
            'category': category,
            'title': title,
            'detail': detail,
        })
    return out[:12]


def _status_flag(label: str, status: str, detail_ok: str, detail_bad: str) -> dict | None:
    if status == 'red':
        return {'severity': 'red', 'category': 'documents', 'title': label, 'detail': detail_bad}
    if status == 'amber':
        return {'severity': 'amber', 'category': 'documents', 'title': label, 'detail': detail_bad}
    if status == 'green':
        return {'severity': 'green', 'category': 'documents', 'title': label, 'detail': detail_ok}
    return None


def _heuristic_evaluation(snapshot: dict) -> dict:
    flags: list[dict] = []

    if snapshot.get('status') != 'active':
        flags.append({
            'severity': 'amber',
            'category': 'general',
            'title': f"Employee status: {snapshot.get('status')}",
            'detail': 'Review whether HR records match current employment status.',
        })
    else:
        flags.append({
            'severity': 'green',
            'category': 'general',
            'title': 'Active employee',
            'detail': 'Employee record is active.',
        })

    if not snapshot.get('date_of_joining'):
        flags.append({
            'severity': 'red',
            'category': 'compliance',
            'title': 'Joining date missing',
            'detail': 'Date of joining is required for leave, gratuity, and compliance.',
        })

    if snapshot.get('location') == 'uae':
        uc = snapshot.get('uae_compliance') or {}
        for label, status_key, ok, bad in (
            ('Emirates ID expiry', 'emirates_id_expiry_status', 'Emirates ID expiry is valid.', 'Emirates ID expiry needs attention.'),
            ('Visa expiry', 'visa_expiry_status', 'Visa expiry is valid.', 'Visa expiry needs attention.'),
            ('Passport expiry', 'passport_expiry_status', 'Passport expiry is valid.', 'Passport expiry needs attention.'),
            ('Labour card expiry', 'labour_card_expiry_status', 'Labour card expiry is valid.', 'Labour card expiry needs attention.'),
            ('Medical insurance expiry', 'medical_insurance_expiry_status', 'Medical insurance is valid.', 'Medical insurance expiry needs attention.'),
        ):
            row = _status_flag(label, uc.get(status_key, ''), ok, bad)
            if row:
                flags.append(row)

        if not uc.get('bank_iban'):
            flags.append({
                'severity': 'red',
                'category': 'payroll',
                'title': 'WPS bank IBAN missing',
                'detail': 'UAE WPS requires employee bank IBAN on the compliance record.',
            })
        else:
            flags.append({
                'severity': 'green',
                'category': 'payroll',
                'title': 'WPS bank IBAN on file',
                'detail': 'Bank IBAN is recorded for WPS payroll.',
            })

    if snapshot.get('basic_salary', 0) <= 0 and snapshot.get('status') == 'active':
        flags.append({
            'severity': 'amber',
            'category': 'payroll',
            'title': 'Zero basic salary',
            'detail': 'Active employee has zero basic salary — confirm payroll setup.',
        })

    red_count = sum(1 for f in flags if f['severity'] == 'red')
    green_count = sum(1 for f in flags if f['severity'] == 'green')
    summary = (
        f'Rule-based check: {green_count} green flag(s), {red_count} red flag(s). '
        'Configure OpenAI in Settings for deeper AI review.'
    )
    return {
        'flags': flags,
        'summary': summary,
        'source': 'heuristic',
        'openai_used': False,
        'generated_at': timezone.now().isoformat(),
    }


def _parse_json_content(content: str) -> dict:
    content = (content or '').strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    return json.loads(content)


def _fetch_evaluation_from_openai(snapshot: dict) -> dict:
    api_key = get_openai_api_key()
    if not api_key:
        result = _heuristic_evaluation(snapshot)
        result['warnings'] = ['OpenAI not configured — showing rule-based checks only.']
        return result

    import urllib.error
    import urllib.request

    from apps.core.ai_knowledge import get_ai_knowledge_prompt_block
    from apps.core.models import AiModuleKnowledge

    knowledge = get_ai_knowledge_prompt_block(AiModuleKnowledge.MODULE_EMPLOYEE)
    system = (
        'You are a UAE HR compliance reviewer for a fire & safety ERP. '
        'Review employee records for UAE labour law compliance: visa, Emirates ID, passport, '
        'labour card, medical insurance, WPS bank details, probation, salary, and leave. '
        'Return ONLY valid JSON with this shape: '
        '{"flags":[{"severity":"green|red|amber","category":"compliance|documents|payroll|general",'
        '"title":"short title","detail":"one or two sentences"}],'
        '"summary":"2-3 sentence overall assessment"} '
        'Use green for OK/pass, red for must-fix issues, amber for warnings.'
        f'{knowledge}'
    )
    user_payload = json.dumps(snapshot, default=str)[:14000]
    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'Employee snapshot:\n{user_payload}'},
        ],
        'temperature': 0.2,
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        content = payload['choices'][0]['message']['content']
        data = _parse_json_content(content)
        flags = _normalize_flags(data.get('flags'))
        if not flags:
            raise ValueError('empty flags')
        return {
            'flags': flags,
            'summary': str(data.get('summary', '')).strip()[:800],
            'source': 'openai',
            'openai_used': True,
            'generated_at': timezone.now().isoformat(),
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError):
        result = _heuristic_evaluation(snapshot)
        result['warnings'] = ['AI request failed — showing rule-based checks only.']
        return result


def evaluate_employee(employee, *, force_refresh: bool = False) -> dict:
    snapshot = build_employee_snapshot(employee)
    key = _cache_key(employee, snapshot)
    if not force_refresh:
        cached = cache.get(key)
        if cached:
            cached['from_cache'] = True
            return cached

    result = _fetch_evaluation_from_openai(snapshot)
    result['from_cache'] = False
    result['employee_code'] = snapshot.get('employee_code', '')
    cache.set(key, result, timeout=int(timedelta(hours=CACHE_HOURS).total_seconds()))
    return result


def get_cached_employee_evaluation(employee) -> dict | None:
    snapshot = build_employee_snapshot(employee)
    key = _cache_key(employee, snapshot)
    cached = cache.get(key)
    if cached:
        cached['from_cache'] = True
    return cached
