#!/usr/bin/env python3
"""Summarize a locally verified debt register with dated evidence."""
from __future__ import annotations

import argparse
import copy
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from itertools import combinations
import os
from pathlib import Path
import tempfile

from currency import currency_code

VERSION = 'local-debt-register-1.0'
AMOUNTS = ('principal','interest','fees','total','overdue','limit')
OBLIGATION_TYPES = {'bank_credit','nonbank_loan','owner_loan','lease','supplier_arrears',
                    'tax_arrears','payroll_arrears','advance_refund','other'}


def money(value):
    if value is None:
        return None
    result = Decimal(str(value))
    if isinstance(value,bool) or not result.is_finite() or result < 0 or result != result.quantize(Decimal('.01')):
        raise ValueError('Сумма должна быть неотрицательной с точностью до копейки')
    return format(result, '.2f')


def pdf_number(value):
    if value is None:
        return None
    converted=float(value)
    return converted if Decimal(str(converted))==Decimal(str(value)) else None


def stamp(value, name):
    if not isinstance(value,str) or len(value)!=10 or date.fromisoformat(value).isoformat()!=value:
        raise ValueError(name+': дата требуется в формате ГГГГ-ММ-ДД')
    return value


def identity(value, name):
    if not isinstance(value,str) or not value.strip():
        raise ValueError(name+': требуется непустая строка')


def object_fields(value, allowed, name):
    if not isinstance(value,dict) or set(value)-set(allowed):
        raise ValueError(name+': неверные поля или формат объекта')


