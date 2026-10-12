const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let models = [], selected = null, chartMode = 'forecast', history = [], historyKey = '', refreshTimer;
let token = sessionStorage.getItem('predictor-token') || '';
const fmt = (value, digits=2) => value == null ? '—' : Number(value).toLocaleString('sv-SE', {maximumFractionDigits:digits});
const date = (value, includeYear=false) => value ? new Date(value).toLocaleString('sv-SE', {timeZone:current()?.config.timezone || 'Europe/Stockholm', year:includeYear?'numeric':undefined,month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
const current = () => models.find(m => m.id === selected);
const stepMinutes = c => ({minute:1,hour:60,day:1440,week:10080}[c.resolution]||c.period_minutes||60);
const periodName = c => {const minutes=stepMinutes(c);return minutes%10080===0?`${minutes/10080} ${minutes===10080?'vecka':'veckor'}`:minutes%1440===0?`${minutes/1440} dygn`:minutes%60===0?`${minutes/60} ${minutes===60?'timme':'timmar'}`:`${minutes} ${minutes===1?'minut':'minuter'}`;};
const aggregateName = s => ({mean:'medelvärde',last:'senaste värde',sum:'summa',change:'mätarökning'}[s.statistic]||'medelvärde');
function updatePeriodPreview(){
  const form=$('model-form'),c={resolution:form.elements.resolution.value,period_minutes:Number(form.elements.period_minutes.value)},h=Number(form.elements.horizon.value);
  $('custom-period-field').hidden=c.resolution!=='custom';
  const signal=window.flowEditor?.graph?.nodes.find(n=>n.kind==='output')?.signal;
  $('period-preview').textContent=`Varje träningsvärde och prognosvärde avser ${periodName(c)}${signal?' · '+aggregateName(signal):''}. ${h} framtida perioder = ${periodName({resolution:'custom',period_minutes:stepMinutes(c)*h})}. Veckor börjar måndag 00:00 UTC. Fasta intervall; kalendermånader och kalenderår stöds inte ännu.`;
}

function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(refreshTimer); refreshTimer = setTimeout(() => $('toast').hidden = true, 5000);
}

async function api(path, options={}) {
  const headers = {...options.headers};
  if (token) headers.Authorization = 'Bearer ' + token;
  if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const response = await fetch(new URL('api/' + path, document.baseURI), {...options, headers});
  const body = await response.json();
  if (response.status === 401) {
    if (!$('auth-dialog').open) $('auth-dialog').showModal();
    throw new Error('Appens åtkomstnyckel behövs');
  }
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map(x => x.msg).join(' · ') : body.detail;
    throw new Error(detail || 'Åtgärden misslyckades');
  }
  return body;
}

async function refresh() {
  try {
    models = await api('models');
    if (selected && !models.some(m => m.id === selected)) selected = null;
    renderList();
    const item = current();
    const nextKey = item ? JSON.stringify([item.id, item.data]) : '';
    if (item && nextKey !== historyKey) {
      history = await api(`models/${item.id}/history`); historyKey = nextKey;
    }
    renderDetail();
  } catch (error) {
    if (!$('auth-dialog').open) toast(error.message);
  }
}

function renderList() {
  $('model-count').textContent = models.length;
  $('model-list').innerHTML = models.map(m => `<button class="model-item ${m.id === selected ? 'selected' : ''}" data-model="${m.id}">${esc(m.config.name)}<small>${m.config.source === 'demo' ? 'SYNTETISK DEMO · ' : ''}${esc(periodName(m.config))} per värde · ${m.config.horizon} perioder${m.status === 'running' ? ' · arbetar' : ''}</small></button>`).join('');
  $('model-list').querySelectorAll('[data-model]').forEach(button => button.onclick = async () => {
    selected = button.dataset.model; historyKey = ''; chartMode = 'forecast'; await refresh();
  });
}

