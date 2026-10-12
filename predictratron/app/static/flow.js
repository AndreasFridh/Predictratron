/* Signal graph: connections are compiled and validated by the server. */
const FlowTypes = {float:'Float',int:'Integer',bool:'Boolean'};
const CalendarNames = {hour:'Klockslag',weekday:'Veckodag',week:'Vecka',year_day:'Årstid'};
const SignalNames = {rain:'Nederbörd',temperature:'Temperatur',consumption:'Timförbrukning',water_level:'Vattennivå i mark'};

class FlowEditor {
  constructor() {
    this.graph=null;this.modelId=null;this.isDraft=false;this.dirty=false;this.mode='flow';this.zoom=1;
    this.armed=null;this.gesture=null;this.signalId=null;this.editingML=false;this.entities=[];
    $('new-model').onclick=()=>this.newDraft();$('first-model').onclick=()=>this.newDraft();
    $('clone').onclick=()=>this.newDraft(current()?.config);
    $('show-examples').onclick=()=>{if(this.dirty&&!confirm('Lämna osparade ändringar på arbetsytan?'))return;this.isDraft=false;this.graph=null;this.modelId=null;selected=null;renderList();renderDetail();};
    $('view-flow').onclick=()=>{this.mode='flow';renderDetail();};
    $('view-results').onclick=()=>{this.mode='results';renderDetail();};
    $('palette-toggle').onclick=()=>$('signal-palette').classList.toggle('open');
    $('save-flow').onclick=()=>this.save(false);$('save-copy').onclick=()=>this.save(true);
    $('ml-settings').onclick=()=>this.editML();
    $('zoom-in').onclick=()=>this.setZoom(this.zoom+.1);$('zoom-out').onclick=()=>this.setZoom(this.zoom-.1);
    $('fit-flow').onclick=()=>this.fit();
    $('flow-sync').onclick=()=>action('sync',this.modelId);
    $('flow-import').onclick=()=>{if(!this.modelId||this.dirty)return;$('csv').dataset.modelId=this.modelId;$('csv').click();};
    const canvas=$('flow-canvas');
    canvas.addEventListener('dragover',e=>{e.preventDefault();e.dataTransfer.dropEffect='copy';canvas.classList.add('drop-over');});
    canvas.addEventListener('dragleave',()=>canvas.classList.remove('drop-over'));
    canvas.addEventListener('drop',e=>{
      e.preventDefault();canvas.classList.remove('drop-over');
      const template=e.dataTransfer.getData('application/x-predictor-signal');
      if(template)this.add(template,this.point(e));
    });
    this.bindPalette();
    $('browse-ha-signals').onclick=()=>window.entityPicker.open('', entity=>this.add('ha:'+this.entities.findIndex(item=>item.entity_id===entity.entity_id)));
    canvas.addEventListener('pointerdown',e=>this.pointerDown(e));
    window.addEventListener('pointermove',e=>this.pointerMove(e));
    window.addEventListener('pointerup',e=>this.pointerUp(e));
    window.addEventListener('pointercancel',()=>{this.gesture=null;this.armed=null;this.drawWires();});
    canvas.addEventListener('keydown',e=>{if(e.key==='Escape'){this.armed=null;this.drawWires();this.help();}});
    $('close-signal').onclick=()=>$('signal-dialog').close();
    $('signal-form').onsubmit=e=>this.saveSignal(e);
    $('remove-node').onclick=()=>this.removeNode();
    const legacySubmit=$('model-form').onsubmit;
    $('model-form').onsubmit=e=>{if(this.editingML)this.saveML(e);else legacySubmit(e);};
    $('model-dialog').addEventListener('close',()=>{$('model-form').elements.source.disabled=false;$('model-form').elements.auto_update.disabled=false;this.editingML=false;$('model-form').classList.remove('ml-edit-mode');});
    window.addEventListener('beforeunload',e=>{if(this.dirty){e.preventDefault();e.returnValue='';}});
  }

  bindPalette() {
    document.querySelectorAll('.palette-signal').forEach(button=>{
      button.ondragstart=e=>{e.dataTransfer.setData('application/x-predictor-signal',button.dataset.template);e.dataTransfer.effectAllowed='copy';};
      button.onclick=()=>this.add(button.dataset.template);
    });
  }

  setEntities(entities) {
    this.entities=entities;
  }

