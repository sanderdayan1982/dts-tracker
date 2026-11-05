import {treasuryHTML} from './treasury.mjs';
import {copy,targets,contextNames,contextNotes,unitNames} from './content.mjs';

export const numeric=x=>typeof x==='number'&&Number.isFinite(x);
export const escapeHTML=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function expired(payload,now=Date.now()){
  const until=Date.parse(payload?.valid_until_utc),created=Date.parse(payload?.generated_at);
  return !Number.isFinite(until)||!Number.isFinite(created)||now>=until||created>now+300000;
}
export function cashBlocked(data,now=Date.now()){
  const required=['ntf_total','dtga','reserves_impact','tga_close','net_debt_cash_iiib'];
  return !data||data.v!=='dts-g8-6.0'||data.dq?.block!==false||data.dq?.stale!==false||expired(data,now)
    ||!required.every(k=>numeric(data.mmt_liquidity?.[k]));
}
export function effectiveCard(card,radar,now=Date.now()){
  const result={...card};
  const sourceAt=Date.parse(card?.source_retrieved_at);
  if(!radar||expired(radar,now)||!Number.isFinite(sourceAt)||now-sourceAt>26*3600000){
    result.status='STALE';result.forecast=null;result.signal=null;result.direction_vs_previous=null;
  }
  if(result.status!=='RESEARCH_ESTIMATE'){result.forecast=null;result.signal=null;result.direction_vs_previous=null;}
  const f=result.forecast;
  if(f&&(!numeric(f.point)||!Array.isArray(f.range80)||f.range80.length!==2||!f.range80.every(numeric)||f.range80[0]>f.range80[1])){
    result.status='INVALID';result.forecast=null;result.signal=null;
  }
  return result;
}
export function slgsState(value){return value===true?'open':value===false?'closed':'unknown';}
export function localConsensus(entry,card,now=Date.now()){
  const captured=Date.parse(entry?.captured_at);
  // Local entry expires after 24h, at period change, or at the verified release date (conservative midnight UTC).
  const release=card.release_date?Date.parse(card.release_date+'T00:00:00Z'):Infinity;
  return entry&&numeric(entry.value)&&entry.reference_period===card.reference_period&&entry.unit===card.unit&&entry.source
    &&Number.isFinite(captured)&&captured<=now&&now-captured<86400000&&now<release?entry:null;
}

export function sharedConsensus(entry,card,now=Date.now()){
  const captured=Date.parse(entry?.captured_at),release=Date.parse(entry?.release_at);
  return entry&&numeric(entry.value)&&entry.reference_period===card.reference_period&&entry.unit===card.unit&&entry.source
    &&Number.isFinite(captured)&&Number.isFinite(release)&&captured<=now&&now<release&&now-captured<=7*86400000?entry:null;
}

export function fiscalDriverText(card,dts,lang='en',now=Date.now()){
  if(!['nfp','claims','retail','trade'].includes(card.id))return null;
  const ready=!cashBlocked(dts,now)&&card.dts_driver_asof===dts.asof&&Date.parse(card.dts_driver_expires)>now&&card.dts_driver_status==='AVAILABLE';
  return ready?(lang==='es'?card.dts_driver_es:card.dts_driver)??(lang==='es'?'DTS no disponible':'DTS unavailable'):(lang==='es'?'DTS no disponible / bloqueado':'DTS unavailable / blocked');
}