function renderDetail() {
  const item = current();
  if (window.flowEditor) window.flowEditor.show(item);
  $('welcome').hidden = !!item || !!window.flowEditor?.isDraft;
  $('detail').hidden = !item || (window.flowEditor && window.flowEditor.mode !== 'results');
  if (!item) return;
  const c = item.config, m = item.metrics, f = item.forecast, busy = item.status === 'running';
  $('model-source').textContent = c.source === 'demo' ? 'SYNTETISK DEMO · INTE VERKLIGA MÄTVÄRDEN' : c.source === 'ha' ? 'HOME ASSISTANT · EGEN MODELLINSTANS' : 'CSV · EGEN MODELLINSTANS';
  $('model-name').textContent = c.name;
  $('model-subtitle').textContent = `${periodName(c)} per värde · ${aggregateName(c.target)} · ${c.horizon} framtida perioder · ${c.inputs.length} ${c.inputs.length===1?'input':'inputs'} · ${c.auto_update ? 'automatisk uppdatering' : 'manuell uppdatering'}`;
  $('model-error').hidden = !item.error; $('model-error').textContent = item.error || '';
  $('baseline-warning').hidden = !m || m.beats_baseline;
  const validPoints = (f?.points || []).filter(p => new Date(p.end) > new Date());
  const next = validPoints[0];
  $('next-value').textContent = next ? `${fmt(next.value)} ${c.unit}` : '—';
  $('next-date').textContent = next ? `${date(next.start)} → ${date(next.end)}` : f ? 'Prognosen har passerat. Uppdatera den.' : 'Ingen prognos ännu';
  $('model-mae').textContent = m ? `${fmt(m.mae, 3)} ${c.unit}` : '—';
  $('baseline-mae').textContent = m ? `${fmt(m.baseline_mae, 3)} ${c.unit}` : '—';
  $('baseline-name').textContent = m ? (m.baseline === 'senaste_värde' ? 'Samma värde som senaste mätningen' : 'Samma tid förra veckan · annars senaste värdet') : 'Senaste värdet / samma tid förra veckan';
  $('sample-count').textContent = fmt(item.data.n, 0);
  $('sample-range').textContent = item.data.n ? `${date(item.data.first,true)} – ${date(item.data.last,true)}` : 'Inga mätvärden ännu';
  $('sync').hidden = c.source !== 'ha'; $('csv-label').hidden = c.source !== 'csv';
  $('publish').hidden = c.source === 'demo';
  for (const id of ['sync','train','forecast','publish']) $(id).disabled = busy;
  $('train').disabled = busy || !item.data.n;
  $('forecast').disabled = busy || !m;
  $('publish').disabled = busy || !f;
  $('csv').disabled = busy;
  $('job-status').innerHTML = busy ? '<span class="spinner"></span>Modellen arbetar…' : item.trained_at ? 'Tränad ' + esc(date(item.trained_at)) : 'Inte tränad ännu';
  const importance = m?.importance || {};
  const row = (label,value) => `<div class="signal-row"><span>${esc(label)}</span><span>${esc(value)}</span></div>`;
  $('signals').innerHTML = `<div class="signal-row"><span>${esc(c.target.key)}</span><span class="tag">MÅL · ${esc(c.unit || 'utan enhet')}</span></div>` + c.inputs.map(s => row(s.key, importance[s.key] != null ? `${fmt(importance[s.key]*100,0)} % av modellens vikt` : s.entity_id || 'CSV-kolumn')).join('') + row('Kalender', c.calendar.map(k => ({hour:'klockslag',weekday:'veckodag',week:'vecka',year_day:'årstid'}[k])).join(', ') || 'Av') + row('Tidigare målvärden',c.use_target_history ? 'Ingår' : 'Ingår inte');
  const qr = (label,value) => `<div class="quality-row"><span>${esc(label)}</span><span>${esc(value)}</span></div>`;
  $('quality').innerHTML = m ? qr('Träningsperioder',fmt(m.training_rows,0)) + qr('Testperioder',fmt(m.test_rows,0)) + qr('Mot jämförelseprognosen',m.improvement_percent == null ? 'Ingen procentsiffra' : `${fmt(m.improvement_percent,1)} % ${m.improvement_percent >= 0 ? 'lägre fel' : '(högre fel)'}`) + qr('Fördröjningar', c.lags.join(', ') + ' perioder') + qr('Historiktest börjar',date(m.test_first_origin)) : '<p class="fine">Kvaliteten visas när modellen har tränats och testats.</p>';
  $('tab-forecast').classList.toggle('active',chartMode === 'forecast'); $('tab-test').classList.toggle('active',chartMode === 'test');
  $('baseline-legend').hidden = chartMode !== 'test';
  $('chart-description').textContent = chartMode === 'test' ? 'Senare historik som inte användes vid träning · en period framåt' : f ? `Prognos från ${date(f.origin)}. Bandet visar historisk felstorlek.` : 'Hämta historik och träna modellen för att börja.';
  $('interval-note').textContent = chartMode === 'forecast' && f ? f.interval_note : 'Modellens vikt visar användning i modellen, inte ett bevis på orsakssamband.';
  drawChart(item);
}

