"""Bounded identifier/filter grounding checks, NOT a general semantic proof."""
import re


def strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for item in value.values():yield from strings(item)
    elif isinstance(value,list):
        for item in value:yield from strings(item)


def parameters(value,path=()):
    if isinstance(value,dict):
        for key,item in value.items():
            if key.endswith('_id') or key.endswith('_ids') or key=='channel':
                for text in strings(item):yield path+(key,),text
            elif isinstance(item,(dict,list)):yield from parameters(item,path+(key,))
    elif isinstance(value,list):
        for i,item in enumerate(value):yield from parameters(item,path+(i,))


def unsupported_identifiers(visible,calls):
    """IDs/channel must be supplied or returned before use; source identity still needs oracle review.

    Case-insensitive matching accommodates supplied names; this does not certify
    translations, source selection, date arithmetic, complete scope or free text.
    """
    known=list(strings({k:v for k,v in visible.items() if k!='allowed_tools'}));issues=[]
    for i,call in enumerate(calls):
        for path,value in parameters(call['arguments']):
            if not value:continue
            pattern=re.escape(value.casefold())
            if path[-1]=='tracking_id' and call['name'].startswith('package_tracking.'):
                # The SDK removes whitespace and uppercases tracking codes.
                code=''.join(value.split()).upper()
                if code:
                    pattern=r'\s*'.join(map(re.escape,code))
                    sources=(source.upper() for source in known)
                else:
                    sources=()
            else:
                sources=(source.casefold() for source in known)
            complete=re.compile(r'(?<![\w-])'+pattern+r'(?![\w-])')
            if not any(complete.search(source) for source in sources):
                issues.append({'call_index':i,'tool':call['name'],'parameter_path':list(path),'value':value,'reason':'identifier_or_channel_not_supplied_or_previously_observed'})
        result=call['result']
        if call['name'] in set(visible['allowed_tools'])|{'sys.ask_missing_info'} and result.get('ok') is True and result.get('done') is not False:
            known.extend(strings(result))
    return issues