  dataSource() {
    if(!this.graph)return 'csv';
    const box=this.graph.nodes.find(node=>node.kind==='ml');
    const connected=this.graph.edges.map(edge=>edge.target===box.id?this.graph.nodes.find(node=>node.id===edge.source):edge.source===box.id?this.graph.nodes.find(node=>node.id===edge.target):null).filter(node=>node?.signal);
    const mapped=connected.filter(node=>node.signal.entity_id).length;
    return mapped===connected.length&&mapped>0?'ha':mapped>0?'mixed':box.config.source==='demo'?'demo':'csv';
  }

  makeGraph(spec, connected=true) {
    const c=structuredClone(spec);
    const nodes=[],edges=[],compact=$('flow-canvas').clientWidth<900;
    const sources=[...c.inputs.map(s=>({kind:'input',signal:{data_type:'float',...s,label:s.label||SignalNames[s.key]||s.key}})),
      ...c.calendar.map(calendar=>({kind:'calendar',calendar}))];
    sources.forEach((data,i)=>{
      const id='input-'+i;nodes.push({id,x:compact?25:55,y:55+i*106,...data});
      if(connected)edges.push({source:id,target:'ml'});
    });
    const mlY=Math.max(110,Math.min(320,55+Math.max(0,sources.length-1)*53));
    nodes.push({id:'ml',kind:'ml',x:compact?300:385,y:mlY,config:c});
    if(connected){
      nodes.push({id:'output',kind:'output',x:compact?300:745,y:compact?mlY+325:mlY+54,signal:{data_type:'float',...c.target,label:c.target.label||SignalNames[c.target.key]||c.target.key}});
      edges.push({source:'ml',target:'output'});
    }
    return {version:1,nodes,edges};
  }

  newDraft(spec=null) {
    if(this.dirty&&!confirm('Lämna osparade ändringar och skapa en ny arbetsyta?'))return;
    selected=null;this.isDraft=true;this.modelId=null;this.mode='flow';this.zoom=1;
    $('workbench').hidden=false;
    const config=spec?{...structuredClone(spec),name:spec.name+' · kopia',source:spec.source==='demo'?'csv':spec.source,auto_update:false}:
      {name:'Ny modell',source:'csv',target:{key:'output',entity_id:null,statistic:'mean',data_type:'float',label:'Outputsignal'},inputs:[],unit:'',resolution:'day',horizon:7,timezone:'Europe/Stockholm',calendar:[],lags:[0,1,2,7,14],windows:[3,7,14],use_target_history:true,minimum:null,maximum:null,auto_update:false,history_days:180,retrain_days:7};
    this.graph=this.makeGraph(config,!!spec);this.dirty=true;this.renderNodes();renderList();renderDetail();
    if(!spec)this.help('Dra ut inputs och en outputsignal från Signaler. ML-boxen finns redan på arbetsytan.');
  }