function drawChart(item) {
  const f = item.forecast, m = item.metrics;
  let actual=[], predicted=[], baseline=[], band=[];
  if (chartMode === 'test') {
    const points=m?.test_preview || [];
    actual=points.map(p=>[new Date(p.timestamp).getTime(),p.actual]);
    predicted=points.map(p=>[new Date(p.timestamp).getTime(),p.predicted]);
    baseline=points.map(p=>[new Date(p.timestamp).getTime(),p.baseline]);
  } else {
    actual=history.slice(-Math.max(48,item.config.horizon)).map(p=>[new Date(p.timestamp).getTime(),p.value]);
    predicted=(f?.points || []).map(p=>[new Date(p.end).getTime(),p.value]);
    band=(f?.points || []).map(p=>[new Date(p.end).getTime(),p.lower,p.upper]);
  }
  const all=[...actual,...predicted,...baseline].filter(p=>Number.isFinite(p[0])&&p[1]!=null&&Number.isFinite(p[1]));
  if (!all.length) {
    $('chart').innerHTML='<div class="chart-empty">Här visas '+(chartMode==='test'?'historiktestet när modellen har tränats.':'historik och prognos när mätvärden finns.')+'</div>'; return;
  }
  const width=1000,height=315,left=58,right=20,top=20,bottom=43;
  let minX=Math.min(...all.map(p=>p[0])),maxX=Math.max(...all.map(p=>p[0]));
  if(minX===maxX) maxX=minX+3600000;
  let minY=Math.min(...all.map(p=>p[1]),...band.map(p=>p[1])),maxY=Math.max(...all.map(p=>p[1]),...band.map(p=>p[2]));
  const padding=(maxY-minY)*.12 || 1; minY-=padding; maxY+=padding;
  const x=t=>left+(t-minX)/(maxX-minX)*(width-left-right),y=v=>height-bottom-(v-minY)/(maxY-minY)*(height-top-bottom);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${chartMode==='test'?'Historiktest med uppmätt värde, modell och jämförelseprognos':'Historik och framtida prognos'}">`;
  for(let i=0;i<=4;i++){
    const value=minY+(maxY-minY)*i/4,yy=y(value);
    svg+=`<line x1="${left}" y1="${yy}" x2="${width-right}" y2="${yy}" stroke="#2c3645" stroke-dasharray="3 5"/><text x="${left-12}" y="${yy+4}" text-anchor="end" fill="#8595a8" font-size="11">${esc(fmt(value,1))}</text>`;
  }
  for(let i=0;i<=4;i++){
    const t=minX+(maxX-minX)*i/4,label=new Date(t).toLocaleString('sv-SE',stepMinutes(item.config)>=1440?{month:'short',day:'numeric'}:{day:'numeric',hour:'2-digit',minute:'2-digit'});
    svg+=`<text x="${x(t)}" y="${height-12}" text-anchor="${i===0?'start':i===4?'end':'middle'}" fill="#8595a8" font-size="11">${esc(label)}</text>`;
  }
  if(band.length){
    const area=band.map((p,i)=>`${i?'L':'M'}${x(p[0])},${y(p[2])}`).join(' ')+[...band].reverse().map(p=>`L${x(p[0])},${y(p[1])}`).join(' ')+'Z';
    svg+=`<path d="${area}" fill="#bef36c" opacity=".12"/>`;
  }
  const path=(points,color,dash='')=>{
    let open=false,d='';
    for(const [time,value] of points){
      if(value==null||!Number.isFinite(value)){open=false;continue;}
      d+=`${open?'L':'M'}${x(time)},${y(value)} `;open=true;
    }
    return `<path d="${d}" stroke="${color}" stroke-width="2.1" fill="none" stroke-linecap="round" stroke-linejoin="round" ${dash?'stroke-dasharray="'+dash+'"':''}/>`;
  };
  svg+=path(baseline,'#b399d4','4 5')+path(actual,'#79b8f8')+path(predicted,'#bef36c');
  if(chartMode==='forecast'&&f){const ox=x(new Date(f.origin).getTime());svg+=`<line x1="${ox}" y1="${top}" x2="${ox}" y2="${height-bottom}" stroke="#6d8260" stroke-dasharray="5 5"/><text x="${Math.min(ox+8,width-95)}" y="${top+10}" fill="#bef36c" font-size="10">Prognosstart</text>`;}
  $('chart').innerHTML=svg+'</svg>';
}

