import test from 'node:test';
import assert from 'node:assert/strict';
import {expired,cashBlocked,effectiveCard,slgsState,localConsensus,sharedConsensus,escapeHTML,hasEdge,briefLines,bridgeState} from '../assets/app.mjs';
import {copy,targets,contextNames,contextNotes,unitNames} from '../assets/content.mjs';
const now=Date.parse('2026-11-05T18:00:00Z');
const fresh={generated_at:'2026-11-05T17:00:00Z',valid_until_utc:'2026-11-05T21:45:00Z'};
test('missing or expired timestamp blocks rather than implying neutral',()=>{
  assert.equal(expired({},now),true);assert.equal(expired(fresh,now),false);
  assert.equal(expired(fresh,Date.parse(fresh.valid_until_utc)),true);
  const mmt={ntf_total:0,dtga:0,reserves_impact:0,tga_close:100,net_debt_cash_iiib:0};
  assert.equal(cashBlocked({...fresh,v:'dts-g8-6.0',dq:{block:false,stale:false},mmt_liquidity:mmt},now),false);
  assert.equal(cashBlocked({...fresh,v:'dts-g8-6.0',dq:{block:false,stale:false},mmt_liquidity:{...mmt,ntf_total:null}},now),true);
  assert.equal(cashBlocked({...fresh,dq:{block:false}},now),true);
});
test('expired radar cannot retain a positive signal',()=>{
  const c={status:'RESEARCH_ESTIMATE',source_retrieved_at:fresh.generated_at,signal:'STRONGER',direction_vs_previous:1,forecast:{point:20,range80:[10,30]}};
  const r=effectiveCard(c,fresh,Date.parse(fresh.valid_until_utc));
  assert.equal(r.signal,null);assert.equal(r.forecast,null);assert.equal(r.status,'STALE');
  assert.equal(effectiveCard(c,fresh,now).forecast.point,20);
});
test('unknown SLGS remains unknown',()=>{
  assert.equal(slgsState(null),'unknown');assert.equal(slgsState(false),'closed');assert.equal(slgsState(true),'open');
});
test('consensus expires and cannot cross a reference period',()=>{
  const c={reference_period:'2026-10',unit:'thousand_jobs',release_date:'2026-11-06'};
  const v={value:100,source:'desk',captured_at:'2026-11-05T15:00:00Z',reference_period:'2026-10',unit:'thousand_jobs'};
  assert.ok(localConsensus(v,c,now));
  assert.equal(localConsensus(v,{...c,reference_period:'2026-11'},now),null);
  assert.equal(localConsensus(v,c,Date.parse('2026-11-06T00:00:00Z')),null);
});
test('both languages have complete dictionaries',()=>{
  for(const dict of [copy,contextNames,contextNotes,unitNames])assert.deepEqual(Object.keys(dict.en).sort(),Object.keys(dict.es).sort());
  for(const value of Object.values(targets)){assert.equal(value.en.length,3);assert.equal(value.es.length,3);}
});
test('untrusted labels are escaped',()=>{assert.equal(escapeHTML('<script>"x"</script>'),'&lt;script&gt;&quot;x&quot;&lt;/script&gt;');});

test('shared consensus expires at its release time',()=>{
  const c={reference_period:'2026-10',unit:'thousand_jobs'};
  const v={...c,value:100,source:'desk',captured_at:'2026-11-05T15:00:00Z',release_at:'2026-11-06T13:30:00Z'};
  assert.ok(sharedConsensus(v,c,now));
  assert.equal(sharedConsensus(v,c,Date.parse(v.release_at)),null);
  assert.equal(sharedConsensus(v,{...c,unit:'percent'},now),null);
});

