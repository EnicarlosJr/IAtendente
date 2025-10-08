/* === Public Intake JS — v2 (melhor visual de horários) === */

const $  = (q,root=document)=>root.querySelector(q);
const $$ = (q,root=document)=>[...root.querySelectorAll(q)];
const pad = n=>String(n).padStart(2,'0');
const fmtBR = new Intl.DateTimeFormat('pt-BR',{ dateStyle:'full', timeStyle:'short' });

/* -------- Resolve URL de slots -------- */
const card = $('.card');
const SHOP   = card?.dataset.shopSlug;
const BARBER = card?.dataset.barberSlug || null;
const SLOTS_URL = ()=> BARBER ? `/pub/${SHOP}/${BARBER}/slots/` : `/pub/${SHOP}/slots/`;

/* -------- Stepper -------- */
const progressBar = $('#progressBar');
const setProgress = step => progressBar.style.width = ({1:'25%',2:'50%',3:'75%',4:'100%'}[Number(step)] || '25%');

function showStep(n){
  $$('.step').forEach(s=>s.classList.add('hidden'));
  $$('.step-label').forEach(l=>l.classList.remove('step-is-active'));
  $(`.step-label.step-${n}`)?.classList.add('step-is-active');
  $(`section[data-step="${n}"]`)?.classList.remove('hidden');
  setProgress(n);
  $('main').scrollIntoView({behavior:'smooth',block:'start'});
}
$$('.next').forEach(b=> b.addEventListener('click',()=> showStep(b.dataset.next)));
$$('.prev').forEach(b=> b.addEventListener('click',()=> showStep(b.dataset.prev)));
showStep(1);

/* Bloqueia Enter antes do final */
$('#publicForm')?.addEventListener('keydown',(e)=>{
  const step = $('.step:not(.hidden)')?.dataset.step;
  if(e.key==='Enter' && step!=='4') e.preventDefault();
});

/* -------- Máscara simples de telefone -------- */
(function(){
  const el = $('#telefone'); if(!el) return;
  el.addEventListener('input', ()=>{
    let v = el.value.replace(/\D/g,'').slice(0,11);
    el.value = !v ? '' : (v.length<=10
      ? `(${v.slice(0,2)}) ${v.slice(2,6)}-${v.slice(6)}`
      : `(${v.slice(0,2)}) ${v.slice(2,3)} ${v.slice(3,7)}-${v.slice(7)}`);
  });
})();

/* -------- Serviço / Resumo -------- */
const servicoSel = $('#servico');
const toStep3 = $('#toStep3');
const toStep4 = $('#toStep4');
const resServico = $('#resServico');
const resDuracao = $('#resDuracao');

servicoSel?.addEventListener('change', ()=>{
  toStep3.disabled = !servicoSel.value;
  const opt = servicoSel.selectedOptions[0];
  resServico.textContent = (opt?.textContent || '—').split(' — ')[0];
  resDuracao.textContent = opt?.dataset?.duracao ? `${opt.dataset.duracao} min` : '—';
  clearSlotSelection();
});

$$('.chip').forEach(ch=>{
  ch.addEventListener('click', ()=>{
    servicoSel.value = ch.dataset.value;
    servicoSel.dispatchEvent(new Event('change'));
    showStep(3); renderCalendar();
  });
});

/* -------- Calendário / Slots -------- */
const monthLabel  = $('#monthLabel');
const calendarGrid= $('#calendarGrid');
const slotsWrap   = $('#slotsWrap');
const slotsGrid   = $('#slotsGrid');   // vamos injetar tabs + acordeões aqui
const slotsSkeleton = $('#slotsSkeleton');
const slotsEmpty  = $('#slotsEmpty');
const slotsErr    = $('#slotsErr');
const errDetail   = $('#errDetail');
const inicioInput = $('#inicio');
const resDataHora = $('#resDataHora');

let current = new Date(); current.setDate(1);
$('#prevMonth')?.addEventListener('click', ()=>{ current.setMonth(current.getMonth()-1); renderCalendar(); });
$('#nextMonth')?.addEventListener('click', ()=>{ current.setMonth(current.getMonth()+1); renderCalendar(); });
$('#toStep3')?.addEventListener('click', renderCalendar);

