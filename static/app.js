'use strict';
/* Sistema de producción y logística de Nata & Schlott: frontend sin dependencias. */
const S = { usuario: null, modulos: [], cat: null, logo: null, estado: {} };
const app = document.getElementById('app');
const REGIONES = ['Arica y Parinacota', 'Tarapacá', 'Antofagasta', 'Atacama', 'Coquimbo', 'Valparaíso', 'Metropolitana de Santiago',
  "O'Higgins", 'Maule', 'Ñuble', 'Biobío', 'La Araucanía', 'Los Ríos', 'Los Lagos', 'Aysén', 'Magallanes'];
const TIPOS_MOV = {
  COMPRA: ['Compra', 'bien'], PRODUCCION: ['Producción', 'bien'], CONSUMO_PRODUCCION: ['Consumo en producción', ''], DESPACHO: ['Despacho', ''],
  RECEPCION_TIENDA: ['Recepción en tienda', 'bien'], MERMA: ['Merma', 'mal'], INVENTARIO: ['Toma de inventario', 'dorada'], VENTA: ['Venta', ''],
  CONSUMO_INTERNO: ['Consumo interno', ''], ANULACION: ['Anulación', 'alerta'],
};
const NAV = [
  ['', [['panel', 'Panel de inicio']]],
  ['Compras', [['compras', 'Compras y proveedores', ['compras', 'proveedores']]]],
  ['Tiendas', [['tiendas', 'Tiendas'], ['bodegas', 'Bodegas']]],
  ['Artículos', [['articulos', 'Productos e insumos'], ['inventario', 'Toma de inventario'], ['historial', 'Historial'], ['mermas', 'Mermas']]],
  ['Producción', [['recetas', 'Recetas'], ['produccion', 'Producción']]],
  ['Logística', [['despachos', 'Despachos a tiendas']]],
  ['Gestión', [['reportes', 'Reportes']]],
  ['Administración', [['usuarios', 'Usuarios y perfiles'], ['config', 'Configuración']]],
];

/* ---------- utilidades ---------- */
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const can = (m, n = 1) => (S.usuario?.permisos?.[m] || 0) >= n;
const hoy = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const haceDias = n => { const d = new Date(Date.now() - n * 864e5); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const fFecha = f => f ? `${f.slice(8, 10)}-${f.slice(5, 7)}-${f.slice(0, 4)}${f.length > 10 ? ' ' + f.slice(11, 16) : ''}` : '';

function fNum(v, min = 0, max = 0) {
  const n = Number(v) || 0;
  let [e, d = ''] = Math.abs(n).toFixed(max).split('.');
  d = d.replace(/0+$/, '').padEnd(min, '0');
  e = e.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const signo = n < 0 && (Number(e.replace(/\./g, '')) || Number(d)) ? '-' : '';
  return signo + e + (d ? ',' + d : '');
}
const fPrecio = v => '$' + fNum(v, 0, 2);          // precios con separador de miles
const fPeso = v => '$' + fNum(Math.round(v || 0));  // totales en pesos, sin decimales
const fMin = v => fNum(v, 5, 5);                    // stock mínimo: miles y 5 decimales
const fCant = v => fNum(v, 0, 5);
const fPct = v => fNum(v, 1, 1) + '%';
function aNum(t) {
  t = String(t ?? '').trim().replace(/[$\s]/g, '');
  if (!t) return null;
  if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.');
  else if ((t.match(/\./g) || []).length > 1 || /^\d{1,3}\.\d{3}$/.test(t)) t = t.replace(/\./g, ''); // 1.500 = mil quinientos
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}
document.addEventListener('focusout', e => {
  const i = e.target;
  if (!i.matches?.('input.num') || !i.value.trim()) return;
  const n = aNum(i.value);
  if (Number.isNaN(n)) return;
  i.value = fNum(n, Number(i.dataset.min || 0), Number(i.dataset.dec ?? 5));
  i.dispatchEvent(new Event('input', { bubbles: true }));
});
const inputNum = (cls, v, dec = 5, min = 0) => `<input class="num ${cls}" inputmode="decimal" autocomplete="off" data-dec="${dec}" data-min="${min}" value="${v === null || v === undefined || v === '' ? '' : fNum(v, min, dec)}">`;

async function api(metodo, ruta, cuerpo) {
  const r = await fetch('/api' + ruta, {
    method: metodo, credentials: 'same-origin',
    headers: cuerpo !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (r.status === 401 && !ruta.startsWith('/login') && S.usuario) { S.usuario = null; iniciar(); }
  if (!r.ok) throw new Error(d.error || 'No se pudo completar la acción.');
  return d;
}
const qs = o => { const p = Object.entries(o).filter(([, v]) => v !== '' && v != null); return p.length ? '?' + new URLSearchParams(p) : ''; };
function aviso(t, mal) {
  const d = document.createElement('div');
  d.className = 'toast' + (mal ? ' mal' : '');
  d.textContent = t;
  $('#toasts').append(d);
  setTimeout(() => d.remove(), mal ? 6000 : 3000);
}
const logo = () => S.logo || 'logo.jpg';
const etq = (t, c = '') => `<span class="etq ${c}">${esc(t)}</span>`;
const accion = (a, t, c = '') => `<button type="button" class="btn mini ${c}" data-a="${a}">${esc(t)}</button>`;
const opciones = (lista, sel, vacio) => (vacio !== undefined ? `<option value="">${esc(vacio)}</option>` : '') +
  lista.map(o => `<option value="${esc(o.id)}" ${String(o.id) === String(sel) ? 'selected' : ''}>${esc(o.nombre)}</option>`).join('');
const claseArticulo = a => a.tipo === 'PRODUCTO' ? 'Producto' : a.tipo === 'SUBPRODUCTO' ? 'Subproducto' : a.desechable ? 'Desechable / aseo' : 'Insumo';

/* Tooltip compartido de gráficos */
const tip = $('#tip');
document.addEventListener('mousemove', e => {
  const t = e.target.closest?.('[data-tip]');
  if (!t) { tip.hidden = true; return; }
  tip.textContent = t.dataset.tip; tip.hidden = false;
  const w = tip.offsetWidth;
  tip.style.left = Math.min(e.clientX + 12, innerWidth - w - 8) + 'px';
  tip.style.top = (e.clientY - tip.offsetHeight - 10) + 'px';
});

/* ---------- tabla genérica ---------- */
function tabla(caja, cfg) {
  let q = '', orden = null, dir = 1;
  const valor = (c, r) => c.v ? c.v(r) : '';
  function dibujar() {
    let filas = cfg.filas;
    if (q) {
      const t = q.toLowerCase();
      filas = filas.filter(r => cfg.cols.some(c => c.v && String(valor(c, r) ?? '').toLowerCase().includes(t)));
    }
    if (orden !== null) {
      const c = cfg.cols[orden];
      filas = [...filas].sort((a, b) => {
        const x = valor(c, a), y = valor(c, b);
        return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? ''), 'es')) * dir;
      });
    }
    const cuerpo = filas.length ? filas.map(r => `<tr data-r="${cfg.filas.indexOf(r)}">${cfg.cols.map(c =>
      `<td class="${c.n ? 'n' : ''}">${c.h ? c.h(r) : esc(valor(c, r))}</td>`).join('')}</tr>`).join('')
      : `<tr><td colspan="${cfg.cols.length}" class="vacio">${esc(cfg.vacio || 'Sin registros.')}</td></tr>`;
    $('.tabla-marco', caja).innerHTML = `<table><thead><tr>${cfg.cols.map((c, i) =>
      `<th class="${c.n ? 'n ' : ''}${c.v ? 'ordenable' : ''}" data-c="${i}">${esc(c.t)}${orden === i ? (dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead><tbody>${cuerpo}</tbody></table>`;
    if ($('.conteo', caja)) $('.conteo', caja).textContent = `${filas.length} ${filas.length === 1 ? 'registro' : 'registros'}`;
  }
  caja.innerHTML = `<div class="tabla-barra">${cfg.buscar === false ? '<span></span>' : '<input type="search" class="buscar" placeholder="Buscar…" aria-label="Buscar en la tabla">'}
    ${cfg.csv ? '<button type="button" class="btn mini csv">Descargar CSV</button>' : ''}</div><div class="tabla-marco"></div><div class="conteo"></div>`;
  $('.buscar', caja)?.addEventListener('input', e => { q = e.target.value; dibujar(); });
  $('.csv', caja)?.addEventListener('click', () => {
    const cols = cfg.cols.filter(c => c.v);
    const celda = v => {
      if (typeof v === 'number') return String(Math.round(v * 100000) / 100000).replace('.', ',');
      let s = String(v ?? '');
      if (/^[=+\-@]/.test(s)) s = "'" + s;
      return `"${s.replace(/"/g, '""')}"`;
    };
    const lineas = [cols.map(c => celda(c.t)).join(';'), ...cfg.filas.map(r => cols.map(c => celda(valor(c, r))).join(';'))];
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['﻿' + lineas.join('\r\n')], { type: 'text/csv;charset=utf-8' }));
    a.download = cfg.csv + '.csv'; a.click(); URL.revokeObjectURL(a.href);
  });
  caja.addEventListener('click', e => {
    const th = e.target.closest('th.ordenable');
    if (th) { const i = Number(th.dataset.c); dir = orden === i ? -dir : 1; orden = i; return dibujar(); }
    const b = e.target.closest('[data-a]');
    if (b) cfg.acciones?.[b.dataset.a]?.(cfg.filas[Number(b.closest('tr').dataset.r)]);
  });
  dibujar();
}

/* ---------- modales y formularios ---------- */
function modal(titulo, html, ancho) {
  const f = document.createElement('div');
  f.className = 'modal-fondo';
  f.innerHTML = `<div class="modal ${ancho ? 'ancho' : ''}" role="dialog" aria-modal="true" aria-label="${esc(titulo)}">
    <div class="modal-cab no-imprimir"><h2>${esc(titulo)}</h2><button type="button" class="cerrar" aria-label="Cerrar">×</button></div>${html}</div>`;
  document.body.append(f);
  const cerrar = () => { f.remove(); document.removeEventListener('keydown', esc_); };
  const esc_ = e => { if (e.key === 'Escape' && document.body.lastElementChild === f) cerrar(); };
  document.addEventListener('keydown', esc_);
  $$('.cerrar', f).forEach(b => b.addEventListener('click', cerrar));
  setTimeout(() => $('input:not([type=hidden]),select,textarea', f)?.focus(), 0);
  return { el: f, cerrar };
}
function campoHtml(c, v) {
  const id = `name="${c.k}"`;
  let ctl;
  if (c.tipo === 'num') ctl = inputNum('', v ?? '', c.dec ?? 5, c.min ?? 0).replace('<input', `<input ${id}`);
  else if (c.tipo === 'select') ctl = `<select ${id}>${opciones(c.op, v, c.vacio)}</select>`;
  else if (c.tipo === 'area') ctl = `<textarea ${id} rows="${c.filas || 3}">${esc(v)}</textarea>`;
  else if (c.tipo === 'check') return `<label class="campo check ${c.todo ? 'todo' : ''}"><input type="checkbox" ${id} ${v ? 'checked' : ''}><span>${esc(c.t)}</span></label>`;
  else ctl = `<input ${id} type="${c.tipo || 'text'}" value="${esc(v)}" ${c.auto ? `autocomplete="${c.auto}"` : ''}>`;
  return `<label class="campo ${c.todo ? 'todo' : ''}"><span>${esc(c.t)}</span>${ctl}${c.ayuda ? `<small>${esc(c.ayuda)}</small>` : ''}</label>`;
}
function leerCampos(raiz, campos) {
  const d = {};
  for (const c of campos) {
    const i = $(`[name="${c.k}"]`, raiz);
    if (c.tipo === 'num') {
      const n = aNum(i.value);
      if (Number.isNaN(n)) throw new Error(`${c.t}: el número no es válido.`);
      d[c.k] = n;
    } else if (c.tipo === 'check') d[c.k] = i.checked;
    else d[c.k] = i.value;
  }
  return d;
}
function formulario(titulo, campos, valores, enviar, textoBtn = 'Guardar') {
  const m = modal(titulo, `<form novalidate><div class="campos">${campos.map(c => campoHtml(c, valores?.[c.k] ?? c.def ?? '')).join('')}</div>
    <div class="error" hidden></div><div class="modal-pie"><button type="button" class="btn cerrar2">Cancelar</button><button class="btn primario">${esc(textoBtn)}</button></div></form>`);
  $('.cerrar2', m.el).addEventListener('click', m.cerrar);
  conEnvio($('form', m.el), m, () => enviar(leerCampos(m.el, campos)));
  return m;
}
function conEnvio(form, m, fn) {
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const err = $('.error', m.el), btn = $('button.primario', form);
    err.hidden = true; if (btn) btn.disabled = true;
    try { await fn(); m.cerrar(); }
    catch (x) { err.textContent = x.message; err.hidden = false; }
    finally { if (btn) btn.disabled = false; }
  });
}
function confirmar(titulo, texto, fn, btn = 'Confirmar') {
  const m = modal(titulo, `<p>${esc(texto)}</p><div class="error" hidden></div><form><div class="modal-pie"><button type="button" class="btn cerrar2">Volver</button><button class="btn primario">${esc(btn)}</button></div></form>`);
  $('.cerrar2', m.el).addEventListener('click', m.cerrar);
  conEnvio($('form', m.el), m, fn);
}