import {legacyBands,legacyZone,selectCashRows,fiscalYear,monitorFresh,treasuryCopy} from '../assets/treasury.mjs';
test('restored legacy bands retain inclusive 30-session population formula',()=>{
 const rows=Array.from({length:31},(_,i)=>({ntf:i+1}));const out=legacyBands(rows);
 assert.equal(out[28].mean,null);assert.equal(out[29].mean,15.5);assert.equal(out[30].mean,16.5);
 assert.ok(Math.abs(out[29].sd-Math.sqrt(899/12))<1e-10);
 assert.equal(legacyBands([...rows.slice(0,29),{ntf:null}])[29].mean,null);
});
test('legacy threshold boundaries are unchanged',()=>{
 assert.equal(legacyZone(2),'strongIn');assert.equal(legacyZone(1),'notableIn');assert.equal(legacyZone(-.999),'inline');assert.equal(legacyZone(-1),'notableOut');assert.equal(legacyZone(-2),'strongOut');assert.equal(legacyZone(null),'missing');
});
test('fiscal-year and as-of selection never cross into another year',()=>{
 const book={rows:[{d:'2026-09-30',fy:2026,ntf:1},{d:'2026-10-01',fy:2027,ntf:2},{d:'2026-10-02',fy:2027,ntf:3}]};
 const s=selectCashRows(book,{year:2027,cutoff:'2026-10-01',days:'fy'});assert.equal(s.rows.length,1);assert.equal(s.last.ntf,2);assert.equal(fiscalYear('2026-09-30'),2026);
});
test('Treasury monitor rejects stale or mismatched snapshots',()=>{
 const book={...fresh,schema:'treasury-book-1.0',asof:'2026-11-03'};assert.ok(monitorFresh(book,{asof:book.asof,dq:{block:false}},now));assert.equal(monitorFresh(book,{asof:'2026-11-04',dq:{block:false}},now),false);
 assert.deepEqual(Object.keys(treasuryCopy.en).sort(),Object.keys(treasuryCopy.es).sort());
});

import {windowTotals,comparableFiscal} from '../assets/cash-desk.mjs';
test('cash-desk windows preserve the reserve/financing identity and require coverage',()=>{
 const rows=Array.from({length:20},()=>({ntf:4,tga:103,periods:{today:{ok:true,open:100,I:10,R:3,net:3}}}));
 assert.deepEqual(windowTotals(rows,5),{ntf:20,reserves:-15,debt:35});
 assert.equal(windowTotals(rows,60),null);rows[19].periods.today.ok=false;assert.equal(windowTotals(rows,5),null);
});
test('partial first fiscal year cannot masquerade as a full prior-year comparator',()=>{
 const row=(d,fy)=>({d,fy,periods:{fytd:{ok:true,D:20,W:30}}});
 assert.equal(comparableFiscal({rows:[row('2025-11-01',2026),row('2026-10-01',2027)]},2027,'2026-10-01'),null);
 const c=comparableFiscal({rows:[row('2025-10-01',2026),row('2026-10-01',2027)]},2027,'2026-10-01');assert.equal(c.sessions,1);
});

import {fiscalDriverText} from '../assets/app.mjs';
import {treasuryHTML} from '../assets/treasury.mjs';
test('DTS radar line is bilingual, coherent and expires independently of FRED',()=>{
 const d={...fresh,v:'dts-g8-6.0',asof:'2026-11-03',dq:{block:false,stale:false},mmt_liquidity:{ntf_total:1,dtga:1,reserves_impact:-1,tga_close:100,net_debt_cash_iiib:2}};
 const c={id:'nfp',dts_driver:'Withheld: +7.8%',dts_driver_es:'Retenciones: +7,8%',dts_driver_asof:d.asof,dts_driver_expires:fresh.valid_until_utc,dts_driver_status:'AVAILABLE'};
 assert.equal(fiscalDriverText(c,d,'en',now),'Withheld: +7.8%');assert.equal(fiscalDriverText(c,d,'es',now),'Retenciones: +7,8%');
 assert.match(fiscalDriverText(c,d,'en',Date.parse(fresh.valid_until_utc)),/blocked/);
 assert.match(fiscalDriverText({...c,dts_driver_asof:'2026-11-02'},d,'en',now),/blocked/);
 assert.equal(fiscalDriverText({id:'cpi'},d,'en',now),null);
});
test('daily net flow chart fills the available panel width',()=>{
 const p={open:100,D:20,W:10,net:10,recon:0,ok:true,I:5,R:2,op_D:15,op_W:8};
 const book={...fresh,schema:'treasury-book-1.0',asof:'2026-11-03',rows:[{d:'2026-11-03',fy:2027,tga:110,ntf:-7,z:0,periods:{today:p,mtd:p,fytd:p},components:{}}],components:[]};
 const html=treasuryHTML(book,{asof:book.asof,dq:{block:false}},{ntfWidth:1174});
 assert.match(html,/viewBox="0 0 1174 220"/);assert.match(html,/viewBox="0 0 300 220"/);
});

