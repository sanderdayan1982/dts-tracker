// Fiscal pulse panel: DTS cash vs the same session of the previous fiscal year.
const STATE_CLASS={better:'good',worse:'bad',pressure_up:'warn',pressure_down:'warn',stable:'flat',na:'flat',distorted:'flat'};
const COPY={
 es:{eyebrow:'PULSO FISCAL → ECONOMÍA',title:'¿La economía va mejor o peor que hace un año? Lo dice la caja del Tesoro',
  intro:'Cada indicador compara lo acumulado en el año fiscal (FYTD) con el mismo número de sesiones del año pasado. Verde: mejor que hace un año. Rojo: peor. Ámbar: más presión fiscal o sobre tipos. Gris: sin cambio relevante (menos de ±3 %). Los ingresos se comparan también descontando la inflación. Es una lectura de tendencia, no la cifra exacta del próximo dato.',
  compared:'Comparado con',sessions:'sesiones',cpi:'Inflación descontada (IPC interanual)',feeds:'Alimenta',fytd:'Año fiscal vs año pasado',real:'real',mtd:'Este mes vs año pasado',
  mtdWait:'aún no fiable ({n} sesiones)',legendCur:'Año fiscal actual',legendOld:'Año fiscal anterior',axis:'Variación de cada mes frente al mismo mes del año anterior',legendBars:'Barras: cada mes frente al mismo mes del año pasado ·',lgGood:'mejor',lgBad:'peor',lgWarn:'más presión',lgFlat:'sin cambio',
  verdict:{stronger:'Más fuerte que hace un año',weaker:'Más débil que hace un año',mixed:'Señales mixtas',pressure:'Más presión que hace un año',relief:'Menos presión que hace un año',neutral:'Sin cambio relevante'},
  na:'Sin datos todavía: se incorpora con la próxima descarga del DTS',blocked:'El pulso fiscal está caducado o no disponible: no usar como lectura vigente.',
  net:'Diferencia frente al año pasado',bn:'mil M USD',release:'Publica',prev:'Anterior',est:'Estimación',cons:'Consenso',session:'Sesión',
  macroTitle:'Datos que alimenta este bloque'},
 en:{eyebrow:'FISCAL PULSE → ECONOMY',title:'Is the economy running hotter or colder than a year ago? Treasury cash says',
  intro:'Each indicator compares the fiscal-year-to-date total with the same number of sessions last year. Green: better than a year ago. Red: worse. Amber: more fiscal or rate pressure. Grey: no material change (under ±3%). Income lines are also shown net of inflation. A trend reading, not the exact next release figure.',
  compared:'Compared with',sessions:'sessions',cpi:'Inflation removed (CPI y/y)',feeds:'Feeds',fytd:'Fiscal YTD vs last year',real:'real',mtd:'This month vs last year',
  mtdWait:'not reliable yet ({n} sessions)',legendCur:'Current fiscal year',legendOld:'Previous fiscal year',axis:'Each month versus the same month a year earlier',legendBars:'Bars: each month vs the same month last year ·',lgGood:'better',lgBad:'worse',lgWarn:'more pressure',lgFlat:'no change',
  verdict:{stronger:'Stronger than a year ago',weaker:'Weaker than a year ago',mixed:'Mixed signals',pressure:'More pressure than a year ago',relief:'Less pressure than a year ago',neutral:'No material change'},
  na:'No data yet: added with the next DTS download',blocked:'The fiscal pulse is expired or unavailable: do not use as a current reading.',
  net:'Difference vs last year',bn:'USD bn',release:'Release',prev:'Previous',est:'Estimate',cons:'Consensus',session:'Session',
  macroTitle:'Releases this block feeds'}};
const VERDICT_CLASS={stronger:'good',weaker:'bad',mixed:'warn',pressure:'warn',relief:'flat',neutral:'flat'};
const LINKS={labor:['nfp','unemployment','claims'],consumption:['retail'],trade:['trade'],growth:[],rates:[],fiscal:[]};

export function pulseExpired(p,now=Date.now()){const u=Date.parse(p?.valid_until_utc);return !p||p.status!=='OK'||!Number.isFinite(u)||now>=u;}

