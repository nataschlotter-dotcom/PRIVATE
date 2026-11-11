'use strict';
/* Sistema de producción y logística de Nata & Schlott: frontend sin dependencias. */
const S = { usuario: null, modulos: [], cat: null, logo: null, estado: {} };
const app = document.getElementById('app');
const REGIONES = ['Arica y Parinacota', 'Tarapacá', 'Antofagasta', 'Atacama', 'Coquimbo', 'Valparaíso', 'Metropolitana de Santiago',
  "O'Higgins", 'Maule', 'Ñuble', 'Biobío', 'La Araucanía', 'Los Ríos', 'Los Lagos', 'Aysén', 'Magallanes'];
const TIPOS_MOV = {
  COMPRA: ['Compra', 'bien'], PRODUCCION: ['Producción', 'bien'], CONSUMO_PRODUCCION: ['Consumo en producción', ''], DESPACHO: ['Despacho', ''],
  RECEPCION_TIENDA: ['Recepción en tienda', 'bien'], MERMA: ['Merma', 'mal'], INVENTARIO: ['Toma de inventario', 'dorada'], VENTA: ['Venta', ''],
  CONSUMO_INTERNO: ['Consumo interno', ''], ANULACION: ['Anulación', 'alerta'], AJUSTE_ADMIN: ['Actualización de stock', 'dorada'], DEVOLUCION_PROVEEDOR: ['Devolución a proveedor', 'alerta'],
  DEVOLUCION_TIENDA: ['Devolución de tienda', 'alerta'], RECEPCION_CENTRAL: ['Recepción en central', 'bien'], CONSUMO_CENTRAL: ['Consumo interno central', ''],
  VENTA_FUDO: ['Ventas en Fudo', ''], TRANSFERENCIA_SALIDA: ['Transferencia enviada a otra tienda', ''], TRANSFERENCIA_ENTRADA: ['Transferencia recibida de otra tienda', 'bien'],
};
const NAV = [
  ['', [['panel', 'Panel de inicio']]],
  ['Compras', [['compras', 'Compras y proveedores', ['compras', 'proveedores']], ['devoluciones', 'Devoluciones a proveedores']]],
  ['Tiendas', [['tiendas', 'Tiendas'], ['bodegas', 'Bodegas']]],
  ['Artículos', [['articulos', 'Productos e insumos'], ['inventario', 'Toma de inventario'], ['historial', 'Historial'], ['mermas', 'Mermas']]],
  ['Producción', [['recetas', 'Recetas'], ['produccion', 'Producción']]],
  ['Logística', [['despachos', 'Despachos a tiendas']]],
  ['Gestión', [['reportes', 'Reportes']]],
  ['Administración', [['stock', 'Actualizar stock'], ['fudo', 'Integración Fudo', ['config']], ['usuarios', 'Usuarios y perfiles'], ['config', 'Configuración']]],
];

