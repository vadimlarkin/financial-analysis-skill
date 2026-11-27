"""One-page IP financial report with cash flows, monthly receipts and a debt calendar."""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from financial_layout import A, BLUE, GRAY, H, INK, L, PALE, R, ReportError, number
from report_facts import fact, obj, sequence, stamp
from historical_cashflow import shifted_month

INCOMING = (
    ('operating', 'Операционные поступления'),
    ('loans', 'Полученные кредиты и займы'),
    ('own_in', 'Переводы с других своих счетов'),
    ('other_in', 'Прочие поступления'),
)
OUTGOING = (
    ('repayments', 'Выплаты по кредитам и займам'),
    ('payroll', 'Заработная плата'),
    ('suppliers', 'Поставщики'),
    ('tax', 'Налоги и сборы'),
    ('own_out', 'Переводы на свои счета'),
    ('other_out', 'Прочие списания'),
)
MONEY_KEYS = {key for key, _ in (*INCOMING, *OUTGOING)} | {
    'debt', 'overdue', 'bank_repayments', 'nonbank_repayments', 'platform_repayments', 'regular_payment',
}
TEXT_KEYS = {'project', 'security', 'flow_note', 'calendar_note', 'closing_note', 'platform_name'}
MONTHS = ('янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек')


def checked(raw, sources, key, *, money=False):
    entry = fact(raw, sources, 'ip.' + key)
    if entry['status'] not in {'calculated', 'confirmed'}:
        return {**entry, 'value': None}
    if money:
        try:
            value = Decimal(str(entry['value']))
        except InvalidOperation:
            raise ReportError(f'ip.{key}: требуется денежная сумма') from None
        if not value.is_finite() or value.adjusted() > 17 or value.quantize(Decimal('0.01')) != value:
            raise ReportError(f'ip.{key}: требуется конечная денежная сумма с точностью до копейки')
        return {**entry, 'value': value}
    if not isinstance(entry['value'], str):
        raise ReportError(f'ip.{key}: требуется текст')
    return entry


def normalize_ip(raw, sources, assessment):
    obj(raw, MONEY_KEYS | TEXT_KEYS | {'bank_scope', 'monthly_receipts'}, 'financial.ip')
    result = {key: checked(raw.get(key), sources, key, money=key in MONEY_KEYS)
              for key in sorted(MONEY_KEYS | TEXT_KEYS)}
    scope = raw.get('bank_scope')
    if scope is not None:
        obj(scope, {'start', 'end', 'operations', 'accounts', 'sources'}, 'ip.bank_scope')
        start, end = (stamp(scope.get(key), 'ip.bank_scope.' + key) for key in ('start', 'end'))
        if not start <= end <= assessment:
            raise ReportError('ip.bank_scope: неверные даты выписок')
        for key in ('operations', 'accounts'):
            if type(scope.get(key)) is not int or scope[key] < 0:
                raise ReportError(f'ip.bank_scope.{key}: требуется целое неотрицательное число')
        fact({'status': 'confirmed', 'value': 0, 'sources': scope.get('sources')}, sources, 'ip.bank_scope')
    result['bank_scope'] = scope
    monthly = {}
    for item in sequence(raw.get('monthly_receipts', []), 'ip.monthly_receipts'):
        obj(item, {'month', 'fact'}, 'ip.monthly_receipts')
        month = item.get('month')
        if not isinstance(month, str) or len(month) != 7:
            raise ReportError('ip.monthly_receipts: требуется месяц YYYY-MM')
        start = stamp(month + '-01', 'ip.monthly_receipts')
        last_day = monthrange(int(month[:4]), int(month[5:]))[1]
        if not scope or start > scope['end'] or month + f'-{last_day}' < scope['start'] or month in monthly:
            raise ReportError('ip.monthly_receipts: повтор месяца или месяц вне выписок')
        monthly[month] = checked(item.get('fact'), sources, 'monthly_receipts', money=True)
    result['monthly_receipts'] = monthly
    return result


def _day(iso):
    return date.fromisoformat(iso).strftime('%d.%m.%Y')


