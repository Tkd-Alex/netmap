'use strict';

const POLL = parseInt(document.querySelector('meta[name="poll-interval"]').content, 10);


const T={
title:['Mappa della rete','Network map'],
sub:['AX55 + GL.iNet Opal · aggiornamento ogni {0} s','AX55 + GL.iNet Opal · refreshing every {0} s'],
langAria:['Lingua','Language'],waiting:['In attesa dei router…','Waiting for the routers…'],connecting:['Connessione in corso','Connecting'],updatedAt:['Aggiornato {0}','Updated {0}'],
refresh:['Aggiorna','Refresh'],refreshing:['Aggiorno…','Refreshing…'],summaryAria:['Riepilogo','Summary'],
statConnected:['Dispositivi connessi','Connected devices'],statDirect:['AX55 · client diretti','AX55 · direct clients'],statDirectSub:['Wi-Fi e cavo','Wi-Fi and wired'],
statOpal:['Opal · client','Opal · clients'],statUplink:['Uplink Opal → AX55','Opal → AX55 uplink'],
countSub:['{0} noti in totale','{0} known in total'],opSub:['{0} Wi-Fi · {1} cavo','{0} Wi-Fi · {1} wired'],
snr:['SNR {0} dB','SNR {0} dB'],worst:['client Opal: peggiore {0} dBm','Opal clients: worst {0} dBm'],opalDown:['Opal non raggiungibile','Opal unreachable'],
topoTitle:['Topologia e associazioni','Topology and associations'],groupBy:['Raggruppa per','Group by'],vNet:['Collegamento','Connection'],vRoom:['Stanza','Room'],vKind:['Tipo','Type'],
topoLoading:['Lettura dello stato dei router…','Reading the router status…'],
allDevices:['Tutti i dispositivi','All devices'],filterPh:['Filtra nome, IP, MAC, access point…','Filter name, IP, MAC, access point…'],filterAria:['Filtra dispositivi','Filter devices'],
connFilterAria:['Filtra per stato di connessione','Filter by connection state'],optAllStates:['Tutti gli stati','All states'],optConnected:['Connessi','Connected'],optDisconnected:['Non connessi','Not connected'],
typeFilterAria:['Filtra per tipo','Filter by type'],roomFilterAria:['Filtra per stanza','Filter by room'],unlabeledOnly:['Solo senza label','Unlabeled only'],showAll:['Mostra tutti','Show all'],
applySug:['Applica suggerimenti ({0})','Apply suggestions ({0})'],confirmApply:['Assegnare a tutti i dispositivi non classificati il tipo suggerito?','Assign the suggested type to every unclassified device?'],
devOne:['{0} dispositivo','{0} device'],devMany:['{0} dispositivi','{0} devices'],client1:['client','client'],clientN:['client','clients'],
thLabel:['Dispositivo','Device'],thType:['Tipo','Type'],thRoom:['Stanza','Room'],thLink:['Collegato a','Connected to'],thBand:['Banda','Band'],ratesTitle:['Velocità di collegamento in Mbps','Link speed in Mbps'],
renameTitle:['Rinomina','Rename'],renameAria:['Rinomina {0}','Rename {0}'],suggestedRow:['Suggerito automaticamente: apri la modifica per confermarlo','Suggested automatically: open Edit to confirm it'],
histTitle:['Storico segnale · {0}','Signal history · {0}'],uplinkName:['uplink Opal → AX55','Opal → AX55 uplink'],r7d:['7 g','7 d'],btnEdit:['Modifica','Edit'],btnClose:['Chiudi','Close'],
chartLegend:['Linee verticali: viola = cambio AP/banda · verde = connessione · rosso = disconnessione','Vertical lines: violet = AP/band change · green = connected · red = disconnected'],
chartAria:['Grafico del segnale nel tempo','Signal over time chart'],chartEmpty:['Nessun campione in questo intervallo: i dispositivi cablati non hanno RSSI.','No samples in this range: wired devices have no RSSI.'],
evTitle:['Cambi di access point e connessioni','Access point changes and connections'],
evIntro:['Quanto spesso i dispositivi passano tra Opal, AX55 ed extender, o cambiano banda. Clic su una riga per vedere lo storico.','How often devices move between the Opal, the AX55 and extenders, or change band. Click a row to see its history.'],
thUnstable:['Più instabili','Most unstable'],thApChanges:['Cambi AP','AP changes'],thBandChanges:['Cambi banda/rete','Band/network changes'],thDisc:['Disconnessioni','Disconnections'],
thWhen:['Quando','When'],thDevice:['Dispositivo','Device'],thEvent:['Evento','Event'],thFromTo:['Da → a','From → to'],
evNote:['Gli eventi si registrano solo quando AX55 e Opal rispondono entrambi: la precisione è quella del ciclo di aggiornamento e dei tempi con cui i router dichiarano un client uscito.','Events are recorded only when both the AX55 and the Opal respond: precision is limited by the refresh cycle and by how long the routers take to report a client as gone.'],
evSum:['· cambi: {0} · disconnessioni: {1} (ultime {2})','· changes: {0} · disconnections: {1} (last {2})'],nHours:['{0} ore','{0} hours'],nDays:['{0} giorni','{0} days'],
evNone:['Nessun cambio nel periodo.','No changes in the period.'],evNoEvents:['Nessun evento nel periodo.','No events in the period.'],evUnavailable:['Eventi non disponibili.','Events unavailable.'],
kMoveAp:['Cambio AP','AP change'],kMoveBand:['Cambio banda/rete','Band/network change'],kConnect:['Connesso','Connected'],kDisconnect:['Disconnesso','Disconnected'],
diagTitle:['Diagnostica sorgenti','Source diagnostics'],thSource:['Sorgente','Source'],thState:['Stato','State'],thLastOk:['Ultimo ok','Last OK'],thDuration:['Durata','Duration'],
thLastReading:['Ultima lettura / errore','Last reading / error'],thFails:['Errori di fila','Consecutive errors'],stDisabled:['disattivato','disabled'],stWaiting:['in attesa','waiting'],stError:['● errore','● error'],
diagOk:['· tutto regolare','· all good'],diagBad:['· {0} sorgente/i in errore','· {0} source(s) failing'],
diagFoot:['Ciclo n. {0}, ogni {1} s · in esecuzione da {2}','Cycle #{0}, every {1} s · running for {2}'],
lastUpdate:['Ultimo aggiornamento:','Last update:'],sqliteNote:['· storico locale SQLite','· local SQLite history'],
dlgTitle:['Modifica dispositivo','Edit device'],fName:['Nome','Name'],namePh:['Label (vuoto = nome rilevato)','Label (empty = detected name)'],fType:['Tipo','Type'],fRoom:['Stanza','Room'],
roomPh:['es. Cucina','e.g. Kitchen'],cancel:['Annulla','Cancel'],save:['Salva','Save'],kindAuto:['Automatico / non classificato','Automatic / unclassified'],
hintSuggested:['Suggerito: {0} · scegli un tipo per confermarlo','Suggested: {0} · pick a type to confirm it'],
unreachable:['Dashboard non raggiungibile.','Dashboard unreachable.'],refreshFailed:['Aggiornamento non riuscito.','Refresh failed.'],saveFailed:['Salvataggio non riuscito.','Could not save.'],opFailed:['Operazione non riuscita.','Operation failed.'],
staleMsg:['Dati {0} non aggiornati da {1} s: mostro l\'ultima lettura valida','{0} data not updated for {1} s: showing the last valid reading'],showHistory:['Mostra lo storico','Show history'],
never:['mai visto','never seen'],now:['ora','now'],minAgo:['{0} min fa','{0} min ago'],hAgo:['{0} h fa','{0} h ago'],dAgo:['{0} g fa','{0} d ago'],underMin:['meno di 1 min','under 1 min'],dayUnit:['g','d'],
seenAgo:['visto {0}','seen {0}'],neverOnline:['mai visto online','never seen online'],notConnectedLink:['Non connesso · {0}','Not connected · {0}'],alsoOpalMac:['visto anche come MAC Opal','also seen as the Opal\'s MAC'],
noLabel:['Senza label','No label'],noIP:['IP non disponibile','IP unavailable'],
localNet:['Rete locale','Local network'],statusUnavailable:['Stato non disponibile','Status unavailable'],gEth:['Ethernet RJ45','Ethernet RJ45'],g5:['Wi-Fi 5 GHz · AX55','Wi-Fi 5 GHz · AX55'],
g2:['Wi-Fi 2.4 GHz · AX55','Wi-Fi 2.4 GHz · AX55'],gIot:['Wi-Fi IoT · AX55','Wi-Fi IoT · AX55'],gGuest:['Wi-Fi ospiti · AX55','Wi-Fi guest · AX55'],
uplinkTip:['Mostra lo storico dell\'uplink','Show the uplink history'],uplinkArrow:['↓ uplink 5 GHz','↓ 5 GHz uplink'],
opalWired:['Opal · RJ45','Opal · RJ45'],opalChan:['canale {0} · {1} {2}','channel {0} · {1} {2}'],noClients:['Nessun client associato','No associated clients'],
unkConnected:['Connessi, collegamento non determinato','Connected, link undetermined'],offTitle:['Non connessi','Not connected'],
noRoom:['Senza stanza','No room'],unclassified:['Non classificati','Unclassified'],noDevices:['Nessun dispositivo.','No devices.'],
allTypes:['Tutti i tipi','All types'],allRooms:['Tutte le stanze','All rooms'],unclassifiedIcon:['Non classificato','Unclassified'],suggestedTag:['(suggerito)','(suggested)'],
unknown:['sconosciuto','unknown'],otherAP:['altro AP','other AP'],
tkWired:['cavo','wired'],tkGuest:['ospiti','guest'],tkUndet:['non determinato','undetermined'],themeToLight:['☀ Tema chiaro','☀ Light theme'],themeToDark:['☾ Tema scuro','☾ Dark theme'],themeAria:['Cambia tema chiaro o scuro','Toggle light or dark theme'],copyIp:['Copia IP {0}','Copy IP {0}'],copyMac:['Copia MAC {0}','Copy MAC {0}'],copied:['Copiato: {0}','Copied: {0}'],copyFailed:['Impossibile copiare. Prova a selezionare e copiare manualmente.','Could not copy. Try selecting and copying manually.'],clearFilters:['Azzera filtri','Clear filters'],clearFiltersTitle:['Azzera ricerca e filtri','Reset search and filters'],thStatus:['Stato','Status'],thTx:['TX Mbps','TX Mbps'],thRx:['RX Mbps','RX Mbps'],statusOnline:['Online','Online'],statusOffline:['Offline','Offline'],noResults:['Nessun dispositivo corrisponde alla ricerca e ai filtri.','No devices match the search and filters.'],tableScrollHint:['Su schermi piccoli, scorri orizzontalmente la tabella per vedere tutte le colonne.','On small screens, scroll horizontally to see all columns.']};
const I={it:{},en:{}};for(const[k,[a,b]]of Object.entries(T)){I.it[k]=a;I.en[k]=b}