def validate(data):
    object_fields(data,{'schema_version','currency','kind','borrower_id','report_date','sources','records','decisions','borrower_kind','owner_payments','active_obligations_review'},'input')
    if data.get('schema_version')!=VERSION:
        raise ValueError('schema_version: неподдерживаемая схема')
    if data.get('kind','verified_register') not in {'bki','verified_register'}:
        raise ValueError('kind: нужен bki или verified_register')
    currency_code(data.get('currency'))
    identity(data.get('borrower_id'),'borrower_id')
    if data.get('borrower_kind') not in {None,'corporate','ip'}:
        raise ValueError('borrower_kind: нужен corporate или ip')
    report=stamp(data['report_date'],'report_date')
    refs=set()
    if not isinstance(data['sources'],list):
        raise ValueError('sources: требуется массив')
    for source in data['sources']:
        object_fields(source,{'id','file','locator','kind','sha256'},'source')
        for key in ('id','file','locator'):
            identity(source.get(key),'sources.'+key)
        if source['id'] in refs:
            raise ValueError('sources: повтор идентификатора')
        if 'sha256' in source and (not isinstance(source['sha256'],str) or len(source['sha256'])!=64 or any(c not in '0123456789abcdefABCDEF' for c in source['sha256'])):raise ValueError('source.sha256: нужен SHA256')
        refs.add(source['id'])
    def sources(values,name):
        if not isinstance(values,list) or not values or any(not isinstance(v,str) or v not in refs for v in values):
            raise ValueError(name+': нужны ссылки на объявленные источники')
    review = data.get('active_obligations_review')
    if review is not None:
        label = 'active_obligations_review'
        object_fields(review, {'as_of', 'scope_complete', 'no_active_obligations', 'sources', 'reason'}, label)
        if data.get('kind') == 'bki':
            raise ValueError(label + ': сверка всех обязательств относится к verified_register')
        if stamp(review.get('as_of'), label + '.as_of') > report:
            raise ValueError(label + ': дата сверки позже даты реестра')
        if type(review.get('scope_complete')) is not bool:
            raise ValueError(label + '.scope_complete: требуется логический признак')
        if 'no_active_obligations' not in review or type(review['no_active_obligations']) not in (bool, type(None)):
            raise ValueError(label + '.no_active_obligations: требуется логический признак или null')
        identity(review.get('reason'), label + '.reason')
        sources(review.get('sources'), label + '.sources')
    if not isinstance(data['records'],list):
        raise ValueError('records: требуется массив')
    ids=set();contracts=set()
    for row in data['records']:
        object_fields(row,{'id','contract_id','subject_id','role','creditor_id','status','as_of','sources','amounts','monthly_payment','payments','maturity','obligation_type','debt_scope','confirmation','assumptions','guarantee_demand','settlements','payment_schedule'},'record')
        for key in ('id','contract_id','subject_id','creditor_id'):
            identity(row.get(key),'record.'+key)
        if row['id'] in ids:
            raise ValueError('record.id: повтор идентификатора')
        ids.add(row['id'])
        if row['role'] not in {'borrower','guarantor','other'} or row['status'] not in {'active','closed','unknown'}:
            raise ValueError('record: неизвестная роль или статус')
        if row.get('obligation_type','other') not in OBLIGATION_TYPES:
            raise ValueError('record.obligation_type: неизвестный вид обязательства')
        if row.get('debt_scope','unknown') not in {'personal','business','corporate','unknown'}:
            raise ValueError('record.debt_scope: неизвестная сфера обязательства')
        if data.get('borrower_kind')=='corporate' and row['subject_id']==data['borrower_id'] and row.get('debt_scope')=='personal':
            raise ValueError('Личный долг собственника не является долгом компании: укажите отдельного subject_id')
        confirmation=row.get('confirmation')
        if confirmation is not None:
            object_fields(confirmation,{'status','sources','reason'},'confirmation')
            if confirmation.get('status') not in {'confirmed','unverified','conflicting'}:
                raise ValueError('confirmation.status: неизвестный статус')
            sources(confirmation.get('sources'),'confirmation.sources')
            if confirmation['status']!='confirmed':identity(confirmation.get('reason'),'confirmation.reason')
        if not isinstance(row.get('assumptions',[]),list):raise ValueError('assumptions: требуется массив')
        for assumption in row.get('assumptions',[]):
            object_fields(assumption,{'reason','sources'},'assumption')
            identity(assumption.get('reason'),'assumption.reason');sources(assumption.get('sources'),'assumption.sources')
        demand=row.get('guarantee_demand')
        if demand is not None:
            object_fields(demand,{'confirmed','as_of','sources','reason'},'guarantee_demand')
            if row['role']!='guarantor' or type(demand.get('confirmed')) is not bool:
                raise ValueError('guarantee_demand: только для роли guarantor с confirmed')
            if stamp(demand.get('as_of'),'guarantee_demand.as_of')>report:raise ValueError('guarantee_demand: дата позже отчёта')
            identity(demand.get('reason'),'guarantee_demand.reason');sources(demand.get('sources'),'guarantee_demand.sources')
        if row['subject_id']==data['borrower_id'] and row['role'] in {'borrower','guarantor'}:
            contracts.add(row['contract_id'])
        if row['as_of'] is not None and stamp(row['as_of'],'record.as_of')>report:
            raise ValueError('record.as_of: дата позже отчёта')
        sources(row['sources'],'record.sources')
        if not isinstance(row['amounts'],dict) or set(row['amounts'])-set(AMOUNTS):
            raise ValueError('record.amounts: неизвестные компоненты долга')
        for value in row['amounts'].values():
            money(value)
        monthly=row.get('monthly_payment')
        if monthly is not None:
            object_fields(monthly,{'amount','as_of','frequency','sources'},'monthly_payment')
            money(monthly['amount'])
            if monthly.get('as_of') is not None and stamp(monthly['as_of'],'monthly_payment.as_of')>report:
                raise ValueError('monthly_payment: дата позже отчёта')
            if monthly['frequency'] not in {'monthly','quarterly','annual','unknown'}:
                raise ValueError('monthly_payment.frequency: неподдерживаемая периодичность')
            sources(monthly['sources'],'monthly_payment.sources')
        maturity=row.get('maturity')
        if maturity is not None:
            object_fields(maturity,{'date','confirmed'},'maturity')
            stamp(maturity['date'],'maturity.date')
            if not isinstance(maturity['confirmed'],bool):
                raise ValueError('maturity.confirmed: требуется логический признак')
        payment_ids=set()
        if not isinstance(row.get('payments',[]),list):
            raise ValueError('payments: требуется массив')
        for payment in row.get('payments',[]):
            object_fields(payment,{'id','date','amount','treatment','sources'},'payment')
            identity(payment['id'],'payment.id')
            if payment['id'] in payment_ids:
                raise ValueError('payment.id: повтор')
            payment_ids.add(payment['id'])
            stamp(payment['date'],'payment.date');money(payment['amount'])
            if payment['treatment'] not in {'replace','additional','unknown'}:
                raise ValueError('payment.treatment: нужен replace, additional или unknown')
            sources(payment['sources'],'payment.sources')
        schedule=row.get('payment_schedule')
        if schedule is not None:
            object_fields(schedule,{'complete','as_of','sources','payments'},'payment_schedule')
            if schedule.get('complete') is not True:raise ValueError('payment_schedule: только полный подтверждённый график; частичные события передайте через payments')
            if stamp(schedule.get('as_of'),'payment_schedule.as_of')>report:raise ValueError('payment_schedule: дата позже отчёта')
            sources(schedule.get('sources'),'payment_schedule.sources')
            if not isinstance(schedule.get('payments'),list):raise ValueError('payment_schedule.payments: требуется массив')
            schedule_ids=set()
            for payment in schedule['payments']:
                object_fields(payment,{'id','date','amount','sources'},'scheduled_payment')
                identity(payment.get('id'),'scheduled_payment.id')
                if payment['id'] in schedule_ids:raise ValueError('scheduled_payment.id: повтор')
                schedule_ids.add(payment['id']);stamp(payment.get('date'),'scheduled_payment.date');money(payment.get('amount'))
                sources(payment.get('sources'),'scheduled_payment.sources')
        if not isinstance(row.get('settlements',[]),list):raise ValueError('settlements: требуется массив')
        for payment in row.get('settlements',[]):
            object_fields(payment,{'id','date','amount','component','operation_id','sources'},'settlement')
            identity(payment.get('id'),'settlement.id');money(payment.get('amount'))
            if payment.get('amount') is None:raise ValueError('settlement.amount: требуется известная фактическая сумма')
            if stamp(payment.get('date'),'settlement.date')>report:raise ValueError('settlement: дата позже отчёта')
            if payment.get('component') not in {'principal','interest','fees','total'}:raise ValueError('settlement.component: неизвестный компонент')
            if payment.get('operation_id') is not None:identity(payment['operation_id'],'settlement.operation_id')
            sources(payment.get('sources'),'settlement.sources')
    owners=data.get('owner_payments',[])
    if not isinstance(owners,list):raise ValueError('owner_payments: требуется массив')
    seen_payments=set()
    for payment in owners:
        object_fields(payment,{'operation_id','subject_id','date','amount','sources','reason'},'owner_payment')
        for key in ('operation_id','subject_id','reason'):identity(payment.get(key),'owner_payment.'+key)
        if payment['operation_id'] in seen_payments:raise ValueError('owner_payment.operation_id: повтор')
        seen_payments.add(payment['operation_id'])
        if payment['subject_id']==data['borrower_id'] or data.get('borrower_kind')=='ip':raise ValueError('owner_payment: только подтверждённые выплаты компании за отдельного собственника')
        if stamp(payment.get('date'),'owner_payment.date')>report:raise ValueError('owner_payment: дата позже отчёта')
        if money(payment.get('amount')) is None:raise ValueError('owner_payment.amount: нужна сумма')
        sources(payment.get('sources'),'owner_payment.sources')
    pairs=set()
    if not isinstance(data.get('decisions',[]),list):
        raise ValueError('decisions: требуется массив')
    for decision in data.get('decisions',[]):
        object_fields(decision,{'contracts','action','reason','sources'},'decision')
        members=decision['contracts']
        if not isinstance(members,list) or len(members)!=2 or len(set(members))!=2 or any(uid not in contracts for uid in members):
            raise ValueError('decision.contracts: нужны два разных известных прямых договора')
        pair=tuple(sorted(members))
        if pair in pairs:
            raise ValueError('decisions: повтор или противоречащие решения')
        pairs.add(pair)
        if decision['action'] not in {'merge','separate'}:
            raise ValueError('decision.action: нужен merge или separate')
        identity(decision.get('reason'),'decision.reason');sources(decision['sources'],'decision.sources')