def _shown(entry, fallback):
    if entry['value'] is not None:
        return entry['value']
    reason = entry.get('reason')
    return reason if reason and reason != 'Сведения не представлены' else fallback


def _amount(value, unit):
    if value is None:
        return 'Нет данных'
    return _millions(Decimal(str(value))) + ' млн ' + unit


def _millions(value):
    scaled = value / 1_000_000
    if not scaled:
        return '0'
    if abs(scaled) < Decimal('0.1'):
        return number(scaled, 8).rstrip('0').rstrip(',')
    return number(scaled, 3)


def _compact(value):
    if value is None:
        return 'н/д'
    scaled = value / 1_000_000
    if not scaled:
        return '0'
    places = min(8, max(2, 1 - abs(scaled).adjusted()))
    return number(scaled, places).rstrip('0').rstrip(',')


def _line(page, label, x, top, width, size, *, bold=False, right=False, center=False, color=INK):
    font = 'BodyBold' if bold else 'Body'
    length = page.stringWidth(label, font, size)
    size = min(size, width / length * size) if length else size
    if size < 6:
        raise ReportError('Сократите подпись листа ИП: ' + label[:60])
    if center:
        x += (width - page.stringWidth(label, font, size)) / 2
    page.lab(label, x, top, size, bold, color, right)


def _text_box(page, label, top, height, size, x=L, width=A):
    if page.para(label, x, None, width, size, justify=False) > height:
        raise ReportError('Сократите текст листа ИП: ' + label[:60])
    page.para(label, x, top, width, size, justify=False)


def _chart(page, scope, monthly, unit):
    page.lab('Операционные поступления по месяцам (млн ' + unit + ')', L, 485, 11, True)
    if not scope or not monthly:
        page.lab('Помесячные поступления по выпискам не установлены', L, 518, 9, color=GRAY)
        return
    first = date.fromisoformat(scope['start']).replace(day=1)
    last = date.fromisoformat(scope['end']).replace(day=1)
    visible_start = max(first, shifted_month(last, -12))
    span = (last.year - visible_start.year) * 12 + last.month - visible_start.month + 1
    rows = []
    for offset in range(span):
        month = shifted_month(visible_start, offset)
        start = max(month, date.fromisoformat(scope['start']))
        end = min(date.fromisoformat(scope['end']), date(month.year, month.month, monthrange(month.year, month.month)[1]))
        partial = start != month or end.day != monthrange(month.year, month.month)[1]
        value = monthly.get(month.isoformat()[:7], {}).get('value')
        rows.append((month, start, end, partial, value))
    full = [value for _, _, _, partial, value in rows if not partial and value is not None]
    average = sum(full) / len(full) if full else None
    if average is None:
        label = 'Среднее не рассчитано: нет полного месяца с данными'
    else:
        mean = number(average / 1_000_000, 1) if abs(average) >= 100_000 else _compact(average)
        label = f'Среднее за полный месяц с данными: {mean} млн {unit}'
    if any(value is None for _, _, _, _, value in rows):
        label += '. н/д: нет данных за месяц'
    if visible_start > first:
        label += '. Последние 13 месяцев'
    page.lab(label, L + (18 if full else 0), 499, 7.3, color=GRAY)
    values = [value for _, _, _, _, value in rows if value is not None]
    low, high = min(values + [0]), max(values + [1])
    scale = Decimal(22) / (high - low)
    bottom = 538
    baseline = bottom + float(low * scale)
    page.rule(L, baseline, R)
    step = A / len(rows)
    for i, (_, _, _, partial, value) in enumerate(rows):
        height = float((value or 0) * scale)
        if height:
            page.rect(L + i * step + 6, min(baseline, baseline - height), step - 12, abs(height), PALE if partial else BLUE)
    if average is not None:
        page.c.saveState()
        page.c.setDash(3, 2)
        page.rule(L, baseline - float(average * scale), R, INK, .65)
        page.rule(L, 496, L + 13, INK, .65)
        page.c.restoreState()
    for i, (month, start, end, partial, value) in enumerate(rows):
        left = L + i * step
        top = min(baseline, baseline - float((value or 0) * scale)) - 4
        label = _compact(value)
        width = page.stringWidth(label, 'Body', 7.1)
        page.rect(left + (step - width) / 2 - 1, top - 7, width + 2, 9, '#FFFFFF')
        _line(page, label, left, top, step, 7.1, center=True)
        _line(page, month.strftime('%m.%y'), left, bottom + 14, step, 7.1, center=True)
        if partial:
            _line(page, f'{start.day}–{end.day}', left, bottom + 24, step, 6.8, center=True)