  show(item) {
    if(!item&&!this.isDraft){$('workbench').hidden=true;return;}
    $('workbench').hidden=false;
    if(item&&this.modelId!==item.id){
      $('csv-period').value='model';
      if(this.isDraft&&this.dirty&&!confirm('Lämna osparade ändringar?')){selected=null;return;}
      this.modelId=item.id;this.isDraft=false;this.dirty=false;this.mode='flow';this.zoom=1;
      this.graph=item.graph?structuredClone(item.graph):this.makeGraph(item.config);
      this.armed=null;this.renderNodes();
    }
    if(!this.graph)return;
    const box=this.graph.nodes.find(n=>n.kind==='ml');
    $('flow-title').textContent=box.config.name;
    $('flow-area').hidden=this.mode==='results';
    $('view-flow').classList.toggle('active',this.mode==='flow');$('view-results').classList.toggle('active',this.mode==='results');
    $('view-results').disabled=!item;
    $('flow-save-status').textContent=this.dirty?'Osparade ändringar':item?.graph?'Sparad arbetsyta':'Kopplingar från modellinställningarna';
    const busy=item?.status==='running';
    $('save-flow').disabled=busy;$('save-copy').disabled=busy;
    const dataSource=this.dataSource();
    $('flow-sync').hidden=dataSource!=='ha';
    $('flow-sync').disabled=busy||!item||this.dirty;
    $('flow-import').hidden=dataSource!=='csv';
    $('csv-period-label').hidden=dataSource!=='csv';
    $('csv-period').disabled=busy||!item||this.dirty;
    $('flow-import').disabled=busy||!item||this.dirty;
    document.querySelectorAll('[data-ml-action]').forEach(button=>{
      const train=button.dataset.mlAction==='train';
      button.disabled=busy||!item||this.dirty||(train?!item.data.n:!item.metrics);
      button.title=this.dirty?'Spara arbetsytan först':!item?'Spara för att skapa en egen modellinstans':busy?'Instansen arbetar':train?(item.data.n?'Träna denna instans på dess sparade historik':'Hämta eller importera historik först'):(item.metrics?'Använd denna instans tränade modell för framtida värden':'Träna denna instans först');
    });
    const instance=document.querySelector('.ml-instance');if(instance)instance.textContent=item?'Egen instans · '+item.id:'Ny instans · skapas vid sparning';
    const data=document.querySelector('.ml-history');if(data)data.textContent=item?.data.n?`${fmt(item.data.n,0)} historiska perioder · egen historik`:'Ingen historik ännu';
    $('flow-job-status').textContent=busy?'Modellen arbetar…':item?.trained_at?'Tränad '+date(item.trained_at):!item?'Spara för att skapa instansen.':!item.data.n?'Hämta eller importera historik för att träna.':'Historiken är redo för träning.';
    $('flow-error').hidden=!item?.error;$('flow-error').textContent=item?.error||'';
    const state=document.querySelector('.ml-state');if(state)state.textContent=busy?'Träning / bearbetning pågår…':item?.metrics?(item.metrics.beats_baseline?'Tränad · lägre fel än jämförelsen':'Tränad · behöver förbättras'):'Inte tränad ännu';
    this.validity();
  }

  point(e) {
    const rect=$('flow-canvas').getBoundingClientRect();
    return {x:(e.clientX-rect.left+$('flow-canvas').scrollLeft)/this.zoom,y:(e.clientY-rect.top+$('flow-canvas').scrollTop)/this.zoom};
  }

  setZoom(value) {
    this.zoom=Math.max(.4,Math.min(1.8,value));
    $('flow-world').style.transform=`scale(${this.zoom})`;
    $('zoom-label').textContent=Math.round(this.zoom*100)+' %';
  }

  fit() {
    if(!this.graph)return;
    const right=Math.max(...this.graph.nodes.map(n=>n.x+(n.kind==='ml'?260:225)))+45;
    const bottom=Math.max(...this.graph.nodes.map(n=>n.y+(document.querySelector(`.flow-node[data-node="${n.id}"]`)?.offsetHeight||110)))+30;
    this.setZoom(Math.min(1,($('flow-canvas').clientWidth-15)/right,($('flow-canvas').clientHeight-15)/bottom));
    $('flow-canvas').scrollTo({top:0,left:0});
  }

  markDirty() {this.dirty=true;this.show(current());this.validity();}
  help(message=null) {$('flow-help').textContent=message||'Dra från en signals ○ till ML-boxens ○. Koppla sedan ML till output. Klicka på en linje för att ta bort kopplingen.';}

