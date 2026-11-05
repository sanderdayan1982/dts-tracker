const ok=v=>typeof v==='number'&&Number.isFinite(v);
const text={
 es:{title:'Lectura de caja para trading',waterfall:'Cómo ha cambiado el TGA',opening:'Saldo inicial',deposits:'Entradas',withdrawals:'Salidas',closing:'Saldo final',unit:'Miles de millones de USD',funding:'¿De dónde entra y hacia dónde sale?',issues:'Entradas por emisiones de deuda',receipts:'Otras entradas de caja',redemptions:'Salidas por amortizaciones',spending:'Otras salidas de caja',fundingNote:'El volumen bruto puede estar dominado por refinanciación. Las otras entradas no son solo impuestos; las otras salidas no equivalen al déficit presupuestario.',rolling:'Persistencia de los flujos',rollingNote:'Acumulados de las últimas 5, 20 y 60 observaciones diarias hasta el corte, aunque crucen el año fiscal. No son previsiones.',ntf:'Caja neta sin deuda',reserves:'Contribución TGA a reservas',debt:'Financiación neta con deuda',sessions:'sesiones',heat:'Días de entrada y salida de reservas por TGA',heatNote:'Últimas 60 observaciones. Verde: cae el TGA; rojo: sube. La intensidad representa el tamaño del movimiento. Los demás factores de reservas de la Fed se mantienen constantes.',compare:'Comparación con el año fiscal anterior',compareNote:'Acumulados oficiales hasta el mismo número de sesiones publicadas desde el inicio fiscal. Comparación nominal: no elimina cambios de impuestos, inflación ni desfases de calendario.',unavailable:'Sin datos completos comparables',prior:'Año anterior',current:'Año seleccionado',headroom:'Margen frente al límite de deuda',debtNote:'El margen legal no es el saldo de caja ni el margen efectivo después de medidas extraordinarias. No es una cuenta atrás hasta un impago.',totalDebt:'Deuda pública total',publicDebt:'Deuda en manos del público',inspect:'Selecciona una fecha en el monitor superior para reconstruir estos gráficos.',invalid:'Datos incompletos: no se calcula',billion:'mil millones USD'},
 en:{title:'Cash-flow reading for traders',waterfall:'What changed the TGA',opening:'Opening balance',deposits:'Money in',withdrawals:'Money out',closing:'Closing balance',unit:'USD billions',funding:'Where money comes from and goes',issues:'Debt issuance receipts',receipts:'Other cash receipts',redemptions:'Debt redemption payments',spending:'Other cash payments',fundingNote:'Gross turnover may be dominated by refinancing. Other receipts are not just taxes; other payments do not equal the budget deficit.',rolling:'Flow persistence',rollingNote:'Totals over the last 5, 20 and 60 daily observations through the cutoff, including across fiscal years. These are not forecasts.',ntf:'Net non-debt cash',reserves:'TGA reserve contribution',debt:'Net cash borrowing',sessions:'sessions',heat:'Daily TGA contributions to reserves',heatNote:'Last 60 observations. Green: TGA falls; red: TGA rises. Intensity reflects size. All other Fed reserve factors held constant.',compare:'Comparison with the previous fiscal year',compareNote:'Official cumulative totals at the same number of reported sessions since the fiscal-year start. Nominal comparison: does not remove tax changes, inflation or calendar timing.',unavailable:'No complete comparable data',prior:'Previous year',current:'Selected year',headroom:'Statutory debt-limit headroom',debtNote:'Legal headroom is neither the cash balance nor effective headroom after extraordinary measures. It is not a countdown to default.',totalDebt:'Total public debt',publicDebt:'Debt held by the public',inspect:'Choose a date in the monitor above to reconstruct these charts.',invalid:'Incomplete data: not calculated',billion:'USD billion'}
};
export function windowTotals(rows,count){
 const span=rows.slice(-count);if(span.length<count)return null;
 const sums={ntf:0,reserves:0,debt:0};
 for(const r of span){const p=r.periods?.today;if(!p?.ok||![r.ntf,p.I,p.R,r.tga,p.open].every(ok))return null;sums.ntf+=r.ntf;sums.reserves-=r.tga-p.open;sums.debt+=p.I-p.R;}
 return sums;
}
export function comparableFiscal(book,year,cutoff){
 const cur=book.rows.filter(r=>r.fy===year&&r.d<=cutoff),prior=book.rows.filter(r=>r.fy===year-1);
 // A partial first fiscal year in the retrieval window must never become a full-year comparison.
 if(!cur.length||!prior.length||cur[0].d>(year-1)+'-10-03'||prior[0].d>(year-2)+'-10-03'||prior.length<cur.length)return null;
 const a=cur.at(-1),b=prior[cur.length-1];
 if(!a.periods.fytd.ok||!b.periods.fytd.ok)return null;
 return {current:a,prior:b,sessions:cur.length};
}
export function cashDeskHTML(book,selection,mode,lang){
 const t=text[lang]??text.es,n=(v,d=2)=>ok(v)?new Intl.NumberFormat(lang==='en'?'en-US':'es-ES',{maximumFractionDigits:d}).format(v):'—',b=v=>ok(v)?n(v/1000):'—';
 const r=selection.last,p=r.periods[mode],all=book.rows.filter(x=>x.d<=r.d),comparison=comparableFiscal(book,selection.year,r.d);
 const svg=(body,label=t.waterfall,height=200)=>`<svg class="desk-svg" viewBox="0 0 520 ${height}" role="img" aria-label="${label}">${body}</svg>`;
 const txt=(x,y,label,anchor='start')=>`<text x="${x}" y="${y}" text-anchor="${anchor}">${label}</text>`;
 let waterfall=`<p>${t.invalid}</p>`;
 if([p.open,p.D,p.W,r.tga].every(ok)){
 const edges=[[0,p.open],[p.open,p.open+p.D],[p.open+p.D,p.open+p.D-p.W],[0,r.tga]],v=edges.flat(),lo=Math.min(0,...v),hi=Math.max(0,...v),scale=150/(hi-lo||1),y=v=>175-(v-lo)*scale;
 waterfall=svg(edges.map(([from,to],i)=>{const x=22+i*128;return `<rect x="${x}" y="${Math.min(y(from),y(to))}" width="90" height="${Math.max(1,Math.abs(y(to)-y(from)))}" fill="${['#f3c476','#64d8c1','#ff9b9b','#7ab8ff'][i]}"/><title>${[t.opening,t.deposits,t.withdrawals,t.closing][i]}: ${b([p.open,p.D,p.W,r.tga][i])}</title>${txt(x+45,Math.min(y(from),y(to))-6,b([p.open,p.D,p.W,r.tga][i]),'middle')}${txt(x+45,197,[t.opening,t.deposits,t.withdrawals,t.closing][i],'middle')}`;}).join(''));
 }
 const financing=[[t.issues,p.I,'#7ab8ff'],[t.receipts,p.op_D,'#64d8c1'],[t.redemptions,p.R,'#b48af5'],[t.spending,p.op_W,'#ff9b9b']];
 const maxFin=Math.max(1,...financing.map(x=>ok(x[1])?Math.abs(x[1]):0));
 const funding=svg(financing.map(([label,v,color],i)=>`${txt(8,18+i*48,label)}<line x1="250" x2="250" y1="${23+i*48}" y2="${40+i*48}" stroke="#94a3b8"/><rect x="${ok(v)&&v<0?250+v/maxFin*210:250}" y="${25+i*48}" width="${ok(v)?Math.abs(v)/maxFin*210:0}" height="13" fill="${color}"/>${txt(508,36+i*48,b(v),'end')}`).join(''),t.funding,215);
 const rolling=[5,20,60].map(count=>({count,totals:windowTotals(all,count)}));const maxRoll=Math.max(1,...rolling.flatMap(x=>Object.values(x.totals??{}).map(Math.abs)));
 const rollingSvg=svg(rolling.map((row,i)=>[t.ntf,t.reserves,t.debt].map((label,j)=>{const v=row.totals?.[['ntf','reserves','debt'][j]],yy=22+i*82+j*22;return `${j===0?txt(2,yy-5,row.count+' '+t.sessions):''}<line x1="310" x2="310" y1="${yy}" y2="${yy+14}" stroke="#94a3b8"/><rect x="${ok(v)&&v<0?310+v/maxRoll*115:310}" y="${yy}" width="${ok(v)?Math.abs(v)/maxRoll*115:0}" height="12" fill="${['#64d8c1','#7ab8ff','#f3c476'][j]}"/>${txt(85,yy+11,label)}${txt(515,yy+11,b(v),'end')}`;}).join('')).join(''),t.rolling,275);
 const heatRows=all.slice(-60),maxHeat=Math.max(1,...heatRows.map(x=>Math.abs((x.tga??0)-(x.periods.today.open??0))));
 const heat=svg(heatRows.map((x,i)=>{const p=x.periods.today,v=p.ok&&ok(x.tga)&&ok(p.open)?-(x.tga-p.open):null,xx=5+(i%10)*51,yy=10+Math.floor(i/10)*44;return `<g><title>${x.d}: ${b(v)} ${t.unit}</title><rect x="${xx}" y="${yy}" width="46" height="37" rx="4" fill="${!ok(v)?'#263a50':v>=0?'#64d8c1':'#ff9b9b'}" fill-opacity="${ok(v)?.2+.8*Math.abs(v)/maxHeat:.4}"/>${txt(xx+23,yy+14,x.d.slice(5),'middle')}${txt(xx+23,yy+29,b(v),'middle')}</g>`;}).join(''),t.heat,280);
 let compare=`<p>${t.unavailable}</p>`;
 if(comparison){const a=comparison.current,bRow=comparison.prior,max=Math.max(1,a.periods.fytd.D,a.periods.fytd.W,bRow.periods.fytd.D,bRow.periods.fytd.W);compare=svg(['D','W'].map((key,i)=>[bRow,a].map((row,j)=>{const v=row.periods.fytd[key],yy=25+i*95+j*34;return `${txt(5,yy-6,(i===0?t.deposits:t.withdrawals)+' · FY '+row.fy)}<rect x="5" y="${yy}" width="${v/max*390}" height="15" fill="${j===0?'#7ab8ff':'#64d8c1'}"/>${txt(512,yy+13,b(v),'end')}`;}).join('')).join(''),t.compare,210)+`<p>${comparison.sessions} ${t.sessions} · ${a.d} / ${bRow.d}</p>`;}
 let headroom='';const debt=r.debt??{};const hr=selection.rows.filter(x=>ok(x.debt?.headroom)),maxH=Math.max(1,...hr.map(x=>Math.abs(x.debt.headroom)));
 if(hr.length){const base=hr.some(x=>x.debt.headroom<0)?100:160,amp=base===100?75:140;headroom=svg(hr.map((x,i)=>{const v=x.debt.headroom,step=490/hr.length,hh=Math.abs(v)/maxH*amp;return `<rect x="${15+i*step}" y="${v>=0?base-hh:base}" width="${Math.max(.5,step-1)}" height="${hh}" fill="${v>=0?'#7ab8ff':'#ff9b9b'}"><title>${x.d}: ${b(v)} ${t.unit}</title></rect>`;}).join('')+txt(15,195,hr[0].d)+txt(505,195,hr.at(-1).d,'end'),t.headroom);}
 return `<details id="cashTradingDesk" class="panel" open><summary>${t.title}</summary><p>${t.inspect}</p><div class="guide-grid">
 <article class="panel"><h3>${t.waterfall}</h3><p>${t.unit}</p>${waterfall}</article>
 <article class="panel"><h3>${t.funding}</h3><p>${t.unit}</p>${funding}<p>${t.fundingNote}</p></article>
 <article class="panel"><h3>${t.rolling}</h3><p>${t.unit}</p>${rollingSvg}<p>${t.rollingNote}</p></article>
 <article class="panel"><h3>${t.heat}</h3><p>${t.unit}</p>${heat}<p>${t.heatNote}</p></article>
 <article class="panel"><h3>${t.compare}</h3><p>${t.unit}</p>${compare}<p>${t.compareNote}</p></article>
 <article class="panel"><h3>${t.headroom}</h3><div class="cash-value">${b(debt.headroom)}</div><p>${t.unit}</p>${headroom}<p>${t.totalDebt}: ${b(debt.total)} · ${t.publicDebt}: ${b(debt.public)}</p><p>${t.debtNote}</p></article>
 </div></details>`;
}