/* ---------- utilidades ---------- */
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const can = (m, n = 1) => (S.usuario?.permisos?.[m] || 0) >= n;
const puede = a => !!S.usuario?.permisos?.['acc_' + a];  // acciones críticas (anular, eliminar, Fudo, respaldo)
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
const claseArticulo = a => a.tipo === 'PRODUCTO' ? 'Producto' : a.tipo === 'SUBPRODUCTO' ? 'Subproducto' : a.punto_venta ? 'Insumo punto de venta' : a.desechable ? 'Desechable / aseo' : 'Insumo';
const SECCIONES = [{ id: 'INSUMOS', nombre: 'Bodega de insumos' }, { id: 'PUNTO_VENTA', nombre: 'Bodega de insumos puntos de venta' }, { id: 'DESECHABLES', nombre: 'Bodega de desechables y aseo' }, { id: 'ELABORADOS', nombre: 'Bodega de productos y subproductos' }];
const seccionDe = a => a.punto_venta ? 'PUNTO_VENTA' : a.desechable ? 'DESECHABLES' : a.tipo === 'INSUMO' ? 'INSUMOS' : 'ELABORADOS';
const grupoDespacho = a => a.punto_venta ? `Insumos puntos de venta · ${a.categoria}` : a.desechable ? 'Desechables y aseo' : 'Productos';

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
function bajarCsv(nombre, filas) {
  const celda = v => {
    if (typeof v === 'number') return String(Math.round(v * 100000) / 100000).replace('.', ',');
    let s = String(v ?? '');
    if (/^[=+\-@]/.test(s)) s = "'" + s;
    return `"${s.replace(/"/g, '""')}"`;
  };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['﻿' + filas.map(f => f.map(celda).join(';')).join('\r\n')], { type: 'text/csv;charset=utf-8' }));
  a.download = nombre + '.csv'; a.click(); URL.revokeObjectURL(a.href);
}
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
    bajarCsv(cfg.csv, [cols.map(c => c.t), ...cfg.filas.map(r => cols.map(c => valor(c, r)))]);
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
  const opcion = a => `<option value="${a.id}">${esc(a.codigo)} · ${esc(a.nombre)}</option>`;
  const opts = cfg.grupos ? cfg.grupos.map(g => `<optgroup label="${esc(g.nombre)}">${cfg.articulos.filter(g.filtro).map(opcion).join('')}</optgroup>`).join('') : cfg.articulos.map(opcion).join('');
  const categorias = [...new Set(cfg.articulos.map(a => a.categoria))].sort((x, y) => x.localeCompare(y)).map(x => ({ id: x, nombre: x }));
  caja.innerHTML = `<div class="filtros"><label>Filtrar artículos por categoría<select class="cat-filtro">${opciones(categorias, '', 'Todas las categorías')}</select></label></div>
    <div class="tabla-marco"><table class="lineas"><thead><tr><th>Artículo</th><th class="n">Cantidad</th><th>Unidad</th>
    ${cfg.stock ? '<th class="n">Disponible</th>' : ''}${cfg.precio ? `<th class="n">${esc(cfg.precio)}</th><th class="n">${esc(cfg.subtotal || 'Subtotal')}</th>` : ''}<th></th></tr></thead><tbody></tbody></table></div>
    <button type="button" class="btn mini agregar" style="margin-top:6px">+ Agregar línea</button><div class="combo-lista" role="listbox" hidden></div>`;
  const cuerpo = $('tbody', caja), lista = $('.combo-lista', caja), catFiltro = $('.cat-filtro', caja);
  const por = id => cfg.articulos.find(a => String(a.id) === String(id));
  const precioDe = a => !a ? 0 : cfg.precioDe ? cfg.precioDe(a) : a.precio || 0;
  const fSub = cfg.fSubtotal || fPeso;
  const etiqueta = a => `${a.codigo} · ${a.nombre}`;
  const normal = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const grupoDe = a => cfg.grupos?.find(g => g.filtro(a))?.nombre ?? a.categoria;
  const ordenGrupo = a => cfg.grupos ? cfg.grupos.findIndex(g => g.filtro(a)) : 0;
  let abierto = null, activo = -1;
  const colocar = () => {
    if (!abierto) return;
    const r = $('.busca', abierto).getBoundingClientRect(), alto = window.visualViewport?.height ?? innerHeight;
    const abajo = alto - r.bottom - 8, arriba = r.top - 8, usarArriba = abajo < 170 && arriba > abajo;
    lista.style.left = `${Math.max(8, Math.min(r.left, innerWidth - Math.max(r.width, 300) - 8))}px`;
    lista.style.width = `${Math.min(Math.max(r.width, 300), innerWidth - 16)}px`;
    lista.style.maxHeight = `${Math.max(usarArriba ? arriba : abajo, 120)}px`;
    lista.style.top = usarArriba ? 'auto' : `${r.bottom + 2}px`;
    lista.style.bottom = usarArriba ? `${innerHeight - r.top + 2}px` : 'auto';
  };
  function cerrarLista() {
    if (!abierto) return;
    $('.busca', abierto).setAttribute('aria-expanded', 'false');
    abierto = null; activo = -1; lista.hidden = true;
    removeEventListener('scroll', colocar, true); removeEventListener('resize', colocar);
  }
  function pintarLista(tr) {
    const entrada = $('.busca', tr), sel = por($('select', tr).value);
    const texto = sel && entrada.value === etiqueta(sel) ? '' : normal(entrada.value.trim());
    const usados = new Set($$('select', cuerpo).filter(s => s !== $('select', tr)).map(s => s.value));
    const disponibles = cfg.articulos.filter(a => !usados.has(String(a.id)) && (!catFiltro.value || a.categoria === catFiltro.value));
    const coincide = campos => a => texto.split(/\s+/).every(p => normal(campos(a)).includes(p));
    const porNombre = disponibles.filter(coincide(a => `${a.codigo} ${a.nombre}`));  // la categoría solo cuenta si el nombre no coincide
    const hallados = (porNombre.length ? porNombre : disponibles.filter(coincide(a => a.categoria)))
      .sort((x, y) => (ordenGrupo(x) - ordenGrupo(y)) || grupoDe(x).localeCompare(grupoDe(y)) || x.nombre.localeCompare(y.nombre));
    let previo = null;
    lista.innerHTML = hallados.map(a => {
      const cab = grupoDe(a) !== previo ? `<div class="combo-grupo">${esc(grupoDe(a))}</div>` : '';
      previo = grupoDe(a);
      return `${cab}<div class="combo-op" role="option" data-id="${a.id}"><span>${esc(etiqueta(a))}</span><small>${esc(a.categoria)}${cfg.stock ? ` · Disponible: ${fCant(cfg.stock[a.id] || 0)} ${esc(a.unidad)}` : ` · ${esc(a.unidad)}`}</small></div>`;
    }).join('') || '<div class="combo-vacio">Sin coincidencias. Revisa el texto o la categoría.</div>';
    activo = texto && hallados.length ? 0 : -1;
    marcarActivo();
  }
  function marcarActivo() {
    $$('.combo-op', lista).forEach((o, i) => { o.classList.toggle('activo', i === activo); if (i === activo) o.scrollIntoView({ block: 'nearest' }); });
  }
  function abrirLista(tr) {
    if (abierto !== tr) cerrarLista();
    if (!abierto) { addEventListener('scroll', colocar, true); addEventListener('resize', colocar); }
    abierto = tr; lista.hidden = false;
    $('.busca', tr).setAttribute('aria-expanded', 'true');
    pintarLista(tr); colocar();
  }
  function elegir(tr, id) {
    const s = $('select', tr);
    s.value = id; s.dispatchEvent(new Event('change'));
    $('.busca', tr).value = etiqueta(por(id));
    cerrarLista();
    $('.q', tr).focus();
  }
  lista.addEventListener('mousedown', e => e.preventDefault());
  lista.addEventListener('click', e => { const o = e.target.closest('.combo-op'); if (o && abierto) elegir(abierto, o.dataset.id); });
  function refrescar(tr) {
    const a = por($('select', tr).value);
    $('.u', tr).textContent = a?.unidad || '';
    if (cfg.stock) $('.d', tr).textContent = a ? fCant(cfg.stock[a.id] || 0) : '';
    if (cfg.precio) $('.s', tr).textContent = fSub((aNum($('.q', tr).value) || 0) * (cfg.editaPrecio ? aNum($('.p', tr).value) || 0 : precioDe(a)));
    cfg.alCambiar?.();
  }
  function agregar(v = {}) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td><input class="busca" type="text" role="combobox" aria-expanded="false" aria-autocomplete="list" aria-label="Buscar artículo" placeholder="Escribe parte del nombre o código…" autocomplete="off"><select aria-hidden="true" tabindex="-1" hidden><option value="">Selecciona…</option>${opts}</select></td>
      <td class="n">${inputNum('q', v.cantidad ?? '', 5).replace('<input', '<input aria-label="Cantidad"')}</td><td class="u tenue"></td>
      ${cfg.stock ? '<td class="n d tenue"></td>' : ''}
      ${cfg.precio ? `<td class="n">${cfg.editaPrecio ? inputNum('p', v.precio ?? '', 2).replace('<input', '<input aria-label="Precio"') : '<span class="pf"></span>'}</td><td class="n s"></td>` : ''}
      <td><button type="button" class="btn mini peligro quitar" aria-label="Quitar línea">×</button></td>`;
    cuerpo.append(tr);
    if (v.articulo_id) { $('select', tr).value = v.articulo_id; $('.busca', tr).value = por(v.articulo_id) ? etiqueta(por(v.articulo_id)) : ''; }
    const entrada = $('.busca', tr);
    entrada.addEventListener('focus', () => { entrada.select(); abrirLista(tr); });
    entrada.addEventListener('click', () => abrirLista(tr));
    entrada.addEventListener('input', () => {
      const s = $('select', tr);
      if (s.value) { s.value = ''; s.dispatchEvent(new Event('change')); }
      abrirLista(tr);
    });
    entrada.addEventListener('blur', () => {
      if (abierto === tr) cerrarLista();
      const a = por($('select', tr).value);
      entrada.value = a ? etiqueta(a) : '';  // un texto sin elegir no queda como si fuera un artículo
    });
    entrada.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        const op = $$('.combo-op', lista)[activo];
        if (abierto === tr && op) elegir(tr, op.dataset.id);
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (abierto !== tr) abrirLista(tr);
        const n = $$('.combo-op', lista).length;
        if (n) { activo = e.key === 'ArrowDown' ? (activo + 1) % n : (activo <= 0 ? n : activo) - 1; marcarActivo(); }
      } else if (e.key === 'Escape' && abierto === tr) {
        e.stopPropagation(); cerrarLista();
      }
    });
    const alSelect = () => {
      const a = por($('select', tr).value);
      if (cfg.precio && cfg.editaPrecio && a && !$('.p', tr).value) $('.p', tr).value = fNum(a.precio, 0, 2);
      if (cfg.precio && !cfg.editaPrecio) $('.pf', tr).textContent = a ? fPrecio(precioDe(a)) + (cfg.porUnidad ? ` / ${a.unidad}` : '') : '';
      refrescar(tr);
    };
    $('select', tr).addEventListener('change', alSelect);
    tr.addEventListener('input', () => refrescar(tr));
    $('.quitar', tr).addEventListener('click', () => { tr.remove(); cfg.alCambiar?.(); });
    alSelect();
  }
  catFiltro.addEventListener('change', () => {
    const fila = $$('tr', cuerpo).find(tr => !$('select', tr).value);
    if (!fila) return;
    $('.busca', fila).focus();
    abrirLista(fila);
  });
  $('.agregar', caja).addEventListener('click', () => { agregar(); $('.busca', cuerpo.lastElementChild).focus(); });
  (cfg.valores?.length ? cfg.valores : [{}]).forEach(agregar);
  return {
    leer: () => $$('tr', cuerpo).filter(tr => $('select', tr).value || $('.q', tr).value).map(tr => {
      const o = { articulo_id: Number($('select', tr).value) || null, cantidad: aNum($('.q', tr).value) };
      if (cfg.editaPrecio) o.precio = aNum($('.p', tr).value);
      return o;
    }),
    neto: () => $$('tr', cuerpo).reduce((s, tr) => {
      const a = por($('select', tr).value);
      return s + (aNum($('.q', tr).value) || 0) * (cfg.editaPrecio ? aNum($('.p', tr).value) || 0 : precioDe(a));
    }, 0),
  };
}

/* ---------- gráficos ---------- */
// Colores por valor (tienda, producto, artículo, proveedor…): paleta categórica validada para daltonismo,
// en orden fijo. Cada barra lleva su nombre y su valor escritos, así el color nunca es la única pista.
// Tonos suaves de la paleta (mismos colores, más claros y menos intensos); validada: se distinguen entre sí, también con daltonismo.
const PALETA_SERIES = ['#528cd8', '#f18760', '#5dbd92', '#e0a448', '#eb92b1', '#4c9b47', '#7c76e1', '#e86e68'];
const SIN_COLOR = '#a7abaf';  // del noveno en adelante: gris neutro (nunca se repite un color)
function ordenEntidades() {
  // Orden estable por identificador: el color sigue a la entidad, no a su lugar en el ranking.
  const m = new Map([['Bodega central', 0]]);
  const porId = l => [...(l || [])].sort((a, b) => a.id - b.id);
  for (const lista of [S.cat?.tiendas, S.cat?.articulos, S.cat?.proveedores])
    for (const x of porId(lista)) if (!m.has(x.nombre)) m.set(x.nombre, m.size);
  return m;
}
function coloresDe(nombres) {
  const orden = ordenEntidades();
  const tiendas = new Set(['Bodega central', ...(S.cat?.tiendas || []).map(t => t.nombre)]);
  const colores = new Map();
  if (nombres.every(n => tiendas.has(n))) {  // tiendas y bodegas: siempre el mismo color en todos los gráficos
    for (const n of nombres) colores.set(n, PALETA_SERIES[orden.get(n)] || SIN_COLOR);
    return colores;
  }
  const unicos = [...new Set(nombres)].sort((a, b) => (orden.get(a) ?? 1e9) - (orden.get(b) ?? 1e9) || a.localeCompare(b, 'es'));
  unicos.forEach((n, i) => colores.set(n, PALETA_SERIES[i] || SIN_COLOR));
  return colores;
}
function barras(filas, et, val, fmt = fPeso) {
  if (!filas.length) return '<p class="vacio">Sin datos en el período.</p>';
  const max = Math.max(...filas.map(val), 1);
  const colores = coloresDe(filas.map(r => String(et(r))));
  return `<div class="barras">${filas.map(r => `<div class="barra-fila" data-tip="${esc(et(r))}: ${esc(fmt(val(r)))}">
    <span>${esc(et(r))}</span><span class="barra-pista"><i style="width:${(val(r) / max * 100).toFixed(1)}%;background:${colores.get(String(et(r)))}"></i></span><b>${esc(fmt(val(r)))}</b></div>`).join('')}</div>`;
}
function columnas(titulo, serie, k) {
  const max = Math.max(...serie.map(s => s[k]), 1);
  const mes = m => new Date(m + '-15').toLocaleDateString('es-CL', { month: 'short' }).replace('.', '');
  const ult = serie[serie.length - 1]?.[k] || 0;
  return `<div class="tarjeta"><h2>${esc(titulo)}</h2><div class="mini-tot">${fPeso(ult)}<small>mes en curso</small></div>
    <div class="columnas" role="img" aria-label="${esc(titulo)} por mes">${serie.map((s, i) => `<div class="columna" data-tip="${esc(mes(s.mes))} ${s.mes.slice(0, 4)}: ${fPeso(s[k])}"><i style="height:${(s[k] / max * 100).toFixed(1)}%;background:${PALETA_SERIES[i] || SIN_COLOR}"></i></div>`).join('')}</div>
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
    <polyline fill="none" stroke="#3a8f9e" stroke-width="2" stroke-linejoin="round" points="${serie.map((s, i) => `${x(i)},${y(s.precio)}`).join(' ')}"/>
    ${serie.map((s, i) => `<g data-tip="${fFecha(s.fecha)}\n${fPrecio(s.precio)}\n${esc(s.proveedor)}"><circle cx="${x(i)}" cy="${y(s.precio)}" r="12" fill="transparent"/><circle cx="${x(i)}" cy="${y(s.precio)}" r="5" fill="${PALETA_SERIES[i] || SIN_COLOR}" stroke="#fff" stroke-width="2"/></g>`).join('')}
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
      // cada usuario parte en su propia primera pantalla, no en la que dejó abierta otra persona en este navegador
      history.replaceState(null, '', location.pathname + location.search);
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
  const tabs = [...(can('compras') ? [['compras', 'Compras'], ['guias', 'Guías por facturar']] : []), ...(can('proveedores') ? [['proveedores', 'Proveedores'], ['iva', 'Valor IVA']] : [])];
  const t = tabs.some(x => x[0] === tabCompras) ? tabCompras : tabs[0][0];
  v.innerHTML = cabecera('Compras', 'Compras de insumos a proveedores', t === 'compras' && can('compras', 2) ? '<button class="btn primario" id="nueva">Registrar compra</button>'
    : t === 'guias' && can('compras', 2) ? '<button class="btn primario" id="factura">Registrar factura</button>'
    : t === 'proveedores' && can('proveedores', 2) ? '<button class="btn primario" id="nuevo-p">Nuevo proveedor</button>' : '');
  v.append(pestanas(tabs, t, k => { tabCompras = k; render(); }));
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  if (t === 'compras') {
    const filas = await api('GET', '/compras');
    tabla(c, { filas, csv: 'compras', vacio: 'Aún no hay compras.', acciones: {
      ver: async r => verCompra(r.id),
      anular: r => confirmar('Anular compra', `Se revertirá el stock de la compra #${r.id}. Solo es posible si el stock aún está disponible.`, async () => { await api('POST', `/compras/${r.id}/anular`, {}); aviso('Compra anulada.'); render(); }, 'Anular compra'),
    }, cols: [
      { t: 'N°', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Proveedor', v: r => r.proveedor }, { t: 'RUT', v: r => r.rut }, { t: 'Tipo', v: r => TIPOS_DOC[r.tipo_documento] || '—' }, { t: 'Documento', v: r => r.documento },
      { t: 'Neto', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }, { t: 'IVA', n: 1, v: r => r.iva, h: r => fPeso(r.iva) }, { t: 'Total', n: 1, v: r => r.total, h: r => fPeso(r.total) },
      { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Vigente', 'bien') },
      { t: 'Factura', v: r => r.tipo_documento !== 'GUIA' || r.estado === 'ANULADO' ? '' : r.factura_doc ? 'Factura ' + r.factura_doc : 'Pendiente de factura',
        h: r => r.tipo_documento !== 'GUIA' || r.estado === 'ANULADO' ? '' : r.factura_doc ? etq('Factura ' + r.factura_doc, 'bien') : etq('Pendiente de factura', 'alerta') },
      { t: '', h: r => `<div class="acciones">${accion('ver', 'Ver')}${r.estado !== 'ANULADO' && !r.factura_doc && can('compras', 2) && puede('anular_compras') ? accion('anular', 'Anular', 'peligro') : ''}</div>` }] });
    $('#nueva', v)?.addEventListener('click', nuevaCompra);
  } else if (t === 'guias') {
    await vistaGuiasPorFacturar(v, c);
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
const TIPOS_DOC = { FACTURA: 'Factura', BOLETA: 'Boleta', GUIA: 'Guía de despacho' };
async function vistaGuiasPorFacturar(v, c) {
  const [pend, facturas] = await Promise.all([api('GET', '/compras/guias-pendientes'), api('GET', '/compras/facturas')]);
  c.innerHTML = `<h2>Guías de despacho pendientes de factura</h2><p class="nota">El stock de estas guías ya ingresó. Cuando llegue la factura, presiona <b>Registrar factura</b> y marca las guías que incluye: quedan neteadas, sin volver a sumar stock ni compras.</p><div></div>`;
  tabla(c.lastElementChild, { filas: pend, csv: 'guias_por_facturar', vacio: 'No hay guías pendientes de factura.', acciones: { ver: r => verCompra(r.id), facturar: r => registrarFactura(r.proveedor_id) }, cols: [
    { t: 'Compra', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Proveedor', v: r => r.proveedor }, { t: 'N° guía', v: r => r.documento },
    { t: 'Neto', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }, { t: 'Total', n: 1, v: r => r.total, h: r => fPeso(r.total) },
    { t: 'Días', n: 1, v: r => Math.max(0, Math.round((new Date(hoy()) - new Date(r.fecha)) / 864e5)) },
    { t: '', h: () => `<div class="acciones">${accion('ver', 'Ver')}${can('compras', 2) ? accion('facturar', 'Registrar factura') : ''}</div>` }] });
  const c2 = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  c2.innerHTML = '<h2>Facturas que netean guías</h2><div></div>';
  tabla(c2.lastElementChild, { filas: facturas, csv: 'facturas_guias', vacio: 'Aún no se registran facturas de guías.', acciones: {
    anular: r => confirmar('Anular factura', `La factura ${r.documento} se anulará y sus guías volverán a quedar pendientes de factura. El stock no cambia.`, async () => { await api('POST', `/compras/facturas/${r.id}/anular`, {}); aviso('Factura anulada: sus guías quedaron pendientes.'); render(); }, 'Anular factura') }, cols: [
    { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Proveedor', v: r => r.proveedor }, { t: 'N° factura', v: r => r.documento },
    { t: 'Guías', v: r => r.guias.map(g => g.documento || '#' + g.id).join(', ') },
    { t: 'Neto factura', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }, { t: 'Neto guías', n: 1, v: r => r.neto_guias, h: r => fPeso(r.neto_guias) },
    { t: 'Diferencia', n: 1, v: r => r.diferencia, h: r => Math.abs(r.diferencia) < 1 ? '<span class="tenue">—</span>' : `<span class="${r.diferencia > 0 ? 'neg' : 'pos'}">${r.diferencia > 0 ? '+' : ''}${fPeso(r.diferencia)}</span>` },
    { t: 'Total', n: 1, v: r => r.total, h: r => fPeso(r.total) },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'VIGENTE' ? etq('Vigente', 'bien') : etq('Anulada', 'mal') },
    { t: '', h: r => r.estado === 'VIGENTE' && can('compras', 2) && puede('anular_compras') ? `<div class="acciones">${accion('anular', 'Anular', 'peligro')}</div>` : '' }] });
  $('#factura', v)?.addEventListener('click', () => registrarFactura(''));
}
function registrarFactura(provSel) {
  const m = modal('Registrar factura de guías de despacho', `<form novalidate><div class="campos">
    <label class="campo"><span>Proveedor</span><select name="proveedor_id">${opciones(S.cat.proveedores, provSel, 'Selecciona…')}</select></label>
    <label class="campo"><span>Fecha de la factura</span><input type="date" name="fecha" value="${hoy()}"></label>
    <label class="campo"><span>N° de factura</span><input name="documento" maxlength="40"></label>
    <label class="campo"><span>Neto de la factura</span>${inputNum('', '', 2).replace('<input', '<input name="neto"')}<small>Se completa con la suma de las guías marcadas. Cámbialo si la factura dice otro monto.</small></label></div>
    <h3 style="font-size:14px;margin:14px 0 6px">Guías que incluye la factura</h3><div class="fg-guias"><p class="tenue">Elige el proveedor.</p></div>
    <div class="totales fg-tot"></div><div class="error" hidden></div>
    <div class="modal-pie"><button type="button" class="btn cerrar2">Cancelar</button><button class="btn primario">Registrar factura</button></div></form>`, true);
  const f = $('form', m.el);
  let guias = [], netoTocado = false;
  const marcadas = () => $$('.fg-guias input:checked', m.el).map(i => guias.find(g => g.id === Number(i.value)));
  const totales = () => {
    const ng = marcadas().reduce((s, g) => s + g.neto, 0);
    if (!netoTocado) f.neto.value = ng ? fNum(ng, 0, 2) : '';
    const n = aNum(f.neto.value) ?? ng, iva = (Number.isNaN(n) ? 0 : n) * S.cat.iva / 100, dif = (Number.isNaN(n) ? 0 : n) - ng;
    $('.fg-tot', m.el).innerHTML = `<div><span>Neto guías marcadas</span><span>${fPeso(ng)}</span></div><div><span>Neto factura</span><span>${fPeso(n)}</span></div>
      <div><span>IVA ${fNum(S.cat.iva, 0, 2)}%</span><span>${fPeso(iva)}</span></div><div class="total"><span>Total factura</span><span>${fPeso(n + iva)}</span></div>
      ${Math.abs(dif) >= 1 ? `<div><span>Diferencia con las guías</span><span class="${dif > 0 ? 'neg' : 'pos'}">${dif > 0 ? '+' : ''}${fPeso(dif)}</span></div>` : ''}`;
  };
  const cargar = async () => {
    const caja = $('.fg-guias', m.el);
    if (!f.proveedor_id.value) { guias = []; caja.innerHTML = '<p class="tenue">Elige el proveedor.</p>'; totales(); return; }
    guias = await api('GET', '/compras/guias-pendientes' + qs({ proveedor_id: f.proveedor_id.value }));
    caja.innerHTML = guias.length ? `<div class="tabla-marco"><table><thead><tr><th></th><th>Fecha</th><th>N° guía</th><th>Compra</th><th class="n">Neto</th><th class="n">Total</th></tr></thead><tbody>
      ${guias.map(g => `<tr><td><input type="checkbox" value="${g.id}" checked aria-label="Incluir guía ${esc(g.documento)}"></td><td>${fFecha(g.fecha)}</td><td>${esc(g.documento) || '—'}</td><td>#${g.id}</td><td class="n">${fPeso(g.neto)}</td><td class="n">${fPeso(g.total)}</td></tr>`).join('')}</tbody></table></div>`
      : '<p class="tenue">Este proveedor no tiene guías pendientes de factura.</p>';
    totales();
  };
  f.proveedor_id.addEventListener('change', () => { netoTocado = false; cargar(); });
  $('.fg-guias', m.el).addEventListener('change', totales);
  f.neto.addEventListener('input', () => { netoTocado = f.neto.value.trim() !== ''; totales(); });
  $('.cerrar2', m.el).addEventListener('click', m.cerrar);
  conEnvio(f, m, async () => {
    const n = aNum(f.neto.value);
    if (Number.isNaN(n)) throw new Error('El neto de la factura no es un número válido.');
    const r = await api('POST', '/compras/facturas', { proveedor_id: f.proveedor_id.value, fecha: f.fecha.value, documento: f.documento.value, neto: n, guias: marcadas().map(g => g.id) });
    aviso(Math.abs(r.diferencia) >= 1 ? `Factura registrada. Diferencia con las guías: ${fPeso(r.diferencia)}.` : 'Factura registrada: las guías quedaron neteadas.'); render();
  });
  cargar();
}
function nuevaCompra() {
  const activos = S.cat.proveedores.filter(p => p.activo);
  const m = modal('Registrar compra', `<form novalidate><div class="campos"><label class="campo"><span>Proveedor</span><select name="proveedor_id">${opciones(activos, '', 'Selecciona…')}</select></label>
    <label class="campo"><span>Fecha</span><input type="date" name="fecha" value="${hoy()}"></label><label class="campo"><span>Tipo de documento</span><select name="tipo_documento">${opciones(Object.entries(TIPOS_DOC).map(([id, nombre]) => ({ id, nombre })), '', 'Selecciona…')}</select></label><label class="campo"><span>N° de documento</span><input name="documento"><small class="doc-ayuda" hidden>Si no tienes el número de la guía, déjalo vacío: se asigna uno automático (SN-…).</small></label></div>
    <h3 style="font-size:14px;margin:14px 0 6px">Detalle</h3><div id="lin"></div><div class="totales" id="tot"></div><div class="error" hidden></div>
    <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Registrar compra</button></div></form>`, true);
  $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
  $('select[name=tipo_documento]', m.el).addEventListener('change', e => { $('.doc-ayuda', m.el).hidden = e.target.value !== 'GUIA'; });
  const totales = () => {
    const n = ed ? ed.neto() : 0, i = n * S.cat.iva / 100;
    $('#tot', m.el).innerHTML = `<div><span>Neto</span><span>${fPeso(n)}</span></div><div><span>IVA ${fNum(S.cat.iva, 0, 2)}%</span><span>${fPeso(i)}</span></div><div class="total"><span>Total</span><span>${fPeso(n + i)}</span></div>`;
  };
  let ed = null;
  ed = editorLineas($('#lin', m.el), { articulos: S.cat.articulos.filter(a => a.tipo === 'INSUMO'), precio: 'Precio neto', editaPrecio: true, alCambiar: totales });
  totales();
  conEnvio($('form', m.el), m, async () => {
    const f = $('form', m.el);
    await api('POST', '/compras', { proveedor_id: f.proveedor_id.value, fecha: f.fecha.value, tipo_documento: f.tipo_documento.value, documento: f.documento.value, items: ed.leer() });
    aviso(f.tipo_documento.value === 'GUIA' ? 'Guía registrada: el stock aumentó. Queda pendiente de factura.' : 'Compra registrada: el stock aumentó.'); render();
  });
}
async function verCompra(id) {
  const c = await api('GET', `/compras/${id}`);
  const m = modal(`Compra #${c.id}`, `<div class="guia-datos"><div><b>Proveedor:</b> ${esc(c.proveedor)}</div><div><b>RUT:</b> ${esc(c.rut)}</div><div><b>Fecha:</b> ${fFecha(c.fecha)}</div><div><b>Tipo de documento:</b> ${esc(TIPOS_DOC[c.tipo_documento]) || '—'}</div><div><b>Documento:</b> ${esc(c.documento) || '—'}</div><div><b>Registrada por:</b> ${esc(c.usuario)}</div>
    ${c.tipo_documento === 'GUIA' ? `<div><b>Factura:</b> ${c.factura_doc ? `${esc(c.factura_doc)} del ${fFecha(c.factura_fecha)}` : 'Pendiente'}</div>` : ''}</div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Insumo</th><th class="n">Cantidad</th><th class="n">Precio neto</th><th class="n">Subtotal</th></tr></thead><tbody>${c.items.map(i => `<tr><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)} ${esc(i.unidad)}</td><td class="n">${fPrecio(i.precio)}</td><td class="n">${fPeso(i.cantidad * i.precio)}</td></tr>`).join('')}</tbody></table></div>
    <div class="totales"><div><span>Neto</span><span>${fPeso(c.neto)}</span></div><div><span>IVA ${fNum(c.iva_pct, 0, 2)}%</span><span>${fPeso(c.iva)}</span></div><div class="total"><span>Total</span><span>${fPeso(c.total)}</span></div></div>`, true);
  return m;
}

/* ---------- Integración con Fudo ---------- */
Vistas.fudo = async v => {
  if (!can('config', 2)) { v.innerHTML = cabecera('Integración Fudo') + '<div class="tarjeta">Tu perfil solo puede ver esta sección con permiso de edición en Configuración.</div>'; return; }
  const filas = await api('GET', '/fudo');
  v.innerHTML = cabecera('Integración Fudo', 'Cada tienda se conecta con su propia cuenta de Fudo. Las guías se envían como gastos desde Despachos a tiendas.');
  if (filas.some(r => r.comparte_con)) v.insertAdjacentHTML('beforeend', '<div class="tarjeta"><p class="error"><b>Hay tiendas conectadas a la misma cuenta Fudo.</b> Fudo lleva el stock por cuenta, así que cada tienda debe usar la API Key y API Secret de su propia cuenta. Mientras tanto, el envío de guías y las operaciones de stock de esas tiendas están bloqueados.</p></div>');
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  const ajustes = async r => {
    const l = await api('POST', `/fudo/${r.tienda_id}/probar`, {});
    formulario(`Gastos de ${r.nombre}`, [
      { k: 'categoria_id', t: 'Categoría de gasto en Fudo', tipo: 'select', op: l.categorias, vacio: 'Selecciona…', todo: 1 },
      { k: 'monto', t: 'Monto del gasto', tipo: 'select', op: [{ id: 'TOTAL', nombre: 'Total de la guía, con IVA' }, { id: 'NETO', nombre: 'Neto de la guía, sin IVA' }], todo: 1,
        ayuda: 'El gasto se registra con el proveedor "Nata & Schlott" (se crea en Fudo si no existe), pagado en Efectivo con la fecha de la guía.' },
      { k: 'stock_modo', t: 'Stock de los insumos en Fudo', tipo: 'select', todo: 1, op: [
        { id: 'SISTEMA', nombre: 'Lo suma el sistema automáticamente' },
        { id: 'MANUAL', nombre: 'Lo cargo yo en el detalle del gasto en Fudo' }],
        ayuda: 'Con "Lo cargo yo", el sistema no toca el stock de Fudo: abre el gasto GD-… en Fudo y carga su detalle de insumos (Fudo registra "Detalle de gasto creado"). El sistema igual cuenta esas cantidades para calcular el consumo por ventas.' }], r, async d => {
      await api('PUT', `/fudo/${r.tienda_id}/gastos`, { ...d, categoria: l.categorias.find(x => x.id === d.categoria_id)?.nombre || '', proveedor_id: r.proveedor_id, proveedor: r.proveedor });
      aviso('Conexión con Fudo lista.'); render();
    }, 'Guardar');
  };
  const credenciales = r => formulario(`Conectar ${r.nombre} con Fudo`, [
    { k: 'api_key', t: 'API Key', auto: 'off', todo: 1, ayuda: r.key_final ? `Guardada, termina en ${r.key_final}. Déjala en blanco para mantenerla.` : 'En Fudo: Administración → Usuarios.' },
    { k: 'api_secret', t: 'API Secret', tipo: 'password', auto: 'new-password', todo: 1, ayuda: r.conectada ? 'Guardada. Déjala en blanco para mantenerla.' : 'Se guarda en este sistema y no vuelve a mostrarse.' },
    ...(r.equivalencias ? [{ k: 'reiniciar_equivalencias', t: `Si es otra cuenta Fudo, borrar las ${r.equivalencias} equivalencias de esta tienda (apuntan a la cuenta anterior)`, tipo: 'check', todo: 1 }] : [])], {}, async d => {
    await api('PUT', `/fudo/${r.tienda_id}/credenciales`, d);
    await ajustes(r);
    render();
  }, 'Guardar y probar');
  tabla(c, { filas, vacio: 'Aún no hay tiendas.', acciones: { conectar: credenciales, ajustes: r => ajustes(r).catch(x => aviso(x.message, 1)), insumos: r => fudoInsumos(r) }, cols: [
    { t: 'Tienda', v: r => r.nombre },
    { t: 'Conexión', v: r => r.conectada, h: r => (r.conectada && r.categoria_id ? etq('Lista', 'bien') : r.conectada ? etq('Falta categoría', 'alerta') : etq('Sin conectar')) +
      (r.comparte_con ? ' ' + etq(`Misma cuenta que ${r.comparte_con}`, 'mal') : '') },
    { t: 'Categoría de gasto', v: r => r.categoria }, { t: 'Proveedor', v: r => r.proveedor }, { t: 'Monto', v: r => r.conectada ? (r.monto === 'NETO' ? 'Neto' : 'Total') : '' },
    { t: '', h: r => `<div class="acciones">${accion('conectar', r.conectada ? 'Cambiar credenciales' : 'Conectar')}${r.conectada ? accion('ajustes', 'Ajustar gastos') + accion('insumos', 'Insumos y stock') : ''}</div>` }] });
};

/* Insumos de Fudo equivalentes a los del sistema, por tienda: comparar stock, descontar ventas y sumar despachos */
function fudoInsumos(t) {
  const m = modal(`Insumos y stock Fudo · ${t.nombre}`, '<div class="pf-tabs"></div><div class="pf-cuerpo"></div>', true);
  let pest = 'importar';
  const cuerpo = $('.pf-cuerpo', m.el);
  const articulos = () => S.cat.articulos.filter(a => a.activo !== 0 && (a.tipo === 'PRODUCTO' || a.desechable))
    .map(a => ({ id: a.id, nombre: `${a.codigo} · ${a.nombre} (${a.unidad})` }));
  const ir = async k => {
    pest = k;
    $('.pf-tabs', m.el).replaceChildren(pestanas([['importar', 'Importar desde Fudo'], ['equiv', 'Equivalencias'], ['comparar', 'Comparar y sincronizar'], ['hist', 'Sincronizaciones']], pest, ir));
    cuerpo.innerHTML = '<p class="tenue">Cargando…</p>';
    try { await VISTAS_FUDO[k](); } catch (x) { cuerpo.innerHTML = `<p class="error">${esc(x.message)}</p>`; }
  };
  const VISTAS_FUDO = {
    async importar() {
      const ings = await api('GET', `/fudo/${t.tienda_id}/importar`);
      const pend = ings.filter(i => !i.equivalencia);
      const creaArt = can('articulos', 2);
      const arts = articulos();
      const GRUPOS = [['PRODUCTO', 'Producto'], ['PUNTO_VENTA', 'Insumo punto de venta'], ['DESECHABLE', 'Desechable / aseo']];
      const catsDe = g => S.cat.categorias.filter(c => g === 'PRODUCTO' ? c.de_productos : !c.de_productos && (g === 'PUNTO_VENTA' ? c.punto_venta : !c.punto_venta));
      const fila = (i, k) => `<tr data-k="${k}">
        <td class="c"><input type="checkbox" class="im-sel" aria-label="Importar ${esc(i.nombre)}" ${i.stock === null ? 'disabled' : ''}></td>
        <td><b>${esc(i.nombre)}</b><br><small class="tenue">${esc(i.unidad || '—')} · stock ${i.stock === null ? 'sin control' : fCant(i.stock)}</small></td>
        <td><select class="im-dest" aria-label="Artículo del sistema para ${esc(i.nombre)}">
          ${creaArt ? '<option value="nuevo">➕ Crear artículo nuevo</option>' : ''}<option value="">Selecciona artículo existente…</option>
          ${arts.map(a => `<option value="${a.id}" ${a.id === i.sugerido_id ? 'selected' : ''}>${esc(a.nombre)}</option>`).join('')}</select>
          ${i.sugerido_id ? `<small class="tenue">Sugerido por nombre (${Math.round(i.parecido * 100)}% parecido)</small>` : ''}
          <div class="im-nuevo filtros" style="margin-top:6px">
            <select class="im-grupo" aria-label="Grupo">${GRUPOS.map(([v, n]) => `<option value="${v}" ${v === 'PUNTO_VENTA' ? 'selected' : ''}>${n}</option>`).join('')}</select>
            <select class="im-cat" aria-label="Categoría"></select>
            <select class="im-uni" aria-label="Unidad">${opciones(S.cat.unidades.map(u => ({ id: u.id, nombre: `${u.nombre} (${u.abreviatura})` })), i.unidad_id, 'Unidad…')}</select>
            <input class="im-nom" value="${esc(i.nombre.replace(/^(IN|IPV|IDA)\s+/i, ''))}" aria-label="Nombre en el sistema" style="min-width:180px"></div></td>
        <td><input class="im-fac" value="1" inputmode="decimal" aria-label="Equivalencia" style="width:80px"><br><small class="tenue">del sistema por 1 ${esc(i.unidad || 'un')}</small></td></tr>`;
      cuerpo.innerHTML = `<p class="nota">Estos son los insumos de la cuenta Fudo de ${esc(t.nombre)} que aún no tienen equivalencia (${pend.length} de ${ings.length}).
        Marca los que quieres traer y elige, para cada uno, el artículo del sistema que le corresponde o <b>crea uno nuevo</b> con los datos de Fudo.
        Al importar, el stock actual de Fudo queda como punto de partida.${creaArt ? '' : ' Tu perfil no puede crear artículos: solo asociar existentes.'}</p>
        ${pend.length ? `<div class="filtros"><input type="search" class="im-buscar" placeholder="Buscar insumo de Fudo…" aria-label="Buscar insumo de Fudo">
          <button type="button" class="btn im-todos">Marcar todos</button><button type="button" class="btn im-ninguno">Desmarcar</button>
          <button type="button" class="btn primario im-ok">Importar seleccionados</button></div>
          ${creaArt ? `<div class="filtros"><span class="tenue">Para los marcados que se crearán nuevos:</span>
            <select class="lote-grupo" aria-label="Grupo para los marcados">${GRUPOS.map(([v, n]) => `<option value="${v}" ${v === 'PUNTO_VENTA' ? 'selected' : ''}>${n}</option>`).join('')}</select>
            <select class="lote-cat" aria-label="Categoría para los marcados"></select>
            <button type="button" class="btn lote-ok">Aplicar a marcados</button></div>` : ''}
          <div class="tabla-marco"><table><thead><tr><th></th><th>Insumo en Fudo</th><th>Artículo del sistema</th><th>Equivalencia</th></tr></thead><tbody>
          ${pend.map(fila).join('')}</tbody></table></div>` : '<p class="tenue">Todos los insumos de Fudo de esta tienda ya tienen equivalencia.</p>'}`;
      const ajustar = tr => {
        const nuevo = $('.im-dest', tr).value === 'nuevo';
        $('.im-nuevo', tr).style.display = nuevo ? '' : 'none';  // .filtros usa display:flex, que anula el atributo hidden
        const g = $('.im-grupo', tr).value, cat = $('.im-cat', tr), previo = cat.value;
        cat.innerHTML = opciones(catsDe(g), previo, 'Categoría…');
      };
      $$('tbody tr', cuerpo).forEach(tr => {
        if (!$('.im-dest', tr).value && creaArt && !pend[tr.dataset.k].sugerido_id) $('.im-dest', tr).value = 'nuevo';
        ajustar(tr);
        tr.addEventListener('change', e => { if (e.target.matches('.im-dest, .im-grupo')) ajustar(tr); if (!e.target.matches('.im-sel')) { const s = $('.im-sel', tr); if (!s.disabled) s.checked = true; } });
      });
      $('.im-buscar', cuerpo)?.addEventListener('input', e => { const q = e.target.value.toLowerCase(); $$('tbody tr', cuerpo).forEach(tr => { tr.hidden = !pend[tr.dataset.k].nombre.toLowerCase().includes(q); }); });
      $('.im-todos', cuerpo)?.addEventListener('click', () => $$('tbody tr:not([hidden]) .im-sel:not(:disabled)', cuerpo).forEach(s => { s.checked = true; }));
      $('.im-ninguno', cuerpo)?.addEventListener('click', () => $$('.im-sel', cuerpo).forEach(s => { s.checked = false; }));
      const loteCats = () => { const g = $('.lote-grupo', cuerpo); if (g) $('.lote-cat', cuerpo).innerHTML = opciones(catsDe(g.value), '', 'Categoría…'); };
      $('.lote-grupo', cuerpo)?.addEventListener('change', loteCats);
      loteCats();
      $('.lote-ok', cuerpo)?.addEventListener('click', () => {
        const g = $('.lote-grupo', cuerpo).value, cat = $('.lote-cat', cuerpo).value;
        if (!cat) return aviso('Elige la categoría a aplicar.', 1);
        let n = 0;
        $$('tbody tr', cuerpo).filter(tr => $('.im-sel', tr).checked && $('.im-dest', tr).value === 'nuevo').forEach(tr => {
          $('.im-grupo', tr).value = g; ajustar(tr); $('.im-cat', tr).value = cat; n++;
        });
        aviso(n ? `Grupo y categoría aplicados a ${n} insumo(s) marcados para crear.` : 'No hay insumos marcados para crear nuevos.', !n);
      });
      $('.im-ok', cuerpo)?.addEventListener('click', async () => {
        const sel = $$('tbody tr', cuerpo).filter(tr => $('.im-sel', tr).checked);
        if (!sel.length) return aviso('Marca al menos un insumo.', 1);
        try {
          const items = sel.map(tr => {
            const i = pend[tr.dataset.k], dest = $('.im-dest', tr).value, factor = aNum($('.im-fac', tr).value);
            if (Number.isNaN(factor) || factor <= 0) throw new Error(`${i.nombre}: la equivalencia debe ser mayor que 0.`);
            if (!dest) throw new Error(`${i.nombre}: elige el artículo del sistema o "Crear artículo nuevo".`);
            if (dest !== 'nuevo') return { fudo_id: i.id, articulo_id: Number(dest), factor };
            const nuevo = { grupo: $('.im-grupo', tr).value, categoria_id: $('.im-cat', tr).value, unidad_id: $('.im-uni', tr).value, nombre: $('.im-nom', tr).value };
            if (!nuevo.categoria_id || !nuevo.unidad_id) throw new Error(`${i.nombre}: elige categoría y unidad del artículo nuevo.`);
            return { fudo_id: i.id, factor, nuevo };
          });
          const r = await api('POST', `/fudo/${t.tienda_id}/importar`, { items });
          if (r.creados.length) await cargarCat();
          aviso(`Importados ${r.equivalencias} insumo(s)${r.creados.length ? `; artículos creados: ${r.creados.map(x => x.codigo).join(', ')}` : ''}.`);
          ir('equiv');
        } catch (x) { aviso(x.message, 1); }
      });
    },
    async equiv() {
      const [eqs, ings] = await Promise.all([api('GET', `/fudo/${t.tienda_id}/equivalencias`), api('GET', `/fudo/${t.tienda_id}/ingredientes`)]);
      const usados = new Set(eqs.map(e => e.fudo_id));
      cuerpo.innerHTML = `<p class="nota">Indica a qué artículo del sistema corresponde cada insumo de Fudo en esta tienda.
        <b>Equivalencia</b> = cuántas unidades del sistema hay en 1 unidad de Fudo. Por ejemplo, si en Fudo la leche está en ml y en el sistema en lt, la equivalencia es 0,001.</p>
        <div class="filtros"><button type="button" class="btn primario" id="fe-nueva">Agregar equivalencia</button></div><div class="tarjeta" id="fe-tabla"></div>`;
      tabla($('#fe-tabla', cuerpo), { filas: eqs, vacio: 'Aún no hay equivalencias.', acciones: {
        editar: e => formulario('Editar equivalencia', [
          { k: 'articulo_id', t: 'Artículo del sistema', tipo: 'select', op: articulos(), todo: 1 },
          { k: 'factor', t: `Unidades del sistema por 1 ${e.fudo_unidad || 'unidad'} de Fudo`, tipo: 'num', todo: 1 }], e,
          async d => { await api('PUT', `/fudo/equivalencias/${e.id}`, d); aviso('Equivalencia guardada.'); ir('equiv'); }),
        quitar: e => confirmar('Quitar equivalencia', `${e.fudo_nombre} dejará de sincronizarse con ${e.nombre}.`, async () => { await api('DELETE', `/fudo/equivalencias/${e.id}`); ir('equiv'); }, 'Quitar') }, cols: [
        { t: 'Insumo en Fudo', v: e => e.fudo_nombre }, { t: 'Unidad Fudo', v: e => e.fudo_unidad },
        { t: 'Artículo del sistema', v: e => `${e.codigo} · ${e.nombre}` }, { t: 'Equivalencia', n: 1, v: e => e.factor, h: e => `1 ${esc(e.fudo_unidad || 'un')} = ${fCant(e.factor)} ${esc(e.unidad)}` },
        { t: '', h: () => `<div class="acciones">${accion('editar', 'Editar')}${accion('quitar', 'Quitar', 'peligro')}</div>` }] });
      $('#fe-nueva', cuerpo).addEventListener('click', () => {
        const libres = ings.filter(i => !usados.has(i.id)).map(i => ({ id: i.id, nombre: `${i.nombre}${i.unidad ? ` (${i.unidad})` : ''}${i.stock === null ? ' — sin control de stock' : ''}` }));
        formulario('Nueva equivalencia', [
          { k: 'fudo_id', t: 'Insumo en Fudo', tipo: 'select', op: libres, vacio: 'Selecciona…', todo: 1 },
          { k: 'articulo_id', t: 'Artículo del sistema', tipo: 'select', op: articulos(), vacio: 'Selecciona…', todo: 1 },
          { k: 'factor', t: 'Unidades del sistema por 1 unidad de Fudo', tipo: 'num', def: 1, todo: 1, ayuda: 'Misma unidad en ambos: 1. Fudo en gramos y sistema en kg: 0,001.' }], {},
          async d => {
            const i = ings.find(x => x.id === d.fudo_id);
            if (!i) throw new Error('Selecciona el insumo de Fudo.');
            await api('POST', `/fudo/${t.tienda_id}/equivalencias`, { ...d, fudo_nombre: i.nombre, fudo_unidad: i.unidad });
            aviso('Equivalencia creada. El stock actual de Fudo queda como punto de partida.'); ir('equiv');
          }, 'Crear');
      });
    },
    async comparar() {
      const r = await api('GET', `/fudo/${t.tienda_id}/comparar`);
      const alerta = [r.comparte_con.length ? `<p class="error"><b>Esta tienda está conectada a la misma cuenta Fudo que ${esc(r.comparte_con.join(', '))}.</b> El stock de Fudo de abajo es el de esa cuenta, no el de esta tienda, y las operaciones de stock están bloqueadas. Conecta cada tienda con la API Key y API Secret de su propia cuenta (Integración Fudo → Cambiar credenciales).</p>` : '',
        r.envios_por_revisar ? `<p class="error">${r.envios_por_revisar} guía(s) con envío de stock a Fudo por revisar: resuélvelas en Despachos antes de sincronizar.</p>` : '',
        r.guias_sin_enviar ? `<p class="nota">${r.guias_sin_enviar} guía(s) vigentes con insumos equivalentes aún no suman su stock en Fudo (Despachos → Stock a Fudo).</p>` : ''].join('');
      cuerpo.innerHTML = `<p class="nota"><b>Consumo por ventas</b> = lo que Fudo descontó con sus recetas desde la última sincronización
        (stock anterior de Fudo + lo enviado desde el sistema − stock actual de Fudo). Al sincronizar se descuenta del stock de la tienda.
        Las mermas o ajustes hechos directamente en Fudo también cuentan como consumo.</p>${alerta}
        <div class="filtros"><label class="campo"><span>Fecha del descuento</span><input type="date" id="fs-fecha" value="${hoy()}"></label>
        ${puede('stock_fudo') ? `<button type="button" class="btn primario" id="fs-sinc" ${r.filas.length ? '' : 'disabled'}>Sincronizar ventas de Fudo</button>
        <button type="button" class="btn" id="fs-ajustar" ${r.filas.length ? '' : 'disabled'}>Ajustar sistema a Fudo</button>
        <button type="button" class="btn" id="fs-igualar" ${r.filas.length ? '' : 'disabled'}>Igualar Fudo al sistema</button>` : '<span class="tenue">Tu perfil puede ver la comparación, pero no sincronizar ni ajustar stock.</span>'}</div><div class="tarjeta" id="fs-tabla"></div>`;
      if (puede('stock_fudo')) $('#fs-ajustar', cuerpo).addEventListener('click', () => confirmar('Ajustar sistema a Fudo',
        'El stock de esta tienda en el sistema quedará igual al de Fudo en cada artículo equivalente. Se registra como una toma de inventario cerrada, visible en Toma de inventario.', async () => {
          const s = await api('POST', `/fudo/${t.tienda_id}/ajustar-sistema`, { fecha: $('#fs-fecha', cuerpo).value });
          aviso(`Stock ajustado a Fudo (toma de inventario N° ${s.inventario_id}).${s.avisos.length ? ' Avisos: ' + s.avisos.join(' · ') : ''}`, s.avisos.length > 0);
          ir('comparar');
        }, 'Ajustar sistema'));
      tabla($('#fs-tabla', cuerpo), { filas: r.filas, csv: `comparacion-fudo-${t.nombre}`, vacio: 'Aún no hay equivalencias.', cols: [
        { t: 'Artículo', v: e => `${e.codigo} · ${e.nombre}` }, { t: 'Insumo Fudo', v: e => e.fudo_nombre },
        { t: 'Stock sistema', n: 1, v: e => e.stock_sistema, h: e => `${fCant(e.stock_sistema)} ${esc(e.unidad)}` },
        { t: 'Stock Fudo', n: 1, v: e => e.fudo_en_sistema, h: e => e.fudo_stock === null ? '—' : `${fCant(e.fudo_en_sistema)} ${esc(e.unidad)}` },
        { t: 'Diferencia', n: 1, v: e => e.diferencia, h: e => e.diferencia === null ? '—' : etq(fCant(e.diferencia), Math.abs(e.diferencia) < 1e-6 ? 'bien' : 'alerta') },
        { t: 'Consumo por ventas', n: 1, v: e => e.consumo_pendiente, h: e => e.consumo_pendiente === null ? '—' : `${fCant(e.consumo_pendiente)} ${esc(e.unidad)}` },
        { t: 'Aviso', v: e => e.error, h: e => e.error ? etq(e.error, 'mal') : '' }] });
      $('#fs-sinc', cuerpo)?.addEventListener('click', () => confirmar('Sincronizar ventas de Fudo',
        'Se descontará del stock de la tienda el consumo por ventas de cada insumo. Lo consumido que supere el stock del sistema queda informado como faltante.', async () => {
          const s = await api('POST', `/fudo/${t.tienda_id}/sincronizar`, { fecha: $('#fs-fecha', cuerpo).value });
          aviso(`Sincronización N° ${s.id} registrada.`); ir('hist');
        }, 'Sincronizar'));
      $('#fs-igualar', cuerpo)?.addEventListener('click', () => confirmar('Igualar Fudo al sistema',
        'El stock de cada insumo equivalente en Fudo se reemplazará por el stock que tiene el sistema en esta tienda. Úsalo para partir alineados; el consumo pendiente sin sincronizar se pierde.', async () => {
          const s = await api('POST', `/fudo/${t.tienda_id}/igualar`, {});
          if (!s.ok) throw new Error(`Igualados: ${s.igualados}. Con error: ${s.errores.map(e => e.error).join(' · ')}`);
          aviso('Stock de Fudo igualado al sistema.'); ir('comparar');
        }, 'Igualar'));
    },
    async hist() {
      const filas = await api('GET', `/fudo/${t.tienda_id}/sincronizaciones`);
      cuerpo.innerHTML = '<div class="tarjeta" id="fh-tabla"></div>';
      const resumen = s => s.detalle.filter(x => x.descontado > 0 || x.faltante > 0 || x.error);
      tabla($('#fh-tabla', cuerpo), { filas, vacio: 'Aún no hay sincronizaciones.', acciones: {
        ver: s => modal(`Ventas Fudo N° ${s.id}`, `<p>${fFecha(s.fecha)} · ${esc(s.usuario || '')}</p><div class="tabla-marco"><table><thead><tr><th>Artículo</th><th class="n">Consumo</th><th class="n">Descontado</th><th class="n">Faltante</th><th>Aviso</th></tr></thead><tbody>
          ${s.detalle.map(x => `<tr><td>${esc(x.codigo)} · ${esc(x.nombre)}</td><td class="n">${x.error ? '—' : fCant(x.consumo)} ${esc(x.unidad)}</td><td class="n">${fCant(x.descontado || 0)}</td><td class="n">${fCant(x.faltante || 0)}</td>
          <td>${x.error ? etq(x.error, 'mal') : x.entrada_en_fudo ? etq(`Fudo subió ${fCant(x.entrada_en_fudo)} sin envío del sistema`, 'alerta') : ''}</td></tr>`).join('')}</tbody></table></div>`, true),
        anular: s => confirmar('Anular sincronización', 'Lo descontado vuelve al stock de la tienda. Ese consumo no se volverá a contar en la próxima sincronización.',
          async () => { await api('POST', `/fudo/sincronizaciones/${s.id}/anular`, {}); aviso('Sincronización anulada.'); ir('hist'); }, 'Anular') }, cols: [
        { t: 'N°', v: s => s.id }, { t: 'Fecha', v: s => s.fecha, h: s => fFecha(s.fecha) }, { t: 'Registrada', v: s => s.creado, h: s => fFecha(s.creado) }, { t: 'Por', v: s => s.usuario },
        { t: 'Artículos descontados', n: 1, v: s => s.detalle.filter(x => x.descontado > 0).length },
        { t: 'Con faltante o aviso', n: 1, v: s => resumen(s).filter(x => x.faltante > 0 || x.error).length },
        { t: 'Estado', v: s => s.estado, h: s => s.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Vigente', 'bien') },
        { t: '', h: s => `<div class="acciones">${accion('ver', 'Ver')}${s.estado === 'VIGENTE' && puede('stock_fudo') ? accion('anular', 'Anular', 'peligro') : ''}</div>` }] });
    },
  };
  ir(pest);
}

/* ---------- Devoluciones a proveedores ---------- */
Vistas.devoluciones = async v => {
  const crea = can('devoluciones', 2) && !S.usuario.tienda_id;
  const filas = await api('GET', '/devoluciones');
  v.innerHTML = cabecera('Devoluciones a proveedores', 'Cada devolución descuenta de la bodega central. Se devuelven insumos, insumos de puntos de venta, desechables y aseo; no productos ni subproductos.', crea ? '<button class="btn primario" id="n">Nueva devolución</button>' : '');
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  tabla(c, { filas, csv: 'devoluciones', vacio: 'Aún no hay devoluciones.', acciones: { ver: r => verDevolucion(r.id),
    anular: r => confirmar('Anular devolución', `El stock de la devolución #${r.id} volverá a la bodega central.`, async () => { await api('POST', `/devoluciones/${r.id}/anular`, {}); aviso('Devolución anulada.'); render(); }, 'Anular devolución') }, cols: [
    { t: 'N°', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Proveedor', v: r => r.proveedor }, { t: 'RUT', v: r => r.rut }, { t: 'Documento', v: r => r.documento }, { t: 'Motivo', v: r => r.motivo },
    { t: 'Neto', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }, { t: 'IVA', n: 1, v: r => r.iva, h: r => fPeso(r.iva) }, { t: 'Total', n: 1, v: r => r.total, h: r => fPeso(r.total) },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Vigente', 'bien') },
    { t: '', h: r => `<div class="acciones">${accion('ver', 'Ver')}${r.estado !== 'ANULADO' && crea && puede('anular_devoluciones') ? accion('anular', 'Anular', 'peligro') : ''}</div>` }] });
  $('#n', v)?.addEventListener('click', async () => {
    const central = await api('GET', '/stock/central');
    const stock = Object.fromEntries(central.map(a => [a.articulo_id, a.cantidad]));
    const m = modal('Nueva devolución a proveedor', `<form novalidate><div class="campos"><label class="campo"><span>Proveedor</span><select name="proveedor_id">${opciones(S.cat.proveedores.filter(p => p.activo), '', 'Selecciona…')}</select></label>
      <label class="campo"><span>Fecha</span><input type="date" name="fecha" value="${hoy()}"></label><label class="campo"><span>N° de documento</span><input name="documento" maxlength="40"></label><label class="campo"><span>Motivo</span><input name="motivo" maxlength="200"></label></div>
      <h3 style="font-size:14px;margin:14px 0 6px">Detalle</h3><div id="lin"></div><div class="totales" id="tot"></div><div class="error" hidden></div>
      <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Registrar devolución</button></div></form>`, true);
    $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
    let ed = null;
    const tot = () => { const n = ed ? ed.neto() : 0, i = n * S.cat.iva / 100; $('#tot', m.el).innerHTML = `<div><span>Neto</span><span>${fPeso(n)}</span></div><div><span>IVA ${fNum(S.cat.iva, 0, 2)}%</span><span>${fPeso(i)}</span></div><div class="total"><span>Total</span><span>${fPeso(n + i)}</span></div>`; };
    const grupo = a => a.punto_venta ? `Insumos puntos de venta · ${a.categoria}` : a.desechable ? 'Desechables y aseo' : 'Insumos';
    const articulos = S.cat.articulos.filter(a => a.tipo === 'INSUMO');
    ed = editorLineas($('#lin', m.el), { articulos, stock, precio: 'Precio neto', editaPrecio: true, alCambiar: tot,
      grupos: [...new Set(articulos.map(grupo))].sort().map(nombre => ({ nombre, filtro: a => grupo(a) === nombre })) });
    tot();
    const f = $('form', m.el);
    conEnvio(f, m, async () => {
      await api('POST', '/devoluciones', { proveedor_id: f.proveedor_id.value, fecha: f.fecha.value, documento: f.documento.value, motivo: f.motivo.value, items: ed.leer() });
      aviso('Devolución registrada: el stock de la bodega central disminuyó.'); render();
    });
  });
};
async function verDevolucion(id) {
  const d = await api('GET', `/devoluciones/${id}`);
  modal(`Devolución #${d.id}`, `<div class="guia-datos"><div><b>Proveedor:</b> ${esc(d.proveedor)}</div><div><b>RUT:</b> ${esc(d.rut)}</div><div><b>Fecha:</b> ${fFecha(d.fecha)}</div><div><b>Documento:</b> ${esc(d.documento) || '—'}</div><div><b>Motivo:</b> ${esc(d.motivo)}</div><div><b>Registrada por:</b> ${esc(d.usuario)}</div></div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Insumo</th><th class="n">Cantidad</th><th class="n">Precio neto</th><th class="n">Subtotal</th></tr></thead><tbody>${d.items.map(i => `<tr><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)} ${esc(i.unidad)}</td><td class="n">${fPrecio(i.precio)}</td><td class="n">${fPeso(i.cantidad * i.precio)}</td></tr>`).join('')}</tbody></table></div>
    <div class="totales"><div><span>Neto</span><span>${fPeso(d.neto)}</span></div><div><span>IVA ${fNum(d.iva_pct, 0, 2)}%</span><span>${fPeso(d.iva)}</span></div><div class="total"><span>Total</span><span>${fPeso(d.total)}</span></div></div>`, true);
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
let tabArt = 'PRODUCTO', filtroCat = '';
Vistas.articulos = async v => {
  const tabs = [['PRODUCTO', 'Productos'], ['SUBPRODUCTO', 'Subproductos'], ['INSUMO', 'Insumos'], ['PUNTO_VENTA', 'Insumos puntos de venta'], ['DESECHABLE', 'Desechables y aseo'], ['categorias', 'Categorías'], ['unidades', 'Unidades de medida']];
  const edita = can('articulos', 2), esArt = !['categorias', 'unidades'].includes(tabArt);
  const notas = { PRODUCTO: 'Artículos terminados. El precio es el de venta, neto.', SUBPRODUCTO: 'Preparaciones que forman parte de un producto. Se fabrican con receta.', INSUMO: 'Ingredientes comprados a proveedores que forman parte de una receta. El precio se actualiza con la última compra.', PUNTO_VENTA: 'Comprados a proveedores y despachados a tiendas, clasificados en café, chocolate, leches, té, agua, utensilios para café, utensilios de aseo y azúcar. No forman parte de una receta.', DESECHABLE: 'Comprados a proveedores, no forman parte de una receta y se despachan a tiendas: vasos, bombillas, sachets, limpiavidrios. Se clasifican en categorías como Aseo o Envases y desechables.' };
  v.innerHTML = cabecera('Productos, subproductos e insumos', notas[tabArt] || 'Tablas maestras', edita ? `<button class="btn primario" id="n">${esArt ? 'Nuevo artículo' : tabArt === 'categorias' ? 'Nueva categoría' : 'Nueva unidad'}</button>` : '');
  v.append(pestanas(tabs, tabArt, k => { tabArt = k; render(); }));
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  if (!esArt) {
    const tiposCat = [{ id: 1, nombre: 'Productos' }, { id: 0, nombre: 'No productos' }];
    const campos = tabArt === 'categorias' ? [{ k: 'nombre', t: 'Nombre', todo: 1 }, { k: 'de_productos', t: 'Tipo de categoría', tipo: 'select', op: tiposCat, def: 0, todo: 1, ayuda: 'Productos: para productos y subproductos. No productos: para insumos, desechables y aseo.' }] : [{ k: 'nombre', t: 'Nombre' }, { k: 'abreviatura', t: 'Abreviatura', ayuda: 'Ejemplo: kg' }];
    const titulo = tabArt === 'categorias' ? 'categoría' : 'unidad';
    const form = r => formulario((r ? 'Editar ' : 'Nueva ') + titulo, campos, r, async d => { await api(r ? 'PUT' : 'POST', `/${tabArt}` + (r ? '/' + r.id : ''), d); aviso('Guardado.'); render(); });
    $('#n', v)?.addEventListener('click', () => form());
    const lista = await api('GET', '/' + tabArt);
    if (tabArt === 'categorias') {
      c.insertAdjacentHTML('beforeend', `<div class="filtros"><label>Ver<select id="fc">${opciones(tiposCat, filtroCat, 'Todas las categorías')}</select></label></div><div id="tc"></div>`);
      $('#fc', c).addEventListener('change', e => { filtroCat = e.target.value; render(); });
    }
    tabla($('#tc', c) || c, { filas: tabArt === 'categorias' && filtroCat !== '' ? lista.filter(x => String(x.de_productos) === filtroCat) : lista, acciones: { editar: form,
      borrar: r => confirmar('Eliminar', `¿Eliminar "${r.nombre}"? No se podrá si algún artículo la usa.`, async () => { await api('DELETE', `/${tabArt}/${r.id}`); aviso('Eliminado.'); render(); }, 'Eliminar') },
    cols: [...(tabArt === 'categorias' ? [{ t: 'Nombre', v: r => r.nombre }, { t: 'Tipo de categoría', v: r => r.de_productos ? 'Productos' : r.punto_venta ? 'No productos · puntos de venta' : 'No productos' }] : campos.map(f => ({ t: f.t, v: r => r[f.k] }))), { t: '', h: () => edita ? `<div class="acciones">${accion('editar', 'Editar')}${puede('eliminar_registros') ? accion('borrar', 'Eliminar', 'peligro') : ''}</div>` : '' }] });
    return;
  }
  const todos = await api('GET', '/articulos');
  const filas = todos.filter(a => tabArt === 'PUNTO_VENTA' ? a.punto_venta : tabArt === 'DESECHABLE' ? a.desechable && !a.punto_venta : tabArt === 'INSUMO' ? a.tipo === 'INSUMO' && !a.desechable : a.tipo === tabArt);
  const form = r => {
    const despachable = tabArt === 'DESECHABLE' || tabArt === 'PUNTO_VENTA';
    const inicial = r || { tipo: despachable ? 'INSUMO' : tabArt, desechable: despachable };
    const esPuntoVenta = tabArt === 'PUNTO_VENTA';
    const categorias = S.cat.categorias.filter(x => inicial.tipo === 'INSUMO' ? !x.de_productos && !!x.punto_venta === esPuntoVenta : !!x.de_productos);
    formulario(r ? `Editar artículo ${r.codigo}` : 'Nuevo artículo', [
      { k: 'nombre', t: 'Nombre', todo: 1, ayuda: r ? '' : 'El código se asigna automáticamente al guardar.' },
      { k: 'categoria_id', t: 'Clasificación o categoría', tipo: 'select', op: categorias, vacio: 'Selecciona…' },
      { k: 'unidad_id', t: 'Unidad de medida', tipo: 'select', op: S.cat.unidades, vacio: 'Selecciona…' },
      { k: 'stock_minimo', t: 'Stock mínimo', tipo: 'num', dec: 5, min: 5, ayuda: 'Se muestra con miles y 5 decimales.' },
      { k: 'precio', t: inicial.tipo === 'INSUMO' ? 'Precio de compra neto' : inicial.tipo === 'PRODUCTO' ? 'Precio de venta neto' : 'Precio', tipo: 'num', dec: 2, ayuda: 'Con separador de miles.' },
      ...(r ? [{ k: 'activo', t: 'Artículo activo', tipo: 'check', todo: 1 }] : [])], inicial,
    async d => {
      const x = await api(r ? 'PUT' : 'POST', '/articulos' + (r ? '/' + r.id : ''), { ...d, tipo: inicial.tipo, desechable: inicial.desechable, punto_venta: esPuntoVenta });
      aviso(x.codigo ? `Artículo creado con el código ${x.codigo}.` : 'Artículo guardado.'); render();
    });
  };
  $('#n', v)?.addEventListener('click', () => form());
  tabla(c, { filas, csv: 'articulos', vacio: 'Sin artículos en esta clasificación.', acciones: { editar: form,
    borrar: r => confirmar('Eliminar artículo', `¿Eliminar "${r.nombre}"? No se podrá si tiene stock, recetas, compras, despachos u otros registros.`, async () => { await api('DELETE', `/articulos/${r.id}`); aviso('Artículo eliminado.'); render(); }, 'Eliminar') }, cols: [
    { t: 'Código', v: r => r.codigo }, { t: 'Nombre', v: r => r.nombre }, { t: 'Categoría', v: r => r.categoria }, { t: 'Unidad', v: r => r.unidad },
    { t: 'Stock mínimo', n: 1, v: r => r.stock_minimo, h: r => fMin(r.stock_minimo) },
    { t: 'Stock central', n: 1, v: r => r.stock, h: r => `${fCant(r.stock)}${r.stock < r.stock_minimo ? ' ' + etq('Bajo mínimo', 'mal') : ''}` },
    { t: 'Precio', n: 1, v: r => r.precio, h: r => fPrecio(r.precio) },
    { t: 'Estado', v: r => r.activo ? 'Activo' : 'Inactivo', h: r => r.activo ? etq('Activo', 'bien') : etq('Inactivo') },
    { t: '', h: () => edita ? `<div class="acciones">${accion('editar', 'Editar')}${puede('eliminar_registros') ? accion('borrar', 'Eliminar', 'peligro') : ''}</div>` : '' }] });
};

/* ---------- Toma de inventario ---------- */
const nombreToma = r => {
  let n = r.seccion ? `${r.bodega} · ${SECCIONES.find(s => s.id === r.seccion).nombre}` : r.bodega;
  const cs = r.categorias_nombres || [];
  if (cs.length) n += ' · ' + (cs.length <= 2 ? cs.join(', ') : `${cs.length} categorías`);
  return n;
};
const sinTilde = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
/* Conteo en una sola pantalla: bodega, fecha y motivo → tipo de artículo (o búsqueda) → conteos que se guardan solos. Lo vacío mantiene su stock. */
const TIPOS_CONTEO = [{ id: 'PRODUCTO', nombre: 'Productos' }, { id: 'SUBPRODUCTO', nombre: 'Subproductos' }, { id: 'INSUMO', nombre: 'Insumos' },
  { id: 'PUNTO_VENTA', nombre: 'Insumos para puntos de venta' }, { id: 'DESECHABLE', nombre: 'Desechables y aseo' }];
const tipoConteo = a => a.punto_venta ? 'PUNTO_VENTA' : a.desechable ? 'DESECHABLE' : a.tipo;
const MOTIVOS_TOMA = ['Inventario mensual', 'Inventario semanal', 'Cierre de mes', 'Control aleatorio', 'Recuento por diferencia'];
const invPanel = { bodega: null, tipo: '', q: '', fecha: '', obs: '' };
const tomaDePanel = r => r.estado === 'ABIERTO' && !r.seccion && !r.categorias;
async function panelConteo(v, filas) {
  const bods = bodegasOp();
  if (!bods.length) return;
  if (!bods.some(b => b.id === invPanel.bodega)) invPanel.bodega = bods[0].id;
  const abierta = filas.find(r => tomaDePanel(r) && r.bodega_id === invPanel.bodega);
  const otra = !abierta && filas.find(r => r.estado === 'ABIERTO' && r.bodega_id === invPanel.bodega);
  let tomaId = abierta?.id || null;
  const valores = new Map();
  const norm = (a, stock) => ({ id: a.articulo_id, codigo: a.codigo, nombre: a.nombre, unidad: a.unidad, categoria: a.categoria, tipo: tipoConteo(a), stock });
  let arts;
  if (tomaId) {
    const inv = await api('GET', `/inventarios/${tomaId}`);
    arts = inv.items.map(i => norm(i, i.stock_actual));
    inv.items.forEach(i => { if (i.conteo !== null) valores.set(i.articulo_id, i.conteo); });
    invPanel.fecha = inv.fecha; invPanel.obs = inv.obs;
  } else {
    arts = (await api('GET', '/inventarios/articulos' + qs({ bodega_id: invPanel.bodega }))).map(a => norm(a, a.cantidad));
    if (!invPanel.fecha) invPanel.fecha = hoy();
  }
  arts.sort((x, y) => x.categoria.localeCompare(y.categoria, 'es') || x.nombre.localeCompare(y.nombre, 'es'));
  const tipos = TIPOS_CONTEO.filter(t => arts.some(a => a.tipo === t.id));
  if (invPanel.tipo && invPanel.tipo !== 'TODOS' && !tipos.some(t => t.id === invPanel.tipo)) invPanel.tipo = '';
  const cierra = puede('cerrar_inventario');
  const t = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta conteo-panel' }));
  t.innerHTML = `<div class="cp-paso"><span class="cp-num">1</span><div class="filtros">
      <label>Bodega<select class="cp-bod">${opciones(bods, invPanel.bodega)}</select></label>
      <label>Fecha<input type="date" class="cp-fecha" value="${esc(invPanel.fecha)}"></label>
      <label class="cp-motivo">Motivo<input class="cp-obs" list="cp-motivos" maxlength="500" placeholder="Ej.: Inventario mensual" value="${esc(invPanel.obs)}"></label>
      <datalist id="cp-motivos">${MOTIVOS_TOMA.map(m => `<option value="${esc(m)}">`).join('')}</datalist>
      <span class="cp-estado tenue">${tomaId ? `Toma #${tomaId} en curso` : ''}</span></div></div>
    ${otra ? `<p class="aviso-linea">La toma #${otra.id} de esta bodega quedó abierta con el método anterior. Ciérrala o elimínala desde la lista de abajo para contar aquí.</p>` : ''}
    <div class="cp-paso"><span class="cp-num">2</span><div class="filtros">
      <label>Tipo de artículo<select class="cp-tipo"><option value="">— Elige el tipo —</option>${tipos.map(x => `<option value="${x.id}" ${x.id === invPanel.tipo ? 'selected' : ''}>${esc(x.nombre)} (${arts.filter(a => a.tipo === x.id).length})</option>`).join('')}<option value="TODOS" ${invPanel.tipo === 'TODOS' ? 'selected' : ''}>Todos los tipos (${arts.length})</option></select></label>
      <label class="cp-buscar">o busca un artículo<input type="search" class="cp-q" placeholder="Nombre o código…" value="${esc(invPanel.q)}"></label></div></div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Artículo</th><th class="n">Stock sistema</th><th class="n">Conteo físico</th><th class="n">Diferencia</th></tr></thead><tbody></tbody></table></div>
    <div class="modal-pie"><span class="tenue cp-resumen" style="margin-right:auto"></span>
      ${cierra ? '<button type="button" class="btn peligro cp-descartar">Descartar conteo</button><button type="button" class="btn primario cp-cerrar">Cerrar y ajustar stock</button>' : '<span class="tenue">Tu perfil no puede cerrar tomas: pide a quien tenga ese permiso que la cierre.</span>'}</div>`;
  const cuerpo = $('tbody', t), estado = (x, mal) => { const e = $('.cp-estado', t); e.textContent = x; e.className = 'cp-estado ' + (mal ? 'neg' : 'tenue'); };
  const listo = () => !!(invPanel.fecha && invPanel.obs.trim());
  const resumen = () => {
    const n = valores.size;
    $('.cp-resumen', t).textContent = n ? `${fNum(n)} ${n === 1 ? 'artículo contado' : 'artículos contados'}. Lo que no cuentes mantiene su stock.` : 'Lo que no cuentes mantiene su stock.';
  };
  const dif = (a, td) => {
    const n = valores.get(a.id);
    if (n === undefined) { td.textContent = ''; td.className = 'n dif'; return; }
    const x = n - a.stock;
    td.textContent = (x > 0 ? '+' : '') + fCant(x); td.className = 'n dif ' + (x > 0 ? 'pos' : x < 0 ? 'neg' : '');
  };
  const pintaTabla = () => {
    $('.cp-tipo', t).disabled = $('.cp-q', t).disabled = !listo();
    if (!listo()) { cuerpo.innerHTML = '<tr><td colspan="5" class="vacio">Ingresa la fecha y el motivo de la toma para empezar.</td></tr>'; return; }
    const q = sinTilde(invPanel.q.trim());
    const lista = arts.filter(a => q ? sinTilde(`${a.codigo} ${a.nombre}`).includes(q) : invPanel.tipo && (invPanel.tipo === 'TODOS' || a.tipo === invPanel.tipo));
    let cat = null;
    cuerpo.innerHTML = lista.map(a => (a.categoria !== cat ? `<tr class="grupo"><td colspan="5">${esc(cat = a.categoria)}</td></tr>` : '') +
      `<tr data-a="${a.id}"><td>${esc(a.codigo)}</td><td>${esc(a.nombre)}</td><td class="n">${fCant(a.stock)} ${esc(a.unidad)}</td>
      <td class="n">${inputNum('c', valores.get(a.id) ?? '', 5).replace('<input', `<input aria-label="Conteo de ${esc(a.nombre)}"`)}</td><td class="n dif"></td></tr>`).join('')
      || `<tr><td colspan="5" class="vacio">${q ? 'Ningún artículo coincide con la búsqueda.' : 'Elige el tipo de artículo o busca uno por nombre.'}</td></tr>`;
    $$('tr[data-a]', cuerpo).forEach(tr => dif(arts.find(a => a.id === Number(tr.dataset.a)), $('.dif', tr)));
  };
  let cola = Promise.resolve();
  const enCola = fn => { cola = cola.then(async () => { try { await fn(); } catch (x) { estado(x.message, true); } }); return cola; };
  const guardar = (id, conteo) => enCola(async () => {
    estado('Guardando…');
    if (!tomaId) tomaId = (await api('POST', '/inventarios', { bodega_id: invPanel.bodega, fecha: invPanel.fecha, obs: invPanel.obs.trim() })).id;
    await api('PUT', `/inventarios/${tomaId}`, { items: [{ articulo_id: id, conteo }] });
    estado(`Toma #${tomaId} · guardado ✓`);
  });
  const guardarCabecera = () => { if (tomaId && listo()) enCola(async () => { await api('PUT', `/inventarios/${tomaId}`, { fecha: invPanel.fecha, obs: invPanel.obs.trim() }); estado(`Toma #${tomaId} · guardado ✓`); }); };
  cuerpo.addEventListener('input', e => {
    const tr = e.target.closest('tr[data-a]'); if (!tr) return;
    const a = arts.find(x => x.id === Number(tr.dataset.a)), n = aNum(e.target.value);
    if (n === null) valores.delete(a.id); else if (!Number.isNaN(n)) valores.set(a.id, n);
    dif(a, $('.dif', tr));
  });
  cuerpo.addEventListener('change', e => {
    const tr = e.target.closest('tr[data-a]'); if (!tr) return;
    const n = aNum(e.target.value);
    if (Number.isNaN(n)) return estado('Hay un conteo que no es un número válido.', true);
    guardar(Number(tr.dataset.a), n); resumen();
  });
  $('.cp-fecha', t).addEventListener('change', e => { invPanel.fecha = e.target.value; pintaTabla(); guardarCabecera(); });
  $('.cp-obs', t).addEventListener('input', e => { invPanel.obs = e.target.value; const antes = $('.cp-tipo', t).disabled; if (antes === listo()) pintaTabla(); });
  $('.cp-obs', t).addEventListener('change', guardarCabecera);
  $('.cp-tipo', t).addEventListener('change', e => { invPanel.tipo = e.target.value; invPanel.q = ''; $('.cp-q', t).value = ''; pintaTabla(); });
  $('.cp-q', t).addEventListener('input', e => { invPanel.q = e.target.value; pintaTabla(); });
  $('.cp-bod', t).addEventListener('change', async e => { await cola; Object.assign(invPanel, { bodega: Number(e.target.value), tipo: '', q: '', fecha: '', obs: '' }); render(); });
  const reiniciar = () => Object.assign(invPanel, { tipo: '', q: '', fecha: '', obs: '' });
  $('.cp-cerrar', t)?.addEventListener('click', async () => {
    await cola;
    if (!listo()) return estado('Ingresa la fecha y el motivo.', true);
    if (!tomaId || !valores.size) return estado('Ingresa al menos un conteo antes de cerrar.', true);
    confirmar('Cerrar toma', `Se ajustará el stock de ${valores.size} ${valores.size === 1 ? 'artículo' : 'artículos'} según lo contado. El resto mantiene su stock.`, async () => {
      await api('POST', `/inventarios/${tomaId}/cerrar`, {}); reiniciar(); aviso('Toma cerrada y reflejada en el historial.'); render();
    }, 'Cerrar y ajustar');
  });
  $('.cp-descartar', t)?.addEventListener('click', async () => {
    await cola;
    if (!tomaId) { valores.clear(); resumen(); pintaTabla(); return; }
    confirmar('Descartar conteo', `¿Descartar la toma #${tomaId}? Se borran los conteos y no se ajusta ningún stock.`, async () => {
      await api('DELETE', `/inventarios/${tomaId}`); reiniciar(); render();
    }, 'Descartar');
  });
  resumen(); pintaTabla();
  if (!listo()) $(invPanel.fecha ? '.cp-obs' : '.cp-fecha', t).focus();
}
Vistas.inventario = async v => {
  const filas = await api('GET', '/inventarios');
  const edita = can('inventario', 2);
  v.innerHTML = cabecera('Toma de inventario', edita ? 'Ingresa la fecha y el motivo, elige el tipo de artículo (o búscalo) y escribe lo contado: se guarda solo. Al cerrar, cada diferencia ajusta el stock y queda en el historial.' : 'Tomas de inventario realizadas.');
  if (edita) await panelConteo(v, filas);
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  c.innerHTML = '<h2>Tomas realizadas</h2><div></div>';
  tabla(c.lastElementChild, { filas, vacio: 'Aún no hay tomas de inventario.', acciones: {
    abrir: r => { if (edita && tomaDePanel(r)) { invPanel.bodega = r.bodega_id; render(); scrollTo(0, 0); } else abrirInventario(r.id); },
    borrar: r => confirmar('Eliminar toma', `¿Eliminar la toma #${r.id} sin aplicar ajustes?`, async () => { await api('DELETE', `/inventarios/${r.id}`); render(); }, 'Eliminar') }, cols: [
    { t: 'N°', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Bodega', v: r => nombreToma(r) }, { t: 'Motivo', v: r => r.obs }, { t: 'Responsable', v: r => r.usuario },
    { t: 'Contados', n: 1, v: r => r.contadas, h: r => `${fNum(r.contadas)} de ${fNum(r.lineas)}` }, { t: 'Con diferencia', n: 1, v: r => r.con_diferencia, h: r => fNum(r.con_diferencia) },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ABIERTO' ? etq('Abierta', 'alerta') : etq('Cerrada', 'bien') },
    { t: '', h: r => `<div class="acciones">${accion('abrir', r.estado === 'ABIERTO' && edita ? 'Contar' : 'Ver')}${r.estado === 'ABIERTO' && edita && puede('cerrar_inventario') ? accion('borrar', 'Eliminar', 'peligro') : ''}</div>` }] });
};
async function abrirInventario(id) {
  const inv = await api('GET', `/inventarios/${id}`);
  const abierto = inv.estado === 'ABIERTO' && can('inventario', 2);
  const cats = [];
  for (const i of inv.items) if (!cats.some(x => x.id === i.categoria_id)) cats.push({ id: i.categoria_id, nombre: i.categoria });
  const filas = cats.map(cat => `<tr class="grupo" data-g="${cat.id}"><td colspan="5">${esc(cat.nombre)} <span class="tenue g-avance"></span></td></tr>` + inv.items.filter(i => i.categoria_id === cat.id).map(i => {
    const sis = abierto ? i.stock_actual : i.stock_sistema;
    return `<tr class="art" data-a="${i.articulo_id}" data-g="${cat.id}" data-s="${sis}" data-n="${esc(`${i.codigo} ${i.nombre}`)}"><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(sis)} ${esc(i.unidad)}</td>
    <td class="n">${abierto ? inputNum('c', i.conteo, 5).replace('<input', `<input aria-label="Conteo de ${esc(i.nombre)}"`) : (i.conteo === null ? '—' : fCant(i.conteo))}</td><td class="n dif">${i.diferencia ? fCant(i.diferencia) : ''}</td></tr>`;
  }).join('')).join('');
  const m = modal(`Toma #${inv.id} · ${nombreToma(inv)}`, `<div class="filtros inv-filtros"><label>Buscar<input type="search" class="inv-q" placeholder="Nombre o código…"></label>
      <label>Categoría<select class="inv-cat">${opciones(cats, '', 'Todas las categorías')}</select></label>
      ${abierto ? '<label class="check"><input type="checkbox" class="inv-pend"> Solo sin contar</label>' : ''}<span class="tenue inv-avance"></span></div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Artículo</th><th class="n">Stock sistema</th><th class="n">Conteo físico</th><th class="n">Diferencia</th></tr></thead><tbody>${filas}
    <tr class="inv-vacio" hidden><td colspan="5" class="vacio">Ningún artículo coincide con la búsqueda.</td></tr></tbody></table></div>
    <p class="tenue">${abierto ? 'Los artículos sin conteo no se ajustan. Puedes contar por categoría y guardar el avance cuantas veces quieras.' : `Cerrada el ${fFecha(inv.cerrado || '') || '—'}.`}</p><div class="error" hidden></div>
    ${abierto ? '<form><div class="modal-pie"><button type="button" class="btn g">Guardar avance</button>' + (puede('cerrar_inventario') ? '<button class="btn primario">Cerrar y ajustar stock</button>' : '<span class="tenue">Tu perfil no puede cerrar tomas: pide a quien tenga ese permiso que la cierre.</span>') + '</div></form>' : ''}`, true);
  const contado = tr => abierto ? $('.c', tr).value.trim() !== '' : !tr.children[3].textContent.includes('—');
  const filtrar = () => {
    const q = sinTilde($('.inv-q', m.el).value.trim()), cat = $('.inv-cat', m.el).value, pend = $('.inv-pend', m.el)?.checked;
    let visibles = 0;
    $$('tr.art', m.el).forEach(tr => {
      const ver = (!q || sinTilde(tr.dataset.n).includes(q)) && (!cat || tr.dataset.g === cat) && (!pend || !contado(tr));
      tr.style.display = ver ? '' : 'none'; visibles += ver;
    });
    $$('tr.grupo', m.el).forEach(g => { g.style.display = $$(`tr.art[data-g="${g.dataset.g}"]`, m.el).some(tr => tr.style.display !== 'none') ? '' : 'none'; });
    $('.inv-vacio', m.el).hidden = visibles > 0;
  };
  const avance = () => {
    const todas = $$('tr.art', m.el);
    $$('tr.grupo', m.el).forEach(g => { const t = todas.filter(tr => tr.dataset.g === g.dataset.g); $('.g-avance', g).textContent = `· ${t.filter(contado).length} de ${t.length} contados`; });
    $('.inv-avance', m.el).textContent = `${todas.filter(contado).length} de ${todas.length} contados`;
  };
  $('.inv-q', m.el).addEventListener('input', filtrar);
  $('.inv-cat', m.el).addEventListener('change', filtrar);
  $('.inv-pend', m.el)?.addEventListener('change', filtrar);
  avance();
  if (!abierto) return;
  $('tbody', m.el).addEventListener('change', avance);
  const pinta = tr => {
    const n = aNum($('.c', tr).value), d = $('.dif', tr);
    if (n === null || Number.isNaN(n)) { d.textContent = ''; return; }
    const x = n - Number(tr.dataset.s);
    d.textContent = (x > 0 ? '+' : '') + fCant(x);
    d.className = 'n dif ' + (x > 0 ? 'pos' : x < 0 ? 'neg' : '');
  };
  $$('tr.art', m.el).forEach(tr => { pinta(tr); tr.addEventListener('input', () => pinta(tr)); });
  const leer = () => $$('tr.art', m.el).map(tr => {
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
    ${sel('clase', 'Clasificación', [{ id: 'PRODUCTO', nombre: 'Productos' }, { id: 'SUBPRODUCTO', nombre: 'Subproductos' }, { id: 'INSUMO', nombre: 'Insumos' }, { id: 'PUNTO_VENTA', nombre: 'Insumos puntos de venta' }, { id: 'DESECHABLE', nombre: 'Desechables y aseo' }])}
    ${sel('sentido', 'Sentido', [{ id: 'entrada', nombre: 'Entradas' }, { id: 'salida', nombre: 'Salidas' }])}
    ${sel('tipo', 'Movimiento', Object.entries(TIPOS_MOV).map(([id, x]) => ({ id, nombre: x[0] })))}
    ${sel('bodega', 'Bodega', bodegasOp())}
    ${S.usuario.tienda_id ? '' : sel('proveedor_id', 'Proveedor', S.cat.proveedores) + sel('tienda_destino_id', 'Tienda destino', S.cat.tiendas)}
    <button class="btn primario">Filtrar</button></form><div id="th"></div></div>`;
  $('#fh', v).addEventListener('submit', e => { e.preventDefault(); new FormData(e.target).forEach((x, k) => { f[k] = x; }); render(); });
  const filas = await api('GET', '/movimientos' + qs(f));
  tabla($('#th', v), { filas, csv: 'historial', vacio: 'Sin movimientos con estos filtros.', cols: [
    { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Código', v: r => r.codigo }, { t: 'Artículo', v: r => r.nombre },
    { t: 'Clasificación', v: r => claseArticulo({ tipo: r.tipo_articulo, desechable: r.desechable, punto_venta: r.punto_venta }) },
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
      { t: 'Motivo', v: r => r.nombre }, { t: '', h: () => edita ? `<div class="acciones">${accion('editar', 'Editar')}${puede('eliminar_registros') ? accion('borrar', 'Eliminar', 'peligro') : ''}</div>` : '' }] });
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
    { t: '', h: r => r.estado === 'VIGENTE' && edita && puede('anular_mermas') ? `<div class="acciones">${accion('anular', 'Anular', 'peligro')}</div>` : '' }] });
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
let bodegaSel = null, seccionSel = '', clasifSel = '';
Vistas.bodegas = async v => {
  const resumen = await api('GET', '/bodegas/resumen');
  const opts = bodegasOp();
  if (!opts.some(o => o.id === bodegaSel)) bodegaSel = opts[0]?.id ?? null;
  v.innerHTML = cabecera('Bodegas', 'La bodega central se divide en insumos, insumos puntos de venta, desechables y productos. Cada tienda tiene su propia bodega.');
  const central = S.usuario.tienda_id ? [] : await api('GET', '/bodegas/stock' + qs({ bodega: 0 }));
  const kp = v.appendChild(Object.assign(document.createElement('div'), { className: 'kpis' }));
  kp.innerHTML = (S.usuario.tienda_id ? [] : SECCIONES).map(s => {
    const f = central.filter(a => seccionDe(a) === s.id), bajo = f.filter(a => a.cantidad < a.stock_minimo).length;
    return `<div class="kpi ${bajo ? 'alerta' : ''}"><span>${esc(s.nombre)}</span><strong>${fPeso(f.reduce((t, a) => t + a.cantidad * a.costo, 0))}</strong><small>${fNum(f.filter(a => a.cantidad > 0).length)} artículos con stock · ${fNum(bajo)} bajo mínimo</small></div>`;
  }).join('') + resumen.map(t => `<div class="kpi"><span>${esc(t.nombre)}</span><strong>${fPeso(t.valor)}</strong><small>${fNum(t.articulos)} artículos con stock · ${esc(t.comuna)}</small></div>`).join('');
  if (bodegaSel === null) { v.insertAdjacentHTML('beforeend', '<div class="tarjeta vacio">Aún no hay tiendas.</div>'); return; }
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  const todas = bodegaSel === 0 ? central : await api('GET', '/bodegas/stock' + qs({ bodega: bodegaSel }));
  const verClasif = bodegaSel === 0 && seccionSel === 'PUNTO_VENTA';
  const filas = (bodegaSel === 0 && seccionSel ? todas.filter(a => seccionDe(a) === seccionSel) : todas).filter(a => !verClasif || !clasifSel || a.categoria === clasifSel);
  c.innerHTML = `<div class="filtros"><label>Bodega<select id="sb">${opciones(opts, bodegaSel)}</select></label>${bodegaSel === 0 ? `<label>Sección<select id="ss">${opciones(SECCIONES, seccionSel, 'Todas las secciones')}</select></label>` : ''}${verClasif ? `<label>Clasificación<select id="sc">${opciones(S.cat.categorias.filter(x => x.punto_venta).map(x => ({ id: x.nombre, nombre: x.nombre })), clasifSel, 'Todas')}</select></label>` : ''}${bodegaSel && can('bodegas', 2) ? '<button class="btn primario" id="sal">Registrar venta o consumo</button>' : ''}</div><div id="tb"></div>`;
  $('#sb', c).addEventListener('change', e => { bodegaSel = Number(e.target.value); render(); });
  $('#ss', c)?.addEventListener('change', e => { seccionSel = e.target.value; render(); });
  $('#sc', c)?.addEventListener('change', e => { clasifSel = e.target.value; render(); });
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

/* ---------- Actualizar stock (solo perfil Administrador) ---------- */
let stockBodega = 0;
Vistas.stock = async v => {
  const opts = bodegasOp();
  if (!opts.some(o => o.id === stockBodega)) stockBodega = opts[0]?.id ?? 0;
  const filas = await api('GET', '/actualizar-stock' + qs({ bodega: stockBodega }));
  const nombreBodega = opts.find(o => o.id === stockBodega)?.nombre || '';
  v.innerHTML = cabecera('Actualizar stock', 'Escribe el stock real de la bodega elegida. Cada cambio queda en el historial con tu usuario y el motivo.');
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  c.innerHTML = `<div class="filtros"><label>Bodega<select id="ab">${opciones(opts, stockBodega)}</select></label>
    ${stockBodega === 0 ? `<label>Sección<select id="as">${opciones(SECCIONES, '', 'Todas las secciones')}</select></label>` : ''}
    <label>Buscar<input id="aq" autocomplete="off"></label></div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Artículo</th><th>Clasificación</th><th class="n">Stock actual</th><th class="n">Stock nuevo</th><th class="n">Diferencia</th></tr></thead><tbody>
    ${filas.map(r => `<tr data-a="${r.articulo_id}" data-s="${r.cantidad}" data-sec="${seccionDe(r)}" data-t="${esc(`${r.codigo} ${r.nombre}`.toLowerCase())}"><td>${esc(r.codigo)}</td><td>${esc(r.nombre)}</td><td>${esc(claseArticulo(r))}${r.punto_venta ? ' · ' + esc(r.categoria) : ''}</td><td class="n">${fCant(r.cantidad)} ${esc(r.unidad)}</td>
      <td class="n">${inputNum('c', '', 5).replace('<input', `<input aria-label="Stock nuevo de ${esc(r.nombre)}"`)}</td><td class="n dif"></td></tr>`).join('') || '<tr><td colspan="6" class="vacio">Sin artículos.</td></tr>'}
    </tbody></table></div>
    <p class="tenue">Los artículos que dejes en blanco no cambian.</p>
    <label class="campo"><span>Motivo</span><input id="am" maxlength="200" autocomplete="off"></label><div class="error" hidden></div>
    <div class="modal-pie"><button type="button" class="btn primario" id="ag">Guardar cambios</button></div>`;
  const lineas = $$('tbody tr[data-a]', c);
  const leer = () => lineas.flatMap(tr => {
    const n = aNum($('.c', tr).value), s = Number(tr.dataset.s);
    if (Number.isNaN(n) || (n !== null && n < 0)) throw new Error(`El stock nuevo de ${$('td:nth-child(2)', tr).textContent} no es válido.`);
    return n === null || Math.abs(n - s) < 1e-6 ? [] : [{ articulo_id: Number(tr.dataset.a), cantidad: n, esperado: s }];
  });
  const pinta = tr => {
    const n = aNum($('.c', tr).value), d = $('.dif', tr);
    if (n === null || Number.isNaN(n)) { d.textContent = ''; d.className = 'n dif'; return; }
    const x = n - Number(tr.dataset.s);
    d.textContent = (x > 0 ? '+' : '') + fCant(x);
    d.className = 'n dif ' + (x > 0 ? 'pos' : x < 0 ? 'neg' : '');
  };
  const filtrar = () => {
    const q = $('#aq', c).value.trim().toLowerCase(), sec = $('#as', c)?.value || '';
    lineas.forEach(tr => { tr.hidden = (!!sec && tr.dataset.sec !== sec) || !tr.dataset.t.includes(q); });
  };
  lineas.forEach(tr => tr.addEventListener('input', () => pinta(tr)));
  $('#as', c)?.addEventListener('change', filtrar);
  $('#aq', c).addEventListener('input', filtrar);
  $('#ab', c).addEventListener('change', e => {
    if (lineas.some(tr => $('.c', tr).value) && !confirm('Se perderán los cambios sin guardar. ¿Cambiar de bodega?')) { e.target.value = stockBodega; return; }
    stockBodega = Number(e.target.value); render();
  });
  $('#ag', c).addEventListener('click', () => {
    const err = $('.error', c); err.hidden = true;
    try {
      const items = leer(), motivo = $('#am', c).value.trim();
      if (!items.length) throw new Error('No hay cambios de stock para guardar.');
      if (!motivo) throw new Error('Indica el motivo de la actualización.');
      confirmar('Actualizar stock', `Se actualizarán ${items.length} artículo(s) en ${nombreBodega}. El cambio se aplica de inmediato y queda en el historial.`, async () => {
        await api('POST', '/actualizar-stock', { bodega_id: stockBodega, motivo, items }); aviso('Stock actualizado.'); render();
      }, 'Actualizar');
    } catch (x) { err.textContent = x.message; err.hidden = false; }
  });
};

/* ---------- Recetas ---------- */
Vistas.recetas = async v => {
  const filas = await api('GET', '/recetas');
  v.innerHTML = cabecera('Recetas', 'Al producir, se descuentan del stock los insumos y subproductos de la receta. Las cantidades van en la unidad de cada ingrediente.');
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  const edita = can('recetas', 2);
  tabla(c, { filas, csv: 'recetas', vacio: 'Primero crea productos o subproductos.', acciones: {
    editar: r => editarReceta(r, filas), ver: r => verReceta(r),
    borrar: r => confirmar('Eliminar receta', `¿Eliminar la receta de ${r.nombre}? Las producciones anteriores se conservan.`, async () => { await api('DELETE', `/recetas/${r.articulo_id}`); render(); }, 'Eliminar') }, cols: [
    { t: 'Código', v: r => r.codigo }, { t: 'Artículo', v: r => r.nombre }, { t: 'Tipo', v: r => claseArticulo(r) },
    { t: 'Rendimiento', n: 1, v: r => r.rendimiento || 0, h: r => r.tiene_receta ? `${fCant(r.rendimiento)} ${esc(r.unidad)}` : '' },
    { t: 'Ingredientes', n: 1, v: r => r.items?.length || 0, h: r => r.tiene_receta ? fNum(r.items.length) : etq('Sin receta', 'alerta') },
    { t: 'Costo unitario', n: 1, v: r => r.costo_unit || 0, h: r => r.tiene_receta ? fPrecio(r.costo_unit) : '' },
    { t: 'Se puede fabricar', n: 1, v: r => r.max_producible || 0, h: r => r.tiene_receta ? `${fCant(Math.floor(r.max_producible))} ${esc(r.unidad)}` : '' },
    { t: '', h: r => `<div class="acciones">${r.tiene_receta ? accion('ver', 'Ver') : ''}${edita ? accion('editar', r.tiene_receta ? 'Editar' : 'Crear') : ''}${edita && r.tiene_receta && puede('eliminar_registros') ? accion('borrar', 'Eliminar', 'peligro') : ''}</div>` }] });
};
function verReceta(r) {
  modal(`Receta: ${r.nombre}`, `<p><b>Rendimiento:</b> ${fCant(r.rendimiento)} ${esc(r.unidad)} · <b>Costo unitario:</b> ${fPrecio(r.costo_unit)}</p>
    <div class="tabla-marco"><table><thead><tr><th>Ingrediente</th><th class="n">Cantidad</th><th class="n">Costo</th><th class="n">Stock central</th></tr></thead><tbody>${r.items.map(i => `<tr><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)} ${esc(i.unidad)}</td><td class="n">${fPeso(i.cantidad * i.costo_unit)}</td><td class="n">${fCant(i.stock)} ${esc(i.unidad)}</td></tr>`).join('')}</tbody></table></div>
    ${r.instrucciones ? `<h3 style="font-size:14px;margin:14px 0 4px">Preparación</h3><p style="white-space:pre-line;margin:0">${esc(r.instrucciones)}</p>` : ''}`, true);
}
function editarReceta(r, recetas) {
  const m = modal(`Receta: ${r.nombre}`, `<form novalidate><div class="campos"><label class="campo"><span>Rendimiento (${esc(r.unidad)})</span>${inputNum('', r.rendimiento ?? 1, 5).replace('<input', '<input name="rendimiento"')}<small>Cantidad de ${esc(r.nombre)} que resulta de estas cantidades.</small></label></div>
    <h3 style="font-size:14px;margin:14px 0 6px">Ingredientes</h3><p class="tenue" style="margin:0 0 6px">Escribe la cantidad en la unidad del ingrediente: por ejemplo, 0,250 kg para 250 g. El costo se calcula con el último precio del insumo.</p><div id="lin"></div><div class="totales" id="tot"></div>
    <label class="campo" style="margin-top:12px"><span>Preparación</span><textarea name="instrucciones" rows="4">${esc(r.instrucciones || '')}</textarea></label><div class="error" hidden></div>
    <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Guardar receta</button></div></form>`, true);
  $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
  const f = $('form', m.el);
  const costoSub = Object.fromEntries((recetas || []).map(x => [x.articulo_id, x.costo_unit || 0]));
  let ed = null;
  const totales = () => {
    const total = ed ? ed.neto() : 0, rend = aNum(f.rendimiento.value) || 0;
    $('#tot', m.el).innerHTML = `<div><span>Costo de los ingredientes</span><span>${fPrecio(total)}</span></div><div class="total"><span>Costo por ${esc(r.unidad)}</span><span>${rend > 0 ? fPrecio(total / rend) : '—'}</span></div>`;
  };
  const ingredientes = S.cat.articulos.filter(a => a.id !== r.articulo_id && (a.tipo === 'SUBPRODUCTO' || (a.tipo === 'INSUMO' && !a.desechable)));
  const grupos = [{ nombre: 'Subproductos (rellenos y bases)', filtro: a => a.tipo === 'SUBPRODUCTO' },
    ...[...new Set(ingredientes.filter(a => a.tipo === 'INSUMO').map(a => a.categoria))].sort((x, y) => x.localeCompare(y)).map(cat => ({ nombre: `Insumos · ${cat}`, filtro: a => a.tipo === 'INSUMO' && a.categoria === cat }))];
  ed = editorLineas($('#lin', m.el), { articulos: ingredientes, valores: r.items, grupos,
    precio: 'Precio', subtotal: 'Costo', porUnidad: true, fSubtotal: fPrecio, alCambiar: totales,
    precioDe: a => a.tipo === 'SUBPRODUCTO' ? costoSub[a.id] || 0 : a.precio || 0 });
  f.rendimiento.addEventListener('input', totales);
  totales();
  conEnvio(f, m, async () => {
    await api('PUT', `/recetas/${r.articulo_id}`, { rendimiento: aNum(f.rendimiento.value), instrucciones: f.instrucciones.value, items: ed.leer() });
    aviso('Receta guardada.'); render();
  });
}

/* ---------- Producción ---------- */
function imprimirProduccion(d) {
  const resumen = {};
  d.ordenes.forEach(o => { const k = o.codigo; resumen[k] = resumen[k] || { codigo: o.codigo, nombre: o.nombre, unidad: o.unidad, cantidad: 0, costo: 0, ordenes: 0 }; resumen[k].cantidad += o.cantidad; resumen[k].costo += o.costo_total; resumen[k].ordenes += 1; });
  const periodo = d.desde === d.hasta ? fFecha(d.desde) : `${fFecha(d.desde)} al ${fFecha(d.hasta)}`;
  const orden = o => `<div class="orden"><h3>Orden N° ${String(o.id).padStart(6, '0')} · ${esc(o.codigo)} ${esc(o.nombre)}</h3>
    <div class="guia-datos"><div><b>Fecha:</b> ${fFecha(o.fecha)}</div><div><b>Cantidad:</b> ${fCant(o.cantidad)} ${esc(o.unidad)}</div><div><b>Costo total:</b> ${fPeso(o.costo_total)}</div><div><b>Registrada por:</b> ${esc(o.usuario) || '—'}</div>${o.obs ? `<div><b>Observación:</b> ${esc(o.obs)}</div>` : ''}</div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Ingrediente</th><th class="n">Cantidad usada</th><th class="n">Costo</th></tr></thead><tbody>${o.items.map(i => `<tr><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)} ${esc(i.unidad)}</td><td class="n">${fPeso(i.cantidad * i.costo_unit)}</td></tr>`).join('') || '<tr><td colspan="4" class="vacio">Sin ingredientes registrados.</td></tr>'}</tbody></table></div></div>`;
  const m = modal('Órdenes de producción', `<div class="guia-cab"><div class="guia-marca"><img src="${esc(logo())}" alt=""><div><strong>Nata &amp; Schlott</strong><span class="tenue">Sistema de producción y logística</span></div></div>
    <div class="guia-num"><span>Órdenes de producción</span><strong>${periodo}</strong></div></div>
    ${d.ordenes.length ? `<h3 class="sub-imp">Resumen del período</h3><div class="tabla-marco"><table><thead><tr><th>Código</th><th>Artículo</th><th class="n">Órdenes</th><th class="n">Cantidad</th><th class="n">Costo total</th></tr></thead><tbody>${Object.values(resumen).map(r => `<tr><td>${esc(r.codigo)}</td><td>${esc(r.nombre)}</td><td class="n">${fNum(r.ordenes)}</td><td class="n">${fCant(r.cantidad)} ${esc(r.unidad)}</td><td class="n">${fPeso(r.costo)}</td></tr>`).join('')}</tbody></table></div>
    <h3 class="sub-imp">Detalle por orden</h3>${d.ordenes.map(orden).join('')}` : '<p class="vacio">No hay producciones vigentes en estas fechas.</p>'}
    <div class="firmas"><div>Responsable de producción</div><div>Revisado por</div></div><p class="legal">Documento de control interno. No incluye producciones anuladas.</p>
    <div class="modal-pie no-imprimir"><button type="button" class="btn primario imprimir">Imprimir</button></div>`, true);
  $('.imprimir', m.el).addEventListener('click', () => print());
}
Vistas.produccion = async v => {
  const filas = await api('GET', '/produccion');
  v.innerHTML = cabecera('Producción', 'Fabrica productos y subproductos según su receta.', '<button class="btn" id="imp">Imprimir por fechas</button>' + (can('produccion', 2) ? '<button class="btn primario" id="n">Registrar producción</button>' : ''));
  $('#imp', v).addEventListener('click', () => formulario('Imprimir órdenes de producción', [
    { k: 'desde', t: 'Desde', tipo: 'date', def: hoy() }, { k: 'hasta', t: 'Hasta', tipo: 'date', def: hoy() }], {}, async d => {
    if (!d.desde || !d.hasta) throw new Error('Indica ambas fechas.');
    imprimirProduccion(await api('GET', '/produccion/impresion' + qs(d)));
  }, 'Ver para imprimir'));
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  tabla(c, { filas, csv: 'produccion', vacio: 'Aún no hay producciones.', acciones: {
    anular: r => confirmar('Anular producción', `Se quitarán ${fCant(r.cantidad)} ${r.unidad} de ${r.nombre} y se devolverán sus ingredientes al stock.`, async () => { await api('POST', `/produccion/${r.id}/anular`, {}); aviso('Producción anulada.'); render(); }, 'Anular producción') }, cols: [
    { t: 'N°', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Código', v: r => r.codigo }, { t: 'Artículo', v: r => r.nombre }, { t: 'Tipo', v: r => claseArticulo(r) },
    { t: 'Cantidad', n: 1, v: r => r.cantidad, h: r => `${fCant(r.cantidad)} ${esc(r.unidad)}` }, { t: 'Costo total', n: 1, v: r => r.costo_total, h: r => fPeso(r.costo_total) },
    { t: 'Costo unitario', n: 1, v: r => r.costo_total / r.cantidad, h: r => fPrecio(r.costo_total / r.cantidad) }, { t: 'Usuario', v: r => r.usuario },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Vigente', 'bien') },
    { t: '', h: r => r.estado === 'VIGENTE' && can('produccion', 2) && puede('anular_produccion') ? `<div class="acciones">${accion('anular', 'Anular', 'peligro')}</div>` : '' }] });
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
let tabDespachos = 'guias';
const SALIDAS = {
  DEVOLUCION_TIENDA: { tab: 'Devoluciones de tiendas', titulo: 'Devoluciones de tiendas', nota: 'Desechables y aseo que una tienda devuelve: baja el stock de la tienda y sube el de la bodega central.', nuevo: 'Nueva devolución', doc: 'Devolución de tienda', hecho: 'Devolución registrada: el stock volvió a la bodega central.' },
  CONSUMO_CENTRAL: { tab: 'Consumo en central', titulo: 'Consumo en bodega central', nota: 'Desechables y aseo usados en la bodega central o en producción: baja el stock de la central.', nuevo: 'Registrar consumo', doc: 'Consumo interno', hecho: 'Consumo registrado: el stock de la bodega central disminuyó.' },
};
const tabsDespachos = () => pestanas([['guias', 'Guías a tiendas'], ...Object.entries(SALIDAS).filter(([k]) => k === 'DEVOLUCION_TIENDA' || !S.usuario.tienda_id).map(([k, x]) => [k, x.tab])], tabDespachos, k => { tabDespachos = k; render(); });
async function vistaSalidas(v, tipo) {
  const cfg = SALIDAS[tipo], crea = can('despachos', 2), filas = await api('GET', '/salidas-internas' + qs({ tipo }));
  const anula = crea && !S.usuario.tienda_id && puede('anular_salidas'), esDev = tipo === 'DEVOLUCION_TIENDA';
  v.innerHTML = cabecera(cfg.titulo, cfg.nota, crea ? `<button class="btn primario" id="n">${esc(cfg.nuevo)}</button>` : '');
  v.append(tabsDespachos());
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  tabla(c, { filas, csv: tipo.toLowerCase(), vacio: 'Aún no hay registros.', acciones: { ver: r => verSalida(r.id),
    anular: r => confirmar(`Anular ${cfg.doc.toLowerCase()}`, esDev ? `Los artículos del documento #${r.id} volverán a la tienda. Requiere que la bodega central aún tenga ese stock.` : `Los artículos del documento #${r.id} volverán a la bodega central.`, async () => { await api('POST', `/salidas-internas/${r.id}/anular`, {}); aviso('Documento anulado.'); render(); }, 'Anular') }, cols: [
    { t: 'N°', v: r => r.id }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, ...(esDev ? [{ t: 'Tienda', v: r => r.origen }] : []), { t: 'Motivo', v: r => r.motivo }, { t: 'Líneas', n: 1, v: r => r.lineas },
    { t: 'Valor a costo', n: 1, v: r => r.valor, h: r => fPeso(r.valor) }, { t: 'Registrado por', v: r => r.usuario },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulado', 'mal') : etq('Vigente', 'bien') },
    { t: '', h: r => `<div class="acciones">${accion('ver', 'Ver')}${r.estado === 'VIGENTE' && anula ? accion('anular', 'Anular', 'peligro') : ''}</div>` }] });
  $('#n', v)?.addEventListener('click', () => {
    const tiendas = bodegasOp(false);
    const m = modal(cfg.nuevo, `<form novalidate><div class="campos">${esDev ? `<label class="campo"><span>Tienda que devuelve</span><select name="tienda_id">${opciones(tiendas, S.usuario.tienda_id || '', S.usuario.tienda_id ? undefined : 'Selecciona…')}</select></label>` : ''}
      <label class="campo"><span>Fecha</span><input type="date" name="fecha" value="${hoy()}"></label><label class="campo todo"><span>Motivo</span><input name="motivo" maxlength="200"></label></div>
      <h3 style="font-size:14px;margin:14px 0 6px">Desechables y aseo</h3><div id="lin"></div><div class="error" hidden></div>
      <div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">${esc(cfg.nuevo)}</button></div></form>`, true);
    $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
    const f = $('form', m.el);
    let ed = null;
    const cargar = async () => {
      const bodega = esDev ? f.tienda_id.value : 0;
      ed = null; $('#lin', m.el).innerHTML = '<p class="tenue">Elige la tienda para ver su stock.</p>';
      if (bodega === '') return;
      const st = await api('GET', '/salidas-internas/stock' + qs({ bodega }));
      ed = editorLineas($('#lin', m.el), { articulos: S.cat.articulos.filter(a => a.desechable && !a.punto_venta), stock: Object.fromEntries(st.map(a => [a.articulo_id, a.cantidad])) });
    };
    if (esDev) f.tienda_id.addEventListener('change', () => cargar().catch(x => aviso(x.message, 1)));
    cargar().catch(x => aviso(x.message, 1));
    conEnvio(f, m, async () => {
      if (!ed) throw new Error('Selecciona la tienda que devuelve.');
      const r = await api('POST', '/salidas-internas', { tipo, tienda_id: esDev ? f.tienda_id.value : null, fecha: f.fecha.value, motivo: f.motivo.value, items: ed.leer() });
      aviso(cfg.hecho); render(); verSalida(r.id);
    });
  });
}
async function verSalida(id) {
  const s = await api('GET', `/salidas-internas/${id}`), cfg = SALIDAS[s.tipo], num = String(s.id).padStart(6, '0'), esDev = s.tipo === 'DEVOLUCION_TIENDA';
  const m = modal(`${cfg.doc} ${num}`, `<div class="guia-cab"><div class="guia-marca"><img src="${esc(logo())}" alt=""><div><strong>Nata &amp; Schlott</strong><span class="tenue">Sistema de producción y logística</span></div></div>
    <div class="guia-num"><span>${esc(cfg.doc)}</span><strong>N° ${num}</strong>${s.estado === 'ANULADO' ? etq('ANULADO', 'mal') : ''}</div></div>
    <div class="guia-datos"><div><b>Fecha:</b> ${fFecha(s.fecha)}</div><div><b>Origen:</b> ${esc(s.origen)}</div><div><b>Destino:</b> ${esDev ? 'Bodega central' : 'Consumo interno'}</div><div><b>Motivo:</b> ${esc(s.motivo)}</div><div><b>Registrado por:</b> ${esc(s.usuario)}</div></div>
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Descripción</th><th class="n">Cantidad</th><th>Unidad</th><th class="n">Costo</th><th class="n">Subtotal</th></tr></thead><tbody>${s.items.map(i => `<tr><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)}</td><td>${esc(i.unidad)}</td><td class="n">${fPrecio(i.costo_unit)}</td><td class="n">${fPeso(i.cantidad * i.costo_unit)}</td></tr>`).join('')}</tbody></table></div>
    <div class="firmas"><div>Entrega</div><div>Recibe conforme</div></div><p class="legal">Documento de control interno.</p>
    <div class="modal-pie no-imprimir"><button type="button" class="btn primario imprimir">Imprimir</button></div>`, true);
  $('.imprimir', m.el).addEventListener('click', () => print());
}
Vistas.despachos = async v => {
  if (SALIDAS[tabDespachos]) return vistaSalidas(v, tabDespachos);
  const crea = can('despachos', 2) && !S.usuario.tienda_id;
  const filas = await api('GET', '/despachos');
  v.innerHTML = cabecera('Despachos a tiendas', 'Cada guía descuenta de la bodega central y aumenta el stock de la bodega de la tienda.', crea ? '<button class="btn primario" id="n">Nueva guía</button>' : '');
  v.append(tabsDespachos());
  const c = v.appendChild(Object.assign(document.createElement('div'), { className: 'tarjeta' }));
  const fudoEnvio = async (r, ruta, cuerpo, ok) => {
    const x = await api('POST', `/despachos/${r.id}/fudo${ruta}`, cuerpo);
    render();
    if (!x.ok) throw new Error(x.error);
    if (x.pago_error) return aviso(`${ok} Pero el pago no quedó registrado: ${x.pago_error} Puedes reintentarlo desde el detalle de la guía.`, 1);
    if (x.stock_error) return aviso(`${ok} Pero el stock en Fudo quedó con problemas: ${x.stock_error}`, 1);
    if (x.manual) return aviso(`${ok} Ahora carga el detalle de insumos del gasto GD-${nGuia(r)} en Fudo.`);
    aviso(ok + (x.stock === 'ENVIADO' ? ' Stock sumado en Fudo.' : x.stock === 'REVERTIDO' ? ' Stock restado en Fudo.' : ''));
  };
  const nGuia = r => String(r.id).padStart(6, '0');
  const estadoStockFudo = r => {
    const e = r.fudo_stock_estado;
    if (r.fudo_stock_manual && e === 'ENVIADO') return `<span title="Carga el detalle de insumos del gasto GD-${nGuia(r)} en Fudo">${etq(r.estado === 'ANULADO' ? 'Manual (guía anulada)' : 'Cargar a mano en Fudo', 'alerta')}</span>`;
    if (r.fudo_stock_manual && e === 'REVERTIDO') return etq('Manual anulado');
    if (e === 'ENVIADO') return etq(r.estado === 'ANULADO' ? 'Sumado (guía anulada)' : 'Sumado', r.estado === 'ANULADO' ? 'alerta' : 'bien');
    if (e === 'REVERTIDO') return etq('Restado');
    if (e === 'ENVIANDO' || e === 'REVISAR') return etq('Revisar', 'alerta');
    if (e === 'ERROR') return `<span title="${esc(r.fudo_stock_error)}">${etq('Con error', 'mal')}</span>`;
    return r.fudo_stock_lineas && r.estado === 'VIGENTE' ? etq('Sin sumar') : '—';
  };
  const accionStockFudo = r => {
    const e = r.fudo_stock_estado;
    if (['ENVIANDO', 'REVISAR'].includes(e)) return puede(r.estado === 'VIGENTE' ? 'enviar_fudo' : 'anular_fudo') ? accion('stockrev', 'Revisar stock Fudo') : '';
    if (r.estado === 'VIGENTE' && r.fudo_stock_lineas && (!e || e === 'ERROR')) return puede('enviar_fudo') ? accion('stock', e === 'ERROR' ? 'Reintentar stock Fudo' : 'Stock a Fudo') : '';
    if (!puede('anular_fudo')) return '';
    if (r.estado === 'ANULADO' && r.fudo_stock_manual && e === 'ENVIADO' && r.fudo_estado !== 'ENVIADO') return accion('stockdes', 'Quitar carga manual', 'peligro');
    if (r.estado === 'ANULADO' && !r.fudo_stock_manual && (e === 'ENVIADO' || e === 'ERROR')) return accion('stockdes', 'Restar stock Fudo', 'peligro');
    return '';
  };
  const estadoFudo = r => r.fudo_estado === 'ENVIADO' ? etq(r.estado === 'ANULADO' ? 'Gasto vigente' : `Gasto #${r.fudo_gasto_id}`, r.estado === 'ANULADO' ? 'alerta' : 'bien') +
      (r.estado === 'ANULADO' ? '' : r.fudo_pago && r.fudo_pago !== 'REVISAR' ? ' ' + etq('Pagado', 'bien') : ' ' + etq(r.fudo_pago === 'REVISAR' ? 'Pago por revisar' : 'Sin pago', 'alerta')) : r.fudo_estado === 'ANULADO' ? etq('Gasto anulado') : ['ENVIANDO', 'REVISAR'].includes(r.fudo_estado) ? etq('Revisar', 'alerta') : r.estado === 'VIGENTE' ? etq('Sin enviar') : '—';
  tabla(c, { filas, csv: 'despachos', vacio: 'Aún no hay guías.', acciones: { ver: r => verGuia(r.id),
    fudo: r => confirmar('Enviar a Fudo', `Se creará un gasto del proveedor Nata & Schlott en la cuenta Fudo de ${r.tienda} por la guía ${nGuia(r)}${r.fudo_stock_lineas ? `, y se sumará el stock de sus ${r.fudo_stock_lineas} insumo(s) equivalentes` : ''}.`, () => fudoEnvio(r, '', {}, 'Gasto creado en Fudo.'), 'Enviar a Fudo'),
    fudorev: r => confirmar('Reenviar a Fudo', `No se sabe si el gasto de la guía ${nGuia(r)} llegó a Fudo. Busca el comprobante GD-${nGuia(r)} en Fudo: reenvía solo si NO está, para no duplicarlo.`, () => fudoEnvio(r, '', { confirmar_reenvio: true }, 'Gasto creado en Fudo.'), 'No está: reenviar'),
    fudoanula: r => confirmar('Anular gasto en Fudo', `Se anulará en Fudo el gasto #${r.fudo_gasto_id} de la guía ${nGuia(r)}${r.fudo_stock_estado === 'ENVIADO' ? ' y se restará el stock que se había sumado' : ''}.`, () => fudoEnvio(r, '/anular', {}, 'Gasto anulado en Fudo.'), 'Anular gasto'),
    stock: r => confirmar('Sumar stock en Fudo', `Se sumarán en Fudo de ${r.tienda} las cantidades de la guía ${nGuia(r)} para sus ${r.fudo_stock_lineas} insumo(s) equivalentes.`, () => fudoEnvio(r, '-stock', {}, 'Stock sumado en Fudo.'), 'Sumar stock'),
    stockrev: r => confirmar('Revisar stock en Fudo', `No se sabe si parte del stock de la guía ${nGuia(r)} se aplicó en Fudo (${r.fudo_stock_error}). Revisa esos insumos en Fudo: continúa solo si NO se aplicó, para no duplicarlo.`,
      () => fudoEnvio(r, r.estado === 'VIGENTE' ? '-stock' : '-stock/revertir', { confirmar_reenvio: true }, 'Listo.'), 'No se aplicó: continuar'),
    stockdes: r => r.fudo_stock_manual
      ? confirmar('Quitar carga manual', `La guía ${nGuia(r)} está anulada: el sistema dejará de contar sus cantidades como cargadas en Fudo. Si ya cargaste ese detalle en Fudo, quítalo allá.`, () => fudoEnvio(r, '-stock/revertir', {}, 'Carga manual quitada.'), 'Quitar')
      : confirmar('Restar stock en Fudo', `La guía ${nGuia(r)} está anulada: se restará en Fudo el stock que se le había sumado.`, () => fudoEnvio(r, '-stock/revertir', {}, 'Stock restado en Fudo.'), 'Restar stock'),
    anular: r => confirmar('Anular guía', `Se devolverá a la bodega central lo despachado en la guía ${String(r.id).padStart(6, '0')}. Requiere que la tienda aún tenga ese stock.`, async () => { await api('POST', `/despachos/${r.id}/anular`, {}); aviso('Guía anulada.'); render(); }, 'Anular guía') }, cols: [
    { t: 'Guía', v: r => String(r.id).padStart(6, '0') }, { t: 'Fecha', v: r => r.fecha, h: r => fFecha(r.fecha) }, { t: 'Tienda', v: r => r.tienda }, { t: 'Líneas', n: 1, v: r => r.lineas },
    { t: 'Neto', n: 1, v: r => r.neto, h: r => fPeso(r.neto) }, { t: 'Total', n: 1, v: r => r.total, h: r => fPeso(r.total) }, { t: 'Transportista', v: r => r.transportista },
    { t: 'Estado', v: r => r.estado, h: r => r.estado === 'ANULADO' ? etq('Anulada', 'mal') : etq('Emitida', 'bien') },
    ...(S.usuario.tienda_id ? [] : [{ t: 'Fudo', v: r => r.fudo_estado, h: estadoFudo }, { t: 'Stock Fudo', v: r => r.fudo_stock_estado, h: estadoStockFudo }]),
    { t: '', h: r => `<div class="acciones">${accion('ver', 'Ver guía')}${crea ? accionStockFudo(r) : ''}${crea && puede('enviar_fudo') && r.estado === 'VIGENTE' && !r.fudo_estado ? accion('fudo', 'Enviar a Fudo') : ''}${crea && puede('enviar_fudo') && r.estado === 'VIGENTE' && ['ENVIANDO', 'REVISAR'].includes(r.fudo_estado) ? accion('fudorev', 'Revisar Fudo') : ''}${crea && puede('anular_fudo') && r.estado === 'ANULADO' && r.fudo_estado === 'ENVIADO' ? accion('fudoanula', 'Anular en Fudo', 'peligro') : ''}${r.estado === 'VIGENTE' && crea && puede('anular_despachos') ? accion('anular', 'Anular', 'peligro') : ''}</div>` }] });
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
    ed = editorLineas($('#lin', m.el), { articulos: S.cat.articulos.filter(a => a.tipo === 'PRODUCTO' || a.desechable), stock, precio: 'Precio', alCambiar: tot,
      grupos: [...new Set(S.cat.articulos.filter(a => a.tipo === 'PRODUCTO' || a.desechable).sort((x, y) => (x.desechable - y.desechable) || (x.punto_venta - y.punto_venta) || x.categoria.localeCompare(y.categoria)).map(grupoDespacho))].map(nombre => ({ nombre, filtro: a => grupoDespacho(a) === nombre })) });
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
    <div class="tabla-marco"><table><thead><tr><th>Código</th><th>Descripción</th><th class="n">Cantidad</th><th>Unidad</th><th class="n">Precio</th><th class="n">Subtotal</th></tr></thead><tbody>${[...new Set(g.items.map(grupoDespacho))].map(titulo => { const its = g.items.filter(i => grupoDespacho(i) === titulo); return `<tr><td colspan="6"><b>${esc(titulo)}</b></td></tr>` + its.map(i => `<tr><td>${esc(i.codigo)}</td><td>${esc(i.nombre)}</td><td class="n">${fCant(i.cantidad)}</td><td>${esc(i.unidad)}</td><td class="n">${fPrecio(i.precio)}</td><td class="n">${fPeso(i.cantidad * i.precio)}</td></tr>`).join(''); }).join('')}</tbody></table></div>
    <div class="totales"><div><span>Neto</span><span>${fPeso(g.neto)}</span></div><div><span>IVA ${fNum(g.iva_pct, 0, 2)}%</span><span>${fPeso(g.iva)}</span></div><div class="total"><span>Total</span><span>${fPeso(g.total)}</span></div></div>
    ${g.obs ? `<p><b>Observación:</b> ${esc(g.obs)}</p>` : ''}<div class="firmas"><div>Entrega</div><div>Recibe conforme</div></div>
    <p class="legal">Documento de control interno. No reemplaza la guía de despacho electrónica exigida por el SII.</p>
    <div class="modal-pie no-imprimir">${botonesGuiaFudo(g)}<button type="button" class="btn primario imprimir">Imprimir</button></div>`, true);
  $('.imprimir', m.el).addEventListener('click', () => print());
  const rehacer = () => { m.cerrar(); render(); verGuia(id); };
  const llamar = async (ruta, cuerpo) => {
    const x = await api('POST', `/despachos/${id}${ruta}`, cuerpo || {});
    if (x.ok === false) throw new Error(x.error);
    return x;
  };
  const resultadoStock = x => (x.pago === 'PAGADO' ? ' Quedó Pagado.' : x.pago_error ? ` Pero el pago no quedó registrado: ${x.pago_error}` : '') + (x.stock_error ? ` Pero el stock en Fudo quedó con problemas: ${x.stock_error}` : x.manual ? ' Carga el detalle de insumos del gasto en Fudo.'
    : x.stock === 'ENVIADO' ? ' Stock de Fudo actualizado.' : x.stock === 'REVERTIDO' ? ' Stock descontado en Fudo.' : '');
  $('.g-fudo', m.el)?.addEventListener('click', () => confirmar('Enviar a Fudo',
    `${['REVISAR', 'ENVIANDO'].includes(g.fudo_estado) ? `No se sabe si el envío anterior llegó: busca el gasto GD-${num} en Fudo y continúa solo si NO está, para no duplicarlo. ` : ''}Se creará en Fudo de ${g.tienda} el gasto de la guía N° ${num} (proveedor Nata & Schlott, pagado en Efectivo)${g.fudo_stock_lineas ? ` y se sumará el stock de sus ${g.fudo_stock_lineas} insumo(s) equivalentes` : ''}.`, async () => {
      const x = await llamar('/fudo', g.fudo_estado === 'REVISAR' || g.fudo_estado === 'ENVIANDO' ? { confirmar_reenvio: true } : {});
      aviso('Gasto creado en Fudo.' + resultadoStock(x), !!(x.stock_error || x.pago_error)); rehacer();
    }, 'Enviar a Fudo'));
  $('.g-pago', m.el)?.addEventListener('click', () => confirmar('Registrar pago en Fudo',
    `${g.fudo_pago === 'REVISAR' ? `No se sabe si el pago anterior llegó: revisa el gasto GD-${num} en Fudo y continúa solo si NO está pagado, para no duplicarlo. ` : ''}Se registrará en Fudo el pago en Efectivo del gasto de la guía N° ${num}, con la fecha de la guía.`, async () => {
      await llamar('/fudo/pago', g.fudo_pago === 'REVISAR' ? { confirmar_reenvio: true } : {});
      aviso('Gasto marcado como Pagado en Fudo.'); rehacer();
    }, 'Registrar pago'));
  $('.g-stock', m.el)?.addEventListener('click', () => confirmar('Actualizar stock en Fudo', `Se sumará en Fudo el stock pendiente de la guía N° ${num}.`, async () => {
    const x = await llamar('-stock', ['REVISAR', 'ENVIANDO'].includes(g.fudo_stock_estado) ? { confirmar_reenvio: true } : {});
    aviso(x.error ? `Stock con problemas: ${x.error}` : 'Stock actualizado en Fudo.', !!x.error); rehacer();
  }, 'Actualizar stock'));
  $('.g-anular', m.el)?.addEventListener('click', () => confirmar('Anular guía',
    `Se devolverá a la bodega central lo despachado en la guía N° ${num} (requiere que la tienda aún tenga ese stock).${g.fudo_estado === 'ENVIADO' ? ' En Fudo se anulará el gasto y se descontará del stock lo que sumó la guía.' : g.fudo_stock_estado === 'ENVIADO' ? ' En Fudo se descontará del stock lo que sumó la guía.' : ''}`, async () => {
      await api('POST', `/despachos/${id}/anular`, {});
      let msg = 'Guía anulada.';
      try {
        if (g.fudo_estado === 'ENVIADO') msg += ' Gasto anulado en Fudo.' + resultadoStock(await llamar('/fudo/anular'));
        else if (['ENVIADO', 'ERROR'].includes(g.fudo_stock_estado)) msg += resultadoStock({ ...(await llamar('-stock/revertir')), stock: 'REVERTIDO' });
      } catch (x) { msg += ` Pero en Fudo no se pudo completar: ${x.message} Reinténtalo desde la lista de guías.`; aviso(msg, 1); return rehacer(); }
      aviso(msg, msg.includes('problemas')); rehacer();
    }, 'Anular guía'));
}
function botonesGuiaFudo(g) {
  if (!can('despachos', 2) || S.usuario.tienda_id || g.estado !== 'VIGENTE') return '';
  let b = '';
  if (!puede('enviar_fudo')) { /* sin permiso: no se ofrece enviar */ }
  else if (g.fudo_lista && g.fudo_estado !== 'ENVIADO' && g.fudo_estado !== 'ANULADO')
    b += `<button type="button" class="btn g-fudo">${['REVISAR', 'ENVIANDO'].includes(g.fudo_estado) ? 'Reintentar envío a Fudo' : 'Enviar a Fudo'}</button>`;
  else {
    if (g.fudo_estado === 'ENVIADO' && ['', 'REVISAR'].includes(g.fudo_pago || ''))
      b += '<button type="button" class="btn g-pago">Registrar pago en Fudo</button>';
    if (g.fudo_estado === 'ENVIADO' && g.fudo_stock_lineas && ['', 'ERROR', 'REVISAR', 'ENVIANDO'].includes(g.fudo_stock_estado))
      b += '<button type="button" class="btn g-stock">Actualizar stock en Fudo</button>';
  }
  // Anular una guía ya enviada también deshace en Fudo: requiere ambos permisos
  const enFudo = g.fudo_estado === 'ENVIADO' || g.fudo_stock_estado === 'ENVIADO';
  if (puede('anular_despachos') && (!enFudo || puede('anular_fudo'))) b += '<button type="button" class="btn peligro g-anular">Anular guía</button>';
  return b;
}

/* ---------- Reportes ---------- */
let tabRep = 'rendimiento', rango = { desde: haceDias(90), hasta: hoy() }, insumoSel = '';
const stockRep = { tipo: '', ver: 'cantidad', central: true, conStock: false, q: '' };
Vistas.reportes = async v => {
  const tabs = [['rendimiento', 'Rendimiento de producción'], ['precios', 'Precios de insumos'], ['margenes', 'Márgenes'], ['cobertura', 'Cobertura y reposición'], ['stock', 'Stock por tienda'], ['compras', 'Compras'], ['despachos', 'Despachos'], ['mermas', 'Mermas']];
  v.innerHTML = cabecera('Reportes de gestión', 'Indicadores para decidir qué producir, comprar y corregir.');
  v.append(pestanas(tabs, tabRep, k => { tabRep = k; render(); }));
  if (tabRep !== 'margenes' && tabRep !== 'stock') {
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
    tarjeta(`<h2>Margen sobre el precio de venta</h2><p class="nota">Costo según receta y el último precio de cada insumo. Considera el precio del producto como neto de IVA.</p>${barras(d.filas, r => r.nombre, r => Math.max(r.margen_pct, 0), fPct)}`);
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
  async stock(z, tarjeta, kpis) {
    const d = await api('GET', '/reportes/stock-tiendas' + qs({ tipo: stockRep.tipo }));
    const bod = d.bodegas.filter(b => stockRep.central || b.id !== 0);
    const cant = (r, b) => r.stock[String(b.id)] || 0;
    const valorFila = (r, b) => cant(r, b) * r.costo;
    const enValor = stockRep.ver === 'valor';
    const celdaV = (r, b) => enValor ? valorFila(r, b) : cant(r, b);
    const total = r => bod.reduce((s, b) => s + celdaV(r, b), 0);
    const fmt = x => enValor ? fPeso(x) : fCant(x);
    const tiendas = d.bodegas.filter(b => b.id !== 0);
    const valTiendas = d.filas.reduce((s, r) => s + tiendas.reduce((t, b) => t + valorFila(r, b), 0), 0);
    kpis([['Artículos', fNum(d.filas.length), 'activos del tipo elegido'], ['Con stock en tiendas', fNum(d.filas.filter(r => tiendas.some(b => cant(r, b))).length)],
      ['Valor en tiendas', fPeso(valTiendas), 'a costo'], ['Valor en bodega central', fPeso(d.filas.reduce((s, r) => s + valorFila(r, { id: 0 }), 0)), 'a costo']]);
    const c = tarjeta(`<h2>Stock por tienda</h2><p class="nota">Stock actual del sistema por bodega. Las filas se agrupan por categoría.${enValor ? ' Valor = cantidad × costo actual del artículo.' : ''}</p>
      <div class="filtros"><label>Tipo<select id="st-tipo">${[['', 'Todos'], ['PRODUCTO', 'Productos'], ['SUBPRODUCTO', 'Subproductos'], ['INSUMO', 'Insumos']].map(([k, t]) => `<option value="${k}" ${k === stockRep.tipo ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      <label>Mostrar<select id="st-ver"><option value="cantidad">Cantidades</option><option value="valor" ${enValor ? 'selected' : ''}>Valor a costo</option></select></label>
      <label class="check"><input type="checkbox" id="st-central" ${stockRep.central ? 'checked' : ''}> Incluir bodega central</label>
      <label class="check"><input type="checkbox" id="st-con" ${stockRep.conStock ? 'checked' : ''}> Solo con stock</label></div>
      <div class="tabla-barra"><input type="search" class="buscar" placeholder="Buscar artículo o categoría…" value="${esc(stockRep.q)}"><button type="button" class="btn mini csv">Descargar CSV</button></div>
      <div class="tabla-marco stock-tiendas"></div><div class="conteo"></div>`);
    const filtradas = () => {
      const t = stockRep.q.trim().toLowerCase();
      return d.filas.filter(r => (!stockRep.conStock || bod.some(b => cant(r, b))) && (!t || `${r.codigo} ${r.nombre} ${r.categoria}`.toLowerCase().includes(t)));
    };
    const dibujar = () => {
      const f = filtradas(), ncol = 3 + bod.length + 1;
      const grupos = [];
      for (const r of f) { if (!grupos.length || grupos.at(-1).cat !== r.categoria) grupos.push({ cat: r.categoria, filas: [] }); grupos.at(-1).filas.push(r); }
      const celda = (x, cls = '') => `<td class="n ${cls} ${x ? '' : 'cero'}">${x ? fmt(x) : '—'}</td>`;
      const cuerpo = grupos.map(g => {
        const cab = enValor
          ? `<tr class="grupo"><td colspan="3">${esc(g.cat)} <span class="tenue">(${g.filas.length})</span></td>${bod.map(b => `<td class="n">${fPeso(g.filas.reduce((s, r) => s + valorFila(r, b), 0))}</td>`).join('')}<td class="n">${fPeso(g.filas.reduce((s, r) => s + total(r), 0))}</td></tr>`
          : `<tr class="grupo"><td colspan="${ncol}">${esc(g.cat)} <span class="tenue">(${g.filas.length})</span></td></tr>`;
        return cab + g.filas.map(r => `<tr><td>${esc(r.codigo)}</td><td>${esc(r.nombre)} <span class="tenue">${esc(claseArticulo(r))}</span></td><td>${esc(r.unidad)}</td>${bod.map(b => celda(celdaV(r, b))).join('')}${celda(total(r), 'total')}</tr>`).join('');
      }).join('') || `<tr><td colspan="${ncol}" class="vacio">Sin artículos para mostrar.</td></tr>`;
      const pie = enValor && f.length ? `<tfoot><tr><td colspan="3">Total</td>${bod.map(b => `<td class="n">${fPeso(f.reduce((s, r) => s + valorFila(r, b), 0))}</td>`).join('')}<td class="n total">${fPeso(f.reduce((s, r) => s + total(r), 0))}</td></tr></tfoot>` : '';
      $('.tabla-marco', c).innerHTML = `<table><thead><tr><th>Código</th><th>Artículo</th><th>Unidad</th>${bod.map(b => `<th class="n">${esc(b.nombre)}</th>`).join('')}<th class="n total">Total</th></tr></thead><tbody>${cuerpo}</tbody>${pie}</table>`;
      $('.conteo', c).textContent = `${f.length} ${f.length === 1 ? 'artículo' : 'artículos'} en ${grupos.length} ${grupos.length === 1 ? 'categoría' : 'categorías'}`;
    };
    dibujar();
    $('#st-tipo', c).addEventListener('change', e => { stockRep.tipo = e.target.value; render(); });
    $('#st-ver', c).addEventListener('change', e => { stockRep.ver = e.target.value; render(); });
    $('#st-central', c).addEventListener('change', e => { stockRep.central = e.target.checked; render(); });
    $('#st-con', c).addEventListener('change', e => { stockRep.conStock = e.target.checked; dibujar(); });
    $('.buscar', c).addEventListener('input', e => { stockRep.q = e.target.value; dibujar(); });
    $('.csv', c).addEventListener('click', () => bajarCsv(`stock_por_tienda_${hoy()}`, [
      ['Categoría', 'Código', 'Artículo', 'Tipo', 'Unidad', ...bod.map(b => b.nombre), 'Total'],
      ...filtradas().map(r => [r.categoria, r.codigo, r.nombre, claseArticulo(r), r.unidad, ...bod.map(b => celdaV(r, b)), total(r)])]));
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
      const esAdmin = p?.nombre === 'Administrador';
      const m = modal(p ? `Perfil: ${p.nombre}` : 'Nuevo perfil', `<form novalidate><label class="campo"><span>Nombre del perfil</span><input name="nombre" value="${esc(p?.nombre)}"></label>
        <div class="tabla-marco" style="margin-top:12px"><table class="perm"><thead><tr><th>Módulo</th><th class="c">Sin acceso</th><th class="c">Ver</th><th class="c">Editar</th></tr></thead><tbody>
        ${S.modulos.map(x => `<tr><td>${esc(x.nombre)}</td>${[0, 1, 2].map(n => `<td class="c"><input type="radio" name="p_${x.id}" value="${n}" aria-label="${esc(x.nombre)}: ${['sin acceso', 'ver', 'editar'][n]}" ${(p?.permisos?.[x.id] || 0) === n ? 'checked' : ''}></td>`).join('')}</tr>`).join('')}</tbody></table></div>
        <h3 style="font-size:15px;margin:16px 0 4px">Acciones críticas</h3>
        <p class="nota">Además de "Editar" en su módulo, cada acción necesita su propio permiso. ${esAdmin ? 'El perfil Administrador siempre las tiene todas.' : 'Solo se pueden marcar si el perfil puede editar ese módulo.'}</p>
        <div class="tabla-marco"><table class="perm"><thead><tr><th>Acción</th><th>Módulo</th><th class="c">Permitida</th></tr></thead><tbody>
        ${S.acciones.map(a => `<tr><td>${esc(a.nombre)}</td><td class="tenue">${esc(a.modulo ? (S.modulos.find(x => x.id === a.modulo)?.nombre || a.modulo) : 'Varios')}</td>
          <td class="c"><input type="checkbox" name="acc_${a.id}" data-mod="${a.modulo || ''}" aria-label="${esc(a.nombre)}" ${esAdmin || p?.permisos?.['acc_' + a.id] ? 'checked' : ''} ${esAdmin ? 'disabled' : ''}></td></tr>`).join('')}</tbody></table></div>
        <div class="error" hidden></div><div class="modal-pie"><button type="button" class="btn cerrar">Cancelar</button><button class="btn primario">Guardar perfil</button></div></form>`, true);
      $$('.cerrar', m.el).forEach(b => b.addEventListener('click', m.cerrar));
      const f = $('form', m.el);
      const habilitar = () => {  // una acción solo se puede marcar si el perfil edita su módulo
        if (esAdmin) return;
        const edita = id => Number(f[`p_${id}`].value) === 2;
        $$('input[name^="acc_"]', f).forEach(i => {
          const ok = i.dataset.mod ? edita(i.dataset.mod) : S.modulos.some(x => edita(x.id));
          i.disabled = !ok; if (!ok) i.checked = false;
        });
      };
      f.addEventListener('change', e => { if (e.target.name?.startsWith('p_')) habilitar(); });
      habilitar();
      conEnvio(f, m, async () => {
        const permisos = {};
        S.modulos.forEach(x => { const n = Number(f[`p_${x.id}`].value); if (n) permisos[x.id] = n; });
        S.acciones.forEach(a => { if (f[`acc_${a.id}`].checked) permisos['acc_' + a.id] = 1; });
        await api(p ? 'PUT' : 'POST', '/perfiles' + (p ? '/' + p.id : ''), { nombre: f.nombre.value, permisos });
        aviso('Perfil guardado.'); if (p) await refrescarUsuario(); render();
      });
    };
    $('#n', v)?.addEventListener('click', () => form());
    tabla(c, { filas: perfiles, acciones: { editar: form,
      borrar: p => confirmar('Eliminar perfil', `¿Eliminar el perfil ${p.nombre}?`, async () => { await api('DELETE', `/perfiles/${p.id}`); render(); }, 'Eliminar') }, cols: [
      { t: 'Perfil', v: r => r.nombre }, { t: 'Usuarios', n: 1, v: r => r.usuarios }, { t: 'Módulos con acceso', n: 1, v: r => S.modulos.filter(x => r.permisos[x.id]).length },
      { t: 'Módulos que puede editar', n: 1, v: r => S.modulos.filter(x => r.permisos[x.id] === 2).length },
      { t: 'Acciones críticas', n: 1, v: r => r.nombre === 'Administrador' ? S.acciones.length : S.acciones.filter(a => r.permisos['acc_' + a.id]).length },
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
    ${edita && puede('respaldo') ? '<div class="tarjeta"><h2>Respaldo</h2><p class="nota">Descarga una copia completa de la base de datos. Guárdala en un lugar seguro: incluye toda la información del sistema.</p><a class="btn" href="/api/config/respaldo" style="display:inline-block;text-decoration:none">Descargar respaldo</a></div>' : ''}`;
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
  if (edita && !S.usuario.tienda_id) await tarjetaPos(v);
};

async function tarjetaPos(v) {
  const t = document.createElement('div');
  t.className = 'tarjeta';
  v.append(t);
  const pintar = async () => {
    const s = await api('GET', '/config/pos');
    const estado = !s.configurado ? '<b>Desactivada.</b> El POS no puede descontar stock hasta que generes una clave.'
      : s.origen === 'variable' ? '<b>Activada</b> con la clave definida en el servidor (variable NS_POS_TOKEN).'
      : '<b>Activada.</b>';
    t.innerHTML = `<h2>Conexión con el POS</h2><p class="nota">Permite que el POS de las tiendas descuente del stock de cada tienda los ingredientes de cada venta, y lo devuelva si la venta se anula.</p>
      <p>${estado} Consumos recibidos: <b>${s.consumos}</b>${s.ultimo ? ` · último: ${esc(s.ultimo)}` : ''}</p>
      ${s.origen === 'variable' ? '' : `<div class="filtros"><button class="btn" id="pos-gen">${s.configurado ? 'Generar clave nueva' : 'Activar y generar clave'}</button>${s.configurado ? '<button class="btn" id="pos-off">Desactivar conexión</button>' : ''}</div>`}`;
    const generar = async () => {
      const r = await api('POST', '/config/pos/token', {});
      const m = modal('Clave de conexión del POS', `<p>Copia esta clave y pégala en el POS, en la pantalla <b>Conexión</b>. <b>Solo se muestra esta vez.</b></p>
        <input id="pos-clave" readonly value="${esc(r.token)}" aria-label="Clave del POS" style="width:100%;font-family:monospace">
        <div class="modal-pie"><button type="button" class="btn primario" id="pos-copiar">Copiar clave</button></div>`);
      $('#pos-copiar', m.el).addEventListener('click', async () => {
        const i = $('#pos-clave', m.el); i.select();
        try { await navigator.clipboard.writeText(i.value); } catch { document.execCommand('copy'); }
        aviso('Clave copiada.');
      });
      pintar();
    };
    $('#pos-gen', t)?.addEventListener('click', () => {
      if (!s.configurado) return generar().catch(x => aviso(x.message, 1));
      confirmar('Generar clave nueva', 'La clave actual dejará de funcionar y tendrás que poner la nueva en el POS.', generar, 'Generar');
    });
    $('#pos-off', t)?.addEventListener('click', () => confirmar('Desactivar conexión con el POS', 'El POS no podrá descontar stock hasta que generes una clave nueva.',
      async () => { await api('DELETE', '/config/pos/token'); aviso('Conexión con el POS desactivada.'); pintar(); }, 'Desactivar'));
  };
  try { await pintar(); } catch (x) { t.innerHTML = `<h2>Conexión con el POS</h2><p class="nota">${esc(x.message)}</p>`; }
}

/* ---------- arranque y rutas ---------- */
const PERMISO_RUTA = { compras: ['compras', 'proveedores'], fudo: ['config'] };
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
    // se corrige la dirección sin disparar 'hashchange' (eso contaría como si el usuario hubiera elegido una opción)
    if (location.hash !== '#/' + m) history.replaceState(null, '', '#/' + m);
  }
  // Al entrar al sistema el menú queda sin marcar hasta que el usuario elige una opción
  $$('.nav a').forEach(a => { const on = !S.menuSinMarca && a.dataset.m === m; a.classList.toggle('activo', on); if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
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
  S.usuario = S.estado.usuario; S.modulos = S.estado.modulos; S.acciones = S.estado.acciones || []; S.logo = S.estado.logo;
  if (!S.usuario) return pantallaAcceso();
  S.menuSinMarca = true;  // recién ingresado: ninguna opción del menú aparece marcada
  marco();
  $('#lateral .nav').addEventListener('click', e => {
    const a = e.target.closest('a[data-m]');
    if (!a) return;
    S.menuSinMarca = false;
    if (a.getAttribute('href') === location.hash) { e.preventDefault(); render(); }  // misma pantalla: solo se marca
  });
  render();
}
addEventListener('hashchange', () => { S.menuSinMarca = false; render(); });
iniciar().catch(x => { app.innerHTML = `<div class="acceso"><div class="tarjeta">${esc(x.message)}</div></div>`; });
