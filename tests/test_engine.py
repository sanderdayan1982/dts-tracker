import datetime as dt
import json
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from institutional_core import business_day, settlement, lag364_stats, cash_contract, radar_valid_until
from build_macro_radar import parse_csv, estimate, transform, verified_consensus, make_card, SERIES
import build_dts_nowcast as dts

class AccountingTests(unittest.TestCase):
    def test_uploaded_accounting(self):
        rows=json.loads((Path(__file__).resolve().parents[1]/"data/dts_history_400d.json").read_text())["series"]
        self.assertEqual(len(rows),len({r['d'] for r in rows}))
        for r in rows:
            self.assertEqual(r['ntf'],(r['W']-r['R'])-(r['D']-r['I']))
            self.assertLessEqual(abs(r['dtga']-(r['D']-r['W'])),1)
    def dates(self):
        dates=[];day=dt.date(2025,1,1)
        while day<=dt.date(2026,11,3):
            if business_day(day):dates.append(day.isoformat())
            day+=dt.timedelta(days=1)
        return dates
    def test_real_time_boundary(self):
        outputs=[]
        for cutoff in ('2026-10-30','2026-11-03'):
            subset=[d for d in self.dates() if d<=cutoff]
            outputs.append(dts.build_asymmetric_calendar_schedule(subset,lambda *args:1000.)[4]['2026-10-30'])
        self.assertEqual(outputs[0],outputs[1]);self.assertIn('SSI_DAY1',outputs[0])
    def test_missing_date_not_holiday(self):
        self.assertIsNone(settlement(dt.date(2026,11,3),{'2026-11-02','2026-11-04'},'2026-11-02','2026-11-04'))
    def test_distinct_calendars(self):
        self.assertFalse(business_day(dt.date(2026,7,3),'federal'))
        self.assertTrue(business_day(dt.date(2026,7,3),'reserve_bank'))
    def test_publication_weekend_and_dst(self):
        f=dts.expected_latest_bd_and_validity
        for stamp,expected in [('2026-11-07T23:00:00+00:00','2026-11-05'),('2026-11-05T22:00:00+00:00','2026-11-04'),('2026-11-11T23:00:00+00:00','2026-11-09')]:
            self.assertEqual(f(dt.datetime.fromisoformat(stamp))[0],expected)
    def test_zero_and_reversals(self):
        self.assertEqual(dts.parse_num('-8'),-8);self.assertEqual(dts.parse_num('0'),0)
        self.assertIsNone(dts.parse_num('null'))
    def test_partial_comparison_blocked(self):
        dates=self.dates();flow={d:10. for d in dates}
        for d in dates[-10:]:flow[(dt.date.fromisoformat(d)-dt.timedelta(days=364)).isoformat()]=None
        self.assertIsNone(lag364_stats(flow,dates,len(dates)-1,20)[0])
    def test_expiry_blocks_all_signals(self):
        p={'generated_at':'2026-11-05T16:00:00Z','valid_until_utc':'2026-11-05T21:45:00Z','dq':{'block':False,'stale':False},'mmt_liquidity':{'funding_state':'SURPRISE_INJECTION'},'nowcast_cards':{'x':{'state':'BULLISH_BIAS','dir':1}}}
        r=cash_contract(p,dt.datetime(2026,11,5,22,tzinfo=dt.timezone.utc))
        self.assertTrue(r['dq']['block']);self.assertIsNone(r['nowcast_cards']['x']['dir'])
        self.assertEqual(r['mmt_liquidity']['funding_state'],'BLOCKED')
    def test_unknown_expiry_blocks(self):
        self.assertTrue(cash_contract({'dq':{'block':False,'stale':False}})['dq']['block'])