/* Editor de líneas: artículo + cantidad (+ precio opcional) */
function editorLineas(caja, cfg) {
  const opts = cfg.articulos.map(a => `<option value="${a.id}">${esc(a.codigo)} · ${esc(a.nombre)}</option>`).join('');
  caja.innerHTML = `<div class="tabla-marco"><table class="lineas"><thead><tr><th>Artículo</th><th class="n">Cantidad</th><th>Unidad</th>
    ${cfg.stock ? '<th class="n">Disponible</th>' : ''}${cfg.precio ? `<th class="n">${esc(cfg.precio)}</th><th class="n">Subtotal</th>` : ''}<th></th></tr></thead><tbody></tbody></table></div>
    <button type="button" class="btn mini agregar" style="margin-top:6px">+ Agregar línea</button>`;
  const cuerpo = $('tbody', caja);
  const por = id => cfg.articulos.find(a => String(a.id) === String(id));
  function refrescar(tr) {
    const a = por($('select', tr).value);
    $('.u', tr).textContent = a?.unidad || '';
    if (cfg.stock) $('.d', tr).textContent = a ? fCant(cfg.stock[a.id] || 0) : '';
    if (cfg.precio) $('.s', tr).textContent = fPeso((aNum($('.q', tr).value) || 0) * (cfg.editaPrecio ? aNum($('.p', tr).value) || 0 : a?.precio || 0));
    cfg.alCambiar?.();
  }
  function agregar(v = {}) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><select aria-label="Artículo"><option value="">Selecciona…</option>${opts}</select></td>
      <td class="n">${inputNum('q', v.cantidad ?? '', 5).replace('<input', '<input aria-label="Cantidad"')}</td><td class="u tenue"></td>
      ${cfg.stock ? '<td class="n d tenue"></td>' : ''}
      ${cfg.precio ? `<td class="n">${cfg.editaPrecio ? inputNum('p', v.precio ?? '', 2).replace('<input', '<input aria-label="Precio"') : '<span class="pf"></span>'}</td><td class="n s"></td>` : ''}
      <td><button type="button" class="btn mini peligro quitar" aria-label="Quitar línea">×</button></td>`;
    cuerpo.append(tr);
    if (v.articulo_id) $('select', tr).value = v.articulo_id;
    const alSelect = () => {
      const a = por($('select', tr).value);
      if (cfg.precio && cfg.editaPrecio && a && !$('.p', tr).value) $('.p', tr).value = fNum(a.precio, 0, 2);
      if (cfg.precio && !cfg.editaPrecio) $('.pf', tr).textContent = a ? fPrecio(a.precio) : '';
      refrescar(tr);
    };
    $('select', tr).addEventListener('change', alSelect);
    tr.addEventListener('input', () => refrescar(tr));
    $('.quitar', tr).addEventListener('click', () => { tr.remove(); cfg.alCambiar?.(); });
    alSelect();
  }
  $('.agregar', caja).addEventListener('click', () => agregar());
  (cfg.valores?.length ? cfg.valores : [{}]).forEach(agregar);
  return {
    leer: () => $$('tr', cuerpo).filter(tr => $('select', tr).value || $('.q', tr).value).map(tr => {
      const o = { articulo_id: Number($('select', tr).value) || null, cantidad: aNum($('.q', tr).value) };
      if (cfg.editaPrecio) o.precio = aNum($('.p', tr).value);
      return o;
    }),
    neto: () => $$('tr', cuerpo).reduce((s, tr) => {
      const a = por($('select', tr).value);
      return s + (aNum($('.q', tr).value) || 0) * (cfg.editaPrecio ? aNum($('.p', tr).value) || 0 : a?.precio || 0);
    }, 0),
  };
}

/* ---------- gráficos ---------- */
function barras(filas, et, val, fmt = fPeso) {
  if (!filas.length) return '<p class="vacio">Sin datos en el período.</p>';
  const max = Math.max(...filas.map(val), 1);
  return `<div class="barras">${filas.map(r => `<div class="barra-fila" data-tip="${esc(et(r))}: ${esc(fmt(val(r)))}">
    <span>${esc(et(r))}</span><span class="barra-pista"><i style="width:${(val(r) / max * 100).toFixed(1)}%"></i></span><b>${esc(fmt(val(r)))}</b></div>`).join('')}</div>`;
}
function columnas(titulo, serie, k) {
  const max = Math.max(...serie.map(s => s[k]), 1);
  const mes = m => new Date(m + '-15').toLocaleDateString('es-CL', { month: 'short' }).replace('.', '');
  const ult = serie[serie.length - 1]?.[k] || 0;
  return `<div class="tarjeta"><h2>${esc(titulo)}</h2><div class="mini-tot">${fPeso(ult)}<small>mes en curso</small></div>
    <div class="columnas" role="img" aria-label="${esc(titulo)} por mes">${serie.map(s => `<div class="columna" data-tip="${esc(mes(s.mes))} ${s.mes.slice(0, 4)}: ${fPeso(s[k])}"><i style="height:${(s[k] / max * 100).toFixed(1)}%"></i></div>`).join('')}</div>
    <div class="columnas-et">${serie.map(s => `<span>${esc(mes(s.mes))}</span>`).join('')}</div></div>`;
}
function linea(serie) {
  if (!serie?.length) return '<p class="vacio">Sin compras en el período.</p>';
  const W = 760, H = 240, L = 66, R = 14, T = 12, B = 26;
  const ps = serie.map(s => s.precio);
  let lo = Math.min(...ps), hi = Math.max(...ps);
  const m = (hi - lo || hi || 1) * .15; lo = Math.max(lo - m, 0); hi += m;
  const x = i => L + (serie.length === 1 ? (W - L - R) / 2 : i * (W - L - R) / (serie.length - 1));
  const y = v => T + (hi - v) / (hi - lo) * (H - T - B);
  const marcas = [0, 1, 2, 3].map(i => lo + (hi - lo) * i / 3);
  const salto = Math.max(1, Math.ceil(serie.length / 6));
  return `<svg class="linea-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Evolución del precio">
    ${marcas.map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#e7e8e9"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${fPrecio(Math.round(v * 100) / 100)}</text>`).join('')}
    <polyline fill="none" stroke="#8e6f3e" stroke-width="2" stroke-linejoin="round" points="${serie.map((s, i) => `${x(i)},${y(s.precio)}`).join(' ')}"/>
    ${serie.map((s, i) => `<g data-tip="${fFecha(s.fecha)}\n${fPrecio(s.precio)}\n${esc(s.proveedor)}"><circle cx="${x(i)}" cy="${y(s.precio)}" r="12" fill="transparent"/><circle cx="${x(i)}" cy="${y(s.precio)}" r="4" fill="#8e6f3e" stroke="#fff" stroke-width="2"/></g>`).join('')}
    ${serie.map((s, i) => i % salto === 0 ? `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${fFecha(s.fecha).slice(0, 5)}</text>` : '').join('')}
  </svg>`;
}

/* ---------- acceso ---------- */
function pantallaAcceso() {
  const instalar = S.estado.requiere_instalacion;
  app.innerHTML = `<div class="acceso"><div class="acceso-caja"><img src="${esc(logo())}" alt="Logo de Nata & Schlott"><h1>Nata &amp; Schlott</h1>
    <p>Sistema de producción y logística</p><form class="tarjeta" novalidate>
    ${instalar ? `<h2 style="font-size:15px;margin-bottom:4px">Primer inicio</h2><p class="tenue" style="margin:0 0 12px">Crea la cuenta del administrador.</p>
      ${S.estado.requiere_clave ? '<label class="campo"><span>Clave de instalación</span><input name="clave" type="password" autocomplete="off"><small>Está en la configuración del servicio en la nube.</small></label>' : ''}
      <label class="campo"><span>Tu nombre</span><input name="nombre" autocomplete="name"></label>` : ''}
    <label class="campo"><span>Usuario</span><input name="username" autocomplete="username"></label>
    <label class="campo"><span>Contraseña</span><input name="password" type="password" autocomplete="${instalar ? 'new-password' : 'current-password'}">${instalar ? '<small>Mínimo 8 caracteres.</small>' : ''}</label>
    ${instalar ? `<label class="campo check"><input type="checkbox" name="demo" ${S.estado.requiere_clave ? '' : 'checked'}><span>Cargar datos de ejemplo ficticios para conocer el sistema</span></label>` : ''}
    <button class="btn primario">${instalar ? 'Crear e ingresar' : 'Ingresar'}</button><div class="error" hidden></div></form></div></div>`;
  $('form', app).addEventListener('submit', async e => {
    e.preventDefault();
    const f = e.target, err = $('.error', f), b = $('button', f);
    err.hidden = true; b.disabled = true;
    if (instalar) b.textContent = 'Preparando…';
    try {
      await api('POST', instalar ? '/instalar' : '/login', {
        username: f.username.value, password: f.password.value,
        ...(instalar ? { nombre: f.nombre.value, demo: f.demo.checked, clave: f.clave?.value } : {}),
      });
      await iniciar();
    } catch (x) { err.textContent = x.message; err.hidden = false; b.disabled = false; if (instalar) b.textContent = 'Crear e ingresar'; }
  });
}

function marco() {
  const nav = NAV.map(([g, items]) => {
    const vis = items.filter(([m, , alt]) => (alt || [m]).some(x => can(x)));
    return vis.length ? `${g ? `<h4>${esc(g)}</h4>` : ''}${vis.map(([m, t]) => `<a href="#/${m}" data-m="${m}">${esc(t)}</a>`).join('')}` : '';
  }).join('');
  const u = S.usuario;
  app.innerHTML = `<div class="menu-movil"><button type="button" id="abrir-menu" aria-label="Abrir menú">☰</button><strong>Nata &amp; Schlott</strong></div>
  <div class="app"><aside class="lateral" id="lateral"><div class="marca"><img src="${esc(logo())}" alt="Logo"><div><strong>Nata &amp; Schlott</strong>
    <small>Sistema de producción y logística</small></div></div><nav class="nav" aria-label="Módulos">${nav}</nav>
    <div class="cuenta">${esc(u.nombre)}<small>${esc(u.perfil)}${u.tienda ? ' · ' + esc(u.tienda) : ''}</small>
    <div class="enlaces"><button type="button" id="mi-clave">Cambiar contraseña</button><button type="button" id="salir">Salir</button></div></div></aside>
  <main class="principal" id="vista"></main></div>`;
  $('#abrir-menu').addEventListener('click', () => $('#lateral').classList.toggle('abierto'));
  $('#salir').addEventListener('click', async () => { await api('POST', '/logout', {}); S.usuario = null; iniciar(); });
  $('#mi-clave').addEventListener('click', () => formulario('Cambiar contraseña', [
    { k: 'actual', t: 'Contraseña actual', tipo: 'password', todo: 1, auto: 'current-password' },
    { k: 'nueva', t: 'Nueva contraseña', tipo: 'password', todo: 1, auto: 'new-password', ayuda: 'Mínimo 8 caracteres.' },
  ], {}, async d => { await api('POST', '/cuenta/password', d); aviso('Contraseña actualizada.'); }));
}

const cabecera = (t, sub, botones = '') => `<div class="cabecera"><div><h1>${esc(t)}</h1>${sub ? `<p>${esc(sub)}</p>` : ''}</div><div class="acciones">${botones}</div></div>`;
function pestanas(lista, activa, al) {
  const d = document.createElement('div');
  d.className = 'pestanas'; d.setAttribute('role', 'tablist');
  d.innerHTML = lista.map(([k, t]) => `<button type="button" role="tab" aria-selected="${k === activa}" class="${k === activa ? 'activo' : ''}" data-k="${k}">${esc(t)}</button>`).join('');
  d.addEventListener('click', e => { const b = e.target.closest('[data-k]'); if (b) al(b.dataset.k); });
  return d;
}
const cargarCat = async () => { S.cat = await api('GET', '/catalogos'); };
const bodegasOp = (incluirCentral = true) => [...(incluirCentral && !S.usuario.tienda_id ? [{ id: 0, nombre: 'Bodega central' }] : []), ...S.cat.tiendas.filter(t => t.activo)];

/* ---------- Panel ---------- */
const Vistas = {};
Vistas.panel = async v => {
  if (S.usuario.tienda_id) { v.innerHTML = cabecera('Panel de inicio', S.usuario.tienda) + '<div class="tarjeta">Usa el menú para ver la bodega y los despachos de tu tienda.</div>'; return; }
  const d = await api('GET', '/reportes/panel'), k = d.kpis;
  const kpi = (t, val, sub = '', cl = '') => `<div class="kpi ${cl}"><span>${esc(t)}</span><strong>${val}</strong><small>${esc(sub)}</small></div>`;
  v.innerHTML = cabecera('Panel de inicio', `Últimos 30 días: ${fFecha(d.desde)} al ${fFecha(d.hasta)}`) + `<div class="kpis">
    ${kpi('Inventario en bodega central', fPeso(k.valor_central), 'valorizado a costo')}
    ${kpi('Inventario en tiendas', fPeso(k.valor_tiendas), 'valorizado a costo')}
    ${kpi('Compras netas', fPeso(k.compras), 'sin IVA')}
    ${kpi('Costo de producción', fPeso(k.produccion_costo), `${fNum(k.lotes)} lotes`)}
    ${kpi('Despachado a tiendas', fPeso(k.despachos), `${fNum(k.guias)} guías`)}
    ${kpi('Mermas', fPeso(k.mermas), `${fPct(k.merma_pct)} de las compras`)}
    ${kpi('Bajo stock mínimo', fNum(k.alertas), 'artículos en bodega central', k.alertas ? 'alerta' : '')}</div>
    <div class="grilla">${columnas('Compras netas', d.serie, 'compras')}${columnas('Costo de producción', d.serie, 'produccion')}${columnas('Despachos a tiendas', d.serie, 'despachos')}${columnas('Mermas', d.serie, 'mermas')}</div>
    <div class="grilla"><div class="tarjeta"><h2>Productos más fabricados</h2>${barras(d.top_producidos, r => r.nombre, r => r.cantidad, fCant)}</div>
    <div class="tarjeta"><h2>Mermas por motivo</h2>${barras(d.mermas_motivo, r => r.nombre, r => r.valor)}</div>
    <div class="tarjeta"><h2>Despachos por tienda</h2>${barras(d.despachos_tienda, r => r.nombre, r => r.valor)}</div></div>
    <div class="grilla"><div class="tarjeta"><h2>Reponer pronto</h2><div id="t-alertas"></div></div><div class="tarjeta"><h2>Mayores alzas de precio</h2><div id="t-alzas"></div></div></div>`;
  tabla($('#t-alertas', v), { buscar: false, filas: d.alertas, vacio: 'Todo está sobre el stock mínimo.', cols: [
    { t: 'Artículo', v: r => r.nombre }, { t: 'Stock', n: 1, v: r => r.stock, h: r => `${fCant(r.stock)} ${esc(r.unidad)}` }, { t: 'Mínimo', n: 1, v: r => r.stock_minimo, h: r => fMin(r.stock_minimo) }] });
  tabla($('#t-alzas', v), { buscar: false, filas: d.alzas, vacio: 'Sin alzas en el período.', cols: [
    { t: 'Insumo', v: r => r.nombre }, { t: 'Inicial', n: 1, v: r => r.inicial, h: r => fPrecio(r.inicial) }, { t: 'Último', n: 1, v: r => r.ultimo, h: r => fPrecio(r.ultimo) }, { t: 'Variación', n: 1, v: r => r.variacion, h: r => `<span class="neg">+${fPct(r.variacion)}</span>` }] });
};

/* ---------- Compras ---------- */
let tabCompras = null;
Vistas.compras = async v => {
  const tabs = [...(can('compras') ? [['compras', 'Compras']] : []), ...(can('proveedores') ? [['proveedores', 'Proveedores'], ['iva', 'Valor IVA']] : [])];
  const t = tabs.some(x => x[0] === tabCompras) ? tabCompras : tabs[0][0];
  v.innerHTML = cabecera('Compras', 'Compras de insumos a proveedores', t === 'compras' && can('compras', 2) ? '<button class="btn primario" id="nueva">Registrar compra</button>' : t === 'proveedores' && can('proveedores', 2) ? '<button class="btn primario" id="nuevo-p">Nuevo proveedor</button>' : '');
  v.append(pestanas(tabs, t, k => { tabCompras = k; render(); }));
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  if (t === 'compras') {
    const filas = await api('GET', '/compras');
    tabla(c, { filas, csv: 'compras', vacio: 'Aún no hay compras.', acciones: {
      ver: async r => verCompra(r.id),
      anular: r => confirmar('Anular compra', `Se revertirá el stock de la compra #${r.id}. Solo es posible si el stock aún está disponible.`, async () => { await api('POST', `/compras/${r.id}/anular`, {}); aviso('Compra anulada.'); render(); }, 'Anular compra'),
    }, cols: [
      { t: 'N°', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Proveedor', v: r => r.proveedor }, { t: 'RUT', v: r => r.rut }, { t: 'Documento', v: r => r.documento },
      { t: 'Neto', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }, { t: 'IVA', n: 1, v: r => r.iva, h: r => fPeso(r.iva) }, { t: 'Total', n: 1, v: r => r.total, h: r => fPeso(r.total) },
      { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Vigente', 'bien') },
      { t: '', h: r => `<div class="acciones">${accion('ver', 'Ver')}${r.estado !== 'ANULADO' && can('compras', 2) ? accion('anular', 'Anular', 'peligro') : ''}</div>` }] });
    $('#nueva', v)?.addEventListener('click', nuevaCompra);
  } else if (t === 'proveedores') {
    const filas = await api('GET', '/proveedores');
    const form = r => formulario(r ? 'Editar proveedor' : 'Nuevo proveedor', [
      { k: 'rut', t: 'RUT', ayuda: 'Ejemplo: 76.123.456-7. Se valida el dígito verificador.' }, { k: 'nombre', t: 'Nombre' },
      ...(r ? [{ k: 'activo', t: 'Proveedor activo', tipo: 'check', todo: 1 }] : [])], r, async d => {
        await api(r ? 'PUT' : 'POST', '/proveedores' + (r ? '/' + r.id : ''), d); aviso('Proveedor guardado.'); render();
      });
    $('#nuevo-p', v)?.addEventListener('click', () => form());
    tabla(c, { filas, csv: 'proveedores', vacio: 'Aún no hay proveedores.', acciones: { editar: form }, cols: [
      { t: 'RUT', v: r => r.rut }, { t: 'Nombre', v: r => r.nombre }, { t: 'Estado', v: r => r.activo ? 'Activo' : 'Inactivo', h: r => r.activo ? etq('Activo', 'bien') : etq('Inactivo') },
      { t: '', h: () => can('proveedores', 2) ? `<div class="acciones">${accion('editar', 'Editar')}</div>` : '' }] });
  } else {
    c.innerHTML = `<h2>Valor IVA</h2><p class="nota">Se aplica a las nuevas compras y guías. Los documentos ya emitidos conservan el IVA con que se registraron.</p>
      <form id="f-iva" class="filtros"><label>IVA (%)<input class="num" name="iva" data-dec="2" value="${fNum(S.cat.iva, 0, 2)}" ${can('proveedores', 2) ? '' : 'disabled'}></label>
      ${can('proveedores', 2) ? '<button class="btn primario">Guardar</button>' : ''}</form>`;
    $('#f-iva', c).addEventListener('submit', async e => {
      e.preventDefault();
      try { await api('PUT', '/config/iva', { iva: aNum(e.target.iva.value) }); aviso('IVA actualizado.'); } catch (x) { aviso(x.message, 1); }
    });
  }
};
function nuevaCompra() {
  const activos = S.cat.proveedores.filter(p => p.activo);
  const m = modal('Registrar compra', `<form novalidate><div class="campos"><label class="campo"><span>Proveedor</span><select name="proveedor_id">${opciones(activos, '', 'Selecciona…')}</select></label>
    <label class="campo"><span>Fecha</span><input type="date" name="fecha" value="${hoy()}"></label><label class="campo"><span>N° de documento</span><input name="documento"></label></div>
    <h3 style="font-size:14px;margin:14px 0 6px">Detalle</h3><div id="lin"></div><div class="totales" id="tot"></div><div class="error" hidden></div>
    <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Registrar compra</button></div></form>`, true);
  $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
  const totales = () => {
    const n = ed ? ed.neto() : 0, i = n * S.cat.iva / 100;
    $('#tot', m.el).innerHTML = `<div><span>Neto</span><span>${fPeso(n)}</span></div><div><span>IVA ${fNum(S.cat.iva, 0, 2)}%</span><span>${fPeso(i)}</span></div><div class="total"><span>Total</span><span>${fPeso(n + i)}</span></div>`;
  };
  let ed = null;
  ed = editorLineas($('#lin', m.el), { articulos: S.cat.articulos.filter(a => a.tipo === 'INSUMO'), precio: 'Precio neto', editaPrecio: true, alCambiar: totales });
  totales();
  conEnvio($('form', m.el), m, async () => {
    const f = $('form', m.el);
    await api('POST', '/compras', { proveedor_id: f.proveedor_id.value, fecha: f.fecha.value, documento: f.documento.value, items: ed.leer() });
    aviso('Compra registrada: el stock aumentó.'); render();
  });
}
async function verCompra(id) {
  const c = await api('GET', `/compras/${id}`);
  const m = modal(`Compra #${c.id}`, `<div class="guia-datos"><div><b>Proveedor:</b> ${esc(c.proveedor)}</div><div><b>RUT:</b> ${esc(c.rut)}</div><div><b>Fecha:</b> ${fFecha(c.fecha)}</div><div><b>Documento:</b> ${esc(c.documento) || '—'}</div><div><b>Registrada por:</b> ${esc(c.usuario)}</div></div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Insumo</th><th class="n">Cantidad</th><th class="n">Precio neto</th><th class="n">Subtotal</th></tr></thead><tbody>${c.items.map(i => `<tr><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)} ${esc(i.unidad)}</td><td class="n">${fPrecio(i.precio)}</td><td class="n">${fPeso(i.cantidad * i.precio)}</td></tr>`).join('')}</tbody></table></div>
    <div class="totales"><div><span>Neto</span><span>${fPeso(c.neto)}</span></div><div><span>IVA ${fNum(c.iva_pct, 0, 2)}%</span><span>${fPeso(c.iva)}</span></div><div class="total"><span>Total</span><span>${fPeso(c.total)}</span></div></div>`, true);
  return m;
}