def _calendar(page, calendar, regular, note, unit):
    start = date.fromisoformat(calendar['horizon']['start'])
    stop = date.fromisoformat(calendar['horizon']['end_exclusive']) - timedelta(days=1)
    complete = calendar.get('confirmed_schedule_complete') and calendar.get('complete')
    amounts = {}
    for event in calendar.get('events', []):
        if event['date_basis'] == 'documented_payment_date':
            month = event['date'][:7]
            amounts[month] = amounts.get(month, Decimal(0)) + Decimal(event['amount'])
    first = start.replace(day=1)
    if start.day > 1 and start.isoformat()[:7] not in amounts and not complete:
        first = shifted_month(first, 1)
    months = (stop.year - first.year) * 12 + stop.month - first.month + 1
    total = sum(amounts.values()) if amounts or complete else None
    qualifier = 'График подтверждён.' if complete else 'Показаны известные платежи.'
    page.lab('Кредитная нагрузка по прежним обязательствам', L, 648, 12, True)
    page.lab(f'{_day(start.isoformat())}–{_day(stop.isoformat())}. {qualifier}', L, 661, 7.8, color=GRAY)
    stats = (
        ('Всего за период' if complete else 'Всего за период (известная часть)', _amount(total, unit)),
        ('Регулярные платежи', _shown(regular, 'Не выделены в графике' if complete else 'График неполный') if regular['value'] is None
         else number(regular['value']) + ' ' + unit + '/мес.'),
    )
    for i, (title, value) in enumerate(stats):
        x = L + i * (A + 8) / 2
        width = (A - 8) / 2
        page.rect(x, 670, width, 37, PALE)
        page.lab(title, x + 8, 682, 7.8, True)
        _line(page, value, x + 8, 700, width - 16, 14.5, bold=True)
    page.lab('Календарный план погашения (млн ' + unit + ')', L, 720, 9.2, True)
    step = A / months
    for i in range(months):
        month = shifted_month(first, i)
        x = L + i * step
        page.rect(x, 729, step, 16, PALE)
        _line(page, f'{MONTHS[month.month - 1]} {month:%y}', x, 740, step, 7.7, center=True, bold=True)
        amount = amounts.get(month.isoformat()[:7], 0 if complete else None)
        label = 'Нет графика' if amount is None else _millions(Decimal(amount))
        _line(page, label, x, 759, step, 9, center=True, bold=True)
    _line(page, note, L, 787, A, 7.2, color=GRAY)