def payment_data(contracts, blocked):
    eligible=[];missing=[];dated=[];patch=[];limitations=[]
    for contract in contracts:
        row=contract['accepted'];uid=contract['id']
        monthly=row.get('monthly_payment') if row else None
        events=row.get('payments',[]) if row else []
        valid=bool(uid not in blocked and monthly and monthly['frequency']=='monthly' and monthly.get('as_of') and monthly['amount'] is not None)
        unresolved=any(p['treatment']=='unknown' for p in events)
        fact=None
        if valid:
            eligible.append({'contract_id':uid,'record_id':row['id'],**monthly})
            fact={'value':pdf_number(monthly['amount']),'status':'confirmed' if pdf_number(monthly['amount']) is not None else 'missing','sources':monthly['sources'],'as_of':monthly['as_of']}
        else:
            missing.append(uid)
        rendered=[]
        usable_base=bool(fact and fact['value'] is not None)
        replacement_months={event['date'][:7] for event in events if event['treatment']=='replace'}
        for event in sorted(events,key=lambda p:(p['date'],p['id'])):
            dated.append({'contract_id':uid,'record_id':row['id'],**event,
                          'replaces_monthly_base':True if event['treatment']=='replace' else False if event['treatment']=='additional' else None,
                          'monthly_base_known':valid,'base_frequency':monthly['frequency'] if monthly else None,
                          'base_as_of':monthly.get('as_of') if monthly else None})
            reason=None
            if uid in blocked:
                reason='Договор требует решения; зависимый платёж не передан в числовую вставку.'
            elif unresolved:
                reason='Неизвестно правило отдельного платежа договора; зависимые платежи не переданы в числовую вставку.'
            elif event['treatment']=='additional' and not usable_base and event['date'][:7] not in replacement_months:
                reason='Месячная база неизвестна; дополнительный платёж не передан как полный итог месяца.'
            if reason:
                limitations.append({'contract_id':uid,'payment_id':event['id'],'reason':reason})
            else:
                rendered.append({'id':uid+':'+event['id'],'date':event['date'],'treatment':event['treatment'],
                                 'amount':{'value':pdf_number(event['amount']),'status':'confirmed' if pdf_number(event['amount']) is not None else 'missing','sources':event['sources']}})
        patch.append({'id':uid,'monthly_payment':fact if not unresolved else None,'payments':rendered})
    subtotal=money(sum((Decimal(str(p['amount'])) for p in eligible),Decimal(0))) if eligible else None
    guide={'regular_monthly':{'value':subtotal if contracts and not missing and not blocked else None,
                              'known_subtotal':subtotal,'frequency':'monthly','includes_dated_payments':False,
                              'known_contracts':[p['contract_id'] for p in eligible],'missing_contracts':missing,
                              'entries':eligible},
           'dated_payments':dated,'patch_limitations':limitations,
           'exact_future_schedule':False}
    return guide,{'contracts':patch}