const RAW='https://raw.githubusercontent.com/sanderdayan1982/dts-tracker/main/data/';
const state={lang:'es',tab:'radar',filter:'all',days:60,data:null,radar:null,history:null,loading:true,error:false,consensus:{},edit:null,book:null,cashMode:'today',cashYear:null,cashDate:null,cashDays:90,cashDaily:false};
const $=id=>document.getElementById(id);
const t=key=>copy[state.lang][key]??key;
const e=escapeHTML;
const n=(v,d=2)=>numeric(v)?new Intl.NumberFormat(state.lang==='es'?'es-ES':'en-US',{maximumFractionDigits:d}).format(v):'—';
const signed=(v,d=2)=>numeric(v)?(v>0?'+':'')+n(v,d):'—';
const date=(v,withTime=false)=>{if(!v)return t('unverified');const d=new Date(v.length===10?v+'T12:00:00Z':v);return Number.isNaN(d.getTime())?t('unverified'):new Intl.DateTimeFormat(state.lang==='es'?'es-ES':'en-US',{dateStyle:'medium',...(withTime?{timeStyle:'short'}:{})}).format(d);};
const pill=(label,cls='')=>`<span class="pill ${cls}">${e(label)}</span>`;
const sourceLink=(id,label=t('source'))=>`<a href="https://fred.stlouisfed.org/series/${encodeURIComponent(id)}" target="_blank" rel="noopener">${e(label)} ↗</a>`;
const signal=key=>({STRONGER:'stronger',WEAKER:'weaker',HOTTER:'hotter',COOLER:'cooler',SIMILAR:'similar'}[key]??'unavailable');
const unit=c=>unitNames[state.lang][c.unit]??c.unit??'';
function cards(){return(state.radar?.cards??Object.keys(targets).map(id=>({id,status:'UNAVAILABLE',group:['cpi','core_cpi','core_pce'].includes(id)?'inflation':['nfp','claims','unemployment'].includes(id)?'labor':'growth'}))).map(c=>effectiveCard(c,state.radar));}

