'use strict';
const $ = id => document.getElementById(id);
const state = { key:'', authenticated:false, user:null, config:null, accounts:[], beneficiaries:[], driveOrders:[], driveOrderPreview:null, selectedDriveOrders:[], batchOrderPreview:null, kind:'transferencia', preview:null, fciPreview:null, fciAccounts:[], fciFunds:[], movements:null, movementPage:1, busy:false };
const money = (v, currency='ARS') => new Intl.NumberFormat('es-AR',{style:'currency',currency,minimumFractionDigits:2}).format(Number(v));
const dateLabel = v => !v ? '—' : /^\d{8}$/.test(v) ? `${v.slice(6,8)}/${v.slice(4,6)}/${v.slice(0,4)}` : /^\d{4}-\d{2}-\d{2}$/.test(v) ? v.split('-').reverse().join('/') : String(v);
const dateTimeLabel = v => {const match=String(v||'').match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);return match?`${match[3]}/${match[2]}/${match[1]} ${match[4]}:${match[5]}`:dateLabel(v);};
const operationSummary = item => item.resumen||{};
const operationLabel = kind => ({transferencia:'Transferencia · TRB',echeq:'eCheq · CHE',echeq_gestion:'Gestión eCheq',fci_suscripcion:'Suscripción FCI',fci_rescate:'Rescate FCI'}[kind]||kind||'—');
const operationBeneficiary = item => operationSummary(item).beneficiario||item.resultado?.data?.beneficiarioNombre||item.resultado?.data?.nombre||'—';
const operationAmount = item => {const value=operationSummary(item).importe;return value?money(value,operationSummary(item).moneda||'ARS'):'—';};
const localDate = value => `${value.getFullYear()}-${String(value.getMonth()+1).padStart(2,'0')}-${String(value.getDate()).padStart(2,'0')}`;
const normalName = v => v.normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-zA-Z0-9 ]/g,'').trim().toUpperCase();
const message = (text,type='neutral') => {
  const notice=document.querySelector('.order-dialog[open] .review-notice')||$('notice');
  notice.textContent=text;notice.className=`${notice.id==='notice'?'':'review-notice '}notice ${type}`;notice.hidden=false;
};
const newId = () => crypto.randomUUID();
const el = (tag,text,cls) => {const x=document.createElement(tag);if(text!==undefined)x.textContent=String(text);if(cls)x.className=cls;return x;};
let reauthTimer=null,reauthDeadline=0,sessionLocked=false;
function scheduleReauthentication(seconds){
  clearTimeout(reauthTimer);
  reauthDeadline=Date.now()+Math.max(0,Number(seconds)||0)*1000;
  reauthTimer=setTimeout(lockSession,Math.max(0,reauthDeadline-Date.now()));
}
function lockSession(){
  if(!state.authenticated||!state.user||sessionLocked)return;
  sessionLocked=true;clearTimeout(reauthTimer);
  clearDriveOrderPreview();clearDriveBatchPreview();clearPreview();clearFciPreview();
  document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
  $('reauth-username').value=state.user.username;$('reauth-password').value='';$('reauth-error').hidden=true;
  $('reauth-dialog').showModal();$('reauth-password').focus();
}
function checkSessionDeadline(){if(state.authenticated&&reauthDeadline&&Date.now()>=reauthDeadline)lockSession();}
window.addEventListener('focus',checkSessionDeadline);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkSessionDeadline();});
async function api(path, options={}) {
  if(!state.authenticated)throw Error('Iniciá sesión para usar el sistema.');
  checkSessionDeadline();
  if(sessionLocked)throw Error('Ingresá tu contraseña para desbloquear la sesión.');
  const headers = {...options.headers};
  if(state.key)headers['X-API-Key']=state.key;
  if(options.body&&!(options.body instanceof FormData))headers['Content-Type']='application/json';
  let response;
  try {response=await fetch(path,{...options,headers,credentials:'same-origin'});}catch{throw Error('No se obtuvo respuesta del servicio local. Si estabas enviando, consultá el registro antes de repetir.');}
  let data;
  try{data=await response.json();}catch{throw Error('El servicio devolvió una respuesta inesperada. Si era un envío, consultá el estado antes de repetir.');}
  if(!response.ok){
    if(response.status===428||(response.status===401&&path!=='/auth/password'))lockSession();
    const detail=data.error||data.detail||'La solicitud no se pudo completar.';
    let text=Array.isArray(detail)?detail.map(x=>`${x.loc.join('.')}: ${x.msg}`).join(' · '):String(detail);
    if(data.detalle_banco)text+=' '+JSON.stringify(data.detalle_banco);
    if(data.resultado_incierto)text+=' Resultado incierto: no crees otro pago para repetirlo.';
    throw Error(text);
  }
  return data;
}
async function action(button, fn) {
  const wasDisabled=button.disabled;button.disabled=true;
  try{await fn();}catch(e){message(e.message,'error');}finally{button.disabled=wasDisabled;}
}
function clearPreview(){state.preview=null;$('payment-preview').hidden=true;$('confirm-payment').checked=false;$('send-payment').disabled=true;}
function clearFciPreview(){state.fciPreview=null;$('fci-preview').hidden=true;$('fci-confirm').checked=false;$('fci-send').disabled=true;}
function showView(view){
  clearPreview();
  clearFciPreview();
  document.querySelectorAll('.view').forEach(x=>x.hidden=true);
  document.querySelectorAll('.nav').forEach(x=>{
    const active=x.dataset.view===view;x.classList.toggle('active',active);
    if(active)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');
  });
  const titles={dashboard:'Inicio',cuentas:'Cuentas y saldos',movimientos:'Movimientos',transferencias:'Transferencias · TRB',echeqs:'eCheqs · CHE',fci:'Fondos comunes de inversión',usuarios:'Usuarios y auditoría'};
  $('page-title').textContent=titles[view];
  if(view==='transferencias'||view==='echeqs'){
    const oldKind=state.kind;
    state.kind=view==='transferencias'?'transferencia':'echeq';$('view-pago').hidden=false;
    if(oldKind!==state.kind){$('beneficiary-name').value='';$('beneficiary-document').value='';$('beneficiary-cbu').value='';state.selectedDriveOrders=[];clearDriveOrderPreview();clearDriveBatchPreview();}
    const cheque=state.kind==='echeq',method=cheque?'CHE':'TRB';$('payment-heading').textContent=cheque?'Preparar eCheq':'Preparar transferencia';
    $('payment-form').hidden=true;
    $('gecom-method-label').textContent=method;$('gecom-orders-title').textContent=`Órdenes ${method}`;
    state.selectedDriveOrders=state.selectedDriveOrders.filter(id=>state.driveOrders.some(order=>order.source_id===id&&order.method===method));
    renderDriveOrders();
    ['cheque-type-label','cheque-date-label','cheque-character-label'].forEach(id=>$(id).hidden=!cheque);
    $('cbu-label').hidden=cheque;$('beneficiary-cbu').required=!cheque;$('cheque-date').required=cheque;
    populateBeneficiaries();
  }else{$(`view-${view}`).hidden=false;}
  window.scrollTo(0,0);
}
function populateBeneficiaries(){
  const list=$('test-beneficiary');list.replaceChildren(el('option','Elegir beneficiario de prueba'));list.firstChild.value='';
  state.beneficiaries.filter(x=>x.tipo===state.kind).forEach(b=>{const o=el('option',`${b.nombre} · ${b.documento}`);o.value=b.documento+'|'+b.cbuCvu;list.append(o);});
  list.disabled=!state.config?.homologacion;
  $('beneficiary-status').textContent='Verificá que esté en la agenda del adherente.';
}
function chosenAccount(){return state.accounts.find(x=>String(x.nroCuenta)===$('payment-account').value);}
function populateAccounts(){
  for(const id of ['payment-account','movement-account']){
    const select=$(id),prior=select.value;select.replaceChildren();
    const empty=el('option','Elegir una cuenta');empty.value='';select.append(empty);
    state.accounts.forEach(a=>{if(id==='payment-account'&&a.moneda!=='ARS')return;const o=el('option',`${a.nroCuenta} · ${a.moneda} · ${a.tipoCuenta}`);o.value=String(a.nroCuenta);select.append(o);});
    if([...select.options].some(x=>x.value===prior))select.value=prior;
    if(!select.value&&select.options.length===2)select.selectedIndex=1;
  }
}
async function loadAccounts(){
  const data=await api('/cuentas');
  const accounts=data.clarifCuentas||data.clarifcuentas;
  if(!Array.isArray(accounts))throw Error('La respuesta no contiene una lista de cuentas válida.');
  state.accounts=accounts;populateAccounts();
  populateDriveAccounts();
  const cards=$('account-cards'),body=$('accounts-body');cards.replaceChildren();body.replaceChildren();
  $('account-count').textContent=`${accounts.length} cuenta${accounts.length===1?'':'s'}`;
  if(!accounts.length)cards.append(el('div','El banco no devolvió cuentas habilitadas.','empty-card'));
  accounts.forEach(a=>{
    const card=el('div',undefined,'account-card');const top=el('div',undefined,'account-title');top.append(el('span',a.tipoCuenta==='CC'?'CUENTA CORRIENTE':'CAJA DE AHORROS'),el('span',a.moneda,'pill soft'));card.append(top,el('div',money(a.saldo,a.moneda),'balance'),el('div',`${a.denominacionCuenta} · ${a.nroCuenta}`,'account-name'));
    const btn=el('button','Ver movimientos →','text-button');btn.type='button';btn.onclick=()=>{showView('movimientos');$('movement-account').value=String(a.nroCuenta);};card.append(btn);cards.append(card);
    const row=el('tr');[a.nroCuenta,a.denominacionCuenta,a.tipoCuenta,a.moneda,a.CBU||a.cbu||'—',money(a.saldo,a.moneda)].forEach((x,i)=>row.append(el('td',x,i===5?'numeric':undefined)));body.append(row);
  });
}
async function loadDashboard(){
  const data=await api('/dashboard'),cards=$('dashboard-cards'),body=$('dashboard-operations');cards.replaceChildren();body.replaceChildren();
  const fciTotal=(data.saldos_fci||[]).reduce((sum,item)=>sum+(Number(item.saldoDisponibleValorizado)||0),0);
  const summary=[['Cuentas activas',data.cantidad_cuentas],['Saldo FCI',(data.saldos_fci||[]).length?money(fciTotal):'Sin consulta'],['Transferencias a firma',data.transferencias_pendientes_firma],['eCheqs a firma',data.echeqs_pendientes_firma],['Con error',data.operaciones_con_error]];
  const captions=['Habilitadas para operar','Tenencia valorizada consultada','Para autorizar en BIE','Para autorizar en BIE','Revisar antes de reintentar'];
  const icons=['M3 10h18M5 10v9m5-9v9m4-9v9m5-9v9M3 21h18M3 7l9-5 9 5H3', 'M4 18l5-5 4 3 7-10M15 6h5v5', 'M4 8h15m-4-4 4 4-4 4M20 16H5m4-4-4 4 4 4', 'M5 3h14v18l-3-2-4 2-4-2-3 2V3m4 5h6m-6 4h4', 'M12 8v5m0 3v1M12 3 2 21h20L12 3'];
  summary.forEach(([title,value],index)=>{
    const card=el('div',undefined,`account-card kpi-card kpi-${index+1}`),heading=el('div',undefined,'kpi-heading'),icon=el('span',undefined,'kpi-icon');
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');path.setAttribute('d',icons[index]);svg.append(path);icon.append(svg);
    heading.append(el('div',title,'muted'),icon);card.append(heading,el('div',String(value),`balance${value==='Sin consulta'?' no-data':''}`),el('small',captions[index],'kpi-caption'));cards.append(card);
  });
  const pending=Number(data.transferencias_pendientes_firma||0)+Number(data.echeqs_pendientes_firma||0);
  $('dashboard-pending-total').textContent=String(pending);
  const today=state.config?.fecha_actual_argentina||localDate(new Date());
  $('dashboard-date').textContent=new Intl.DateTimeFormat('es-AR',{dateStyle:'full'}).format(new Date(today+'T12:00:00'));
  const accountCards=$('dashboard-account-cards');accountCards.replaceChildren();
  (data.cuentas||[]).forEach(account=>{
    const card=el('div',undefined,'account-card dashboard-balance'),info=el('div',undefined,'dashboard-account-info');
    info.append(el('div',`${account.nroCuenta} · ${account.moneda||''}`,'account-title'),el('div',account.denominacionCuenta||'Cuenta','account-name'));
    const amount=el('div',undefined,'dashboard-account-amount');amount.append(el('small','Saldo de la cuenta'),el('div',money(account.saldo,account.moneda||'ARS'),'balance'));
    card.append(el('span','$','account-symbol'),info,amount);accountCards.append(card);
  });
  if(!accountCards.childElementCount)accountCards.append(el('div','No hay cuentas disponibles para mostrar.','empty-card'));
  const operations=data.operaciones_hoy||[];$('dashboard-operation-count').textContent=`${operations.length} operación(es) hoy`;
  $('dashboard-sync-status').textContent=`Última sincronización: ${data.ultima_sincronizacion_banco?dateTimeLabel(data.ultima_sincronizacion_banco):'sin datos'}`;
  operations.forEach(item=>{const row=el('tr'),result=item.resultado||{},reference=operationBeneficiary(item);[dateTimeLabel(item.actualizado),item.actor,operationLabel(item.tipo),reference,operationAmount(item),result.consulta_estado?.data?.estadoOperacion?.descripcion||result.data?.estadoOperacion?.descripcion||item.estado,item.id_origen].forEach((value,index)=>row.append(el('td',value||'—',index===4?'numeric':undefined)));body.append(row);});
  renderDashboardEmpty(body);
}
function renderDashboardEmpty(body){
  if(body.childElementCount)return;
  const row=el('tr'),cell=el('td',undefined,'dashboard-empty');cell.colSpan=7;
  cell.append(el('strong','Tu actividad de hoy aparecerá acá'),el('span','Las operaciones que prepares se mostrarán con su importe, beneficiario y estado.'));
  row.append(cell);body.append(row);
}
async function loadDayOperations(){
  const date=state.config?.fecha_actual_argentina||new Date().toISOString().slice(0,10);
  const result=await api(`/operaciones?fecha_desde=${date}&fecha_hasta=${date}`),rows=result.operaciones||[],body=$('dashboard-operations');body.replaceChildren();
  $('dashboard-operation-count').textContent=`${rows.length} operación(es) hoy`;
  rows.forEach(item=>{const bankData=item.resultado?.consulta_estado?.data||item.resultado?.data||{},status=bankData.estadoOperacion?.descripcion||item.estado,row=el('tr');
    [dateTimeLabel(item.actualizado),item.actor,operationLabel(item.tipo),operationBeneficiary(item),operationAmount(item),status,item.id_origen].forEach((value,index)=>row.append(el('td',value||'—',index===4?'numeric':undefined)));body.append(row);
  });
  renderDashboardEmpty(body);
}
async function loadUsers(){
  if(state.user?.role!=='admin'){$('user-admin-panel').hidden=true;return;}
  $('user-admin-panel').hidden=false;const data=await api('/usuarios'),body=$('users-body');body.replaceChildren();
  data.usuarios.forEach(user=>{const row=el('tr');[user.username,user.role,user.active?'Activo':'Inactivo',dateLabel(user.last_login_at)].forEach(value=>row.append(el('td',value||'—')));const cell=el('td');
    const toggle=el('button',user.active?'Desactivar':'Reactivar','text-button');toggle.type='button';toggle.onclick=()=>action(toggle,async()=>{await api(`/usuarios/${encodeURIComponent(user.username)}`,{method:'PATCH',body:JSON.stringify({active:!user.active})});await loadUsers();});
    const reset=el('button','Restablecer contraseña','text-button');reset.type='button';reset.onclick=()=>{ $('reset-user-name').value=user.username;$('reset-user-password').value='';$('admin-password-dialog').showModal();};cell.append(toggle,reset);row.append(cell);body.append(row);
  });
}
async function loadAudit(){
  const params=new URLSearchParams();if($('audit-from').value)params.set('fecha_desde',$('audit-from').value);if($('audit-to').value)params.set('fecha_hasta',$('audit-to').value);if($('audit-user').value.trim())params.set('usuario',$('audit-user').value.trim());
  const data=await api('/operaciones?'+params),body=$('audit-body');body.replaceChildren();
  data.operaciones.forEach(item=>{const row=el('tr'),bankData=item.resultado?.consulta_estado?.data||item.resultado?.data||{};[dateTimeLabel(item.actualizado),item.actor,operationLabel(item.tipo),operationBeneficiary(item),operationAmount(item),bankData.estadoOperacion?.descripcion||item.estado,item.id_origen].forEach((value,index)=>row.append(el('td',value??'—',index===4?'numeric':undefined)));body.append(row);});
}
let movementVersion=0,movementQuery=null;
function movementEmpty(title,description){
  const row=el('tr'),cell=el('td',undefined,'movement-empty');cell.colSpan=9;
  cell.append(el('span','⇄','movement-empty-icon'),el('strong',title),el('span',description));row.append(cell);$('movements-body').replaceChildren(row);
}
function clearMovementQuery(){
  movementVersion+=1;movementQuery=null;state.movements=null;state.movementPage=1;
  $('movement-summary').hidden=true;$('movement-kpis').hidden=true;$('export-movements').disabled=true;
  $('movement-page-prev').disabled=true;$('movement-page-next').disabled=true;$('movement-page-label').textContent='Sin consulta';
  $('movement-result-context').textContent='Elegí una cuenta y un período para consultar.';
  movementEmpty('Todo listo para tu consulta','Pulsá Consultar movimientos para ver la actividad de la cuenta y el período elegidos.');
}
function renderMovementRows(){
  if(!state.movements)return;const currency=movementQuery?.currency||'ARS';
  const search=$('movement-search').value.trim().toLocaleLowerCase('es-AR'),rawAmount=$('movement-amount-filter').value.trim(),type=$('movement-type').value;
  const amountSearch=(rawAmount.includes(',')?rawAmount.replace(/\./g,'').replace(',','.'):rawAmount).replace(/[^0-9.]/g,'');
  const rows=state.movements.movimientos.filter(item=>{
    const amount=Number(item.monto)||0,description=String(item.descripcion||'').toLocaleLowerCase('es-AR');
    return (!search||description.includes(search))&&(!amountSearch||Math.abs(amount).toFixed(2).includes(amountSearch))&&(!type||item.indDBCR===type);
  });
  const pageSize=50;state.movementPage=Math.max(1,Math.min(state.movementPage,Math.ceil(rows.length/pageSize)||1));
  const start=(state.movementPage-1)*pageSize,body=$('movements-body');body.replaceChildren();
  rows.slice(start,start+pageSize).forEach(item=>{
    const amount=Math.abs(Number(item.monto)||0),account=movementQuery?.account||'—',row=el('tr'),debit=item.indDBCR==='DB',credit=item.indDBCR==='CR';
    [dateLabel(item.fecha),item.descripcion,item.nroComprobante||item.idTransaccion||'—',debit?'Egreso':credit?'Ingreso':item.indDBCR||'—',
     debit?money(amount,currency):'—',credit?money(amount,currency):'—',
     money(debit?-amount:amount,currency),item.saldo===undefined?'—':money(item.saldo,currency),account].forEach((value,index)=>{
      const cell=el('td',index===3?undefined:value,index>=4&&index<=7?'numeric':undefined);
      if(index===3)cell.append(el('span',value,`movement-type ${debit?'debit':credit?'credit':'unknown'}`));
      if(index===6&&(debit||credit))cell.classList.add(debit?'negative':'positive');
      row.append(cell);
    });body.append(row);
  });
  if(!rows.length)movementEmpty(state.movements.movimientos.length?'No hay coincidencias':'No hay movimientos en este período',state.movements.movimientos.length?'Probá otra descripción o importe, o limpiá los filtros.':'Probá ampliar el período o consultar otra cuenta.');
  $('movement-page-label').textContent=`${rows.length?start+1:0}–${Math.min(start+pageSize,rows.length)} de ${rows.length}`;
  $('movement-page-prev').disabled=state.movementPage<=1;$('movement-page-next').disabled=start+pageSize>=rows.length;
}
async function downloadFile(path,options={}){
  checkSessionDeadline();if(sessionLocked)throw Error('Ingresá tu contraseña para desbloquear la sesión.');
  const response=await fetch(path,{...options,credentials:'same-origin'});if(!response.ok){if(response.status===401||response.status===428)lockSession();let message='No se pudo generar el XLSX.';try{message=(await response.json()).detail||message;}catch{}throw Error(message);}
  const blob=await response.blob(),url=URL.createObjectURL(blob),link=el('a');link.href=url;link.download=response.headers.get('content-disposition')?.match(/filename="?([^";]+)"?/)?.[1]||'reporte.xlsx';link.click();URL.revokeObjectURL(url);
}
async function loadTrackedTransfers(){
  const params=new URLSearchParams({tipo:'transferencia',fecha_desde:$('status-transfer-from').value,fecha_hasta:$('status-transfer-to').value});
  const result=await api('/operaciones?'+params),body=$('status-transfer-body'),rows=result.operaciones||[];body.replaceChildren();
  $('status-transfer-count').textContent=`${rows.length} operación(es)`;
  rows.forEach(item=>{
    const row=el('tr'),resultData=item.resultado?.consulta_estado?.data||item.resultado?.data||{},status=resultData.estadoOperacion?.descripcion||item.estado;
    const operationId=resultData.idOperacion||item.resultado?.data?.idOperacion||'—';
    [dateTimeLabel(item.actualizado),item.actor,operationBeneficiary(item),operationAmount(item),status,operationId,item.id_origen].forEach((value,index)=>row.append(el('td',value||'—',index===3?'numeric':undefined)));
    const cell=el('td'),button=el('button','Consultar banco','text-button');button.type='button';button.disabled=!item.id_origen;
    button.onclick=()=>action(button,async()=>{await api('/transferencias/estado?'+new URLSearchParams({id_origen:item.id_origen}));await loadTrackedTransfers();message('Estado bancario actualizado.','success');});
    cell.append(button);row.append(cell);body.append(row);
  });
}
function selectedFciAccount(){
  return state.fciAccounts.find(x=>`${x.tipoCuenta}|${x.sucursalCuenta}|${x.numeroCuenta}`===$('fci-account').value);
}
function selectedFciFund(){return state.fciFunds.find(x=>x.codigo===$('fci-fund').value);}
function populateFciInputs(){
  const accountSelect=$('fci-account'), oldAccount=accountSelect.value;
  accountSelect.replaceChildren();
  state.fciAccounts.forEach(a=>{
    const option=el('option',`${a.tipoCuenta} · ${a.sucursalCuenta} · ${a.numeroCuenta}`);
    option.value=`${a.tipoCuenta}|${a.sucursalCuenta}|${a.numeroCuenta}`;accountSelect.append(option);
  });
  if([...accountSelect.options].some(x=>x.value===oldAccount))accountSelect.value=oldAccount;
  const fundSelect=$('fci-fund'),oldFund=fundSelect.value;fundSelect.replaceChildren();
  state.fciFunds.forEach(f=>{
    const option=el('option',`${f.codigo} · ${f.nombre} · ${f.moneda} · ${f.perfil}`);
    option.value=f.codigo;fundSelect.append(option);
  });
  if([...fundSelect.options].some(x=>x.value===oldFund))fundSelect.value=oldFund;
}
async function loadFciData(){
  clearFciPreview();$('fci-preview-button').disabled=true;
  state.fciAccounts=[];state.fciFunds=[];populateFciInputs();$('fci-cbu').replaceChildren();
  $('fci-accounts-body').replaceChildren();$('fci-funds-body').replaceChildren();
  $('fci-profile').textContent='Sin datos validados';$('fci-linked-cbus').textContent='';
  const [accountsResponse,fundsResponse]=await Promise.all([
    api('/fci/cuentas-comitentes'),api('/fci/fondos')
  ]);
  const accountData=accountsResponse.data,fundData=fundsResponse.data;
  const invalidFields=['cuentasComitentes'].filter(key=>!Array.isArray(accountData?.[key]));
  if(invalidFields.length)
    throw Error(`La respuesta FCI no contiene listas válidas en ${invalidFields.map(key=>`data.${key}`).join(' y ')}. Se registró la estructura recibida en el log del servidor: RESPONSE FCI cuentas-comitentes. No se habilitaron operaciones.`);
  if(!Array.isArray(fundData?.detalleFondo))throw Error('La respuesta FCI no contiene una lista de fondos válida.');
  state.fciAccounts=accountData.cuentasComitentes;state.fciFunds=fundData.detalleFondo;
  populateFciInputs();
  $('fci-profile').textContent=`Perfil ${accountData.perfilInversor||'sin informar'} · Test ${accountData.estadoTestInversor||'sin informar'}`;
  const accountsBody=$('fci-accounts-body');accountsBody.replaceChildren();
  state.fciAccounts.forEach(a=>{
    const row=el('tr');[a.tipoCuenta,a.sucursalCuenta,a.numeroCuenta].forEach(v=>row.append(el('td',v)));accountsBody.append(row);
  });
  const linkedFromResponse=Array.isArray(accountData?.cuentasVinculadas)?accountData.cuentasVinculadas.map(x=>x?.cbu).filter(Boolean):[];
  const linked=linkedFromResponse;
  const cbuSelect=$('fci-cbu'),prior=cbuSelect.value;cbuSelect.replaceChildren();
  linked.forEach(cbu=>{const option=el('option',cbu);option.value=cbu;cbuSelect.append(option);});
  if([...cbuSelect.options].some(x=>x.value===prior))cbuSelect.value=prior;
  $('fci-linked-cbus').textContent=`CBU vinculados para débito/crédito: ${linked.join(' · ')||'ninguno informado'}`;
  const fundsBody=$('fci-funds-body');fundsBody.replaceChildren();
  state.fciFunds.forEach(f=>{
    const row=el('tr');
    [f.codigo,f.nombre,f.moneda,f.valorCuotaparte||'—',dateLabel(f.fechaCotizacion?.value),f.perfil||'—',f.plazo||'—']
      .forEach((v,i)=>row.append(el('td',v,i===3?'numeric':undefined)));
    const cell=el('td');
    if(typeof f.linkCartera==='string'&&/^https:\/\/www\.proahorro\.com\.ar(?:\/|$)/.test(f.linkCartera)){
      const link=el('a','Ver cartera');link.href=f.linkCartera;link.target='_blank';link.rel='noopener noreferrer';cell.append(link);
    }else cell.textContent='—';
    row.append(cell);
    fundsBody.append(row);
  });
  $('fci-movement-start').value=state.config.fecha_operativa_banco.slice(0,8)+'01';
  $('fci-movement-end').value=state.config.fecha_operativa_banco;clearFciPreview();
  $('fci-preview-button').disabled=!state.fciAccounts.length||!state.fciFunds.length||!linked.length;
  if(!$('fci-preview-button').disabled)return;
  message('El banco no informó cuentas comitentes, CBU vinculados o fondos suficientes para operar. No se completan datos automáticamente.','neutral');
}
function fciInstruction(){
  if(!$('fci-form').reportValidity())throw Error('Completá los campos requeridos para la operación FCI.');
  const account=selectedFciAccount(),fund=selectedFciFund(),cbu=$('fci-cbu').value;
  if(!account||!fund||!cbu)throw Error('Consultá las cuentas comitentes, los CBU vinculados y los fondos antes de operar.');
  const body={idOrigen:$('fci-origin').value.trim(),cuentaComitente:account};
  if($('fci-kind').value==='suscripcion'){
    body.cbuCuentaDebito=cbu;
    body.solicitudSuscripcion={codigoFondo:fund.codigo,moneda:fund.moneda,monto:$('fci-amount').value.trim(),
      avanzarTestVencido:$('fci-advance-expired').checked,aceptarRiesgoExcedido:$('fci-accept-risk').checked};
  }else{
    body.cbuCuentaCredito=cbu;
    body.solicitudRescate={codigoFondo:fund.codigo,moneda:fund.moneda};
    if($('fci-redemption-mode').value==='monto')body.solicitudRescate.monto=$('fci-amount').value.trim();
    else body.solicitudRescate.cuotapartes=$('fci-units').value.trim();
  }
  return body;
}
function fciPath(){return $('fci-kind').value==='suscripcion'?'/fci/suscripciones':'/fci/rescates';}
async function previewFci(){
  clearFciPreview();const body=fciInstruction(),path=fciPath();
  const result=await api(path+'/previsualizar',{method:'POST',body:JSON.stringify(body)});
  state.fciPreview={body,snapshot:JSON.stringify(body),path,payload:result.payload_banco};
  $('fci-preview-json').textContent=JSON.stringify(result.payload_banco,null,2);$('fci-preview').hidden=false;
  message('Vista previa FCI validada. Aún no se envió nada al banco.','success');
}
async function submitFci(){
  const pending=state.fciPreview;
  if(!pending||JSON.stringify(fciInstruction())!==pending.snapshot)
    throw Error('Los datos cambiaron. Revisá una nueva vista previa antes de enviar.');
  if(!$('fci-confirm').checked)throw Error('Confirmá la revisión de la operación FCI antes de enviar.');
  $('send-dialog').close();$('fci-send').disabled=true;
  $('fci-status-id').value='';$('fci-status-origin').value=pending.body.idOrigen;
  try{
    const response=await api(pending.path,{method:'POST',body:JSON.stringify(pending.body)});
    $('fci-result-json').textContent=JSON.stringify(response,null,2);
    $('fci-operation-state').textContent=response.respuesta_banco?.data?.estadoOperacion?.descripcion||'Respuesta recibida';
    $('fci-result').hidden=false;
    const id=response.respuesta_banco?.data?.idOperacion;if(id)$('fci-status-id').value=String(id);
    message(`${state.config.simulacion?'Operación FCI simulada':'Operación FCI enviada a firma'}. Conservá el idOrigen ${pending.body.idOrigen} y completá la firma en BIE.`, 'success');
    clearFciPreview();
  }catch(e){
    message(`${e.message} Conservá el idOrigen ${pending.body.idOrigen} y consultá el estado antes de intentar otra operación.`,'error');
  }
}
function populateDriveAccounts(){
  const select=$('drive-debit-account');if(!select)return;
  const previous=select.value;select.replaceChildren();
  const empty=el('option','Elegir una cuenta de débito');empty.value='';select.append(empty);
  state.accounts.forEach(account=>{
    const cbu=account.CBU||account.cbu||'';
    if(account.moneda!=='ARS'||!/^\d{22}$/.test(cbu))return;
    const option=el('option',`${account.nroCuenta} · ${account.moneda} · ${account.tipoCuenta}`);
    option.value=String(account.nroCuenta);select.append(option);
  });
  if([...select.options].some(option=>option.value===previous))select.value=previous;
  if(!select.value&&select.options.length===2)select.selectedIndex=1;
}
function clearDriveOrderPreview(){
  state.driveOrderPreview=null;
  $('drive-order-preview').close();
  $('drive-order-confirm').checked=false;
  $('drive-order-send').disabled=true;
}
function clearDriveBatchPreview(){
  state.batchOrderPreview=null;$('drive-batch-preview').close();$('drive-batch-confirm').checked=false;$('drive-batch-send').disabled=true;
}
function openOrderReview(id){
  if(sessionLocked){clearDriveOrderPreview();clearDriveBatchPreview();return;}
  const dialog=$(id);
  dialog.querySelector('.review-notice').hidden=true;
  dialog.querySelector('.technical-details').open=false;
  dialog.querySelector('.review-environment').textContent=state.config?.simulacion?'Demo local · sin envío al banco':state.config?.homologacion?'Homologación · entorno de pruebas':'Producción · operación real';
  dialog.showModal();
  dialog.scrollTop=0;
}
function renderDriveOrders(){
  const body=$('drive-orders-body'),method=state.kind==='echeq'?'CHE':'TRB';body.replaceChildren();
  const orders=state.driveOrders.filter(order=>order.method===method);
  state.selectedDriveOrders=state.selectedDriveOrders.filter(id=>orders.some(order=>order.source_id===id&&order.status==='READY'));
  $('drive-order-count').textContent=`${orders.length} orden(es) ${method} · ${state.selectedDriveOrders.length} seleccionada(s)`;
  const statusLabels={READY:'Lista para revisar',NEEDS_REVIEW:'Requiere revisión',DUPLICATE:'Duplicada',ENVIADA_A_FIRMA:'Enviada a firma',RESPUESTA_RECIBIDA:'Respuesta recibida',RESULTADO_INCIERTO:'Resultado incierto',ERROR:'Error'};
  orders.forEach(order=>{
    const row=el('tr'),selectCell=el('td'),select=el('input');select.type='checkbox';select.checked=state.selectedDriveOrders.includes(order.source_id);select.disabled=order.status!=='READY';select.setAttribute('aria-label',`Seleccionar orden ${order.order_number||order.source_name}`);
    select.onchange=()=>{state.selectedDriveOrders=select.checked?[...state.selectedDriveOrders,order.source_id]:state.selectedDriveOrders.filter(id=>id!==order.source_id);clearDriveBatchPreview();renderDriveOrders();};
    selectCell.append(select);row.append(selectCell);
    [order.order_number||'—',dateLabel(order.issue_date),order.source_name,order.supplier?.name||'—',order.supplier?.document||'—',order.method||'—',order.amount?money(order.amount):'—',order.supplier?.cbu||'—',order.concept||order.references?.join(' · ')||'—',statusLabels[order.status]||order.status].forEach((value,index)=>{
      const cell=el('td',index===9?undefined:value,index===6?'numeric':undefined);
      if(index===9)cell.append(el('span',value,`order-status ${order.status==='READY'?'ready':order.status==='ENVIADA_A_FIRMA'?'sent':'attention'}`));
      row.append(cell);
    });
    const actionCell=el('td');
    if(order.status==='READY'){
      const button=el('button','Revisar','text-button');button.type='button';
      button.onclick=()=>action(button,()=>previewDriveOrder(order));actionCell.append(button);
    }else if(order.reason){
      const reason=el('small',order.reason,'muted');reason.title=order.reason;actionCell.append(reason);
    }else actionCell.append(el('span','—','muted'));
    row.append(actionCell);body.append(row);
  });
  if(!orders.length){const row=el('tr'),cell=el('td',`No hay órdenes ${method} para mostrar. Buscá en Drive para actualizar la lista.`,'table-empty');cell.colSpan=12;row.append(cell);body.append(row);}
  const ready=orders.filter(order=>order.status==='READY');
  $('drive-select-all').checked=ready.length>0&&ready.every(order=>state.selectedDriveOrders.includes(order.source_id));
  $('drive-select-all').indeterminate=ready.some(order=>state.selectedDriveOrders.includes(order.source_id))&&!$('drive-select-all').checked;
  $('drive-select-all').disabled=!ready.length;
  $('drive-batch-review-button').disabled=!state.selectedDriveOrders.length;
}
async function previewSelectedDriveOrders(){
  const selected=state.driveOrders.filter(order=>state.selectedDriveOrders.includes(order.source_id)&&order.status==='READY');
  if(!selected.length)throw Error('Seleccioná una o más órdenes listas para preparar.');
  const account=state.accounts.find(item=>String(item.nroCuenta)===$('drive-debit-account').value),cbu=account?.CBU||account?.cbu;
  if(!/^\d{22}$/.test(cbu||''))throw Error('Elegí una cuenta de débito ARS habilitada.');
  const previews=[];
  for(const order of selected){
    const result=await api(`/ordenes-pago/${encodeURIComponent(order.source_id)}/previsualizar`,{method:'POST',body:JSON.stringify({cbuCuentaDebito:cbu})});
    const item=result.payload_banco.beneficiarios?.[0]||result.payload_banco.echeqs?.[0];
    previews.push({source_id:order.source_id,source_name:order.source_name,order_number:order.order_number,
      method:order.method,beneficiary:item?.nombre||item?.beneficiarioNombre,amount:item?.monto,
      document:item?.cui||item?.beneficiarioDocumento,destination:item?.cbuCvu,paymentDate:item?.fechaPago,
      idOrigen:result.payload_banco.idOrigen,payload:result.payload_banco});
  }
  state.batchOrderPreview={accountNumber:String(account.nroCuenta),cbu,sourceIds:selected.map(order=>order.source_id),orders:previews};
  const summary=$('drive-batch-summary');summary.replaceChildren();
  summary.append(el('p',`${previews.length} orden(es) · Total ${money(previews.reduce((sum,item)=>sum+Number(item.amount),0))}`,'batch-total'),el('p',`Cuenta de débito ${account.nroCuenta} · CBU ${cbu}`,'batch-account'));
  previews.forEach(item=>{
    const card=el('article',undefined,'batch-order');
    card.append(el('strong',item.beneficiary||'Beneficiario sin nombre'),el('strong',money(item.amount),'numeric'),el('span',`${item.method==='CHE'?'eCheq':'Transferencia'} · ${item.source_name}`,'muted'));
    card.append(el('span',`CUIT / CUIL: ${item.document||'—'} · ${item.method==='CHE'?`Pago: ${dateLabel(item.paymentDate)}`:`CBU / CVU: ${item.destination||'—'}`}`,'muted'));
    summary.append(card);
  });
  $('drive-batch-preview-json').textContent=JSON.stringify(previews.map(({payload,...item})=>item),null,2);
  $('drive-batch-confirm').checked=false;$('drive-batch-send').disabled=true;
  openOrderReview('drive-batch-preview');
}
async function sendSelectedDriveOrders(){
  const pending=state.batchOrderPreview;if(!pending)throw Error('No hay una selección revisada.');
  const account=state.accounts.find(item=>String(item.nroCuenta)===$('drive-debit-account').value);
  if(String(account?.nroCuenta)!==pending.accountNumber||(account?.CBU||account?.cbu)!==pending.cbu
      ||JSON.stringify(state.selectedDriveOrders.slice().sort())!==JSON.stringify(pending.sourceIds.slice().sort()))
    throw Error('Cambió la selección o la cuenta. Volvé a revisar todas las órdenes.');
  if(!$('drive-batch-confirm').checked)throw Error('Confirmá la revisión de todas las órdenes antes de enviar.');
  state.busy=true;$('drive-batch-preview').setAttribute('aria-busy','true');
  $('drive-batch-send').disabled=true;$('drive-batch-confirm').disabled=true;const results=[];
  for(const order of pending.orders){
    try{
      const response=await api(`/ordenes-pago/${encodeURIComponent(order.source_id)}/enviar`,{method:'POST',body:JSON.stringify({cbuCuentaDebito:pending.cbu})});
      results.push({source_name:order.source_name,idOrigen:order.idOrigen,estado:'ENVIADA_A_FIRMA',respuesta:response});
    }catch(error){results.push({source_name:order.source_name,idOrigen:order.idOrigen,estado:'ERROR_O_INCIERTO',error:error.message});break;}
  }
  state.busy=false;$('drive-batch-preview').removeAttribute('aria-busy');$('drive-batch-confirm').disabled=false;
  $('drive-batch-preview-json').textContent=JSON.stringify(results,null,2);$('drive-batch-confirm').checked=false;
  const summary=$('drive-batch-summary');summary.replaceChildren();
  results.forEach(item=>{const card=el('article',undefined,'batch-order');card.append(el('strong',item.source_name),el('span',item.estado==='ENVIADA_A_FIRMA'?'Enviada a firma':'Revisar estado antes de reintentar',`order-status ${item.estado==='ENVIADA_A_FIRMA'?'sent':'attention'}`));summary.append(card);});
  if(results.length<pending.orders.length)summary.append(el('p',`${pending.orders.length-results.length} orden(es) sin enviar. El lote se detuvo para evitar nuevos envíos tras un error.`));
  state.batchOrderPreview=null;state.selectedDriveOrders=[];
  try{await loadDriveOrders();}catch(error){message(`No se pudo actualizar la lista (${error.message}); revisá los registros por idOrigen.`, 'error');return;}
  const failed=results.some(item=>item.estado!=='ENVIADA_A_FIRMA');
  message(failed?'El lote se detuvo en el primer error. Revisá cada idOrigen; no se reintentó automáticamente.':`${results.length} operación(es) enviadas a firma. Completá la autorización en BIE.`,failed?'error':'success');
}
async function loadDriveOrders(sync=false){
  const result=await api(sync?'/ordenes-pago/sincronizar':'/ordenes-pago',{method:sync?'POST':'GET'});
  state.driveOrders=result.ordenes||[];
  renderDriveOrders();
  if(sync)message(`Sincronización de solo lectura completada: ${result.archivos_op_pdf_en_drive} PDF(s) op-*.pdf en Drive.`, 'success');
}
async function previewDriveOrder(order){
  clearDriveOrderPreview();
  const account=state.accounts.find(item=>String(item.nroCuenta)===$('drive-debit-account').value);
  const cbu=account?.CBU||account?.cbu;
  if(!/^\d{22}$/.test(cbu||''))throw Error('Consultá las cuentas y elegí una cuenta ARS válida para debitar.');
  const result=await api(`/ordenes-pago/${encodeURIComponent(order.source_id)}/previsualizar`,{
    method:'POST',body:JSON.stringify({cbuCuentaDebito:cbu})
  });
  state.driveOrderPreview={sourceId:order.source_id,accountNumber:String(account.nroCuenta),cbu,payload:result.payload_banco,summary:result.orden};
  const payload=result.payload_banco,item=payload.beneficiarios?.[0]||payload.echeqs?.[0];
  $('drive-preview-amount').textContent=money(result.orden.importe);
  $('drive-preview-method').textContent=payload.beneficiarios?'Transferencia · TRB':'eCheq · CHE';
  $('drive-preview-summary').replaceChildren();
  addDriveReview('Proveedor / destinatario',result.orden.proveedor);
  addDriveReview('CUIT / CUIL',item?.cui||item?.beneficiarioDocumento||order.supplier?.document||'—');
  if(payload.beneficiarios)addDriveReview('CBU / CVU de destino',item?.cbuCvu||'—');
  else addDriveReview('Fecha de pago',dateLabel(item?.fechaPago||order.cheque_date));
  addDriveReview('Cuenta de débito',`${account.nroCuenta} · ARS`);
  addDriveReview('CBU de débito',cbu);
  addDriveReview('Archivo en Drive',result.orden.archivo);
  $('drive-preview-json').textContent=JSON.stringify(payload,null,2);
  openOrderReview('drive-order-preview');
}
function addDriveReview(label,value){
  const item=el('div',undefined,'review-item');item.append(el('small',label),el('strong',value));$('drive-preview-summary').append(item);
}
async function transmitDriveOrder(){
  const pending=state.driveOrderPreview;if(!pending)throw Error('No hay una orden revisada para enviar.');
  const account=state.accounts.find(item=>String(item.nroCuenta)===$('drive-debit-account').value);
  if(String(account?.nroCuenta)!==pending.accountNumber||(account?.CBU||account?.cbu)!==pending.cbu)
    throw Error('La cuenta de débito cambió. Volvé a revisar la vista previa.');
  if(!$('drive-order-confirm').checked)throw Error('Confirmá la revisión de la orden antes de enviarla.');
  $('drive-order-preview').close();state.busy=true;$('confirm-send').disabled=true;$('drive-order-send').disabled=true;
  const payload=pending.payload,item=payload.beneficiarios?.[0]||payload.echeqs[0];
  const kind=payload.beneficiarios?'transferencia':'echeq';
  sessionStorage.setItem('credicoopPendingOrigin',payload.idOrigen);
  $('status-origin').value=payload.idOrigen;$('status-kind').value=kind;$('status-operation').value='';
  try{
    const response=await api(`/ordenes-pago/${encodeURIComponent(pending.sourceId)}/enviar`,{
      method:'POST',body:JSON.stringify({cbuCuentaDebito:pending.cbu})
    });
    $('status-operation').value=String(response.respuesta_banco?.data?.idOperacion||'');
    showOperation(response);clearDriveOrderPreview();await loadDriveOrders();
    message(`${state.config.simulacion?'Operación simulada':'Orden enviada a firma'} para ${item.nombre||item.beneficiarioNombre}. Consultá su estado y completá la firma en BIE.`, 'success');
  }catch(error){
    clearDriveOrderPreview();
    try{await loadDriveOrders();}catch(refreshError){throw Error(`${error.message} No se pudo actualizar el estado de la orden (${refreshError.message}); consultá el registro y el banco antes de repetir.`);}
    throw Error(`${error.message} Consultá el registro de la orden y el banco antes de repetir.`);
  }finally{state.busy=false;$('confirm-send').disabled=false;}
}
function resetChequeDate(){
  if(!state.config)return;
  const d=state.config.fecha_operativa_banco;
  if($('cheque-type').value==='ECHC')$('cheque-date').value=d;
  else{const next=new Date(d+'T00:00:00Z');next.setUTCDate(next.getUTCDate()+7);$('cheque-date').value=next.toISOString().slice(0,10);}
}
function newInstruction(fromOrder=false){
  clearPreview();$('payment-origin').value=newId();sessionStorage.removeItem('credicoopPendingOrigin');
  $('beneficiary-name').value='';$('beneficiary-document').value='';$('beneficiary-cbu').value='';
  $('test-beneficiary').value='';$('payment-amount').value='15.79';
  if(!fromOrder)clearPreview();
}
function buildPayment(){
  if(!state.config)throw Error('Conectá el servicio antes de preparar una instrucción.');
  if(!$('payment-form').reportValidity())throw Error('Completá los campos requeridos del pago.');
  const account=chosenAccount();const cbu=account?.CBU||account?.cbu;
  if(!/^\d{22}$/.test(cbu||''))throw Error('La cuenta elegida no tiene un CBU de débito válido. Actualizá la consulta de cuentas.');
  const amount=$('payment-amount').value.trim().replace(',','.');
  if(!/^\d{1,13}(\.\d{1,2})?$/.test(amount)||/^0+(\.0+)?$/.test(amount))throw Error('Ingresá un importe positivo con hasta dos decimales, por ejemplo 15.79.');
  const body={idOrigen:$('payment-origin').value.trim(),cbuCuentaDebito:cbu,operadoresFirmantes:[]};
  if($('signer-document').value.trim())body.operadoresFirmantes.push({documento:$('signer-document').value.trim(),documentoTipo:$('signer-type').value});
  const name=$('beneficiary-name').value.trim(),documento=$('beneficiary-document').value.trim(),concept=$('payment-concept').value,note=$('payment-note').value.trim();
  if(state.kind==='transferencia')body.beneficiarios=[{cbuCvu:$('beneficiary-cbu').value.trim(),esCuentaPropia:'N',monto:amount,moneda:'ARS',concepto:concept,cui:documento,nombre:name,observaciones:note}];
  else body.echeqs=[{monto:amount,fechaPago:$('cheque-date').value,motivoPago:note,caracter:'1',modo:'1',beneficiarioNombre:name,beneficiarioDocumentoTipo:'CUIT',beneficiarioDocumento:documento,concepto:concept,tipoCheque:$('cheque-type').value}];
  return body;
}
function paymentPath(){return state.kind==='transferencia'?'/transferencias':'/echeqs';}
function addReview(label,value){const item=el('div',undefined,'review-item');item.append(el('small',label),el('strong',value));$('preview-summary').append(item);}
function renderPreview(payload){
  const item=payload.beneficiarios?.[0]||payload.echeqs[0];$('preview-summary').replaceChildren();
  addReview('Cuenta de débito',payload.cbuCuentaDebito);addReview('Beneficiario',item.nombre||item.beneficiarioNombre);
  addReview('Importe',money(item.monto));addReview('CUIT / CUIL / CDI',item.cui||item.beneficiarioDocumento);
  addReview('Modalidad','Firma posterior en BIE');addReview('Fecha de pago',item.fechaPago?dateLabel(item.fechaPago):dateLabel(state.config.fecha_operativa_banco));
  if(item.cbuCvu)addReview('CBU / CVU de destino',item.cbuCvu);addReview('idOrigen',payload.idOrigen);
  $('preview-json').textContent=JSON.stringify(payload,null,2);$('payment-preview').hidden=false;$('confirm-payment').checked=false;$('send-payment').disabled=true;
}
async function previewPayment(){
  clearPreview();const body=buildPayment();
  const result=await api(paymentPath()+'/previsualizar',{method:'POST',body:JSON.stringify(body)});
  state.preview={body,snapshot:JSON.stringify(body),kind:state.kind,path:paymentPath(),payload:result.payload_banco};renderPreview(result.payload_banco);
  message('Vista previa validada. Todavía no se envió la operación al banco.','success');
}
async function transmit(){
  const p=state.preview;
  if(!p||p.kind!==state.kind||JSON.stringify(buildPayment())!==p.snapshot)throw Error('Los datos cambiaron. Generá y revisá una nueva vista previa.');
  if(!$('confirm-payment').checked)throw Error('Confirmá la revisión antes de enviar.');
  $('send-dialog').close();state.busy=true;$('confirm-send').disabled=true;$('send-payment').disabled=true;
  sessionStorage.setItem('credicoopPendingOrigin',p.body.idOrigen);
  $('status-origin').value=p.body.idOrigen;$('status-kind').value=p.kind;$('status-operation').value='';
  try{
    const response=await api(p.path,{method:'POST',body:JSON.stringify(p.body)});
    $('status-operation').value=String(response.respuesta_banco?.data?.idOperacion||'');
    showOperation(response);showView('dashboard');loadDayOperations().catch(error=>message(`El envío fue respondido, pero no se pudo actualizar el seguimiento (${error.message}).`,'error'));
    const status=response.respuesta_banco?.data?.estadoOperacion?.descripcion||'Respuesta recibida';
    message(`${state.config.simulacion?'Respuesta simulada':'Respuesta del banco'}: ${status}. ${state.config.simulacion?'Esta demostración no envía instrucciones al banco.':'Consultá el estado y completá firma y activación en BIE.'}`,status.toLowerCase().includes('rechaz')?'error':'success');
  }catch(e){
    clearPreview();showView('dashboard');message(`${e.message} Conservá el idOrigen ${p.body.idOrigen} y revisá el registro local antes de repetir.`,'error');
  }finally{state.busy=false;$('confirm-send').disabled=false;}
}
function showOperation(data){
  $('operation-result').hidden=false;$('operation-json').textContent=JSON.stringify(data,null,2);
  const d=data.respuesta_banco?.data||data.data||data.resultado?.data||data;
  $('operation-state').textContent=d.estadoOperacion?.descripcion||data.estado||'Respuesta recibida';
}
function renderSessionIdentity(){
  const user=state.user,role=user.role==='admin'?'Administrador':'Usuario';
  $('connected-user').textContent=user.username;$('connected-user').title=`${user.username} · ${role}`;
  $('session-profile').setAttribute('aria-label',`Mi usuario y seguridad: ${user.username}, ${role}`);
  $('session-avatar').textContent=user.username.slice(0,1).toUpperCase();
  $('profile-name').textContent=user.username;$('profile-role').textContent=role;
}
async function initializeApp(user,reauthenticateIn=1800){
  sessionLocked=false;scheduleReauthentication(reauthenticateIn);
  state.authenticated=true;state.user=user;document.body.classList.remove('logged-out');document.body.classList.add('logged-in');$('login-panel').hidden=true;$('bank-app').hidden=false;
  renderSessionIdentity();
  $('connection-status').textContent='Sesión protegida';$('user-admin-panel').hidden=user.role!=='admin';
  state.config=await api('/configuracion');
  $('environment').textContent=state.config.simulacion?'Demo local · Sin banco':state.config.homologacion?'Homologación · Pruebas':'Producción · Operaciones reales';
  $('environment').dataset.mode=state.config.simulacion?'demo':state.config.homologacion?'test':'production';
  const today=state.config.fecha_actual_argentina,monthStart=today.slice(0,8)+'01';
  $('movement-start').value=state.config.fecha_operativa_banco.slice(0,8)+'01';clearMovementQuery();resetChequeDate();
  $('status-transfer-from').value=monthStart;$('status-transfer-to').value=today;
  $('homo-dates').hidden=!state.config.homologacion;
  $('payment-origin').value=sessionStorage.getItem('credicoopPendingOrigin')||newId();
  $('audit-from').value=today;$('audit-to').value=today;
  state.beneficiaries=[];
  if(state.config.homologacion)state.beneficiaries=(await api('/homologacion/beneficiarios')).beneficiarios;
  populateBeneficiaries();await loadAccounts();if(!state.config.simulacion)await loadDriveOrders();await loadDashboard();showView('dashboard');
  message(`Sesión iniciada. Fecha operativa: ${dateLabel(state.config.fecha_operativa_banco)}.`, 'success');
}
function showLogin(){
  clearTimeout(reauthTimer);reauthDeadline=0;sessionLocked=false;
  document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());$('reauth-password').value='';
  clearDriveOrderPreview();clearDriveBatchPreview();
  state.authenticated=false;state.user=null;state.key='';document.body.classList.remove('logged-in');document.body.classList.add('logged-out');$('bank-app').hidden=true;$('login-panel').hidden=false;$('environment').textContent='Iniciar sesión';$('environment').removeAttribute('data-mode');
}
$('sidebar-toggle').onclick=()=>{
  const collapsed=document.body.classList.toggle('sidebar-collapsed');
  $('sidebar-toggle').setAttribute('aria-expanded',String(!collapsed));
  $('sidebar-toggle').setAttribute('aria-label',collapsed?'Expandir menú':'Colapsar menú');
};
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>{
  if(!state.busy&&state.authenticated){
    showView(button.dataset.view);
    if(button.dataset.view==='dashboard')action($('refresh-dashboard'),loadDashboard);
    if(button.dataset.view==='usuarios')action($('refresh-audit'),async()=>{await loadUsers();await loadAudit();});
    if(button.dataset.view==='fci'&&!state.fciAccounts.length)action($('refresh-fci'),loadFciData);
    if((button.dataset.view==='transferencias'||button.dataset.view==='echeqs')&&!state.config?.simulacion)action($('sync-drive-orders'),()=>loadDriveOrders());
  }
});
document.querySelectorAll('[data-dashboard-view]').forEach(button=>button.onclick=()=>{
  document.querySelector(`.nav[data-view="${button.dataset.dashboardView}"]`).click();
});
$('login-form').onsubmit=async event=>{
  event.preventDefault();const button=$('login-submit');button.disabled=true;$('login-error').hidden=true;
  try{
    const response=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({username:$('login-username').value.trim(),password:$('login-password').value})});
    let data={};try{data=await response.json();}catch{}
    if(!response.ok)throw Error(data.detail||'No se pudo iniciar sesión.');
    $('login-password').value='';await initializeApp(data.usuario);
  }catch(error){$('login-error').textContent=error.message||'No se pudo iniciar sesión.';$('login-error').hidden=false;}
  finally{button.disabled=false;}
};
async function endSession(button){
  button.disabled=true;
  try{
    const response=await fetch('/logout',{method:'POST',credentials:'same-origin'});
    if(!response.ok)throw Error('No se pudo cerrar la sesión. Intentá nuevamente.');
    showLogin();
  }catch(error){
    if(sessionLocked){$('reauth-error').textContent=error.message;$('reauth-error').hidden=false;}else message(error.message,'error');
  }finally{button.disabled=false;}
}
$('logout').onclick=()=>endSession($('logout'));
$('reauth-logout').onclick=()=>endSession($('reauth-logout'));
$('reauth-dialog').addEventListener('cancel',event=>event.preventDefault());
$('reauth-form').onsubmit=async event=>{
  event.preventDefault();const button=$('reauth-submit');button.disabled=true;$('reauth-error').hidden=true;
  try{
    const response=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({username:state.user.username,password:$('reauth-password').value})});
    const data=await response.json();$('reauth-password').value='';
    if(!response.ok)throw Error(data.detail||'No se pudo validar la contraseña.');
    state.user=data.usuario;sessionLocked=false;$('reauth-dialog').close();scheduleReauthentication(data.revalidar_en_segundos);
    if(!state.config)await initializeApp(data.usuario,data.revalidar_en_segundos);
    renderSessionIdentity();
    $('user-admin-panel').hidden=state.user.role!=='admin';
    message('Sesión desbloqueada. Volvé a revisar los pagos pendientes antes de enviarlos.','success');
  }catch(error){$('reauth-error').textContent=error.message;$('reauth-error').hidden=false;$('reauth-password').focus();}
  finally{button.disabled=false;}
};
$('session-profile').onclick=()=>document.querySelector('.nav[data-view="usuarios"]').click();
$('change-password').onclick=()=>$('password-dialog').showModal();
$('password-cancel').onclick=()=>$('password-dialog').close();
$('password-form').onsubmit=event=>{event.preventDefault();action(event.submitter,async()=>{
  await api('/auth/password',{method:'POST',body:JSON.stringify({current_password:$('password-current').value,new_password:$('password-new').value})});
  $('password-dialog').close();$('password-current').value='';$('password-new').value='';showLogin();message('Contraseña actualizada; iniciá sesión nuevamente.','success');
});};
fetch('/auth/me',{credentials:'same-origin'}).then(async response=>{
  if(!response.ok)return;const data=await response.json(),user={username:data.usuario,role:data.rol};
  if(data.revalidacion_requerida){state.authenticated=true;state.user=user;lockSession();return;}
  await initializeApp(user,data.revalidar_en_segundos);
}).catch(()=>{});
$('sync-drive-orders').onclick=()=>action($('sync-drive-orders'),()=>loadDriveOrders(true));
$('drive-select-all').onchange=()=>{clearDriveBatchPreview();const method=state.kind==='echeq'?'CHE':'TRB';state.selectedDriveOrders=$('drive-select-all').checked?state.driveOrders.filter(order=>order.status==='READY'&&order.method===method).map(order=>order.source_id):[];renderDriveOrders();};
$('drive-batch-review-button').onclick=()=>action($('drive-batch-review-button'),previewSelectedDriveOrders);
$('drive-batch-confirm').onchange=()=>$('drive-batch-send').disabled=!state.batchOrderPreview||!$('drive-batch-confirm').checked;
$('drive-batch-send').onclick=async()=>{await action($('drive-batch-send'),sendSelectedDriveOrders);$('drive-batch-send').disabled=!state.batchOrderPreview||!$('drive-batch-confirm').checked||state.busy;};
$('drive-debit-account').onchange=()=>{clearDriveOrderPreview();clearDriveBatchPreview();};
$('drive-order-confirm').onchange=()=>$('drive-order-send').disabled=!state.driveOrderPreview||!$('drive-order-confirm').checked||state.busy;
$('drive-order-send').onclick=async()=>{await action($('drive-order-send'),transmitDriveOrder);$('drive-order-send').disabled=!state.driveOrderPreview||!$('drive-order-confirm').checked||state.busy;};
['order','batch'].forEach(kind=>{
  const dialog=$(`drive-${kind}-preview`),clear=kind==='order'?clearDriveOrderPreview:clearDriveBatchPreview;
  const dismiss=()=>{if(!state.busy)clear();};
  $(`drive-${kind}-close`).onclick=dismiss;$(`drive-${kind}-back`).onclick=dismiss;
  dialog.addEventListener('cancel',event=>{event.preventDefault();dismiss();});
});
$('refresh-fci').onclick=()=>action($('refresh-fci'),loadFciData);
$('fci-kind').onchange=()=>{
  const subscription=$('fci-kind').value==='suscripcion',byAmount=subscription||$('fci-redemption-mode').value==='monto';
  $('fci-risk-options').hidden=!subscription;$('fci-redemption-mode-label').hidden=subscription;
  $('fci-amount-label').hidden=!byAmount;$('fci-units-label').hidden=byAmount;
  $('fci-amount').required=byAmount;$('fci-units').required=!byAmount;clearFciPreview();
};
$('fci-redemption-mode').onchange=()=>$('fci-kind').dispatchEvent(new Event('change'));
$('fci-form').addEventListener('input',clearFciPreview);$('fci-form').addEventListener('change',clearFciPreview);
$('fci-form').onsubmit=e=>{e.preventDefault();action(e.submitter,previewFci);};
$('fci-new-operation').onclick=()=>{
  clearFciPreview();$('fci-origin').value=newId();$('fci-amount').value='';$('fci-units').value='';
  $('fci-advance-expired').checked=false;$('fci-accept-risk').checked=false;
  $('fci-status-id').value='';$('fci-status-origin').value='';$('fci-result').hidden=true;
  message('Nuevo idOrigen generado. Usalo sólo para una operación nueva, no para repetir una anterior.','neutral');
};
$('fci-confirm').onchange=()=>$('fci-send').disabled=!state.fciPreview||!$('fci-confirm').checked;
$('fci-send').onclick=()=>{
  const pending=state.fciPreview;if(!pending)return;
  const detail=pending.body.solicitudSuscripcion||pending.body.solicitudRescate;
  const size=detail.monto?money(detail.monto,detail.moneda):`${detail.cuotapartes} cuotapartes`;
  $('dialog-summary').textContent=`${state.config.simulacion?'DEMO LOCAL SIN ENVÍO AL BANCO':state.config.homologacion?'HOMOLOGACIÓN':'PRODUCCIÓN'} · ${pending.body.solicitudSuscripcion?'Suscripción':'Rescate'} ${size} del fondo ${detail.codigoFondo}. Firmante DNI 44379155. idOrigen ${pending.body.idOrigen}.`;
  $('send-dialog').showModal();
};
$('fci-load-balances').onclick=()=>action($('fci-load-balances'),async()=>{
  const account=selectedFciAccount();if(!account)throw Error('Actualizá las cuentas comitentes y seleccioná una.');
  const result=await api('/fci/saldos',{method:'POST',body:JSON.stringify({cuentaComitente:account})});
  $('fci-balances').textContent=JSON.stringify(result,null,2);
});
$('fci-movements-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{
  const account=selectedFciAccount();if(!account)throw Error('Actualizá las cuentas comitentes y seleccioná una.');
  const request={cuentaComitente:account,fechaDesde:$('fci-movement-start').value,fechaHasta:$('fci-movement-end').value};
  const result=await api('/fci/movimientos',{method:'POST',body:JSON.stringify(request)});
  const rows=result.data?.movimientos;if(!Array.isArray(rows))throw Error('La respuesta FCI no contiene una lista de movimientos válida.');
  const body=$('fci-movements-body');body.replaceChildren();$('fci-movement-count').textContent=`${result.data.totalMovimientos??rows.length} movimiento(s)`;
  rows.forEach(m=>{
    const row=el('tr');[dateLabel(m.fecha),m.movimiento,m.fondo,m.cuotapartes].forEach(v=>row.append(el('td',v??'—')));
    const cell=el('td');const button=el('button','Ver detalle','text-button');button.type='button';
    button.onclick=()=>action(button,async()=>{
      if(!m.operacion)throw Error('Este movimiento no incluye los identificadores requeridos para consultar su detalle.');
      const query=new URLSearchParams(m.operacion);const detail=await api('/fci/movimientos/detalle?'+query);
      $('fci-result-json').textContent=JSON.stringify(detail,null,2);$('fci-operation-state').textContent='Detalle del movimiento';$('fci-result').hidden=false;
    });
    cell.append(button);row.append(cell);body.append(row);
  });
  message('Consulta de movimientos FCI recibida.','success');
});};
$('fci-check-operation').onclick=()=>action($('fci-check-operation'),async()=>{
  const kind=$('fci-status-kind').value,params=new URLSearchParams();
  const operation=$('fci-status-id').value.trim(),origin=$('fci-status-origin').value.trim();
  if(operation)params.set('id_operacion',operation);if(origin)params.set('id_origen',origin);
  if(!operation&&!origin)throw Error('Ingresá idOperacion o idOrigen para consultar.');
  const result=await api(`/fci/${kind==='suscripcion'?'suscripciones':'rescates'}/estado?${params}`);
  $('fci-result-json').textContent=JSON.stringify(result,null,2);
  $('fci-operation-state').textContent=result.data?.estadoOperacion?.descripcion||'Estado consultado';$('fci-result').hidden=false;
});
$('fci-local-status').onclick=()=>action($('fci-local-status'),async()=>{
  const origin=$('fci-status-origin').value.trim();if(!origin)throw Error('Ingresá idOrigen para consultar el registro local.');
  const kind=$('fci-status-kind').value==='suscripcion'?'fci_suscripcion':'fci_rescate';
  const result=await api(`/operaciones/${kind}/${encodeURIComponent(origin)}`);
  $('fci-result-json').textContent=JSON.stringify(result,null,2);
  $('fci-operation-state').textContent=result.estado||'Registro local';$('fci-result').hidden=false;
});
$('refresh-accounts').onclick=()=>action($('refresh-accounts'),loadAccounts);
$('export-accounts').onclick=()=>action($('export-accounts'),()=>downloadFile('/export/cuentas.xlsx'));
$('refresh-dashboard').onclick=()=>action($('refresh-dashboard'),loadDashboard);
$('refresh-day-operations').onclick=()=>action($('refresh-day-operations'),async()=>{await loadDayOperations();if(!$('status-transfer-panel').hidden&&$('status-transfer-from').value)await loadTrackedTransfers();});
$('fci-export-balances').onclick=()=>action($('fci-export-balances'),async()=>{
  const account=selectedFciAccount();if(!account)throw Error('Actualizá las cuentas comitentes y seleccioná una.');
  await downloadFile('/fci/saldos/export.xlsx',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cuentaComitente:account})});
});
$('user-create-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{
  await api('/usuarios',{method:'POST',body:JSON.stringify({username:$('user-new-name').value.trim(),password:$('user-new-password').value,role:$('user-new-role').value})});
  $('user-new-name').value='';$('user-new-password').value='';await loadUsers();message('Usuario creado.','success');
});};
$('refresh-audit').onclick=()=>action($('refresh-audit'),async()=>{await loadUsers();await loadAudit();});
$('audit-user').onchange=()=>action($('refresh-audit'),loadAudit);
$('export-audit').onclick=()=>action($('export-audit'),()=>{const params=new URLSearchParams();if($('audit-from').value)params.set('fecha_desde',$('audit-from').value);if($('audit-to').value)params.set('fecha_hasta',$('audit-to').value);if($('audit-user').value.trim())params.set('usuario',$('audit-user').value.trim());return downloadFile('/operaciones/export.xlsx?'+params);});
$('admin-password-dialog').querySelector('form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{
  await api(`/usuarios/${encodeURIComponent($('reset-user-name').value)}`,{method:'PATCH',body:JSON.stringify({password:$('reset-user-password').value})});
  $('admin-password-dialog').close();$('reset-user-password').value='';await loadUsers();message('Contraseña restablecida por un administrador.','success');
});};
$('admin-password-cancel').onclick=()=>$('admin-password-dialog').close();
$('audit-from').onchange=()=>action($('refresh-audit'),loadAudit);$('audit-to').onchange=()=>action($('refresh-audit'),loadAudit);
$('homo-dates').onclick=()=>{if(!state.config)return;$('movement-start').value=state.config.fecha_operativa_banco.slice(0,8)+'01';$('movement-end').value=state.config.fecha_operativa_banco;clearMovementQuery();document.querySelectorAll('.movement-range').forEach(button=>button.setAttribute('aria-pressed','false'));};
$('movement-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{
  clearMovementQuery();const version=movementVersion,query={account:$('movement-account').value,from:$('movement-start').value,to:$('movement-end').value};
  query.currency=state.accounts.find(a=>String(a.nroCuenta)===query.account)?.moneda||'ARS';
  const params=new URLSearchParams({fecha_desde:query.from});if(query.to)params.set('fecha_hasta',query.to);
  $('movement-form').setAttribute('aria-busy','true');$('movement-result-context').textContent='Consultando los movimientos…';
  movementEmpty('Consultando al banco','La consulta puede tardar según el período elegido.');
  try{
    const data=await api(`/cuentas/${encodeURIComponent(query.account)}/movimientos?${params}`);
    if(version!==movementVersion)return;
    if(!Array.isArray(data.movimientos))throw Error('El banco no devolvió una lista de movimientos válida.');
    state.movements=data;movementQuery={...query,from:data.fecha_desde||query.from,to:data.fecha_hasta||query.to};state.movementPage=1;
    $('export-movements').disabled=false;renderMovementRows();
    const currency=query.currency,last=data.encabezados?.[0]?.datos;
    $('movement-result-context').textContent=`Cuenta ${query.account} · ${currency} · ${dateLabel(movementQuery.from)} al ${dateLabel(movementQuery.to)}${data.completa?'':' · Consulta parcial'}`;
    const credits=data.movimientos.filter(item=>item.indDBCR==='CR').reduce((sum,item)=>sum+Math.abs(Number(item.monto)||0),0),debits=data.movimientos.filter(item=>item.indDBCR==='DB').reduce((sum,item)=>sum+Math.abs(Number(item.monto)||0),0);
    const kpis=$('movement-kpis');kpis.replaceChildren();
    const caption=data.completa?'En el período consultado':'Solo movimientos recuperados · parcial';
    [['Movimientos',String(data.movimientos.length),'Operaciones recuperadas','blue'],['Ingresos',money(credits,currency),caption,'green'],['Egresos',money(debits,currency),caption,'amber'],['Saldo actual',last?.monto===undefined?'Sin dato':money(last.monto,currency),'Informado por el banco','slate']].forEach(([title,value,note,tone])=>{const card=el('div',undefined,`movement-kpi ${tone}`);card.append(el('small',title),el('strong',value),el('span',note));kpis.append(card);});kpis.hidden=false;
    const summary=$('movement-summary');summary.hidden=false;summary.className='notice '+(data.completa?'neutral':'error');
    let text=data.completa?'Consulta completa. Los filtros se aplican a los resultados mostrados; el XLSX incluye todo el período.':'Consulta incompleta: los importes reflejan únicamente los movimientos recuperados. Rangos pendientes: '+JSON.stringify(data.rangos_incompletos||[])+'.';
    if(last?.saldo!==undefined)text+=` Saldo al cierre consultado: ${money(last.saldo,currency)}.`;
    if(data.aviso_homologacion)text+=' '+data.aviso_homologacion;summary.textContent=text;
  }catch(error){if(version===movementVersion){$('movement-result-context').textContent='No se pudo completar la consulta.';movementEmpty('No pudimos cargar los movimientos','Revisá la cuenta y el período e intentá nuevamente.');}throw error;}
  finally{$('movement-form').removeAttribute('aria-busy');}
});};
$('export-movements').onclick=()=>action($('export-movements'),()=>{if(!movementQuery)throw Error('Consultá los movimientos antes de descargar.');const params=new URLSearchParams({nro_cuenta:movementQuery.account,fecha_desde:movementQuery.from,fecha_hasta:movementQuery.to});return downloadFile('/export/movimientos.xlsx?'+params);});
$('movement-clear-filters').onclick=()=>{['movement-search','movement-amount-filter','movement-type'].forEach(id=>$(id).value='');state.movementPage=1;renderMovementRows();};
['movement-account','movement-start','movement-end'].forEach(id=>$(id).addEventListener('change',clearMovementQuery));
['movement-search','movement-amount-filter','movement-type'].forEach(id=>$(id).addEventListener('input',()=>{state.movementPage=1;renderMovementRows();}));
$('movement-page-prev').onclick=()=>{state.movementPage=Math.max(1,state.movementPage-1);renderMovementRows();};
$('movement-page-next').onclick=()=>{state.movementPage+=1;renderMovementRows();};
document.querySelectorAll('.movement-range').forEach(button=>button.onclick=()=>{
  const days=Number(button.dataset.days),end=new Date(),start=new Date(end);start.setDate(start.getDate()-(days-1));
  $('movement-start').value=localDate(start);$('movement-end').value=localDate(end);clearMovementQuery();
  document.querySelectorAll('.movement-range').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
});
['movement-start','movement-end'].forEach(id=>$(id).addEventListener('input',()=>document.querySelectorAll('.movement-range').forEach(button=>button.setAttribute('aria-pressed','false'))));
$('test-beneficiary').onchange=()=>{
  const b=state.beneficiaries.find(x=>x.tipo===state.kind&&x.documento+'|'+x.cbuCvu===$('test-beneficiary').value);
  if(!b)return;$('beneficiary-name').value=normalName(b.nombre);$('beneficiary-document').value=b.documento;$('beneficiary-cbu').value=b.cbuCvu||'';clearPreview();
};
$('validate-beneficiary').onclick=()=>action($('validate-beneficiary'),async()=>{
  const params=new URLSearchParams(state.kind==='transferencia'?{cbu_cvu:$('beneficiary-cbu').value}:{documento:$('beneficiary-document').value,documento_tipo:'CUIT'});
  const path=state.kind==='transferencia'?'/beneficiarios/transferencias':'/beneficiarios/echeqs';
  const data=await api(path+'?'+params);$('beneficiary-status').textContent='Respuesta del banco: '+JSON.stringify(data);message('Consulta de beneficiario recibida. Verificá que los datos y el estado permitan operar.','neutral');
});
$('cheque-type').onchange=()=>{resetChequeDate();clearPreview();};
$('payment-form').addEventListener('input',clearPreview);$('payment-form').addEventListener('change',clearPreview);
$('payment-form').onsubmit=e=>{e.preventDefault();action(e.submitter,previewPayment);};
$('new-instruction').onclick=()=>{newInstruction();message('Nueva instrucción creada. Usala para un pago nuevo; para un envío anterior consultá su estado.','neutral');};
$('confirm-payment').onchange=()=>{$('send-payment').disabled=!state.preview||!$('confirm-payment').checked||state.busy;};
$('send-payment').onclick=()=>{
  if(!state.preview)return;const p=state.preview.payload, b=p.beneficiarios?.[0]||p.echeqs[0];
  $('dialog-summary').textContent=`${state.config.simulacion?'DEMO LOCAL SIN ENVÍO AL BANCO':state.config.homologacion?'HOMOLOGACIÓN':'PRODUCCIÓN'} · ${money(b.monto)} para ${b.nombre||b.beneficiarioNombre}. Cuenta de débito ${p.cbuCuentaDebito}. idOrigen ${p.idOrigen}.`;
  $('send-dialog').showModal();
};
$('cancel-send').onclick=()=>$('send-dialog').close();$('confirm-send').onclick=()=>action($('confirm-send'),()=>state.driveOrderPreview?transmitDriveOrder():state.fciPreview?submitFci():transmit());
$('status-transfer-form').onsubmit=e=>{e.preventDefault();action(e.submitter,loadTrackedTransfers);};
$('payment-origin').value=sessionStorage.getItem('credicoopPendingOrigin')||newId();
 $('fci-origin').value=newId();$('fci-kind').dispatchEvent(new Event('change'));
if(sessionStorage.getItem('credicoopPendingOrigin')){$('status-origin').value=$('payment-origin').value;message('Hay un envío anterior en esta sesión. Consultá su registro local y el banco antes de repetir.','neutral');}