def eligible_subject(row,data):
    return row['subject_id']==data['borrower_id'] and (row['role']=='borrower' or
        row['role']=='guarantor' and row.get('guarantee_demand',{}).get('confirmed') is True)


def closed_payment_claims(row, data):
    if row is None or row['status'] != 'closed' or not eligible_subject(row, data):
        return False
    schedule = row.get('payment_schedule')
    if schedule and schedule['as_of'] >= row['as_of']:
        payments = schedule['payments']
    else:
        payments = row.get('payments', [])
        monthly = row.get('monthly_payment')
        if monthly and monthly.get('as_of') and monthly['as_of'] >= row['as_of']:
            payments = [*payments, monthly]
    return any(p['amount'] is None or Decimal(str(p['amount'])) > 0 for p in payments)


def settlements(entries):
    """Combine evidence of one execution, preserving its separate components.

    The same bank operation may contain principal, interest and fees. Repeated
    evidence of one component is not another payment. A supplied total replaces
    its breakdown in additive output, with that breakdown retained as detail.
    """
    groups={};issues=[];history=[]
    for row in entries:
        for payment in row.get('settlements',[]):
            key=('operation',payment['operation_id']) if payment.get('operation_id') else ('payment',payment['id'])
            parts=groups.setdefault(key,{})
            component=payment['component']
            signature=(payment['date'],money(payment['amount']))
            candidate=parts.setdefault(component,{})
            if signature not in candidate:
                value=copy.deepcopy(payment);value['amount']=signature[1]
                value['settlement_ids']=[payment['id']];value['record_ids']=[row['id']]
                candidate[signature]=value
            else:
                value=candidate[signature]
                value['sources']=sorted(set(value['sources'])|set(payment['sources']))
                value['settlement_ids']=sorted(set(value['settlement_ids'])|{payment['id']})
                value['record_ids']=sorted(set(value['record_ids'])|{row['id']})
                value['id']=min(value['settlement_ids'])
    for key,components in sorted(groups.items()):
        values=[value for _,versions in sorted(components.items()) for _,value in sorted(versions.items())]
        conflict=any(len(versions)>1 for versions in components.values()) or len({value['date'] for value in values})>1
        if conflict:
            issues.append({'code':'conflicting_settlement','operation_or_payment_id':key[1],
                           'reason':'Не согласованы даты или суммы одной части исполнения'})
            history.extend(values);continue
        total=next(iter(components['total'].values())) if 'total' in components else None
        parts=[value for value in values if value['component']!='total']
        if total is not None and parts:
            subtotal=sum((Decimal(value['amount']) for value in parts),Decimal(0))
            if subtotal>Decimal(total['amount']):
                issues.append({'code':'conflicting_settlement','operation_or_payment_id':key[1],
                               'reason':'Сумма частей исполнения превышает подтверждённый общий платёж'})
                history.extend(values);continue
            total['components']=copy.deepcopy(parts)
            total['breakdown_complete']=subtotal==Decimal(total['amount'])
            total['unallocated_amount']=money(Decimal(total['amount'])-subtotal)
            total['sources']=sorted({ref for value in values for ref in value['sources']})
            total['settlement_ids']=sorted({uid for value in values for uid in value['settlement_ids']})
            total['record_ids']=sorted({uid for value in values for uid in value['record_ids']})
            history.append(total)
        else:
            history.extend(values)
    return history,issues