/* ---------- Tiendas ---------- */
Vistas.tiendas = async v => {
  const filas = await api('GET', '/tiendas');
  const form = r => formulario(r ? 'Editar tienda' : 'Nueva tienda', [
    { k: 'nombre', t: 'Nombre del local', todo: 1 }, { k: 'direccion', t: 'Dirección', todo: 1 }, { k: 'comuna', t: 'Comuna' },
    { k: 'region', t: 'Región', tipo: 'select', vacio: 'Selecciona…', op: REGIONES.map(x => ({ id: x, nombre: x })) },
    ...(r ? [{ k: 'activo', t: 'Tienda activa', tipo: 'check', todo: 1 }] : [])], r, async d => {
      await api(r ? 'PUT' : 'POST', '/tiendas' + (r ? '/' + r.id : ''), d); aviso('Tienda guardada.'); render();
    });
  v.innerHTML = cabecera('Tiendas', 'Locales que reciben despachos', can('tiendas', 2) ? '<button class="btn primario" id="n">Nueva tienda</button>' : '');
  $('#n', v)?.addEventListener('click', () => form());
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  tabla(c, { filas, csv: 'tiendas', vacio: 'Aún no hay tiendas.', acciones: { editar: form }, cols: [
    { t: 'Nombre del local', v: r => r.nombre }, { t: 'Dirección', v: r => r.direccion }, { t: 'Comuna', v: r => r.comuna }, { t: 'Región', v: r => r.region },
    { t: 'Estado', v: r => r.activo ? 'Activa' : 'Inactiva', h: r => r.activo ? etq('Activa', 'bien') : etq('Inactiva') },
    { t: '', h: () => can('tiendas', 2) ? `<div class="acciones">${accion('editar', 'Editar')}</div>` : '' }] });
};