test('no-edge estimates are never presented as an edge',()=>{
  assert.equal(hasEdge({forecast:{edge:'NONE',validation:{beats_baseline:true}}}),false);
  assert.equal(hasEdge({forecast:{edge:'DEMONSTRATED'}}),true);
  assert.equal(hasEdge({forecast:{validation:{beats_baseline:true}}}),true);
  assert.equal(hasEdge({forecast:null}),false);
});
test('radar source age is judged against its own run, not wall-clock',()=>{
  const radar={generated_at:'2026-11-06T21:15:00Z',valid_until_utc:'2026-11-09T23:15:00Z'};
  const c={status:'RESEARCH_ESTIMATE',source_retrieved_at:'2026-11-06T21:14:00Z',signal:'SIMILAR',forecast:{point:1,range80:[0,2]}};
  assert.equal(effectiveCard(c,radar,Date.parse('2026-11-08T12:00:00Z')).status,'RESEARCH_ESTIMATE');
  assert.equal(effectiveCard(c,radar,Date.parse('2026-11-09T23:15:00Z')).status,'STALE');
});
test('desk reading follows the cash contract and both languages',()=>{
  const mmt={ntf_total:13329,dtga:-13496,reserves_impact:13496,tga_close:922752,net_debt_cash_iiib:-167,z_ntf_ex_exp_weekday_100bd:.56};
  const data={...fresh,asof:'2026-11-05',v:'dts-g8-6.0',dq:{block:false,stale:false},mmt_liquidity:mmt};
  const cs=[{id:'cpi',release_date:'2026-11-10',forecast:{point:.37,edge:'NONE'}},{id:'retail',release_date:'2026-11-17',forecast:{point:.45,edge:'DEMONSTRATED'}}];
  for(const lang of ['en','es']){
    const lines=briefLines(data,cs,lang,now);
    assert.ok(lines.every(l=>!/\{\w+\}/.test(l.text)),'no unfilled placeholders');
    assert.match(lines[0].text,/13[.,]5/);assert.equal(lines[0].tone,'teal');
    assert.match(lines.at(-2).text,/2026-11-10/);
  }
  const blocked=briefLines({...data,dq:{block:true}},cs,'es',now);
  assert.equal(blocked[0].tone,'red');assert.equal(blocked.length,3);
});

test('DTS bridge is shown only with a live forecast and a valid state',()=>{
  const b={status:'PRELIMINARY',edge:'NONE',point:138.6,dts_contribution:-3.6};
  assert.equal(bridgeState({forecast:{point:1},dts_bridge:b}),b);
  assert.equal(bridgeState({forecast:null,dts_bridge:b}),null);
  assert.equal(bridgeState({forecast:{point:1},dts_bridge:{status:'UNAVAILABLE',edge:'NONE'}}),null);
  const mmt={ntf_total:1,dtga:-1,reserves_impact:1,tga_close:1,net_debt_cash_iiib:0,z_ntf_ex_exp_weekday_100bd:0};
  const data={...fresh,asof:'2026-11-05',v:'dts-g8-6.0',dq:{block:false,stale:false},mmt_liquidity:mmt};
  for(const lang of ['en','es']){
    const lines=briefLines(data,[{id:'nfp',release_date:'2026-12-04',forecast:{point:1,edge:'NONE'},dts_bridge:b}],lang,now);
    assert.ok(lines.some(l=>/0/.test(l.text)&&/DTS/.test(l.text)));
    assert.ok(lines.every(l=>!/\{\w+\}/.test(l.text)));
  }
});

test('desk reading shows the automatic consensus of the next release',()=>{
  const mmt={ntf_total:1,dtga:-1,reserves_impact:1,tga_close:1,net_debt_cash_iiib:0,z_ntf_ex_exp_weekday_100bd:0};
  const data={...fresh,asof:'2026-11-05',v:'dts-g8-6.0',dq:{block:false,stale:false},mmt_liquidity:mmt};
  const con={value:.3,reference_period:'2026-10',unit:'percent_mom',source:'ForexFactory via G8 RadarNews',captured_at:'2026-11-05T12:00:00Z',release_at:'2026-11-10T13:30:00Z'};
  const card={id:'cpi',release_date:'2026-11-10',reference_period:'2026-10',unit:'percent_mom',forecast:{point:.37,edge:'NONE'},consensus:con};
  const es=briefLines(data,[card],'es',now).find(l=>/CPI/.test(l.text));
  assert.match(es.text,/Consenso 0,3 frente a estimación 0,37/);
  const en=briefLines(data,[card],'en',now).find(l=>/CPI/.test(l.text));
  assert.match(en.text,/Consensus 0.3 vs estimate 0.37/);
});