function addInput(signal={key:'',entity_id:'',statistic:'mean'}) {
  const div=document.createElement('div');div.className='input-row';
  div.innerHTML=`<label>Namn i modellen<input class="input-key" required pattern="[a-z][a-z0-9_]{0,39}" placeholder="rain" value="${esc(signal.key)}"></label><label>HA-sensor<span class="entity-field"><input class="input-entity" placeholder="sensor.rain" value="${esc(signal.entity_id)}"><button type="button" class="secondary" data-entity-picker aria-label="Sök HA-signal för input">Sök</button></span></label><label>Värde per period<select class="input-stat"><option value="mean">Medelvärde</option><option value="last">Senaste värde</option><option value="change">Mätarökning</option></select></label><button type="button" class="remove-input" aria-label="Ta bort input">×</button>`;
  div.querySelector('.input-stat').value=signal.statistic;
  div.querySelector('.remove-input').onclick=()=>div.remove();
  $('input-rows').append(div);
}

function openForm(spec=null) {
  const form=$('model-form');form.reset();$('form-error').hidden=true;$('input-rows').innerHTML='';
  if(spec){
    const values={...spec,name:spec.name+' · kopia',source:spec.source==='demo'?'csv':spec.source,target_key:spec.target.key,target_entity:spec.target.entity_id||'',target_stat:spec.target.statistic,lags:spec.lags.join(', '),windows:spec.windows.join(', ')};
    for(const [name,value] of Object.entries(values)){
      const field=form.elements.namedItem(name);
      if(!field||name==='calendar')continue;
      if(field.type==='checkbox')field.checked=!!value;else if(value!=null)field.value=value;
    }
    form.querySelectorAll('[name=calendar]').forEach(el=>el.checked=spec.calendar.includes(el.value));
    spec.inputs.forEach(addInput);
  }else addInput({key:'rain',entity_id:'',statistic:'change'});
  updatePeriodPreview();$('model-dialog').showModal();
}

async function action(name, modelId=selected) {
  if(!modelId)return;
  if(window.flowEditor?.modelId===modelId&&window.flowEditor?.dirty){toast('Spara arbetsytan innan du tränar eller gör en prognos.');return;}
  try{await api(`models/${modelId}/actions/${name}`,{method:'POST'});await refresh();}
  catch(error){toast(error.message);}
}