/* ---------- Artículos ---------- */
let tabArt = 'PRODUCTO';
Vistas.articulos = async v => {
  const tabs = [['PRODUCTO', 'Productos'], ['SUBPRODUCTO', 'Subproductos'], ['INSUMO', 'Insumos'], ['DESECHABLE', 'Desechables y aseo'], ['categorias', 'Categorías'], ['unidades', 'Unidades de medida']];
  const edita = can('articulos', 2), esArt = !['categorias', 'unidades'].includes(tabArt);
  const notas = { PRODUCTO: 'Artículos terminados. El precio es el de venta, neto.', SUBPRODUCTO: 'Preparaciones que forman parte de un producto. Se fabrican con receta.', INSUMO: 'Ingredientes comprados a proveedores que forman parte de una receta. El precio se actualiza con la última compra.', DESECHABLE: 'Comprados a proveedores, no forman parte de una receta y se despachan a tiendas: vasos, bombillas, sachets, limpiavidrios.' };
  v.innerHTML = cabecera('Productos, subproductos e insumos', notas[tabArt] || 'Tablas maestras', edita ? `<button class="btn primario" id="n">${esArt ? 'Nuevo artículo' : tabArt === 'categorias' ? 'Nueva categoría' : 'Nueva unidad'}</button>` : '');
  v.append(pestanas(tabs, tabArt, k => { tabArt = k; render(); }));
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  if (!esArt) {
    const campos = tabArt === 'categorias' ? [{ k: 'nombre', t: 'Nombre', todo: 1 }] : [{ k: 'nombre', t: 'Nombre' }, { k: 'abreviatura', t: 'Abreviatura', ayuda: 'Ejemplo: kg' }];
    const titulo = tabArt === 'categorias' ? 'categoría' : 'unidad';
    const form = r => formulario((r ? 'Editar ' : 'Nueva ') + titulo, campos, r, async d => { await api(r ? 'PUT' : 'POST', `/${tabArt}` + (r ? '/' + r.id : ''), d); aviso('Guardado.'); render(); });
    $('#n', v)?.addEventListener('click', () => form());
    tabla(c, { filas: await api('GET', '/' + tabArt), acciones: { editar: form,
      borrar: r => confirmar('Eliminar', `¿Eliminar "${r.nombre}"? No se podrá si algún artículo la usa.`, async () => { await api('DELETE', `/${tabArt}/${r.id}`); aviso('Eliminado.'); render(); }, 'Eliminar') },
    cols: [...campos.map(f => ({ t: f.t, v: r => r[f.k] })), { t: '', h: () => edita ? `<div class="acciones">${accion('editar', 'Editar')}${accion('borrar', 'Eliminar', 'peligro')}</div>` : '' }] });
    return;
  }
  const todos = await api('GET', '/articulos');
  const filas = todos.filter(a => tabArt === 'DESECHABLE' ? a.desechable : tabArt === 'INSUMO' ? a.tipo === 'INSUMO' && !a.desechable : a.tipo === tabArt);
  const form = r => {
    const inicial = r || { tipo: tabArt === 'DESECHABLE' ? 'INSUMO' : tabArt, desechable: tabArt === 'DESECHABLE' };
    formulario(r ? 'Editar artículo' : 'Nuevo artículo', [
      { k: 'codigo', t: 'Código' }, { k: 'nombre', t: 'Nombre' },
      { k: 'categoria_id', t: 'Clasificación o categoría', tipo: 'select', op: S.cat.categorias, vacio: 'Selecciona…' },
      { k: 'unidad_id', t: 'Unidad de medida', tipo: 'select', op: S.cat.unidades, vacio: 'Selecciona…' },
      { k: 'stock_minimo', t: 'Stock mínimo', tipo: 'num', dec: 5, min: 5, ayuda: 'Se muestra con miles y 5 decimales.' },
      { k: 'precio', t: inicial.tipo === 'INSUMO' ? 'Precio de compra neto' : inicial.tipo === 'PRODUCTO' ? 'Precio de venta neto' : 'Precio', tipo: 'num', dec: 2, ayuda: 'Con separador de miles.' },
      ...(r ? [{ k: 'activo', t: 'Artículo activo', tipo: 'check', todo: 1 }] : [])], inicial,
    async d => {
      await api(r ? 'PUT' : 'POST', '/articulos' + (r ? '/' + r.id : ''), { ...d, tipo: inicial.tipo, desechable: inicial.desechable });
      aviso('Artículo guardado.'); render();
    });
  };
  $('#n', v)?.addEventListener('click', () => form());
  tabla(c, { filas, csv: 'articulos', vacio: 'Sin artículos en esta clasificación.', acciones: { editar: form }, cols: [
    { t: 'Código', v: r => r.codigo }, { t: 'Nombre', v: r => r.nombre }, { t: 'Categoría', v: r => r.categoria }, { t: 'Unidad', v: r => r.unidad },
    { t: 'Stock mínimo', n: 1, v: r => r.stock_minimo, h: r => fMin(r.stock_minimo) },
    { t: 'Stock central', n: 1, v: r => r.stock, h: r => `${fCant(r.stock)}${r.stock < r.stock_minimo ? ' ' + etq('Bajo mínimo', 'mal') : ''}` },
    { t: 'Precio', n: 1, v: r => r.precio, h: r => fPrecio(r.precio) },
    { t: 'Estado', v: r => r.activo ? 'Activo' : 'Inactivo', h: r => r.activo ? etq('Activo', 'bien') : etq('Inactivo') },
    { t: '', h: () => edita ? `<div class="acciones">${accion('editar', 'Editar')}</div>` : '' }] });
};

