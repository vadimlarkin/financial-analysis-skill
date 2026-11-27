"""Drawing code for the original branded financial report layouts."""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import html
import io
import math
from pathlib import Path
import re


class ReportError(ValueError):
    pass


W,H=595.28,841.89
L,R,A=36,W-36,W-72
INK,BLUE,GRAY,PANEL,GRID,PALE='#23282D','#0072EF','#515D67','#F3F3F3','#E1E5E9','#E9F5FF'
LIMIT=786
ASSETS=Path(__file__).resolve().parents[1] / 'assets'
FONT_HASHES={'Body':('RobotoFlex-Text.ttf','1ea45867601ead14da44818408a8d6af5c28e643b345258ede8e3b2873bd21f8'),
             'BodyBold':('RobotoFlex-Heading.ttf','751b033f8cc4fae744b18675dc777281a10a440fbda2711b0187cf3f6bb5a8da')}
LOGO_HASH='33d4ebd4c516e49244922dd5c345d4ff163033693cc345c215f6ea501bcd043e'

STATEMENTS = (
    ('revenue', 'Выручка'), ('operating_profit', 'Прибыль от продаж'), ('net_profit', 'Чистая прибыль'),
    ('total_assets', 'Активы всего'), ('fixed_assets', 'Основные средства'), ('inventory', 'Запасы'),
    ('receivables', 'Дебиторская задолженность'), ('cash', 'Деньги'),
    ('long_term_investments', 'Долгосрочные финансовые вложения'),
    ('short_term_investments', 'Краткосрочные финансовые вложения'), ('equity', 'Собственный капитал'),
    ('long_term_debt', 'Долгосрочные кредиты и займы'), ('short_term_debt', 'Краткосрочные кредиты и займы'),
    ('accounts_payable', 'Кредиторская задолженность'))
CASHFLOW = (('revenue', 'Выручка'), ('net_credit_turnover', 'Чистый кредитовый оборот'),
            ('principal_paid', 'Погашение основного долга'), ('cash_interest_paid', 'Уплаченные проценты'))
CURRENT_DEBT = (('bank_principal', 'Банковские'), ('unrelated_nonbank_principal', 'Небанковские, кроме связанных'),
                ('related_party_principal', 'Перед связанными кредиторами'))
RATIOS = (('interest_coverage', 'Прибыль от продаж / проценты'), ('debt_equity', 'Процентный долг / капитал'))

LABELS = {'amount': 'Сумма займа', 'rate': 'Ставка заёмщика', 'term': 'Срок и погашение'}
VERSION = 'financial-analysis-1.0'


def number(value,decimals=2):
    value=Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals),rounding=ROUND_HALF_UP)
    return f'{value:,.{decimals}f}'.replace(',',' ').replace('.',',')


def value(f, *, money=False):
    v = f['value']
    if v is None:
        result = '—'
    elif isinstance(v, (int, float)):
        if money:
            # Keep a small confirmed amount visibly distinct from zero.
            n = 1 if v == 0 or abs(v) >= 100000 else min(6, max(2, 7-int(math.log10(abs(v)))))
            result = number(v/1000000, n)
        else:
            result = number(v, 0 if v == int(v) else 2)
    else:
        result = str(v)
    if f.get('unit') and not money and result != '—':
        result += ' ' + f['unit']
    return result


def load_assets():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    base=ASSETS
    for name,(filename,digest) in FONT_HASHES.items():
        path=base/'fonts'/filename
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ReportError('Не найден или изменён шрифт '+filename)
        if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,str(path)))
    logo=base/'brand/vbeton-logo.pdfpath'
    if not logo.is_file() or hashlib.sha256(logo.read_bytes()).hexdigest()!=LOGO_HASH:
        raise ReportError('Не найден проверенный векторный логотип ВБетон')
    return logo.read_text(encoding='ascii')


