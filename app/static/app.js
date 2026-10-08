'use strict';
const $ = id => document.getElementById(id);
const LAST_OPERATION_KEY='credicoopLastOperation';
const COMPANY_FCI_CBU='1910054455005400309496';
const state = { key:'', config:null, accounts:[], beneficiaries:[], orders:[], driveOrders:[], driveOrderPreview:null, kind:'transferencia', preview:null, fciPreview:null, fciAccounts:[], fciFunds:[], movements:null, busy:false, selectedOrder:null };
const money = (v, currency='ARS') => new Intl.NumberFormat('es-AR',{style:'currency',currency,minimumFractionDigits:2}).format(Number(v));
const dateLabel = v => !v ? '—' : /^\d{8}$/.test(v) ? `${v.slice(6,8)}/${v.slice(4,6)}/${v.slice(0,4)}` : /^\d{4}-\d{2}-\d{2}$/.test(v) ? v.split('-').reverse().join('/') : String(v);
const normalName = v => v.normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-zA-Z0-9 ]/g,'').trim().toUpperCase();
const message = (text,type='neutral') => { $('notice').textContent=text; $('notice').className=`notice ${type}`; $('notice').hidden=false; };
const newId = () => crypto.randomUUID();
const el = (tag,text,cls) => {const x=document.createElement(tag);if(text!==undefined)x.textContent=String(text);if(cls)x.className=cls;return x;};
function readLastOperation(){
  try{
    const raw=sessionStorage.getItem(LAST_OPERATION_KEY);
    return raw?JSON.parse(raw):null;
  }catch(_){return null;}
}
function rememberLastOperation(kind,idOrigen,idOperacion=''){
  try{sessionStorage.setItem(LAST_OPERATION_KEY,JSON.stringify({kind,idOrigen:idOrigen||'',idOperacion:idOperacion||''}));}catch(_){/* ignore */}
}
function applyLastOperationToStatus(){
  const last=readLastOperation();
  if(!last)return false;
  if(last.kind)$('status-kind').value=last.kind;
  $('status-origin').value=last.idOrigen||'';
  $('status-operation').value=last.idOperacion||'';
  return Boolean(last.idOrigen||last.idOperacion);
}
function showBankExchanges(exchanges,status,localError=null){
  const panel=$('exchange-log');
  const list=$('bank-exchange-list');
  const statusPill=$('exchange-status');
  if(!panel||!list||!statusPill)return;
  list.replaceChildren();
  panel.hidden=false;statusPill.textContent=String(status);
  if(!exchanges.length){
    list.append(el('p',localError
      ?localError
      :'Esta consulta no produjo una llamada a la API del banco.'));
    return;
  }
  exchanges.forEach((exchange,index)=>{
    const request=exchange.request||{};
    const response=exchange.response||{};
    const method=String(request.method||'HTTP').toUpperCase();
    const section=el('section',undefined,'bank-exchange');
    const heading=el('div',undefined,'bank-exchange-heading');
    const identity=el('div',undefined,'bank-exchange-identity');
    identity.append(el('span',method,`method-badge method-${method.toLowerCase()}`),el('h4',`Intercambio bancario ${index+1}`));
    heading.append(identity,el('span',request.url||'URL no disponible','exchange-url'));
    const grid=el('div',undefined,'bank-exchange-grid');
    const cards=[
      {kind:'request',label:'Request',caption:'Enviada al banco',data:request},
      {kind:'response',label:'Response',caption:response.status?`HTTP ${response.status}`:'Recibida del banco',data:response},
    ];
    cards.forEach(({kind,label,caption,data})=>{
      const card=el('article',undefined,`exchange-card exchange-card-${kind}`);
      const cardHeading=el('div',undefined,'exchange-card-heading');
      cardHeading.append(el('div',label,'exchange-card-title'),el('span',caption,'exchange-card-caption'));
      const code=el('pre');
      code.append(el('code',JSON.stringify(data,null,2)??String(data)));
      card.append(cardHeading,code);grid.append(card);
    });
    section.append(heading,grid);list.append(section);
  });
}
function beneficiaryResponseRows(value,path='',rows=[]){
  if(Array.isArray(value)){
    if(!value.length)rows.push([path,'[]']);
    else value.forEach((item,index)=>beneficiaryResponseRows(item,`${path}[${index}]`,rows));
  }else if(value!==null&&typeof value==='object'){
    const entries=Object.entries(value);
    if(!entries.length)rows.push([path,'{}']);
    else entries.forEach(([key,item])=>beneficiaryResponseRows(item,path?`${path}.${key}`:key,rows));
  }else rows.push([path,value===null?'null':String(value)]);
  return rows;
}
function displayBeneficiaryResponse(data){
  const fields=$('beneficiary-response-fields');
  fields.replaceChildren();
  beneficiaryResponseRows(data).forEach(([field,value])=>{
    const row=el('tr');
    row.append(el('td',field),el('td',value));
    fields.append(row);
  });
  $('beneficiary-response-json').textContent=JSON.stringify(data,null,2)??String(data);
  $('beneficiary-response-status').textContent=`${fields.rows.length} campos recibidos`;
  $('beneficiary-response-panel').hidden=false;
}
async function api(path, options={}) {
  if(!state.key)throw Error('Ingresá la clave API local y presioná Conectar.');
  const headers = {'X-API-Key':state.key, ...options.headers};
  if(options.body)headers['Content-Type']='application/json';
  let response;
  try {response=await fetch(path,{...options,headers});}catch{
    const error='No se obtuvo respuesta del servicio local. Si estabas enviando, consultá el registro antes de repetir.';
    showBankExchanges([],'Sin respuesta',error);throw Error(error);
  }
  let data;
  try{const body=await response.text();data=body?JSON.parse(body):null;}catch{
    const error='El servicio devolvió una respuesta inesperada. Si era un envío, consultá el estado antes de repetir.';
    showBankExchanges([],`${response.status} ${response.statusText}`,error);throw Error(error);
  }
  const exchangeId=response.headers.get('X-Bank-Exchange-ID');
  let exchanges=[];
  let exchangeError=null;
  if(exchangeId){
    try{
      const exchangeResponse=await fetch(`/intercambios-banco/${encodeURIComponent(exchangeId)}`,{headers:{'X-API-Key':state.key}});
      const exchangeData=await exchangeResponse.json();
      if(exchangeResponse.ok&&Array.isArray(exchangeData.intercambios))exchanges=exchangeData.intercambios;
      else exchangeError=exchangeData.error||exchangeData.detail||`HTTP ${exchangeResponse.status}`;
    }catch(error){exchangeError=`No se pudieron recuperar los detalles del intercambio bancario: ${error.message}`;}
  }
  const localError=!response.ok
    ?`La API local rechazó la operación antes de completar una llamada al banco: ${data?.error||data?.detail||'error sin detalle'}.`
    :exchangeError?`No se pudieron cargar los intercambios del banco: ${exchangeError}`:null;
  showBankExchanges(exchanges,`${response.status} ${response.statusText}`,localError);
  if(!response.ok){
    const detail=data.error||data.detail||'La solicitud no se pudo completar.';
    let text=Array.isArray(detail)?detail.map(x=>`${x.loc.join('.')}: ${x.msg}`).join(' · '):String(detail);
    if(data.detalle_banco)text+=' '+JSON.stringify(data.detalle_banco);
    if(data.resultado_incierto)text+=' Resultado incierto: no crees otro pago para repetirlo.';
    throw Error(text);
  }
  return data;
}
async function action(button, fn) {
  const wasDisabled = button.disabled; button.disabled = true;
  try {
    await fn();
  } catch (e) {
    const msg = String(e?.message || e || 'Error inesperado');
    // If backend reports duplicate idOrigen, clear pending and generate a new one for the user
    const low = msg.toLowerCase();
    // Robust detection for duplicate idOrigen responses (varias redacciones posibles)
    if ((low.includes('idorigen') && (low.includes('registr') || low.includes('ya registr'))) || low.includes('id origen ya registrado')) {
      // remove pending and regenerate a fresh idOrigen for the user
      sessionStorage.removeItem('credicoopPendingOrigin');
      try{
        const fresh = newId();
        $('payment-origin').value = fresh;
        // Clear any status fields showing the old origin/operation
        if($('status-origin')) $('status-origin').value = '';
        if($('status-operation')) $('status-operation').value = '';
      }catch(_){/* ignore DOM errors */}
      message('El idOrigen anterior ya estaba registrado. Se generó un nuevo idOrigen para esta sesión. Conservá el nuevo valor.', 'neutral');
    }
    message(msg, 'error');
  } finally {
    button.disabled = wasDisabled;
  }
}
function clearPreview(){state.preview=null;$('payment-preview').hidden=true;$('confirm-payment').checked=false;$('send-payment').disabled=true;}
function clearFciPreview(){state.fciPreview=null;$('fci-preview').hidden=true;$('fci-confirm').checked=false;$('fci-send').disabled=true;}
function setChequeVisibility(visible){
  // Ensure cheque-only fields are consistently shown/hidden and required attributes set
  try{
    const idsToToggle = ['cheque-type-label','cheque-date-label','cheque-character-label'];
    idsToToggle.forEach(id=>{const el=document.getElementById(id);if(el)el.hidden=!visible;});
    const cbuLabel = document.getElementById('cbu-label'); if(cbuLabel) cbuLabel.hidden = visible;
    const beneficiaryCbu = document.getElementById('beneficiary-cbu'); if(beneficiaryCbu) beneficiaryCbu.required = !visible;
    const chequeDate = document.getElementById('cheque-date'); if(chequeDate) chequeDate.required = visible;
  }catch(e){/* non-blocking */}
}