/* ---------- Toma de inventario ---------- */
Vistas.inventario = async v => {
  const filas = await api('GET', '/inventarios');
  v.innerHTML = cabecera('Toma de inventario', 'Al cerrar, cada diferencia queda registrada en el historial y ajusta el stock.', can('inventario', 2) ? '<button class="btn primario" id="n">Nueva toma</button>' : '');
  $('#n', v)?.addEventListener('click', () => formulario('Nueva toma de inventario', [
    { k: 'bodega_id', t: 'Bodega', tipo: 'select', op: bodegasOp(), todo: 1 }, { k: 'obs', t: 'Observación', tipo: 'area', todo: 1 }], {}, async d => {
    const r = await api('POST', '/inventarios', d); render(); abrirInventario(r.id);
  }, 'Crear toma'));
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  tabla(c, { filas, vacio: 'Aún no hay tomas de inventario.', acciones: { abrir: r => abrirInventario(r.id),
    borrar: r => confirmar('Eliminar toma', `¿Eliminar la toma #${r.id} sin aplicar ajustes?`, async () => { await api('DELETE', `/inventarios/${r.id}`); render(); }, 'Eliminar') }, cols: [
    { t: 'N°', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Bodega', v: r => r.bodega }, { t: 'Responsable', v: r => r.usuario },
    { t: 'Contados', n: 1, v: r => r.contadas, h: r => `${fNum(r.contadas)} de ${fNum(r.lineas)}` }, { t: 'Con diferencia', n: 1, v: r => r.con_diferencia, h: r => fNum(r.con_diferencia) },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ABIERTO' ? etq('Abierta', 'alerta') : etq('Cerrada', 'bien') },
    { t: '', h: r => `<div class="acciones">${accion('abrir', r.estado === 'ABIERTO' && can('inventario', 2) ? 'Contar' : 'Ver')}${r.estado === 'ABIERTO' && can('inventario', 2) ? accion('borrar', 'Eliminar', 'peligro') : ''}</div>` }] });
};
async function abrirInventario(id) {
  const inv = await api('GET', `/inventarios/${id}`);
  const abierto = inv.estado === 'ABIERTO' && can('inventario', 2);
  const filas = inv.items.map(i => {
    const sis = abierto ? i.stock_actual : i.stock_sistema;
    return `<tr data-a="${i.articulo_id}" data-s="${sis}"><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(sis)} ${esc(i.unidad)}</td>
    <td class="n">${abierto ? inputNum('c', i.conteo, 5).replace('<input', `<input aria-label="Conteo de ${esc(i.nombre)}"`) : (i.conteo === null ? '—' : fCant(i.conteo))}</td><td class="n dif">${i.diferencia ? fCant(i.diferencia) : ''}</td></tr>`;
  }).join('');
  const m = modal(`Toma #${inv.id} · ${inv.bodega}`, `<div class="tabla-marco"><table><thead><tr><th>Código</th><th>Artículo</th><th class="n">Stock sistema</th><th class="n">Conteo físico</th><th class="n">Diferencia</th></tr></thead><tbody>${filas}</tbody></table></div>
    <p class="tenue">${abierto ? 'Los artículos sin conteo no se ajustan.' : `Cerrada el ${fFecha(inv.cerrado || '') || '—'}.`}</p><div class="error" hidden></div>
    ${abierto ? '<form><div class="modal-pie"><button type="button" class="btn g">Guardar avance</button><button class="btn primario">Cerrar y ajustar stock</button></div></form>' : ''}`, true);
  if (!abierto) return;
  const pinta = tr => {
    const n = aNum($('.c', tr).value), d = $('.dif', tr);
    if (n === null || Number.isNaN(n)) { d.textContent = ''; return; }
    const x = n - Number(tr.dataset.s);
    d.textContent = (x > 0 ? '+' : '') + fCant(x);
    d.className = 'n dif ' + (x > 0 ? 'pos' : x < 0 ? 'neg' : '');
  };
  $$('tbody tr', m.el).forEach(tr => { pinta(tr); tr.addEventListener('input', () => pinta(tr)); });
  const leer = () => $$('tbody tr', m.el).map(tr => {
    const n = aNum($('.c', tr).value);
    if (Number.isNaN(n)) throw new Error('Hay un conteo que no es un número válido.');
    return { articulo_id: Number(tr.dataset.a), conteo: n };
  });
  $('.g', m.el).addEventListener('click', async () => {
    try { await api('PUT', `/inventarios/${id}`, { items: leer() }); aviso('Avance guardado.'); render(); }
    catch (x) { const e = $('.error', m.el); e.textContent = x.message; e.hidden = false; }
  });
  conEnvio($('form', m.el), m, async () => { await api('POST', `/inventarios/${id}/cerrar`, { items: leer() }); aviso('Toma cerrada y reflejada en el historial.'); render(); });
}

/* ---------- Historial ---------- */
const filtrosHist = { desde: haceDias(30), hasta: hoy(), clase: '', sentido: '', tipo: '', bodega: '', proveedor_id: '', tienda_destino_id: '' };
Vistas.historial = async v => {
  const f = filtrosHist;
  const sel = (k, t, op) => `<label>${t}<select name="${k}">${opciones(op, f[k], 'Todos')}</select></label>`;
  v.innerHTML = cabecera('Historial de entradas y salidas', 'Productos, subproductos e insumos: proveedor, tienda de destino y motivo de cada movimiento.') + `<div class="tarjeta"><form class="filtros" id="fh">
    <label>Desde<input type="date" name="desde" value="${f.desde}"></label><label>Hasta<input type="date" name="hasta" value="${f.hasta}"></label>
    ${sel('clase', 'Clasificación', [{ id: 'PRODUCTO', nombre: 'Productos' }, { id: 'SUBPRODUCTO', nombre: 'Subproductos' }, { id: 'INSUMO', nombre: 'Insumos' }, { id: 'DESECHABLE', nombre: 'Desechables y aseo' }])}
    ${sel('sentido', 'Sentido', [{ id: 'entrada', nombre: 'Entradas' }, { id: 'salida', nombre: 'Salidas' }])}
    ${sel('tipo', 'Movimiento', Object.entries(TIPOS_MOV).map(([id, x]) => ({ id, nombre: x[0] })))}
    ${sel('bodega', 'Bodega', bodegasOp())}
    ${S.usuario.tienda_id ? '' : sel('proveedor_id', 'Proveedor', S.cat.proveedores) + sel('tienda_destino_id', 'Tienda destino', S.cat.tiendas)}
    <button class="btn primario">Filtrar</button></form><div id="th"></div></div>`;
  $('#fh', v).addEventListener('submit', e => { e.preventDefault(); new FormData(e.target).forEach((x, k) => { f[k] = x; }); render(); });
  const filas = await api('GET', '/movimientos' + qs(f));
  tabla($('#th', v), { filas, csv: 'historial', vacio: 'Sin movimientos con estos filtros.', cols: [
    { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Código', v: r => r.codigo }, { t: 'Artículo', v: r => r.nombre },
    { t: 'Clasificación', v: r => claseArticulo({ tipo: r.tipo_articulo, desechable: r.desechable }) },
    { t: 'Movimiento', v: r => TIPOS_MOV[r.tipo]?.[0] || r.tipo, h: r => etq(TIPOS_MOV[r.tipo]?.[0] || r.tipo, TIPOS_MOV[r.tipo]?.[1]) },
    { t: 'Entrada', n: 1, v: r => r.cantidad > 0 ? r.cantidad : '', h: r => r.cantidad > 0 ? `<span class="pos">${fCant(r.cantidad)}</span>` : '' },
    { t: 'Salida', n: 1, v: r => r.cantidad < 0 ? -r.cantidad : '', h: r => r.cantidad < 0 ? `<span class="neg">${fCant(-r.cantidad)}</span>` : '' },
    { t: 'Saldo', n: 1, v: r => r.saldo, h: r => `${fCant(r.saldo)} ${esc(r.unidad)}` }, { t: 'Bodega', v: r => r.bodega },
    { t: 'Proveedor', v: r => r.proveedor || '' }, { t: 'Tienda destino', v: r => r.tienda_destino || '' }, { t: 'Motivo merma', v: r => r.motivo || '' },
    { t: 'Referencia', v: r => r.referencia }, { t: 'Usuario', v: r => r.usuario || '' }] });
};

/* ---------- Mermas ---------- */
let tabMerma = 'registros';
Vistas.mermas = async v => {
  const edita = can('mermas', 2);
  v.innerHTML = cabecera('Mermas', 'Desperdicios y su motivo', edita ? `<button class="btn primario" id="n">${tabMerma === 'registros' ? 'Registrar merma' : 'Nuevo motivo'}</button>` : '');
  v.append(pestanas([['registros', 'Registros'], ['motivos', 'Motivos']], tabMerma, k => { tabMerma = k; render(); }));
  if (tabMerma === 'motivos') {
    const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
    const form = r => formulario(r ? 'Editar motivo' : 'Nuevo motivo', [{ k: 'nombre', t: 'Motivo', todo: 1 }], r, async d => { await api(r ? 'PUT' : 'POST', '/motivos_merma' + (r ? '/' + r.id : ''), d); render(); });
    $('#n', v)?.addEventListener('click', () => form());
    tabla(c, { filas: await api('GET', '/motivos_merma'), acciones: { editar: form,
      borrar: r => confirmar('Eliminar motivo', `¿Eliminar "${r.nombre}"? No se podrá si tiene mermas registradas.`, async () => { await api('DELETE', `/motivos_merma/${r.id}`); render(); }, 'Eliminar') }, cols: [
      { t: 'Motivo', v: r => r.nombre }, { t: '', h: () => edita ? `<div class="acciones">${accion('editar', 'Editar')}${accion('borrar', 'Eliminar', 'peligro')}</div>` : '' }] });
    return;
  }
  const filas = await api('GET', '/mermas');
  const vig = filas.filter(r => r.estado === 'VIGENTE');
  const porM = {}; vig.forEach(r => { porM[r.motivo] = (porM[r.motivo] || 0) + r.cantidad * r.costo_unit; });
  const g = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  g.innerHTML = `<h2>Costo por motivo, último año</h2>${barras(Object.entries(porM).sort((a, b) => b[1] - a[1]), r => r[0], r => r[1])}`;
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  tabla(c, { filas, csv: 'mermas', vacio: 'Aún no hay mermas.', acciones: {
    anular: r => confirmar('Anular merma', `Se devolverán ${fCant(r.cantidad)} ${r.unidad} de ${r.nombre} al stock.`, async () => { await api('POST', `/mermas/${r.id}/anular`, {}); render(); }, 'Anular merma') }, cols: [
    { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Artículo', v: r => r.nombre }, { t: 'Bodega', v: r => r.bodega }, { t: 'Motivo', v: r => r.motivo },
    { t: 'Cantidad', n: 1, v: r => r.cantidad, h: r => `${fCant(r.cantidad)} ${esc(r.unidad)}` }, { t: 'Costo', n: 1, v: r => r.cantidad * r.costo_unit, h: r => fPeso(r.cantidad * r.costo_unit) },
    { t: 'Observación', v: r => r.obs }, { t: 'Usuario', v: r => r.usuario },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Vigente', 'bien') },
    { t: '', h: r => r.estado === 'VIGENTE' && edita ? `<div class="acciones">${accion('anular', 'Anular', 'peligro')}</div>` : '' }] });
  $('#n', v)?.addEventListener('click', () => {
    const bod = bodegasOp();
    const m = modal('Registrar merma', `<form novalidate><div class="campos"><label class="campo"><span>Bodega</span><select name="bodega_id">${opciones(bod, bod[0]?.id)}</select></label>
      <label class="campo"><span>Fecha</span><input type="date" name="fecha" value="${hoy()}"></label><label class="campo todo"><span>Artículo</span><select name="articulo_id"></select></label>
      <label class="campo"><span>Cantidad <span id="u" class="tenue"></span></span>${inputNum('', '', 5).replace('<input', '<input name="cantidad"')}</label>
      <label class="campo"><span>Motivo</span><select name="motivo_id">${opciones(S.cat.motivos, '', 'Selecciona…')}</select></label>
      <label class="campo todo"><span>Observación</span><textarea name="obs" rows="2"></textarea></label></div><div class="error" hidden></div>
      <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Registrar merma</button></div></form>`);
    $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
    const f = $('form', m.el);
    let stock = [];
    const pintaU = () => { const a = stock.find(x => String(x.articulo_id) === f.articulo_id.value); $('#u', m.el).textContent = a ? `(disponible: ${fCant(a.cantidad)} ${a.unidad})` : ''; };
    const carga = async () => {
      stock = await api('GET', '/stock/mermable' + qs({ bodega: f.bodega_id.value }));
      f.articulo_id.innerHTML = '<option value="">Selecciona…</option>' + stock.filter(a => a.cantidad > 0).map(a => `<option value="${a.articulo_id}">${esc(a.codigo)} · ${esc(a.nombre)}</option>`).join('');
      pintaU();
    };
    f.bodega_id.addEventListener('change', carga); f.articulo_id.addEventListener('change', pintaU); carga();
    conEnvio(f, m, async () => {
      await api('POST', '/mermas', { bodega_id: f.bodega_id.value, fecha: f.fecha.value, articulo_id: f.articulo_id.value, cantidad: aNum(f.cantidad.value), motivo_id: f.motivo_id.value, obs: f.obs.value });
      aviso('Merma registrada.'); render();
    });
  });
};

/* ---------- Bodegas ---------- */
let bodegaSel = null;
Vistas.bodegas = async v => {
  const resumen = await api('GET', '/bodegas/resumen');
  const opts = bodegasOp();
  if (!opts.some(o => o.id === bodegaSel)) bodegaSel = opts.find(o => o.id !== 0)?.id ?? opts[0]?.id ?? null;
  v.innerHTML = cabecera('Bodegas', 'Stock de productos terminados y de insumos desechables o de aseo en cada tienda.');
  const kp = v.appendChild(Object.assign(document.createElement('div'), { className: 'kpis' }));
  kp.innerHTML = resumen.map(t => `<div class="kpi"><span>${esc(t.nombre)}</span><strong>${fPeso(t.valor)}</strong><small>${fNum(t.articulos)} artículos con stock · ${esc(t.comuna)}</small></div>`).join('');
  if (bodegaSel === null) { v.insertAdjacentHTML('beforeend', '<div class="tarjeta vacio">Aún no hay tiendas.</div>'); return; }
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  const filas = await api('GET', '/bodegas/stock' + qs({ bodega: bodegaSel }));
  c.innerHTML = `<div class="filtros"><label>Bodega<select id="sb">${opciones(opts, bodegaSel)}</select></label>${bodegaSel && can('bodegas', 2) ? '<button class="btn primario" id="sal">Registrar venta o consumo</button>' : ''}</div><div id="tb"></div>`;
  $('#sb', c).addEventListener('change', e => { bodegaSel = Number(e.target.value); render(); });
  tabla($('#tb', c), { filas, csv: 'bodega', vacio: 'Sin artículos.', cols: [
    { t: 'Código', v: r => r.codigo }, { t: 'Artículo', v: r => r.nombre }, { t: 'Clasificación', v: r => claseArticulo(r) }, { t: 'Categoría', v: r => r.categoria },
    { t: 'Stock', n: 1, v: r => r.cantidad, h: r => `${fCant(r.cantidad)} ${esc(r.unidad)}${r.cantidad <= 0 ? ' ' + etq('Sin stock', 'mal') : bodegaSel === 0 && r.cantidad < r.stock_minimo ? ' ' + etq('Bajo mínimo', 'mal') : ''}` },
    { t: 'Precio', n: 1, v: r => r.precio, h: r => fPrecio(r.precio) }, { t: 'Valor a costo', n: 1, v: r => r.cantidad * r.costo, h: r => fPeso(r.cantidad * r.costo) }] });
  $('#sal', c)?.addEventListener('click', () => formulario('Registrar venta o consumo', [
    { k: 'articulo_id', t: 'Artículo', tipo: 'select', vacio: 'Selecciona…', todo: 1, op: filas.filter(a => a.cantidad > 0).map(a => ({ id: a.articulo_id, nombre: `${a.codigo} · ${a.nombre} (${fCant(a.cantidad)} ${a.unidad})` })) },
    { k: 'cantidad', t: 'Cantidad', tipo: 'num' }, { k: 'motivo', t: 'Motivo', tipo: 'select', op: [{ id: 'VENTA', nombre: 'Venta' }, { id: 'CONSUMO_INTERNO', nombre: 'Consumo interno' }] },
    { k: 'fecha', t: 'Fecha', tipo: 'date', def: hoy() }, { k: 'obs', t: 'Observación' }], {}, async d => {
    await api('POST', '/bodegas/salidas', { ...d, tienda_id: bodegaSel }); aviso('Salida registrada.'); render();
  }, 'Registrar'));
};

/* ---------- Recetas ---------- */
Vistas.recetas = async v => {
  const filas = await api('GET', '/recetas');
  v.innerHTML = cabecera('Recetas', 'Al producir, se descuentan del stock los insumos y subproductos de la receta. Las cantidades van en la unidad de cada ingrediente.');
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  const edita = can('recetas', 2);
  tabla(c, { filas, csv: 'recetas', vacio: 'Primero crea productos o subproductos.', acciones: {
    editar: r => editarReceta(r), ver: r => verReceta(r),
    borrar: r => confirmar('Eliminar receta', `¿Eliminar la receta de ${r.nombre}? Las producciones anteriores se conservan.`, async () => { await api('DELETE', `/recetas/${r.articulo_id}`); render(); }, 'Eliminar') }, cols: [
    { t: 'Código', v: r => r.codigo }, { t: 'Artículo', v: r => r.nombre }, { t: 'Tipo', v: r => claseArticulo(r) },
    { t: 'Rendimiento', n: 1, v: r => r.rendimiento || 0, h: r => r.tiene_receta ? `${fCant(r.rendimiento)} ${esc(r.unidad)}` : '' },
    { t: 'Ingredientes', n: 1, v: r => r.items?.length || 0, h: r => r.tiene_receta ? fNum(r.items.length) : etq('Sin receta', 'alerta') },
    { t: 'Costo unitario', n: 1, v: r => r.costo_unit || 0, h: r => r.tiene_receta ? fPrecio(r.costo_unit) : '' },
    { t: 'Se puede fabricar', n: 1, v: r => r.max_producible || 0, h: r => r.tiene_receta ? `${fCant(Math.floor(r.max_producible))} ${esc(r.unidad)}` : '' },
    { t: '', h: r => `<div class="acciones">${r.tiene_receta ? accion('ver', 'Ver') : ''}${edita ? accion('editar', r.tiene_receta ? 'Editar' : 'Crear') : ''}${edita && r.tiene_receta ? accion('borrar', 'Eliminar', 'peligro') : ''}</div>` }] });
};
function verReceta(r) {
  modal(`Receta: ${r.nombre}`, `<p><b>Rendimiento:</b> ${fCant(r.rendimiento)} ${esc(r.unidad)} · <b>Costo unitario:</b> ${fPrecio(r.costo_unit)}</p>
    <div class="tabla-marco"><table><thead><tr><th>Ingrediente</th><th class="n">Cantidad</th><th class="n">Costo</th><th class="n">Stock central</th></tr></thead><tbody>${r.items.map(i => `<tr><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)} ${esc(i.unidad)}</td><td class="n">${fPeso(i.cantidad * i.costo_unit)}</td><td class="n">${fCant(i.stock)} ${esc(i.unidad)}</td></tr>`).join('')}</tbody></table></div>
    ${r.instrucciones ? `<h3 style="font-size:14px;margin:14px 0 4px">Preparación</h3><p style="white-space:pre-line;margin:0">${esc(r.instrucciones)}</p>` : ''}`, true);
}
function editarReceta(r) {
  const m = modal(`Receta: ${r.nombre}`, `<form novalidate><div class="campos"><label class="campo"><span>Rendimiento (${esc(r.unidad)})</span>${inputNum('', r.rendimiento ?? 1, 5).replace('<input', '<input name="rendimiento"')}<small>Cantidad de ${esc(r.nombre)} que resulta de estas cantidades.</small></label></div>
    <h3 style="font-size:14px;margin:14px 0 6px">Ingredientes</h3><div id="lin"></div>
    <label class="campo" style="margin-top:12px"><span>Preparación</span><textarea name="instrucciones" rows="4">${esc(r.instrucciones || '')}</textarea></label><div class="error" hidden></div>
    <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Guardar receta</button></div></form>`, true);
  $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
  const ed = editorLineas($('#lin', m.el), { articulos: S.cat.articulos.filter(a => a.id !== r.articulo_id && (a.tipo === 'SUBPRODUCTO' || (a.tipo === 'INSUMO' && !a.desechable))), valores: r.items });
  const f = $('form', m.el);
  conEnvio(f, m, async () => {
    await api('PUT', `/recetas/${r.articulo_id}`, { rendimiento: aNum(f.rendimiento.value), instrucciones: f.instrucciones.value, items: ed.leer() });
    aviso('Receta guardada.'); render();
  });
}

/* ---------- Producción ---------- */
Vistas.produccion = async v => {
  const filas = await api('GET', '/produccion');
  v.innerHTML = cabecera('Producción', 'Fabrica productos y subproductos según su receta.', can('produccion', 2) ? '<button class="btn primario" id="n">Registrar producción</button>' : '');
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  tabla(c, { filas, csv: 'produccion', vacio: 'Aún no hay producciones.', acciones: {
    anular: r => confirmar('Anular producción', `Se quitarán ${fCant(r.cantidad)} ${r.unidad} de ${r.nombre} y se devolverán sus ingredientes al stock.`, async () => { await api('POST', `/produccion/${r.id}/anular`, {}); aviso('Producción anulada.'); render(); }, 'Anular producción') }, cols: [
    { t: 'N°', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Código', v: r => r.codigo }, { t: 'Artículo', v: r => r.nombre }, { t: 'Tipo', v: r => claseArticulo(r) },
    { t: 'Cantidad', n: 1, v: r => r.cantidad, h: r => `${fCant(r.cantidad)} ${esc(r.unidad)}` }, { t: 'Costo total', n: 1, v: r => r.costo_total, h: r => fPeso(r.costo_total) },
    { t: 'Costo unitario', n: 1, v: r => r.costo_total / r.cantidad, h: r => fPrecio(r.costo_total / r.cantidad) }, { t: 'Usuario', v: r => r.usuario },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Vigente', 'bien') },
    { t: '', h: r => r.estado === 'VIGENTE' && can('produccion', 2) ? `<div class="acciones">${accion('anular', 'Anular', 'peligro')}</div>` : '' }] });
  $('#n', v)?.addEventListener('click', async () => {
    const recs = (await api('GET', '/produccion/recetas')).filter(r => r.tiene_receta);
    const m = modal('Registrar producción', `<form novalidate><div class="campos"><label class="campo todo"><span>Artículo a fabricar</span><select name="articulo_id"><option value="">Selecciona…</option>${recs.map(r => `<option value="${r.articulo_id}">${esc(r.codigo)} · ${esc(r.nombre)}</option>`).join('')}</select></label>
      <label class="campo"><span>Cantidad <span id="u" class="tenue"></span></span>${inputNum('', '', 5).replace('<input', '<input name="cantidad"')}</label><label class="campo"><span>Fecha</span><input type="date" name="fecha" value="${hoy()}"></label>
      <label class="campo todo"><span>Observación</span><input name="obs"></label></div><div id="req" style="margin-top:12px"></div><div class="error" hidden></div>
      <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Registrar y descontar insumos</button></div></form>`, true);
    $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
    const f = $('form', m.el);
    const pinta = () => {
      const r = recs.find(x => String(x.articulo_id) === f.articulo_id.value), q = aNum(f.cantidad.value) || 0, caja = $('#req', m.el);
      $('#u', m.el).textContent = r ? `(${r.unidad})` : '';
      if (!r) { caja.innerHTML = ''; return; }
      const fac = q / r.rendimiento;
      caja.innerHTML = `<p class="tenue" style="margin:0 0 6px">Con el stock actual se pueden fabricar hasta ${fCant(Math.floor(r.max_producible))} ${esc(r.unidad)}.</p><div class="tabla-marco"><table><thead><tr><th>Ingrediente</th><th class="n">Se descuenta</th><th class="n">Disponible</th><th></th></tr></thead><tbody>${r.items.map(i => {
        const req = i.cantidad * fac;
        return `<tr><td>${esc(i.nombre)}</td><td class="n">${fCant(req)} ${esc(i.unidad)}</td><td class="n">${fCant(i.stock)} ${esc(i.unidad)}</td><td>${req > i.stock ? etq('Falta', 'mal') : q ? etq('Alcanza', 'bien') : ''}</td></tr>`;
      }).join('')}</tbody></table></div>`;
    };
    f.addEventListener('input', pinta); f.articulo_id.addEventListener('change', pinta);
    conEnvio(f, m, async () => {
      await api('POST', '/produccion', { articulo_id: f.articulo_id.value, cantidad: aNum(f.cantidad.value), fecha: f.fecha.value, obs: f.obs.value });
      aviso('Producción registrada: stock actualizado.'); render();
    });
  });
};

/* ---------- Despachos ---------- */
Vistas.despachos = async v => {
  const crea = can('despachos', 2) && !S.usuario.tienda_id;
  const filas = await api('GET', '/despachos');
  v.innerHTML = cabecera('Despachos a tiendas', 'Cada guía descuenta de la bodega central y aumenta el stock de la bodega de la tienda.', crea ? '<button class="btn primario" id="n">Nueva guía</button>' : '');
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  tabla(c, { filas, csv: 'despachos', vacio: 'Aún no hay guías.', acciones: { ver: r => verGuia(r.id),
    anular: r => confirmar('Anular guía', `Se devolverá a la bodega central lo despachado en la guía ${String(r.id).padStart(6, '0')}. Requiere que la tienda aún tenga ese stock.`, async () => { await api('POST', `/despachos/${r.id}/anular`, {}); aviso('Guía anulada.'); render(); }, 'Anular guía') }, cols: [
    { t: 'Guía', v: r => String(r.id).padStart(6, '0') }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Tienda', v: r => r.tienda }, { t: 'Líneas', n: 1, v: r => r.lineas },
    { t: 'Neto', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }, { t: 'Total', n: 1, v: r => r.total, h: r => fPeso(r.total) }, { t: 'Transportista', v: r => r.transportista },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Emitida', 'bien') },
    { t: '', h: r => `<div class="acciones">${accion('ver', 'Ver guía')}${r.estado === 'VIGENTE' && crea ? accion('anular', 'Anular', 'peligro') : ''}</div>` }] });
  $('#n', v)?.addEventListener('click', async () => {
    const central = await api('GET', '/stock/central');
    const stock = Object.fromEntries(central.map(a => [a.articulo_id, a.cantidad]));
    const m = modal('Nueva guía de despacho', `<form novalidate><div class="campos"><label class="campo"><span>Tienda de destino</span><select name="tienda_id">${opciones(S.cat.tiendas.filter(t => t.activo), '', 'Selecciona…')}</select></label>
      <label class="campo"><span>Fecha</span><input type="date" name="fecha" value="${hoy()}"></label><label class="campo"><span>Transportista</span><input name="transportista"></label><label class="campo"><span>Patente</span><input name="patente"></label></div>
      <h3 style="font-size:14px;margin:14px 0 6px">Detalle</h3><div id="lin"></div><div class="totales" id="tot"></div>
      <label class="campo" style="margin-top:8px"><span>Observación</span><input name="obs"></label><div class="error" hidden></div>
      <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Emitir guía</button></div></form>`, true);
    $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
    let ed = null;
    const tot = () => { const n = ed ? ed.neto() : 0, i = n * S.cat.iva / 100; $('#tot', m.el).innerHTML = `<div><span>Neto</span><span>${fPeso(n)}</span></div><div><span>IVA ${fNum(S.cat.iva, 0, 2)}%</span><span>${fPeso(i)}</span></div><div class="total"><span>Total</span><span>${fPeso(n + i)}</span></div>`; };
    ed = editorLineas($('#lin', m.el), { articulos: S.cat.articulos.filter(a => a.tipo === 'PRODUCTO' || a.desechable), stock, precio: 'Precio', alCambiar: tot });
    tot();
    const f = $('form', m.el);
    conEnvio(f, m, async () => {
      const r = await api('POST', '/despachos', { tienda_id: f.tienda_id.value, fecha: f.fecha.value, transportista: f.transportista.value, patente: f.patente.value, obs: f.obs.value, items: ed.leer() });
      aviso('Guía emitida: stock de la tienda actualizado.'); render(); verGuia(r.id);
    });
  });
};
async function verGuia(id) {
  const g = await api('GET', `/despachos/${id}`);
  const num = String(g.id).padStart(6, '0');
  const m = modal(`Guía ${num}`, `<div class="guia-cab"><div class="guia-marca"><img src="${esc(logo())}" alt=""><div><strong>Nata &amp; Schlott</strong><span class="tenue">Sistema de producción y logística</span></div></div>
    <div class="guia-num"><span>Guía de despacho interna</span><strong>N° ${num}</strong>${g.estado === 'ANULADO' ? etq('ANULADA', 'mal') : ''}</div></div>
    <div class="guia-datos"><div><b>Fecha:</b> ${fFecha(g.fecha)}</div><div><b>Origen:</b> Bodega central</div><div><b>Destino:</b> ${esc(g.tienda)}</div><div><b>Dirección:</b> ${esc(g.direccion)}</div><div><b>Comuna:</b> ${esc(g.comuna)}</div><div><b>Región:</b> ${esc(g.region)}</div><div><b>Transportista:</b> ${esc(g.transportista) || '—'}</div><div><b>Patente:</b> ${esc(g.patente) || '—'}</div><div><b>Emitida por:</b> ${esc(g.usuario)}</div></div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Descripción</th><th class="n">Cantidad</th><th>Unidad</th><th class="n">Precio</th><th class="n">Subtotal</th></tr></thead><tbody>${g.items.map(i => `<tr><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)}</td><td>${esc(i.unidad)}</td><td class="n">${fPrecio(i.precio)}</td><td class="n">${fPeso(i.cantidad * i.precio)}</td></tr>`).join('')}</tbody></table></div>
    <div class="totales"><div><span>Neto</span><span>${fPeso(g.neto)}</span></div><div><span>IVA ${fNum(g.iva_pct, 0, 2)}%</span><span>${fPeso(g.iva)}</span></div><div class="total"><span>Total</span><span>${fPeso(g.total)}</span></div></div>
    ${g.obs ? `<p><b>Observación:</b> ${esc(g.obs)}</p>` : ''}<div class="firmas"><div>Entrega</div><div>Recibe conforme</div></div>
    <p class="legal">Documento de control interno. No reemplaza la guía de despacho electrónica exigida por el SII.</p>
    <div class="modal-pie no-imprimir"><button type="button" class="btn primario imprimir">Imprimir</button></div>`, true);
  $('.imprimir', m.el).addEventListener('click', () => print());
}