class Pages:
    def __init__(self,data,logo):
        from reportlab.lib.colors import HexColor
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph
        from reportlab.lib.enums import TA_JUSTIFY,TA_LEFT,TA_RIGHT
        from reportlab.pdfgen.canvas import Canvas
        self.HexColor,self.stringWidth=HexColor,stringWidth
        self.ParagraphStyle,self.Paragraph=ParagraphStyle,Paragraph
        self.TA_JUSTIFY,self.TA_LEFT,self.TA_RIGHT=TA_JUSTIFY,TA_LEFT,TA_RIGHT
        self.Canvas=Canvas
        self.data,self.logo=data,logo
        self.pages=[];self.c=None;self.t=0;self.title='';self.key='';self.pending_section=None

    def rect(self,x,top,w,h,color=PANEL):
        self.c.setFillColor(self.HexColor(color));self.c.rect(x,H-top-h,w,h,fill=1,stroke=0)

    def rule(self,x,top,x2,color=GRID,width=.5):
        self.c.setStrokeColor(self.HexColor(color));self.c.setLineWidth(width);self.c.line(x,H-top,x2,H-top)

    def lab(self,text,x,top,size=9.5,bold=False,color=INK,right=False):
        self.c.setFillColor(self.HexColor(color));self.c.setFont('BodyBold' if bold else 'Body',size)
        (self.c.drawRightString if right else self.c.drawString)(x,H-top,str(text))

    def para(self,text,x,top,width,size=10.6,bold=False,color=INK,justify=True,right=False,url=None):
        if width<=14:raise ReportError('Недостаточная ширина поля')
        text=str(text)
        text=re.sub(r'(?<=\d) (?=\d{3}(?:\D|$))','\u00a0',text)
        text=re.sub(r'(?<=\d) +(млн +₽|тыс\. +₽|₽(?:/м²)?|м²|дней)',lambda m:'\u00a0'+m[1].replace(' ','\u00a0'),text)
        st=self.ParagraphStyle('p',fontName='BodyBold' if bold else 'Body',fontSize=size,leading=size*1.27,
            textColor=self.HexColor(color),alignment=self.TA_RIGHT if right else self.TA_JUSTIFY if justify else self.TA_LEFT,
            splitLongWords=True)
        markup=html.escape(text).replace('\n','<br/>')
        if url:
            markup='<link href="'+html.escape(url,quote=True)+'" color="'+BLUE+'">'+markup+'</link>'
        p=self.Paragraph(markup,st)
        _,height=p.wrap(width,H)
        if top is not None:
            if top+height>LIMIT+.01:raise ReportError('Текст не помещается в отведённое поле: '+text[:60])
            p.drawOn(self.c,x,H-top-height)
        return height

    def logo_draw(self):
        self.c.beginForm('VBetonLogo',0,0,585.0041,120.317)
        self.c.addLiteral(self.logo);self.c.endForm()
        self.c.saveState()
        self.c.translate(36,H-23-120.317*100/585.0041);self.c.scale(100/585.0041,100/585.0041)
        self.c.doForm('VBetonLogo');self.c.restoreState()

    def new(self,key,title,subtitle=None,category=''):
        self.end()
        self.buffer=io.BytesIO();self.c=self.Canvas(self.buffer,pagesize=(W,H),invariant=1,pageCompression=1)
        self.c.setAuthor('ВБетон');self.c.setTitle(self.data['title'])
        self.key,self.title,self.category=key,title,category
        self.subtitle_base=subtitle or self.data['subject']+' / '+self.data['as_of']
        self.logo_draw()
        if self.data['demo']:self.lab('ОБРАЗЕЦ / УСЛОВНЫЕ ДАННЫЕ',R,33,8,True,right=True)
        self.rule(L,56,R)
        if category:self.lab(category.upper(),L,76,8.5,True,BLUE)
        top=83 if category else 66
        rating=self.financial_rating() if key=='financial' else None
        title_width=A-218 if rating else A
        self.t=top+self.para(title,L,top,title_width,25,True,justify=False)+5
        if rating:
            self.draw_financial_rating(rating)
            self.t=max(self.t,112)
        self.t+=self.para(self.subtitle_base,L,self.t,A,10,color=GRAY,justify=False)+18
        if self.t>310:raise ReportError('Слишком длинный заголовок страницы')

    def end(self):
        if self.c is not None:
            self.c.showPage();self.c.save()
            self.pages.append({'data':self.buffer.getvalue(),'key':self.key,'title':self.title})
            self.c=None

    def continuation(self):
        key,title,sub,cat=self.key,self.title,self.subtitle_base,self.category
        if not title.endswith(' · продолжение'):title+=' · продолжение'
        self.new(key,title,sub,cat)

    def ensure(self,height):
        # Delay section ink until the next block's real height is known. A section
        # travels with its table header and first complete row, including long rows.
        pending=self.pending_section;self.pending_section=None
        extra=23 if pending else 0
        if self.t+extra+height>LIMIT:self.continuation()
        if self.t+extra+height>LIMIT:raise ReportError('Одна строка или блок превышает полезную высоту страницы')
        if pending:
            title,hint=pending
            self.lab(title,L,self.t+14,14,True)
            if hint:
                if self.stringWidth(hint,'Body',8.6)>A-self.stringWidth(title,'BodyBold',14)-14:
                    raise ReportError('Слишком длинная подпись раздела')
                self.lab(hint,R,self.t+14,8.6,color=GRAY,right=True)
            self.t+=23

    def sec(self,title,hint=''):
        if self.pending_section is not None:raise ReportError('Раздел не содержит блока данных')
        self.pending_section=(title,hint)

    def body(self,text,size=10.6,gap=10,color=INK):
        h=self.para(text,L,None,A,size,color=color);self.ensure(h+gap)
        self.para(text,L,self.t,A,size,color=color);self.t+=h+gap

    def tab(self,headers,rows,widths,*,size=10,pad=4.6,nums=(),highlight=None,scores=None,gap=11):
        if abs(sum(widths)-A)>.1:raise ReportError('Неверная ширина таблицы')
        def height(row,bold=False):
            if len(row)!=len(widths):raise ReportError('Неверное число ячеек')
            return max(self.para(v,0,None,w-14,size,bold,justify=j==1 and not bold,right=j in nums)
                       for j,(v,w) in enumerate(zip(row,widths)))+2*pad
        hh=height(headers,True)
        def paint(row,bold=False,score=None):
            h=height(row,bold)
            if score is not None:h=max(h,44)
            if bold:self.rect(L,self.t,A,h)
            else:self.rule(L,self.t+h,R)
            if bold and highlight is not None:self.rect(L+sum(widths[:highlight]),self.t,widths[highlight],h,PALE)
            x=L
            for j,(v,w) in enumerate(zip(row,widths)):
                if score is not None and j==len(widths)-1:self.score(score,x+w/2,self.t+h/2)
                else:self.para(v,x+7,self.t+pad,w-14,size,bold,justify=j==1 and not bold,right=j in nums)
                x+=w
            self.t+=h
        rows=rows or [['—']+['']*(len(headers)-1)]
        first=max(height(rows[0]),44 if scores else 0)
        self.ensure(hh+first+8);paint(headers,True)
        for i,row in enumerate(rows):
            h=max(height(row),44 if scores else 0)
            if self.t+h+8>LIMIT:
                self.continuation()
                if self.t+hh+h+8>LIMIT:raise ReportError('Строка таблицы не помещается на странице')
                paint(headers,True)
            paint(row,score=scores[i] if scores else None)
        self.t+=gap

    def score(self,f,x,top,*,financial=False):
        v=f['value']
        if v is None or f['status'] != 'confirmed':
            self.para('—',x-33,top-10,66,8.2,color=GRAY,justify=False);return
        r=15 if financial else 16.5;maximum=f.get('maximum',999)
        self.c.saveState()
        self.c.setFillColor(self.HexColor(PANEL));self.c.setStrokeColor(self.HexColor('#D7EAFB'))
        self.c.setLineWidth(6 if financial else 2.15);self.c.circle(x,H-top,r,fill=not financial,stroke=1)
        self.c.setStrokeColor(self.HexColor(BLUE));self.c.setLineCap(0 if financial else 1)
        if v>0:self.c.arc(x-r,H-top-r,x+r,H-top+r,startAng=90,extent=-360*v/maximum)
        self.c.setLineCap(0)
        self.c.setFillColor(self.HexColor(INK));self.c.setFont('BodyBold',10.5)
        if financial:
            self.c.setFont('BodyBold',11)
            self.c.drawCentredString(x,H-top-3.8,number(v,0))
        else:
            self.c.drawCentredString(x,H-top-1,number(v,0));self.c.setFillColor(self.HexColor(GRAY));self.c.setFont('Body',6.5)
            self.c.drawCentredString(x,H-top-9,'из '+str(maximum))
        self.c.restoreState()

    def financial_rating(self):
        scored=[person for person in self.data['persons']
                if person['score']['value'] is not None and person['score']['status']=='confirmed']
        return next((person for person in scored if 'borrower' in person['roles']),scored[0] if scored else None)

    def draw_financial_rating(self,person):
        score={**person['score'],'maximum':person['score_max']}
        source=next(source for source in self.data['sources'] if source['id']==score['sources'][0])
        x=R-18;top=88;right=R-44;width=174
        self.score(score,x,top,financial=True)
        self.lab('Рейтинг кредитной истории',right,79,9.5,True,right=True)
        bureau=source['credit_report']['bureau']
        dated=score['as_of']
        caption=bureau+' · '+dated
        if self.stringWidth(caption,'Body',8.5)<=width:
            height=self.para(caption,right-width,85,width,8.5,color=GRAY,right=True,justify=False,url=source.get('url'))
        else:
            height=self.para(bureau,right-width,None,width,8.5,right=True,justify=False)
            if height>24:raise ReportError('Слишком длинная подпись рейтинга бюро в шапке')
            self.para(bureau,right-width,85,width,8.5,color=GRAY,right=True,justify=False)
            height+=self.para(dated,right-width,85+height,width,8.5,color=GRAY,right=True,justify=False,url=source.get('url'))
        self.t=max(self.t,85+height+6)
        # The report subject identifies the borrower; other participants need a name.
        if 'borrower' not in person['roles']:
            self.t+=self.para(person['name'],right-width,self.t,width,8,color=GRAY,right=True,justify=False)



