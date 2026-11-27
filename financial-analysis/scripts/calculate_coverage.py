"""Six-month scenario coverage and cumulative cash deficits from retained stages.

The proposed loan is only a denominator. Historical amounts and dated obligation
payments remain the source of arithmetic; reviewed descriptors state restrictions
and timing, without inventing future receipts.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

VERSION = 'six-month-coverage-1.0'
REVIEW_CONTEXT_VERSION = 2
ZERO = Decimal(0)
CENT = Decimal('0.01')


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def legacy_review_digest(config, history, calendar):
    """Check the original digest before migrating a retained review."""
    return _digest({
        'config': config,
        'history': {
            'months': history['months'], 'source_versions': history['source_versions'],
            'classified_operations': history['classified_operations'],
        },
        'calendar': calendar,
    })


def review_fingerprint(config, history, calendar, intake, cashflow, register):
    """Project the approved inputs, keeping general source catalogs out of the digest."""
    months = []
    for month in history['months']:
        flow = month['totals']['business_flow_before_creditors']
        months.append({
            'month': month['month'], 'period': month['period'], 'complete': month['complete'],
            'flow': {k: v for k, v in flow.items() if k != 'sources'},
            'limitations': [{k: v for k, v in item.items() if k != 'document_coverage'}
                            for item in month['limitations']],
        })
    accounts = []
    for row in sorted(intake['bank_accounts'], key=lambda value: value['account']):
        accounts.append({
            'account': row['account'], 'opened_on': row.get('opened_on'), 'closed_on': row.get('closed_on'),
            'periods': sorted(row['periods'], key=lambda item: (item['start'], item['end'], sorted(item['sources']))),
        })
    operations = []
    for row in sorted(cashflow.get('operations', []), key=lambda item: item['id']):
        operation = dict(row)
        confirmation = operation.get('transfer_confirmation')
        if isinstance(confirmation, str) and operation.get('pair_id'):
            operation['transfer_confirmation'] = json.loads(confirmation)
        operations.append(operation)
    context = {
        'config': {k: v for k, v in config.items() if k != 'review_id'},
        'history': {
            'assessment_date': history['assessment_date'], 'borrower_id': history['borrower_id'],
            'borrower_kind': history.get('borrower_kind'), 'period': history['available_period'],
            'reviewed_by': history['reviewed_by'], 'months': months, 'classified_operations': history['classified_operations'],
            'complete_windows': {key: value['complete'] for key, value in history['windows'].items()},
            'settlement_links': history['settlement_links'], 'duplicate_lineage': history['duplicate_lineage'],
        },
        'intake': {'credit': intake.get('credit', {}), 'bank_target': intake.get('bank_target'), 'bank_accounts': accounts},
        'cashflow': {
            'period': cashflow.get('period'), 'coverage': cashflow.get('coverage'), 'operations': operations,
            'bank_controls': sorted(cashflow.get('bank_controls') or [], key=lambda c: (c['account'], c['source'])),
            'document_coverage': {k: v for k, v in cashflow.get('document_coverage', {}).items() if k != 'accounts'},
        },
        'register': {key: register.get(key, []) for key in ('contracts', 'owner_payments', 'decisions')},
        'calendar': {k: v for k, v in calendar.items()
                     if k not in {'sources', 'limitations'} and not (k == 'active_obligations_review' and v is None)},
    }

    refs = set()

    def normalize(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key == 'sources' and isinstance(item, list) and all(isinstance(s, str) for s in item):
                    refs.update(item)
                    result[key] = sorted(item)
                else:
                    if key == 'source' and isinstance(item, str):
                        refs.add(item)
                    result[key] = normalize(item)
            return result
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    projected = normalize(context)
    locators = {item['id']: item['locator'] for item in history['sources']}
    versions = {sid: history['source_versions'].get(sid) for sid in sorted(refs)}
    projected['evidence'] = {sid: {'sha256': version, 'locator': locators.get(sid)} for sid, version in versions.items()}
    return {'review_context_version': REVIEW_CONTEXT_VERSION, 'review_context_sha256': _digest(projected),
            'review_source_versions': versions}


def calculate(history, calendar, config, intake, *, cashflow=None, register=None):
    def obj(raw, allowed, label):
        if not isinstance(raw, dict) or set(raw)-set(allowed):
            raise ValueError(label+': неверные поля объекта')
        return raw
    def seq(raw, label):
        if not isinstance(raw, list):raise ValueError(label+': требуется массив')
        return raw
    def text(raw, label):
        if not isinstance(raw, str) or not raw.strip():raise ValueError(label+': требуется основание')
        return raw
    def flag(raw, label):
        if type(raw) is not bool:raise ValueError(label+': требуется логический признак')
        return raw
    def amount(raw, label, *, unknown=True):
        if raw is None and unknown:return None
        if isinstance(raw, bool) or not isinstance(raw, (str,int,float)):
            raise ValueError(label+': требуется сумма или null')
        try:v=Decimal(str(raw))
        except Exception:raise ValueError(label+': неверная сумма') from None
        if not v.is_finite() or v<ZERO or v!=v.quantize(CENT):raise ValueError(label+': требуется неотрицательная сумма до копейки')
        return v
    def money(v):return None if v is None else format(v.quantize(CENT,rounding=ROUND_HALF_UP),'.2f')
    def number(v):return None if v is None else format(v.quantize(Decimal('0.000001'),rounding=ROUND_HALF_UP),'f')
    period=deepcopy(calendar['horizon']);start=date.fromisoformat(period['start']);end=date.fromisoformat(period['end_exclusive'])
    if history['assessment_date']!=calendar['assessment_date'] or history['borrower_id']!=calendar['borrower_id']:
        raise ValueError('История и календарь относятся к разным датам или заёмщикам')
    sources=deepcopy(history['sources']);refs={s['id'] for s in sources}
    refs.update(s['id'] for s in calendar['sources'])
    def links(raw,label,*,empty=False):
        if not isinstance(raw,list) or (not raw and not empty) or len(set(raw))!=len(raw) or any(not isinstance(x,str) or x not in refs for x in raw):
            raise ValueError(label+': нужны ссылки на сохранённые источники')
        return sorted(raw)
    def stamp(raw,label):
        if not isinstance(raw,str):raise ValueError(label+': нужна дата ISO')
        try:d=date.fromisoformat(raw)
        except ValueError:raise ValueError(label+': нужна дата ISO') from None
        if d.isoformat()!=raw:raise ValueError(label+': нужна дата ISO')
        return d
    def reviewed(raw,allowed,label):
        obj(raw,allowed,label);text(raw.get('reason'),label+'.reason');links(raw.get('sources'),label+'.sources')
        return raw
    obj(config,{'review_id','reviewed_by','opening','trend_review','timing','business_costs','proposed_loan','excluded_inflows','borrower_budget'},'coverage')
    text(config.get('review_id'),'coverage.review_id');text(config.get('reviewed_by'),'coverage.reviewed_by')
    limits=[]
    def limited(code,reason,**extra):limits.append({'code':code,'reason':reason,**extra})
    timing=reviewed(config.get('timing'),{'basis','reason','sources'},'timing')
    if timing.get('basis') not in {'interval_start','interval_end'}:raise ValueError('timing.basis: interval_start или interval_end')
    trend=reviewed(config.get('trend_review'),{'reason','sources','one_offs'},'trend_review')
    terms_by_operation = defaultdict(list)
    for month in history['months']:
        for term in month['totals']['business_flow_before_creditors']['terms']:
            terms_by_operation[term['operation_id']].append(term)
    oneoffs, exclusions = {}, {}
    for raw in seq(trend.get('one_offs', []), 'trend_review.one_offs'):
        reviewed(raw, {'operation_id', 'amount', 'reason', 'sources'}, 'one_off')
        uid = text(raw.get('operation_id'), 'one_off.operation_id')
        terms = terms_by_operation.get(uid, [])
        if len(terms) != 1 or uid in oneoffs:
            raise ValueError('one_off: нужна уникальная операция бизнес-потока за 12 месяцев')
        oneoffs[uid] = deepcopy(raw)
        if 'amount' in raw and raw['amount'] is None:
            continue
        term = terms[0]
        original_amount = Decimal(term['amount'])
        excluded_amount = amount(raw['amount'], 'one_off.amount', unknown=False) if 'amount' in raw else original_amount
        if not ZERO < excluded_amount <= original_amount:
            raise ValueError('one_off.amount: требуется положительная сумма в пределах исходной операции')
        exclusions[uid] = {
            'operation_id': uid, 'side': term['side'], 'sign': term['sign'],
            'original_amount': money(original_amount), 'excluded_amount': money(excluded_amount),
            'remaining_amount': money(original_amount - excluded_amount), 'sources': deepcopy(raw['sources']),
        }
    adjusted=[]
    for month in history['months']:
        original=month['totals']['business_flow_before_creditors']
        removed = [exclusions[t['operation_id']] for t in original['terms'] if t['operation_id'] in exclusions]
        adjustment = sum((Decimal(part['excluded_amount']) * part['sign'] for part in removed), ZERO)
        known=Decimal(original['known_subtotal'])-adjustment
        adjusted.append({'month':month['month'],'period':deepcopy(month['period']),
            'original':deepcopy(original),'one_off_operation_ids':[part['operation_id'] for part in removed],
            'one_off_adjustments': removed,
            'value':money(Decimal(original['value'])-adjustment) if original['value'] is not None else None,
            'known_subtotal':money(known),'sources':sorted(set(original['sources'])|set(trend['sources'])|
                {source for part in removed for source in part['sources']}),
            'calculated':True,'conservative':False})
    recent=adjusted[-6:]
    if len(adjusted)!=12 or len(recent)!=6:raise ValueError('История должна сохранять 12 месячных окон')
    trend_known=history['windows']['6m']['complete'] and all(m['value'] is not None for m in recent)
    annual_known=history['windows']['12m']['complete']
    if not trend_known:limited('six_month_history_incomplete','Неполные последние шесть месяцев не дают числового прогноза.')
    if not annual_known:limited('seasonality_scope_incomplete','Проверка сезонности по 12 месяцам ограничена фактическим охватом; доступен только сценарий по шести месяцам.')
    recent_total=sum((Decimal(m['value']) for m in recent),ZERO) if trend_known else None
    avg=recent_total/Decimal(6) if recent_total is not None else None
    older=adjusted[:6]
    older_mean=sum((Decimal(m['value']) for m in older),ZERO)/Decimal(6) if all(m['value'] is not None for m in older) else None
    all_mean=sum((Decimal(m['value']) for m in adjusted),ZERO)/Decimal(12) if all(m['value'] is not None for m in adjusted) else None
    # Future amounts are computed from reviewed historical terms. No multiplier,
    # promised sale or borrowing may replace them in this contract.
    timing_conservative=bool(avg is not None and ((avg>ZERO and timing['basis']=='interval_end') or (avg<ZERO and timing['basis']=='interval_start')))
    forecast=[];distributed=ZERO
    for i,month in enumerate(calendar['months']):
        at=date.fromisoformat(month['start']) if timing['basis']=='interval_start' else date.fromisoformat(month['end_exclusive'])-timedelta(days=1)
        # Differences of rounded cumulative amounts preserve the total and
        # monotonicity: rounding cannot invent a flow of the opposite sign.
        cumulative=None if recent_total is None else (recent_total*Decimal(i+1)/Decimal(6)).quantize(CENT,rounding=ROUND_HALF_UP)
        value=None if cumulative is None else cumulative-distributed
        if value is not None:
            if value==ZERO:value=ZERO  # A rounded zero has no negative sign.
            distributed=cumulative
        forecast.append({'id':'trend-'+str(i+1),'month_index':i+1,'date':at.isoformat(),
            'amount':money(value),'sources':sorted(set(timing['sources'])|set(trend['sources'])|{s for m in recent for s in m['sources']}),
            'date_basis':'scenario_assumption','calculated':True,'conservative':timing_conservative,
            'basis':'Продолжение среднего наблюдаемого бизнес-потока последних шести полных месяцев; дата задана сценарием.'})
    costs={};cost_calendar_claims=set();calendar_events={e['id']:e for e in calendar['events']}
    for raw in seq(config.get('business_costs',[]),'business_costs'):
        reviewed(raw,{'id','date','amount','included_in_trend','kind','calendar_event_id','reason','sources'},'business_cost')
        uid=text(raw.get('id'),'business_cost.id')
        if uid in costs:raise ValueError('Повтор business_cost.id')
        at=stamp(raw['date'],'business_cost.date') if raw.get('date') is not None else None
        if at is not None and at<start and raw.get('kind')!='legacy_obligation':raise ValueError('business_cost: требуется оставшийся расход с даты отчёта')
        included=flag(raw.get('included_in_trend'),'business_cost.included_in_trend')
        value=amount(raw.get('amount'),'business_cost.amount')
        kind=raw.get('kind')
        if kind not in {'business','legacy_obligation','unresolved'}:raise ValueError('business_cost.kind: business, legacy_obligation или unresolved')
        if kind=='legacy_obligation':
            eid=raw.get('calendar_event_id');event=calendar_events.get(eid)
            if event is None or eid in cost_calendar_claims:raise ValueError('Legacy cost требует уникального calendar_event_id')
            if included or value is None or money(value)!=event['amount'] or (at is not None and at.isoformat() not in {event['date'],event.get('documented_due_date')}):
                raise ValueError('Legacy cost расходится с датой/суммой календаря либо уже включён в trend')
            if at is None:at=date.fromisoformat(event['date'])
            cost_calendar_claims.add(eid)
        elif 'calendar_event_id' in raw:raise ValueError('Ссылка calendar_event_id требует подтверждённой классификации legacy_obligation')
        costs[uid]={**deepcopy(raw),'date':at.isoformat() if at else None,'amount':money(value),'included_in_trend':included}
    opening=config.get('opening')
    # Opening balances are primary account facts, not an unexplained aggregate.
    obj(opening,{'as_of','accounts','restrictions','restrictions_complete','advances_review','reason','sources'},'opening')
    text(opening.get('reason'),'opening.reason');links(opening.get('sources'),'opening.sources')
    if stamp(opening.get('as_of'),'opening.as_of')!=start:raise ValueError('Деньги на начало должны быть установлены на дату отчёта')
    account_values={}
    for raw in seq(opening.get('accounts'),'opening.accounts'):
        obj(raw,{'account','amount','sources'},'opening.account');uid=text(raw.get('account'),'opening.account.account')
        if uid in account_values:raise ValueError('Повтор счёта opening')
        links(raw.get('sources'),'opening.account.sources');account_values[uid]=amount(raw.get('amount'),'opening.account.amount')
    expected={a['account'] for a in intake['bank_accounts']}
    opening_complete=bool(expected) and intake.get('bank_target',{}).get('all_accounts_confirmed',False) and set(account_values)==expected and all(v is not None for v in account_values.values())
    if not opening_complete:limited('opening_accounts_incomplete','Не установлены актуальные остатки всех известных счетов.',expected_accounts=sorted(expected),presented_accounts=sorted(account_values))
    if not flag(opening.get('restrictions_complete'),'opening.restrictions_complete'):
        opening_complete=False;limited('restrictions_incomplete','Не проверена полнота ограничений денег.')
    advance=reviewed(opening.get('advances_review'),{'complete','reason','sources'},'opening.advances_review')
    if not flag(advance.get('complete'),'advances_review.complete'):
        opening_complete=False;limited('advances_unreviewed','Назначение полученных авансов не установлено; они не считаются свободными автоматически.')
    calendar_events={e['id']:e for e in calendar['events']}
    restrictions=[];restricted_by_account=defaultdict(lambda:ZERO);cost_reserved=defaultdict(lambda:ZERO);event_reserved=defaultdict(lambda:ZERO)
    for raw in seq(opening.get('restrictions',[]),'opening.restrictions'):
        reviewed(raw,{'id','account','amount','purpose','cost_id','event_id','reason','sources'},'restriction')
        uid=text(raw.get('id'),'restriction.id');account=raw.get('account');purpose=raw.get('purpose')
        if any(r['id']==uid for r in restrictions) or account not in account_values:raise ValueError('Неверный id или счёт ограничения')
        if purpose not in {'unavailable','business_cost','legacy_payment'}:raise ValueError('Неверное назначение ограничения')
        value=amount(raw.get('amount'),'restriction.amount')
        if value is None:
            opening_complete=False;limited('restriction_amount_unknown','Не определена сумма ограничения денег.',restriction_id=uid,sources=raw['sources'])
        else:restricted_by_account[account]+=value
        if purpose=='business_cost':
            cid=raw.get('cost_id')
            if cid not in costs or 'event_id' in raw:raise ValueError('Резерв бизнеса требует единственный известный cost_id')
            if costs[cid]['kind']!='business':raise ValueError('Резерв бизнеса не относится к legacy/unresolved; свяжите резерв непосредственно с событием календаря')
            if costs[cid]['included_in_trend']:raise ValueError('Резерв нельзя повторно вычесть для расхода, уже включённого в trend; сверить базу и дополнительный расход')
            if costs[cid]['amount'] is None:raise ValueError('Резерв требует известной суммы расхода')
            if value is not None:cost_reserved[cid]+=value
        elif purpose=='legacy_payment':
            eid=raw.get('event_id')
            if eid not in calendar_events or 'cost_id' in raw:raise ValueError('Резерв платежа требует единственный event_id текущего календаря')
            if value is not None:event_reserved[eid]+=value
        elif 'event_id' in raw or 'cost_id' in raw:raise ValueError('Недоступные деньги не назначаются одновременно на расход/платёж')
        restrictions.append({**deepcopy(raw),'amount':money(value)})
    for account,total in restricted_by_account.items():
        if account_values[account] is not None and total>account_values[account]:raise ValueError('Ограничения превышают деньги счёта '+account)
    for cid,total in cost_reserved.items():
        if total>Decimal(costs[cid]['amount']):raise ValueError('Повторное назначение резерва сверх расхода '+cid)
    for eid,total in event_reserved.items():
        if total>Decimal(calendar_events[eid]['amount']):raise ValueError('Резерв превышает установленный платёж '+eid)
    balances=sum((v for v in account_values.values() if v is not None),ZERO)
    held=sum(restricted_by_account.values(),ZERO)
    earmarked=sum(event_reserved.values(),ZERO)
    unrestricted=balances-held
    available=unrestricted+earmarked
    resource_events=[];cost_events=[]
    for eid,value in sorted(event_reserved.items()):
        e=calendar_events[eid]
        resource_events.append({'id':'reserve-'+eid,'date':e['date'],'amount':money(value),'event_id':eid,
            'sources':sorted({s for r in restrictions if r.get('event_id')==eid for s in r['sources']}),
            'calculated':True,'conservative':e['conservative'],'date_basis':e['date_basis']})
    costs_known=True
    for uid,cost in sorted(costs.items()):
        if cost['date'] is not None and cost['date']>=end.isoformat():continue
        if cost['kind']=='unresolved':
            costs_known=False;limited('cost_classification_unresolved','Не установлено, является ли расход обычным или уже включённым в календарь обязательством.',cost_id=uid,sources=cost['sources']);continue
        if cost['kind']=='legacy_obligation' or cost['included_in_trend']:continue
        if cost['date'] is None:
            costs_known=False;limited('necessary_cost_date_unknown','Не определён срок дополнительного обязательного расхода бизнеса.',cost_id=uid,sources=cost['sources']);continue
        if cost['amount'] is None:
            costs_known=False;limited('necessary_cost_unknown','Не определён дополнительный обязательный расход бизнеса.',cost_id=uid,sources=cost['sources']);continue
        value=Decimal(cost['amount'])-cost_reserved[uid]
        cost_events.append({'id':uid,'date':cost['date'],'amount':money(value),'gross_amount':cost['amount'],
            'funded_by_opening_reserve':money(cost_reserved[uid]),'sources':cost['sources'],
            'calculated':True,'conservative':False,'date_basis':'reviewed_business_commitment'})
    scenario_complete=bool(opening_complete and trend_known and costs_known and calendar['scenario_complete'])
    complete=bool(scenario_complete and annual_known and calendar['complete'])
    if not calendar['scenario_complete']:limited('calendar_scenario_incomplete','Неоценённая часть календаря не даёт полного сценарного покрытия.',unestimated=deepcopy(calendar['unestimated']))
    elif not calendar['complete']:limited('calendar_full_total_unknown','Продолжение регулярных платежей допускает сценарий; неизвестный финальный платёж не устанавливает верхнюю границу.',unestimated=deepcopy(calendar['unestimated']))
    conservative=bool(calendar['totals']['conservative'] or timing_conservative)
    refs_all=sorted(refs)
    def fact(value,*,reason=None,known=None,cons=conservative,unit=None):
        return {'value':money(value),'known_subtotal':money(known if known is not None else value),'period':deepcopy(period),
                'sources':refs_all,'calculated':True,'conservative':cons,'unit':unit or history.get('currency', 'RUB'),**({'reason':reason} if reason else {})}
    projected=sum((Decimal(e['amount']) for e in forecast if e['amount'] is not None),ZERO)
    additional=sum((Decimal(e['amount']) for e in cost_events),ZERO)
    resources=available+projected-additional if opening_complete and trend_known and costs_known else None
    payments_value=calendar['totals']['value'];payments_scenario=calendar['totals']['scenario_value']
    payments={'value':payments_value,'scenario_value':payments_scenario,'known_subtotal':calendar['totals']['known_subtotal'],
              'period':deepcopy(period),'sources':calendar['totals'].get('sources', refs_all),
              'calculated':True,'conservative':calendar['totals']['conservative']}
    def dated_running(flow, scope_complete, conservative):
        # Events of one date are netted together without assuming intraday ordering.
        balances = []
        by_date = defaultdict(lambda: {'resources': ZERO, 'business_costs': ZERO, 'payments': ZERO, 'ids': []})
        for key, events in [('resources', flow + resource_events), ('business_costs', cost_events), ('payments', calendar['events'])]:
            for event in events:
                if event['amount'] is not None:
                    by_date[event['date']][key] += Decimal(event['amount'])
                    by_date[event['date']]['ids'].append(event['id'])
        running = unrestricted
        maximum = max(ZERO, -running)
        maximum_at = start.isoformat() if maximum else None
        for day, values in sorted(by_date.items()):
            running += values['resources'] - values['business_costs'] - values['payments']
            balances.append({
                'date': day, 'resources': money(values['resources']), 'business_costs': money(values['business_costs']),
                'payments': money(values['payments']), 'closing_balance': money(running) if scope_complete else None,
                'known_balance': money(running), 'event_ids': sorted(values['ids']),
                'calculated': True, 'conservative': conservative,
            })
            if -running > maximum:
                maximum, maximum_at = -running, day
        return balances, maximum, maximum_at

    dated, maximum, maximum_at = dated_running(forecast, scenario_complete, conservative)
    monthly = []
    running_month=unrestricted;monthly_max=max(ZERO,-running_month);monthly_at=start.isoformat() if monthly_max else None
    for m in calendar['months']:
        selected=[r for r in dated if m['start']<=r['date']<m['end_exclusive']]
        running_month+=sum((Decimal(r['resources'])-Decimal(r['business_costs'])-Decimal(r['payments']) for r in selected),ZERO)
        if -running_month>monthly_max:monthly_max=-running_month;monthly_at=m['start']
        monthly.append({'index':m['index'],'start':m['start'],'end_exclusive':m['end_exclusive'],
            'resources':money(sum((Decimal(r['resources']) for r in selected),ZERO)),
            'business_costs':money(sum((Decimal(r['business_costs']) for r in selected),ZERO)),
            'payments':m['value'],'scenario_payments':m['scenario_value'],'known_payments':m['known_subtotal'],
            'closing_balance':money(running_month) if scenario_complete else None,'known_balance':money(running_month),
            'calculated':True,'conservative':conservative})
    def deficit(value, at, *, full=complete, scenario=scenario_complete, cons=conservative):
        month=next((m for m in calendar['months'] if at and m['start']<=at<m['end_exclusive']),None)
        return {**fact(value if full else None, known=value, cons=cons),
                'scenario_value':money(value) if scenario else None,'date':at if scenario else None,
                'month_index':month['index'] if month and scenario else None,
                'month_start':month['start'] if month and scenario else None,
                'reason':None if full else 'incomplete_full_scope'}
    def ratio(top,bottom,*,percent=False,full=True):
        why='zero_denominator' if bottom is not None and Decimal(bottom)==ZERO else 'incomplete_scope' if top is None or bottom is None else None
        val=None if why else Decimal(top)/Decimal(bottom)*(100 if percent else 1)
        return {'value':number(val) if full else None,'scenario_value':number(val),'reason':why if why else None if full else 'incomplete_full_scope',
            'numerator':money(top),'denominator':money(Decimal(bottom)) if bottom is not None else None,
            'period':deepcopy(period),'sources':refs_all,'unit':'%' if percent else 'ratio',
            'calculated':True,'conservative':conservative}
    proposed=obj(config.get('proposed_loan'),{'amount','sources'},'proposed_loan')
    loan=amount(proposed.get('amount'),'proposed_loan.amount');links(proposed.get('sources',[]),'proposed_loan.sources',empty=loan is None)
    ignored=[]
    for raw in seq(config.get('excluded_inflows',[]),'excluded_inflows'):
        reviewed(raw,{'id','date','amount','kind','reason','sources'},'excluded_inflow')
        if raw.get('kind') not in {'proposed_loan','new_borrowing','unconfirmed_sale','unconfirmed_owner_contribution'}:raise ValueError('Поступление вне поддерживаемого перечня исключений')
        text(raw.get('id'),'excluded_inflow.id');stamp(raw.get('date'),'excluded_inflow.date');amount(raw.get('amount'),'excluded_inflow.amount')
        ignored.append(deepcopy(raw))
    dated_deficit=deficit(maximum,maximum_at);monthly_deficit=deficit(monthly_max,monthly_at)
    result={'schema_version':VERSION,'assessment_date':start.isoformat(),'borrower_id':history['borrower_id'],
        'review_id':config['review_id'],'reviewed_by':config['reviewed_by'],'horizon':period,
        'opening':{'as_of':opening['as_of'],'accounts':deepcopy(opening['accounts']),'restrictions':restrictions,
            'balances':fact(balances if opening_complete else None,known=balances,cons=False),
            'unrestricted':fact(unrestricted if opening_complete else None,known=unrestricted,cons=False),
            'earmarked_for_calendar':fact(earmarked if opening_complete else None,known=earmarked,cons=False),
            'available_for_legacy':fact(available if opening_complete else None,known=available,cons=False),
            'complete':opening_complete,'advances_review':deepcopy(advance)},
        'trend':{'months':adjusted,'one_offs':list(oneoffs.values()),'review':deepcopy(trend),
            'last_six_month_total':fact(recent_total,cons=False),'monthly_mean':number(avg),'older_six_month_mean':number(older_mean),
            'twelve_month_mean':number(all_mean),'seasonality_scope_complete':annual_known,
            'timing':deepcopy(timing),'calculated':True,'conservative':timing_conservative},
        'forecast':forecast,'reserved_resource_events':resource_events,'business_costs':list(costs.values()),'business_cost_events':cost_events,
        'resources':fact(resources,known=available+projected-additional),'payments':payments,
        'coverage_ratio':ratio(resources,payments_scenario,full=complete),
        'max_monthly_deficit':monthly_deficit,'max_dated_deficit':dated_deficit,
        'relative_deficit':ratio(maximum if scenario_complete else None,loan,percent=True,full=complete),
        'proposed_loan':{'amount':money(loan),'sources':deepcopy(proposed.get('sources',[]))},
        'excluded_inflows':ignored,'months':monthly,'dated_balances':dated,
        'complete':complete,'scenario_complete':scenario_complete,'limitations':limits,
        'sources':sources,'source_versions':deepcopy(history['source_versions']),
        'interpretation':'Дефицит показывает расчётную потребность в финансировании. Он не доказывает рефинансирование или намерение использовать рассматриваемый заём.',
        'assumptions':['Будущий поток продолжает наблюдаемую тенденцию и не гарантирует будущие поступления.',
            'Месячный и датированный дефицит разделены; относительный показатель использует датированный максимум.',
            'В пределах одной даты учитывается чистый итог; порядок операций внутри дня не установлен.',
            'Резерв на платёж календаря остаётся ресурсом этого платежа и доступен в его расчётную дату.',
            'Резерв дополнительного бизнес-расхода вычтен из opening, поэтому повторно оплачивается только непокрытая часть.']}
    if 'borrower_budget' in config:
        budget = reviewed(config['borrower_budget'], {'scope_complete', 'reason', 'sources', 'events'}, 'borrower_budget')
        budget_scope = flag(budget.get('scope_complete'), 'borrower_budget.scope_complete')
        budget_events, event_ids = [], set()
        for raw in seq(budget.get('events'), 'borrower_budget.events'):
            obj(raw, {'id', 'date', 'receipts', 'operating_expenses', 'sources'}, 'borrower_budget.event')
            uid = text(raw.get('id'), 'borrower_budget.event.id')
            at = stamp(raw.get('date'), 'borrower_budget.event.date')
            if uid in event_ids or not start <= at < end:
                raise ValueError('borrower_budget.event: нужен уникальный id и дата в горизонте покрытия')
            event_ids.add(uid)
            receipts = amount(raw.get('receipts'), 'borrower_budget.event.receipts')
            expenses = amount(raw.get('operating_expenses'), 'borrower_budget.event.operating_expenses')
            net = receipts - expenses if receipts is not None and expenses is not None else None
            budget_events.append({
                'id': 'borrower-budget-' + uid, 'input_id': uid, 'date': at.isoformat(),
                'receipts': money(receipts), 'operating_expenses': money(expenses), 'amount': money(net),
                'sources': links(raw.get('sources'), 'borrower_budget.event.sources'),
                'date_basis': 'borrower_budget', 'calculated': True,
            })
        budget_events.sort(key=lambda item: (item['date'], item['id']))
        budget_scope = budget_scope and all(event['amount'] is not None for event in budget_events)
        budget_total = sum((Decimal(event['amount']) for event in budget_events), ZERO) if budget_scope else None
        budget_period = {'start': budget_events[0]['date'], 'end': budget_events[-1]['date']} if budget_events else None
        budget_refs = sorted(set(budget['sources']) | {ref for event in budget_events for ref in event['sources']})
        budget_scenario = bool(budget_scope and opening_complete and costs_known and calendar['scenario_complete'])
        budget_complete = bool(budget_scenario and calendar['complete'])
        budget_conservative = calendar['totals']['conservative']
        balances, maximum, at = dated_running(budget_events, budget_scenario, budget_conservative)
        result['borrower_budget'] = {
            'basis': 'borrower_provided_dated_budget', 'review': deepcopy(budget), 'operating_events': budget_events,
            'operating_flow': {'value': money(budget_total), 'period': budget_period, 'sources': budget_refs,
                               'formula': 'Сумма поступлений за вычетом операционных расходов по датированному бюджету заёмщика'},
            'complete': budget_complete, 'scenario_complete': budget_scenario,
            'dated_balances': balances,
            'max_dated_deficit': deficit(maximum, at, full=budget_complete, scenario=budget_scenario, cons=budget_conservative),
        }
    if loan is None:result['relative_deficit']['reason']='unknown_proposed_loan'
    result.update(review_fingerprint(config, history, calendar, intake, cashflow or {}, register or {}))
    return result