/* ---------- Reportes ---------- */
let tabRep = 'rendimiento', rango = { desde: haceDias(90), hasta: hoy() }, insumoSel = '';
Vistas.reportes = async v => {
  const tabs = [['rendimiento', 'Rendimiento de producción'], ['precios', 'Precios de insumos'], ['margenes', 'Márgenes'], ['cobertura', 'Cobertura y reposición'], ['compras', 'Compras'], ['despachos', 'Despachos'], ['mermas', 'Mermas']];
  v.innerHTML = cabecera('Reportes de gestión', 'Indicadores para decidir qué producir, comprar y corregir.');
  v.append(pestanas(tabs, tabRep, k => { tabRep = k; render(); }));
  if (tabRep !== 'margenes') {
    const fr = v.appendChild(document.createElement('form'));
    fr.className = 'filtros sobre-gris';
    fr.innerHTML = `<label>Desde<input type="date" name="desde" value="${rango.desde}"></label><label>Hasta<input type="date" name="hasta" value="${rango.hasta}"></label><button class="btn">Aplicar</button>`;
    fr.addEventListener('submit', e => { e.preventDefault(); rango = { desde: e.target.desde.value, hasta: e.target.hasta.value }; render(); });
  }
  const zona = v.appendChild(document.createElement('div'));
  const tarjeta = (h = '') => { const c = zona.appendChild(document.createElement('div')); c.className = 'tarjeta'; c.innerHTML = h; return c; };
  const kpis = l => { const k = zona.appendChild(document.createElement('div')); k.className = 'kpis'; k.innerHTML = l.map(([t, x, s]) => `<div class="kpi"><span>${esc(t)}</span><strong>${x}</strong><small>${esc(s || '')}</small></div>`).join(''); };
  await REP[tabRep](zona, tarjeta, kpis);
};
const REP = {
  async rendimiento(z, tarjeta, kpis) {
    const d = await api('GET', '/reportes/rendimiento' + qs(rango)), f = d.filas;
    const sum = k => f.reduce((s, r) => s + r[k], 0);
    const prod = f.filter(r => r.tipo === 'PRODUCTO');
    const rend = prod.length ? prod.reduce((s, r) => s + r.rendimiento * r.producido, 0) / prod.reduce((s, r) => s + r.producido, 0) : 0;
    kpis([['Lotes fabricados', fNum(sum('lotes'))], ['Costo de producción', fPeso(sum('costo'))], ['Rendimiento de productos', fPct(rend), 'producido que no terminó en merma']]);
    tarjeta(`<h2>Costo de producción por artículo</h2>${barras(f.slice(0, 10), r => r.nombre, r => r.costo)}`);
    tabla(tarjeta(), { filas: f, csv: 'rendimiento', vacio: 'Sin producción en el período.', cols: [
      { t: 'Artículo', v: r => r.nombre }, { t: 'Lotes', n: 1, v: r => r.lotes }, { t: 'Producido', n: 1, v: r => r.producido, h: r => `${fCant(r.producido)} ${esc(r.unidad)}` },
      { t: 'Costo real unit.', n: 1, v: r => r.costo_real, h: r => fPrecio(r.costo_real) }, { t: 'Costo receta hoy', n: 1, v: r => r.costo_receta, h: r => fPrecio(r.costo_receta) },
      { t: 'Desviación', n: 1, v: r => r.desviacion, h: r => fPct(r.desviacion) }, { t: 'Merma', n: 1, v: r => r.merma, h: r => fCant(r.merma) }, { t: 'Rendimiento', n: 1, v: r => r.rendimiento, h: r => fPct(r.rendimiento) }] });
  },
  async precios(z, tarjeta, kpis) {
    const d = await api('GET', '/reportes/precios' + qs({ ...rango, articulo_id: insumoSel })), f = d.filas;
    if (!f.some(r => String(r.id) === String(insumoSel)) && f.length) { insumoSel = f[0].id; return render(); }
    const alzas = f.filter(r => r.variacion > 0).length;
    const prom = f.length ? f.reduce((s, r) => s + r.variacion, 0) / f.length : 0;
    kpis([['Insumos comprados', fNum(f.length)], ['Con alza de precio', fNum(alzas)], ['Variación promedio', fPct(prom), 'simple entre insumos']]);
    const c = tarjeta(`<h2>Evolución del precio</h2><div class="filtros"><label>Insumo<select id="ins">${opciones(f, insumoSel)}</select></label></div>${linea(d.serie)}`);
    $('#ins', c)?.addEventListener('change', e => { insumoSel = e.target.value; render(); });
    tabla(tarjeta(), { filas: f, csv: 'precios_insumos', vacio: 'Sin compras en el período.', cols: [
      { t: 'Código', v: r => r.codigo }, { t: 'Insumo', v: r => r.nombre }, { t: 'Unidad', v: r => r.unidad }, { t: 'Compras', n: 1, v: r => r.compras },
      { t: 'Inicial', n: 1, v: r => r.inicial, h: r => fPrecio(r.inicial) }, { t: 'Último', n: 1, v: r => r.ultimo, h: r => fPrecio(r.ultimo) }, { t: 'Mínimo', n: 1, v: r => r.minimo, h: r => fPrecio(r.minimo) }, { t: 'Máximo', n: 1, v: r => r.maximo, h: r => fPrecio(r.maximo) },
      { t: 'Variación', n: 1, v: r => r.variacion, h: r => `<span class="${r.variacion > 0 ? 'neg' : r.variacion < 0 ? 'pos' : ''}">${r.variacion > 0 ? '+' : ''}${fPct(r.variacion)}</span>` },
      { t: 'Último proveedor', v: r => r.proveedor }, { t: 'Mejor precio con', v: r => r.mejor_proveedor }] });
  },
  async margenes(z, tarjeta) {
    const d = await api('GET', '/reportes/margenes');
    tarjeta(`<h2>Margen sobre el precio de venta</h2><p class="nota">Costo según receta y costos promedio actuales. Considera el precio del producto como neto de IVA.</p>${barras(d.filas, r => r.nombre, r => Math.max(r.margen_pct, 0), fPct)}`);
    tabla(tarjeta(), { filas: d.filas, csv: 'margenes', vacio: 'Sin productos con receta.', cols: [
      { t: 'Código', v: r => r.codigo }, { t: 'Producto', v: r => r.nombre }, { t: 'Precio', n: 1, v: r => r.precio, h: r => fPrecio(r.precio) }, { t: 'Costo receta', n: 1, v: r => r.costo, h: r => fPrecio(r.costo) },
      { t: 'Margen', n: 1, v: r => r.margen, h: r => fPrecio(r.margen) }, { t: 'Margen %', n: 1, v: r => r.margen_pct, h: r => r.margen_pct < 30 ? `${fPct(r.margen_pct)} ${etq('Bajo', 'alerta')}` : fPct(r.margen_pct) }] });
  },
  async cobertura(z, tarjeta, kpis) {
    const d = await api('GET', '/reportes/cobertura' + qs(rango)), f = d.filas;
    kpis([['Con menos de 7 días', fNum(f.filter(r => r.dias !== null && r.dias < 7).length)], ['Bajo mínimo', fNum(f.filter(r => r.stock < r.stock_minimo).length)], ['Reposición sugerida a costo', fPeso(f.reduce((s, r) => s + r.sugerido * r.costo, 0)), 'para cubrir 14 días o el mínimo']]);
    tabla(tarjeta('<h2>Días de cobertura en bodega central</h2><p class="nota">Según las salidas del período. La cantidad sugerida cubre 14 días de consumo o el stock mínimo, lo que sea mayor.</p><div id="c"></div>').querySelector('#c'), { filas: f, csv: 'cobertura', cols: [
      { t: 'Artículo', v: r => r.nombre }, { t: 'Clasificación', v: r => claseArticulo(r) }, { t: 'Stock', n: 1, v: r => r.stock, h: r => `${fCant(r.stock)} ${esc(r.unidad)}` }, { t: 'Mínimo', n: 1, v: r => r.stock_minimo, h: r => fMin(r.stock_minimo) },
      { t: 'Consumo diario', n: 1, v: r => r.consumo_diario, h: r => fNum(r.consumo_diario, 0, 2) }, { t: 'Días de cobertura', n: 1, v: r => r.dias ?? '', h: r => r.dias === null ? '<span class="tenue">Sin consumo</span>' : r.dias < 7 ? `${fNum(r.dias, 0, 1)} ${etq('Crítico', 'mal')}` : fNum(r.dias, 0, 1) },
      { t: 'Reposición sugerida', n: 1, v: r => r.sugerido, h: r => r.sugerido ? `${fNum(r.sugerido, 0, 2)} ${esc(r.unidad)}` : '—' }] });
  },
  async compras(z, tarjeta) {
    const d = await api('GET', '/reportes/compras' + qs(rango));
    tarjeta(`<h2>Compras netas por proveedor</h2>${barras(d.filas, r => r.nombre, r => r.neto)}`);
    tabla(tarjeta(), { filas: d.filas, csv: 'compras_proveedor', vacio: 'Sin compras en el período.', cols: [
      { t: 'Proveedor', v: r => r.nombre }, { t: 'RUT', v: r => r.rut }, { t: 'Documentos', n: 1, v: r => r.documentos }, { t: 'Neto', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }, { t: 'IVA', n: 1, v: r => r.iva, h: r => fPeso(r.iva) }, { t: 'Total', n: 1, v: r => r.total, h: r => fPeso(r.total) }] });
  },
  async despachos(z, tarjeta) {
    const d = await api('GET', '/reportes/despachos' + qs(rango));
    tarjeta(`<h2>Valor despachado por tienda</h2>${barras(d.filas, r => r.nombre, r => r.neto)}`);
    tabla(tarjeta(), { filas: d.filas, csv: 'despachos_tienda', vacio: 'Sin despachos en el período.', cols: [
      { t: 'Tienda', v: r => r.nombre }, { t: 'Comuna', v: r => r.comuna }, { t: 'Guías', n: 1, v: r => r.guias }, { t: 'Cantidad', n: 1, v: r => r.unidades, h: r => fCant(r.unidades) }, { t: 'Neto', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }] });
  },
  async mermas(z, tarjeta) {
    const d = await api('GET', '/reportes/mermas' + qs(rango));
    const g = z.appendChild(document.createElement('div')); g.className = 'grilla';
    g.innerHTML = `<div class="tarjeta"><h2>Por motivo</h2>${barras(d.motivos, r => r.nombre, r => r.valor)}</div><div class="tarjeta"><h2>Por bodega</h2>${barras(d.bodegas, r => r.nombre, r => r.valor)}</div>`;
    tabla(tarjeta(), { filas: d.articulos, csv: 'mermas_articulo', vacio: 'Sin mermas en el período.', cols: [
      { t: 'Código', v: r => r.codigo }, { t: 'Artículo', v: r => r.nombre }, { t: 'Registros', n: 1, v: r => r.registros }, { t: 'Cantidad', n: 1, v: r => r.cantidad, h: r => fCant(r.cantidad) }, { t: 'Costo', n: 1, v: r => r.valor, h: r => fPeso(r.valor) }] });
  },
};