$('new-model').onclick=()=>openForm();$('first-model').onclick=()=>openForm();
$('show-examples').onclick=()=>{selected=null;renderList();renderDetail();};
$('model-form').elements.resolution.onchange=event=>{
  const value=event.target.value,form=$('model-form');
  const presets={minute:['0, 1, 5, 15, 60','5, 15, 60',60,7],hour:['0, 1, 24, 168','24, 72, 168',24,180],day:['0, 1, 2, 7, 14','3, 7, 14',7,730],week:['0, 1, 2, 4','2, 4, 8',4,1095]};
  if(presets[value]){const [lags,windows,horizon,days]=presets[value];form.elements.lags.value=lags;form.elements.windows.value=windows;form.elements.horizon.value=horizon;form.elements.history_days.value=days;}
  updatePeriodPreview();
};
$('model-form').elements.period_minutes.oninput=updatePeriodPreview;
$('model-form').elements.horizon.oninput=updatePeriodPreview;
$('close-dialog').onclick=()=>$('model-dialog').close();$('add-input').onclick=()=>addInput();
$('clone').onclick=()=>openForm(current()?.config);
$('tab-forecast').onclick=()=>{chartMode='forecast';renderDetail();};
$('tab-test').onclick=()=>{chartMode='test';renderDetail();};
for(const name of ['sync','train','forecast','publish'])$(name).onclick=()=>action(name);
document.querySelectorAll('[data-demo]').forEach(button=>button.onclick=async()=>{
  button.disabled=true;
  try{const item=await api('demo/'+button.dataset.demo,{method:'POST'});selected=item.id;historyKey='';await refresh();toast('Demomodellen är skapad. Träna den för att se historiktestet.');}
  catch(error){toast(error.message);}finally{button.disabled=false;}
});
$('model-form').onsubmit=async event=>{
  event.preventDefault();const fd=new FormData(event.target),source=fd.get('source');
  const offsets=key=>String(fd.get(key)).split(',').map(s=>{if(!/^\s*\d+\s*$/.test(s))throw new Error('Fördröjningar och summeringar ska vara heltal med kommatecken mellan.');return Number(s);});
  const bound=key=>fd.get(key)===''?null:Number(fd.get(key));
  try{
    const spec={name:fd.get('name'),source,target:{key:fd.get('target_key'),entity_id:source==='ha'?fd.get('target_entity')||null:null,statistic:fd.get('target_stat')},
      inputs:[...$('input-rows').children].map(row=>({key:row.querySelector('.input-key').value,entity_id:source==='ha'?row.querySelector('.input-entity').value||null:null,statistic:row.querySelector('.input-stat').value})),
      unit:fd.get('unit'),resolution:fd.get('resolution'),period_minutes:Number(fd.get('period_minutes')),horizon:Number(fd.get('horizon')),timezone:fd.get('timezone'),calendar:fd.getAll('calendar'),
      lags:offsets('lags'),windows:offsets('windows'),use_target_history:fd.has('use_target_history'),minimum:bound('minimum'),maximum:bound('maximum'),
      auto_update:source==='ha'&&fd.has('auto_update'),history_days:Number(fd.get('history_days')),retrain_days:Number(fd.get('retrain_days'))};
    const item=await api('models',{method:'POST',body:JSON.stringify(spec)});selected=item.id;historyKey='';$('model-dialog').close();await refresh();toast('Modellen är skapad. Hämta eller importera historik för att börja.');
  }catch(error){$('form-error').textContent=error.message;$('form-error').hidden=false;}
};
$('csv').onchange=async event=>{
  const file=event.target.files[0],modelId=event.target.dataset.modelId||selected;if(!file||!modelId)return;
  if(window.flowEditor?.modelId===modelId&&window.flowEditor?.dirty){event.target.value='';toast('Spara arbetsytan innan du importerar historik.');return;}
  const form=new FormData();form.append('file',file);
  if($('csv-period').value!=='model')form.append('interval_minutes',$('csv-period').value);
  try{const result=await api(`models/${modelId}/csv`,{method:'POST',body:form});historyKey='';await refresh();toast(`${result.rows} mätperioder importerade.`);}
  catch(error){toast(error.message);}finally{event.target.value='';delete event.target.dataset.modelId;}
};
$('csv-label').onclick=()=>{$('csv').dataset.modelId=selected||'';};
$('auth-form').onsubmit=async event=>{
  event.preventDefault();token=$('app-token').value;
  try{await api('status');sessionStorage.setItem('predictor-token',token);$('auth-dialog').close();await init();}
  catch(error){$('auth-error').textContent=error.message;}
};
async function init(){
  try{
    const status=await api('status');$('connection').textContent=status.ha_configured?'HA-anslutning konfigurerad':'CSV och demo · HA ej ansluten';$('connection').classList.toggle('connected',status.ha_configured);
    window.entityPicker?.setConfigured(status.ha_configured);
    if(status.ha_configured) await window.entityPicker?.refresh();
    await refresh();
  }catch(error){if(!$('auth-dialog').open)toast(error.message);}
}
init();setInterval(()=>{if(!$('auth-dialog').open)refresh();},3000);