class ForecastTests(unittest.TestCase):
    now=dt.datetime(2026,11,5,18,tzinfo=dt.timezone.utc)
    def test_csv_rejects_bad_schema_and_duplicate(self):
        for raw in ['foo,bar\n1,2','observation_date,PAYEMS\n2026-09-01,1\n2026-09-01,2']:
            with self.assertRaises(ValueError):parse_csv(raw,'PAYEMS',self.now)
    def test_csv_missing_and_future(self):
        rows=parse_csv('observation_date,PAYEMS\n2026-09-01,0\n2026-10-01,.\n2027-01-01,9','PAYEMS',self.now)
        self.assertEqual(rows,[{'date':'2026-09-01','value':0.}])
    def test_units(self):
        rows=[{'date':'2026-08-01','value':100},{'date':'2026-09-01','value':102}]
        self.assertEqual(transform(rows,SERIES['nfp'])[-1]['value'],2)
        self.assertAlmostEqual(transform(rows,SERIES['cpi'])[-1]['value'],2)
        self.assertAlmostEqual(transform(rows,SERIES['claims'])[-1]['value'],.102)
    def test_consensus_contract(self):
        c={'nfp':{'value':100,'reference_period':'2026-10','unit':'thousand_jobs','source':'test','captured_at':'2026-11-05T12:00:00Z','release_at':'2026-11-06T13:30:00Z'}}
        self.assertIsNotNone(verified_consensus(c,'nfp','2026-10','thousand_jobs',self.now))
        self.assertIsNone(verified_consensus(c,'nfp','2026-09','thousand_jobs',self.now))
        self.assertIsNone(verified_consensus(c,'nfp','2026-10','percent',self.now))
    def test_holdout_not_probability(self):
        r=estimate([100+math.sin(i/3) for i in range(180)],'level')
        self.assertEqual(r['validation']['holdout_n'],30)
        self.assertFalse(r['validation']['first_release_verified'])
        self.assertIsNone(r['probability_above_consensus'])
        self.assertTrue(all(math.isfinite(x) for x in r['range80']))
    def test_insufficient_history(self):self.assertIsNone(estimate([1,2,3],'level'))
    def test_gap_is_not_multimonth_inflation(self):
        rows=[{'date':'2025-09-01','value':100},{'date':'2025-11-01','value':110},{'date':'2025-12-01','value':111}]
        out=transform(rows,SERIES['cpi'])
        self.assertIsNone(out[0]['value'])
        self.assertAlmostEqual(out[1]['value'],100*(111/110-1))
    def test_old_hole_skipped_current_hole_blocks(self):
        values=[100+math.sin(i/4) for i in range(180)]
        values[100]=None
        self.assertIsNotNone(estimate(values,'level'))
        values[-1]=None
        self.assertIsNone(estimate(values,'level'))
    def test_failed_feed(self):
        src={'status':'FETCH_FAIL','retrieved_at':'2026-11-05T17:00:00Z','observations':[{'date':'2026-09-01','value':4.2}]}
        self.assertIsNone(make_card('unemployment',SERIES['unemployment'],src,self.now,{})['forecast'])

class ValidityAndEdgeTests(unittest.TestCase):
    def test_weekend_and_holiday_validity(self):
        u=dt.timezone.utc
        cases={dt.datetime(2026,11,6,21,15,tzinfo=u):dt.datetime(2026,11,9,23,15,tzinfo=u),   # Friday -> Monday
               dt.datetime(2026,11,4,23,15,tzinfo=u):dt.datetime(2026,11,6,1,15,tzinfo=u),    # midweek unchanged
               dt.datetime(2026,11,10,23,15,tzinfo=u):dt.datetime(2026,11,13,1,15,tzinfo=u)}  # Veterans Day
        for now,expected in cases.items():self.assertEqual(radar_valid_until(now),expected)
    def test_business_day_failure_still_expires(self):
        now=dt.datetime(2026,11,3,13,45,tzinfo=dt.timezone.utc)
        self.assertEqual(radar_valid_until(now)-now,dt.timedelta(hours=26))
    def test_ar1_failing_holdout_is_demoted(self):
        # Smooth start lets AR1 win selection; a noisy holdout makes it lose to persistence.
        import random
        random.seed(3)
        values=[100+10*math.sin(i/6) for i in range(150)]+[100+random.choice((-1,1))*8 for _ in range(30)]
        r=estimate(values,'level')
        self.assertIn(r['edge'],('NONE','DEMONSTRATED'))
        if r['selected_on_training']=='ar1' and not r['validation']['ar1_holdout_mae']<r['validation']['baseline_mae']:
            self.assertTrue(r['demoted_on_holdout']);self.assertEqual(r['method'],'baseline')
        if r['edge']=='DEMONSTRATED':self.assertEqual(r['method'],'ar1')
    def test_baseline_never_claims_edge(self):
        r=estimate([5.0]*180,'level')
        self.assertEqual(r['method'],'baseline');self.assertEqual(r['edge'],'NONE')

if __name__=='__main__':unittest.main()