/* ---------- Usuarios y perfiles ---------- */
let tabUsu = 'usuarios';
Vistas.usuarios = async v => {
  const edita = can('usuarios', 2);
  v.innerHTML = cabecera('Usuarios y perfiles', 'El perfil define a qué opciones accede cada usuario.', edita ? `<button class="btn primario" id="n">${tabUsu === 'usuarios' ? 'Nuevo usuario' : 'Nuevo perfil'}</button>` : '');
  v.append(pestanas([['usuarios', 'Usuarios'], ['perfiles', 'Perfiles y accesos']], tabUsu, k => { tabUsu = k; render(); }));
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  const perfiles = await api('GET', '/perfiles');
  if (tabUsu === 'usuarios') {
    const form = r => formulario(r ? 'Editar usuario' : 'Nuevo usuario', [
      { k: 'nombre', t: 'Nombre' }, { k: 'username', t: 'Usuario', auto: 'off' },
      { k: 'password', t: r ? 'Nueva contraseña' : 'Contraseña', tipo: 'password', auto: 'new-password', ayuda: r ? 'Déjala vacía para no cambiarla.' : 'Mínimo 8 caracteres.' },
      { k: 'perfil_id', t: 'Perfil', tipo: 'select', op: perfiles, vacio: 'Selecciona…' },
      { k: 'tienda_id', t: 'Tienda asociada', tipo: 'select', op: S.cat.tiendas, vacio: 'Ninguna (todas las bodegas)', ayuda: 'Si eliges una, solo verá la información de esa tienda.' },
      ...(r ? [{ k: 'activo', t: 'Usuario activo', tipo: 'check', todo: 1 }] : [])], r, async d => {
      await api(r ? 'PUT' : 'POST', '/usuarios' + (r ? '/' + r.id : ''), d); aviso('Usuario guardado.'); render();
    });
    $('#n', v)?.addEventListener('click', () => form());
    tabla(c, { filas: await api('GET', '/usuarios'), acciones: { editar: form }, cols: [
      { t: 'Nombre', v: r => r.nombre }, { t: 'Usuario', v: r => r.username }, { t: 'Perfil', v: r => r.perfil }, { t: 'Tienda', v: r => r.tienda || 'Todas' },
      { t: 'Estado', v: r => r.activo ? 'Activo' : 'Inactivo', h: r => r.activo ? etq('Activo', 'bien') : etq('Inactivo') },
      { t: '', h: () => edita ? `<div class="acciones">${accion('editar', 'Editar')}</div>` : '' }] });
  } else {
    const form = p => {
      const m = modal(p ? `Perfil: ${p.nombre}` : 'Nuevo perfil', `<form novalidate><label class="campo"><span>Nombre del perfil</span><input name="nombre" value="${esc(p?.nombre)}"></label>
        <div class="tabla-marco" style="margin-top:12px"><table class="perm"><thead><tr><th>Módulo</th><th class="c">Sin acceso</th><th class="c">Ver</th><th class="c">Editar</th></tr></thead><tbody>
        ${S.modulos.map(x => `<tr><td>${esc(x.nombre)}</td>${[0, 1, 2].map(n => `<td class="c"><input type="radio" name="p_${x.id}" value="${n}" aria-label="${esc(x.nombre)}: ${['sin acceso', 'ver', 'editar'][n]}" ${(p?.permisos?.[x.id] || 0) === n ? 'checked' : ''}></td>`).join('')}</tr>`).join('')}</tbody></table></div>
        <div class="error" hidden></div><div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Guardar perfil</button></div></form>`, true);
      $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
      const f = $('form', m.el);
      conEnvio(f, m, async () => {
        const permisos = {};
        S.modulos.forEach(x => { const n = Number(f[`p_${x.id}`].value); if (n) permisos[x.id] = n; });
        await api(p ? 'PUT' : 'POST', '/perfiles' + (p ? '/' + p.id : ''), { nombre: f.nombre.value, permisos });
        aviso('Perfil guardado.'); if (p) await refrescarUsuario(); render();
      });
    };
    $('#n', v)?.addEventListener('click', () => form());
    tabla(c, { filas: perfiles, acciones: { editar: form,
      borrar: p => confirmar('Eliminar perfil', `¿Eliminar el perfil ${p.nombre}?`, async () => { await api('DELETE', `/perfiles/${p.id}`); render(); }, 'Eliminar') }, cols: [
      { t: 'Perfil', v: r => r.nombre }, { t: 'Usuarios', n: 1, v: r => r.usuarios }, { t: 'Módulos con acceso', n: 1, v: r => Object.keys(r.permisos).length },
      { t: 'Módulos que puede editar', n: 1, v: r => Object.values(r.permisos).filter(x => x === 2).length },
      { t: '', h: r => edita ? `<div class="acciones">${accion('editar', 'Editar accesos')}${r.usuarios ? '' : accion('borrar', 'Eliminar', 'peligro')}</div>` : '' }] });
  }
};
async function refrescarUsuario() {
  const e = await api('GET', '/estado');
  S.usuario = e.usuario; marco();
}

