"""Descriptive DTS drivers shared by ARGOS and the release radar; no model blending."""
import copy
from decimal import Decimal, ROUND_HALF_UP
from institutional_core import cash_contract, finite, lag364_stats

PULSE_FIELDS=(
    'withheld_20d_yoy_pct','withheld_fytd_yoy_pct','dol_benefits_20d_yoy_pct',
    'dol_benefits_fytd_yoy_pct','indiv_refunds_fytd_yoy_pct',
    'biz_refunds_today_musd','customs_fytd_musd','customs_20d_yoy_pct')

def clean(value):
    return value if finite(value) else None

def yoy(current,previous):
    # Preserve negative current reversals; an absent/nonpositive base is not a meaningful percentage denominator.
    return round(100*(current/previous-1),2) if finite(current) and finite(previous) and previous>0 else None

def refund_total(record,kind,period):
    keys=[f'{kind}_eft_{period}',f'{kind}_checks_{period}']
    return sum(record[k] for k in keys) if all(k in record.get('present',set()) and finite(record.get(k)) for k in keys) else None

def fiscal_pulse(dates,asof,anchor,value,t5,customs_clean,flags):
    idx=dates.index(asof)
    def rolling(side,cid):
        return lag364_stats({d:value(side,cid,d,'today') for d in dates},dates,idx,20)[0]
    def fiscal(side,cid):
        return yoy(value(side,cid,asof,'fytd'),value(side,cid,anchor,'fytd') if anchor else None)
    return {
        'withheld_20d_yoy_pct':rolling('Deposits','WITHHELD_FICA'),
        'withheld_fytd_yoy_pct':fiscal('Deposits','WITHHELD_FICA'),
        'dol_benefits_20d_yoy_pct':rolling('Withdrawals','DOL_UNEMP_BEN'),
        'dol_benefits_fytd_yoy_pct':fiscal('Withdrawals','DOL_UNEMP_BEN'),
        'indiv_refunds_fytd_yoy_pct':yoy(refund_total(t5.get(asof,{}),'indiv','fytd'),refund_total(t5.get(anchor,{}),'indiv','fytd')),
        'biz_refunds_today_musd':refund_total(t5.get(asof,{}),'biz','today'),
        'customs_fytd_musd':clean(value('Deposits','CUSTOMS_DUTIES',asof,'fytd')),
        'customs_20d_yoy_pct':rolling('Deposits','CUSTOMS_DUTIES'),
        'basis':{'rolling':'lag364_daily_mean_20_sessions','fytd':'official_cumulative_same_calendar_anchor','fytd_anchor':anchor},
        'customs_20d_comparable':bool(customs_clean),'flags':sorted(set(flags)),
    }

def ntf_persistence(records,dates,count):
    window=[records[d] for d in dates[-count:]]
    if len(window)!=count or any(not r.get('inputs_complete') or not finite(r.get('ntf_total'))
        or not finite(r.get('recon_diff')) or r['recon_diff']>5 for r in window):return None
    return round(sum(r['ntf_total'] for r in window))

def dts_summary(payload,now):
    dts=cash_contract(copy.deepcopy(payload),now);m=dts.get('mmt_liquidity',{});blocked=dts['dq']['block']
    def pick(key):return None if blocked else clean(m.get(key))
    out={'at':dts.get('asof'),'blocked':blocked,'expires':dts.get('valid_until_utc'),'units':'USD_millions',
         'ntf':pick('ntf_total'),'reserve_contribution':pick('reserves_impact'),
         'tga_close':pick('tga_close'),'tga_open':pick('tga_open'),'dtga':pick('dtga'),
         'net_debt_cash':pick('net_debt_cash_iiib'),'calendar_z':pick('z_ntf_ex_exp_weekday_100bd'),
         'debt_headroom':pick('debt_headroom_iiic'),
         'slgs_status':'UNKNOWN' if blocked or m.get('slgs_open') is None else 'OPEN' if m['slgs_open'] is True else 'CLOSED',
         **{f'ntf_{n}d':pick(f'ntf_{n}d') for n in (5,20,60)}}
    if dts['dq'].get('calendar_miss') or dts['dq'].get('calendar_warmup'):out['calendar_z']=None
    source=dts.get('fiscal_pulse_lag364',{})
    pulse={k:None if blocked else clean(source.get(k)) for k in PULSE_FIELDS}
    for key in ('basis','customs_20d_comparable','flags'):pulse[key]=source.get(key,[] if key=='flags' else None)
    out['fiscal_pulse_lag364']=pulse
    return out

DRIVERS={
 'nfp':('withheld_20d_yoy_pct','Withheld 20d YoY (Lag 364)','Retenciones 20 sesiones interanual (Lag 364)','pct'),
 'claims':('dol_benefits_fytd_yoy_pct','DOL UI Benefits FYTD YoY','Prestaciones DOL interanual acumulado fiscal','pct'),
 'retail':('indiv_refunds_fytd_yoy_pct','Tax Refunds FYTD YoY (EFT + Checks)','Devoluciones fiscales interanual acumulado fiscal (EFT + cheques)','pct'),
 'trade':('customs_fytd_musd','Customs Duties FYTD','Aduanas acumulado fiscal','billions'),
}

def attach_dts_drivers(cards,summary):
    pulse=summary['fiscal_pulse_lag364']
    for card in cards:
        if card['id'] not in DRIVERS:continue
        key,en,es,unit=DRIVERS[card['id']];v=pulse.get(key)
        billions=(Decimal(str(v))/Decimal(1000)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP) if finite(v) else None
        display=(f'{v:+.1f}%' if unit=='pct' else f'${billions:,.2f}B') if finite(v) else None
        display_es=(f'{v:+.1f}'.replace('.',',')+'%' if unit=='pct' else f'{billions:.2f}'.replace('.',',')+' mil millones USD') if finite(v) else None
        card.update(dts_driver=f'{en}: {display}' if display else None,
                    dts_driver_es=f'{es}: {display_es}' if display_es else None,
                    dts_driver_asof=summary['at'],dts_driver_expires=summary['expires'],
                    dts_driver_metric=key,dts_driver_status='BLOCKED' if summary['blocked'] else 'AVAILABLE' if display else 'UNAVAILABLE')
