/* Ayuda del sistema: el usuario escribe una pregunta o palabra y recibe los pasos del tema que mejor coincide.
   Funciona sin internet y sin enviar datos fuera: busca en la base de temas de este archivo. */
(() => {
  // m: módulo (para "Ir a la pantalla" y para mostrarlo solo a quien tiene acceso); k: palabras y sinónimos; r: respuesta (HTML)
  const TEMAS = [
    // General
    { t: 'Cómo ingresar y salir del sistema', k: 'entrar ingresar login acceso usuario contraseña clave salir cerrar sesion', r: '<ol><li>Escribe tu <b>usuario</b> y <b>contraseña</b> y presiona <b>Ingresar</b>.</li><li>Para salir, usa <b>Salir</b> al pie del menú de la izquierda.</li></ol><p>Si olvidaste tu contraseña, pide al administrador que te asigne una nueva en <b>Usuarios y perfiles</b>.</p>' },
    { t: 'Cambiar mi contraseña', k: 'cambiar contraseña clave password nueva olvidé', r: '<ol><li>Al pie del menú de la izquierda presiona <b>Cambiar contraseña</b>.</li><li>Escribe la actual y la nueva (mínimo 8 caracteres) y guarda.</li></ol>' },
    { t: 'No veo un módulo o un botón', k: 'no veo boton opcion menu falta permiso acceso oculto aparece bloqueado', r: '<p>Cada usuario ve solo lo que su <b>perfil</b> permite. Los botones de acciones críticas (anular, cerrar inventario, enviar a Fudo…) necesitan además un permiso propio.</p><p>Pide al administrador que revise tu perfil en <b>Usuarios y perfiles → Perfiles y accesos</b>.</p>' },
    { t: 'Buscar, ordenar y descargar tablas a Excel', k: 'buscar filtrar ordenar tabla excel csv descargar exportar planilla', r: '<ul><li><b>Buscar…</b> filtra la tabla mientras escribes.</li><li>Haz clic en el <b>encabezado de una columna</b> para ordenar.</li><li><b>Descargar CSV</b> baja la tabla para abrirla en Excel.</li></ul>' },
    { t: 'Los cambios no se ven o la pantalla se ve rara', k: 'actualizar recargar no se ve cambios pantalla rara error cache f5 lento', r: '<p>Recarga la página con <b>Ctrl + F5</b> (en celular, cierra y vuelve a abrir la pestaña). Si el error sigue, avisa al administrador con el mensaje que aparece.</p>' },
    { t: 'Qué muestra el Panel de inicio', m: 'panel', k: 'panel inicio resumen indicadores kpi graficos dashboard', r: '<p>Resume los últimos 30 días: inventario valorizado en la central y en tiendas, compras, costo de producción, despachos, mermas y artículos <b>bajo stock mínimo</b>, con gráficos por mes.</p>' },
    { t: 'Qué significa “el stock no puede quedar negativo”', k: 'negativo stock insuficiente no alcanza falta disponible saldo', r: '<p>Ningún movimiento puede dejar una bodega con saldo negativo. Si el sistema lo rechaza, revisa el stock en <b>Bodegas</b>: puede faltar registrar una compra, una producción o una guía antes.</p>' },
    { t: 'Anular un documento', k: 'anular deshacer revertir borrar eliminar equivocado error corregir documento', r: '<p>Las compras, devoluciones, producciones, guías, mermas y salidas se corrigen con <b>Anular</b> en su fila. Se crea un movimiento inverso visible en el historial.</p><ul><li>Solo es posible si el stock que sumó todavía está disponible.</li><li>Requiere el permiso de la acción crítica correspondiente.</li></ul>' },
    // Compras
    { t: 'Registrar una compra', m: 'compras', k: 'compra comprar factura boleta ingresar mercaderia proveedor recibir entrada insumos registrar', r: '<ol><li>Ve a <b>Compras y proveedores → Registrar compra</b>.</li><li>Elige proveedor, fecha, tipo y número de documento.</li><li>Agrega cada artículo con su <b>cantidad</b> y <b>precio neto</b>.</li><li>Presiona <b>Registrar compra</b>.</li></ol><p>Suma a la bodega central y actualiza el último precio y el costo promedio.</p>' },
    { t: 'Compra con guía de despacho y su factura', m: 'compras', k: 'guia despacho proveedor factura llega despues netear netea pendiente facturar cuadrar', r: '<ol><li>Al recibir la mercadería, registra la compra con tipo <b>Guía de despacho</b> y su número: el stock entra al tiro.</li><li>La guía queda <b>Pendiente de factura</b> en la pestaña <b>Guías por facturar</b>.</li><li>Cuando llegue la factura, presiona <b>Registrar factura</b>, elige el proveedor, marca las guías que incluye y escribe el N° y el neto de la factura.</li></ol><p>Las guías quedan neteadas: no vuelve a entrar stock ni se cuenta dos veces la compra. Si el monto no coincide, se muestra la <b>diferencia</b>.</p>' },
    { t: 'Crear o editar un proveedor', m: 'compras', k: 'proveedor nuevo crear editar rut agregar', r: '<ol><li>En <b>Compras y proveedores</b> abre la pestaña <b>Proveedores</b>.</li><li>Presiona <b>Nuevo proveedor</b> (o <b>Editar</b> en su fila), con RUT y nombre.</li></ol>' },
    { t: 'Cambiar el valor del IVA', m: 'compras', k: 'iva impuesto porcentaje 19', r: '<p>En <b>Compras y proveedores → Valor IVA</b> se define el porcentaje que usan las compras y las guías.</p>' },
    { t: 'Devolver mercadería a un proveedor', m: 'devoluciones', k: 'devolucion devolver proveedor mal estado reclamo', r: '<ol><li>Ve a <b>Devoluciones a proveedores → Nueva devolución</b>.</li><li>Indica proveedor, <b>motivo</b>, artículos y cantidades.</li></ol><p>Saca el stock de la central. Los productos y subproductos no se devuelven, y no cambia el costo promedio.</p>' },
    // Artículos
    { t: 'Crear un producto o insumo', m: 'articulos', k: 'crear nuevo articulo producto insumo subproducto agregar catalogo item', r: '<ol><li>Ve a <b>Productos e insumos → Nuevo artículo</b>.</li><li>Elige el tipo, la categoría, la unidad, el nombre y el stock mínimo.</li><li>Guarda: el código se asigna solo.</li></ol>' },
    { t: 'Qué significan los códigos P, SP, IN, IPV e IDA', k: 'codigo prefijo p sp in ipv ida tipo articulo clasificacion', r: '<ul><li><b>P</b>: producto (se vende).</li><li><b>SP</b>: subproducto (se usa en otras recetas).</li><li><b>IN</b>: insumo de receta.</li><li><b>IPV</b>: insumo de punto de venta (café, leche, azúcar…).</li><li><b>IDA</b>: desechables y aseo.</li></ul><p>El código no cambia aunque cambies la clasificación.</p>' },
    { t: 'Categorías y unidades de medida', m: 'articulos', k: 'categoria unidad medida kg gramo litro crear', r: '<p>En <b>Productos e insumos</b> están las pestañas <b>Categorías</b> y <b>Unidades de medida</b>. Una categoría es de productos o de no productos, y no se cambia si ya tiene artículos.</p>' },
    { t: 'Eliminar o desactivar un artículo', m: 'articulos', k: 'eliminar borrar desactivar inactivo articulo', r: '<p>Solo se elimina si no tiene stock, recetas ni movimientos. Si tiene historial, edítalo y déjalo <b>inactivo</b>: deja de aparecer en las listas.</p>' },
    { t: 'Stock mínimo y alertas', m: 'articulos', k: 'stock minimo alerta bajo reponer reposicion falta', r: '<p>Cada artículo tiene un <b>stock mínimo</b>. Si la central queda bajo ese valor, aparece en el <b>Panel de inicio</b> y en <b>Bodegas</b>. El reporte <b>Cobertura y reposición</b> sugiere cuánto comprar.</p>' },
    // Producción
    { t: 'Crear o modificar una receta', m: 'recetas', k: 'receta ingredientes rendimiento formula preparacion crear editar', r: '<ol><li>Ve a <b>Recetas</b> y elige el producto o subproducto.</li><li>Indica el <b>rendimiento</b> (cuánto produce) y cada ingrediente con su cantidad.</li></ol><p>Las cantidades van en la unidad de cada ingrediente: si la harina está en kg, 250 g se escribe 0,250.</p>' },
    { t: 'Registrar una producción', m: 'produccion', k: 'producir produccion fabricar elaborar lote cocinar deja falta ingrediente insuficiente', r: '<ol><li>Ve a <b>Producción → Registrar producción</b>.</li><li>Elige el artículo, la cantidad y la fecha.</li><li>Presiona <b>Registrar y descontar insumos</b>.</li></ol><p>Si falta algún ingrediente, no se descuenta nada y el mensaje dice cuál falta.</p>' },
    { t: 'Imprimir órdenes de producción', m: 'produccion', k: 'imprimir orden produccion fechas', r: '<p>En <b>Producción</b> presiona <b>Imprimir por fechas</b> y elige el período.</p>' },
    // Tiendas y bodegas
    { t: 'Crear o editar una tienda', m: 'tiendas', k: 'tienda local sucursal crear nueva direccion comuna', r: '<p>En <b>Tiendas → Nueva tienda</b> se registran nombre, dirección, comuna y región. Una tienda inactiva deja de aparecer en las listas.</p>' },
    { t: 'Ver el stock de una bodega', m: 'bodegas', k: 'ver stock bodega cuanto hay existencias saldo inventario actual tienda central', r: '<p>En <b>Bodegas</b> elige la bodega (y en la central, la sección) para ver el stock por artículo y su valor a costo. Para comparar todas las tiendas a la vez usa <b>Reportes → Stock por tienda</b>.</p>' },
    // Despachos
    { t: 'Emitir una guía de despacho a una tienda', m: 'despachos', k: 'guia despacho enviar tienda despachar traslado mandar reparto', r: '<ol><li>Ve a <b>Despachos a tiendas → Nueva guía</b>.</li><li>Elige tienda, fecha y, si quieres, transportista y patente.</li><li>Agrega artículos y cantidades (la columna <b>Disponible</b> muestra la central).</li><li>Presiona <b>Emitir guía</b>.</li></ol><p>Descuenta de la central y suma a la tienda. Los insumos de receta no se despachan.</p>' },
    { t: 'Imprimir una guía', m: 'despachos', k: 'imprimir guia papel firma', r: '<p>En la fila de la guía presiona <b>Ver guía</b> y luego <b>Imprimir</b>. Es un documento interno: no reemplaza la guía electrónica del SII.</p>' },
    { t: 'Enviar una guía a Fudo', m: 'despachos', k: 'fudo enviar gasto guia pagar pagado efectivo', r: '<ol><li>Abre la guía con <b>Ver guía</b>.</li><li>Presiona <b>Enviar a Fudo</b>.</li></ol><p>Crea un gasto en la cuenta Fudo de la tienda con el proveedor Nata &amp; Schlott, lo deja <b>pagado en Efectivo</b> con la fecha de la guía y suma el stock de los insumos con equivalencia.</p>' },
    { t: 'Anular una guía', m: 'despachos', k: 'anular guia devolver error despacho equivocado', r: '<p>En <b>Ver guía</b> presiona <b>Anular guía</b>. Devuelve el stock a la central y, si estaba en Fudo, anula el gasto y resta el stock que había sumado. La tienda debe tener todavía ese stock.</p>' },
    { t: 'Qué significan los estados de una guía y de Fudo', m: 'despachos', k: 'estado revisar sin pago pagado sumado restado manual sin enviar gasto vigente', r: '<ul><li><b>Sin enviar</b>: aún no va a Fudo.</li><li><b>Pagado</b> / <b>Sin pago</b>: el gasto existe; si falta el pago usa <b>Registrar pago en Fudo</b> en Ver guía.</li><li><b>Revisar</b>: Fudo no confirmó; revisa en Fudo antes de reintentar.</li><li><b>Sumado / Restado</b>: el stock de la guía en Fudo.</li></ul>' },
    { t: 'Devolución de una tienda a la central', m: 'despachos', k: 'devolucion tienda devolver central desechables aseo retorno', r: '<p>En <b>Despachos a tiendas → Devoluciones de tiendas → Nueva devolución</b>. Es para desechables y aseo: baja la tienda y sube la central. Exige motivo.</p>' },
    { t: 'Registrar consumo interno en la central', m: 'despachos', k: 'consumo interno central uso desechables aseo gasto propio', r: '<p>En <b>Despachos a tiendas → Consumo en central → Registrar consumo</b>, para desechables y aseo usados en la central o en producción. Exige motivo.</p>' },
    // Control de stock
    { t: 'Hacer una toma de inventario', m: 'inventario', k: 'inventario toma contar conteo fisico recuento cuadrar ajustar diferencia', r: '<ol><li>Ve a <b>Toma de inventario</b>.</li><li>Elige la <b>bodega</b>, la <b>fecha</b> y escribe el <b>motivo</b>.</li><li>Elige el <b>tipo de artículo</b> o busca uno por nombre.</li><li>Escribe lo contado: se guarda solo al pasar al siguiente campo.</li><li>Al terminar, presiona <b>Cerrar y ajustar stock</b>.</li></ol><p>Lo que no cuentes mantiene su stock.</p>' },
    { t: 'Seguir una toma de inventario después', m: 'inventario', k: 'continuar seguir retomar inventario guardado despues pausa', r: '<p>Los conteos se guardan solos. Vuelve a <b>Toma de inventario</b>, elige la misma bodega y aparece la toma en curso con lo que ya contaste. También puedes usar <b>Contar</b> en la lista de tomas.</p>' },
    { t: 'Descartar una toma de inventario', m: 'inventario', k: 'descartar eliminar cancelar toma inventario borrar conteo', r: '<p>En la toma en curso presiona <b>Descartar conteo</b>: borra lo contado sin tocar el stock. Requiere el permiso <b>Cerrar inventario</b>.</p>' },
    { t: 'Registrar una merma', m: 'mermas', k: 'merma perdida vencido roto quebrado botar desecho dañado', r: '<ol><li>Ve a <b>Mermas → Registrar merma</b>.</li><li>Elige la bodega, el artículo, la cantidad y el <b>motivo</b>.</li></ol><p>Los motivos se administran en la pestaña <b>Motivos</b>.</p>' },
    { t: 'Ver el historial de movimientos', m: 'historial', k: 'historial movimientos kardex entradas salidas quien cuando trazabilidad', r: '<p>En <b>Historial</b> está cada entrada y salida con fecha, saldo, bodega y usuario. Filtra por fechas, tipo de movimiento, bodega, proveedor o tienda.</p>' },
    { t: 'Corregir el stock directamente', m: 'stock', k: 'actualizar stock corregir fijar ajuste manual cambiar cantidad', r: '<p>En <b>Actualizar stock</b> (solo Administrador) se escribe el nuevo stock y un <b>motivo</b>; la diferencia queda en el historial. Para conteos físicos usa mejor la <b>Toma de inventario</b>.</p>' },
    // Reportes
    { t: 'Ver el stock de todas las tiendas en un solo informe', m: 'reportes', k: 'informe reporte stock tiendas columnas categorias comparar todas', r: '<p>En <b>Reportes → Stock por tienda</b>: una columna por bodega, filas agrupadas por categoría. Puedes ver cantidades o <b>valor a costo</b>, filtrar por tipo y descargar CSV.</p>' },
    { t: 'Qué reportes hay', m: 'reportes', k: 'reportes informes margen costo precios cobertura rendimiento compras ventas analisis', r: '<ul><li><b>Rendimiento de producción</b>: costo real vs receta.</li><li><b>Precios de insumos</b>: evolución y mejor proveedor.</li><li><b>Márgenes</b>: precio, costo y margen por producto.</li><li><b>Cobertura y reposición</b>: días de stock y cuánto comprar.</li><li><b>Stock por tienda</b>, <b>Compras</b>, <b>Despachos</b> y <b>Mermas</b>.</li></ul>' },
    { t: 'Saber cuánto comprar', m: 'reportes', k: 'cuanto comprar reponer pedido sugerido cobertura dias', r: '<p>En <b>Reportes → Cobertura y reposición</b> ves los días de stock de la central y la cantidad sugerida para cubrir 14 días o el stock mínimo.</p>' },
    // Fudo
    { t: 'Conectar una tienda con Fudo', m: 'fudo', k: 'fudo conectar credenciales api key secret cuenta integracion', r: '<ol><li>Ve a <b>Integración Fudo</b>.</li><li>En la tienda presiona <b>Cambiar credenciales</b> e ingresa la API Key y API Secret de <b>su propia cuenta</b> Fudo.</li><li>En <b>Ajustar gastos</b> elige la categoría de gasto.</li></ol><p>No se permite usar la misma cuenta en dos tiendas.</p>' },
    { t: 'Asociar los insumos de Fudo con los del sistema', m: 'fudo', k: 'equivalencia importar insumos fudo asociar relacionar vincular', r: '<ol><li>En <b>Integración Fudo → Insumos y stock</b> de la tienda, abre <b>Importar desde Fudo</b>.</li><li>Revisa la sugerencia de cada insumo o elige <b>Crear artículo nuevo</b>.</li><li>Marca los que quieras y presiona <b>Importar seleccionados</b>.</li></ol>' },
    { t: 'Comparar y sincronizar el stock con Fudo', m: 'fudo', k: 'comparar sincronizar ventas fudo descontar diferencia ajustar igualar', r: '<p>En <b>Insumos y stock → Comparar y sincronizar</b> ves el stock del sistema y el de Fudo. <b>Sincronizar</b> descuenta lo vendido como <b>Ventas en Fudo</b>. <b>Ajustar sistema a Fudo</b> e <b>Igualar Fudo al sistema</b> sirven para partir alineados.</p>' },
    { t: 'En Comparar no aparece nada', m: 'fudo', k: 'comparar vacio no aparece nada productos fudo stock no veo', r: '<p>Faltan las <b>equivalencias</b> de esa tienda. Cárgalas con <b>Importar desde Fudo</b> en Insumos y stock.</p>' },
    // Administración
    { t: 'Crear un usuario', m: 'usuarios', k: 'usuario nuevo crear agregar persona empleado cuenta', r: '<ol><li>Ve a <b>Usuarios y perfiles → Nuevo usuario</b>.</li><li>Indica nombre, usuario, contraseña y <b>perfil</b>.</li><li>Si es de una tienda, asócialo: solo verá esa tienda.</li></ol>' },
    { t: 'Dar o quitar permisos (perfiles)', m: 'usuarios', k: 'perfil permisos accesos rol dar quitar acciones criticas editar ver', r: '<ol><li>Ve a <b>Usuarios y perfiles → Perfiles y accesos</b>.</li><li>Presiona <b>Editar accesos</b> en el perfil.</li><li>Para cada módulo elige <b>Sin acceso</b>, <b>Ver</b> o <b>Editar</b>, y marca las <b>acciones críticas</b> permitidas.</li></ol>' },
    { t: 'Descargar un respaldo', m: 'config', k: 'respaldo backup copia seguridad descargar base datos', r: '<p>En <b>Configuración → Respaldo</b> presiona <b>Descargar respaldo</b> y guárdalo en un lugar seguro.</p>' },
    { t: 'Cambiar el logo', m: 'config', k: 'logo imagen marca cambiar', r: '<p>En <b>Configuración → Logo</b> elige un archivo PNG, JPG, WEBP o SVG de hasta 2 MB.</p>' },
    { t: 'Conectar el POS de las tiendas', m: 'config', k: 'pos caja punto venta conectar clave token ventas', r: '<p>En <b>Configuración → Conexión con el POS</b> presiona <b>Activar y generar clave</b> y pégala en el POS. Se muestra una sola vez: si se pierde, genera otra.</p>' },
  ];

  const VACIAS = new Set('a al como con cual cuales cuando de del donde el en es esta este hacer hago la las lo los me mi mis no o para por puedo que se si sin su sus un una uno y ya quiero necesito debo tengo ver hay esto eso porque favor ayuda'.split(' '));
  const norm = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const palabras = s => norm(s).split(/[^a-z0-9ñ]+/).filter(w => w.length > 1 && !VACIAS.has(w));
  // Parecido por raíz común (anulo ~ anular, guías ~ guía): 2 exacto, 1 parecido, 0 nada
  const parecido = (a, b) => {
    if (a === b) return 2;
    if (a.length < 4 || b.length < 4) return 0;
    let i = 0; while (i < a.length && i < b.length && a[i] === b[i]) i++;
    return i >= 4 && i >= Math.min(a.length, b.length) - 2 ? 1 : 0;
  };
  const mejor = (w, lista) => lista.reduce((m, p) => Math.max(m, parecido(w, p)), 0);
  const idx = TEMAS.map(x => ({ ...x, pt: palabras(x.t), pk: palabras(x.k), pr: palabras(x.r.replace(/<[^>]+>/g, ' ')) }));

  const visible = x => !x.m || ((typeof PERMISO_RUTA !== 'undefined' && PERMISO_RUTA[x.m]) || [x.m]).some(p => can(p));
  function buscar(q) {
    const ws = palabras(q);
    if (!ws.length) return [];
    const actual = location.hash.replace(/^#\//, '');
    return idx.filter(visible).map(x => {
      let s = 0, hits = 0;
      for (const w of ws) {
        const t = mejor(w, x.pt), k = mejor(w, x.pk), r = mejor(w, x.pr);
        const h = Math.max(t === 2 ? 3 : t ? 2 : 0, k === 2 ? 2.5 : k ? 1.5 : 0, r === 2 ? 0.8 : r ? 0.4 : 0);
        s += h; if (h) hits++;
      }
      if (hits) s += hits / ws.length * 2 + (x.m === actual ? 0.5 : 0);
      return { x, s };
    }).filter(r => r.s >= 1.5).sort((a, b) => b.s - a.s).map(r => r.x);
  }

  const NOMBRES = { panel: 'Panel de inicio', compras: 'Compras y proveedores', devoluciones: 'Devoluciones', tiendas: 'Tiendas', bodegas: 'Bodegas', articulos: 'Productos e insumos',
    inventario: 'Toma de inventario', historial: 'Historial', mermas: 'Mermas', recetas: 'Recetas', produccion: 'Producción', despachos: 'Despachos a tiendas', reportes: 'Reportes',
    stock: 'Actualizar stock', fudo: 'Integración Fudo', usuarios: 'Usuarios y perfiles', config: 'Configuración' };
  const tarjeta = (x, abierta) => `<details class="ay-tema" ${abierta ? 'open' : ''}><summary>${esc(x.t)}</summary><div class="ay-resp">${x.r}
    ${x.m ? `<button type="button" class="btn mini ay-ir" data-m="${x.m}">Ir a ${esc(NOMBRES[x.m] || x.m)} →</button>` : ''}</div></details>`;

  let panel = null;
  function abrir(pregunta) {
    if (!S.usuario) return;
    if (!panel) {
      panel = document.createElement('aside');
      panel.className = 'ay-panel'; panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Ayuda');
      panel.innerHTML = `<div class="ay-cab"><strong>¿En qué te ayudo?</strong><button type="button" class="cerrar ay-cerrar" aria-label="Cerrar ayuda">×</button></div>
        <div class="ay-chat" aria-live="polite"></div>
        <form class="ay-form"><input type="search" class="ay-q" placeholder="Escribe tu pregunta…" aria-label="Pregunta" autocomplete="off"><button class="btn primario">Preguntar</button></form>`;
      document.body.append(panel);
      $('.ay-cerrar', panel).addEventListener('click', cerrar);
      $('.ay-form', panel).addEventListener('submit', e => { e.preventDefault(); const q = $('.ay-q', panel).value.trim(); if (q) { responder(q); $('.ay-q', panel).value = ''; } });
      $('.ay-q', panel).addEventListener('input', e => sugerir(e.target.value));
      panel.addEventListener('click', e => {
        const ir = e.target.closest('.ay-ir'); if (ir) { location.hash = '#/' + ir.dataset.m; if (innerWidth < 900) cerrar(); return; }
        const s = e.target.closest('[data-q]'); if (s) responder(s.dataset.q);
      });
      document.addEventListener('keydown', e => { if (e.key === 'Escape' && panel?.classList.contains('abierto')) cerrar(); });
    }
    panel.classList.add('abierto');
    if (!$('.ay-chat', panel).children.length) bienvenida();
    if (pregunta) responder(pregunta);
    setTimeout(() => $('.ay-q', panel).focus(), 50);
  }
  function cerrar() { panel?.classList.remove('abierto'); }
  function bienvenida() {
    const actual = location.hash.replace(/^#\//, '');
    const aqui = idx.filter(x => x.m === actual && visible(x)).slice(0, 4);
    const chat = $('.ay-chat', panel);
    chat.insertAdjacentHTML('beforeend', `<div class="ay-msg ay-bot"><p>Escribe una pregunta o una palabra (por ejemplo <i>merma</i>, <i>guía</i>, <i>inventario</i>) y te explico los pasos.</p>
      ${aqui.length ? `<p class="ay-sub">Sobre esta pantalla:</p>${aqui.map(x => `<button type="button" class="ay-chip" data-q="${esc(x.t)}">${esc(x.t)}</button>`).join('')}` : ''}</div>`);
  }
  function sugerir(q) {
    let box = $('.ay-sug', panel);
    const r = q.trim().length >= 3 ? buscar(q).slice(0, 4) : [];
    if (!r.length) { box?.remove(); return; }
    if (!box) { box = document.createElement('div'); box.className = 'ay-sug'; $('.ay-form', panel).before(box); }
    box.innerHTML = r.map(x => `<button type="button" class="ay-chip" data-q="${esc(x.t)}">${esc(x.t)}</button>`).join('');
  }
  function responder(q) {
    $('.ay-sug', panel)?.remove();
    const chat = $('.ay-chat', panel);
    const r = buscar(q);
    let html = `<div class="ay-msg ay-yo">${esc(q)}</div><div class="ay-msg ay-bot">`;
    if (!r.length) {
      const pop = ['Registrar una compra', 'Emitir una guía de despacho a una tienda', 'Hacer una toma de inventario', 'Registrar una merma', 'Registrar una producción']
        .map(t => idx.find(x => x.t === t)).filter(x => x && visible(x));
      html += `<p>No encontré un tema que coincida. Prueba con otras palabras, o revisa uno de estos:</p>${pop.map(x => `<button type="button" class="ay-chip" data-q="${esc(x.t)}">${esc(x.t)}</button>`).join('')}
        <p class="ay-sub">Si no está aquí, consulta al administrador del sistema o el manual de usuario.</p>`;
    } else {
      html += tarjeta(r[0], true);
      if (r.length > 1) html += `<p class="ay-sub">También te puede servir:</p>${r.slice(1, 4).map(x => tarjeta(x, false)).join('')}`;
    }
    chat.insertAdjacentHTML('beforeend', html + '</div>');
    chat.lastElementChild.previousElementSibling.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  // Botón flotante y enlace en el menú, cada vez que se dibuja el marco del sistema
  const marcoOriginal = window.marco;
  window.marco = function () {
    marcoOriginal.apply(this, arguments);
    const nav = $('#lateral .enlaces');
    if (nav && !$('#ay-menu', nav)) nav.insertAdjacentHTML('afterbegin', '<button type="button" id="ay-menu">Ayuda</button>');
    $('#ay-menu')?.addEventListener('click', () => abrir());
    if (!$('#ay-boton')) {
      document.body.insertAdjacentHTML('beforeend', '<button type="button" id="ay-boton" title="Ayuda (F1)" aria-label="Abrir ayuda">?</button>');
      $('#ay-boton').addEventListener('click', () => (panel?.classList.contains('abierto') ? cerrar() : abrir()));
    }
  };
  // Sin sesión (pantalla de acceso) el botón y el panel se ocultan por CSS
  document.addEventListener('keydown', e => { if (e.key === 'F1' && S.usuario && $('#lateral')) { e.preventDefault(); abrir(); } });
  window.ayuda = { abrir, buscar, TEMAS };
})();