const BAR={good:'#3fbf95',bad:'#e57373',warn:'#d9a441',flat:'#5d6f86'};
function barState(x,v){
  if(!Number.isFinite(v))return 'flat';
  const stable=x.kind==='net'?25:3;if(Math.abs(v)<stable)return 'flat';
  if(x.good==='none')return v>0?'warn':'flat';
  return (v>0)===(x.good==='up')?'good':'bad';
}
function chart(x,lang){
  const data=(x.monthly||[]).filter(m=>!m.partial&&Number.isFinite(m.change)).slice(-12);if(data.length<2)return '';
  const W=320,H=118,L=30,R=6,T=10,B=18,n=data.length,max=Math.max(...data.map(m=>Math.abs(m.change)),x.kind==='net'?25:3);
  const bw=(W-L-R)/n,y0=T+(H-T-B)/2,sc=(H-T-B)/2/max,unit=x.kind==='net'?'':'%';
  const f=v=>new Intl.NumberFormat(lang==='es'?'es-ES':'en-US',{maximumFractionDigits:0}).format(v);
  const mon=k=>new Intl.DateTimeFormat(lang==='es'?'es-ES':'en-US',{month:'short',year:'2-digit',timeZone:'UTC'}).format(new Date(k+'-15T00:00:00Z'));
  const bars=data.map((m,i)=>{const h=Math.max(1,Math.abs(m.change)*sc),yy=m.change>=0?y0-h:y0;
    return `<rect x="${(L+i*bw+1).toFixed(1)}" y="${yy.toFixed(1)}" width="${(bw-2).toFixed(1)}" height="${h.toFixed(1)}" rx="2" fill="${BAR[barState(x,m.change)]}"><title>${mon(m.month)}: ${m.change>0?'+':''}${f(m.change)}${unit}</title></rect>`;}).join('');
  const last=data[n-1],ly=last.change>=0?y0-Math.abs(last.change)*sc-3:y0+Math.abs(last.change)*sc+9;
  return `<svg class="pulse-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${COPY[lang].axis}" data-pulse="${x.id}" data-months='${JSON.stringify(data.map(m=>[mon(m.month),m.change]))}' data-unit="${unit||(' '+COPY[lang].bn)}" data-l="${L}" data-r="${R}" data-w="${W}">
  <line x1="${L}" x2="${W-R}" y1="${y0}" y2="${y0}" stroke="var(--line)"/>
  <text x="2" y="${T+6}" fill="var(--muted)" font-size="9">+${f(max)}${unit}</text><text x="2" y="${y0+3}" fill="var(--muted)" font-size="9">0</text><text x="2" y="${H-B}" fill="var(--muted)" font-size="9">−${f(max)}${unit}</text>
  ${bars}<text x="${(L+(n-1)*bw+bw/2).toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="middle" fill="var(--text)" font-size="9" font-weight="600">${last.change>0?'+':''}${f(last.change)}${unit}</text>
  <text x="${L}" y="${H-4}" fill="var(--muted)" font-size="9">${mon(data[0].month)}</text><text x="${W-R}" y="${H-4}" text-anchor="end" fill="var(--muted)" font-size="9">${mon(last.month)}</text>
  <rect class="pulse-hit" x="${L}" y="${T}" width="${W-L-R}" height="${H-T-B}" fill="transparent"/></svg><div class="pulse-tip" id="tip-${x.id}" aria-live="polite"></div>`;
}