async function fetchFile(name){
  const urls=location.hostname==='127.0.0.1'||location.hostname==='localhost'?[`data/${name}`]:[RAW+name,`data/${name}`];
  const results=await Promise.allSettled(urls.map(async url=>{
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),12000);
    try{const r=await fetch(url+'?t='+Date.now(),{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error(r.status);const data=await r.json();if(!data||typeof data!=='object')throw Error('invalid');return data;}finally{clearTimeout(timer);}
  }));
  const valid=results.filter(r=>r.status==='fulfilled').map(r=>r.value);
  if(!valid.length)throw Error(name);
  valid.sort((a,b)=>Date.parse(b.last_fetch_attempt_utc??b.generated_at??'1970-01-01')-Date.parse(a.last_fetch_attempt_utc??a.generated_at??'1970-01-01'));
  return valid[0];
}
async function load(){
  state.loading=true;render();
  const r=await Promise.allSettled(['dts_nowcast.json','macro_radar.json','dts_history_400d.json','treasury_book.json'].map(fetchFile));
  ['data','radar','history','book'].forEach((key,i)=>{if(r[i].status==='fulfilled')state[key]=r[i].value;else state[key]=null;});
  state.error=r.some(x=>x.status==='rejected');state.loading=false;render();
}
function spark(rows,color='var(--blue)'){
  const vs=(rows??[]).map(r=>r.value).filter(numeric);if(vs.length<2)return '';
  const lo=Math.min(...vs),hi=Math.max(...vs),span=hi-lo||1;
  const points=vs.map((v,i)=>`${(i*300/(vs.length-1)).toFixed(2)},${(42-(v-lo)/span*38).toFixed(2)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 300 48" preserveAspectRatio="none" role="img" aria-label="${e(t('seriesHistory'))}"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.7" vector-effect="non-scaling-stroke"/></svg>`;
}
function renderHeader(){
  document.documentElement.lang=state.lang;
  for(const[id,key]of [['brandTitle','brand'],['brandSub','subtitle'],['eyebrow','eyebrow'],['pageTitle','title'],['pageIntro','intro'],['contract','contract'],['refreshText','refresh'],['footerText','footer'],['argosLink','argos'],['docsLink','docs']])$(id).textContent=t(key);
  $('langEn').setAttribute('aria-pressed',String(state.lang==='en'));$('langEs').setAttribute('aria-pressed',String(state.lang==='es'));
  $('nav').innerHTML=['radar','fiscal','liquidity','guide'].map(key=>`<button data-tab="${key}" class="${state.tab===key?'active':''}" aria-pressed="${state.tab===key}">${e(t(key))}</button>`).join('');
  const blocked=cashBlocked(state.data),available=cards().filter(c=>c.forecast).length;
  const msg=state.loading?t('loading'):state.error?t('failed'):`${t('cashSource')}: ${blocked?t('expired'):t('fresh')} · ${t('asof')} ${state.data?.asof??'—'}`;
  $('status').className='statusbar'+(blocked||state.error?' warn':'');
  $('status').innerHTML=`<span><span class="dot"></span>${e(msg)}</span><span>${e(t('updated'))}: ${e(date(state.radar?.generated_at??state.data?.generated_at,true))}</span>`;
  const m=state.data?.mmt_liquidity??{};
  const zOk=!blocked&&!state.data?.dq?.calendar_miss&&!state.data?.dq?.calendar_warmup;
  const metrics=[['cash',blocked?'—':signed(m.ntf_total/1000),t('billion')+' · '+t('cashSub')],['reserve',blocked?'—':signed(m.reserves_impact/1000),t('billion')+' · '+t('reserveSub')],['z',zOk?signed(m.z_ntf_ex_exp_weekday_100bd):'—',t('zSub')],['coverage',`${available} / 10`,t('coverageSub')]];
  $('kpis').innerHTML=metrics.map(([key,value,sub])=>`<article class="kpi"><div class="label">${e(t(key))}</div><div class="value">${e(value)}</div><div class="sub">${e(sub)}</div></article>`).join('');
}
function consensusFor(c){return localConsensus(state.consensus[c.id],c)??sharedConsensus(c.consensus,c)??null;}
function cardHTML(c){
  const desc=targets[c.id]?.[state.lang]??[c.id,'',''];const f=c.forecast;const con=consensusFor(c);
  const cls=c.signal==='HOTTER'?'hot':c.signal==='WEAKER'?'weak':'';
  const validation=f?.validation;
  const fiscalLine=fiscalDriverText(c,state.data,state.lang);
  let fiscalEvidence='';
  if(c.id==='nfp'&&!cashBlocked(state.data)){
    const w=state.data?.nowcast_cards?.nfp_wage_bill;
    fiscalEvidence=`<p>${e(t('nominal'))}: <strong>${signed(w?.withheld_t2_20d_norm_yoy)}%</strong> · 20 ${e(t('days'))}. ${e(t('nominalText'))}</p>`;
  }
  let gap='';
  if(con&&f){const diff=f.point-con.value;const within=con.value>=f.range80[0]&&con.value<=f.range80[1];gap=`<p><strong>${e(t('gap'))}: ${signed(diff)}</strong><br>${e(t(within?'gapSmall':'gapLarge'))}</p>`;}
  return `<article class="card" data-card="${e(c.id)}"><div class="card-top"><div><h3>${e(desc[0])}</h3><div class="meta">${e(c.agency??'')} · ${e(c.reference_period??'—')}</div></div>${pill(t(f?'research':'blocked'),f?'amber':'red')}</div>
  <div class="reading ${cls}">${e(t(signal(c.signal)))}</div><div class="numbers"><div><div class="label">${e(t('previous'))}</div><div class="big">${n(c.last)}</div></div><div><div class="label">${e(t('estimate'))}</div><div class="big estimate">${n(f?.point)}</div></div></div><div class="unit">${e(unit(c))}</div>
  ${fiscalLine?`<p class="unit" data-dts-driver="${e(c.id)}">DTS · ${e(fiscalLine)}${c.dts_driver_asof?' · '+e(c.dts_driver_asof):''}</p>`:''}
  <div class="range">${e(t('range'))}<strong>${f?n(f.range80[0])+' → '+n(f.range80[1]):'—'}</strong></div>
  ${spark(c.history)}<p class="explain">${e(desc[1])}</p><div class="consensus"><span>${e(t('consensus'))}<br><strong>${con?n(con.value):e(t('missingConsensus'))}</strong></span><button class="linkbutton" data-consensus="${e(c.id)}">${e(t('enter'))}</button></div>${gap}
  <details><summary>${e(t('evidence'))}</summary><p>${e(desc[2])}</p>${fiscalEvidence}
  ${f?`<p>${e(t('method'))}: ${e(t(f.method))}.<br>${e(t('mae'))}: <strong>${n(validation?.mae)}</strong> ${e(unit(c))}.<br>${e(t('holdout'))}: ${n(validation?.holdout_n,0)}.<br>${e(t('improvement'))}: ${n(validation?.improvement_pct,1)}%.</p><p>${e(t(validation?.beats_baseline?'hasEdge':'noEdge'))}</p><p>${e(t('rangeNote'))}</p>`:`<p>${e(t('notReady'))} · ${e(statusText(c.status))}</p>`}
  <p>${e(t('revised'))}</p><p>${e(t('probability'))}</p><p>${e(t('observed'))}: ${e(c.observed_period??'—')}<br>${e(t('lastUpdated'))}: ${e(date(c.source_retrieved_at,true))}</p></details>
  <div class="card-footer"><span>${e(t('release'))}: ${e(date(c.release_date))}</span>${c.series_id?sourceLink(c.series_id):''}</div></article>`;
}
function statusText(status){return t(({OK:'fresh',RESEARCH_ESTIMATE:'research',DATA_GAP:'missing',FETCH_FAIL:'fetchFail',STALE:'stale',INSUFFICIENT_HISTORY:'notReady',UNAVAILABLE:'missing'})[status]??'blocked');}
function radarHTML(){
  const cs=cards(),today=new Date().toISOString().slice(0,10),end=new Date(Date.now()+7*86400000).toISOString().slice(0,10);
  const upcoming=cs.filter(c=>c.release_date&&c.release_date>=today).sort((a,b)=>a.release_date.localeCompare(b.release_date));
  const next=upcoming[0];const f=next?.forecast;
  const spotlight=next?`<section class="spotlight"><div><div class="eyebrow">${e(t('upcoming'))} · ${e(date(next.release_date))}</div><h2>${e(targets[next.id][state.lang][0])}</h2><p>${e(t(signal(next.signal)))} · ${e(t('target'))}: ${e(next.reference_period??'—')}</p><p>${e(t('missingCalendar'))} ${sourceLink(next.series_id,t('calendarSource'))}</p></div><div class="focus-values"><div><small>${e(t('previous'))}</small><strong>${n(next.last)}</strong></div><div><small>${e(t('estimate'))}</small><strong style="color:var(--teal)">${n(f?.point)}</strong></div></div></section>`:`<section class="spotlight"><div><div class="eyebrow">${e(t('radar'))}</div><h2>${e(t('noUpcoming'))}</h2><p>${e(t('noUpcomingText'))}</p></div></section>`;
  const filtered=cs.filter(c=>state.filter==='all'||state.filter===c.group||(state.filter==='week'&&c.release_date>=today&&c.release_date<=end));
  return `<div class="section-head"><div><h2>${e(t('radarTitle'))}</h2><p>${e(t('radarSub'))}</p></div><div class="filters">${['all','labor','inflation','growth','week'].map(g=>`<button data-filter="${g}" aria-pressed="${state.filter===g}">${e(t(g))}</button>`).join('')}</div></div>${spotlight}<div class="grid">${filtered.map(cardHTML).join('')}</div>${!filtered.length?`<div class="empty">${e(t('noneWeek'))}</div>`:''}<div class="note">${e(t('contract'))}</div>`;
}
function lineChart(rows,key,color='var(--teal)'){
  const valid=rows.filter(r=>numeric(r[key]));if(valid.length<2)return `<div class="empty">${e(t('noData'))}</div>`;
  const vals=valid.map(r=>r[key]/1000),lo=Math.min(0,...vals),hi=Math.max(0,...vals),span=hi-lo||1;
  const y=v=>210-(v-lo)/span*180;
  const pts=vals.map((v,i)=>`${55+i/(vals.length-1)*720},${y(v)}`).join(' ');
  return `<svg class="chart" viewBox="0 0 800 250" role="img" aria-label="${e(t(key==='tga'?'tga':'cash'))}"><line x1="55" x2="775" y1="${y(0)}" y2="${y(0)}" stroke="var(--line)"/><text x="3" y="35">${n(hi,0)}</text><text x="3" y="211">${n(lo,0)}</text><text x="55" y="240">${e(valid[0].d)}</text><text x="775" y="240" text-anchor="end">${e(valid.at(-1).d)}</text><polyline points="${pts}" stroke="${color}" fill="none" stroke-width="2"/></svg>`;
}
function cashHTML(){
  const d=state.data??{},m=d.mmt_liquidity??{},dq=d.dq??{},rows=(state.history?.series??[]).slice(-state.days);
  const fields=[['tga',m.tga_close],['total',m.ntf_total],['debt',m.net_debt_cash_iiib],['reserve',m.reserves_impact],['expected',m.ntf_expected_cal],['residual',m.ntf_ex_expected],['headroom',m.debt_headroom_iiic]];
  const w=d.nowcast_cards?.nfp_wage_bill??{},ref=d.nowcast_cards?.retail_household??{},corp=d.nowcast_cards?.corp_and_tariffs??{};
  return `<div class="section-head"><div><h2>${e(t('cashTitle'))}</h2><p>${e(t('cashIntro'))}</p></div><div class="filters">${[20,60,400].map(v=>`<button data-days="${v}" aria-pressed="${state.days===v}">${v} ${e(t('days'))}</button>`).join('')}</div></div>${cashBlocked(d)?`<div class="note">${e(t('cashBlocked'))}</div>`:''}
  <div class="two-col"><div><div class="panel"><h3>${e(t('cash'))}</h3><p>${e(t('billion'))} · ${e(t('asof'))} ${e(d.asof??'—')}</p>${lineChart(rows,'ntf')}<div class="legend"><span><i></i>${e(t('total'))}</span></div></div><div class="panel"><h3>${e(t('tga'))}</h3>${lineChart(rows,'tga','var(--blue)')}</div></div><div><div class="panel"><h3>${e(t('quality'))}</h3><table class="data-table"><tbody>${fields.map(([k,v])=>`<tr><td>${e(t(k))}</td><td class="numeric">${n(v,0)}</td></tr>`).join('')}<tr><td>${e(t('slgs'))}</td><td class="numeric">${e(t(slgsState(m.slgs_open)))}</td></tr></tbody></table><p>${e(t('million'))}</p><p>${e(t('recon'))}: ${dq.recon_ok===true?'✓':'—'} · ${n(dq.recon_diff_musd,0)} / ${n(dq.recon_op_diff_musd,0)} M</p><p>${e(t('calendar'))}: ${e(dq.calendar_miss||dq.calendar_warmup?t('calendarUnknown'):t('obsOnly'))}</p><p>${e(t('fiscalExplain'))}</p></div><div class="panel"><h3>${e(t('calendar'))}</h3><p>${e(t('calendarText'))}</p><p>Z = ${n(m.z_ntf_ex_exp_weekday_100bd)} · n = ${n(m.z_sample_n,0)}</p><p>${m.z_fallback_used?e(t('baseline')):'100 '+e(t('days'))} · ${e(t('probability'))}</p></div></div></div>
  <div class="grid"><article class="card"><h3>${e(t('nominal'))}</h3><div class="numbers"><div><div class="label">20 ${e(t('days'))} · YoY</div><div class="big">${signed(w.withheld_t2_20d_norm_yoy)}%</div></div><div><div class="label">${e(t('fiscalFY'))}</div><div class="big">${signed(w.withheld_t2_fytd_per_bd_yoy)}%</div></div></div><p class="explain">${e(t('nominalText'))}</p>${pill(t('dormant'),'amber')}</article><article class="card"><h3>${e(targets.retail[state.lang][0])} · DTS</h3><div class="numbers"><div><div class="label">${e(t('fiscalFY'))}</div><div class="big">${n(ref.indiv_refunds_fytd_musd,0)}</div><div class="unit">${e(t('million'))}</div></div></div><p class="explain">${e(targets.retail[state.lang][2])}</p>${pill(t('dormant'),'amber')}</article><article class="card"><h3>${e(targets.trade[state.lang][0])} · DTS</h3><div class="numbers"><div><div class="label">${e(t('fiscalFY'))}</div><div class="big">${n(corp.customs_fytd_musd,0)}</div><div class="unit">${e(t('million'))}</div></div></div><p class="explain">${e(t('customsText'))}</p>${pill(t('dormant'),'amber')}</article></div>
  <div class="panel" style="margin-top:22px"><div class="section-head"><h3>${e(t('history'))}</h3><button data-download="history">${e(t('download'))}</button></div><div class="table-scroll"><table class="data-table"><thead><tr><th>${e(t('date'))}</th>${['flow','deltaTga','reserve','debt'].map(x=>`<th class="numeric">${e(t(x))}</th>`).join('')}</tr></thead><tbody>${[...rows].reverse().map(r=>`<tr><td>${e(r.d)}</td>${['ntf','dtga','res_imp','debt_iiib'].map(k=>`<td class="numeric">${signed(r[k],0)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p>${e(t('million'))}</p></div>`;
}
function liquidityHTML(){
  return `<div class="section-head"><div><h2>${e(t('reserveTitle'))}</h2><p>${e(t('reserveIntro'))}</p></div></div><div class="grid">${(state.radar?.context??[]).map(c=>{
    const valid=c.status==='OK'&&!expired(state.radar);
    return `<article class="card"><div class="card-top"><h3>${e(contextNames[state.lang][c.id]??c.id)}</h3>${pill(t(valid?'dormant':'blocked'),valid?'':'red')}</div><div class="numbers"><div><div class="big">${n(c.value)}</div><div class="unit">${e(unit(c))}</div></div><div><div class="label">${e(t('contextChange'))}</div><div class="big">${valid?signed(c.change):'—'}</div></div></div>${spark(c.history)}<p class="explain">${e(contextNotes[state.lang][c.id]??'')}</p><div class="card-footer"><span>${e(c.observed_at??'—')} · ${e(t(c.frequency==='daily'?'daily':'weeks'))}</span>${sourceLink(c.series_id)}</div></article>`;
  }).join('')}</div><div class="note">${e(t('bondNote'))}</div><div class="guide-grid"><div class="panel"><h3>${e(t('gdpTitle'))}</h3><p>${e(t('gdpText'))}</p></div><div class="panel"><h3>${e(t('adpTitle'))}</h3><p>${e(t('adpText'))}</p></div></div>`;
}
function guideHTML(){
  const panels=[['legendTitle','legendText'],['unitsTitle','unitsText'],['methodTitle','methodText'],['fiscalTitle','fiscalText'],['maturity','maturityText'],['gdpTitle','gdpText']];
  return `<div class="section-head"><div><h2>${e(t('guideTitle'))}</h2><p>${e(t('guideIntro'))}</p></div></div><div class="panel steps">${[1,2,3,4].map(i=>`<div class="step">${e(t('step'+i))}</div>`).join('')}</div><div class="guide-grid">${panels.map(([title,body])=>`<article class="panel"><h3>${e(t(title))}</h3><p>${e(t(body))}</p></article>`).join('')}</div><div class="panel" style="margin-top:20px"><h3>${e(t('feedHealth'))}</h3><div class="table-scroll"><table class="data-table"><thead><tr><th>${e(t('dataOrigin'))}</th><th>${e(t('observed'))}</th><th>${e(t('sourceState'))}</th></tr></thead><tbody>${cards().map(c=>`<tr><td>${e(targets[c.id][state.lang][0])}</td><td>${e(c.observed_period??'—')}</td><td>${e(statusText(c.status))}</td></tr>`).join('')}</tbody></table></div><ul class="source-list"><li><a href="https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/" target="_blank" rel="noopener">Treasury · Daily Treasury Statement</a></li><li><a href="https://fred.stlouisfed.org/" target="_blank" rel="noopener">Federal Reserve Bank of St. Louis · FRED</a></li><li><a href="https://www.bls.gov/schedule/" target="_blank" rel="noopener">BLS · ${e(t('calendarSource'))}</a></li><li><a href="https://www.bea.gov/news/schedule" target="_blank" rel="noopener">BEA · ${e(t('calendarSource'))}</a></li></ul></div>`;
}
function render(){
  if(typeof document==='undefined')return;
  const openDetails=[...document.querySelectorAll('[data-card] details[open]')].map(el=>el.closest('[data-card]').dataset.card);
  const cashDetails=[...document.querySelectorAll('#treasury details')].map(el=>[el.id,el.open]);
  const cashScroll=new Map([...document.querySelectorAll('#treasury [data-scroll-id]')].map(el=>[el.dataset.scrollId,el.scrollLeft]));
  renderHeader();$('treasury').innerHTML=treasuryHTML(state.book,state.data,{lang:state.lang,mode:state.cashMode,year:state.cashYear,cutoff:state.cashDate,days:state.cashDays,dailyBars:state.cashDaily,ntfWidth:Math.max(300,$('treasury').clientWidth-46)});
  for(const [id,open] of cashDetails){const el=document.getElementById(id);if(el)el.open=open;}
  for(const el of document.querySelectorAll('#treasury [data-scroll-id]'))el.scrollLeft=cashScroll.get(el.dataset.scrollId)??Math.max(0,el.scrollWidth-el.clientWidth);
  $('view').innerHTML=({radar:radarHTML,fiscal:cashHTML,liquidity:liquidityHTML,guide:guideHTML}[state.tab])();
  for(const id of openDetails)document.querySelector(`[data-card="${id}"] details`)?.setAttribute('open','');
}
function saveLocal(){try{localStorage.setItem('dts-v6-consensus',JSON.stringify(state.consensus));}catch{}}
function editConsensus(id){
  const c=cards().find(x=>x.id===id);if(!c)return;state.edit=c;
  for(const[id,key]of [['dialogTitle','consensusTitle'],['dialogHelp','consensusHelp'],['valueLabel','value'],['sourceLabel','provider'],['saveConsensus','save'],['cancelConsensus','cancel'],['removeConsensus','remove']])$(id).textContent=t(key);
  $('dialogTarget').textContent=`${targets[c.id][state.lang][0]} · ${c.reference_period??'—'} · ${unit(c)}`;
  const con=consensusFor(c);$('consensusValue').value=con?.value??'';$('consensusSource').value=con?.source??'';$('dialogError').textContent='';
  $('consensusDialog').showModal();
}
function download(value,name){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);}
function init(){
  try{state.lang=localStorage.getItem('dts-v6-language')??'es';if(!copy[state.lang])state.lang='es';state.consensus=JSON.parse(localStorage.getItem('dts-v6-consensus')??'{}');}catch{}
  for(const lang of ['en','es'])$('lang'+(lang==='en'?'En':'Es')).addEventListener('click',()=>{state.lang=lang;try{localStorage.setItem('dts-v6-language',lang);}catch{}render();});
  $('refresh').addEventListener('click',load);
  let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(render,150);});
  document.addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b)return;if(b.dataset.tab){state.tab=b.dataset.tab;render();}if(b.dataset.filter){state.filter=b.dataset.filter;render();}if(b.dataset.days){state.days=Number(b.dataset.days);render();}if(b.dataset.consensus)editConsensus(b.dataset.consensus);if(b.dataset.cashMode){state.cashMode=b.dataset.cashMode;state.cashDaily=false;if(state.cashMode==='fytd')state.cashDays='fy';render();}if(b.dataset.cashDaily){state.cashDaily=b.dataset.cashDaily==='yes';render();}if(b.dataset.download==='treasury')download(state.book,'treasury-cash-ledger.json');if(b.dataset.download==='history')download(state.history,'dts-history.json');});
  document.addEventListener('change',ev=>{if(ev.target.id==='cashYear'){state.cashYear=Number(ev.target.value);state.cashDate=null;render();}if(ev.target.id==='cashDate'){state.cashDate=ev.target.value;render();}if(ev.target.id==='cashWindow'){state.cashDays=ev.target.value;render();}});
  const inspectBar=ev=>{const bar=ev.target.closest('[data-cash-bar]');if(bar){const box=document.getElementById('readout-'+bar.dataset.chartId);if(box)box.textContent=bar.dataset.cashBar;}};
  document.addEventListener('click',inspectBar);document.addEventListener('focusin',inspectBar);
  $('cancelConsensus').onclick=()=>$('consensusDialog').close();$('removeConsensus').onclick=()=>{delete state.consensus[state.edit.id];saveLocal();$('consensusDialog').close();render();};
  $('consensusForm').onsubmit=ev=>{ev.preventDefault();const value=Number($('consensusValue').value),source=$('consensusSource').value.trim();if(!numeric(value)||!source||!$('consensusValue').value){$('dialogError').textContent=t('consensusError');return;}const c=state.edit;state.consensus[c.id]={value,source,unit:c.unit,reference_period:c.reference_period,captured_at:new Date().toISOString()};saveLocal();$('consensusDialog').close();render();};
  setInterval(()=>{if(!document.hidden&&!$('consensusDialog').open)render();},30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)render();});
  setInterval(()=>{if(!document.hidden&&!state.loading)load();},300000);
  load();
}
if(typeof document!=='undefined')init();