def financial(p):
    s=p.data['sections']['financial']
    if s.get('review') is not None:
        financial_review(p);return
    p.new('financial','Финансовый отчёт')
    start_count=len(p.pages);f=s['fields']
    summary=value(f['summary'])
    if p.para(summary,L+12,None,A-24,10.3)>28:raise ReportError('Сократите финансовый вывод до двух строк')
    p.rect(L,p.t,A,38);p.rect(L,p.t,3,38,BLUE)
    p.para(summary,L+12,p.t+5,A-24,10.3);p.t+=47
    for x,k in [(L,'amount'),(L+175,'rate'),(L+350,'term')]:
        p.lab(LABELS[k],x,p.t+9,8.5,color=GRAY)
        txt=value(f[k])
        if p.para(txt,x,None,169,10.4,True,justify=False)>27:raise ReportError('Слишком длинное условие займа в финансовом листе')
        p.para(txt,x,p.t+14,169,10.4,True,justify=False)
    p.t+=43
    p.sec('Финансовое состояние','млн '+p.data['money_unit'])
    headers=['Результаты']+[value(x) for x in s['periods']]
    widths=[256,87,87,A-430]
    rows=[[label]+[value(v,money=True) for v in s['statements'][k]] for k,label in STATEMENTS[:3]]
    p.tab(headers,rows,widths,pad=2.3,nums=(1,2,3),highlight=3,gap=7)
    rows=[[label]+[value(v,money=True) for v in s['statements'][k]] for k,label in STATEMENTS[3:]]
    p.tab(['Активы и обязательства']+[value(x) for x in s['balance_dates']],rows,widths,pad=2.1,nums=(1,2,3),highlight=3)
    # Same two-column chart/debt composition as accepted page 6.
    p.ensure(111);top=p.t;split=L+272
    p.lab('Поступления и погашения',L,top+11,12,True);p.lab('Кредитная нагрузка',split,top+11,12,True)
    for x,width,caption in [(L,260,value(f['chart_period'])),(split,A-272,value(f['debt_date']))]:
        if p.para(caption,x,None,width,8.7,justify=False)>23:raise ReportError('Слишком длинный период финансового блока')
        p.para(caption,x,top+17,width,8.7,color=GRAY,justify=False)
    valid=all(s['cashflow'][k]['status'] in {'confirmed','calculated'} and isinstance(s['cashflow'][k]['value'],(int,float)) for k,_ in CASHFLOW)
    cash_values=[s['cashflow'][k]['value'] for k,_ in CASHFLOW] if valid else [0]
    cash_min=min(0,min(cash_values));cash_max=max(0,max(cash_values));cash_span=max(1,cash_max-cash_min)
    cash_x=lambda v:L+130+72*(v-cash_min)/cash_span
    for i,(k,label) in enumerate(CASHFLOW):
        yy=top+51+i*14.7;p.lab(label,L,yy,8.4)
        fact=s['cashflow'][k]
        if valid:
            p.rect(L+130,yy-8,72,8,PALE)
            a,b=cash_x(0),cash_x(fact['value'])
            p.rect(min(a,b),yy-8,abs(b-a),8,BLUE)
            if cash_min<0:
                p.c.setStrokeColor(p.HexColor(GRAY));p.c.setLineWidth(.5)
                p.c.line(cash_x(0),H-yy+10,cash_x(0),H-yy-2)
        p.lab(value(fact,money=True),L+258,yy,8.6,True,right=True)
    for i,(k,label) in enumerate(CURRENT_DEBT):
        yy=top+51+i*14.7
        p.lab(label,split,yy,8.4);p.lab(value(s['current_debt'][k],money=True),R,yy,8.6,True,right=True)
        p.rule(split,yy+4,R)
    p.t=top+111
    p.sec('Влияние нового займа')
    period=value(f['ratio_period'])
    rows=[[label+'\n'+(period if k=='interest_coverage' else value(f['debt_date']).split('·',1)[0].strip()),value(s['ratios'][k]['before']),value(s['ratios'][k]['after'])] for k,label in RATIOS]
    p.tab(['Соотношение','До займа','После займа'],rows,[302,102,A-404],pad=3.4,nums=(1,2),gap=7)
    if f['footnote']['value'] is not None:
        p.body(value(f['footnote']),8.2,4,GRAY)
    if len(p.pages)!=start_count:raise ReportError('Финансовая форма должна помещаться на одном листе. Сократите тексты полей.')