def summarize(data, *, assessment_date=None):
    validate(data)
    rows = copy.deepcopy(data['records'])
    direct = [r for r in rows if r['subject_id']==data['borrower_id'] and r['role'] in {'borrower','guarantor'}]
    groups = {}
    for row in direct:
        groups.setdefault(row['contract_id'],[]).append(row)
    decisions=copy.deepcopy(data.get('decisions',[]))
    parents={uid:uid for uid in groups}
    def root(uid):
        while parents[uid]!=uid:
            uid=parents[uid]
        return uid
    for decision in decisions:
        if decision['action']=='merge':
            left,right=sorted(root(uid) for uid in decision['contracts'])
            parents[right]=left
    merged={}
    for uid,entries in groups.items():
        merged.setdefault(root(uid),[]).extend(entries)
    groups=merged
    separate=set()
    for decision in decisions:
        if decision['action']=='separate':
            pair=tuple(sorted(root(uid) for uid in decision['contracts']))
            if pair[0]==pair[1]:
                raise ValueError('decisions: объединённые договоры одновременно объявлены разными')
            separate.add(pair)
    contracts=[]
    issues=[]
    for uid, entries in sorted(groups.items()):
        ignored=[r for r in entries if not r['as_of'] and all(v is None or Decimal(str(v))==0 for v in r['amounts'].values()) and not r.get('monthly_payment') and not r.get('payments')]
        dated=[r for r in entries if r['as_of']]
        selected=max(dated,key=lambda r:(r['as_of'],r['id'])) if dated else None
        problems=[]
        undated=[r['id'] for r in entries if r['as_of'] is None and r not in ignored]
        if undated:
            problems.append({'code':'undated_record','record_ids':sorted(undated)})
        if selected:
            latest=[r for r in dated if r['as_of']==selected['as_of']]
            def signature(row):
                def content(value):
                    if isinstance(value,dict):return {k:content(v) for k,v in value.items() if k!='sources'}
                    if isinstance(value,list):return [content(v) for v in value]
                    return value
                value=content({k:v for k,v in row.items() if k not in {'id','contract_id','settlements'}})
                value['amounts']={k:money(value['amounts'].get(k)) for k in AMOUNTS}
                return json.dumps(value,sort_keys=True)
            if len({signature(r) for r in latest})>1:
                problems.append({'code':'conflicting_latest','record_ids':sorted(r['id'] for r in latest)})
            elif len(latest)>1:
                selected['sources']=sorted({ref for r in latest for ref in r['sources']})
                for field in ('confirmation','monthly_payment','guarantee_demand','payment_schedule'):
                    if selected.get(field):selected[field]['sources']=sorted({ref for r in latest for ref in r[field]['sources']})
                for assumption in selected.get('assumptions',[]):
                    assumption['sources']=sorted({ref for r in latest for item in r.get('assumptions',[]) if item['reason']==assumption['reason'] for ref in item['sources']})
                if selected.get('payment_schedule'):
                    for event in selected['payment_schedule']['payments']:
                        event['sources']=sorted({ref for r in latest for p in r['payment_schedule']['payments'] if p['id']==event['id'] for ref in p['sources']})
                for event in selected.get('payments',[]):
                    event['sources']=sorted({ref for r in latest for p in r.get('payments',[]) if p['id']==event['id'] for ref in p['sources']})
            if selected['status']=='unknown':
                problems.append({'code':'unknown_status','record_ids':[selected['id']]})
            values={k:Decimal(str(v)) for k,v in selected['amounts'].items() if v is not None}
            if ('total' in values and any(values[k]>values['total'] for k in ('principal','interest','fees','overdue') if k in values)
                    or 'total' in values and 'principal' in values and 'interest' in values and values['principal']+values['interest']>values['total']
                    or 'total' in values and sum((values.get(k,0) for k in ('principal','interest','fees')),Decimal(0))>values['total']
                    or selected['status']=='closed' and any(values.get(k,0)>0 for k in ('principal','interest','fees','total','overdue'))):
                problems.append({'code':'conflicting_amounts','record_ids':[selected['id']]})
        else:
            problems.append({'code':'no_dated_record','record_ids':sorted(r['id'] for r in entries)})
        if selected and selected.get('confirmation',{}).get('status','confirmed')!='confirmed':
            problems.append({'code':'unconfirmed_record','record_ids':[selected['id']]})
        history,history_issues=settlements(entries);problems.extend(history_issues)
        # A contradictory current demand can affect load regardless of the arbitrary selected record ID.
        relevant=any(eligible_subject(r,data) for r in latest) if selected else any(eligible_subject(r,data) for r in entries)
        if relevant:issues.extend(dict(problem,contract_id=uid) for problem in problems)
        maturity=selected.get('maturity') if selected else None
        contracts.append({'id':uid,'accepted':selected,'record_ids':sorted(r['id'] for r in entries),
                          'ignored_record_ids':sorted(r['id'] for r in ignored),
                          'issues':problems,'settlements':history,'confirmed_maturity':maturity['date'] if maturity and maturity['confirmed'] and maturity['date']!='9999-12-31' else None})
    for contract in contracts:
        row=contract['accepted']
        contract['obligation_type']=row.get('obligation_type','other') if row else 'other'
        contract['debt_scope']=row.get('debt_scope','unknown') if row else 'unknown'
        contract['confirmation']=copy.deepcopy(row.get('confirmation',{'status':'confirmed','sources':row['sources'], 'reason':'Ранее проверенный реестр; отдельный статус не задан'})) if row else None
        contract['assumptions']=copy.deepcopy(row.get('assumptions',[])) if row else []
        contract['inclusion_basis']=('confirmed_guarantee_demand' if eligible_subject(row,data) else 'guarantee_without_confirmed_demand') if row and row['role']=='guarantor' else 'direct_borrower_obligation'
    active=[c for c in contracts if c['accepted'] and eligible_subject(c['accepted'],data) and c['accepted']['status']!='closed']
    unresolved=[]
    for left,right in combinations(active,2):
        ids=(left['id'],right['id'])
        if left['accepted']['creditor_id']==right['accepted']['creditor_id'] and ids not in separate:
            unresolved.append({'contracts':list(ids),'reason':'Совпадает кредитор; требуется решение аналитика.'})
    blocked={uid for candidate in unresolved for uid in candidate['contracts']} | {i['contract_id'] for i in issues}
    for contract in contracts:
        contract['eligible_for_calendar']=bool(contract['accepted'] and contract['accepted']['status']=='active' and eligible_subject(contract['accepted'],data) and contract['id'] not in blocked)
    review = copy.deepcopy(data.get('active_obligations_review'))
    if review is not None:
        if review['as_of'] != (assessment_date or data['report_date']):
            review['status'] = 'stale'
        elif not review['scope_complete']:
            review['status'] = 'incomplete'
        elif review['no_active_obligations'] is not True:
            review['status'] = 'absence_unconfirmed'
        else:
            conflicts = blocked | {contract['id'] for contract in active}
            conflicts.update(c['id'] for c in contracts if closed_payment_claims(c['accepted'], data))
            review['status'] = 'conflicting' if conflicts else 'confirmed_absence'
            if conflicts:
                review['conflicting_contract_ids'] = sorted(conflicts)
    absence_confirmed = review is not None and review['status'] == 'confirmed_absence'
    scope_limited = review is None or review['status'] in {'stale', 'incomplete', 'conflicting'}
    dates=[c['accepted']['as_of'] for c in active if c['accepted']['as_of']]
    totals={}
    for field in AMOUNTS:
        known=[c for c in active if c['id'] not in blocked and c['accepted']['amounts'].get(field) is not None]
        total=sum((Decimal(str(c['accepted']['amounts'][field])) for c in known),Decimal(0))
        known_zero = absence_confirmed and field != 'limit'
        totals[field]={'value':money(total) if known_zero or (active and not blocked and not scope_limited and len(known)==len(active)) else None,
                       'known_subtotal':money(total) if known or known_zero else None,
                       **({'sources': review['sources']} if known_zero else {}),
                       'contract_ids':[c['id'] for c in known],
                       'record_ids':[c['accepted']['id'] for c in known],
                       'entries':[{'contract_id':c['id'],'record_id':c['accepted']['id'],
                                   'as_of':c['accepted']['as_of'],'sources':c['accepted']['sources'],
                                   'value':money(c['accepted']['amounts'][field])} for c in known]}
    record_period={'start':min(dates),'end':max(dates)} if dates else None
    guide,load_patch=payment_data(active,blocked)
    if absence_confirmed:
        guide['regular_monthly'].update(value='0.00', known_subtotal='0.00', sources=review['sources'])
    elif scope_limited:
        guide['regular_monthly']['value'] = None
    def pdf_fact(raw):
        return {'value':pdf_number(raw['value']),'status':'calculated' if pdf_number(raw['value']) is not None else 'missing',
                'sources':sorted({ref for c in active if c['id'] in raw['contract_ids'] for ref in c['accepted']['sources']}),
                'derivation':'Сумма последних принятых записей договоров: '+', '.join(raw['record_ids']),
                **({'period_start':record_period['start'],'period_end':record_period['end']} if record_period else {})}
    bki={}
    if data.get('kind')=='bki' and record_period:
        bki={'report_date':data['report_date'],'record_period':record_period,
             **{field:pdf_fact(totals[field]) for field in ('principal','interest','total','overdue')}}
        # The form checks this optional decomposition. Other costs remain in total.
        if all(totals[k]['value'] is not None for k in ('principal','interest','total')) and Decimal(totals['principal']['value'])+Decimal(totals['interest']['value'])!=Decimal(totals['total']['value']):
            bki.pop('interest')
    source_dates=[r['as_of'] for r in rows if r['as_of']]
    return {'schema_version':VERSION,'payment_guide':guide,
            'source_record_period':{'start':min(source_dates),'end':max(source_dates)} if source_dates else None,
            'pdf_patch':{'bki':bki,'credit_load':load_patch,'sources':copy.deepcopy(data['sources'])},
            'active_obligations_review': review,
            'basis': 'documented_absence_of_active_obligations' if absence_confirmed else 'sum_of_latest_records',
            'common_balance_date': review['as_of'] if absence_confirmed else None,
            'limits': [] if absence_confirmed else [
                'Свод относится к последним записям с разными датами, общий остаток на одну дату не установлен.',
                'Платёжные ориентиры не являются точным будущим графиком.',
            ],
            'ok':not unresolved and not issues,'issues':issues,'decisions':decisions,'unresolved_matches':unresolved,'totals':totals,'contracts':contracts,
            'record_period':record_period,'report_date':data['report_date'],'currency':data['currency'],
            'borrower_id':data['borrower_id'],'borrower_kind':data.get('borrower_kind'),
            'sources':copy.deepcopy(data['sources']),
            'guarantees':[r for r in rows if r['role']=='guarantor'],
            'owner_payments':copy.deepcopy(data.get('owner_payments',[])),
            'other_roles':[r for r in rows if not eligible_subject(r,data)]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args(argv)
    if args.input.resolve()==args.output.resolve() or (args.input.exists() and args.output.exists() and args.input.samefile(args.output)):
        parser.error('Результат не может заменять исходник')
    try:
        data=json.loads(args.input.read_text(encoding='utf-8-sig'))
        result=summarize(data)
    except (OSError,ValueError,KeyError,TypeError,InvalidOperation) as exc:
        result={'schema_version':VERSION,'ok':False,'issues':[{'code':'invalid_input','message':str(exc)}]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=args.output.parent,delete=False) as handle:
        json.dump(result,handle,ensure_ascii=False,indent=2,sort_keys=True);handle.write('\n')
        temporary=handle.name
    os.replace(temporary,args.output)
    return 0 if result['ok'] else 2


if __name__=='__main__':
    raise SystemExit(main())