  renderNodes() {
    if(!this.graph)return;
    const incoming=this.graph.edges.filter(e=>e.target==='ml').map(e=>this.graph.nodes.find(n=>n.id===e.source)).filter(Boolean);
    const out=this.graph.edges.find(e=>e.source==='ml');
    const target=this.graph.nodes.find(n=>n.id===out?.target);
    const port=(node,side)=>`<button class="node-port port-${side}" data-node="${node.id}" data-port="${side}" aria-label="${side==='out'?'Utgång':'Ingång'}: ${esc(node.kind==='ml'?'ML':node.signal?.label||node.signal?.key||CalendarNames[node.calendar])}" title="Dra eller klicka för att koppla"></button>`;
    $('flow-nodes').innerHTML=this.graph.nodes.map(n=>{
      if(n.kind==='ml')return `<article class="flow-node node-ml" data-node="${n.id}" style="left:${n.x}px;top:${n.y}px" aria-label="ML-box ${esc(n.config.name)}"><div class="node-drag" data-drag="${n.id}"><span class="ml-symbol">✳</span><div class="ml-title">ML-box<small>${esc(n.config.name)}</small></div></div><button class="node-gear" data-edit="${n.id}" aria-label="Ändra ML-inställningar">⚙</button><div class="ml-body"><div class="ml-instance"></div><div class="ml-input-count">${incoming.length} anslutna inputs</div><div class="ml-output-label">→ ${esc(target?.signal?.label||target?.signal?.key||'Koppla en outputsignal')}</div><div class="ml-history"></div><div class="ml-state">Inte tränad ännu</div><div class="ml-actions"><button class="secondary" data-ml-action="train" disabled>1. Träna på historik</button><button class="primary" data-ml-action="forecast" disabled>2. Prediktera framtid</button></div><div class="ml-period"><button class="ml-period-button" data-period-settings="${n.id}" aria-label="Välj ML-boxens tidsperiod">${esc(periodName(n.config))} · ${esc(aggregateName(target?.signal||n.config.target))} ⚙</button></div><div class="ml-foot"><span>${n.config.horizon} × ${esc(periodName(n.config))} framåt</span><span>${n.config.use_target_history?'Tidigare output ingår':'Endast inputs'}</span></div></div>${port(n,'in')}${port(n,'out')}</article>`;
      const calendar=n.kind==='calendar',label=calendar?CalendarNames[n.calendar]:n.signal.label||n.signal.key;
      const type=calendar?'Integer':FlowTypes[n.signal.data_type||'float'];
      const caption=calendar?'Kalender · skapas automatiskt':n.kind==='output'?'OUTPUT · mål för träning och prognos':n.signal.entity_id||'INPUT · '+n.signal.key;
      return `<article class="flow-node node-${n.kind}" data-node="${n.id}" style="left:${n.x}px;top:${n.y}px" aria-label="${esc(label)} (${type})"><div class="node-drag" data-drag="${n.id}"><span class="signal-symbol">○</span><span class="node-label">– ${esc(label)} <span class="node-type">(${type})</span></span></div><button class="node-gear" data-edit="${n.id}" aria-label="Ändra ${esc(label)}">⚙</button><div class="node-caption">${esc(caption)}</div>${port(n,n.kind==='output'?'in':'out')}</article>`;
    }).join('');
    $('flow-nodes').querySelectorAll('[data-edit]').forEach(button=>button.onclick=()=>{
      const n=this.graph.nodes.find(n=>n.id===button.dataset.edit);
      if(n.kind==='ml')this.editML();else if(n.kind==='calendar')this.editCalendar(n);else this.editSignal(n);
    });
    $('flow-nodes').querySelectorAll('[data-period-settings]').forEach(button=>button.onclick=()=>this.editML());
    $('flow-nodes').querySelectorAll('[data-ml-action]').forEach(button=>button.onclick=()=>action(button.dataset.mlAction,this.modelId));
    this.setZoom(this.zoom);this.drawWires();this.validity();
  }

  socket(id,side) {
    const n=this.graph.nodes.find(n=>n.id===id);if(!n)return{x:0,y:0};
    return {x:n.x+(side==='out'?(n.kind==='ml'?260:225):0),y:n.y+(n.kind==='ml'?108:46)};
  }

  curve(a,b) {
    if(b.x<a.x&&b.y>a.y+90){
      const mid=Math.max(a.y+125,b.y-55);
      return `M ${a.x} ${a.y} C ${a.x+18} ${a.y}, ${a.x+18} ${mid}, ${a.x} ${mid} L ${b.x-26} ${mid} Q ${b.x-40} ${mid}, ${b.x-40} ${mid+14} L ${b.x-40} ${b.y-14} Q ${b.x-40} ${b.y}, ${b.x-26} ${b.y} L ${b.x} ${b.y}`;
    }
    const reach=Math.max(35,Math.min(140,Math.abs(b.x-a.x)*.5));return `M ${a.x} ${a.y} C ${a.x+reach} ${a.y}, ${b.x-reach} ${b.y}, ${b.x} ${b.y}`;
  }