export function pulseHTML(pulse,cards,lang='es',now=Date.now()){
  const c=COPY[lang],e=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const nf=(v,d=1)=>Number.isFinite(v)?new Intl.NumberFormat(lang==='es'?'es-ES':'en-US',{maximumFractionDigits:d,minimumFractionDigits:d}).format(v):'—';
  const sg=(v,d=1)=>Number.isFinite(v)?(v>0?'+':v<0?'−':'')+nf(Math.abs(v),d):'—';
  if(!pulse)return '';
  const head=`<div class="pulse-head"><div><div class="eyebrow">${c.eyebrow}</div><h2>${c.title}</h2><p>${c.intro}</p></div>
  <div class="pulse-meta"><span>${c.compared}: <b>${e(pulse.compare_fytd_date??'—')}</b> · ${pulse.sessions_fytd??'—'} ${c.sessions}</span><span>${c.cpi}: <b>${sg(pulse.cpi_yoy_pct)} %</b> (${e(pulse.cpi_period??'—')})</span>
  <span class="pulse-legend">${c.legendBars} <i style="background:${BAR.good}"></i>${c.lgGood} <i style="background:${BAR.bad}"></i>${c.lgBad} <i style="background:${BAR.warn}"></i>${c.lgWarn} <i style="background:${BAR.flat}"></i>${c.lgFlat}</span></div></div>`;
  if(pulseExpired(pulse,now))return `<section class="pulse">${head}<div class="note">${c.blocked}</div></section>`;
  const byId=Object.fromEntries((cards||[]).map(x=>[x.id,x]));
  const blocks=Object.entries(pulse.themes||{}).map(([key,th])=>{
    const items=pulse.indicators.filter(x=>x.theme===key);const v=pulse.verdicts?.[key]??{};
    const links=(LINKS[key]||[]).map(id=>byId[id]).filter(Boolean).map(k=>`<div class="pulse-link"><b>${e(k._name??k.id)}</b><span>${c.prev} ${nf(k.last,2)}</span><span>${c.est} ${nf(k.forecast?.point,2)}</span><span>${c.cons} ${k.consensus?nf(k.consensus.value,2):'—'}</span><span>${c.release} ${e(k.release_date??'—')}</span></div>`).join('');
    const rows=items.map(x=>{
      const cls=STATE_CLASS[x.state]||'flat',net=x.kind==='net',f=x.fytd;
      const big=f.change==null?'—':net?`${sg(f.change,0)} ${c.bn}`:`${sg(f.change)} %`;
      const arrow=f.change==null?'':f.change>0?'▲':f.change<0?'▼':'■';
      const real=f.real_change!=null?`<span class="pulse-real">${c.real} ${sg(f.real_change)} %</span>`:'';
      const mtd=x.mtd.change!=null?(net?`${sg(x.mtd.change,0)} ${c.bn}`:`${sg(x.mtd.change)} %`):c.mtdWait.replace('{n}',x.mtd.sessions??'—');
      const fmt=v=>nf(v,0);
      return `<article class="pulse-item ${cls}" data-pulse-item="${e(x.id)}"><div class="pulse-top"><h4>${e(lang==='es'?x.es:x.en)}</h4><span class="pulse-big">${arrow} ${big}</span></div>
      ${f.change==null?`<p class="muted small">${c.na}</p>`:`<div class="pulse-sub"><span>${net?c.net:c.fytd}</span>${real}<span>${c.mtd}: ${mtd}</span></div>
      ${(x.base_effects||[]).map(b=>`<p class="pulse-base">⚠ ${e(lang==='es'?b.es:b.en)}</p>`).join('')}<p class="pulse-reading">${e(lang==='es'?x.reading_es:x.reading_en)}</p>${chart(x,lang)}`}
      <p class="pulse-note">${e(lang==='es'?x.note_es:x.note_en)}</p></article>`;}).join('');
    return `<div class="pulse-block"><div class="pulse-block-head"><div><h3>${e(lang==='es'?th.es:th.en)}</h3><span class="muted small">${c.feeds}: ${e(lang==='es'?th.feeds_es:th.feeds_en)}</span></div><span class="pulse-verdict ${VERDICT_CLASS[v.verdict]||'flat'}">${c.verdict[v.verdict]||'—'}</span></div>
    <p class="pulse-summary">${e(lang==='es'?v.summary_es:v.summary_en)}</p>
    ${links?`<div class="pulse-links"><span class="muted small">${c.macroTitle}</span>${links}</div>`:''}<div class="pulse-grid">${rows}</div></div>`;
  }).join('');
  return `<section class="pulse">${head}${blocks}</section>`;
}

export function attachPulseHover(root,getLang=()=>'es'){
  root.addEventListener('pointermove',ev=>{
    const svg=ev.target.closest?.('svg[data-pulse]');if(!svg)return;
    const lang=getLang(),data=JSON.parse(svg.dataset.months),L=+svg.dataset.l,R=+svg.dataset.r,W=+svg.dataset.w;
    const box=svg.getBoundingClientRect(),px=(ev.clientX-box.left)*W/box.width;
    const i=Math.max(0,Math.min(data.length-1,Math.floor((px-L)/((W-L-R)/data.length))));
    const tip=document.getElementById('tip-'+svg.dataset.pulse);const [m,v]=data[i];
    const f=new Intl.NumberFormat(lang==='es'?'es-ES':'en-US',{maximumFractionDigits:1}).format(v);
    if(tip)tip.textContent=`${m}: ${v>0?'+':''}${f}${svg.dataset.unit} ${lang==='es'?'frente al mismo mes del año pasado':'vs the same month last year'}`;
    svg.querySelectorAll('rect[rx]').forEach((r,j)=>r.setAttribute('opacity',j===i?'1':'0.55'));
  });
  root.addEventListener('pointerout',ev=>{const svg=ev.target.closest?.('svg[data-pulse]');if(svg&&!svg.contains(ev.relatedTarget))svg.querySelectorAll('rect[rx]').forEach(r=>r.setAttribute('opacity','1'));});
}
