import test from 'node:test';
import assert from 'node:assert/strict';
import {expired,cashBlocked,effectiveCard,slgsState,localConsensus,escapeHTML} from '../assets/app.mjs';
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
