import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from treasury_book import cash_row, build_book
class TreasuryBookTests(unittest.TestCase):
 def source(self):
  return dict(tga_close=120,tga_open=100,tga_open_mtd=90,tga_open_fytd=80,tga_dep_t1=30,tga_wd_t1=10,tga_dep_mtd_t1=70,tga_wd_mtd_t1=40,tga_dep_fytd_t1=100,tga_wd_fytd_t1=60)
 def test_official_cumulative_and_stock(self):
  r=cash_row('2026-11-03',self.source());self.assertEqual(r['fy'],2027);self.assertEqual(r['tga'],120)
  self.assertEqual(r['periods']['fytd']['D'],100);self.assertTrue(all(p['ok'] for p in r['periods'].values()))
 def test_negative_reversal_preserved(self):
  s=self.source();s.update(tga_dep_t1=-5,tga_wd_t1=-25)
  p=cash_row('2026-11-03',s)['periods']['today'];self.assertEqual(p['D'],-5);self.assertTrue(p['ok'])
 def test_missing_is_not_zero(self):
  s=self.source();s.pop('tga_dep_fytd_t1');p=cash_row('2026-11-03',s)['periods']['fytd'];self.assertIsNone(p['D']);self.assertIsNone(p['recon']);self.assertFalse(p['ok'])
 def test_reset_at_october_and_no_summing(self):
  self.assertEqual(cash_row('2026-09-30',self.source())['fy'],2026)
  self.assertEqual(cash_row('2026-10-01',self.source())['fy'],2027)
 def test_breakdown_zero_missing_distinct_and_threshold_provenance(self):
  d='2026-11-03';book=build_book({d:self.source()},{'Deposits':{'WITHHELD_FICA':{d:{'today':0,'present':{'today'}}}}},{},{},{'asof':d})
  r=book['rows'][0];self.assertEqual(r['components']['WITHHELD_FICA'],[0,None,None]);self.assertIsNone(r['periods']['today']['I']);self.assertIsNone(r['ntf']);self.assertEqual(book['legacy_thresholds']['bands'],[1,2])
 def test_cash_debt_totals_fallback_to_table_ii_not_truncated_sums(self):
  d='2026-11-03';t2={'Deposits':{'PUBLIC_DEBT_CASH_ISSUES_T2':{d:{'fytd':70,'present':{'fytd'}}}},'Withdrawals':{'PUBLIC_DEBT_CASH_REDEMP_T2':{d:{'fytd':50,'present':{'fytd'}}}}}
  r=build_book({d:self.source()},t2,{},{},{'asof':d})['rows'][0]['periods']['fytd']
  self.assertEqual(r['I'],70);self.assertEqual(r['R'],50);self.assertEqual(r['op_D'],30);self.assertEqual(r['op_W'],10)
if __name__=='__main__':unittest.main()