let LANG='';try{LANG=localStorage.getItem('lang')||''}catch(e){}
if(!I[LANG])LANG=(navigator.language||'').toLowerCase().startsWith('it')?'it':'en';
let THEME='dark';try{THEME=localStorage.getItem('theme')||'dark'}catch(e){}if(!['dark','light'].includes(THEME))THEME='dark';
const LOC=()=>LANG==='it'?'it-IT':'en-GB';
const t=(k,...a)=>{let s=I[LANG][k]??I.en[k]??k;a.forEach((v,i)=>{s=s.split('{'+i+'}').join(v)});return s};
const tx=x=>x&&typeof x==='object'?(x[LANG]||x.en||''):(x??'');   // bilingual server texts: {it, en}

const $=id=>document.getElementById(id);
let S=null,DATA=null,TS=null,EV=null,sortKey='ap',sortDir=1,onlyUnlabeled=false,hist={mac:null,hours:24,res:null,events:[]},pts=[],busy=false;

const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));


function applyStatic(){document.documentElement.lang=LANG;document.title=t('title');
 document.querySelectorAll('[data-i]').forEach(e=>{e.textContent=t(e.dataset.i)});
 document.querySelectorAll('[data-iph]').forEach(e=>{e.placeholder=t(e.dataset.iph)});
  document.querySelectorAll('[data-it]').forEach(e=>{e.title=t(e.dataset.it)});if($('clearFilters'))$('clearFilters').title=t('clearFiltersTitle');
 document.querySelectorAll('[data-ia]').forEach(e=>e.setAttribute('aria-label',t(e.dataset.ia)));
 $('sub').textContent=t('sub',POLL/1000);if(!busy)$('refreshLabel').textContent=t('refresh');$('unlabeled').textContent=onlyUnlabeled?t('showAll'):t('unlabeledOnly');
  document.querySelectorAll('#langSel button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.l===LANG)));applyTheme()}

// neutral server tokens (e.g. "AX55 · wired") and those of old events stored in Italian
const TOK={wired:'tkWired',guest:'tkGuest',undetermined:'tkUndet'},LEGACY={cavo:'wired',ospiti:'guest','non determinato':'undetermined','non connesso':'undetermined'};
const tokTr=s=>String(s??'').split(' · ').map(p=>{const k=TOK[p]?p:LEGACY[p];return k?t(TOK[k]):p}).join(' · ');

const upl=u=>u==='unknown'?t('unknown'):u==='other AP'?t('otherAP'):(u||'—');
const TH=()=>DATA?.thresholds||{good:-60,warn:-75};
const strength=x=>x==null?'':x>=TH().good?'good':x>TH().warn?'mid':'bad';
const badge=x=>x==null?'<span class="muted">—</span>':`<span class="rssi ${strength(x)}">${esc(x)} dBm</span>`;
const fmt=n=>n==null?'—':Number(n).toLocaleString(LOC(),{maximumFractionDigits:1});
const ago=ts=>{const s=Date.now()/1000-ts;return s<90?t('now'):s<5400?t('minAgo',Math.round(s/60)):s<172800?t('hAgo',Math.round(s/3600)):t('dAgo',Math.round(s/86400))};
const span=s=>s<90?t('underMin'):s<5400?`${Math.round(s/60)} min`:s<172800?`${Math.round(s/3600)} h`:`${Math.round(s/86400)} ${t('dayUnit')}`;
const seen=ts=>ts?t('seenAgo',ago(ts)):t('neverOnline');
const link=d=>d.connected?(d.ap_name?`${d.ap_name}${d.connection?' · '+tx(d.connection):''}`:tokTr(d.ap))+(d.alias&&!d.via?' · '+t('alsoOpalMac'):''):t('notConnectedLink',seen(d.last_seen))+(d.arp?` · ARP Opal: ${d.arp}`:'');
const ICON={pc:'<rect x="3" y="5" width="18" height="11" rx="2"/><path d="M2 20h20"/>',
 server:'<rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01"/>',
 smartphone:'<rect x="7" y="2" width="10" height="20" rx="2.5"/><path d="M11 18h2"/>',
 tv:'<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>',
 camera:'<path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>',
 luce_presa:'<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
 iot:'<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
 rete:'<rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 17h.01M11 17h.01M8 10a6 6 0 0 1 8 0M5.5 7.5a10 10 0 0 1 13 0"/>',
 altro:'<circle cx="12" cy="12" r="9"/><path d="M8 12h.01M12 12h.01M16 12h.01"/>',
 none:'<circle cx="12" cy="12" r="9" stroke-dasharray="3 3"/>'};

const icon=(k,auto,label)=>`<svg class="ic${k?'':' none'}${auto?' auto':''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="${esc(label||'')}"><title>${esc(label||'')}</title>${ICON[k]||ICON.none}</svg>`;
const typeName=k=>tx((DATA?.types||{})[k])||k;
const iconFor=d=>icon(d.kind,d.kind_auto,d.kind?typeName(d.kind)+(d.kind_auto?' '+t('suggestedTag'):''):t('unclassifiedIcon'));
const kindLabel=d=>d.kind?typeName(d.kind)+(d.kind_auto?' (?)':''):'';
const rates=d=>d.tx==null&&d.rx==null?'—':`${fmt(d.tx)} / ${fmt(d.rx)} Mbps`;
const notice=(k,cls)=>`<div class="notice${cls?' '+cls:''}">${esc(t(k))}</div>`;

async function api(url,opts={}){const r=await fetch(url,{cache:'no-store',...opts,headers:{'X-Requested-With':'dashboard',...(opts.headers||{})}});if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}

async function refresh(){try{const s=await api('/api/data'+(TS?`?since=${TS}`:''));if(!s.unchanged)render(s)}catch(e){$('errors').innerHTML=notice('unreachable')}}

async function refreshNow(){const b=$('refreshBtn');busy=true;b.disabled=true;b.classList.add('is-busy');$('refreshLabel').textContent=t('refreshing');try{render(await api('/api/refresh',{method:'POST'}))}catch(e){$('errors').innerHTML=notice('refreshFailed')}finally{busy=false;b.disabled=false;b.classList.remove('is-busy');$('refreshLabel').textContent=t('refresh')}}

function render(s){S=s;TS=s.ts;paint();if($('evPanel').open)loadEvents();if(!$('historyPanel').hidden)loadHistory()}

function paint(){const s=S;if(!s)return;DATA=s.data;const ds=DATA?.devices||[],live=ds.filter(d=>d.connected);
 $('updated').textContent=s.ts?t('updatedAt',new Date(s.ts*1000).toLocaleTimeString(LOC())):t('connecting');
 $('fulltime').textContent=s.ts?new Date(s.ts*1000).toLocaleString(LOC()):'—';
 $('errors').innerHTML=Object.entries(s.errors||{}).map(([k,v])=>`<div class="notice"><b>${esc(k)}</b> · ${esc(v)}</div>`).join('');
 const names={router:'AX55 (Home Assistant)',opal:'Opal'};
 $('alerts').innerHTML=[...(DATA?.alerts||[]),...Object.entries(DATA?.stale||{}).map(([k,v])=>({level:'warn',text:t('staleMsg',names[k]||k,v)}))].map(a=>`<div class="notice ${esc(a.level)}"${a.mac?` data-mac="${esc(a.mac)}" tabindex="0" role="button" style="cursor:pointer" title="${esc(t('showHistory'))}"`:''}>${esc(tx(a.text))}</div>`).join('');
 const ax=live.filter(d=>['wired','w5','w2','iot','guest'].includes(d.group)),ow=live.filter(d=>d.group==='opal'),ocab=live.filter(d=>d.group==='opal_wired');
 $('count').textContent=live.length;$('countSub').textContent=t('countSub',ds.length);$('axcount').textContent=ax.length;
 $('opcount').textContent=ow.length+ocab.length;$('opSub').textContent=t('opSub',ow.length,ocab.length);
 const o=DATA?.opal,sig=o?.sta?.signal,rs=ow.filter(d=>d.rssi!=null);
 $('uplinkNum').innerHTML=sig==null?'—':`<span class="${strength(sig)}">${sig} dBm</span>`;
 $('uplinkSub').textContent=o?[o.snr!=null?t('snr',o.snr):'',rs.length?t('worst',Math.min(...rs.map(d=>d.rssi))):''].filter(Boolean).join(' · ')||'\u00a0':t('opalDown');
 fillFilters();drawTopology();drawTable();renderDiag(s.health)}

function renderDiag(h){if(!h)return;const src=Object.values(h.sources),bad=src.filter(x=>x.ok===false).length;
 $('diagRows').innerHTML=src.map(x=>`<tr><td>${esc(x.label)}</td><td><span class="${x.ok==null?'muted':x.ok?'good':'bad'}">${x.ok==null?t(x.detail?'stDisabled':'stWaiting'):x.ok?'● ok':t('stError')}</span></td><td>${x.last_ok?esc(ago(x.last_ok)):'—'}</td><td>${x.duration!=null?fmt(x.duration)+' s':'—'}</td><td>${x.ok===false?`<span class="bad">${esc(x.last_error)}</span>`:esc(tx(x.detail)||'—')}</td><td>${x.fails||0}</td></tr>`).join('');
 $('diagSum').textContent=bad?t('diagBad',bad):t('diagOk');
 $('diagFoot').textContent=t('diagFoot',h.cycle,h.poll,span(Date.now()/1000-h.started))}

function copyButton(value,kind){if(value==null||value==='')return '';const key=kind==='ip'?'copyIp':'copyMac';return `<button type="button" class="copy-btn" data-copy-value="${esc(value)}" data-copy-kind="${kind}" title="${esc(t(key,value))}" aria-label="${esc(t(key,value))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg><span class="sr-only">${esc(t(key,value))}</span></button>`}

function copyCell(value,kind){return value?`<span class="copy-cell"><span class="copy-value">${esc(value)}</span>${copyButton(value,kind)}</span>`:'<span class="muted">—</span>'}

function card(d){return `<div class="device${d.connected?'':' off'}" data-mac="${esc(d.mac)}" tabindex="0" role="button"><div class="dtop"><span class="dname" title="${esc(d.name)}">${iconFor(d)}${esc(d.name||t('noLabel'))}</span>${badge(d.rssi)}</div><div class="dmeta dmeta-copy"><span>IP · ${esc(d.ip||t('noIP'))}</span>${copyButton(d.ip,'ip')}</div><div class="dmeta dmeta-copy"><span>MAC · ${esc(d.mac)}</span>${copyButton(d.mac,'mac')}</div><div class="dmeta">${esc([d.connected?(tx(d.via)||d.band):seen(d.last_seen),d.room,kindLabel(d)].filter(Boolean).join(' · '))}</div></div>`}
const grp=(cls,title,list)=>list.length?`<div class="group ${cls}"><h3>${title} <span>· ${list.length}</span></h3><div class="device-grid">${list.map(card).join('')}</div></div>`:'';
let VIEW='net',FSIG='';try{VIEW=localStorage.getItem('view')||'net'}catch(e){}

function syncView(){document.querySelectorAll('#viewSel button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===VIEW)))}

function drawGroups(){const ds=DATA.devices,T=DATA.types||{},key=VIEW==='room'?d=>d.room||'':d=>d.kind||'',m=new Map(),loc=LOC();
 for(const d of ds){const k=key(d);if(!m.has(k))m.set(k,[]);m.get(k).push(d)}
 const order=VIEW==='kind'?[...Object.keys(T),'']:[...[...m.keys()].filter(Boolean).sort((a,b)=>a.localeCompare(b,loc)),''];
 const title=k=>k===''?t(VIEW==='room'?'noRoom':'unclassified'):(VIEW==='kind'?typeName(k):k);
 return order.filter(k=>m.has(k)).map(k=>{const l=m.get(k).sort((a,b)=>(b.connected-a.connected)||(a.name||'').localeCompare(b.name||'',loc)),on=l.filter(d=>d.connected).length;
  return `<div class="group g-ax"><h3>${VIEW==='kind'?icon(k||null,false,title(k)):''}${esc(title(k))} <span>· ${on}/${l.length} online</span></h3><div class="device-grid">${l.map(card).join('')}</div></div>`}).join('')||`<div class="empty">${esc(t('noDevices'))}</div>`}

function fillFilters(){const ds=DATA?.devices||[],T=DATA?.types||{},rooms=[...new Set(ds.map(d=>d.room).filter(Boolean))].sort((a,b)=>a.localeCompare(b,LOC())),n=ds.filter(d=>d.kind_auto).length;
 const b=$('applySug');b.hidden=!n;b.textContent=t('applySug',n);
 const sig=JSON.stringify([T,rooms,LANG]);if(sig===FSIG)return;FSIG=sig;const tf=$('typeFilter'),rf=$('roomFilter'),tv=tf.value,rv=rf.value;
 tf.innerHTML=`<option value="all">${esc(t('allTypes'))}</option>`+Object.keys(T).map(k=>`<option value="${esc(k)}">${esc(typeName(k))}</option>`).join('')+`<option value="none">${esc(t('unclassified'))}</option>`;
 rf.innerHTML=`<option value="all">${esc(t('allRooms'))}</option>`+rooms.map(r=>`<option value="${esc(r)}">${esc(r)}</option>`).join('')+`<option value="none">${esc(t('noRoom'))}</option>`;
 tf.value=[...tf.options].some(o=>o.value===tv)?tv:'all';rf.value=[...rf.options].some(o=>o.value===rv)?rv:'all';
 $('roomList').innerHTML=rooms.map(r=>`<option value="${esc(r)}">`).join('')}

function drawTopology(){if(!DATA)return;if(VIEW!=='net'){$('topology').innerHTML=drawGroups();return}const ds=DATA.devices,by=g=>ds.filter(d=>d.group===g&&d.connected);
 let h=`<div class="router core-router"><div class="node"><div class="node-title">Internet</div><small>${esc(t('localNet'))}</small></div><span class="arrow">⟷</span><div class="node"><div class="node-title">TP-Link Archer AX55</div><small>${esc(tx(DATA.router.fw)||t('statusUnavailable'))}</small></div></div>`;
 h+=grp('g-wired',t('gEth'),by('wired'))+grp('g-ax',t('g5'),by('w5'))+grp('g-ax',t('g2'),by('w2'))+grp('g-ax',t('gIot'),by('iot'))+grp('g-ax',t('gGuest'),by('guest'));
 const o=DATA.opal;if(o){const w=by('opal'),c=by('opal_wired');
  h+=`<div class="router"><span class="arrow">${esc(t('uplinkArrow'))} ${badge(o.sta?.signal)}</span><div class="node opalnode" data-mac="opal:uplink" tabindex="0" role="button" title="${esc(t('uplinkTip'))}"><div class="node-title">GL.iNet Opal</div><small>uplink: ${esc(upl(o.uplink))} · ${esc(o.sta?.essid||'')}</small><small>${esc(o.sta?.bssid||'')}</small></div></div>`;
  h+=grp('g-wired',t('opalWired'),c)+`<div class="group g-opal"><h3>Opal · Wi-Fi 2.4 GHz · ${esc(o.ap?.essid||'')} <span>${esc(t('opalChan',o.ap?.channel??'—',w.length,t(w.length===1?'client1':'clientN')))}</span></h3><div class="device-grid">${w.map(card).join('')||`<span class="empty">${esc(t('noClients'))}</span>`}</div></div>`}
 const unk=ds.filter(d=>d.connected&&d.group==='unknown'),off=ds.filter(d=>!d.connected);
 h+=grp('',t('unkConnected'),unk);
 if(off.length)h+=`<details class="group" style="grid-column:1/-1"><summary>${esc(t('offTitle'))} <span>· ${off.length}</span></summary><div class="device-grid">${off.map(card).join('')}</div></details>`;
 const prev=document.querySelector('#topology details')?.open;$('topology').innerHTML=h;if(prev)document.querySelector('#topology details')?.setAttribute('open','')}
const IPN=ip=>{if(!ip)return null;const p=String(ip).split('.');return p.length===4&&p.every(n=>/^\d{1,3}$/.test(n)&&Number(n)<=255)?p.reduce((a,n)=>a*256+(+n),0):null};
const SORT={name:d=>d.name||'',status:d=>d.connected?0:1,ip:d=>d.ip||'',mac:d=>d.mac||'',kind:d=>kindLabel(d)||'',room:d=>d.room||'',ap:d=>link(d)||'',band:d=>d.connected?(tx(d.via)||d.band||''):'',ssid:d=>d.ssid||'',rssi:d=>d.rssi,tx:d=>d.tx,rx:d=>d.rx};

function compareRows(a,b){const get=SORT[sortKey]||SORT.name,x=get(a),y=get(b);const empty=x==null||x==='',emptyY=y==null||y==='';if(empty||emptyY)return empty===emptyY?0:(empty?1:-1);if(sortKey==='ip'){const nx=IPN(x),ny=IPN(y);if(nx!==null&&ny!==null)return(nx<ny?-1:nx>ny?1:0)*sortDir}if(typeof x==='number'&&typeof y==='number')return(x<y?-1:x>y?1:0)*sortDir;return String(x).localeCompare(String(y),LOC(),{numeric:true,sensitivity:'base'})*sortDir}

function drawTable(){if(!DATA)return;const q=$('filter').value.toLowerCase(),cf=$('connectionFilter').value,tf=$('typeFilter').value||'all',rf=$('roomFilter').value||'all';
 let ds=DATA.devices.filter(d=>(!onlyUnlabeled||!d.labeled)&&(cf==='all'||(cf==='connected')===d.connected)&&(tf==='all'||(tf==='none'?!d.kind:d.kind===tf))&&(rf==='all'||(rf==='none'?!d.room:d.room===rf))&&[d.name,d.ip,d.mac,link(d),d.ssid,d.band,d.room,kindLabel(d)].join(' ').toLowerCase().includes(q));
  ds.sort(compareRows);
 document.querySelectorAll('#head th').forEach(th=>{const b=th.querySelector('button');if(!b)return;const on=b.dataset.k===sortKey;th.setAttribute('aria-sort',on?(sortDir>0?'ascending':'descending'):'none');b.textContent=b.textContent.replace(/ [▲▼]$/,'')+(on?(sortDir>0?' ▲':' ▼'):'')});
 $('shown').textContent=t(ds.length===1?'devOne':'devMany',ds.length);
 $('rows').innerHTML=ds.length?ds.map(d=>`<tr class="${d.connected?'':'off'}" data-mac="${esc(d.mac)}" tabindex="0"><td><b>${esc(d.name||'—')}</b> <button type="button" class="rename" title="${esc(t('renameTitle'))}" aria-label="${esc(t('renameAria',d.name||d.mac))}">✎</button></td><td><span class="status-pill ${d.connected?'online':'offline'}">${esc(t(d.connected?'statusOnline':'statusOffline'))}</span></td><td>${copyCell(d.ip,'ip')}</td><td>${copyCell(d.mac,'mac')}</td><td title="${d.kind_auto?esc(t('suggestedRow')):''}">${iconFor(d)}${esc(kindLabel(d)||'—')}</td><td>${esc(d.room||'—')}</td><td>${esc(link(d))}</td><td>${esc(d.connected?(tx(d.via)||d.band||'—'):'—')}</td><td>${esc(d.ssid||'—')}</td><td>${badge(d.rssi)}</td><td>${fmt(d.tx)}</td><td>${fmt(d.rx)}</td></tr>`).join(''):`<tr><td class="empty-cell" colspan="12">${esc(t('noResults'))}</td></tr>`}

function openEdit(mac){const d=DATA?.devices.find(x=>x.mac===mac);if(!d)return;$('dlg').dataset.mac=mac;$('dlgMac').textContent=mac;$('dlgName').value=d.name||'';
 $('dlgKind').innerHTML=`<option value="">${esc(t('kindAuto'))}</option>`+Object.keys(DATA.types||{}).map(k=>`<option value="${esc(k)}">${esc(typeName(k))}</option>`).join('');
 $('dlgKind').value=d.kind_auto?'':(d.kind||'');$('dlgHint').textContent=d.kind_auto?t('hintSuggested',typeName(d.kind)):'';
 $('dlgRoom').value=d.room||'';$('dlg').showModal();$('dlgName').select()}

async function saveEdit(){const mac=$('dlg').dataset.mac,name=$('dlgName').value,type=$('dlgKind').value,room=$('dlgRoom').value,j=b=>({method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
 try{await Promise.all([api('/api/names/'+encodeURIComponent(mac),j({name})),api('/api/meta/'+encodeURIComponent(mac),j({type,room}))]);
  const d=DATA.devices.find(x=>x.mac===mac);if(d){if(name.trim())d.name=name.trim();d.room=room.trim();if(type){d.kind=type;d.kind_auto=false}else if(!d.kind_auto)d.kind=null}
  fillFilters();drawTopology();drawTable();setTimeout(refresh,8000)}catch(e){$('errors').innerHTML=notice('saveFailed')}}

async function applySuggestions(){if(!confirm(t('confirmApply')))return;
 try{await api('/api/meta/apply-suggestions',{method:'POST'});for(const d of DATA.devices)d.kind_auto=false;fillFilters();drawTopology();drawTable();setTimeout(refresh,8000)}catch(e){$('errors').innerHTML=notice('opFailed')}}

async function loadHistory(){const {mac,hours}=hist;try{const [r,e]=await Promise.all([api(`/api/history?mac=${encodeURIComponent(mac)}&hours=${hours}`),api(`/api/events?mac=${encodeURIComponent(mac)}&hours=${hours}`).catch(()=>({events:[]}))]);hist.res=r;hist.events=e.events||[];drawChart(r)}catch(e){hist.res=null}}
let evHours=24;const KIND={move_ap:['kMoveAp','mid'],move_band:['kMoveBand','mid'],connect:['kConnect','good'],disconnect:['kDisconnect','bad']};

async function loadEvents(){try{EV=await api(`/api/events?hours=${evHours}`);drawEvents(EV)}catch(e){$('evList').innerHTML=`<tr><td colspan="4" class="bad">${esc(t('evUnavailable'))}</td></tr>`}}

function drawEvents(r){const tt=r.totals||{},when=ts=>new Date(ts*1000).toLocaleString(LOC(),{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'});
 $('evSum').textContent=t('evSum',(tt.move_ap||0)+(tt.move_band||0),tt.disconnect||0,evHours>24?t('nDays',evHours/24):t('nHours',evHours));
 $('evTop').innerHTML=r.summary.length?r.summary.map(x=>`<tr data-mac="${esc(x.mac)}" tabindex="0" style="cursor:pointer"><td><b>${esc(x.name||x.mac)}</b></td><td>${x.move_ap}</td><td>${x.move_band}</td><td>${x.disconnect}</td></tr>`).join(''):`<tr><td colspan="4" class="empty">${esc(t('evNone'))}</td></tr>`;
 $('evList').innerHTML=r.events.length?r.events.map(e=>{const k=KIND[e.kind]||[null,''];return `<tr data-mac="${esc(e.mac)}" tabindex="0" style="cursor:pointer"><td class="mono">${when(e.ts)}</td><td><b>${esc(e.name||e.mac)}</b></td><td><span class="${k[1]}">${esc(k[0]?t(k[0]):e.kind)}</span></td><td>${esc(e.src?tokTr(e.src):'—')} → ${esc(e.dst?tokTr(e.dst):'—')}</td></tr>`}).join(''):`<tr><td colspan="4" class="empty">${esc(t('evNoEvents'))}</td></tr>`}
const histTitle=()=>t('histTitle',hist.mac==='opal:uplink'?t('uplinkName'):(DATA?.devices.find(x=>x.mac===hist.mac)?.name||hist.mac));

function showHistory(mac){hist.mac=mac;$('historyPanel').hidden=false;$('historyTitle').textContent=histTitle();syncRanges();$('historyPanel').scrollIntoView({behavior:'smooth',block:'nearest'});loadHistory()}

function syncRanges(){document.querySelectorAll('#ranges button').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.h===hist.hours)))}

function drawChart(r){const c=$('chart'),ctx=c.getContext('2d'),w=c.clientWidth,h=c.clientHeight,dpr=devicePixelRatio||1,cs=getComputedStyle(document.documentElement),col=n=>cs.getPropertyValue(n).trim(),loc=LOC();
 c.width=w*dpr;c.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);pts=[];ctx.font='11px system-ui';ctx.fillStyle=col('--muted');
 if(!r||!r.points.length){ctx.fillText(t('chartEmpty'),12,32);return}
 const L=48,R=10,T=10,B=22,t1=Date.now()/1000,t0=t1-r.hours*3600,vs=r.points.map(p=>p[1]),lo=Math.min(-90,Math.floor(Math.min(...vs)/5)*5),hi=Math.max(-40,Math.ceil(Math.max(...vs)/5)*5);
 const X=t=>L+(t-t0)/(t1-t0)*(w-L-R),Y=v=>T+(hi-v)/(hi-lo)*(h-T-B);
 ctx.strokeStyle=col('--line');ctx.lineWidth=1;for(let v=Math.ceil(lo/10)*10;v<=hi;v+=10){ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(w-R,Y(v));ctx.stroke();ctx.fillText(v+' dBm',2,Y(v)+4)}
 for(let i=0;i<=4;i++){const tm=t0+(t1-t0)*i/4,d=new Date(tm*1000),hm=d.toLocaleTimeString(loc,{hour:'2-digit',minute:'2-digit'});ctx.textAlign=i===4?'right':i===0?'left':'center';ctx.fillText(r.hours>24?d.toLocaleDateString(loc,{day:'numeric',month:'short'})+' '+hm:hm,X(tm),h-6)}ctx.textAlign='left';
 for(const e of hist.events||[]){if(e.ts<t0)continue;const x=X(e.ts);ctx.strokeStyle=e.kind==='disconnect'?col('--red'):e.kind==='connect'?col('--green'):col('--violet');ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(x,T);ctx.lineTo(x,h-B);ctx.stroke()}
 ctx.setLineDash([4,4]);ctx.strokeStyle=col('--amber');ctx.beginPath();ctx.moveTo(L,Y(TH().warn));ctx.lineTo(w-R,Y(TH().warn));ctx.stroke();ctx.setLineDash([]);
 ctx.strokeStyle=col('--blue');ctx.lineWidth=2;ctx.beginPath();let prev=null;
 for(const [tm,v] of r.points){prev!==null&&tm-prev<=r.bucket*2.5?ctx.lineTo(X(tm),Y(v)):ctx.moveTo(X(tm),Y(v));prev=tm;pts.push({x:X(tm),y:Y(v),t:tm,v})}ctx.stroke();
 ctx.fillStyle=col('--blue');if(pts.length<200)pts.forEach(p=>{ctx.beginPath();ctx.arc(p.x,p.y,2,0,7);ctx.fill()})}
const tip=$('tip');
$('chart').addEventListener('pointermove',e=>{if(!pts.length)return;const x=e.offsetX;let best=pts[0];for(const p of pts)if(Math.abs(p.x-x)<Math.abs(best.x-x))best=p;
 tip.hidden=false;tip.textContent=`${best.v} dBm · ${new Date(best.t*1000).toLocaleString(LOC(),{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})}`;
 tip.style.left=Math.min(best.x+10,$('chart').clientWidth-tip.offsetWidth-4)+'px';tip.style.top=Math.max(best.y-34,0)+'px'});
$('chart').addEventListener('pointerleave',()=>tip.hidden=true);
new ResizeObserver(()=>{if(!$('historyPanel').hidden&&hist.res)drawChart(hist.res)}).observe($('chart'));

function applyTheme(){document.documentElement.dataset.theme=THEME;document.documentElement.style.colorScheme=THEME;const b=$('themeToggle');if(b){const key=THEME==='dark'?'themeToLight':'themeToDark';b.textContent=t(key);b.title=t(key);b.setAttribute('aria-pressed',String(THEME==='dark'));b.setAttribute('aria-label',t('themeAria'))}if(hist?.res&&!$('historyPanel').hidden)drawChart(hist.res)}
let toastTimer=null;function showToast(message){const el=$('toast');if(!el)return;el.textContent=message;el.dataset.show='true';clearTimeout(toastTimer);toastTimer=setTimeout(()=>{el.dataset.show='false'},1900)}

function fallbackCopy(value){const ta=document.createElement('textarea');ta.value=value;ta.setAttribute('readonly','');ta.style.position='fixed';ta.style.opacity='0';ta.style.left='-9999px';document.body.appendChild(ta);ta.select();let ok=false;try{ok=document.execCommand('copy')}catch(e){}ta.remove();return ok}

async function copyToClipboard(value,kind){if(!value)return;let ok=false;try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(value);ok=true}else ok=fallbackCopy(value)}catch(e){ok=fallbackCopy(value)}showToast(ok?t('copied',kind==='ip'?'IP':'MAC'):t('copyFailed'))}

function setLang(l){LANG=l;try{localStorage.setItem('lang',l)}catch(e){}applyStatic();paint();if(EV)drawEvents(EV);if(hist.res)drawChart(hist.res);if(hist.mac)$('historyTitle').textContent=histTitle()}

// events (delegated: no inline onclick, everything reachable from the keyboard)
const target=e=>e.target.closest('[data-mac]');

function activate(e){const cb=e.target.closest('.copy-btn');if(cb){e.preventDefault();e.stopPropagation();copyToClipboard(cb.dataset.copyValue,cb.dataset.copyKind);return}const r=e.target.closest('.rename');if(r){e.preventDefault();e.stopPropagation();openEdit(r.closest('tr').dataset.mac);return}const tg=target(e);if(tg)showHistory(tg.dataset.mac)}
for(const id of ['topology','rows','evTop','evList','alerts'])$(id).addEventListener('click',activate);
for(const id of ['topology','rows','evTop','evList','alerts'])$(id).addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&!e.target.closest('button')){e.preventDefault();activate(e)}});
$('head').addEventListener('click',e=>{const b=e.target.closest('button[data-k]');if(!b)return;sortDir=sortKey===b.dataset.k?-sortDir:1;sortKey=b.dataset.k;drawTable()});
$('filter').addEventListener('input',drawTable);$('connectionFilter').addEventListener('change',drawTable);
$('unlabeled').addEventListener('click',()=>{onlyUnlabeled=!onlyUnlabeled;$('unlabeled').setAttribute('aria-pressed',onlyUnlabeled);$('unlabeled').textContent=onlyUnlabeled?t('showAll'):t('unlabeledOnly');drawTable()});
$('ranges').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;hist.hours=+b.dataset.h;syncRanges();loadHistory()});
$('evPanel').addEventListener('toggle',()=>{if($('evPanel').open)loadEvents()});
$('evRanges').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;evHours=+b.dataset.h;document.querySelectorAll('#evRanges button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));loadEvents()});
$('closeHistory').addEventListener('click',()=>$('historyPanel').hidden=true);
$('refreshBtn').addEventListener('click',refreshNow);
$('themeToggle').addEventListener('click',()=>{THEME=THEME==='dark'?'light':'dark';try{localStorage.setItem('theme',THEME)}catch(e){}applyTheme()});
$('clearFilters').addEventListener('click',()=>{$('filter').value='';$('connectionFilter').value='all';$('typeFilter').value='all';$('roomFilter').value='all';onlyUnlabeled=false;$('unlabeled').setAttribute('aria-pressed','false');$('unlabeled').textContent=t('unlabeledOnly');drawTable()});
$('typeFilter').addEventListener('change',drawTable);$('roomFilter').addEventListener('change',drawTable);$('applySug').addEventListener('click',applySuggestions);
$('editHist').addEventListener('click',()=>{if(hist.mac&&hist.mac!=='opal:uplink')openEdit(hist.mac)});
$('viewSel').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;VIEW=b.dataset.v;try{localStorage.setItem('view',VIEW)}catch(x){}syncView();drawTopology()});
$('langSel').addEventListener('click',e=>{const b=e.target.closest('button');if(b&&b.dataset.l!==LANG)setLang(b.dataset.l)});
$('dlgCancel').addEventListener('click',()=>$('dlg').close('cancel'));
$('dlg').addEventListener('close',()=>{if($('dlg').returnValue==='ok')saveEdit()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
applyStatic();syncView();syncRanges();
refresh();setInterval(()=>{if(!document.hidden)refresh()},POLL);