def financial_value(f, *, money=False, millions=False, money_unit=None):
    v = f['value']
    if v is None:
        return '—'
    if not isinstance(v, (int, float)):
        return str(v)
    if millions:
        return number(Decimal(str(v))/Decimal(1000000),8).rstrip('0').rstrip(',')
    if money:
        return (number(Decimal(str(v))/1000000,2)+' млн ' if abs(v)>=100000 else number(v,2)+' ')+(money_unit or f.get('unit') or '₽')
    return number(v,2)+(' '+f['unit'] if f.get('unit') else '')


def annual_table(section, header, period_facts, statements, *, gap, p):
    rows = [[label] + [financial_value(entry, millions=True) for entry in section['statements'][key]]
            for key, label in statements]
    p.tab([header] + [value(period) for period in period_facts], rows, [218,108,108,A-434],
          size=8.2, pad=1.5, gap=gap, nums=(1, 2, 3))


def financial_review(p):
    """One v0.8 page, shared by financial-only and full outputs."""
    s=p.data['sections']['financial'];r=s['review'];f=s['fields']
    p.new('financial','Финансовый отчёт')
    count=len(p.pages)
    if p.t>160:raise ReportError('Сократите заголовок финансовой страницы')
    horizon=r['horizon']['start']+' — '+(datetime.fromisoformat(r['horizon']['end_exclusive']).date()-timedelta(days=1)).isoformat()
    p.rect(L,p.t,A,31);p.rect(L,p.t,3,31,BLUE)
    p.lab('Покрытие прежних обязательств',L+10,p.t+12,10,True)
    p.lab('Прежние обязательства / '+horizon,L+10,p.t+25,8.3,color=GRAY);p.t+=39
    terms_height = 0
    for i,key in enumerate(('amount','rate','term')):
        x=L+i*A/3;width=A/3-8
        p.lab('Срок' if key=='term' else LABELS[key],x,p.t+9,8,color=GRAY)
        entry = f[key]
        if key == 'rate' and not entry.get('unit'):
            entry = {**entry, 'unit': '% годовых'}
        text = financial_value(entry, money=key == 'amount',money_unit=p.data['money_unit'])
        height = p.para(text,x,None,width,9.7,True,justify=False)
        if height > 25:
            raise ReportError('Слишком длинные условия финансовой формы')
        p.para(text,x,p.t+13,width,9.7,True,justify=False)
        citation = entry.get('as_of')
        if citation:
            height += p.para(citation,x,p.t+13+height,width,7.8,color=GRAY,justify=False)
        terms_height = max(terms_height, height)
    p.t += max(39, 17 + terms_height)
    if r['accounting_mode']=='corporate':
        p.sec('Краткая финансовая история','млн '+p.data['money_unit'])
        annual_table(s,'Результаты',s['periods'],STATEMENTS[:3],gap=3,p=p)
        annual_table(s,'Активы и обязательства',s['balance_dates'],STATEMENTS[3:],gap=7,p=p)
        if s.get('verified_calculations'):
            ratio = s['ratios']['debt_equity']['before']
            parts = ('Процентный долг / капитал до займа', ratio['as_of'], financial_value(ratio))
            p.body(' · '.join(filter(None, parts)), 8.4, 4, GRAY)
    else:
        p.sec('Денежные потоки ИП','млн '+p.data['money_unit']+', если не указано иное')
        labels=[('business_flow','Поток бизнеса до выплат кредиторам'),('creditor_payments','Выплаты по накопленным обязательствам'),
                ('external_receipts','Внешние поступления'),('borrowed_receipts','Кредиты и займы, включая займы собственника'),
                ('owner_contributions','Взносы собственника'),('historical_coverage','Историческое покрытие, раз'),('borrowed_share','Заимствования во внешних поступлениях, %')]
        rows=[]
        for key,label in labels:
            rows.append([label]+[financial_value(r['history'][window]['fields'][key],millions=key not in {'historical_coverage','borrowed_share'}) for window in ('12m','6m')])
        p.tab(['Показатель','Последние 12 месяцев','Последние 6 месяцев'],rows,[269,127,A-396],size=8.8,pad=2.3,gap=6,nums=(1,2))
        periods=[r['history'][w]['period']['start']+' — '+r['history'][w]['period']['end'] for w in ('12m','6m')]
        p.body('Периоды: '+periods[0]+' / '+periods[1],8.2,5,GRAY)
    p.sec('Прежние обязательства на шесть месяцев')
    p.ensure(118);top=p.t;gap=10;width=(A-gap)/2
    cards=[('coverage_ratio','Покрытие обязательств',False),('payments','Платежи за полгода',True),
           ('max_dated_deficit','Максимальный дефицит',True),('relative_deficit','Дефицит / рассматриваемый заём',False)]
    for i,(key,label,cash) in enumerate(cards):
        x=L+(i%2)*(width+gap);y=top+(i//2)*57
        p.rect(x,y,width,51);p.lab(label,x+9,y+12,8.6,color=GRAY)
        text=financial_value(r['metrics'][key],money=cash)
        size=16
        while p.stringWidth(text,'BodyBold',size)>width-18 and size>10:size-=.5
        if p.stringWidth(text,'BodyBold',size)>width-18:raise ReportError('Число финансовой формы не помещается')
        p.lab(text,x+9,y+32,size,True)
    p.t=top+116
    maximum=r['metrics']['max_dated_deficit']['value']
    at='Не возникает' if maximum==0 else r['maximum_date'] or '—'
    if r['maximum_month_index'] is not None:
        at += ' · месяц '+str(r['maximum_month_index'])+' из 6'
    p.body('Дата максимального разрыва: '+at,8.4,5,GRAY)
    p.body('Доступно для прежних обязательств на начало: '+financial_value(r['metrics']['opening_money'],money=True)+'.',8.4,3,GRAY)
    base = r['history']['6m']['period']
    p.body('База покрытия по выпискам '+base['start']+' — '+base['end']+
           '. Продолжение потока на горизонте покрытия: '+financial_value(r['metrics']['forecast_flow'],money=True)+'.',8.4,5,GRAY)
    if 'borrower_budget' in r:
        budget = r['borrower_budget']
        period = budget['period']
        p.body('Отдельный прогноз заёмщика '+period['start']+' — '+period['end']+
               ': '+financial_value(budget['flow'],money=True)+'.',8.4,5,GRAY)
    if 'debt_balance' in r:
        balance = r['debt_balance']
        label = 'Остаток по последним записям'
        entry = balance['total']
        if entry['value'] is None and balance['known_subtotal']['value'] is not None:
            label = 'Остаток по последним записям, известная часть'
            entry = balance['known_subtotal']
        p.body(label+' '+financial_value(entry,money=True)+'.',8.4,3,GRAY)
    if 'loan_schedule' in r:
        schedule = r['loan_schedule']
        label = 'Новый заём по графику' if not schedule['scenario_assumptions'] else 'Отдельный сценарий нового займа'
        p.body(label+'. Погашение основного долга до '+schedule['last_principal_date']+
               '. За первые 12 мес. проценты '+financial_value(schedule['interest_accrued'],money=True)+
               ', комиссии '+financial_value(schedule['fees'],money=True)+'.',8.4,3,GRAY)
    if 'ip_load' in r:
        load = r['ip_load']
        period = load['period']
        label = 'Нагрузка ИП, сценарий'
        if load['status'] == 'partial':
            label += ', известная часть'
        p.body(label+' '+period['start_month']+' — '+period['end_month']+' '+
               financial_value(load['payments'],money=True)+'.',8.4,3,GRAY)
    source_map = {source['id']: source for source in p.data['sources']}
    header_rating=p.financial_rating()
    scored = [person for person in p.data['persons'] if person['score']['value'] is not None and person is not header_rating]
    if len(scored)>5:raise ReportError('Более пяти рейтингов не помещаются на финансовом A4; сохраните их в разделе участников')
    if scored:
        p.ensure(45)
        width=A/len(scored);top=p.t
        for i,person in enumerate(scored):
            x=L+i*width
            score={**person['score'],'maximum':person['score_max']}
            p.score(score,x+21,top+19,financial=True)
            source = source_map[score['sources'][0]]
            bureau = source['credit_report']['bureau']
            caption = person['name']+' / '+bureau+'\n'+score['as_of']
            if p.para(caption,x+43,None,width-47,7.8,justify=False)>42:raise ReportError('Слишком длинная подпись рейтинга бюро')
            p.para(caption,x+43,top+2,width-47,7.8,color=GRAY,justify=False,url=source.get('url'))
        p.t+=45
    if f['summary']['value'] is not None:
        p.body(value(f['summary']),9.2,5)
    if len(p.pages)!=count or p.t>LIMIT:raise ReportError('Финансовая форма должна помещаться на одном A4; сократите подписи и комментарии')
