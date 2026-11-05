"""Table-I cash monitor: official daily/MTD/FYTD amounts, never summed balances."""
from institutional_core import finite

COMPONENTS = [
 ('Deposits','WITHHELD_FICA','Payroll withholding / FICA','Retenciones de nómina / FICA'),
 ('Deposits','NON_WITHHELD_ELEC','Non-withheld income / SECA · electronic','Renta no retenida / SECA · electrónica'),
 ('Deposits','NON_WITHHELD_OTHER','Non-withheld income / SECA · other','Renta no retenida / SECA · otros'),
 ('Deposits','CORP_INCOME','Corporate income tax','Impuesto sobre sociedades'),
 ('Deposits','CUSTOMS_DUTIES','Customs duties, taxes and fees','Derechos, impuestos y tasas de aduanas'),
 ('Deposits','MEDICARE_PREMIUMS','Medicare premiums','Primas de Medicare'),
 ('Withdrawals','MEDICARE_PART_A','Medicare · Part A','Medicare · Parte A'),
 ('Withdrawals','MEDICARE_PART_B','Medicare · Part B','Medicare · Parte B'),
 ('Withdrawals','MEDICAID','Medicaid grants to states','Transferencias Medicaid a los estados'),
 ('Withdrawals','MEDICARE_PART_D','Medicare · Part D','Medicare · Parte D'),
 ('Withdrawals','DOD_MISC_WD','Department of Defense · miscellaneous','Departamento de Defensa · varios'),
 ('Withdrawals','HHS_MISC_WD','Health and Human Services · miscellaneous','Salud y Servicios Humanos · varios'),
 ('Withdrawals','USDA_SNAP','SNAP food assistance','Ayuda alimentaria SNAP'),
 ('Withdrawals','DOL_UNEMP_BEN','Unemployment benefits','Prestaciones por desempleo'),
 ('Withdrawals','INDIV_REFUNDS_EFT','Individual tax refunds · EFT','Devoluciones fiscales individuales · EFT'),
 ('Withdrawals','TREAS_INTEREST','Interest on Treasury securities','Intereses de títulos del Tesoro'),
 ('Withdrawals','SSA_BENEFITS','Social Security benefits','Prestaciones de la Seguridad Social'),
 ('Withdrawals','SSA_SSI','Supplemental Security Income','Ingreso de Seguridad Suplementario')]

def number(x):
    return round(x, 3) if finite(x) else None

def cash_row(day, source):
    r={'d':day,'fy':int(day[:4])+(int(day[5:7])>=10),'tga':number(source.get('tga_close')),'periods':{}}
    for mode,suffix,open_key in [('today','t1','tga_open'),('mtd','mtd_t1','tga_open_mtd'),('fytd','fytd_t1','tga_open_fytd')]:
        opening=number(source.get(open_key));dep=number(source.get('tga_dep_'+suffix));wd=number(source.get('tga_wd_'+suffix))
        complete=all(finite(v) for v in (opening,dep,wd,r['tga']))
        error=round(r['tga']-(opening+dep-wd),3) if complete else None
        r['periods'][mode]={'open':opening,'D':dep,'W':wd,'net':round(dep-wd,3) if finite(dep) and finite(wd) else None,
                             'recon':error,'ok':complete and abs(error)<=5}
    return r

def build_book(t1, t2, t3b, daily, contract, t3c=None):
    rows=[]
    for day in sorted(t1):
        r=cash_row(day,t1[day]);rec=daily.get(day,{})
        debt=(t3c or {}).get(day,{})
        limit=number(debt.get('stat_debt_limit'));subject=number(debt.get('debt_subj_limit'))
        r['debt']={'public':number(debt.get('debt_public')),'total':number(debt.get('debt_total')),
                   'headroom':number(limit-subject) if finite(limit) and limit>0 and finite(subject) else None}
        r['ntf']=number(rec.get('ntf_total')) if rec.get('inputs_complete') and rec.get('recon_diff',999)<=5 else None
        r['z']=number(rec.get('z_ntf_ex_exp_weekday_100bd')) if not rec.get('calendar_miss') and not rec.get('calendar_warmup') and r['ntf'] is not None else None
        for mode in ('today','mtd','fytd'):
            p=r['periods'][mode];debt=t3b.get(day,{})
            i=number(debt.get('cash_issues_'+mode));red=number(debt.get('cash_redemp_'+mode))
            p['I']=i;p['R']=red
            p['op_D']=number(p['D']-i) if finite(p['D']) and finite(i) else None
            p['op_W']=number(p['W']-red) if finite(p['W']) and finite(red) else None
        r['components']={}
        for side,cid,_,_ in COMPONENTS:
            obs=t2.get(side,{}).get(cid,{}).get(day,{})
            r['components'][cid]=[number(obs.get(mode)) if mode in obs.get('present',set()) else None for mode in ('today','mtd','fytd')]
        rows.append(r)
    return {'schema':'treasury-book-1.0','asof':contract.get('asof'),'generated_at':contract.get('generated_at'),
            'valid_until_utc':contract.get('valid_until_utc'),'unit':'USD_millions','source':'Daily Treasury Statement · Tables I / II / IIIB',
            'components':[{'side':s,'id':cid,'en':en,'es':es} for s,cid,en,es in COMPONENTS],
            'legacy_thresholds':{'source_commit':'dbab8541068e5ae1b35607b138822488f6b684c9','series':'daily_ntf',
                'mean_window':30,'std_ddof':0,'include_current':True,'bands':[1,2],'z_cutoffs':[-2,-1,1,2],
                'note':'Descriptive legacy bands, not forecast thresholds; no TGA balance threshold existed in this version.'},
            'rows':rows}
