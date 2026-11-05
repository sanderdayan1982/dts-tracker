import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from argos_dts import fiscal_pulse, dts_summary, attach_dts_drivers, ntf_persistence, refund_total, yoy, PULSE_FIELDS
from institutional_core import business_day
import build_dts_nowcast as dts

class ArgosDtsTests(unittest.TestCase):
 now=dt.datetime(2026,11,5,20,tzinfo=dt.timezone.utc)
 def payload(self):
  return {'asof':'2026-11-03','generated_at':'2026-11-05T19:00:00Z','valid_until_utc':'2026-11-05T21:45:00Z',
          'dq':{'block':False,'stale':False},'mmt_liquidity':{'tga_close':938208,'tga_open':930757,'dtga':7451,'reserves_impact':-7451,'ntf_total':35925,'net_debt_cash_iiib':43376,'z_ntf_ex_exp_weekday_100bd':.8,'debt_headroom_iiic':753753,'slgs_open':True,'ntf_5d':100,'ntf_20d':-200,'ntf_60d':0},
          'fiscal_pulse_lag364':{k:v for k,v in zip(PULSE_FIELDS,[7.81,4.69,-2.3,.4,26.1,-8,27775,8])}}
 def test_exact_summary_mapping_and_signs(self):
  s=dts_summary(self.payload(),self.now)
  for k,v in {'tga_close':938208,'tga_open':930757,'dtga':7451,'net_debt_cash':43376,'calendar_z':.8,'debt_headroom':753753,'ntf_20d':-200,'ntf_60d':0}.items():self.assertEqual(s[k],v)
  self.assertEqual(s['slgs_status'],'OPEN');self.assertEqual(s['fiscal_pulse_lag364']['biz_refunds_today_musd'],-8)
 def test_expiry_blocks_fiscal_driver_without_erasing_fred_forecast(self):
  s=dts_summary(self.payload(),self.now+dt.timedelta(hours=2));c={'id':'nfp','forecast':{'point':50}}
  attach_dts_drivers([c],s);self.assertIsNone(c['dts_driver']);self.assertEqual(c['forecast']['point'],50)
  self.assertTrue(s['blocked']);self.assertIsNone(s['calendar_z']);self.assertTrue(all(s['fiscal_pulse_lag364'][k] is None for k in PULSE_FIELDS));self.assertEqual(s['slgs_status'],'UNKNOWN')
 def test_calendar_quality_and_unknown_slgs(self):
  p=self.payload();p['dq']['calendar_warmup']=True;p['mmt_liquidity']['slgs_open']=None
  s=dts_summary(p,self.now);self.assertIsNone(s['calendar_z']);self.assertEqual(s['slgs_status'],'UNKNOWN');self.assertEqual(s['tga_close'],938208)
 def test_four_driver_strings_match_published_values(self):
  s=dts_summary(self.payload(),self.now);cards=[{'id':x} for x in ('nfp','claims','retail','trade','cpi')];attach_dts_drivers(cards,s)
  self.assertEqual(cards[0]['dts_driver'],'Withheld 20d YoY (Lag 364): +7.8%')
  self.assertIn('+0.4%',cards[1]['dts_driver']);self.assertIn('+26.1%',cards[2]['dts_driver']);self.assertIn('$27.78B',cards[3]['dts_driver']);self.assertNotIn('dts_driver',cards[4])
 def test_complete_signed_ntf_windows(self):
  dates=[str(i) for i in range(60)];records={d:{'inputs_complete':True,'recon_diff':1,'ntf_total':-2} for d in dates}
  self.assertEqual(ntf_persistence(records,dates,60),-120);self.assertIsNone(ntf_persistence(records,dates[:4],5))
  records['59']['inputs_complete']=False;self.assertIsNone(ntf_persistence(records,dates,5))
 def test_refunds_require_both_channels_but_allow_zero_reversals(self):
  r={'indiv_eft_fytd':-2,'indiv_checks_fytd':0,'present':{'indiv_eft_fytd','indiv_checks_fytd'}}
  self.assertEqual(refund_total(r,'indiv','fytd'),-2);r['present'].remove('indiv_checks_fytd');self.assertIsNone(refund_total(r,'indiv','fytd'))
  self.assertEqual(yoy(-2,10),-120);self.assertIsNone(yoy(10,0))
 def test_aliases_stay_side_specific(self):
  for label in ('DHS - Customs Duties, Taxes, and Fees','DHS - Customs and Certain Excise Taxes'):
   self.assertIn('CUSTOMS_DUTIES',dts.match_canonical('Deposits',label,''));self.assertNotIn('CUSTOMS_DUTIES',dts.match_canonical('Withdrawals',label,''))
 def test_lag364_and_fytd_have_explicit_distinct_bases(self):
  day=dt.date(2025,1,1);dates=[]
  while day<=dt.date(2026,11,3):
   if business_day(day):dates.append(day.isoformat())
   day+=dt.timedelta(days=1)
  asof=dates[-1];anchor='2025-11-03'
  def value(side,cid,date,field):return 110 if date and date>='2026-01-01' else 100
  pulse=fiscal_pulse(dates,asof,anchor,value,{},False,['out_of_refund_season'])
  self.assertEqual(pulse['dol_benefits_20d_yoy_pct'],10);self.assertEqual(pulse['dol_benefits_fytd_yoy_pct'],10)
  self.assertEqual(pulse['basis']['fytd_anchor'],anchor);self.assertFalse(pulse['customs_20d_comparable']);self.assertIsNone(pulse['indiv_refunds_fytd_yoy_pct'])
if __name__=='__main__':unittest.main()
