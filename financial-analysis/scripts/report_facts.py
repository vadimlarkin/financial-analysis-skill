"""Source-backed input facts for the branded financial form."""

from datetime import date
import math

from financial_layout import ReportError

STATUSES = {'confirmed', 'calculated', 'missing', 'conflicting', 'unverified', 'not_applicable'}


def text(value, where):
    if not isinstance(value, str) or not value.strip() or len(value) > 30000:
        raise ReportError(f"{where}: требуется текст")
    return value


def missing(reason='Сведения не представлены'):
    return {'status': 'missing', 'value': None, 'sources': [], 'reason': reason}


def obj(value, allowed, where):
    if not isinstance(value, dict):
        raise ReportError(f'{where}: требуется объект')
    unknown = set(value)-set(allowed)
    if unknown:
        raise ReportError(f'{where}: неизвестные поля {sorted(unknown)}')
    return value


def stamp(value, where):
    try:
        if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:
            raise ValueError()
    except ValueError:
        raise ReportError(f'{where}: требуется дата YYYY-MM-DD') from None
    return value


def sequence(value, where):
    if not isinstance(value,list) or len(value)>10000:
        raise ReportError(f'{where}: требуется массив до 10000 записей')
    return value


def fact(raw, sources, where):
    if raw is None:
        return missing()
    obj(raw, {'status','value','sources','reason','derivation','unit','as_of','conservative','scenario_only'}, where)
    status=raw.get('status')
    if status not in STATUSES:
        raise ReportError(f'{where}: неизвестный статус')
    value=raw.get('value')
    if isinstance(value, bool) or not (value is None or isinstance(value,(str,int,float))):
        raise ReportError(f'{where}: недопустимое значение')
    if isinstance(value,(int,float)) and not math.isfinite(value):
        raise ReportError(f'{where}: требуется конечное число')
    if isinstance(value,str):
        text(value, where+'.value')
    refs=sequence(raw.get('sources',[]),where+'.sources')
    if any(not isinstance(r,str) or r not in sources for r in refs) or len(set(refs))!=len(refs):
        raise ReportError(f'{where}: неизвестный или повторный источник')
    if status in {'confirmed','calculated'} and (value is None or not refs):
        raise ReportError(f'{where}: подтверждённое значение требует источники')
    if status=='calculated' and not raw.get('derivation'):
        raise ReportError(f'{where}: расчёт требует derivation')
    if status in {'missing','not_applicable'} and value is not None:
        raise ReportError(f'{where}: отсутствующее или неприменимое значение должно быть null')
    if status in {'conflicting','unverified','not_applicable'} and not raw.get('reason'):
        raise ReportError(f'{where}: требуется причина или ограничение')
    for key in ('reason','derivation','unit'):
        if key in raw:text(raw[key],where+'.'+key)
    if 'as_of' in raw:stamp(raw['as_of'],where+'.as_of')
    if 'conservative' in raw and type(raw['conservative']) is not bool:raise ReportError(where+': conservative требует boolean')
    if 'scenario_only' in raw and (type(raw['scenario_only']) is not bool or
                                   raw['scenario_only'] and status != 'calculated'):
        raise ReportError(where+': scenario_only требует расчётного значения')
    return {'status':status,'value':value,'sources':refs,**{k:v for k,v in raw.items() if k not in {'status','value','sources'}}}


def normalize_score(score, sources, person_id):
    """Publish only a bureau observation linked to this participant and its date."""
    if score['status'] in {'missing', 'not_applicable', 'unverified', 'conflicting'}:
        return {**score, 'value': None}
    if score['status'] != 'confirmed' or score.get('derivation'):
        return {'status': 'unverified', 'value': None, 'sources': score['sources'],
                'reason': 'Представлен расчёт. Исходный рейтинг БКИ не подтверждён.'}
    matches = {}
    for ref in score['sources']:
        source = sources.get(ref, {})
        credit = source.get('credit_report', {})
        date_of_report = source.get('document_date')
        if credit.get('person_id') == person_id and date_of_report and score.get('as_of', date_of_report) == date_of_report:
            matches.setdefault((credit['bureau'], date_of_report), []).append(ref)
    if len(matches) != 1:
        return {'status': 'unverified', 'value': None, 'sources': score['sources'],
                'reason': 'Нет однозначной ссылки на кредитный отчёт этого участника с датой рейтинга.'}
    (_, date_of_report), refs = next(iter(matches.items()))
    return {**score, 'as_of': date_of_report, 'sources': refs}


def fields(raw, keys, sources, where):
    obj(raw,keys,where)
    return {key:fact(raw.get(key),sources,where+'.'+key) for key in keys}
