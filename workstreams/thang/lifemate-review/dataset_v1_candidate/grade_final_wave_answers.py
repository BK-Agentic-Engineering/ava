"""Ten narrow answer rubrics grounded in submitted observations; other cases stay manual."""
from datetime import datetime,timedelta
from decimal import Decimal
import re
import unicodedata

RULES={
 'TR9_WALLET_LOOK':('ewallet.get_balance',None,{},'balance','vnd'),
 'TR11_SAVE_LOOK':('banking.get_balance','accounts',{'name':'Quỹ Kẹp Vải'},'balance','vnd'),
 'TR9_WEATHER_LOOKNEXT':('weather.get_forecast','forecast',{'location':'Huế','date':'2027-03-12'},'rain_pct','percent'),
 'TR14_CITY_LOOK':('weather.get_forecast','forecast',None,'rain_pct','percent'),
 'TR12_LEARN_LOOK':('learning.list_courses','courses',{'name':'Gấp Nếp','provider':'Nhà Cói'},'progress_minutes','minutes'),
 'TR10_PHONE_LOOK':('phone.recent_calls','calls',{'direction':'incoming','status':'completed','time':'2027-04-10T08:30:00+07:00'},'phone_number','phone'),
 'TR9_MEET_LOOK':('video_meeting.list_meetings','meetings',{'title':'Kiểm Vết Men','start':'2027-03-10T09:00:00+07:00'},'link','url'),
 'TR12_SOURCE_READONLY':('notes.list','notes',{'title':'Điểm Đóng Kiện'},'content','address'),
 'TR12_QUOTE_LOOK':('notes.list','notes',{'title':'Lời Ghi'},'content','quote'),
 'TR8_TASK_STATUS':('tasks.list','tasks',{'title':'Gói Mẫu Cát'},'done','done')}


def norm(text):return ' '.join(unicodedata.normalize('NFC',text).casefold().split()).rstrip('.!')


def numeric_value(text,kind):
    if re.fullmatch(r'[0-9]+',text):
        return Decimal(text)
    if kind=='vnd':
        # Vietnamese integer grouping uses consistent dots or spaces.
        grouped=re.fullmatch(r'[1-9][0-9]{0,2}([. ])[0-9]{3}(?:\1[0-9]{3})*(?:,[0-9]+)?',text)
        if grouped:
            return Decimal(text.replace(grouped[1],'').replace(',','.'))
        decimal=r'[0-9]+,[0-9]{1,2}'
    elif kind=='percent':
        # A leading zero is not a thousands group. Percentage decimals
        # such as 0.050% are small fractions, never 50%.
        decimal=r'(?:0[.,][0-9]+|[0-9]+[.,][0-9]{1,2})'
    else:
        decimal=r'[0-9]+[.,][0-9]{1,2}'
    return Decimal(text.replace(',','.')) if re.fullmatch(decimal,text) else None


def observed_value(sid,visible,calls):
    tool,collection,selector,field,kind=RULES[sid]
    if selector is None:
        c=visible['context'];selector={'location':c['user_profile']['city'],'date':(datetime.fromisoformat(c['current_time'])+timedelta(days=1)).date().isoformat()}
    records={};found=False;scalar=None
    for ci,c in enumerate(calls):
        r=c['result']
        if c['name']!=tool or tool not in visible['allowed_tools'] or r.get('ok') is not True or r.get('done') is False:continue
        if collection is None:
            if field in r:scalar=r[field];found=True
        elif isinstance(r.get(collection),list):
            for ri,row in enumerate(r[collection]):
                if isinstance(row,dict) and all(row.get(k)==v for k,v in selector.items()) and field in row:
                    records[('id',row['id']) if row.get('id') else ('position',ci,ri)]=row[field]
    if collection is None:return (found,scalar)
    return (True,next(iter(records.values()))) if len(records)==1 else (False,None)


def grade(sid,visible,calls,text,trace_verdict='pass'):
    if trace_verdict!='pass':return {'verdict':'fail','reason':'trace_not_passed'}
    if not isinstance(text,str) or not text.strip():return {'verdict':'fail','reason':'missing_required_answer'}
    if sid not in RULES:return {'verdict':'unresolved','reason':'manual_rubric_required'}
    supported,value=observed_value(sid,visible,calls)
    if not supported:return {'verdict':'fail','reason':'insufficient_relevant_observation'}
    kind=RULES[sid][-1];t=norm(text);actual=None
    if kind in {'vnd','percent','minutes'}:
        number=r'(?P<n>[0-9]+(?:[., ][0-9]+)*)'
        unit={'vnd':r'(?:đồng|vnd|đ)','percent':r'(?:%|phần trăm)','minutes':r'phút'}[kind]
        prefix={'vnd':r'(?:(?:ví còn|quỹ còn|số dư(?: là)?) )?','percent':r'(?:(?:khả năng mưa|xác suất mưa(?: là)?) )?','minutes':r'(?:(?:đã tích lũy) )?'}[kind]
        if kind=='percent' and sid=='TR14_CITY_LOOK':prefix=r'(?:'+re.escape(norm(visible['context']['user_profile']['city']))+r' ngày mai có )?'+prefix
        match=re.fullmatch(prefix+number+r'\s*'+unit,t)
        if match:
            actual=numeric_value(match['n'],kind)
    elif kind=='phone':
        match=re.fullmatch(r'(?:(?:số đó|số điện thoại) là )?(\d+)',t)
        if match:actual=match[1]
    elif kind=='done':
        positive={'xong rồi','đã xong','việc đó đã hoàn thành'};negative={'chưa xong','việc đó chưa hoàn thành'}
        if t in positive:actual=True
        elif t in negative:actual=False
    elif kind=='url':
        raw=re.sub(r'^link là ', '',text.strip(),flags=re.IGNORECASE).rstrip('.!')
        if re.fullmatch(r'https?://\S+',raw):
            if raw.casefold()==str(value).casefold() and raw!=value:return {'verdict':'unresolved','reason':'url_case_equivalence_not_established'}
            actual=raw
    else:
        # Recognize only whole observed strings with a small task-relevant wrapper.
        prefix={'address':r'(?:địa chỉ là )?','quote':r'(?:nội dung: )?'}[kind]
        match=re.fullmatch(prefix+'(.+)',t)
        candidate=match[1] if match else t
        if kind=='quote':candidate=norm(candidate.strip('“”"'))
        if candidate==norm(str(value)):actual=value
        elif kind=='quote' and norm(str(value)).startswith(candidate):return {'verdict':'fail','reason':'missing_quote_content'}
    if actual is None:return {'verdict':'unresolved','reason':'outside_scoped_equivalence'}
    matches=actual==value
    if isinstance(actual,Decimal):
        matches=type(value) in (int,float) and actual==Decimal(str(value))
    return {'verdict':'pass' if matches else 'fail','reason':'supported_fact' if matches else 'wrong_value','observed_value':value}
