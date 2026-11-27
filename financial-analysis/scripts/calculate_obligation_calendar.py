"""Six-month existing-obligation calendar from the reviewed debt register.

No proposed-loan terms are inputs. Facts, calculated aggregates, and conservative
assumptions remain separate; unknown amounts are not replaced with zero.
"""
from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal

VERSION = 'local-obligation-calendar-1.0'


def add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def calculate(register, assessment_date):
    start = date.fromisoformat(assessment_date)
    boundaries = [add_months(start, i) for i in range(7)]
    end = boundaries[-1]
    events, unestimated, excluded, assumptions = [], [], [], []
    sources = deepcopy(register['sources'])

    def money(value):
        return format(Decimal(str(value)).quantize(Decimal('0.01')), '.2f')

    def locate(day):
        return next((i for i in range(6) if boundaries[i] <= day < boundaries[i+1]), None)

    def missing(contract, reason, **extra):
        row = contract.get('accepted') or {}
        item = {'contract_id': contract['id'], 'creditor_id': row.get('creditor_id'),
                'reason': reason, 'sources': deepcopy(row.get('sources', [])), 'affects_scenario': True, **extra}
        if item not in unestimated:
            unestimated.append(item)

    def event(contract, event_id, day, amount, refs, basis, *, conservative=False, assumed=False):
        at = date.fromisoformat(day) if isinstance(day, str) else day
        documented_due_date = at.isoformat()
        source_basis = basis
        overdue = at < start and (basis == 'confirmed_complete_schedule' or basis.startswith('documented_'))
        if overdue:
            at = start
            assumed = True
            conservative = True
            basis = 'unpaid_overdue_schedule_at_report_date' if source_basis == 'confirmed_complete_schedule' else 'unpaid_overdue_partial_at_report_date'
        month_index = locate(at)
        if month_index is None:
            return
        row = contract['accepted']
        if amount is None:
            missing(contract, 'Сумма установленного платежа неизвестна.', payment_id=event_id, date=at.isoformat(), sources=sorted(set(refs)))
            return
        events.append({'id': contract['id'] + ':' + event_id, 'contract_id': contract['id'],
                       'record_id': row['id'], 'creditor_id': row['creditor_id'],
                       'obligation_type': contract.get('obligation_type', 'other'),
                       'date': at.isoformat(), 'documented_due_date': documented_due_date if not assumed or overdue else None, 'month_index': month_index + 1, 'amount': money(amount),
                       'sources': sorted(set(refs)), 'basis': basis, 'source_basis': source_basis,
                       'calculated': assumed, 'conservative': conservative,
                       'date_basis': 'scenario_assumption' if assumed else 'documented_payment_date'})

    review = deepcopy(register.get('active_obligations_review'))
    if review and review['as_of'] != assessment_date:
        review['status'] = 'stale'
    absence_confirmed = review is not None and review['status'] == 'confirmed_absence'
    absence_sources = review['sources'] if absence_confirmed else []
    scope_reasons = {
        'stale': 'Сверка обязательств не доведена до даты анализа.',
        'incomplete': 'Полнота проверки обязательств не подтверждена.',
        'conflicting': 'Отметка об отсутствии обязательств расходится с записями реестра.',
    }
    scope_reason = (scope_reasons.get(review['status']) if review else
                    'Полнота проверки обязательств не подтверждена.')

    for contract in register['contracts']:
        row = contract.get('accepted')
        if not contract.get('eligible_for_calendar'):
            if row and not contract.get('issues') and (row['status'] == 'closed' or
                    contract.get('inclusion_basis') == 'guarantee_without_confirmed_demand'):
                excluded.append({'contract_id': contract['id'], 'reason': 'closed' if row['status'] == 'closed' else 'guarantee_without_confirmed_demand',
                                 'sources': deepcopy(row['sources'])})
            else:
                missing(contract, 'Обязательство требует сверки и не включено в числовую оценку.', issues=deepcopy(contract.get('issues', [])))
            continue
        schedule = row.get('payment_schedule')
        if schedule:
            for payment in schedule['payments']:
                event(contract, payment['id'], payment['date'], payment['amount'],
                      sorted(set(payment['sources']) | set(schedule['sources'])), 'confirmed_complete_schedule')
            continue
        balance = row['amounts'].get('total')
        monthly = row.get('monthly_payment')
        regular = bool(monthly and monthly.get('as_of') and monthly.get('frequency') == 'monthly' and monthly.get('amount') is not None)
        if balance is not None:
            event(contract, 'balance-first-month', start, balance, row['sources'],
                  'known_balance_without_schedule', conservative=True, assumed=True)
            assumptions.append({'contract_id': contract['id'], 'code': 'balance_in_first_month',
                                'reason': 'Подтверждённый остаток без полного графика целиком отнесён к началу первого месяца. Это консервативная расчётная дата, не юридический срок требования.',
                                'sources': deepcopy(row['sources']), 'calculated': True, 'conservative': True,
                                'suppressed_regular_base': regular, 'superseded_payment_ids': [p['id'] for p in row.get('payments', [])]})
            for payment in row.get('payments', []):
                if date.fromisoformat(payment['date']) < end and (payment['amount'] is None or payment['treatment'] == 'unknown'):
                    missing(contract, 'Неизвестная сумма или связь отдельного платежа ограничивает сценарий по текущему остатку.', payment_id=payment['id'], date=payment['date'], sources=deepcopy(payment['sources']))
            if Decimal(str(balance)) == 0 and (regular and Decimal(str(monthly['amount'])) > 0 or any(p.get('amount') is None or Decimal(str(p['amount'])) > 0 for p in row.get('payments', []))):
                missing(contract, 'Нулевой текущий остаток не объясняет сохраняющиеся будущие платежи; нужен график.')
            continue
        # Reviewed partial payments describe remaining unpaid amounts. A past due
        # date belongs to an earlier period, not to the next regular-base interval.
        dated = [p for p in row.get('payments', []) if date.fromisoformat(p['date']) < end]
        if regular:
            # A known replace event replaces that interval's base, not the whole debt.
            replacement_months = {locate(date.fromisoformat(p['date'])) for p in dated if p['treatment'] == 'replace' and date.fromisoformat(p['date']) >= start}
            unresolved_months = {locate(date.fromisoformat(p['date'])) for p in dated if p['treatment'] == 'unknown' and date.fromisoformat(p['date']) >= start}
            for i in range(6):
                if i not in replacement_months and i not in unresolved_months:
                    event(contract, 'observed-monthly-' + str(i + 1), boundaries[i], monthly['amount'], monthly['sources'],
                          'observed_regular_continuation', conservative=True, assumed=True)
            assumptions.append({'contract_id': contract['id'], 'code': 'regular_continuation',
                                'reason': 'Продолжены наблюдаемые ежемесячные выплаты. Дата начала каждого интервала является консервативным допущением; остаток и финальный платёж неизвестны.',
                                'sources': deepcopy(monthly['sources']), 'calculated': True, 'conservative': True})
            missing(contract, 'Остаток и окончательный платёж неизвестны; продолжение регулярных выплат не устанавливает верхнюю границу нагрузки.', affects_scenario=False)
        else:
            # A principal/component is a known portion, not a fabricated total.
            components = {key: value for key, value in row['amounts'].items() if key in {'principal', 'interest', 'fees'} and value is not None}
            known_dated = any(p['amount'] is not None for p in dated)
            if components and not known_dated:
                known = sum((Decimal(str(v)) for v in components.values()), Decimal(0))
                event(contract, 'known-components-first-month', start, known, row['sources'],
                      'known_components_without_total_or_schedule', conservative=True, assumed=True)
                assumptions.append({'contract_id': contract['id'], 'code': 'known_components_in_first_month',
                                    'reason': 'Установленные компоненты отнесены к началу первого месяца; общая сумма неизвестна, просрочка повторно не прибавлена.',
                                    'components': components, 'sources': deepcopy(row['sources']), 'calculated': True, 'conservative': True})
            missing(contract, 'Общая сумма и регулярность неизвестны; отражена только установленная часть.')
        # An unknown relation limits the total, but does not erase a known payment.
        for payment in dated:
            if regular and date.fromisoformat(payment['date']) < start and payment['treatment'] in {'replace', 'unknown'}:
                missing(contract, 'Просроченный платёж относится к прежнему периоду; его отношение к будущей регулярной базе требует сверки и не заменяет её автоматически.', payment_id=payment['id'], date=payment['date'], sources=deepcopy(payment['sources']))
            if payment['treatment'] == 'unknown':
                event(contract, payment['id'], payment['date'], payment['amount'], payment['sources'], 'documented_payment_with_unknown_base_relation')
                missing(contract, 'Не установлено, заменяет ли платёж базу или добавляется к ней.', payment_id=payment['id'], date=payment['date'], sources=deepcopy(payment['sources']))
            elif not regular and any(e['contract_id'] == contract['id'] and e['basis'] == 'known_components_without_total_or_schedule' for e in events):
                missing(contract, 'Отдельный платёж не добавлен к установленным компонентам без подтверждения отсутствия повторного счёта.', payment_id=payment['id'], date=payment['date'])
            else:
                event(contract, payment['id'], payment['date'], payment['amount'], payment['sources'], 'documented_' + payment['treatment'])

    has_active_contracts = any(c.get('eligible_for_calendar') for c in register['contracts'])
    if not absence_confirmed and not unestimated and not has_active_contracts:
        scope_reason = scope_reason or 'Отсутствие действующих обязательств на дату анализа не подтверждено.'
    if scope_reason:
        unestimated.append({'contract_id': 'register_scope', 'creditor_id': None,
                            'sources': review['sources'] if review else [], 'affects_scenario': True,
                            'reason': scope_reason})

    events.sort(key=lambda item: (item['date'], item['contract_id'], item['id']))
    # Any unestimated contract may add payments in any interval: partial subtotals stay explicit.
    complete = not unestimated
    scenario_complete = not any(x.get('affects_scenario', True) for x in unestimated)
    months = []
    for i in range(6):
        selected = [e for e in events if e['month_index'] == i + 1]
        subtotal = money(sum((Decimal(e['amount']) for e in selected), Decimal(0)))
        months.append({'index': i + 1, 'start': boundaries[i].isoformat(), 'end_exclusive': boundaries[i+1].isoformat(),
                       'value': subtotal if complete else None, 'scenario_value': subtotal if scenario_complete else None, 'known_subtotal': subtotal,
                       'event_ids': [e['id'] for e in selected], 'sources': absence_sources or sorted({s for e in selected for s in e['sources']}),
                       'unestimated_contract_ids': sorted({x['contract_id'] for x in unestimated}),
                       'calculated': True, 'conservative': any(e['conservative'] for e in selected)})
    subtotal = money(sum((Decimal(e['amount']) for e in events), Decimal(0)))
    return {'schema_version': VERSION, 'assessment_date': assessment_date,
            'horizon': {'start': start.isoformat(), 'end_exclusive': end.isoformat(), 'months': 6,
                        'boundary_rule': 'monthly_anniversary_end_exclusive'},
            'events': events, 'months': months,
            'totals': {'value': subtotal if complete else None, 'scenario_value': subtotal if scenario_complete else None, 'known_subtotal': subtotal,
                       'calculated': True, 'conservative': any(e['conservative'] for e in events),
                       **({'sources': absence_sources} if absence_confirmed else {})},
            'active_obligations_review': review,
            'complete': complete, 'scenario_complete': scenario_complete, 'confirmed_schedule_complete': not unestimated and not assumptions,
            'unestimated': unestimated, 'excluded': excluded, 'assumptions': assumptions,
            'sources': sources, 'borrower_id': register['borrower_id'],
            'limitations': [
                *([] if absence_confirmed else ['Календарь отражает сведения принятого реестра.']),
                'Поступления рассматриваемого займа и срок этого займа не участвуют в календаре.',
            ]}