  drawWires(point=null) {
    if(!this.graph)return;
    $('flow-wires').innerHTML=this.graph.edges.map((e,i)=>{
      const source=this.graph.nodes.find(n=>n.id===e.source);if(!source)return'';
      const d=this.curve(this.socket(e.source,'out'),this.socket(e.target,'in'));
      return `<path class="wire-visible ${source.kind==='calendar'?'calendar-wire':source.kind==='ml'?'output-wire':''}" d="${d}"/><path class="wire-hit" d="${d}" data-edge="${i}" role="button" tabindex="0" aria-label="Ta bort koppling ${esc(source.signal?.label||source.signal?.key||CalendarNames[source.calendar]||'ML')}"/>`;
    }).join('');
    const from=this.gesture?.kind==='wire'?this.gesture.port:this.armed;
    if(from&&point){const start=this.socket(from.node,from.side);$('flow-wires').innerHTML+=`<path class="wire-draft" d="${from.side==='out'?this.curve(start,point):this.curve(point,start)}"/>`;}
    document.querySelectorAll('.node-port').forEach(p=>p.classList.toggle('armed',p.dataset.node===from?.node&&p.dataset.port===from?.side));
    $('flow-wires').querySelectorAll('[data-edge]').forEach(path=>{
      const remove=()=>{this.graph.edges.splice(Number(path.dataset.edge),1);this.renderNodes();this.markDirty();};
      path.onclick=remove;path.onkeydown=e=>{if(e.key==='Delete'||e.key==='Backspace'||e.key==='Enter'){e.preventDefault();remove();}};
    });
  }

  pointerDown(e) {
    if(e.button!==0||!this.graph)return;
    const port=e.target.closest('[data-port]');
    if(port){
      e.preventDefault();const info={node:port.dataset.node,side:port.dataset.port};
      if(this.armed&&(this.armed.node!==info.node||this.armed.side!==info.side)){this.connect(this.armed,info);this.armed=null;this.drawWires();return;}
      this.armed=null;this.gesture={kind:'wire',port:info,start:this.point(e),moved:false};return;
    }
    if(e.target.closest('button,[data-edge]'))return;
    const header=e.target.closest('[data-drag]');
    if(header){
      const node=this.graph.nodes.find(n=>n.id===header.dataset.drag),point=this.point(e);
      this.gesture={kind:'move',node,start:point,x:node.x,y:node.y,moved:false};
      e.preventDefault();document.querySelector(`.flow-node[data-node="${node.id}"]`).classList.add('moving');
    }else {this.armed=null;this.drawWires();this.help();}
  }

  pointerMove(e) {
    const p=this.point(e),g=this.gesture;
    if(!g){if(this.armed&&$('flow-canvas').contains(e.target))this.drawWires(p);return;}
    if(Math.abs(p.x-g.start.x)+Math.abs(p.y-g.start.y)>4)g.moved=true;
    if(g.kind==='wire'){this.drawWires(p);return;}
    g.node.x=Math.max(10,Math.min(5800,g.x+p.x-g.start.x));g.node.y=Math.max(20,Math.min(5800,g.y+p.y-g.start.y));
    const node=document.querySelector(`.flow-node[data-node="${g.node.id}"]`);node.style.left=g.node.x+'px';node.style.top=g.node.y+'px';this.drawWires();
  }

