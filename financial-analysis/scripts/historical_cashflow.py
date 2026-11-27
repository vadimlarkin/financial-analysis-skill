"""Historical business cash before creditor payments, with retained classifications.

Consumes the existing reconciled bank result and verified obligation register.
Money uses Decimal; unknown coverage never becomes a zero or a complete ratio.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

from calculate_cashflow import ALIASES
from check_cashflow import amount, date_value, money

VERSION = 'historical-cashflow-1.0'
ZERO = Decimal('0')
KINDS = {'business_receipt', 'customer_refund', 'ordinary_expense', 'tax',
         'necessary_business_expense', 'creditor_payment', 'accumulated_obligation',
         'borrowed_receipt', 'owner_loan', 'owner_contribution', 'owner_withdrawal',
         'other_external_receipt', 'technical_refund', 'own_transfer'}
DEFAULTS = {'revenue': 'business_receipt', 'customer_refund': 'customer_refund',
            'received_loan': 'borrowed_receipt', 'principal': 'creditor_payment',
            'interest': 'creditor_payment', 'debt_payment_unsplit': 'creditor_payment',
            'payroll': 'ordinary_expense', 'suppliers': 'ordinary_expense', 'taxes': 'tax',
            'card': 'ordinary_expense', 'own_transfer_matched': 'own_transfer'}
INCOMING = {'business_receipt', 'borrowed_receipt', 'owner_loan', 'owner_contribution',
            'other_external_receipt'}
OUTGOING = {'customer_refund', 'ordinary_expense', 'tax', 'necessary_business_expense',
            'creditor_payment', 'accumulated_obligation', 'owner_withdrawal'}
COMPONENTS = ('business_receipts', 'ordinary_expenses', 'taxes', 'necessary_business_expenses',
              'owner_withdrawals', 'owner_debt_payments', 'creditor_payments',
              'external_receipts', 'borrowed_receipts', 'owner_loans', 'owner_contributions',
              'business_flow_before_creditors')


def shifted_month(first, delta):
    index = first.year * 12 + first.month - 1 + delta
    return date(index // 12, index % 12 + 1, 1)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def turnover_series(months, operations, settlement_links):
    """Project bank-classified client receipts and documented debt payments once."""
    rows = []
    for month in months:
        receipts = deepcopy(month['totals']['business_receipts'])
        parts = {'principal': [], 'interest': []}
        unresolved = []
        for term in month['totals']['creditor_payments']['terms']:
            uid = term['operation_id']
            settlements = settlement_links.get(uid)
            if settlements:
                # A total and its breakdown are different views of one payment.
                details = [part for item in settlements
                           for part in (item.get('components', []) if item['component'] == 'total' else [item])]
                if sum((Decimal(part['amount']) for part in details), ZERO) != Decimal(term['amount']):
                    unresolved.append(uid)
            else:
                category = operations[uid]['category']
                if category not in parts:
                    unresolved.append(uid)
                    continue
                details = [{'component': category, 'amount': term['amount'], 'sources': term['sources']}]
            for item in details:
                if item['component'] in parts:
                    parts[item['component']].append({'operation_id': uid, 'amount': item['amount'],
                                                      'sources': deepcopy(item['sources'])})
        row = {'month': month['month'], 'period': deepcopy(month['period']), 'receipts': receipts,
               'unresolved_payment_ids': sorted(set(unresolved))}
        for component, values in parts.items():
            observed = money(sum((Decimal(part['amount']) for part in values), ZERO))
            row[component + '_paid'] = {
                'value': observed if month['complete'] and not unresolved else None, 'known_subtotal': observed,
                'sources': sorted({sid for term in values for sid in term['sources']}) or receipts['sources'],
                'terms': values,
            }
        rows.append(row)
    complete = bool(rows) and all(row['receipts']['value'] is not None for row in rows)
    average = None
    if complete:
        total = sum((Decimal(row['receipts']['value']) for row in rows), ZERO)
        average = money((total / len(rows)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    return {'months': rows, 'receipts_complete': complete,
            'average_receipts': {'value': average,
                                 'sources': sorted({sid for row in rows for sid in row['receipts']['sources']}),
                                 'formula': 'Сумма поступлений покупателей за полные месяцы / число этих месяцев'}}


def calculate(cashflow, register, config, assessment_date, sources, source_versions,
              *, outside_transfers=(), duplicate_lineage=()):
    if not isinstance(config, dict) or set(config) - {'reviewed_by', 'classifications'}:
        raise ValueError('historical_cashflow: нужны reviewed_by и classifications')
    if not isinstance(config.get('reviewed_by'), str) or not config['reviewed_by'].strip():
        raise ValueError('historical_cashflow.reviewed_by: укажите аналитика')
    if not cashflow.get('ok') or not register.get('ok'):
        raise ValueError('История требует пригодные результаты выписок и реестра обязательств')
    today = date.fromisoformat(assessment_date)
    end = today.replace(day=1) - timedelta(days=1)
    first = shifted_month(today.replace(day=1), -12)
    available = cashflow['period']
    available_start, available_end = (date.fromisoformat(available[k]) for k in ('start', 'end'))
    refs = {s['id'] for s in sources}
    rows = deepcopy(cashflow['operations'])
    for row in rows:
        row['date'] = date_value(row['date']).isoformat()
        row['category'] = ALIASES.get(row['category'], row['category'])
    # Recognized identities must cross the existing overlap boundary first.
    # Equal amounts/purposes alone are not evidence of a duplicate.
    identities = {}
    for row in rows:
        keys = []
        bank_id = row.get('bank_operation_id')
        if bank_id is not None:
            if not isinstance(bank_id, str) or not bank_id.strip():
                raise ValueError('bank_operation_id требует непустой идентификатор банка')
            keys.append(('bank', row['account'], bank_id))
        if row.get('source_row') is not None:
            if not isinstance(row['source_row'], str) or not row['source_row'].strip():
                raise ValueError('source_row требует точную исходную строку')
            version = source_versions.get(row['source'])
            if version is not None:
                keys.append(('source', row['account'], version, row['source_row']))
        for key in keys:
            if key in identities:
                raise ValueError('Известный повтор операции '+identities[key]+' / '+row['id']+
                                 ': требуется сверка cashflow.overlaps до расчёта истории')
            identities[key] = row['id']
    by_id = {r['id']: r for r in rows}
    if len(by_id) != len(rows):
        raise ValueError('Повтор ID операции после сверки выписок')
    decisions = config.get('classifications', [])
    if not isinstance(decisions, list):
        raise ValueError('historical_cashflow.classifications: нужен массив')
    selected = {}
    contexts = []
    for item in decisions:
        if not isinstance(item, dict) or set(item) - {'operation_id', 'kind', 'reason', 'sources', 'related_operation_id'}:
            raise ValueError('Неверные поля классификации истории')
        uid = item.get('operation_id')
        if uid not in by_id or uid in selected or item.get('kind') not in KINDS:
            raise ValueError('Классификация требует уникальную известную операцию и поддерживаемый kind')
        if not isinstance(item.get('reason'), str) or not item['reason'].strip():
            raise ValueError('Классификация требует основание аналитика')
        links = item.get('sources')
        if not isinstance(links, list) or not links or len(set(links)) != len(links) or any(s not in refs for s in links):
            raise ValueError('Классификация требует непустые источники')
        if item['kind'] != 'technical_refund' and 'related_operation_id' in item:
            raise ValueError('related_operation_id относится только к техническому возврату')
        selected[uid] = deepcopy(item)
        stable = deepcopy(item);stable['sources'] = sorted(links);stable['reason'] = ' '.join(item['reason'].split())
        related = [by_id[uid]]
        if item.get('related_operation_id') in by_id:
            related.append(by_id[item['related_operation_id']])
        relevant = set(links) | {r['source'] for r in related}
        contexts.append({'operation_id': uid, 'signature': digest(stable),
                         'context_sha256': digest({'operations': related,
                             'sources': {s: source_versions[s] for s in sorted(relevant)}})})

    outside_ids = {r['operation_id'] for r in outside_transfers}
    linked = {}; unmatched = []; owner_ids = set()
    for contract in register['contracts']:
        for payment in contract.get('settlements', []):
            uid = payment.get('operation_id')
            if not uid:
                if available_start <= date.fromisoformat(payment['date']) <= available_end:
                    unmatched.append({'code': 'settlement_without_operation', 'date': payment['date'],
                                      'contract_id': contract['id'], 'payment': deepcopy(payment)})
                continue
            if uid not in by_id:
                if available_start <= date.fromisoformat(payment['date']) <= available_end:
                    unmatched.append({'code': 'settlement_operation_missing', 'operation_id': uid,
                                      'date': payment['date'], 'contract_id': contract['id'], 'payment': deepcopy(payment)})
                continue
            row = by_id[uid]
            if contract.get('issues') or contract.get('confirmation', {}).get('status') != 'confirmed':
                unmatched.append({'code':'settlement_unconfirmed', 'operation_id':uid,
                                  'date':payment['date'], 'contract_id':contract['id'], 'payment':deepcopy(payment)})
                continue
            if row['date'] != payment['date'] or not amount(row['debit']):
                raise ValueError('Исполненный платёж не соответствует дате/направлению операции '+uid)
            linked.setdefault(uid, []).append({'contract_id': contract['id'], **deepcopy(payment)})
    for uid, payments in linked.items():
        if sum((amount(p['amount']) for p in payments), ZERO) != amount(by_id[uid]['debit']):
            raise ValueError('Сумма распределённых исполнений не равна операции; требуется сверка '+uid)
    for payment in register.get('owner_payments', []):
        uid = payment['operation_id']
        if uid not in by_id:
            if available_start <= date.fromisoformat(payment['date']) <= available_end:
                unmatched.append({'code': 'owner_payment_operation_missing', **deepcopy(payment)})
            continue
        row = by_id[uid]
        if row['date'] != payment['date'] or not amount(row['debit']) or amount(row['debit']) != amount(payment['amount']):
            raise ValueError('Выплата за собственника не соответствует операции '+uid)
        if uid in linked:
            raise ValueError('Одна операция отнесена и к долгу заёмщика, и к выплате за собственника '+uid)
        owner_ids.add(uid)

    for uid, item in selected.items():
        if item['kind'] != 'technical_refund':
            continue
        other_id = item.get('related_operation_id')
        other = selected.get(other_id, {})
        if (other_id == uid or other.get('kind') != 'technical_refund' or other.get('related_operation_id') != uid):
            raise ValueError('Технический возврат требует обе взаимно связанные операции')
        row, mate = by_id[uid], by_id[other_id]
        if not (amount(row['debit']) == amount(mate['credit']) and amount(row['credit']) == amount(mate['debit'])):
            raise ValueError('Не сходятся стороны технического возврата')

    classified = []; exclusions = []; unresolved = []
    for row in sorted(rows, key=lambda r: (r['date'], r['id'])):
        uid = row['id']; explicit = selected.get(uid)
        kind = explicit['kind'] if explicit else DEFAULTS.get(row['category'])
        evidence = sorted({row['source']} | set(explicit.get('sources', []) if explicit else []))
        reason = explicit['reason'] if explicit else 'Подтверждённая категория '+row['category']
        if row.get('category_status') != 'confirmed':
            kind = None;reason = 'Исходная категория операции не подтверждена'
        if row['category'] == 'own_transfer_matched':
            if explicit and explicit['kind'] != 'own_transfer':
                raise ValueError('Подтверждённая пара собственного перевода не является внешней операцией '+uid)
            kind = 'own_transfer'
        if uid in outside_ids:
            if explicit and explicit['kind'] != 'own_transfer':
                raise ValueError('Собственный перевод на непредставленный счёт не является внешним поступлением '+uid)
            kind = 'own_transfer'
        if kind == 'own_transfer' and row['category'] != 'own_transfer_matched' and uid not in outside_ids:
            raise ValueError('Исключение собственного перевода требует проверенную пару или счёт вне охвата '+uid)
        if uid in linked:
            if explicit and explicit['kind'] not in {'creditor_payment', 'accumulated_obligation'}:
                raise ValueError('Классификация расхода противоречит исполнению обязательства '+uid)
            if kind in {'technical_refund', 'own_transfer'}:
                raise ValueError('Исполненное обязательство нельзя исключить как техническую операцию '+uid)
            kind = 'accumulated_obligation';reason = 'Исполнение связано с реестром обязательств'
            evidence = sorted(set(evidence) | {s for p in linked[uid] for s in p['sources']})
        if uid in owner_ids:
            if kind in {'technical_refund', 'own_transfer'}:
                raise ValueError('Выплату за собственника нельзя исключить как техническую операцию '+uid)
            if explicit and explicit['kind'] != 'owner_withdrawal':
                raise ValueError('Классификация противоречит выплате за собственника '+uid)
            kind = 'owner_debt_payment';reason = 'Подтверждённая выплата компании за собственника'
            evidence = sorted(set(evidence) | {s for p in register['owner_payments'] if p['operation_id'] == uid for s in p['sources']})
        if row.get('category_status') != 'confirmed':
            kind = None;reason = 'Исходная категория операции не подтверждена'
        if kind in INCOMING and amount(row['debit']) or kind in OUTGOING and amount(row['credit']):
            raise ValueError('Направление операции противоречит роли истории '+uid)
        item = {'operation_id': uid, 'date': row['date'], 'kind': kind,
                'debit': row['debit'], 'credit': row['credit'], 'source': row['source'],
                'sources': evidence, 'reason': reason, 'category': row['category']}
        if kind in {'own_transfer', 'technical_refund'}:
            exclusions.append(item)
        elif kind is None:
            unresolved.append(item)
        classified.append(item)

    def window(start, stop):
        period = {'start': start.isoformat(), 'end': stop.isoformat()}
        coverage = cashflow['coverage']
        missing = coverage.get('missing_months')
        limits = []
        if start < available_start or stop > available_end:
            limits.append({'code': 'period_not_covered', 'available': deepcopy(available)})
        if not coverage['complete'] and (not missing or any(start.strftime('%Y-%m') <= m <= stop.strftime('%Y-%m') for m in missing)):
            limits.append({'code': 'bank_coverage_incomplete', 'document_coverage': deepcopy(cashflow.get('document_coverage', {}))})
        selected_rows = [r for r in classified if start.isoformat() <= r['date'] <= stop.isoformat()]
        unresolved_rows = [r['operation_id'] for r in selected_rows if r['kind'] is None]
        if unresolved_rows:limits.append({'code': 'classification_unresolved', 'operation_ids': unresolved_rows})
        unmatched_rows = [p for p in unmatched if start.isoformat() <= p['date'] <= stop.isoformat()]
        if unmatched_rows:limits.append({'code': 'unmatched_documented_payments', 'payments': deepcopy(unmatched_rows)})
        if outside_ids:limits.append({'code': 'own_account_outside_statements', 'operation_ids': sorted(outside_ids)})
        complete = not limits
        terms = {key: [] for key in COMPONENTS}
        def add(key, row, side, sign=1):
            if amount(row[side]):terms[key].append({'operation_id': row['operation_id'], 'side': side, 'sign': sign,
                                                   'amount': money(amount(row[side])), 'sources': row['sources']})
        for row in selected_rows:
            kind = row['kind']
            if kind in INCOMING:add('external_receipts', row, 'credit')
            if kind == 'business_receipt':add('business_receipts', row, 'credit')
            elif kind == 'customer_refund':add('business_receipts', row, 'debit', -1)
            elif kind == 'ordinary_expense':add('ordinary_expenses', row, 'debit')
            elif kind == 'tax':add('taxes', row, 'debit')
            elif kind == 'necessary_business_expense':add('necessary_business_expenses', row, 'debit')
            elif kind == 'owner_withdrawal':add('owner_withdrawals', row, 'debit')
            elif kind == 'owner_debt_payment':add('owner_debt_payments', row, 'debit')
            elif kind in {'creditor_payment', 'accumulated_obligation'}:add('creditor_payments', row, 'debit')
            if kind in {'borrowed_receipt', 'owner_loan'}:add('borrowed_receipts', row, 'credit')
            if kind == 'owner_loan':add('owner_loans', row, 'credit')
            elif kind == 'owner_contribution':add('owner_contributions', row, 'credit')
        terms['business_flow_before_creditors'] = deepcopy(terms['business_receipts'])
        for key in ('ordinary_expenses', 'taxes', 'necessary_business_expenses', 'owner_withdrawals', 'owner_debt_payments'):
            terms['business_flow_before_creditors'] += [dict(term, sign=-term['sign']) for term in terms[key]]
        totals = {}
        for key, values in terms.items():
            subtotal = sum((Decimal(t['amount']) * t['sign'] for t in values), ZERO)
            totals[key] = {'value': money(subtotal) if complete else None, 'known_subtotal': money(subtotal),
                'period': deepcopy(period), 'sources': sorted({s for t in values for s in t['sources']}) or sorted(refs),
                'operation_ids': sorted({t['operation_id'] for t in values}), 'terms': values,
                'calculated': True, 'conservative': False}
        def ratio(numerator, denominator, percent=False):
            top, bottom = totals[numerator], totals[denominator]
            reason = 'incomplete_coverage' if not complete else 'zero_denominator' if Decimal(bottom['value']) == ZERO else None
            value = None if reason else format((Decimal(top['value']) / Decimal(bottom['value']) * (100 if percent else 1)).quantize(
                Decimal('0.000001'), rounding=ROUND_HALF_UP), 'f')
            return {'value': value, 'unit': '%' if percent else 'ratio', 'period': deepcopy(period),
                    'numerator': deepcopy(top), 'denominator': deepcopy(bottom), 'reason': reason,
                    'sources': sorted(set(top['sources']) | set(bottom['sources'])),
                    'calculated': True, 'conservative': False,
                    'formula': numerator+' / '+denominator+(' * 100' if percent else '')}
        return {'period': period, 'complete': complete, 'totals': totals, 'limitations': limits,
                'historical_coverage': ratio('business_flow_before_creditors', 'creditor_payments'),
                'borrowed_share': ratio('borrowed_receipts', 'external_receipts', True)}

    months = []
    for offset in range(12):
        start = shifted_month(first, offset);stop = shifted_month(start, 1)-timedelta(days=1)
        months.append({'month': start.strftime('%Y-%m'), **window(start, stop)})
    windows = {str(size)+'m': window(shifted_month(today.replace(day=1), -size), end) for size in (12, 6)}
    return {'schema_version': VERSION, 'assessment_date': assessment_date, 'currency': cashflow.get('currency', 'RUB'),
            'borrower_id': register['borrower_id'], 'borrower_kind': register.get('borrower_kind'),
            'reviewed_by': config['reviewed_by'], 'available_period': deepcopy(available),
            'complete': all(w['complete'] for w in windows.values()), 'windows': windows, 'months': months,
            'classified_operations': classified, 'exclusions': exclusions, 'unresolved_operations': unresolved,
            'unmatched_payments': unmatched, 'settlement_links': linked,
            'turnover': turnover_series(months, by_id, linked),
            'duplicate_lineage': deepcopy(list(duplicate_lineage)), 'sources': deepcopy(sources),
            'source_versions': deepcopy(source_versions), 'runner_decision_contexts': contexts,
            'limitations': ['Поток относится к представленным счетам и проверенной классификации.',
                            'Денежные поступления ИП не являются бухгалтерской выручкой или прибылью.',
                            'Займы и взносы собственника не входят в поток бизнеса до выплат кредиторам.']}