function renderCalendar(){
  if(!servicoSel.value) return;
  const y=current.getFullYear(), m=current.getMonth();
  monthLabel.textContent = new Intl.DateTimeFormat('pt-BR',{month:'long',year:'numeric'}).format(current);
  calendarGrid.innerHTML='';
  const first=new Date(y,m,1).getDay();
  for(let i=0;i<first;i++) calendarGrid.appendChild(document.createElement('div'));
  const days=new Date(y,m+1,0).getDate();
  const today=new Date(); today.setHours(0,0,0,0);

  for(let d=1; d<=days; d++){
    const btn=document.createElement('button');
    btn.type='button'; btn.className='day-btn'; btn.textContent=d;
    const thisDate=new Date(y,m,d); thisDate.setHours(0,0,0,0);
    btn.disabled = thisDate < today;
    const dateStr=`${y}-${pad(m+1)}-${pad(d)}`;
    btn.addEventListener('click', ()=>{
      $$('.day-btn',calendarGrid).forEach(x=>x.classList.remove('active'));
      btn.classList.add('active'); fetchSlotsFor(dateStr);
    });
    calendarGrid.appendChild(btn);
  }
  precheckMonthAvailability(y,m+1);
}

async function precheckMonthAvailability(year, month){
  if(!servicoSel.value) return;
  try{
    const url=new URL(SLOTS_URL(), window.location.origin);
    url.searchParams.set('mode','days');
    url.searchParams.set('service_id', servicoSel.value);
    url.searchParams.set('year', String(year));
    url.searchParams.set('month', String(month).padStart(2,'0'));
    const resp=await fetch(url.toString(),{headers:{'Accept':'application/json'}});
    const data=await resp.json();
    const allowed=new Set((data.days||[]).map(Number));
    $$('.day-btn',calendarGrid).forEach(btn=>{
      const d=parseInt(btn.textContent,10);
      if(!allowed.has(d)) btn.disabled=true;
    });
  }catch(e){ console.warn('[days] erro:',e); }
}

/* -------- Render de slots (abas + acordeões) -------- */

function clearSlotSelection(){
  inicioInput.value=''; resDataHora.textContent='—'; toStep4.disabled=true;
  $$('.slot-btn', slotsGrid).forEach(x=>x.classList.remove('selected'));
}

function bucketOfHour(h){
  const hh=Number(h);
  if (hh>=5 && hh<=11)  return 'morning';   // Manhã
  if (hh>=12 && hh<=17) return 'afternoon'; // Tarde
  return 'evening';                         // Noite (18–23 e 00–04 cai aqui tbm)
}

function renderTabs(activeKey, counts){
  const tabs = document.createElement('div');
  tabs.className='slot-tabs';
  const defs = [
    {key:'morning',   label:'Manhã'},
    {key:'afternoon', label:'Tarde'},
    {key:'evening',   label:'Noite'},
  ];
  defs.forEach(d=>{
    const b=document.createElement('button');
    b.type='button'; b.className='slot-tab' + (d.key===activeKey?' active':'');
    b.textContent = `${d.label}${counts[d.key] ? ` (${counts[d.key]})` : ''}`;
    b.addEventListener('click', ()=> renderSections(d.key));
    tabs.appendChild(b);
  });
  return tabs;
}

let slotsState = { sectionsByBucket: {}, activeBucket: 'morning', dayStr: '' };

function buildSections(slots){
  const cleaned = [...new Set(slots.filter(Boolean))]  // remove vazios/duplicados
    .filter(t=>/^\d{2}:\d{2}$/.test(t))
    .sort((a,b)=> a.localeCompare(b));

  const byHour = {};
  for(const t of cleaned){
    const [hh] = t.split(':');
    (byHour[hh] ??= []).push(t);
  }

  const byBucket = { morning:[], afternoon:[], evening:[] };
  Object.keys(byHour).forEach(hh=>{
    const bucket = bucketOfHour(hh);
    byBucket[bucket].push({ hour: hh, list: byHour[hh] });
  });
  Object.values(byBucket).forEach(arr=> arr.sort((a,b)=> Number(a.hour)-Number(b.hour)));
  return byBucket;
}

