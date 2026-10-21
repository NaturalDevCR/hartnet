const $ = (selector) => document.querySelector(selector);
const escape = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let state, selected, tab = "fixtures", preview, editorSave;
const kinds = ["dimmer","red","green","blue","white","cold_white","warm_white","number","switch","select","constant"];
const titles = {fixtures:["Equipos","Un espacio para conectar, mapear y controlar."],patch:["Patch de universos","La dirección de cada función, sin perder de vista el conjunto."],profiles:["Biblioteca de perfiles","Crea una vez. Reutiliza, adapta y comparte."],import:["Trae tu configuración","Del YAML a un espacio visual. Conservando cada dirección."],settings:["Configuración","Conexiones, descubrimiento y herramientas del proyecto."]};
const option = (value,label,chosen) => `<option value="${escape(value)}" ${value === chosen ? "selected" : ""}>${escape(label)}</option>`;
const profileOf = f => state.project.profiles.find(p => p.id === f.profile_id);
const controlsOf = f => profileOf(f).controls;
const colorControls = f => ["red","green","blue","white","cold_white","warm_white"].map(k => controlsOf(f).find(c => c.kind === k)).filter(Boolean);
const maxOf = c => c.max ?? 256 ** c.slots.length - 1;
function lightType(f) {
  const c = controlsOf(f).map(c => c.kind);
  return c.includes("red") ? c.includes("cold_white") ? "RGBWW" : c.includes("white") ? "RGBW" : "RGB" : c.includes("cold_white") ? "Blanco dual" : c.includes("dimmer") ? "Dimmer" : "Controles";
}
function notify(message,error=false) {
  const box = $("#message"); box.hidden=false; box.classList.toggle("error",error); box.textContent=message;
}
async function api(path,method="GET",body) {
  const response = await fetch(`api/${path}`,{method,headers:body === undefined ? {} : {"Content-Type":"application/json"},body:body === undefined ? undefined : JSON.stringify(body)});
  const result = response.headers.get("Content-Type")?.includes("json") ? await response.json() : {error:await response.text()};
  if(!response.ok) throw new Error(result.error || `Error ${response.status}`);
  return result;
}
async function guarded(action) {try {await action();} catch(error) {notify(error.message,true);}}
async function refresh(renderContent=true) {state=await api("state"); renderHeader(); if(renderContent) render();}
function renderHeader() {
  $("#stat-nodes").textContent=state.project.nodes.length;
  $("#stat-fixtures").textContent=state.project.fixtures.length;
  $("#nav-count").textContent=state.project.fixtures.length;
  $("#stat-universes").textContent=new Set(state.project.fixtures.map(f=>`${f.node_id}:${f.universe}`)).size;
  $("#stat-frames").textContent=state.frames_sent.toLocaleString();
  $("#output-badge").textContent=state.output_enabled ? "Salida activa · Estado asumido" : "Salida detenida";
  $("#output-badge").classList.toggle("live",state.output_enabled);
  $("#output-toggle").textContent=state.output_enabled ? "Detener salida" : "Activar salida";
  if(state.last_error) notify(state.last_error,true);
}
function render() {
  $("#page-title").textContent=titles[tab][0]; $("#page-description").textContent=titles[tab][1];
  document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));
  ({fixtures:renderFixtures,patch:renderPatch,profiles:renderProfiles,import:renderImport,settings:renderSettings})[tab]();
}
function renderFixtures() {
  const fixtures=state.project.fixtures;
  if(!fixtures.some(f=>f.id===selected)) selected=fixtures[0]?.id;
  $("#content").innerHTML=`<div class="toolbar"><div><h2>Tu instalación <span class="badge">${fixtures.length} equipos</span></h2><p>Funciones reales. Entidades nativas en Home Assistant.</p></div><div class="actions"><button data-action="add-node">＋ Nodo</button><button class="primary" data-action="add-fixture">＋ Agregar equipo</button></div></div>${!fixtures.length ? `<div class="panel empty"><div class="empty-symbol">⌘</div><h2>Cada equipo empieza con un perfil.</h2><p>Importa tu configuración actual o crea un nodo y un mapeo. Podrás revisarlo todo antes de enviar DMX.</p><button class="primary" data-action="go-import">Importar YAML</button> <button data-action="add-profile">Crear perfil</button></div>` : `<div class="equipment-layout"><div class="panel">${fixtures.map(f=>`<button class="equipment-row ${f.id===selected ? "selected" : ""}" data-fixture="${escape(f.id)}"><span class="equipment-icon">${lightType(f)==="Controles" ? "≋" : "◈"}</span><span><strong>${escape(f.name)}</strong><small>${escape(lightType(f))} · ${controlsOf(f).reduce((n,c)=>n+c.slots.length,0)} canales mapeados</small></span><span class="address">U${f.universe}<br>CH ${String(f.start_channel).padStart(3,"0")}</span><span class="chevron">›</span></button>`).join("")}</div><div class="panel inspector" id="inspector"></div></div>`}
  ${state.project.nodes.map(n=>`<div class="node-strip"><div class="node-name"><span class="node-symbol">⌘</span><div><strong>${escape(n.name)}</strong><small>${escape(n.host)}:${n.port??6454} · ${n.max_fps??25} fps máx. · Refresh ${n.refresh_every??1}s</small></div></div><div class="actions"><span class="badge">Unicast manual</span><button data-edit-node="${escape(n.id)}">Configurar</button></div></div>`).join("")}`;
  if(selected) renderInspector();
}
function renderInspector() {
  const f=state.project.fixtures.find(f=>f.id===selected), s=state.states[f.id], colors=colorControls(f);
  const isLight=controlsOf(f).some(c=>["dimmer",...colors.map(c=>c.kind)].includes(c.kind));
  $("#inspector").innerHTML=`<div class="label">CONTROL DEL EQUIPO</div><h2>${escape(f.name)}</h2><p>${escape(profileOf(f).name)} · U${f.universe} / CH ${f.start_channel}</p>
    ${isLight ? `<div class="control"><label>Encendido <button data-action="light-toggle">${s.on ? "Apagar" : "Encender"}</button></label><label for="brightness">Brillo<output>${Math.round(s.brightness/255*100)}%</output></label><input id="brightness" aria-label="Brillo" type="range" min="0" max="255" value="${s.brightness}" data-light="brightness"></div>` : ""}
    ${colors.map((c,i)=>`<div class="control"><label for="color-${i}">${escape(c.name)}<output>${s.color[i]}</output></label><input id="color-${i}" type="range" min="0" max="255" value="${s.color[i]}" data-color="${i}"></div>`).join("")}
    ${controlsOf(f).filter(c=>["number","select","switch"].includes(c.kind)).map(c=>`<div class="control"><label for="control-${escape(c.id)}">${escape(c.name)} <output>${s.values[c.id]} ${escape(c.unit||"")}</output></label>${c.kind==="select" ? `<select id="control-${escape(c.id)}" data-control="${escape(c.id)}">${c.options.map(o=>option(o.value,o.label,s.values[c.id])).join("")}</select>` : c.kind==="switch" ? `<button id="control-${escape(c.id)}" data-switch="${escape(c.id)}">${s.values[c.id]===maxOf(c) ? "Desactivar" : "Activar"}</button>` : `<input id="control-${escape(c.id)}" type="number" min="${c.min??0}" max="${maxOf(c)}" step="1" value="${s.values[c.id]}" data-control="${escape(c.id)}">`}</div>`).join("")}
    <div class="actions"><button data-action="edit-fixture">Editar patch</button><button data-edit-profile="${escape(f.profile_id)}">Editar perfil</button></div><div class="tip">${state.output_enabled ? "Los cambios envían DMX. El protocolo no confirma el estado físico." : "Vista previa: los cambios no envían DMX mientras la salida esté detenida."}</div>`;
}
function renderPatch() {
  const universes=[...new Set(state.project.fixtures.map(f=>JSON.stringify([f.node_id,f.universe])))];
  $("#content").innerHTML=`<div class="toolbar"><h2>Mapa de canales</h2><span class="badge">Direcciones DMX 1–512</span></div><p class="section-note">Los huecos no tienen una función asignada. Esta versión los emite a 0 al activar el universo.</p>${universes.map(key=>{const [nodeId,u]=JSON.parse(key), node=state.project.nodes.find(n=>n.id===nodeId), used={};state.project.fixtures.filter(f=>f.node_id===nodeId&&f.universe===u).forEach(f=>controlsOf(f).forEach(c=>c.slots.forEach(slot=>used[f.start_channel+slot-1]=`${f.name} · ${c.name}`)));return `<h3 class="patch-header">${escape(node.name)} <span class="divider">/</span> Universo ${u}</h3><div class="patch-grid">${Array.from({length:512},(_,i)=>`<span class="slot ${used[i+1] ? "used" : ""}" title="CH ${i+1}: ${escape(used[i+1]||"Sin asignar")}">${i+1}</span>`).join("")}</div>`;}).join("")}<div class="patch-legend"><span><i></i>Mapeado</span><span><i class="free"></i>Sin asignar</span></div>`;
}
function renderProfiles() {
  $("#content").innerHTML=`<div class="toolbar"><div><h2>Perfiles reutilizables</h2><p>Offsets relativos. Sin IP ni direcciones de tu instalación.</p></div><div class="actions"><button data-action="import-profiles">Importar JSON</button><button data-action="export-profiles">Exportar perfiles ↗</button><button class="primary" data-action="add-profile">＋ Crear perfil</button></div></div><input type="file" id="profile-file" class="hidden-file" accept="application/json,.json"><div class="profile-grid">${state.project.profiles.map(p=>`<article class="panel profile-card"><div class="profile-symbol">◇</div><h3>${escape(p.name)}</h3><p>${escape(p.manufacturer||"Personalizado")} · ${escape(p.mode||"Modo personalizado")}</p><div class="profile-footer"><small>${p.controls.length} funciones · ${Math.max(...p.controls.flatMap(c=>c.slots))} slots</small><button data-edit-profile="${escape(p.id)}">Editar</button></div></article>`).join("")}</div>`;
}
function renderImport() {
  $("#content").innerHTML=`<div class="panel import-panel"><span class="badge">ha-artnet-led → HartNet</span><h2>Conserva tu patch. Mejora tus controles.</h2><p>Pega el bloque <code>light:</code> de artnet_led. La vista previa conserva host, universo, direcciones, orden de canales y valores fijos. No se envían paquetes al importar.</p><label for="legacy-yaml">Configuración YAML</label><textarea id="legacy-yaml" spellcheck="false" placeholder="light:&#10;  - platform: artnet_led&#10;    host: 192.0.2.30"></textarea><label class="check"><input type="checkbox" id="scalars" checked>Convertir dimmers independientes a entidades number (p. ej. Macro y Speed)</label><div class="actions"><button class="primary" data-action="preview-import">Revisar importación →</button><button data-action="load-example">Cargar configuración de ejemplo</button></div><div id="import-preview"></div></div>`;
}
async function previewImport() {
  preview=await api("legacy/preview","POST",{yaml:$("#legacy-yaml").value,scalars_as_numbers:$("#scalars").checked});
  $("#import-preview").innerHTML=`<div class="preview"><h3>${preview.project.fixtures.length} equipos listos para revisar</h3><div class="table-scroll"><table class="preview-table"><thead><tr><th>Equipo</th><th>Universo</th><th>Inicio</th><th>Entidades</th></tr></thead><tbody>${preview.project.fixtures.map(f=>{const p=preview.project.profiles.find(p=>p.id===f.profile_id),scalar=p.controls.every(c=>["number","constant"].includes(c.kind));return `<tr><td>${escape(f.name)}</td><td>${f.universe}</td><td>${f.start_channel}</td><td>${scalar ? "number" : "light"}</td></tr>`;}).join("")}</tbody></table></div><ul>${preview.warnings.map(w=>`<li>${escape(w)}</li>`).join("")}</ul><button class="primary" data-action="apply-import">Reemplazar patch con esta importación</button></div>`;
}
function renderSettings() {
  $("#content").innerHTML=`<div class="settings-panel panel"><div class="toolbar"><h2>Nodos y conexiones</h2><button data-action="add-node">＋ Agregar nodo</button></div>${state.project.nodes.map(n=>`<div class="node-strip"><div>${escape(n.name)}<small>${escape(n.host)}:${n.port??6454} · ${n.full_universe ? "512 canales" : "Tramas parciales"}</small></div><button data-edit-node="${escape(n.id)}">Editar</button></div>`).join("")}</div><div class="settings-panel panel"><h2>Descubrimiento Art-Net</h2><p>ArtPoll descubre nodos y universos. No identifica automáticamente las funciones de sus equipos DMX. Introduce una IP de nodo o el broadcast dirigido de tu red.</p><div class="form-grid"><label>Destino IPv4<input id="discovery-target" placeholder="192.0.2.30"></label><div class="actions"><button data-action="discover">Buscar nodos</button></div></div><div id="discovery-results"></div></div><div class="settings-panel panel"><h2>Editor avanzado del proyecto</h2><p>Incluye direcciones de instalación. Los cambios solo se guardan con salida detenida y se validan contra solapamientos. La configuración anterior queda respaldada. Las entidades nuevas aparecen automáticamente en HA; al eliminar o cambiar tipos, recarga la integración.</p><label for="project-json">Proyecto JSON</label><textarea id="project-json" spellcheck="false">${escape(JSON.stringify(state.project,null,2))}</textarea><div class="actions"><button class="primary" data-action="save-json">Validar y guardar proyecto</button><button data-action="download-project">Descargar copia del proyecto</button></div></div>`;
}
function showEditor(title,markup,save) {$("#editor-title").textContent=title;$("#editor-body").innerHTML=markup;$("#editor-error").textContent="";editorSave=save;$("#editor").showModal();}
async function saveProject(project) {state=await api("project","PUT",project);renderHeader();render();notify("Configuración validada y guardada. Salida detenida.");}
function nodeEditor(id) {
  const existing=state.project.nodes.find(n=>n.id===id), node=existing || {id:crypto.randomUUID(),name:"Nodo Art-Net",host:"",port:6454,max_fps:25,refresh_every:1,full_universe:true};
  showEditor(existing ? "Configurar nodo" : "Agregar nodo",`<div class="form-grid"><label>Nombre<input name="name" required value="${escape(node.name)}"></label><label>Dirección IPv4<input name="host" required value="${escape(node.host)}" placeholder="192.0.2.30"></label><label>Puerto UDP<input name="port" type="number" min="1" max="65535" value="${node.port??6454}"></label><label>FPS máximo<input name="max_fps" type="number" min="1" max="44" value="${node.max_fps??25}"></label><label>Refresh (segundos, 0 desactiva)<input name="refresh_every" type="number" step="0.1" min="0" max="120" value="${node.refresh_every??1}"></label><label class="check"><input name="full_universe" type="checkbox" ${node.full_universe ? "checked" : ""}>Enviar 512 canales</label></div>`,async form=>{const data=new FormData(form), candidate=structuredClone(state.project);const changed={id:node.id,name:data.get("name"),host:data.get("host"),port:Number(data.get("port")),max_fps:Number(data.get("max_fps")),refresh_every:Number(data.get("refresh_every")),full_universe:data.has("full_universe")};candidate.nodes=existing ? candidate.nodes.map(n=>n.id===id ? changed : n) : [...candidate.nodes,changed];await saveProject(candidate);});
}
function fixtureEditor(id) {
  if(!state.project.nodes.length || !state.project.profiles.length) throw new Error("Agrega al menos un nodo y un perfil antes de crear el equipo.");
  const existing=state.project.fixtures.find(f=>f.id===id), f=existing || {id:crypto.randomUUID(),name:"Equipo",node_id:state.project.nodes[0].id,profile_id:state.project.profiles[0].id,universe:1,start_channel:1};
  showEditor(existing ? "Editar equipo y patch" : "Agregar equipo",`<div class="form-grid"><label class="wide">Nombre<input name="name" required value="${escape(f.name)}"></label><label>Nodo<select name="node_id">${state.project.nodes.map(n=>option(n.id,n.name,f.node_id)).join("")}</select></label><label>Perfil<select name="profile_id">${state.project.profiles.map(p=>option(p.id,p.name,f.profile_id)).join("")}</select></label><label>Universo Art-Net (sin renumerar)<input name="universe" type="number" min="0" max="32767" value="${f.universe}"></label><label>Canal inicial DMX<input name="start_channel" type="number" min="1" max="512" value="${f.start_channel}"></label></div>`,async form=>{const data=new FormData(form),candidate=structuredClone(state.project),changed={id:f.id,name:data.get("name"),node_id:data.get("node_id"),profile_id:data.get("profile_id"),universe:Number(data.get("universe")),start_channel:Number(data.get("start_channel"))};candidate.fixtures=existing ? candidate.fixtures.map(item=>item.id===f.id ? changed : item) : [...candidate.fixtures,changed];selected=f.id;await saveProject(candidate);});
}
function channelRow(c,index) {
  return `<div class="channel-row" data-channel-row data-id="${escape(c.id)}"><label>Nombre<input data-field="name" required value="${escape(c.name)}"></label><label>Función<select data-field="kind">${kinds.map(k=>option(k,k,c.kind)).join("")}</select></label><label>Slots MSB → LSB<input data-field="slots" required value="${c.slots.join(",")}" placeholder="1,8"></label><label>Default<input data-field="default" type="number" min="0" value="${c.default??0}"></label><button type="button" data-remove-channel="${index}" aria-label="Eliminar canal">×</button><details class="wide"><summary>Rangos y opciones</summary><div class="channel-details"><label>Mínimo<input data-field="min" type="number" value="${c.min??0}"></label><label>Máximo<input data-field="max" type="number" value="${maxOf(c)}"></label><label>Valor al apagar<input data-field="off_value" type="number" value="${c.off_value??0}"></label><label>Curva<select data-field="curve">${["linear","quadratic","cubic","quadruple"].map(v=>option(v,v,c.curve||"linear")).join("")}</select></label><label class="check"><input data-field="scale_by_brightness" type="checkbox" ${c.scale_by_brightness!==false ? "checked" : ""}>Color escalado por brillo</label><label class="wide">Opciones select (JSON con label/value)<textarea data-field="options">${escape(JSON.stringify(c.options||[{label:"Manual",value:0}],null,2))}</textarea></label></div></details></div>`;
}
function profileEditor(id) {
  const existing=state.project.profiles.find(p=>p.id===id), p=structuredClone(existing || {id:crypto.randomUUID(),name:"Perfil personalizado",manufacturer:"",model:"",mode:"",controls:[{id:crypto.randomUUID(),name:"Control",kind:"number",slots:[1],default:0}]});
  showEditor(existing ? "Editar perfil compartido" : "Crear perfil",`<p class="section-note">Este perfil puede usarse en varios equipos. Los slots son relativos al canal inicial; puedes usar pares separados como 1,8 para 16 bits. Las funciones number, select y switch crean entidades independientes en el mismo dispositivo de HA.</p><div class="form-grid"><label>Nombre<input name="name" required value="${escape(p.name)}"></label><label>Fabricante<input name="manufacturer" value="${escape(p.manufacturer)}"></label><label>Modelo<input name="model" value="${escape(p.model)}"></label><label>Modo<input name="mode" value="${escape(p.mode)}" placeholder="15ch"></label></div><div class="channel-editor" id="channel-rows">${p.controls.map(channelRow).join("")}</div><button type="button" id="add-channel">＋ Función</button>`,async form=>{const data=new FormData(form),candidate=structuredClone(state.project);const changed={...p,name:data.get("name"),manufacturer:data.get("manufacturer"),model:data.get("model"),mode:data.get("mode"),controls:readChannels()};candidate.profiles=existing ? candidate.profiles.map(item=>item.id===p.id ? changed : item) : [...candidate.profiles,changed];await saveProject(candidate);});
  $("#add-channel").addEventListener("click",()=>{const index=document.querySelectorAll("[data-channel-row]").length;$("#channel-rows").insertAdjacentHTML("beforeend",channelRow({id:crypto.randomUUID(),name:"Control",kind:"number",slots:[index+1],default:0},index));});
}
function readChannels() {
  return [...document.querySelectorAll("[data-channel-row]")].map(row=>{const val=key=>row.querySelector(`[data-field="${key}"]`).value;const c={id:row.dataset.id,name:val("name"),kind:val("kind"),slots:val("slots").split(",").map(n=>Number(n.trim())),default:Number(val("default")),min:Number(val("min")),max:Number(val("max")),off_value:Number(val("off_value")),curve:val("curve"),scale_by_brightness:row.querySelector('[data-field="scale_by_brightness"]').checked};if(c.kind==="select") c.options=JSON.parse(val("options"));return c;});
}
function download(data,filename) {const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function command(body) {state=await api(`fixtures/${encodeURIComponent(selected)}/command`,"POST",body);renderHeader();renderInspector();}
document.querySelectorAll("[data-tab]").forEach(b=>b.addEventListener("click",()=>{tab=b.dataset.tab;render();}));
$("#output-toggle").addEventListener("click",()=>guarded(async()=>{state=await api("output","POST",{enabled:!state.output_enabled});renderHeader();render();notify(state.output_enabled ? "Salida DMX activada hacia los nodos configurados." : "Paquetes detenidos. El nodo puede mantener el último estado.");}));
$("#close-editor").addEventListener("click",()=>$("#editor").close());
$("#editor-form").addEventListener("submit",async event=>{event.preventDefault();try{await editorSave(event.currentTarget);$("#editor").close();}catch(error){$("#editor-error").textContent=error.message;}});
$("#editor-body").addEventListener("click",event=>{const button=event.target.closest("[data-remove-channel]");if(button) button.closest("[data-channel-row]").remove();});
$("#content").addEventListener("click",event=>guarded(async()=>{
  const b=event.target.closest("button");if(!b)return;
  if(b.dataset.fixture){selected=b.dataset.fixture;renderFixtures();return;}
  if(b.dataset.editNode){nodeEditor(b.dataset.editNode);return;}
  if(b.dataset.editProfile){profileEditor(b.dataset.editProfile);return;}
  if(b.dataset.switch){const f=state.project.fixtures.find(f=>f.id===selected),c=controlsOf(f).find(c=>c.id===b.dataset.switch);await command({values:{[c.id]:state.states[selected].values[c.id]===maxOf(c) ? c.min??0 : maxOf(c)}});return;}
  switch(b.dataset.action){
    case "add-node":nodeEditor();break;
    case "add-fixture":fixtureEditor();break;
    case "edit-fixture":fixtureEditor(selected);break;
    case "add-profile":profileEditor();break;
    case "go-import":tab="import";render();break;
    case "light-toggle":await command({on:!state.states[selected].on});break;
    case "preview-import":await previewImport();break;
    case "apply-import":await saveProject(preview.project);tab="fixtures";render();break;
    case "load-example":$("#legacy-yaml").value=await (await fetch("static/party-legacy.yaml")).text();break;
    case "export-profiles":download(await api("profiles"),"hartnet-profiles.json");break;
    case "import-profiles":$("#profile-file").click();break;
    case "save-json":await saveProject(JSON.parse($("#project-json").value));break;
    case "download-project":download(state.project,"hartnet-project.json");break;
    case "discover":{b.disabled=true;try{const results=await api("discover","POST",{target:$("#discovery-target").value});$("#discovery-results").innerHTML=results.length ? results.map(n=>`<div class="node-strip"><div><strong>${escape(n.name)}</strong><small>${escape(n.host)} · Bind ${n.bind_index} · Universos ${n.universes.join(", ")||"sin salidas"} · RDM anunciado: ${n.rdm ? "sí" : "no"}</small></div></div>`).join("") : `<p class="section-note">No se recibieron respuestas. Puedes agregar el nodo manualmente.</p>`;}finally{b.disabled=false;}break;}
  }
}));
$("#content").addEventListener("change",event=>guarded(async()=>{
  const input=event.target;
  if(input.dataset.light) await command({brightness:Number(input.value)});
  if(input.dataset.color!==undefined){const color=[...state.states[selected].color];color[Number(input.dataset.color)]=Number(input.value);await command({color});}
  if(input.dataset.control) await command({values:{[input.dataset.control]:Number(input.value)}});
  if(input.id==="profile-file" && input.files[0]){state=await api("profiles","POST",JSON.parse(await input.files[0].text()));renderHeader();render();notify("Perfiles importados. Asigna un perfil al agregar un equipo.");}
}));
await guarded(()=>refresh());
setInterval(()=>guarded(()=>refresh(false)),2000);