  pointerUp(e) {
    const g=this.gesture;if(!g)return;this.gesture=null;
    if(g.kind==='move'){document.querySelector('.moving')?.classList.remove('moving');if(g.moved)this.markDirty();return;}
    const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-port]');
    if(target&&(target.dataset.node!==g.port.node||target.dataset.port!==g.port.side))this.connect(g.port,{node:target.dataset.node,side:target.dataset.port});
    else if(!g.moved){this.armed=g.port;this.help('Port vald. Klicka på mottagarens ○ eller tryck Escape för att avbryta.');}
    else this.help('Släpp kopplingen på en passande ○-port.');
    this.drawWires();
  }

  connect(a,b) {
    if(a.side===b.side){this.help('Koppla en utgång till en ingång.');return;}
    const from=a.side==='out'?a:b,to=a.side==='in'?a:b;
    const source=this.graph.nodes.find(n=>n.id===from.node),target=this.graph.nodes.find(n=>n.id===to.node);
    if(!((['input','calendar'].includes(source.kind)&&target.kind==='ml')||(source.kind==='ml'&&target.kind==='output'))){this.help('Koppla inputs till ML och ML till output.');return;}
    if(this.graph.edges.some(e=>e.source===source.id&&e.target===target.id)){this.help('Signalerna är redan kopplade.');return;}
    if(source.kind==='ml')this.graph.edges=this.graph.edges.filter(e=>e.source!==source.id);
    this.graph.edges.push({source:source.id,target:target.id});this.renderNodes();this.markDirty();this.help();
  }

  add(template,position=null) {
    if(!this.graph)return;
    const box=this.graph.nodes.find(n=>n.kind==='ml'),id='signal-'+crypto.randomUUID().slice(0,8);
    const existing=new Set(this.graph.nodes.filter(n=>n.signal).map(n=>n.signal.key));
    const unique=base=>{if(!/^[a-z]/.test(base))base='signal_'+base;let key=base,n=2;while(existing.has(key))key=base+'_'+n++;return key;};
    let node, entity=null;
    if(template in CalendarNames)node={id,kind:'calendar',calendar:template};
    else {
      entity=template.startsWith('ha:')?this.entities[Number(template.split(':')[1])]:null;
      const key=unique(entity?entity.entity_id.split('.')[1].slice(0,30):template==='custom'?'signal':template==='output'?'output':template);
      node={id,kind:template==='output'?'output':'input',signal:{key,label:entity?.name||(template==='output'?'Outputsignal':template==='custom'?'Egen signal':SignalNames[template]),entity_id:entity?.entity_id||null,statistic:entity?.entity_id.startsWith('binary_sensor.')?'last':template==='rain'?'change':'mean',data_type:entity?.entity_id.startsWith('binary_sensor.')?'bool':'float'}};
    }
    const offset=this.graph.nodes.filter(n=>n.kind!=='ml').length;
    const where=position||{x:30+(offset%2)*25,y:70+offset*105};
    this.graph.nodes.push({...node,x:Math.max(15,Math.min(5800,where.x)),y:Math.max(25,Math.min(5800,where.y))});
    this.renderNodes();this.markDirty();
    const canvas=$('flow-canvas'),added=this.graph.nodes.at(-1);
    if(added.y*this.zoom>canvas.scrollTop+canvas.clientHeight-130)canvas.scrollTo({top:Math.max(0,added.y*this.zoom-80),left:canvas.scrollLeft,behavior:'smooth'});
    if(position)$('signal-palette').classList.remove('open');
    this.help('Signalen är tillagd. Koppla dess ○ till ML-boxen.');
    if(!entity&&node.kind!=='calendar')this.editSignal(this.graph.nodes.at(-1));
  }

  editSignal(node) {
    this.signalId=node.id;const form=$('signal-form');form.reset();
    for(const field of form.querySelectorAll('input,select')){field.disabled=false;field.readOnly=false;}
    form.querySelector('[type=submit]').textContent='Använd signal';
    for(const [key,value] of Object.entries(node.signal)){if(form.elements[key])form.elements[key].value=value??'';}
    form.elements.data_type.value=node.signal.data_type||'float';
    $('signal-role').textContent=node.kind==='output'?'OUTPUTSIGNAL':'INPUTSIGNAL';
    $('signal-note').textContent=node.kind==='output'?'Den uppmätta signalen är målet vid träning. ML-boxen skickar sin framtida prognos till denna output.':'Välj signalens datakälla. Koppla sedan signalen till ML-boxen.';
    $('signal-error').hidden=true;$('signal-dialog').showModal();
  }

  saveSignal(e) {
    e.preventDefault();const data=new FormData(e.target),node=this.graph.nodes.find(n=>n.id===this.signalId);
    if(node.kind==='calendar'){$('signal-dialog').close();return;}
    const key=data.get('key');
    if(this.graph.nodes.some(n=>n.id!==node.id&&n.signal?.key===key)){$('signal-error').textContent='Varje signal behöver ett unikt kolumnnamn.';$('signal-error').hidden=false;return;}
    if(node.kind==='output'&&data.get('data_type')==='bool'){$('signal-error').textContent='ML-boxen förutsäger numeriska mål. Boolean kan användas som input.';$('signal-error').hidden=false;return;}
    node.signal={key,label:data.get('label'),entity_id:data.get('entity_id')||null,statistic:data.get('statistic'),data_type:data.get('data_type')};
    $('signal-dialog').close();this.renderNodes();this.markDirty();
  }

  editCalendar(node) {
    this.signalId=node.id;const form=$('signal-form');form.reset();
    form.elements.label.value=CalendarNames[node.calendar];form.elements.label.readOnly=true;
    form.elements.key.value=node.calendar;form.elements.key.readOnly=true;
    form.elements.data_type.value='int';form.elements.data_type.disabled=true;
    form.elements.entity_id.value='';form.elements.entity_id.disabled=true;
    form.elements.statistic.disabled=true;form.querySelector('[type=submit]').textContent='Klar';
    $('signal-role').textContent='KALENDERSIGNAL';$('signal-note').textContent='Kalendern skapas automatiskt i modellens tidszon. Koppla signalen till ML-boxen för att använda den.';
    $('signal-error').hidden=true;$('signal-dialog').showModal();
  }

  removeNode() {
    const id=this.signalId;this.graph.nodes=this.graph.nodes.filter(n=>n.id!==id);this.graph.edges=this.graph.edges.filter(e=>e.source!==id&&e.target!==id);
    $('signal-dialog').close();this.renderNodes();this.markDirty();
  }

  editML() {
    if(!this.graph)return;const box=this.graph.nodes.find(n=>n.kind==='ml');
    openForm(box.config);this.editingML=true;
    const form=$('model-form');form.classList.add('ml-edit-mode');form.elements.name.value=box.config.name;
    if(!form.elements.source.querySelector('[value=demo]'))form.elements.source.add(new Option('Syntetisk demo','demo'));
    form.elements.source.value=box.config.source;form.elements.source.disabled=true;
    form.elements.auto_update.disabled=this.dataSource()!=='ha';
    $('target-section-title').textContent='Prognosinställningar';
    form.querySelector('.dialog-heading h2').textContent='ML-boxens inställningar';
    form.querySelector('[type=submit]').textContent='Använd inställningar';
    updatePeriodPreview();
  }

  saveML(e) {
    e.preventDefault();const fd=new FormData(e.target),box=this.graph.nodes.find(n=>n.kind==='ml');
    try{
      const offsets=key=>String(fd.get(key)).split(',').map(s=>{if(!/^\s*\d+\s*$/.test(s))throw new Error('Ange heltal med kommatecken mellan.');return Number(s);});
      const bound=key=>fd.get(key)===''?null:Number(fd.get(key));
      box.config={...box.config,name:fd.get('name'),source:this.dataSource()==='mixed'?box.config.source:this.dataSource(),unit:fd.get('unit'),resolution:fd.get('resolution'),period_minutes:Number(fd.get('period_minutes')),horizon:Number(fd.get('horizon')),timezone:fd.get('timezone'),lags:offsets('lags'),windows:offsets('windows'),use_target_history:fd.has('use_target_history'),minimum:bound('minimum'),maximum:bound('maximum'),auto_update:this.dataSource()==='ha'&&fd.has('auto_update'),history_days:Number(fd.get('history_days')),retrain_days:Number(fd.get('retrain_days'))};
      $('model-dialog').close();this.renderNodes();this.markDirty();
    }catch(error){$('form-error').textContent=error.message;$('form-error').hidden=false;}
  }

  validity() {
    if(!this.graph)return;const inputs=this.graph.edges.filter(e=>e.target==='ml').length,outputs=this.graph.edges.filter(e=>e.source==='ml').length;
    $('flow-validity').textContent=outputs===1?`${inputs} inputs → ML → 1 output`:'Koppla en output för att spara';
  }

  async save(copy) {
    if(!this.graph)return;
    const button=copy?$('save-copy'):$('save-flow');button.disabled=true;
    try{
      const creating=copy||!this.modelId;
      const payload=structuredClone(this.graph);
      if(this.dataSource()!=='mixed')payload.nodes.find(node=>node.kind==='ml').config.source=this.dataSource();
      if(copy)payload.nodes.find(n=>n.kind==='ml').config.name+=' · kopia';
      const item=await api(creating?'graphs':`models/${this.modelId}/graph`,{method:creating?'POST':'PUT',body:JSON.stringify(payload)});
      selected=item.id;this.modelId=item.id;this.graph=structuredClone(item.graph);this.isDraft=false;this.dirty=false;
      this.renderNodes();await refresh();toast(creating?'Modellinstansen är skapad. Hämta eller importera historik.':'Kopplingar och placeringar är sparade.');
    }catch(error){$('flow-error').textContent=error.message;$('flow-error').hidden=false;toast(error.message);}finally{button.disabled=false;}
  }
}

window.flowEditor=new FlowEditor();