function renderSections(bucketKey){
  slotsState.activeBucket = bucketKey;
  // Limpa mantendo tabs (primeiro filho é tabs)
  const tabs = slotsGrid.firstChild;
  slotsGrid.innerHTML=''; if (tabs) slotsGrid.appendChild(tabs);

  const sections = slotsState.sectionsByBucket[bucketKey] || [];
  if (!sections.length){
    const empty=document.createElement('p');
    empty.className='text-sm text-gray-500 px-1 py-2';
    empty.textContent='Sem horários nesse período.';
    slotsGrid.appendChild(empty);
    return;
  }

  // Acordeões por hora
  sections.forEach((sec, idx)=>{
    const wrap = document.createElement('div');
    wrap.className='hour-section';

    const summary = document.createElement('div');
    summary.className='hour-summary';
    const left = document.createElement('div'); left.className='label'; left.textContent = `${sec.hour}:00`;
    const right = document.createElement('span'); right.className='count'; right.textContent = `${sec.list.length}`;
    summary.appendChild(left); summary.appendChild(right);

    const content = document.createElement('div');
    content.className='hour-content';
    const chips = document.createElement('div');
    chips.className='slot-chips';
    sec.list.forEach(t=>{
      const btn=document.createElement('button');
      btn.type='button'; btn.className='slot-btn'; btn.textContent=t;
      btn.addEventListener('click', ()=>{
        $$('.slot-btn', chips.parentElement).forEach(x=>x.classList.remove('selected'));
        btn.classList.add('selected');
        const iso = `${slotsState.dayStr}T${t}:00`;
        inicioInput.value = iso;
        try{ resDataHora.textContent = fmtBR.format(new Date(iso)); }catch{ resDataHora.textContent = `${slotsState.dayStr} ${t}`; }
        toStep4.disabled = false;
      });
      chips.appendChild(btn);
    });
    content.appendChild(chips);

    // comportamento de “acordeão” simples
    let open = idx === 0; // primeira hora já aberta
    const toggle = ()=>{
      open = !open;
      content.style.display = open ? 'block' : 'none';
    };
    // inicial
    content.style.display = open ? 'block' : 'none';
    summary.addEventListener('click', toggle);

    wrap.appendChild(summary);
    wrap.appendChild(content);
    slotsGrid.appendChild(wrap);
  });

  // Marca container como pronto (ativa scroll/altura)
  slotsWrap.classList.add('ready');
}

async function fetchSlotsFor(dateStr){
  // reset UI
  slotsErr.classList.add('hidden'); errDetail.textContent='';
  slotsEmpty.classList.add('hidden');
  slotsGrid.innerHTML=''; slotsSkeleton.hidden=false; toStep4.disabled=true; inicioInput.value='';
  slotsWrap.classList.remove('ready');
  slotsState.dayStr = dateStr;

  // call
  const url=new URL(SLOTS_URL(), window.location.origin);
  url.searchParams.set('service_id', servicoSel.value);
  url.searchParams.set('date', dateStr);

  try{
    const resp=await fetch(url.toString(),{headers:{'Accept':'application/json'}});
    if(!resp.ok){
      const txt=await resp.text();
      throw new Error(`HTTP ${resp.status} em ${url.pathname} – ${txt.slice(0,140)}`);
    }
    const data=await resp.json();
    const slots=data.slots || [];

    if(!slots.length){
      slotsEmpty.classList.remove('hidden');
      return;
    }

    // constrói seções
    const sectionsByBucket = buildSections(slots);
    slotsState.sectionsByBucket = sectionsByBucket;

    // conta por período
    const counts = {
      morning: sectionsByBucket.morning.reduce((acc,s)=>acc+s.list.length,0),
      afternoon: sectionsByBucket.afternoon.reduce((acc,s)=>acc+s.list.length,0),
      evening: sectionsByBucket.evening.reduce((acc,s)=>acc+s.list.length,0),
    };

    // decide bucket inicial pela hora atual (qual costuma ser mais útil)
    const now = new Date();
    const guess = ['morning','afternoon','evening'][ (now.getHours()<12) ? 0 : (now.getHours()<18?1:2) ];
    const initialBucket = counts[guess] ? guess : (counts.morning ? 'morning' : (counts.afternoon ? 'afternoon' : 'evening'));

    // Tabs + sections
    const tabs = renderTabs(initialBucket, counts);
    slotsGrid.appendChild(tabs);
    renderSections(initialBucket);

  }catch(e){
    slotsErr.classList.remove('hidden');
    errDetail.textContent = e.message || String(e);
    console.error('[slots] erro:', e);
  }finally{
    slotsSkeleton.hidden=true;
  }
}

/* -------- Submissão -------- */
$('#submitBtn')?.addEventListener('click',(e)=>{
  const telOk = !!$('#telefone')?.value.trim();
  const srvOk = !!servicoSel?.value;
  if(!telOk || !srvOk){
    e.preventDefault(); showStep(1);
    alert('Preencha WhatsApp e Serviço.');
    return;
  }
  $('#_submit').value='1';
});