function showView(view){
  clearPreview();
  clearFciPreview();
  document.querySelectorAll('.view').forEach(x=>x.hidden=true);
  document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  const titles={cuentas:'Cuentas y saldos',movimientos:'Movimientos',transferencias:'Transferencias',echeqs:'eCheqs',proveedores:'Preparación de pagos',seguimiento:'Seguimiento',fci:'Fondos comunes de inversión'};
  $('page-title').textContent=titles[view];
  if(view==='transferencias'){
    // Show payment form for transfers
    const oldKind=state.kind; state.kind='transferencia'; $('view-pago').hidden=false;
    if(oldKind!==state.kind){$('beneficiary-name').value='';$('beneficiary-document').value='';$('beneficiary-cbu').value='';$('beneficiary-response-panel').hidden=true;}
    $('payment-heading').textContent='Preparar transferencia';
    setChequeVisibility(false); populateBeneficiaries(); $('test-order-note').hidden=!state.selectedOrder;
  }else if(view==='echeqs'){
    // Show eCheq listing/management view
    $('view-echeqs').hidden=false; populateEcheqCbus();
  }else{$(`view-${view}`).hidden=false;}
}

// Show payment form for a given kind without overriding navigation intent
function showPayment(kind){
  clearPreview(); clearFciPreview(); document.querySelectorAll('.view').forEach(x=>x.hidden=true);
  // mark transferencias nav active because payment form is under that view
  document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.view==='transferencias'));
  state.kind = kind; $('view-pago').hidden = false; $('payment-heading').textContent = (kind==='echeq'?'Preparar eCheq':'Preparar transferencia');
  setChequeVisibility(kind==='echeq'); populateBeneficiaries(); $('test-order-note').hidden = !state.selectedOrder;
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
  const [accountsResponse,fundsResponse]=await Promise.all([
    api('/fci/cuentas-comitentes'),api('/fci/fondos')
  ]);
  const accountData=accountsResponse.data,fundData=fundsResponse.data;
  if(!Array.isArray(accountData?.cuentasComitentes))
    throw Error('La respuesta FCI no contiene una lista válida de cuentas comitentes.');
  const linkedAccounts=Array.isArray(accountData?.cuentasVinculadas)?accountData.cuentasVinculadas:[];
  if(!Array.isArray(fundData?.detalleFondo))throw Error('La respuesta FCI no contiene una lista de fondos válida.');
  state.fciAccounts=accountData.cuentasComitentes;state.fciFunds=fundData.detalleFondo;
  populateFciInputs();
  $('fci-profile').textContent=`Perfil ${accountData.perfilInversor||'sin informar'} · Test ${accountData.estadoTestInversor||'sin informar'}`;
  const accountsBody=$('fci-accounts-body');accountsBody.replaceChildren();
  state.fciAccounts.forEach(a=>{
    const row=el('tr');[a.tipoCuenta,a.sucursalCuenta,a.numeroCuenta].forEach(v=>row.append(el('td',v)));accountsBody.append(row);
  });
  const linked=linkedAccounts.map(x=>x.cbu).filter(Boolean);
  const effectiveLinked=linked.length?linked:[COMPANY_FCI_CBU];
  const cbuSelect=$('fci-cbu'),prior=cbuSelect.value;cbuSelect.replaceChildren();
  effectiveLinked.forEach(cbu=>{const option=el('option',cbu);option.value=cbu;cbuSelect.append(option);});
  if([...cbuSelect.options].some(x=>x.value===prior))cbuSelect.value=prior;
  const linkedLabel=effectiveLinked.join(' · ');
  $('fci-linked-cbus').textContent=accountData?.avisoCbuVinculado
    ?`CBU vinculados para débito/crédito: ${linkedLabel}. ${accountData.avisoCbuVinculado}`
    :`CBU vinculados para débito/crédito: ${linkedLabel}`;
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
    // Clear pending idOrigen on successful response
    try{ sessionStorage.removeItem('credicoopPendingOrigin'); $('payment-origin').value = newId(); $('status-origin').value = ''; }catch(_){ }
    maybeClearPendingOrigin(response);
    message(`${state.config.simulacion?'Operación FCI simulada':'Operación FCI enviada a firma'}. Conservá el idOrigen ${pending.body.idOrigen} y completá la firma en BIE.`, 'success');
    clearFciPreview();
  }catch(e){
    message(`${e.message} Conservá el idOrigen ${pending.body.idOrigen} y consultá el estado antes de intentar otra operación.`,'error');
  }
}
async function loadOrders(){
  if(!state.config?.homologacion)throw Error('Las órdenes y destinatarios de ejemplo sólo están disponibles en homologación.');
  const data=await api('/homologacion/ordenes');state.orders=data.ordenes;
  const body=$('orders-body');body.replaceChildren();
  state.orders.forEach(o=>{
    const row=el('tr');[o.orden,o.proveedorOriginal,o.medioOriginal,money(o.importeOriginal),money(o.retenciones)].forEach((x,i)=>row.append(el('td',x,i>=3?'numeric':undefined)));
    const cell=el('td');const medium=el('select');medium.setAttribute('aria-label',`Medio de prueba ${o.orden}`);
    for(const [v,t] of [['transferencia','Transferencia'],['echeq','eCheq']]){const opt=el('option',t);opt.value=v;medium.append(opt);}if(o.medioOriginal==='CHE')medium.value='echeq';
    const btn=el('button','Preparar prueba','text-button');btn.type='button';btn.onclick=()=>prepareOrder(o,medium.value);cell.append(medium,btn);row.append(cell);body.append(row);
  });
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
  $('drive-order-preview').hidden=true;
  $('drive-order-confirm').checked=false;
  $('drive-order-send').disabled=true;
}
function renderDriveOrders(){
  const body=$('drive-orders-body');body.replaceChildren();
  $('drive-order-count').textContent=`${state.driveOrders.length} orden(es)`;
  const statusLabels={READY:'Lista para revisar',NEEDS_REVIEW:'Requiere revisión',DUPLICATE:'Duplicada',ENVIADA_A_FIRMA:'Enviada a firma',RESPUESTA_RECIBIDA:'Respuesta recibida',RESULTADO_INCIERTO:'Resultado incierto',ERROR:'Error'};
  state.driveOrders.forEach(order=>{
    const row=el('tr');
    [order.source_name,order.supplier?.name||'—',order.method||'—',order.amount?money(order.amount):'—',statusLabels[order.status]||order.status].forEach((value,index)=>row.append(el('td',value,index===3?'numeric':undefined)));
    const actionCell=el('td');
    if(order.status==='READY'){
      const button=el('button','Revisar','text-button');button.type='button';
      button.onclick=()=>action(button,()=>previewDriveOrder(order));actionCell.append(button);
    }else if(order.reason){
      const reason=el('small',order.reason,'muted');reason.title=order.reason;actionCell.append(reason);
    }else actionCell.append(el('span','—','muted'));
    row.append(actionCell);body.append(row);
  });
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
  $('drive-preview-summary').replaceChildren();
  addDriveReview('Archivo',result.orden.archivo);
  addDriveReview('Proveedor',result.orden.proveedor);
  addDriveReview('Medio',result.orden.medio);
  addDriveReview('Importe',money(result.orden.importe));
  addDriveReview('Cuenta de débito',cbu);
  addDriveReview('idOrigen',result.payload_banco.idOrigen);
  $('drive-preview-json').textContent=JSON.stringify(result.payload_banco,null,2);
  $('drive-order-preview').hidden=false;
  message('Vista previa lista. No se envió ninguna operación al banco.','success');
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
  $('send-dialog').close();state.busy=true;$('confirm-send').disabled=true;$('drive-order-send').disabled=true;
  const payload=pending.payload,item=payload.beneficiarios?.[0]||payload.echeqs[0];
  const kind=payload.beneficiarios?'transferencia':'echeq';
  sessionStorage.setItem('credicoopPendingOrigin',payload.idOrigen);
  $('status-origin').value=payload.idOrigen;$('status-kind').value=kind;$('status-operation').value='';
  try{
    const response=await api(`/ordenes-pago/${encodeURIComponent(pending.sourceId)}/enviar`,{
      method:'POST',body:JSON.stringify({cbuCuentaDebito:pending.cbu})
    });
    const idOperacion=String(response.respuesta_banco?.data?.idOperacion||'');
    $('status-operation').value=idOperacion;
    rememberLastOperation(kind,payload.idOrigen,idOperacion);
    try{ sessionStorage.removeItem('credicoopPendingOrigin'); $('payment-origin').value = newId(); }catch(_){ }
    showOperation(response);maybeClearPendingOrigin(response);clearDriveOrderPreview();await loadDriveOrders();
    message(`${state.config.simulacion?'Operación simulada':'Orden enviada a firma'} para ${item.nombre||item.beneficiarioNombre}. Consultá su estado y completá la firma en BIE.`, 'success');
  }catch(error){
    clearDriveOrderPreview();
    try{await loadDriveOrders();}catch(refreshError){throw Error(`${error.message} No se pudo actualizar el estado de la orden (${refreshError.message}); consultá el registro y el banco antes de repetir.`);}
    throw Error(`${error.message} Consultá el registro de la orden y el banco antes de repetir.`);
  }finally{state.busy=false;$('confirm-send').disabled=false;}
}
function prepareOrder(order,kind){
  if(!state.config?.homologacion){message('Las órdenes de ejemplo sólo se usan en homologación.','error');return;}
  state.selectedOrder=order;newInstruction(true); 
  // For eCheq orders, open the payment form pre-configured for eCheq; for transfer, open transfer payment
  if(kind==='echeq'){ showPayment('echeq'); } else { showView('transferencias'); }
  $('test-order-note').textContent=`Prueba de la orden ${order.orden}. Proveedor original: ${order.proveedorOriginal}. Importe original: ${money(order.importeOriginal)}. Elegí un beneficiario de homologación; esta instrucción no modifica la orden ni la planilla original.`;
  $('test-order-note').hidden=false;$('payment-amount').value='15.79';
  // Usar exclusivamente el calendario operativo del banco para este ejemplo.
  resetChequeDate();message('Orden cargada para prueba. Elegí un beneficiario y revisá cuenta, importe y fecha.','neutral');
}
function resetChequeDate(){
  if(!state.config)return;
  const d=state.config.fecha_operativa_banco;
  if($('cheque-type').value==='ECHC')$('cheque-date').value=d;
  else{const next=new Date(d+'T00:00:00Z');next.setUTCDate(next.getUTCDate()+7);$('cheque-date').value=next.toISOString().slice(0,10);}
}
function newInstruction(fromOrder=false){
  clearPreview();
  // Preserve a pending idOrigen while the previous operation is unresolved.
  const pending = sessionStorage.getItem('credicoopPendingOrigin');
  if(pending){
    // Keep the pending origin and warn the user instead of generating a new one.
    $('payment-origin').value = pending; 
    message('Hay un idOrigen pendiente para esta sesión. Consultá su estado antes de generar uno nuevo.','neutral');
  }else{
    $('payment-origin').value = newId();
  }
  $('beneficiary-name').value='';$('beneficiary-document').value='';$('beneficiary-cbu').value='';
  $('test-beneficiary').value='';$('payment-amount').value='15.79';
  if(!fromOrder){state.selectedOrder=null;$('test-order-note').hidden=true;}
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

// Auto-clear pending idOrigen when bank confirms an idOperacion (sent to firma)
function maybeClearPendingOrigin(response){
  try{
    const idOp = response?.respuesta_banco?.data?.idOperacion || response?.idOperacion || null;
    if(idOp){
      sessionStorage.removeItem('credicoopPendingOrigin');
      $('payment-origin').value = newId();
    }
  }catch(e){/* non-blocking */}
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
    const idOperacion=String(response.respuesta_banco?.data?.idOperacion||'');
    $('status-operation').value=idOperacion;
    rememberLastOperation(p.kind,p.body.idOrigen,idOperacion);
    try{ sessionStorage.removeItem('credicoopPendingOrigin'); $('payment-origin').value = newId(); }catch(_){ }
    showOperation(response);maybeClearPendingOrigin(response);showView('seguimiento');
    const status=response.respuesta_banco?.data?.estadoOperacion?.descripcion||'Respuesta recibida';
    message(`${state.config.simulacion?'Respuesta simulada':'Respuesta del banco'}: ${status}. ${state.config.simulacion?'Esta demostración no envía instrucciones al banco.':'Consultá el estado y completá firma y activación en BIE.'}`,status.toLowerCase().includes('rechaz')?'error':'success');
  }catch(e){
    clearPreview();showView('seguimiento');message(`${e.message} Conservá el idOrigen ${p.body.idOrigen} y revisá el registro local antes de repetir.`,'error');
  }finally{state.busy=false;$('confirm-send').disabled=false;}
}
function showOperation(data){
  $('operation-result').hidden=false;$('operation-json').textContent=JSON.stringify(data,null,2);
  const d=data.respuesta_banco?.data||data.data||data.resultado?.data||data;
  $('operation-state').textContent=d.estadoOperacion?.descripcion||data.estado||'Respuesta recibida';
}
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>{
  if(!state.busy){
    if(b.dataset.view==='transferencias'||b.dataset.view==='echeqs')state.selectedOrder=null;
    showView(b.dataset.view);
    if(b.dataset.view==='fci'&&state.key&&!state.fciAccounts.length)action($('refresh-fci'),loadFciData);
    if(b.dataset.view==='proveedores'&&state.key&&!state.config?.simulacion)action($('sync-drive-orders'),()=>loadDriveOrders());
  }
});
$('connect').onclick=()=>action($('connect'),async()=>{
  state.key=$('api-key').value.trim();clearPreview();state.config=await api('/configuracion');
  $('environment').textContent=state.config.simulacion?'Demo local · Sin banco':state.config.homologacion?'Homologación':'Producción';
  $('connection-status').textContent=`Adherente ${state.config.adherente}`;
  $('movement-start').value=state.config.fecha_operativa_banco.slice(0,8)+'01';resetChequeDate();
  state.beneficiaries=[];state.orders=[];
  if(state.config.homologacion)state.beneficiaries=(await api('/homologacion/beneficiarios')).beneficiarios;
  populateBeneficiaries();
  await loadAccounts();message(`${state.config.simulacion?'Demostración con respuestas simuladas. No se contacta al banco.':'Conectado.'} Fecha operativa: ${dateLabel(state.config.fecha_operativa_banco)}.`, 'success');
});
$('sync-drive-orders').onclick=()=>action($('sync-drive-orders'),()=>loadDriveOrders(true));
// Echeq UI: new issuance button
$('echeq-new-issuance')?.addEventListener('click',()=>{ newInstruction(true); showPayment('echeq'); });
$('drive-debit-account').onchange=clearDriveOrderPreview;
$('drive-order-confirm').onchange=()=>$('drive-order-send').disabled=!state.driveOrderPreview||!$('drive-order-confirm').checked||state.busy;
$('drive-order-send').onclick=()=>{
  const pending=state.driveOrderPreview;if(!pending)return;
  const item=pending.payload.beneficiarios?.[0]||pending.payload.echeqs[0];
  $('dialog-summary').textContent=`${state.config.homologacion?'HOMOLOGACIÓN':'PRODUCCIÓN'} · Orden ${pending.summary.archivo}, ${money(item.monto)} para ${item.nombre||item.beneficiarioNombre}. Cuenta de débito ${pending.cbu}. idOrigen ${pending.payload.idOrigen}. La operación se enviará a firma; no se ejecutará sin la firma en BIE.`;
  $('send-dialog').showModal();
};
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
$('homo-dates').onclick=()=>{if(!state.config){message('Conectá el servicio para conocer la fecha operativa.','error');return;}$('movement-start').value=state.config.fecha_operativa_banco.slice(0,8)+'01';$('movement-end').value=state.config.fecha_operativa_banco;};
$('movement-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{
  const params=new URLSearchParams({fecha_desde:$('movement-start').value});if($('movement-end').value)params.set('fecha_hasta',$('movement-end').value);
  const data=await api(`/cuentas/${encodeURIComponent($('movement-account').value)}/movimientos?${params}`);state.movements=data;
  const currency=state.accounts.find(a=>String(a.nroCuenta)===$('movement-account').value)?.moneda||'ARS';
  $('download-movements').disabled=false;const body=$('movements-body');body.replaceChildren();
  data.movimientos.forEach(m=>{const row=el('tr'),amount=(m.indDBCR==='DB'?-1:1)*Number(m.monto);[dateLabel(m.fecha),m.descripcion,m.indDBCR,m.nroComprobante||'—',money(amount,currency),money(m.saldo,currency)].forEach((x,i)=>row.append(el('td',x,i>=4?`numeric ${i===4?(amount<0?'negative':'positive'):''}`:undefined)));body.append(row);});
  const summary=$('movement-summary');summary.hidden=false;summary.className='notice '+(data.completa?'neutral':'error');
  let text=`${data.movimientos.length} movimientos · ${dateLabel(data.fecha_desde)} al ${dateLabel(data.fecha_hasta)}.`;
  const last=data.encabezados?.[0]?.datos;if(last)text+=` Saldo actual: ${money(last.monto,currency)}. Saldo al cierre consultado: ${money(last.saldo,currency)}.`;
  if(!data.completa)text+=' La consulta está incompleta: '+JSON.stringify(data.rangos_incompletos);
  if(data.aviso_homologacion)text+=' '+data.aviso_homologacion;summary.textContent=text;
});};
$('download-movements').onclick=()=>{if(!state.movements)return;const blob=new Blob([JSON.stringify(state.movements,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=el('a');a.href=url;a.download='movimientos.json';a.click();URL.revokeObjectURL(url);};
$('test-beneficiary').onchange=()=>{
  const b=state.beneficiaries.find(x=>x.tipo===state.kind&&x.documento+'|'+x.cbuCvu===$('test-beneficiary').value);
  $('beneficiary-response-panel').hidden=true;
  if(!b)return;$('beneficiary-name').value=normalName(b.nombre);$('beneficiary-document').value=b.documento;$('beneficiary-cbu').value=b.cbuCvu||'';clearPreview();
};
$('beneficiary-document').addEventListener('input',()=>$('beneficiary-response-panel').hidden=true);
$('beneficiary-cbu').addEventListener('input',()=>$('beneficiary-response-panel').hidden=true);
$('validate-beneficiary').onclick=()=>action($('validate-beneficiary'),async()=>{
  const document=$('beneficiary-document').value.trim(),cbu=$('beneficiary-cbu').value.trim();
  if(state.kind==='echeq'&&!/^\d{11}$/.test(document))throw Error('Ingresá un CUIT, CUIL o CDI de 11 dígitos para consultar el beneficiario de eCheq.');
  if(state.kind==='transferencia'&&!/^\d{22}$/.test(cbu))throw Error('Ingresá un CBU o CVU de 22 dígitos para consultar el beneficiario de transferencia.');
  $('beneficiary-response-panel').hidden=true;
  const params=new URLSearchParams(state.kind==='transferencia'?{cbu_cvu:cbu}:{documento:document,documento_tipo:'CUIT'});
  const path=state.kind==='transferencia'?'/beneficiarios/transferencias':'/beneficiarios/echeqs';
  const data=await api(path+'?'+params);displayBeneficiaryResponse(data);$('beneficiary-status').textContent='Consulta recibida; revisá todos los datos devueltos abajo.';message('Consulta de beneficiario recibida. Verificá que los datos y el estado permitan operar.','neutral');
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
$('status-form').onsubmit=e=>{e.preventDefault();action(e.submitter,async()=>{
  const kind=$('status-kind').value,params=new URLSearchParams(),op=$('status-operation').value.trim(),origin=$('status-origin').value.trim();
  if(op)params.set('id_operacion',op);if(kind==='transferencia'&&origin)params.set('id_origen',origin);
  if(!op&&(!origin||kind==='echeq'))throw Error(kind==='echeq'?'Para consultar eCheq al banco necesitás idOperacion. Si se perdió la respuesta, usá "Consultar último envío" o revisá el registro local y BIE.':'Ingresá idOperacion o idOrigen.');
  showOperation(await api((kind==='transferencia'?'/transferencias/estado':'/echeqs/estado')+'?'+params));
});};
$('status-last-operation').onclick=()=>action($('status-last-operation'),async()=>{
  if(!applyLastOperationToStatus())throw Error('No hay un envío reciente guardado en esta sesión.');
  showView('seguimiento');
  const kind=$('status-kind').value,op=$('status-operation').value.trim(),origin=$('status-origin').value.trim();
  if(kind==='echeq'&&!op){
    showOperation(await api(`/operaciones/echeq/${encodeURIComponent(origin)}`));
    message('Se mostró el registro local del último eCheq. Para consultar al banco todavía necesitás el idOperacion.','neutral');
    return;
  }
  const params=new URLSearchParams();
  if(op)params.set('id_operacion',op);
  if(kind==='transferencia'&&origin)params.set('id_origen',origin);
  showOperation(await api((kind==='transferencia'?'/transferencias/estado':'/echeqs/estado')+'?'+params));
});
$('local-status').onclick=()=>action($('local-status'),async()=>{const origin=$('status-origin').value.trim();if(!origin)throw Error('Ingresá idOrigen.');showOperation(await api(`/operaciones/${$('status-kind').value}/${encodeURIComponent(origin)}`));});
// --- eCheq listing and management UI handlers ---
async function echeqListSubmit(e){
  if(e) e.preventDefault();
  const filtro = { gestion: $('echeq-gestion').value, estado: $('echeq-estado').value, pagina: Number($('echeq-pagina').value)||1, limite: Number($('echeq-limite').value)||20 };
  const cuit = $('echeq-cuit').value.trim(); if(cuit) filtro.cuitCuilCdi = cuit.replace(/-/g,'');
  const desde = $('echeq-fecha-desde').value; if(desde) filtro.fechaPagoDesde = desde.replace(/-/g,'');
  const hasta = $('echeq-fecha-hasta').value; if(hasta) filtro.fechaPagoHasta = hasta.replace(/-/g,'');
  const payload = { idOrigen: newId(), filtro };
  const result = await api('/echeqs/lista',{method:'POST',body:JSON.stringify(payload)});
  $('echeq-list-json').textContent = JSON.stringify(result,null,2);
  $('echeq-list-result').hidden = false;
  // Try to render a sensible table if present
  const rows = result.data?.cheques || result.listaCheques || result.data?.listaCheques || result.data?.detalle || result.data?.resultado || null;
  const body = $('echeq-list-body'); body.replaceChildren();
  let count = 0;
  if(Array.isArray(rows)){
    rows.forEach(r=>{
      const row = el('tr');
      row.append(el('td',r.idCheque||r.id||'—'),el('td',r.numeroCheque||r.numero||'—'),el('td',r.monto||r.montoPago||'—'),el('td',r.fechaPago||r.fecha||'—'),el('td',r.estado||r.estadoOperacion||'—'));
      body.append(row);count++;
    });
  }
  $('echeq-list-count').textContent = count?`${count} eCheq(s)`:'Sin lista tabular. Revisa el JSON';
}

function populateEcheqCbus(){
  const select = $('manage-cbu'); if(!select) return; select.replaceChildren();
  const empty = el('option','Elegir CBU'); empty.value=''; select.append(empty);
  state.accounts.forEach(a=>{const cbu=a.CBU||a.cbu||''; if(a.moneda==='ARS' && /^\d{22}$/.test(cbu)){const o=el('option',`${a.nroCuenta} · ${cbu}`); o.value=cbu; select.append(o);}});
}

$('echeq-list-form')?.addEventListener('submit',e=>action($('echeq-list-button'),()=>echeqListSubmit(e)));

// Consultar emisión (idOperacion)
$('echeq-emision-button')?.addEventListener('click',()=>action($('echeq-emision-button'),async()=>{
  const id = $('echeq-emision-id')?.value.trim(); if(!id) throw Error('Ingresá idOperacion para consultar emisión.');
  const result = await api(`/echeqs/estado?id_operacion=${encodeURIComponent(id)}`);
  $('echeq-emision-json').textContent = JSON.stringify(result,null,2);
  $('echeq-emision-json').scrollTop = 0;
  // Optionally open the management form if response includes cheque identifiers
  try{
    const data = result.respuesta_banco?.data || result.data || result;
    const cheque = Array.isArray(data.cheques)?data.cheques[0]:(Array.isArray(data.echeqs)?data.echeqs[0]:null);
    if(cheque){
      const idCheque = cheque.idCheque || cheque.id || '';
      const cmc7 = cheque.cmc7 || cheque.cmc || '';
      if(idCheque) $('manage-idCheque').value = idCheque;
      if(cmc7) $('manage-cmc7').value = cmc7;
      if(cheque.cbuDestino && $('manage-cbu')){
        // try to select CBU if present in accounts
        const cbus = [...(document.getElementById('manage-cbu')?.options||[])].map(o=>o.value);
        if(cbus.includes(cheque.cbuDestino)) document.getElementById('manage-cbu').value = cheque.cbuDestino;
      }
      $('echeq-management').hidden = false;
    }
  }catch(e){/* ignore */}
}));
$('echeq-refresh')?.addEventListener('click',()=>{$('echeq-list-json').textContent='';$('echeq-list-result').hidden=true;$('echeq-list-body').replaceChildren();$('echeq-list-count').textContent='Sin consulta';});

$('echeq-preview-button')?.addEventListener('click',()=>action($('echeq-preview-button'),async()=>{
  const idCheque = $('manage-idCheque').value.trim(); const cmc7 = $('manage-cmc7').value.trim();
  if(!idCheque && !cmc7) throw Error('Informá idCheque o cmc7 para gestionar.');
  const cbu = $('manage-cbu').value.trim(); if(!/^[0-9]{22}$/.test(cbu)) throw Error('Seleccioná un CBU destino válido.');
  const accion = $('manage-accion').value; const body = { idOrigen: newId(), cbuCuenta: cbu, operadoresFirmantes: [], accion, echeqs: [{ idCheque: idCheque||undefined, cmc7: cmc7||undefined }] };
  if(accion==='DEPOSITAR'){ const monto = $('manage-monto').value.trim(); const fecha = $('manage-fecha').value; if(!monto||!fecha) throw Error('DEPOSITAR requiere monto y fecha.'); body.echeqs[0].monto = monto.replace(',','.'); body.echeqs[0].fechaPago = fecha.replace(/-/g,''); }
  if(accion==='ENDOSAR'){ body.tipoEndoso = $('manage-tipoendoso').value; const doc = $('manage-benef-doc').value.trim(); if(!doc) throw Error('ENDOSAR requiere beneficiario.'); body.beneficiario = { documento: doc, documentoTipo: 'CUIT' }; }
  const result = await api('/echeqs/gestion/previsualizar',{method:'POST',body:JSON.stringify(body)});
  $('echeq-management-json').textContent = JSON.stringify(result,null,2);$('echeq-management-preview').hidden=false; $('echeq-send-button').disabled=false;
  // store pending payload for send
  state.echeqManagementPending = { body, path: '/echeqs/gestion' };
}));

$('echeq-send-button')?.addEventListener('click',()=>action($('echeq-send-button'),async()=>{
  const pending = state.echeqManagementPending; if(!pending) throw Error('No hay previsualización.');
  const response = await api(pending.path,{method:'POST',body:JSON.stringify(pending.body)});
  $('echeq-management-json').textContent = JSON.stringify(response,null,2);
  message('Gestión enviada. Consultá el estado y completá firma si corresponde.','success');
  maybeClearPendingOrigin(response);
  $('echeq-send-button').disabled = true; $('echeq-management-preview').hidden=false; $('echeq-management').hidden=false;
}));

// populate CBU select when accounts load
const origPopulateAccounts = populateAccounts; populateAccounts = function(){ origPopulateAccounts(); populateEcheqCbus(); };

// initialize defaults
$('payment-origin').value=sessionStorage.getItem('credicoopPendingOrigin')||newId();
$('fci-origin').value=newId();$('fci-kind').dispatchEvent(new Event('change'));
if(sessionStorage.getItem('credicoopPendingOrigin')){$('status-origin').value=$('payment-origin').value;message('Hay un envío anterior en esta sesión. Consultá su registro local y el banco antes de repetir.','neutral');}
else if(readLastOperation()){applyLastOperationToStatus();}