def render_ip(page):
    section = page.data['sections']['financial']
    fields, ip = section['fields'], section['ip']
    unit = page.data['money_unit']
    page.new('financial', '', subtitle=' ')
    # The approved IP sheet keeps its title and borrower on fixed baselines.
    date_label = _day(page.data['as_of'])
    if page.data['demo']:
        _line(page, date_label, R, 45, 280, 7.5, right=True)
    else:
        _line(page, 'ФИНАНСОВЫЙ АНАЛИЗ / ' + date_label, R, 33, 280, 7.5, bold=True, right=True)
    _line(page, 'Анализ финансового состояния', L, 79, A - 170, 22, bold=True)
    _line(page, page.data['subject'], L, 100, A - 174, 10.5, bold=True)
    page.rect(L, 111, A, 35, PALE)
    page.rect(L, 111, 3, 35, BLUE)
    amount = fields['amount']['value']
    rate = fields['rate']['value']
    terms = (
        'Сумма не указана' if amount is None else _amount(amount, unit),
        'Ставка не указана' if rate is None else (number(rate) + '% годовых' if isinstance(rate, (int, float)) else rate),
        _shown(fields['term'], 'Срок не указан') if fields['term']['value'] is not None else 'Срок не указан',
    )
    _line(page, ' / '.join(terms), L + 12, 133, A - 24, 12, bold=True)
    _text_box(page, _shown(ip['project'], 'Цель займа и график погашения не установлены'), 153, 28, 8.6)
    page.rect(L, 184, A, 34, PALE)
    page.lab('Планируемый залог', L + 8, 195, 8.2, True)
    _text_box(page, _shown(ip['security'], 'Параметры залога не представлены'), 199, 17, 8.3, L + 8, A - 16)
    scope = ip['bank_scope']
    coverage_label = (
        f'Операций: {scope["operations"]}. Счетов: {scope["accounts"]}. '
        f'Период выписок {_day(scope["start"])}–{_day(scope["end"])}.'
        if scope else 'Сведения об охвате банковских выписок не представлены'
    )
    _line(page, coverage_label, L, 233, A, 8.3)

    cards = (('Операционные поступления', 'operating'), ('Долг по БКИ', 'debt'), ('Просрочка по БКИ', 'overdue'))
    for i, (title, key) in enumerate(cards):
        x = L + i * (A + 8) / 3
        width = (A - 16) / 3
        page.rect(x, 244, width, 51, PALE)
        page.lab(title, x + 10, 259, 8.7, True)
        _line(page, _amount(ip[key]['value'], unit), x + 10, 286, width - 20, 17, bold=True)
    page.lab('Денежные потоки', L, 316, 12, True)
    width = (A - 25) / 2
    for x, title, rows in ((L, 'Поступления', INCOMING), (R - width, 'Списания', OUTGOING)):
        page.rect(x, 324, width, 17, PALE)
        page.lab(title, x + 8, 336, 9, True)
        known = []
        for i, (key, label) in enumerate(rows):
            top = 354 + 14 * i
            amount = ip[key]['value']
            if amount is not None:
                known.append(amount)
            _line(page, label, x + 8, top, width - 93, 7.4)
            if amount is None:
                display = _shown(ip[key], 'Не выделена' if key == 'payroll' else 'Нет данных')
            else:
                display = _amount(amount, unit)
            _line(page, display, x + width - 8, top, 83, 9.3, bold=True, right=True)
            page.rule(x, top + 4, x + width)
        page.lab('Итого по строкам', x + 8, 444, 9, True)
        _line(page, _amount(sum(known) if known else None, unit), x + width - 8, 444, 100, 10.3, bold=True, right=True)
    _text_box(page, _shown(ip['flow_note'], 'В таблицах показаны суммы по представленным счетам.'), 452, 30, 7.5)
    _chart(page, scope, ip['monthly_receipts'], unit)

    page.lab('Фактические выплаты по кредитам и займам за период', L, 582, 10.5, True)
    for top, key, title in ((601, 'bank_repayments', 'Банковские кредиторы'), (619, 'nonbank_repayments', 'Небанковские кредиторы')):
        page.lab(title, L + 8, top, 8.6)
        _line(page, _amount(ip[key]['value'], unit), L + width - 2, top, 100, 10.5, bold=True, right=True)
        page.rule(L, top + 4, L + width)
    x = R - width
    page.rect(x, 591, width, 37, PALE)
    page.rect(x, 591, 3, 37, BLUE)
    platform = _shown(ip['platform_name'], 'платформой')
    _line(page, 'История работы с ' + platform, x + 10, 603, width - 20, 9.1, bold=True)
    value = ip['platform_repayments']['value']
    _line(page, 'Выплаты не подтверждены' if value is None else 'Подтверждено ' + _amount(value, unit),
          x + 10, 618, width - 20, 9.2)
    calendar = section['ip_calendar']
    _calendar(page, calendar, ip['regular_payment'],
              _shown(ip['calendar_note'], 'Платежи по выпискам могут включать основной долг и проценты одной суммой.'), unit)
    summary = fields['summary']['value'] or 'Итоги ограничены представленными документами.'
    _line(page, _shown(ip['closing_note'], summary), L, 775, A, 7.2, color=GRAY)