/* ---------- Configuración ---------- */
Vistas.config = async v => {
  const edita = can('config', 2);
  v.innerHTML = cabecera('Configuración', 'Identidad del sistema') + `<div class="tarjeta"><h2>Logo</h2><p class="nota">Aparece en el acceso, el menú y las guías. PNG, JPG, WEBP o SVG de hasta 2 MB.</p>
    <img class="logo-vista" src="${esc(logo())}" alt="Logo actual"><div class="filtros" style="margin-top:12px">${edita ? `<input type="file" id="lg" accept="image/png,image/jpeg,image/webp,image/svg+xml" aria-label="Archivo del logo" style="max-width:320px">${S.logo ? '<button class="btn" id="qt">Quitar logo</button>' : ''}` : ''}</div></div>
    ${edita ? '<div class="tarjeta"><h2>Respaldo</h2><p class="nota">Descarga una copia completa de la base de datos. Guárdala en un lugar seguro: incluye toda la información del sistema.</p><a class="btn" href="/api/config/respaldo" style="display:inline-block;text-decoration:none">Descargar respaldo</a></div>' : ''}`;
  $('#lg', v)?.addEventListener('change', e => {
    const a = e.target.files[0]; if (!a) return;
    if (a.size > 2 * 1024 * 1024) return aviso('El archivo supera 2 MB.', 1);
    const r = new FileReader();
    r.onload = async () => {
      try { await api('PUT', '/config/logo', { logo: r.result }); S.logo = r.result; aviso('Logo actualizado.'); marco(); render(); }
      catch (x) { aviso(x.message, 1); }
    };
    r.readAsDataURL(a);
  });
  $('#qt', v)?.addEventListener('click', async () => { await api('PUT', '/config/logo', { logo: '' }); S.logo = null; marco(); render(); });
};

/* ---------- arranque y rutas ---------- */
const PERMISO_RUTA = { compras: ['compras', 'proveedores'] };
let turno = 0;
function primeraRuta() {
  for (const [, items] of NAV) for (const [m, , alt] of items) if ((alt || [m]).some(x => can(x))) return m;
  return null;
}
async function render() {
  if (!S.usuario) return;
  const id = ++turno;
  let m = location.hash.replace(/^#\//, '');
  if (!Vistas[m] || !(PERMISO_RUTA[m] || [m]).some(x => can(x))) {
    m = primeraRuta();
    if (!m) { $('#vista').innerHTML = cabecera('Sin accesos', 'Tu perfil aún no tiene módulos asignados.'); return; }
    if (location.hash !== '#/' + m) { location.hash = '#/' + m; return; }
  }
  $$('.nav a').forEach(a => { const on = a.dataset.m === m; a.classList.toggle('activo', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  $('#lateral').classList.remove('abierto');
  const destino = document.createElement('div');
  try {
    await cargarCat();
    await Vistas[m](destino);
    if (id === turno) { const vista = $('#vista'); vista.replaceChildren(destino); }
  } catch (x) {
    if (id === turno && S.usuario) $('#vista').innerHTML = `<div class="tarjeta"><div class="error">${esc(x.message)}</div></div>`;
  }
}
async function iniciar() {
  S.estado = await api('GET', '/estado');
  S.usuario = S.estado.usuario; S.modulos = S.estado.modulos; S.logo = S.estado.logo;
  if (!S.usuario) return pantallaAcceso();
  marco();
  render();
}
addEventListener('hashchange', render);
iniciar().catch(x => { app.innerHTML = `<div class="acceso"><div class="tarjeta">${esc(x.message)}</div></div>`; });
