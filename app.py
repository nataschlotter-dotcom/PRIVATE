#!/usr/bin/env python3
"""Sistema de producción y logística de Nata & Schlott.

Servidor sin dependencias externas (Python 3.10+ y SQLite).
Variables de entorno: PORT o NS_PORT (8080), NS_HOST (127.0.0.1), NS_DB (nata_schlott.db), NS_CLAVE_INSTALACION.
"""
import difflib
import hashlib
import hmac
import json
import mimetypes
import os
import random
import re
import secrets
import sqlite3
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
DB_PATH = os.environ.get("NS_DB", str(BASE / "nata_schlott.db"))
CLAVE_INSTALACION = os.environ.get("NS_CLAVE_INSTALACION", "").strip()  # protege el primer inicio cuando está en internet
CENTRAL = 0  # bodega_id de la bodega central de producción
SECCIONES = {"INSUMOS": "a.tipo='INSUMO' AND a.desechable=0", "PUNTO_VENTA": "c.punto_venta=1", "DESECHABLES": "a.desechable=1 AND c.punto_venta=0",
             "ELABORADOS": "a.tipo IN ('PRODUCTO','SUBPRODUCTO')"}  # secciones de la bodega central, según la clase del artículo
CATEGORIAS_PRODUCTOS = ("Tortas", "Pastelería individual", "Galletas y alfajores", "Bases y rellenos")
CATEGORIAS_PUNTO_VENTA = ("Café", "Chocolate", "Leches", "Té", "Agua", "Utensilios para café", "Utensilios de aseo", "Azúcar")
FUDO_API = os.environ.get("NS_FUDO_API", "https://api.fu.do/v1alpha1")
FUDO_AUTH = os.environ.get("NS_FUDO_AUTH", "https://auth.fu.do/api")
FUDO_TIMEOUT = 20
SESION_HORAS = 12
MAX_BODY = 5 * 1024 * 1024
MAX_LOGO = 2 * 1024 * 1024

MODULOS = [
    ("panel", "Panel de inicio"), ("compras", "Compras"), ("devoluciones", "Devoluciones a proveedores"), ("proveedores", "Proveedores e IVA"),
    ("tiendas", "Tiendas"), ("articulos", "Artículos y catálogos"), ("inventario", "Toma de inventario"),
    ("historial", "Historial de movimientos"), ("mermas", "Mermas"), ("bodegas", "Bodegas"),
    ("recetas", "Recetas"), ("produccion", "Producción"), ("despachos", "Despachos a tiendas"),
    ("reportes", "Reportes de gestión"), ("usuarios", "Usuarios y perfiles"), ("config", "Configuración"),
]
TODOS = [m for m, _ in MODULOS]
# Acciones críticas: además del nivel "editar" en su módulo, requieren este permiso propio (clave "acc_<id>" en perfiles.permisos).
ACCIONES = [
    ("anular_compras", "Anular compras", "compras"),
    ("anular_devoluciones", "Anular devoluciones a proveedores", "devoluciones"),
    ("anular_produccion", "Anular producciones", "produccion"),
    ("anular_despachos", "Anular guías de despacho", "despachos"),
    ("anular_salidas", "Anular devoluciones de tiendas y consumos internos", "despachos"),
    ("enviar_fudo", "Enviar guías a Fudo (gasto y stock)", "despachos"),
    ("anular_fudo", "Anular gastos y restar stock en Fudo", "despachos"),
    ("anular_mermas", "Anular mermas", "mermas"),
    ("cerrar_inventario", "Cerrar o eliminar tomas de inventario (ajusta stock)", "inventario"),
    ("eliminar_registros", "Eliminar artículos, recetas, categorías, unidades, proveedores y tiendas", None),  # aplica a varios módulos
    ("stock_fudo", "Sincronizar, igualar y ajustar stock con Fudo", "config"),
    ("respaldo", "Descargar respaldo de la base de datos", "config"),
]
ACCIONES_IDS = [a for a, _, _ in ACCIONES]
PERFIL_ADMIN = "Administrador"  # "stock" no está en MODULOS: solo este perfil lo recibe, y no se puede asignar a otros
PERFILES = {
    PERFIL_ADMIN: {m: 2 for m in TODOS},
    "Gerencia": {**{m: 1 for m in TODOS if m not in ("usuarios", "config")}},
    "Producción": {"panel": 1, "articulos": 1, "inventario": 2, "historial": 1, "mermas": 2, "recetas": 2, "produccion": 2},
    "Bodega y logística": {"panel": 1, "compras": 2, "devoluciones": 2, "proveedores": 2, "tiendas": 1, "articulos": 2, "inventario": 2,
                           "historial": 1, "mermas": 2, "bodegas": 2, "despachos": 2},
    "Tienda": {"inventario": 2, "historial": 1, "mermas": 2, "bodegas": 2, "despachos": 1},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS config(clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS perfiles(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, permisos TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS tiendas(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, direccion TEXT NOT NULL,
  comuna TEXT NOT NULL, region TEXT NOT NULL, activo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS usuarios(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, nombre TEXT NOT NULL,
  password TEXT NOT NULL, perfil_id INTEGER NOT NULL REFERENCES perfiles(id), tienda_id INTEGER REFERENCES tiendas(id),
  activo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sesiones(token TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE, expira REAL NOT NULL);
CREATE TABLE IF NOT EXISTS proveedores(id INTEGER PRIMARY KEY, rut TEXT NOT NULL UNIQUE, nombre TEXT NOT NULL, activo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS categorias(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, punto_venta INTEGER NOT NULL DEFAULT 0, de_productos INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS unidades(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, abreviatura TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS motivos_merma(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS articulos(id INTEGER PRIMARY KEY, tipo TEXT NOT NULL CHECK(tipo IN ('PRODUCTO','SUBPRODUCTO','INSUMO')),
  desechable INTEGER NOT NULL DEFAULT 0, categoria_id INTEGER NOT NULL REFERENCES categorias(id),
  unidad_id INTEGER NOT NULL REFERENCES unidades(id), codigo TEXT NOT NULL UNIQUE COLLATE NOCASE, nombre TEXT NOT NULL,
  stock_minimo REAL NOT NULL DEFAULT 0, precio REAL NOT NULL DEFAULT 0, costo REAL NOT NULL DEFAULT 0, activo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS stock(bodega_id INTEGER NOT NULL, articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  cantidad REAL NOT NULL DEFAULT 0, PRIMARY KEY(bodega_id, articulo_id));
CREATE TABLE IF NOT EXISTS recetas(articulo_id INTEGER PRIMARY KEY REFERENCES articulos(id), rendimiento REAL NOT NULL, instrucciones TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS receta_items(receta_id INTEGER NOT NULL REFERENCES recetas(articulo_id) ON DELETE CASCADE,
  articulo_id INTEGER NOT NULL REFERENCES articulos(id), cantidad REAL NOT NULL, PRIMARY KEY(receta_id, articulo_id));
CREATE TABLE IF NOT EXISTS compras(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
  documento TEXT NOT NULL DEFAULT '', iva_pct REAL NOT NULL, neto REAL NOT NULL, iva REAL NOT NULL, total REAL NOT NULL,
  obs TEXT NOT NULL DEFAULT '', estado TEXT NOT NULL DEFAULT 'VIGENTE', usuario_id INTEGER REFERENCES usuarios(id), tipo_documento TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS compra_facturas(id INTEGER PRIMARY KEY, proveedor_id INTEGER NOT NULL REFERENCES proveedores(id), fecha TEXT NOT NULL,
  documento TEXT NOT NULL, iva_pct REAL NOT NULL, neto REAL NOT NULL, iva REAL NOT NULL, total REAL NOT NULL, obs TEXT NOT NULL DEFAULT '',
  estado TEXT NOT NULL DEFAULT 'VIGENTE', guias_anuladas TEXT NOT NULL DEFAULT '', usuario_id INTEGER REFERENCES usuarios(id), creado TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS compra_items(compra_id INTEGER NOT NULL REFERENCES compras(id), articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  cantidad REAL NOT NULL, precio REAL NOT NULL);
CREATE TABLE IF NOT EXISTS devoluciones(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
  documento TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL, iva_pct REAL NOT NULL, neto REAL NOT NULL, iva REAL NOT NULL, total REAL NOT NULL,
  estado TEXT NOT NULL DEFAULT 'VIGENTE', usuario_id INTEGER REFERENCES usuarios(id));
CREATE TABLE IF NOT EXISTS devolucion_items(devolucion_id INTEGER NOT NULL REFERENCES devoluciones(id), articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  cantidad REAL NOT NULL, precio REAL NOT NULL);
CREATE TABLE IF NOT EXISTS historial_precios(id INTEGER PRIMARY KEY, articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  proveedor_id INTEGER NOT NULL REFERENCES proveedores(id), compra_id INTEGER NOT NULL REFERENCES compras(id), fecha TEXT NOT NULL, precio REAL NOT NULL);
CREATE TABLE IF NOT EXISTS producciones(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  cantidad REAL NOT NULL, costo_total REAL NOT NULL, obs TEXT NOT NULL DEFAULT '', estado TEXT NOT NULL DEFAULT 'VIGENTE', usuario_id INTEGER REFERENCES usuarios(id));
CREATE TABLE IF NOT EXISTS despachos(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, tienda_id INTEGER NOT NULL REFERENCES tiendas(id),
  transportista TEXT NOT NULL DEFAULT '', patente TEXT NOT NULL DEFAULT '', obs TEXT NOT NULL DEFAULT '', iva_pct REAL NOT NULL,
  neto REAL NOT NULL, iva REAL NOT NULL, total REAL NOT NULL, estado TEXT NOT NULL DEFAULT 'VIGENTE', usuario_id INTEGER REFERENCES usuarios(id),
  fudo_estado TEXT NOT NULL DEFAULT '', fudo_gasto_id TEXT NOT NULL DEFAULT '', fudo_error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS salidas_internas(id INTEGER PRIMARY KEY, tipo TEXT NOT NULL CHECK(tipo IN ('DEVOLUCION_TIENDA','CONSUMO_CENTRAL')), fecha TEXT NOT NULL,
  tienda_id INTEGER REFERENCES tiendas(id), motivo TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'VIGENTE', usuario_id INTEGER REFERENCES usuarios(id));
CREATE TABLE IF NOT EXISTS salida_interna_items(salida_id INTEGER NOT NULL REFERENCES salidas_internas(id), articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  cantidad REAL NOT NULL, costo_unit REAL NOT NULL);
CREATE TABLE IF NOT EXISTS fudo_tiendas(tienda_id INTEGER PRIMARY KEY REFERENCES tiendas(id) ON DELETE CASCADE, api_key TEXT NOT NULL, api_secret TEXT NOT NULL,
  categoria_id TEXT NOT NULL DEFAULT '', categoria TEXT NOT NULL DEFAULT '', proveedor_id TEXT NOT NULL DEFAULT '', proveedor TEXT NOT NULL DEFAULT '',
  monto TEXT NOT NULL DEFAULT 'TOTAL');
CREATE TABLE IF NOT EXISTS despacho_items(despacho_id INTEGER NOT NULL REFERENCES despachos(id), articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  cantidad REAL NOT NULL, precio REAL NOT NULL);
CREATE TABLE IF NOT EXISTS mermas(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  bodega_id INTEGER NOT NULL, cantidad REAL NOT NULL, costo_unit REAL NOT NULL, motivo_id INTEGER NOT NULL REFERENCES motivos_merma(id),
  obs TEXT NOT NULL DEFAULT '', estado TEXT NOT NULL DEFAULT 'VIGENTE', usuario_id INTEGER REFERENCES usuarios(id));
CREATE TABLE IF NOT EXISTS salidas_tienda(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, tienda_id INTEGER NOT NULL REFERENCES tiendas(id),
  articulo_id INTEGER NOT NULL REFERENCES articulos(id), cantidad REAL NOT NULL, motivo TEXT NOT NULL, obs TEXT NOT NULL DEFAULT '', usuario_id INTEGER REFERENCES usuarios(id));
CREATE TABLE IF NOT EXISTS pos_consumos(id INTEGER PRIMARY KEY, referencia TEXT NOT NULL UNIQUE, tienda_id INTEGER NOT NULL REFERENCES tiendas(id),
  fecha TEXT NOT NULL, detalle TEXT NOT NULL DEFAULT '', estado TEXT NOT NULL DEFAULT 'VIGENTE', creado TEXT NOT NULL, anulado TEXT);
CREATE TABLE IF NOT EXISTS inventarios(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, bodega_id INTEGER NOT NULL, estado TEXT NOT NULL DEFAULT 'ABIERTO',
  obs TEXT NOT NULL DEFAULT '', usuario_id INTEGER REFERENCES usuarios(id), cerrado TEXT, seccion TEXT NOT NULL DEFAULT '', categorias TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS pos_transferencias(id INTEGER PRIMARY KEY, referencia TEXT NOT NULL UNIQUE, tipo TEXT NOT NULL CHECK(tipo IN ('SALIDA','ENTRADA')),
  tienda_id INTEGER NOT NULL REFERENCES tiendas(id), contraparte_id INTEGER REFERENCES tiendas(id), fecha TEXT NOT NULL, detalle TEXT NOT NULL DEFAULT '',
  estado TEXT NOT NULL DEFAULT 'VIGENTE', creado TEXT NOT NULL, anulado TEXT);
CREATE TABLE IF NOT EXISTS fudo_equivalencias(id INTEGER PRIMARY KEY, tienda_id INTEGER NOT NULL REFERENCES tiendas(id), fudo_id TEXT NOT NULL,
  fudo_nombre TEXT NOT NULL, fudo_unidad TEXT NOT NULL DEFAULT '', articulo_id INTEGER NOT NULL REFERENCES articulos(id), factor REAL NOT NULL,
  base REAL NOT NULL DEFAULT 0, enviado REAL NOT NULL DEFAULT 0, base_fecha TEXT NOT NULL, creado TEXT NOT NULL,
  UNIQUE(tienda_id, fudo_id), UNIQUE(tienda_id, articulo_id));
CREATE TABLE IF NOT EXISTS fudo_stock_envios(despacho_id INTEGER PRIMARY KEY REFERENCES despachos(id), tienda_id INTEGER NOT NULL REFERENCES tiendas(id),
  estado TEXT NOT NULL, items TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '', actualizado TEXT NOT NULL, manual INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS fudo_sincronizaciones(id INTEGER PRIMARY KEY, tienda_id INTEGER NOT NULL REFERENCES tiendas(id), fecha TEXT NOT NULL,
  creado TEXT NOT NULL, usuario_id INTEGER REFERENCES usuarios(id), estado TEXT NOT NULL DEFAULT 'VIGENTE', detalle TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS pos_inventarios(referencia TEXT PRIMARY KEY, inventario_id INTEGER NOT NULL REFERENCES inventarios(id));
CREATE TABLE IF NOT EXISTS inventario_items(inventario_id INTEGER NOT NULL REFERENCES inventarios(id) ON DELETE CASCADE,
  articulo_id INTEGER NOT NULL REFERENCES articulos(id), stock_sistema REAL NOT NULL, conteo REAL, diferencia REAL,
  PRIMARY KEY(inventario_id, articulo_id));
CREATE TABLE IF NOT EXISTS movimientos(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, articulo_id INTEGER NOT NULL REFERENCES articulos(id),
  bodega_id INTEGER NOT NULL, tipo TEXT NOT NULL, cantidad REAL NOT NULL, saldo REAL NOT NULL, costo_unit REAL NOT NULL DEFAULT 0,
  proveedor_id INTEGER REFERENCES proveedores(id), tienda_destino_id INTEGER REFERENCES tiendas(id), motivo_id INTEGER REFERENCES motivos_merma(id),
  doc_tipo TEXT, doc_id INTEGER, referencia TEXT NOT NULL DEFAULT '', obs TEXT NOT NULL DEFAULT '', usuario_id INTEGER REFERENCES usuarios(id));
CREATE INDEX IF NOT EXISTS ix_mov_art ON movimientos(articulo_id, fecha);
CREATE INDEX IF NOT EXISTS ix_mov_doc ON movimientos(doc_tipo, doc_id);
CREATE INDEX IF NOT EXISTS ix_mov_fecha ON movimientos(fecha);
CREATE INDEX IF NOT EXISTS ix_precios ON historial_precios(articulo_id, fecha);
"""


class Archivo:
    def __init__(self, nombre, contenido):
        self.nombre, self.contenido = nombre, contenido


class ApiError(Exception):
    def __init__(self, status, mensaje):
        super().__init__(mensaje)
        self.status, self.mensaje = status, mensaje


def conectar():
    db = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def rows(db, sql, *a):
    return [dict(r) for r in db.execute(sql, a).fetchall()]


def row(db, sql, *a):
    r = db.execute(sql, a).fetchone()
    return dict(r) if r else None


def scalar(db, sql, *a):
    r = db.execute(sql, a).fetchone()
    return r[0] if r and r[0] is not None else 0


# ---------------------------------------------------------------- validación

def txt(v, nombre, req=True, maximo=200):
    v = "" if v is None else str(v).strip()
    if req and not v:
        raise ApiError(400, f"Falta {nombre}.")
    if len(v) > maximo:
        raise ApiError(400, f"{nombre} es demasiado largo (máximo {maximo}).")
    return v


def num(v, nombre, minimo=0.0, estricto=False):
    try:
        if isinstance(v, bool):
            raise ValueError
        n = round(float(v), 5)
    except (TypeError, ValueError):
        raise ApiError(400, f"{nombre} debe ser un número.")
    if n != n or n in (float("inf"), float("-inf")) or n < minimo or (estricto and n <= minimo):
        raise ApiError(400, f"{nombre} debe ser mayor {'que' if estricto else 'o igual a'} {minimo:g}.")
    return n


def entero(v, nombre):
    try:
        if isinstance(v, bool):
            raise ValueError
        return int(v)
    except (TypeError, ValueError):
        raise ApiError(400, f"Falta seleccionar {nombre}.")


def fecha_valida(v, nombre="la fecha"):
    if not v:
        return date.today().isoformat()
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ApiError(400, f"{nombre} no es válida.")


def normalizar_rut(v):
    limpio = re.sub(r"[^0-9kK]", "", str(v or "")).upper()
    if len(limpio) < 2 or not limpio[:-1].isdigit():
        raise ApiError(400, "El RUT no es válido.")
    cuerpo, dv = limpio[:-1].lstrip("0"), limpio[-1]
    if dv_rut(cuerpo) != dv:
        raise ApiError(400, "El RUT no es válido: el dígito verificador no coincide.")
    return f"{int(cuerpo):,}".replace(",", ".") + "-" + dv


def dv_rut(cuerpo):
    suma, factor = 0, 2
    for d in reversed(str(cuerpo)):
        suma += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    r = 11 - suma % 11
    return {11: "0", 10: "K"}.get(r, str(r))


def hash_password(p, salt=None, iters=240000):
    salt = salt or secrets.token_hex(16)
    d = hashlib.pbkdf2_hmac("sha256", p.encode(), salt.encode(), iters).hex()
    return f"{iters}${salt}${d}"


def verificar_password(p, guardado):
    iters, salt, _ = guardado.split("$")
    return hmac.compare_digest(hash_password(p, salt, int(iters)), guardado)


def validar_password(p):
    if not isinstance(p, str) or len(p) < 8:
        raise ApiError(400, "La contraseña debe tener al menos 8 caracteres.")
    return p


def iva_actual(db):
    return float(scalar(db, "SELECT valor FROM config WHERE clave='iva'") or 19)


# ---------------------------------------------------------------- stock y documentos

def stock_de(db, bodega, articulo):
    return float(scalar(db, "SELECT cantidad FROM stock WHERE bodega_id=? AND articulo_id=?", bodega, articulo))


def articulo(db, art_id):
    a = row(db, "SELECT a.*, u.abreviatura unidad FROM articulos a JOIN unidades u ON u.id=a.unidad_id WHERE a.id=?", art_id)
    if not a:
        raise ApiError(404, "Artículo no encontrado.")
    return a


def costo_de(a):
    return a["costo"] or a["precio"] or 0


def mover(db, art_id, bodega, delta, tipo, uid, fecha, doc_tipo=None, doc_id=None, ref="", proveedor=None, destino=None,
          motivo=None, costo=None, obs=""):
    """Único punto que modifica stock: garantiza saldo no negativo y deja rastro en el historial."""
    a = articulo(db, art_id)
    nuevo = round(stock_de(db, bodega, art_id) + delta, 5)
    if nuevo < 0:
        raise ApiError(409, f"Stock insuficiente de {a['nombre']}: hay {stock_de(db, bodega, art_id):g} {a['unidad']} "
                            f"y se necesitan {abs(delta):g} {a['unidad']}.")
    db.execute("INSERT INTO stock(bodega_id,articulo_id,cantidad) VALUES(?,?,?) "
               "ON CONFLICT(bodega_id,articulo_id) DO UPDATE SET cantidad=excluded.cantidad", (bodega, art_id, nuevo))
    db.execute("INSERT INTO movimientos(fecha,articulo_id,bodega_id,tipo,cantidad,saldo,costo_unit,proveedor_id,tienda_destino_id,"
               "motivo_id,doc_tipo,doc_id,referencia,obs,usuario_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (f"{fecha} {datetime.now():%H:%M:%S}", art_id, bodega, tipo, round(delta, 5), nuevo,
                costo if costo is not None else costo_de(a), proveedor, destino, motivo, doc_tipo, doc_id, ref, obs, uid))


def actualizar_cpp(db, art_id, cantidad, costo_unit):
    """Costo promedio ponderado; debe llamarse antes de sumar la entrada al stock central."""
    a = articulo(db, art_id)
    actual = max(stock_de(db, CENTRAL, art_id), 0)
    base = costo_de(a) if actual > 0 else 0
    nuevo = (actual * base + cantidad * costo_unit) / (actual + cantidad)
    db.execute("UPDATE articulos SET costo=? WHERE id=?", (round(nuevo, 5), art_id))


def lineas(items, nombre_precio=None):
    if not isinstance(items, list) or not items:
        raise ApiError(400, "Debes agregar al menos una línea de detalle.")
    vistos, out = set(), []
    for i in items:
        if not isinstance(i, dict):
            raise ApiError(400, "Detalle inválido.")
        aid = entero(i.get("articulo_id"), "el artículo en cada línea")
        if aid in vistos:
            raise ApiError(400, "Hay un artículo repetido en el detalle.")
        vistos.add(aid)
        ln = {"articulo_id": aid, "cantidad": num(i.get("cantidad"), "La cantidad", 0, True)}
        if nombre_precio:
            ln["precio"] = num(i.get("precio"), nombre_precio)
        out.append(ln)
    return out


TIPOS_DOC_COMPRA = {"FACTURA": "Factura", "BOLETA": "Boleta", "GUIA": "Guía de despacho"}


def crear_compra(db, uid, d):
    fecha = fecha_valida(d.get("fecha"))
    tipo_doc = d.get("tipo_documento")
    if tipo_doc not in TIPOS_DOC_COMPRA:
        raise ApiError(400, "Indica si el documento es factura, boleta o guía de despacho.")
    prov = entero(d.get("proveedor_id"), "el proveedor")
    proveedor = row(db, "SELECT * FROM proveedores WHERE id=? AND activo=1", prov)
    if not proveedor:
        raise ApiError(400, "Proveedor no válido o inactivo.")
    items = lineas(d.get("items"), "El precio")
    pct = iva_actual(db)
    neto = round(sum(i["cantidad"] * i["precio"] for i in items), 2)
    iva = round(neto * pct / 100, 2)
    cur = db.execute("INSERT INTO compras(fecha,proveedor_id,tipo_documento,documento,iva_pct,neto,iva,total,obs,usuario_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (fecha, prov, tipo_doc, txt(d.get("documento"), "El documento", False, 40), pct, neto, iva, round(neto + iva, 2),
                      txt(d.get("obs"), "La observación", False, 500), uid))
    cid = cur.lastrowid
    ref = f"Compra #{cid} · {TIPOS_DOC_COMPRA[tipo_doc]}" + (f" {d.get('documento')}" if d.get("documento") else "")
    for i in items:
        a = articulo(db, i["articulo_id"])
        if a["tipo"] != "INSUMO":
            raise ApiError(400, f"{a['nombre']} no es un insumo: solo los insumos se compran a proveedores.")
        db.execute("INSERT INTO compra_items VALUES(?,?,?,?)", (cid, a["id"], i["cantidad"], i["precio"]))
        db.execute("INSERT INTO historial_precios(articulo_id,proveedor_id,compra_id,fecha,precio) VALUES(?,?,?,?,?)",
                   (a["id"], prov, cid, fecha, i["precio"]))
        actualizar_cpp(db, a["id"], i["cantidad"], i["precio"])
        ultimo = scalar(db, "SELECT precio FROM historial_precios WHERE articulo_id=? ORDER BY fecha DESC, id DESC LIMIT 1", a["id"])
        db.execute("UPDATE articulos SET precio=? WHERE id=?", (ultimo, a["id"]))
        mover(db, a["id"], CENTRAL, i["cantidad"], "COMPRA", uid, fecha, "COMPRA", cid, ref, proveedor=prov, costo=i["precio"])
    return cid


def crear_devolucion(db, uid, d):
    """Saca insumos de la bodega central hacia el proveedor. No toca el costo promedio ni el historial de precios."""
    fecha = fecha_valida(d.get("fecha"))
    prov = entero(d.get("proveedor_id"), "el proveedor")
    if not row(db, "SELECT id FROM proveedores WHERE id=? AND activo=1", prov):
        raise ApiError(400, "Proveedor no válido o inactivo.")
    motivo = txt(d.get("motivo"), "el motivo", True, 200)
    documento = txt(d.get("documento"), "El documento", False, 40)
    items = lineas(d.get("items"), "El precio")
    pct = iva_actual(db)
    neto = round(sum(i["cantidad"] * i["precio"] for i in items), 2)
    iva = round(neto * pct / 100, 2)
    did = db.execute("INSERT INTO devoluciones(fecha,proveedor_id,documento,motivo,iva_pct,neto,iva,total,usuario_id) VALUES(?,?,?,?,?,?,?,?,?)",
                     (fecha, prov, documento, motivo, pct, neto, iva, round(neto + iva, 2), uid)).lastrowid
    ref = f"Devolución #{did}" + (f" · Doc. {documento}" if documento else "")
    for i in items:
        a = articulo(db, i["articulo_id"])
        if a["tipo"] != "INSUMO":
            raise ApiError(400, f"{a['nombre']} no se devuelve a proveedores: los productos y subproductos no están permitidos.")
        db.execute("INSERT INTO devolucion_items VALUES(?,?,?,?)", (did, a["id"], i["cantidad"], i["precio"]))
        mover(db, a["id"], CENTRAL, -i["cantidad"], "DEVOLUCION_PROVEEDOR", uid, fecha, "DEVOLUCION", did, ref, proveedor=prov, obs=motivo)
    return did


def receta_de(db, art_id):
    r = row(db, "SELECT * FROM recetas WHERE articulo_id=?", art_id)
    if r:
        r["items"] = rows(db, "SELECT ri.articulo_id, ri.cantidad, a.codigo, a.nombre, a.tipo, a.costo, a.precio, u.abreviatura unidad "
                              "FROM receta_items ri JOIN articulos a ON a.id=ri.articulo_id JOIN unidades u ON u.id=a.unidad_id "
                              "WHERE ri.receta_id=? ORDER BY a.nombre", art_id)
    return r


def costo_teorico(db, art_id, memo=None):
    """Costo unitario según receta vigente, resolviendo subproductos recursivamente.
    Los insumos se valorizan a su último precio (el de la última compra o el editado a mano), no al costo promedio."""
    memo = {} if memo is None else memo
    if art_id in memo:
        return memo[art_id]
    r = receta_de(db, art_id)
    if not r:
        a = articulo(db, art_id)
        memo[art_id] = (a["precio"] or a["costo"] or 0) if a["tipo"] == "INSUMO" else costo_de(a)
    else:
        memo[art_id] = sum(i["cantidad"] * costo_teorico(db, i["articulo_id"], memo) for i in r["items"]) / r["rendimiento"]
    return memo[art_id]


def crear_produccion(db, uid, d):
    fecha = fecha_valida(d.get("fecha"))
    art_id = entero(d.get("articulo_id"), "el producto a fabricar")
    cantidad = num(d.get("cantidad"), "La cantidad", 0, True)
    r = receta_de(db, art_id)
    if not r or not r["items"]:
        raise ApiError(400, "Este artículo no tiene receta: ingrésala antes de producir.")
    factor = cantidad / r["rendimiento"]
    faltantes = []
    for i in r["items"]:
        req = round(i["cantidad"] * factor, 5)
        hay = stock_de(db, CENTRAL, i["articulo_id"])
        if hay < req:
            faltantes.append(f"{i['nombre']}: faltan {round(req - hay, 5):g} {i['unidad']}")
    if faltantes:
        raise ApiError(409, "No hay stock suficiente para producir. " + "; ".join(faltantes) + ".")
    total = round(sum(i["cantidad"] * factor * (i["costo"] or i["precio"] or 0) for i in r["items"]), 2)
    pid = db.execute("INSERT INTO producciones(fecha,articulo_id,cantidad,costo_total,obs,usuario_id) VALUES(?,?,?,?,?,?)",
                     (fecha, art_id, cantidad, total, txt(d.get("obs"), "La observación", False, 500), uid)).lastrowid
    ref = f"Producción #{pid}"
    for i in r["items"]:
        mover(db, i["articulo_id"], CENTRAL, -round(i["cantidad"] * factor, 5), "CONSUMO_PRODUCCION", uid, fecha, "PRODUCCION", pid, ref)
    actualizar_cpp(db, art_id, cantidad, total / cantidad)
    mover(db, art_id, CENTRAL, cantidad, "PRODUCCION", uid, fecha, "PRODUCCION", pid, ref, costo=round(total / cantidad, 5))
    return pid


def crear_despacho(db, uid, d):
    fecha = fecha_valida(d.get("fecha"))
    tienda_id = entero(d.get("tienda_id"), "la tienda de destino")
    tienda = row(db, "SELECT * FROM tiendas WHERE id=? AND activo=1", tienda_id)
    if not tienda:
        raise ApiError(400, "Tienda no válida o inactiva.")
    items = lineas(d.get("items"))
    pct = iva_actual(db)
    detalle = []
    for i in items:
        a = articulo(db, i["articulo_id"])
        if not (a["tipo"] == "PRODUCTO" or a["desechable"]):
            raise ApiError(400, f"{a['nombre']} no se despacha a tiendas: solo productos terminados, desechables o de aseo e insumos de puntos de venta.")
        detalle.append((a, i["cantidad"]))
    neto = round(sum(c * a["precio"] for a, c in detalle), 2)
    iva = round(neto * pct / 100, 2)
    did = db.execute("INSERT INTO despachos(fecha,tienda_id,transportista,patente,obs,iva_pct,neto,iva,total,usuario_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (fecha, tienda_id, txt(d.get("transportista"), "El transportista", False, 100), txt(d.get("patente"), "La patente", False, 12).upper(),
                      txt(d.get("obs"), "La observación", False, 500), pct, neto, iva, round(neto + iva, 2), uid)).lastrowid
    ref = f"Guía {did:06d}"
    for a, c in detalle:
        db.execute("INSERT INTO despacho_items VALUES(?,?,?,?)", (did, a["id"], c, a["precio"]))
        mover(db, a["id"], CENTRAL, -c, "DESPACHO", uid, fecha, "DESPACHO", did, ref, destino=tienda_id)
        mover(db, a["id"], tienda_id, c, "RECEPCION_TIENDA", uid, fecha, "DESPACHO", did, ref, destino=tienda_id)
    return did


def crear_merma(db, uid, d, bodega):
    fecha = fecha_valida(d.get("fecha"))
    a = articulo(db, entero(d.get("articulo_id"), "el artículo"))
    cantidad = num(d.get("cantidad"), "La cantidad", 0, True)
    motivo = entero(d.get("motivo_id"), "el motivo")
    if not row(db, "SELECT id FROM motivos_merma WHERE id=?", motivo):
        raise ApiError(400, "Motivo de merma no válido.")
    obs = txt(d.get("obs"), "La observación", False, 500)
    mid = db.execute("INSERT INTO mermas(fecha,articulo_id,bodega_id,cantidad,costo_unit,motivo_id,obs,usuario_id) VALUES(?,?,?,?,?,?,?,?)",
                     (fecha, a["id"], bodega, cantidad, costo_de(a), motivo, obs, uid)).lastrowid
    mover(db, a["id"], bodega, -cantidad, "MERMA", uid, fecha, "MERMA", mid, f"Merma #{mid}", motivo=motivo, obs=obs)
    return mid


def anular(db, uid, tabla, doc_tipo, doc_id):
    doc = row(db, f"SELECT * FROM {tabla} WHERE id=?", doc_id)
    if not doc:
        raise ApiError(404, "Documento no encontrado.")
    if doc["estado"] == "ANULADO":
        raise ApiError(409, "El documento ya está anulado.")
    hoy = date.today().isoformat()
    for m in rows(db, "SELECT * FROM movimientos WHERE doc_tipo=? AND doc_id=? AND tipo<>'ANULACION'", doc_tipo, doc_id):
        mover(db, m["articulo_id"], m["bodega_id"], -m["cantidad"], "ANULACION", uid, hoy, doc_tipo, doc_id, "Anula " + m["referencia"],
              proveedor=m["proveedor_id"], destino=m["tienda_destino_id"], motivo=m["motivo_id"], costo=m["costo_unit"])
    db.execute(f"UPDATE {tabla} SET estado='ANULADO' WHERE id=?", (doc_id,))
    if doc_tipo == "COMPRA":
        ids = [r["articulo_id"] for r in rows(db, "SELECT articulo_id FROM compra_items WHERE compra_id=?", doc_id)]
        db.execute("DELETE FROM historial_precios WHERE compra_id=?", (doc_id,))
        for aid in ids:
            p = db.execute("SELECT precio FROM historial_precios WHERE articulo_id=? ORDER BY fecha DESC, id DESC LIMIT 1", (aid,)).fetchone()
            if p:
                db.execute("UPDATE articulos SET precio=? WHERE id=?", (p[0], aid))


def articulos_de_bodega(db, bodega, seccion=""):
    filtro = f"AND {SECCIONES[seccion]}" if seccion else "" if bodega == CENTRAL else "AND (a.tipo='PRODUCTO' OR a.desechable=1)"
    return rows(db, f"""SELECT a.id articulo_id, a.codigo, a.nombre, a.tipo, a.desechable, a.stock_minimo, a.precio, a.costo,
        c.punto_venta, c.id categoria_id, c.nombre categoria, u.abreviatura unidad, COALESCE(s.cantidad,0) cantidad
        FROM articulos a JOIN categorias c ON c.id=a.categoria_id JOIN unidades u ON u.id=a.unidad_id
        LEFT JOIN stock s ON s.articulo_id=a.id AND s.bodega_id=?
        WHERE a.activo=1 {filtro} ORDER BY a.tipo, a.nombre""", bodega)


# ---------------------------------------------------------------- enrutador

RUTAS = []


def ruta(metodo, patron, modulo=None, nivel=1, publica=False, accion=None):
    assert accion is None or accion in ACCIONES_IDS, accion
    def deco(fn):
        RUTAS.append((metodo, re.compile("^" + patron + "$"), modulo, nivel, publica, accion, fn))
        return fn
    return deco


class Ctx:
    def __init__(self, db, user, body, q, headers=None):
        self.db, self.user, self.body, self.q, self.headers = db, user, body, q, headers or {}

    @property
    def uid(self):
        return self.user["id"]

    def bodega(self, valor, requerida=True):
        """Bodega solicitada, restringida a la tienda propia si el usuario está asociado a una."""
        propia = self.user.get("tienda_id")
        if valor in (None, ""):
            if propia:
                return propia
            if requerida:
                return CENTRAL
            return None
        b = entero(valor, "la bodega")
        if propia and b != propia:
            raise ApiError(403, "Tu usuario solo tiene acceso a la bodega de su tienda.")
        if b != CENTRAL and not row(self.db, "SELECT id FROM tiendas WHERE id=?", b):
            raise ApiError(404, "Tienda no encontrada.")
        return b

    def sin_tienda(self):
        if self.user.get("tienda_id"):
            raise ApiError(403, "Esta información no está disponible para usuarios de tienda.")

    def rango(self, dias=90):
        hasta = fecha_valida(self.q.get("hasta"))
        desde = fecha_valida(self.q.get("desde") or (date.fromisoformat(hasta) - timedelta(days=dias)).isoformat())
        return desde, hasta


FALLOS_LOGIN = {}


def cargar_usuario(db, u):
    u = dict(u)
    u.pop("password", None)
    u["permisos"] = json.loads(u["permisos"])
    return u


@ruta("GET", "/api/estado", publica=True)
def estado(c):
    cfg = {r["clave"]: r["valor"] for r in rows(c.db, "SELECT * FROM config WHERE clave='logo'")}
    return {"requiere_instalacion": not scalar(c.db, "SELECT COUNT(*) FROM usuarios"), "requiere_clave": bool(CLAVE_INSTALACION), "logo": cfg.get("logo"),
            "usuario": c.user, "modulos": [{"id": m, "nombre": n} for m, n in MODULOS],
            "acciones": [{"id": a, "nombre": n, "modulo": m} for a, n, m in ACCIONES]}


@ruta("POST", "/api/instalar", publica=True)
def instalar(c):
    if scalar(c.db, "SELECT COUNT(*) FROM usuarios"):
        raise ApiError(409, "El sistema ya fue instalado.")
    d = c.body
    if CLAVE_INSTALACION and not hmac.compare_digest(str(d.get("clave") or "").strip().encode(), CLAVE_INSTALACION.encode()):
        raise ApiError(403, "La clave de instalación no es correcta.")
    perfil = scalar(c.db, "SELECT id FROM perfiles WHERE nombre='Administrador'")
    uid = c.db.execute("INSERT INTO usuarios(username,nombre,password,perfil_id) VALUES(?,?,?,?)",
                       (txt(d.get("username"), "El usuario", True, 40), txt(d.get("nombre"), "El nombre", True, 100),
                        hash_password(validar_password(d.get("password"))), perfil)).lastrowid
    if d.get("demo"):
        cargar_demo(c.db, uid)
    return {"ok": True}, nueva_sesion(c.db, uid)


def nueva_sesion(db, uid):
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sesiones WHERE expira<?", (time.time(),))
    db.execute("INSERT INTO sesiones VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), uid, time.time() + SESION_HORAS * 3600))
    return token


@ruta("POST", "/api/login", publica=True)
def login(c):
    nombre = str(c.body.get("username") or "").strip().lower()
    n, hasta = FALLOS_LOGIN.get(nombre, (0, 0))
    if n >= 5 and time.time() < hasta:
        raise ApiError(429, "Demasiados intentos fallidos. Espera unos minutos.")
    u = row(c.db, "SELECT * FROM usuarios WHERE username=? AND activo=1", nombre)
    if not u or not verificar_password(str(c.body.get("password") or ""), u["password"]):
        if len(FALLOS_LOGIN) > 10000:
            FALLOS_LOGIN.clear()
        FALLOS_LOGIN[nombre] = (n + 1, time.time() + 300)
        raise ApiError(401, "Usuario o contraseña incorrectos.")
    FALLOS_LOGIN.pop(nombre, None)
    return {"ok": True}, nueva_sesion(c.db, u["id"])


@ruta("POST", "/api/logout")
def logout(c):
    c.db.execute("DELETE FROM sesiones WHERE usuario_id=? AND token=?", (c.uid, c.user["_token"]))
    return {"ok": True}, ""


@ruta("POST", "/api/cuenta/password")
def cambiar_password(c):
    u = row(c.db, "SELECT password FROM usuarios WHERE id=?", c.uid)
    if not verificar_password(str(c.body.get("actual") or ""), u["password"]):
        raise ApiError(400, "La contraseña actual no es correcta.")
    c.db.execute("UPDATE usuarios SET password=? WHERE id=?", (hash_password(validar_password(c.body.get("nueva"))), c.uid))
    c.db.execute("DELETE FROM sesiones WHERE usuario_id=? AND token<>?", (c.uid, c.user["_token"]))
    return {"ok": True}


@ruta("GET", "/api/catalogos")
def catalogos(c):
    """Listas de selección para formularios; sin stock ni datos sensibles."""
    db = c.db
    tiendas = rows(db, "SELECT id,nombre,direccion,comuna,region,activo FROM tiendas ORDER BY nombre")
    if c.user.get("tienda_id"):
        tiendas = [t for t in tiendas if t["id"] == c.user["tienda_id"]]
    return {
        "iva": iva_actual(db), "tiendas": tiendas,
        "proveedores": rows(db, "SELECT id,nombre,rut,activo FROM proveedores ORDER BY nombre"),
        "categorias": rows(db, "SELECT * FROM categorias ORDER BY nombre"),
        "unidades": rows(db, "SELECT * FROM unidades ORDER BY nombre"),
        "motivos": rows(db, "SELECT * FROM motivos_merma ORDER BY nombre"),
        "articulos": rows(db, "SELECT a.id,a.codigo,a.nombre,a.tipo,a.desechable,a.precio,c.punto_venta,c.nombre categoria,u.abreviatura unidad FROM articulos a "
                              "JOIN categorias c ON c.id=a.categoria_id JOIN unidades u ON u.id=a.unidad_id WHERE a.activo=1 ORDER BY a.nombre"),
    }


# ---------------------------------------------------------------- usuarios y perfiles

@ruta("GET", "/api/usuarios", "usuarios")
def usuarios_lista(c):
    return rows(c.db, "SELECT u.id,u.username,u.nombre,u.perfil_id,u.tienda_id,u.activo,p.nombre perfil,t.nombre tienda FROM usuarios u "
                      "JOIN perfiles p ON p.id=u.perfil_id LEFT JOIN tiendas t ON t.id=u.tienda_id ORDER BY u.nombre")


def quedan_admins(db, sin_id=None):
    n = 0
    for u in rows(db, "SELECT u.id,p.permisos FROM usuarios u JOIN perfiles p ON p.id=u.perfil_id WHERE u.activo=1"):
        if u["id"] != sin_id and json.loads(u["permisos"]).get("usuarios", 0) >= 2:
            n += 1
    return n > 0


@ruta("POST", "/api/usuarios", "usuarios", 2)
def usuarios_crear(c):
    d = c.body
    return {"id": c.db.execute("INSERT INTO usuarios(username,nombre,password,perfil_id,tienda_id) VALUES(?,?,?,?,?)",
            (txt(d.get("username"), "El usuario", True, 40), txt(d.get("nombre"), "El nombre", True, 100),
             hash_password(validar_password(d.get("password"))), entero(d.get("perfil_id"), "el perfil"), d.get("tienda_id") or None)).lastrowid}


@ruta("PUT", r"/api/usuarios/(\d+)", "usuarios", 2)
def usuarios_editar(c, uid):
    d, uid = c.body, int(uid)
    if not row(c.db, "SELECT id FROM usuarios WHERE id=?", uid):
        raise ApiError(404, "Usuario no encontrado.")
    c.db.execute("UPDATE usuarios SET username=?,nombre=?,perfil_id=?,tienda_id=?,activo=? WHERE id=?",
                 (txt(d.get("username"), "El usuario", True, 40), txt(d.get("nombre"), "El nombre", True, 100), entero(d.get("perfil_id"), "el perfil"),
                  d.get("tienda_id") or None, 1 if d.get("activo", True) else 0, uid))
    if d.get("password"):
        c.db.execute("UPDATE usuarios SET password=? WHERE id=?", (hash_password(validar_password(d["password"])), uid))
    if d.get("password") or not d.get("activo", True):
        c.db.execute("DELETE FROM sesiones WHERE usuario_id=? AND token<>?", (uid, c.user["_token"]))
    if not quedan_admins(c.db):
        raise ApiError(409, "Debe quedar al menos un usuario activo que administre usuarios.")
    return {"ok": True}


@ruta("GET", "/api/perfiles", "usuarios")
def perfiles_lista(c):
    out = rows(c.db, "SELECT p.*,(SELECT COUNT(*) FROM usuarios u WHERE u.perfil_id=p.id) usuarios FROM perfiles p ORDER BY p.nombre")
    for p in out:
        p["permisos"] = json.loads(p["permisos"])
    return out


def permisos_validos(v):
    if not isinstance(v, dict):
        raise ApiError(400, "Permisos inválidos.")
    out = {m: int(v[m]) for m in TODOS if m in v and int(v[m]) in (1, 2)}
    for a, _, modulo in ACCIONES:  # una acción crítica solo tiene sentido si el perfil puede editar su módulo
        if v.get("acc_" + a) and (out.get(modulo) == 2 if modulo else 2 in out.values()):
            out["acc_" + a] = 1
    return json.dumps(out)


@ruta("POST", "/api/perfiles", "usuarios", 2)
def perfiles_crear(c):
    return {"id": c.db.execute("INSERT INTO perfiles(nombre,permisos) VALUES(?,?)",
            (txt(c.body.get("nombre"), "El nombre", True, 60), permisos_validos(c.body.get("permisos", {})))).lastrowid}


@ruta("PUT", r"/api/perfiles/(\d+)", "usuarios", 2)
def perfiles_editar(c, pid):
    if scalar(c.db, "SELECT COUNT(*) FROM perfiles WHERE id=? AND nombre=?", int(pid), PERFIL_ADMIN) and str(c.body.get("nombre") or "").strip() != PERFIL_ADMIN:
        raise ApiError(409, "El perfil Administrador no se puede renombrar.")
    c.db.execute("UPDATE perfiles SET nombre=?,permisos=? WHERE id=?",
                 (txt(c.body.get("nombre"), "El nombre", True, 60), permisos_validos(c.body.get("permisos", {})), int(pid)))
    if not quedan_admins(c.db):
        raise ApiError(409, "Debe quedar al menos un usuario activo que administre usuarios.")
    return {"ok": True}


@ruta("DELETE", r"/api/perfiles/(\d+)", "usuarios", 2)
def perfiles_borrar(c, pid):
    c.db.execute("DELETE FROM perfiles WHERE id=?", (int(pid),))
    return {"ok": True}


# ---------------------------------------------------------------- maestros

def crud_simple(tabla, modulo, campos, validar_edicion=None):
    ruta_base = f"/api/{tabla}"

    def limpiar(body):
        return [fn(body.get(k)) for k, fn in campos]

    @ruta("GET", ruta_base, modulo)
    def listar(c):
        return rows(c.db, f"SELECT * FROM {tabla} ORDER BY {campos[0][0]}")

    @ruta("POST", ruta_base, modulo, 2)
    def crear(c):
        ks = ",".join(k for k, _ in campos)
        marcas = ",".join("?" * len(campos))
        return {"id": c.db.execute(f"INSERT INTO {tabla}({ks}) VALUES({marcas})", limpiar(c.body)).lastrowid}

    @ruta("PUT", ruta_base + r"/(\d+)", modulo, 2)
    def editar(c, i):
        if validar_edicion:
            validar_edicion(c, int(i), dict(zip((k for k, _ in campos), limpiar(c.body))))
        ks = ",".join(f"{k}=?" for k, _ in campos)
        c.db.execute(f"UPDATE {tabla} SET {ks} WHERE id=?", [*limpiar(c.body), int(i)])
        if "activo" in c.body:
            c.db.execute(f"UPDATE {tabla} SET activo=? WHERE id=?", (1 if c.body["activo"] else 0, int(i)))
        return {"ok": True}

    @ruta("DELETE", ruta_base + r"/(\d+)", modulo, 2, accion="eliminar_registros")
    def borrar(c, i):
        c.db.execute(f"DELETE FROM {tabla} WHERE id=?", (int(i),))
        return {"ok": True}


nombre_campo = lambda v: txt(v, "El nombre", True, 120)
crud_simple("proveedores", "proveedores", [("nombre", nombre_campo), ("rut", normalizar_rut)])
def validar_tipo_categoria(c, i, v):
    cat = row(c.db, "SELECT * FROM categorias WHERE id=?", i)
    if not cat or cat["de_productos"] == v["de_productos"]:
        return
    if cat["punto_venta"]:
        raise ApiError(409, "Las categorías de puntos de venta son siempre de no productos.")
    if scalar(c.db, "SELECT COUNT(*) FROM articulos WHERE categoria_id=?", i):
        raise ApiError(409, "Esta categoría tiene artículos: cámbialos de categoría antes de cambiar su tipo.")


crud_simple("categorias", "articulos", [("nombre", nombre_campo), ("de_productos", lambda v: 1 if v in (True, 1, "1") else 0)], validar_tipo_categoria)
crud_simple("unidades", "articulos", [("nombre", nombre_campo), ("abreviatura", lambda v: txt(v, "La abreviatura", True, 12))])
crud_simple("motivos_merma", "mermas", [("nombre", nombre_campo)])
crud_simple("tiendas", "tiendas", [("nombre", nombre_campo), ("direccion", lambda v: txt(v, "La dirección", True, 200)),
                                   ("comuna", lambda v: txt(v, "La comuna", True, 80)), ("region", lambda v: txt(v, "La región", True, 80))])


@ruta("PUT", "/api/config/iva", "proveedores", 2)
def config_iva(c):
    v = num(c.body.get("iva"), "El IVA")
    if v > 100:
        raise ApiError(400, "El IVA no puede superar 100%.")
    c.db.execute("INSERT OR REPLACE INTO config VALUES('iva',?)", (str(v),))
    return {"ok": True}


@ruta("PUT", "/api/config/logo", "config", 2)
def config_logo(c):
    v = c.body.get("logo")
    if not v:
        c.db.execute("DELETE FROM config WHERE clave='logo'")
        return {"ok": True}
    if not re.match(r"^data:image/(png|jpeg|webp|svg\+xml);base64,[A-Za-z0-9+/=]+$", str(v)) or len(v) > MAX_LOGO * 4 / 3:
        raise ApiError(400, "El logo debe ser PNG, JPG, WEBP o SVG de hasta 2 MB.")
    c.db.execute("INSERT OR REPLACE INTO config VALUES('logo',?)", (v,))
    return {"ok": True}


def pos_token_guardado(db):
    """(origen, hash sha256) de la clave del POS: la variable NS_POS_TOKEN manda sobre la generada en Configuración."""
    env = os.environ.get("NS_POS_TOKEN", "").strip()
    if env:
        return "variable", hashlib.sha256(env.encode()).hexdigest()
    h = scalar(db, "SELECT valor FROM config WHERE clave='pos_token_hash'")
    return ("configuracion", h) if h else (None, None)


@ruta("GET", "/api/config/pos", "config", 2)
def config_pos(c):
    c.sin_tienda()
    origen, _ = pos_token_guardado(c.db)
    ultimo = row(c.db, "SELECT creado FROM pos_consumos ORDER BY id DESC LIMIT 1")
    return {"configurado": bool(origen), "origen": origen, "consumos": scalar(c.db, "SELECT COUNT(*) FROM pos_consumos"),
            "ultimo": ultimo["creado"] if ultimo else None}


@ruta("POST", "/api/config/pos/token", "config", 2)
def config_pos_token(c):
    """Genera una clave nueva (reemplaza la anterior). Solo se muestra esta vez: se guarda únicamente su huella."""
    c.sin_tienda()
    if os.environ.get("NS_POS_TOKEN", "").strip():
        raise ApiError(409, "La clave del POS está definida en el servidor (variable NS_POS_TOKEN); cámbiala ahí.")
    token = secrets.token_urlsafe(32)
    c.db.execute("INSERT OR REPLACE INTO config VALUES('pos_token_hash',?)", (hashlib.sha256(token.encode()).hexdigest(),))
    return {"token": token}


@ruta("DELETE", "/api/config/pos/token", "config", 2)
def config_pos_quitar(c):
    c.sin_tienda()
    c.db.execute("DELETE FROM config WHERE clave='pos_token_hash'")
    return {"ok": True}


@ruta("GET", "/api/config/respaldo", "config", 2, accion="respaldo")
def config_respaldo(c):
    with tempfile.TemporaryDirectory() as carpeta:
        ruta_copia = Path(carpeta) / "respaldo.db"
        copia = sqlite3.connect(ruta_copia)
        with copia:
            c.db.backup(copia)
        with copia:  # las credenciales de Fudo no salen en el archivo descargado
            copia.execute("UPDATE fudo_tiendas SET api_key='', api_secret=''")
        copia.execute("VACUUM")
        copia.close()
        return Archivo(f"nata_schlott_{datetime.now():%Y%m%d_%H%M}.db", ruta_copia.read_bytes())


# ---------------------------------------------------------------- artículos

def siguiente_codigo(db, tipo, desechable, punto_venta):
    """Correlativo por clasificación. Se ejecuta dentro de la transacción, así dos usuarios no obtienen el mismo."""
    prefijo = {"PRODUCTO": "P", "SUBPRODUCTO": "SP"}.get(tipo) or ("IPV" if punto_venta else "IDA" if desechable else "IN")
    usados = [int(m.group(1)) for r in rows(db, "SELECT codigo FROM articulos WHERE codigo LIKE ?", prefijo + "%")
              if (m := re.fullmatch(prefijo + r"(\d+)", r["codigo"], re.I))]
    return f"{prefijo}{max(usados, default=0) + 1:04d}"


def datos_articulo(db, d, codigo=None):
    """Sin codigo, se asigna el siguiente correlativo. Al editar se conserva el que ya tiene."""
    tipo = d.get("tipo")
    if tipo not in ("PRODUCTO", "SUBPRODUCTO", "INSUMO"):
        raise ApiError(400, "Tipo de artículo no válido.")
    # Un insumo de punto de venta se comporta como desechable: se despacha a tiendas y no entra en recetas
    punto_venta = scalar(db, "SELECT punto_venta FROM categorias WHERE id=?", entero(d.get("categoria_id"), "la categoría"))
    if bool(scalar(db, "SELECT de_productos FROM categorias WHERE id=?", entero(d.get("categoria_id"), "la categoría"))) != (tipo != "INSUMO"):
        raise ApiError(400, "Usa una categoría de productos para productos y subproductos, y una de no productos para los demás artículos.")
    if "punto_venta" in d and bool(d["punto_venta"]) != bool(punto_venta):  # la pestaña define el grupo: una categoría no puede cambiarlo
        raise ApiError(400, "Esa clasificación no pertenece a este grupo de artículos.")
    desechable = 1 if tipo == "INSUMO" and (d.get("desechable") or punto_venta) else 0
    return (tipo, desechable, entero(d.get("categoria_id"), "la categoría"),
            entero(d.get("unidad_id"), "la unidad de medida"), codigo or siguiente_codigo(db, tipo, desechable, punto_venta),
            txt(d.get("nombre"), "El nombre", True, 120), num(d.get("stock_minimo", 0), "El stock mínimo"), num(d.get("precio", 0), "El precio"))


@ruta("GET", "/api/articulos", "articulos")
def articulos_lista(c):
    return rows(c.db, """SELECT a.*, c.punto_venta, c.nombre categoria, u.abreviatura unidad, COALESCE(s.cantidad,0) stock
        FROM articulos a JOIN categorias c ON c.id=a.categoria_id JOIN unidades u ON u.id=a.unidad_id
        LEFT JOIN stock s ON s.articulo_id=a.id AND s.bodega_id=0 ORDER BY a.nombre""")


@ruta("POST", "/api/articulos", "articulos", 2)
def articulos_crear(c):
    v = datos_articulo(c.db, c.body)
    costo = v[7] if v[0] == "INSUMO" else 0
    return {"id": c.db.execute("INSERT INTO articulos(tipo,desechable,categoria_id,unidad_id,codigo,nombre,stock_minimo,precio,costo) VALUES(?,?,?,?,?,?,?,?,?)",
                               (*v, costo)).lastrowid, "codigo": v[4]}


@ruta("PUT", r"/api/articulos/(\d+)", "articulos", 2)
def articulos_editar(c, i):
    i = int(i)
    a = articulo(c.db, i)
    v = datos_articulo(c.db, c.body, a["codigo"])
    if a["tipo"] != v[0] and scalar(c.db, "SELECT COUNT(*) FROM movimientos WHERE articulo_id=?", i):
        raise ApiError(409, "No se puede cambiar el tipo de un artículo con movimientos.")
    if v[1] and scalar(c.db, "SELECT COUNT(*) FROM receta_items WHERE articulo_id=?", i):
        raise ApiError(409, "Este insumo está en una receta: quítalo de ella antes de marcarlo como desechable o de punto de venta.")
    c.db.execute("UPDATE articulos SET tipo=?,desechable=?,categoria_id=?,unidad_id=?,codigo=?,nombre=?,stock_minimo=?,precio=?,activo=? WHERE id=?",
                 (*v, 1 if c.body.get("activo", True) else 0, i))
    return {"ok": True}


RELACIONES_ARTICULO = (("movimientos", "movimientos en el historial"), ("compra_items", "compras"), ("devolucion_items", "devoluciones a proveedores"), ("salida_interna_items", "devoluciones de tiendas o consumos internos"), ("historial_precios", "historial de precios"),
                       ("producciones", "producciones"), ("despacho_items", "guías de despacho"), ("mermas", "mermas"), ("salidas_tienda", "ventas o consumos de tienda"),
                       ("recetas", "una receta propia"), ("receta_items", "recetas donde es ingrediente"), ("fudo_equivalencias", "equivalencias con insumos de Fudo"))


@ruta("DELETE", r"/api/articulos/(\d+)", "articulos", 2, accion="eliminar_registros")
def articulos_borrar(c, i):
    i = int(i)
    articulo(c.db, i)
    usos = [texto for tabla, texto in RELACIONES_ARTICULO if scalar(c.db, f"SELECT COUNT(*) FROM {tabla} WHERE articulo_id=?", i)]
    if scalar(c.db, "SELECT COUNT(*) FROM stock WHERE articulo_id=? AND cantidad<>0", i):
        usos.append("stock en bodega")
    if scalar(c.db, "SELECT COUNT(*) FROM inventario_items WHERE articulo_id=? AND conteo IS NOT NULL", i):
        usos.append("tomas de inventario")
    if usos:
        raise ApiError(409, f"No se puede eliminar porque tiene {', '.join(usos)}. Puedes dejarlo inactivo desde Editar.")
    # Las tomas incluyen todos los artículos: una línea sin conteo no es información que deba conservarse
    c.db.execute("DELETE FROM inventario_items WHERE articulo_id=?", (i,))
    c.db.execute("DELETE FROM stock WHERE articulo_id=?", (i,))
    c.db.execute("DELETE FROM articulos WHERE id=?", (i,))
    return {"ok": True}


# ---------------------------------------------------------------- recetas y producción

def max_producible(db, r):
    limite = None
    for i in r["items"]:
        posible = stock_de(db, CENTRAL, i["articulo_id"]) / i["cantidad"] * r["rendimiento"]
        limite = posible if limite is None else min(limite, posible)
    return round(limite or 0, 5)


@ruta("GET", "/api/recetas", "recetas")
def recetas_lista(c):
    return recetas_con_detalle(c.db)


@ruta("GET", "/api/produccion/recetas", "produccion")
def recetas_produccion(c):
    return recetas_con_detalle(c.db)


def recetas_con_detalle(db):
    out, memo = [], {}
    for a in rows(db, "SELECT a.id articulo_id,a.codigo,a.nombre,a.tipo,a.precio,u.abreviatura unidad FROM articulos a JOIN unidades u ON u.id=a.unidad_id "
                      "WHERE a.tipo IN ('PRODUCTO','SUBPRODUCTO') AND a.activo=1 ORDER BY a.tipo,a.nombre"):
        r = receta_de(db, a["articulo_id"])
        a["tiene_receta"] = bool(r)
        if r:
            for i in r["items"]:
                i["stock"] = stock_de(db, CENTRAL, i["articulo_id"])
                i["costo_unit"] = costo_teorico(db, i["articulo_id"], memo)
            a.update(rendimiento=r["rendimiento"], instrucciones=r["instrucciones"], items=r["items"],
                     costo_unit=costo_teorico(db, a["articulo_id"], memo), max_producible=max_producible(db, r))
        out.append(a)
    return out


def alcanza(db, desde, objetivo):
    if desde == objetivo:
        return True
    return any(alcanza(db, r["articulo_id"], objetivo) for r in rows(db, "SELECT articulo_id FROM receta_items WHERE receta_id=?", desde))


@ruta("PUT", r"/api/recetas/(\d+)", "recetas", 2)
def receta_guardar(c, art_id):
    art_id = int(art_id)
    a = articulo(c.db, art_id)
    if a["tipo"] == "INSUMO":
        raise ApiError(400, "Solo productos y subproductos llevan receta.")
    rend = num(c.body.get("rendimiento"), "El rendimiento", 0, True)
    items = lineas(c.body.get("items"))
    for i in items:
        ing = articulo(c.db, i["articulo_id"])
        if ing["tipo"] == "PRODUCTO" or ing["desechable"]:
            raise ApiError(400, f"{ing['nombre']} no puede ser ingrediente: usa insumos de receta o subproductos.")
        if alcanza(c.db, ing["id"], art_id):
            raise ApiError(400, f"{ing['nombre']} genera una receta circular con {a['nombre']}.")
    c.db.execute("INSERT INTO recetas VALUES(?,?,?) ON CONFLICT(articulo_id) DO UPDATE SET rendimiento=excluded.rendimiento, instrucciones=excluded.instrucciones",
                 (art_id, rend, txt(c.body.get("instrucciones"), "Las instrucciones", False, 4000)))
    c.db.execute("DELETE FROM receta_items WHERE receta_id=?", (art_id,))
    for i in items:
        c.db.execute("INSERT INTO receta_items VALUES(?,?,?)", (art_id, i["articulo_id"], i["cantidad"]))
    return {"ok": True}


@ruta("DELETE", r"/api/recetas/(\d+)", "recetas", 2, accion="eliminar_registros")
def receta_borrar(c, art_id):
    c.db.execute("DELETE FROM recetas WHERE articulo_id=?", (int(art_id),))
    return {"ok": True}


@ruta("GET", "/api/produccion", "produccion")
def produccion_lista(c):
    d, h = c.rango(365)
    return rows(c.db, """SELECT p.*, a.codigo, a.nombre, a.tipo, un.abreviatura unidad, u.nombre usuario FROM producciones p
        JOIN articulos a ON a.id=p.articulo_id JOIN unidades un ON un.id=a.unidad_id LEFT JOIN usuarios u ON u.id=p.usuario_id
        WHERE p.fecha BETWEEN ? AND ? ORDER BY p.fecha DESC, p.id DESC LIMIT 500""", d, h)


@ruta("GET", "/api/produccion/impresion", "produccion")
def produccion_impresion(c):
    """Producciones vigentes del rango, con los ingredientes que realmente descontó cada una."""
    d, h = c.rango(0)
    if d > h:
        raise ApiError(400, "La fecha desde no puede ser posterior a la fecha hasta.")
    ordenes = rows(c.db, """SELECT p.*, a.codigo, a.nombre, a.tipo, un.abreviatura unidad, u.nombre usuario FROM producciones p
        JOIN articulos a ON a.id=p.articulo_id JOIN unidades un ON un.id=a.unidad_id LEFT JOIN usuarios u ON u.id=p.usuario_id
        WHERE p.estado='VIGENTE' AND p.fecha BETWEEN ? AND ? ORDER BY p.fecha, p.id""", d, h)
    for o in ordenes:
        o["items"] = rows(c.db, """SELECT a.codigo, a.nombre, un.abreviatura unidad, -m.cantidad cantidad, m.costo_unit FROM movimientos m
            JOIN articulos a ON a.id=m.articulo_id JOIN unidades un ON un.id=a.unidad_id
            WHERE m.doc_tipo='PRODUCCION' AND m.doc_id=? AND m.tipo='CONSUMO_PRODUCCION' ORDER BY a.nombre""", o["id"])
    return {"desde": d, "hasta": h, "ordenes": ordenes}


@ruta("POST", "/api/produccion", "produccion", 2)
def produccion_crear(c):
    return {"id": crear_produccion(c.db, c.uid, c.body)}


@ruta("POST", r"/api/produccion/(\d+)/anular", "produccion", 2, accion="anular_produccion")
def produccion_anular(c, i):
    anular(c.db, c.uid, "producciones", "PRODUCCION", int(i))
    return {"ok": True}


# ---------------------------------------------------------------- compras

SQL_COMPRA = """SELECT co.*, p.nombre proveedor, p.rut, u.nombre usuario, f.documento factura_doc, f.fecha factura_fecha
    FROM compras co JOIN proveedores p ON p.id=co.proveedor_id LEFT JOIN usuarios u ON u.id=co.usuario_id
    LEFT JOIN compra_facturas f ON f.id=co.factura_id AND f.estado='VIGENTE'"""


@ruta("GET", "/api/compras", "compras")
def compras_lista(c):
    d, h = c.rango(365)
    return rows(c.db, SQL_COMPRA + " WHERE co.fecha BETWEEN ? AND ? ORDER BY co.fecha DESC, co.id DESC LIMIT 500", d, h)


# Guías de despacho de proveedor: ingresan el stock al recibirlas y quedan pendientes hasta que llega la factura, que las netea.
# La factura no mueve stock ni se suma a los reportes de compras: las guías ya lo hicieron. Solo registra el documento y la diferencia.

@ruta("GET", "/api/compras/guias-pendientes", "compras")
def compras_guias_pendientes(c):
    filtro, args = "", []
    if c.q.get("proveedor_id"):
        filtro, args = " AND co.proveedor_id=?", [entero(c.q["proveedor_id"], "el proveedor")]
    return rows(c.db, SQL_COMPRA + f" WHERE co.tipo_documento='GUIA' AND co.estado='VIGENTE' AND co.factura_id IS NULL{filtro} ORDER BY co.fecha, co.id", *args)


@ruta("GET", "/api/compras/facturas", "compras")
def compras_facturas(c):
    fs = rows(c.db, """SELECT f.*, p.nombre proveedor, p.rut, u.nombre usuario FROM compra_facturas f JOIN proveedores p ON p.id=f.proveedor_id
        LEFT JOIN usuarios u ON u.id=f.usuario_id ORDER BY f.fecha DESC, f.id DESC LIMIT 500""")
    for f in fs:
        f["guias"] = rows(c.db, "SELECT id, fecha, documento, neto, total FROM compras WHERE factura_id=? ORDER BY fecha, id", f["id"]) if f["estado"] == "VIGENTE" \
            else json.loads(f["guias_anuladas"] or "[]")
        f["neto_guias"] = round(sum(g["neto"] for g in f["guias"]), 2)
        f["diferencia"] = round(f["neto"] - f["neto_guias"], 2)
    return fs


@ruta("POST", "/api/compras/facturas", "compras", 2)
def compras_factura_crear(c):
    d, db = c.body, c.db
    prov = entero(d.get("proveedor_id"), "el proveedor")
    if not row(db, "SELECT id FROM proveedores WHERE id=?", prov):
        raise ApiError(400, "Proveedor no válido.")
    doc = txt(d.get("documento"), "El N° de factura", True, 40)
    if row(db, "SELECT id FROM compra_facturas WHERE proveedor_id=? AND documento=? AND estado='VIGENTE'", prov, doc):
        raise ApiError(409, f"La factura {doc} de este proveedor ya está registrada.")
    ids = d.get("guias") or []
    if not isinstance(ids, list) or not ids:
        raise ApiError(400, "Marca al menos una guía de despacho para netear con la factura.")
    ids = sorted({entero(x, "la guía") for x in ids})
    guias = rows(db, f"SELECT * FROM compras WHERE id IN ({','.join('?' * len(ids))})", *ids)
    for g in guias:
        if g["proveedor_id"] != prov or g["tipo_documento"] != "GUIA":
            raise ApiError(400, f"La compra #{g['id']} no es una guía de despacho de este proveedor.")
        if g["estado"] != "VIGENTE":
            raise ApiError(409, f"La guía de la compra #{g['id']} está anulada.")
        if g["factura_id"]:
            raise ApiError(409, f"La guía de la compra #{g['id']} ya fue neteada con otra factura.")
    if len(guias) != len(ids):
        raise ApiError(404, "Alguna de las guías no existe.")
    neto_guias = round(sum(g["neto"] for g in guias), 2)
    neto = neto_guias if d.get("neto") in (None, "") else num(d.get("neto"), "El neto de la factura")
    pct = iva_actual(db)
    iva = round(neto * pct / 100, 2)
    fid = db.execute("INSERT INTO compra_facturas(proveedor_id,fecha,documento,iva_pct,neto,iva,total,obs,usuario_id,creado) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (prov, fecha_valida(d.get("fecha")), doc, pct, neto, iva, round(neto + iva, 2), txt(d.get("obs"), "La observación", False, 500), c.uid,
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"))).lastrowid
    db.execute(f"UPDATE compras SET factura_id=? WHERE id IN ({','.join('?' * len(ids))})", (fid, *ids))
    return {"id": fid, "neto_guias": neto_guias, "diferencia": round(neto - neto_guias, 2)}


@ruta("POST", r"/api/compras/facturas/(\d+)/anular", "compras", 2, accion="anular_compras")
def compras_factura_anular(c, i):
    f = row(c.db, "SELECT * FROM compra_facturas WHERE id=?", int(i))
    if not f:
        raise ApiError(404, "Factura no encontrada.")
    if f["estado"] != "VIGENTE":
        raise ApiError(409, "La factura ya está anulada.")
    guias = rows(c.db, "SELECT id, fecha, documento, neto, total FROM compras WHERE factura_id=?", f["id"])
    c.db.execute("UPDATE compra_facturas SET estado='ANULADA', guias_anuladas=? WHERE id=?", (json.dumps(guias), f["id"]))
    c.db.execute("UPDATE compras SET factura_id=NULL WHERE factura_id=?", (f["id"],))
    return {"ok": True}


@ruta("GET", r"/api/compras/(\d+)", "compras")
def compras_detalle(c, i):
    r = row(c.db, SQL_COMPRA + " WHERE co.id=?", int(i))
    if not r:
        raise ApiError(404, "Compra no encontrada.")
    r["items"] = rows(c.db, "SELECT ci.*, a.codigo, a.nombre, u.abreviatura unidad FROM compra_items ci JOIN articulos a ON a.id=ci.articulo_id "
                            "JOIN unidades u ON u.id=a.unidad_id WHERE ci.compra_id=?", int(i))
    return r


@ruta("POST", "/api/compras", "compras", 2)
def compras_crear(c):
    return {"id": crear_compra(c.db, c.uid, c.body)}


@ruta("POST", r"/api/compras/(\d+)/anular", "compras", 2, accion="anular_compras")
def compras_anular(c, i):
    f = row(c.db, "SELECT f.documento FROM compras co JOIN compra_facturas f ON f.id=co.factura_id AND f.estado='VIGENTE' WHERE co.id=?", int(i))
    if f:
        raise ApiError(409, f"Esta guía ya fue neteada con la factura {f['documento']}. Anula primero esa factura en Guías por facturar.")
    anular(c.db, c.uid, "compras", "COMPRA", int(i))
    return {"ok": True}


# ---------------------------------------------------------------- desechables: devolución de tienda y consumo en la central

TIPOS_SALIDA_INTERNA = ("DEVOLUCION_TIENDA", "CONSUMO_CENTRAL")


@ruta("GET", "/api/salidas-internas/stock", "despachos", 2)
def salidas_internas_stock(c):
    return articulos_de_bodega(c.db, c.bodega(c.q.get("bodega")), "DESECHABLES")


@ruta("GET", "/api/salidas-internas", "despachos")
def salidas_internas_lista(c):
    d, h = c.rango(365)
    tipo = c.q.get("tipo")
    if tipo not in TIPOS_SALIDA_INTERNA:
        raise ApiError(400, "Tipo de documento no válido.")
    propia = c.user.get("tienda_id")
    if propia and tipo == "CONSUMO_CENTRAL":
        c.sin_tienda()
    return rows(c.db, f"""SELECT s.*, COALESCE(t.nombre,'Bodega central') origen, u.nombre usuario,
        (SELECT COUNT(*) FROM salida_interna_items i WHERE i.salida_id=s.id) lineas,
        (SELECT SUM(i.cantidad*i.costo_unit) FROM salida_interna_items i WHERE i.salida_id=s.id) valor
        FROM salidas_internas s LEFT JOIN tiendas t ON t.id=s.tienda_id LEFT JOIN usuarios u ON u.id=s.usuario_id
        WHERE s.tipo=? AND s.fecha BETWEEN ? AND ? {'AND s.tienda_id=' + str(int(propia)) if propia else ''}
        ORDER BY s.fecha DESC, s.id DESC LIMIT 500""", tipo, d, h)


def salida_interna_de(c, i):
    r = row(c.db, """SELECT s.*, COALESCE(t.nombre,'Bodega central') origen, t.direccion, t.comuna, u.nombre usuario FROM salidas_internas s
        LEFT JOIN tiendas t ON t.id=s.tienda_id LEFT JOIN usuarios u ON u.id=s.usuario_id WHERE s.id=?""", int(i))
    propia = c.user.get("tienda_id")
    if not r or (propia and r["tienda_id"] != propia):
        raise ApiError(404, "Documento no encontrado.")
    return r


@ruta("GET", r"/api/salidas-internas/(\d+)", "despachos")
def salidas_internas_detalle(c, i):
    r = salida_interna_de(c, i)
    r["items"] = rows(c.db, "SELECT si.*, a.codigo, a.nombre, u.abreviatura unidad FROM salida_interna_items si JOIN articulos a ON a.id=si.articulo_id "
                            "JOIN unidades u ON u.id=a.unidad_id WHERE si.salida_id=? ORDER BY a.nombre", int(i))
    return r


@ruta("POST", "/api/salidas-internas", "despachos", 2)
def salidas_internas_crear(c):
    d = c.body
    tipo = d.get("tipo")
    if tipo not in TIPOS_SALIDA_INTERNA:
        raise ApiError(400, "Tipo de documento no válido.")
    tienda = None
    if tipo == "DEVOLUCION_TIENDA":
        tienda = c.bodega(entero(d.get("tienda_id"), "la tienda"))
        if tienda == CENTRAL:
            raise ApiError(400, "Selecciona la tienda que devuelve.")
    else:
        c.sin_tienda()
    fecha = fecha_valida(d.get("fecha"))
    motivo = txt(d.get("motivo"), "el motivo", True, 200)
    items = lineas(d.get("items"))
    sid = c.db.execute("INSERT INTO salidas_internas(tipo,fecha,tienda_id,motivo,usuario_id) VALUES(?,?,?,?,?)", (tipo, fecha, tienda, motivo, c.uid)).lastrowid
    ref = f"{'Devolución de tienda' if tienda else 'Consumo interno central'} #{sid}"
    for i in items:
        a = articulo(c.db, i["articulo_id"])
        if not a["desechable"] or scalar(c.db, "SELECT punto_venta FROM categorias WHERE id=?", a["categoria_id"]):
            raise ApiError(400, f"{a['nombre']} no corresponde: aquí solo se registran desechables y aseo.")
        c.db.execute("INSERT INTO salida_interna_items VALUES(?,?,?,?)", (sid, a["id"], i["cantidad"], costo_de(a)))
        if tienda:
            mover(c.db, a["id"], tienda, -i["cantidad"], "DEVOLUCION_TIENDA", c.uid, fecha, "SALIDA_INTERNA", sid, ref, obs=motivo)
            mover(c.db, a["id"], CENTRAL, i["cantidad"], "RECEPCION_CENTRAL", c.uid, fecha, "SALIDA_INTERNA", sid, ref, obs=motivo)
        else:
            mover(c.db, a["id"], CENTRAL, -i["cantidad"], "CONSUMO_CENTRAL", c.uid, fecha, "SALIDA_INTERNA", sid, ref, obs=motivo)
    return {"id": sid}


@ruta("POST", r"/api/salidas-internas/(\d+)/anular", "despachos", 2, accion="anular_salidas")
def salidas_internas_anular(c, i):
    salida_interna_de(c, i)
    c.sin_tienda()
    anular(c.db, c.uid, "salidas_internas", "SALIDA_INTERNA", int(i))
    return {"ok": True}


# ---------------------------------------------------------------- integración con Fudo

class FudoError(Exception):
    """incierto=True: la solicitud pudo haber llegado a Fudo, no se sabe si creó el gasto."""
    def __init__(self, mensaje, incierto=False):
        super().__init__(mensaje)
        self.mensaje, self.incierto = mensaje, incierto


FUDO_TOKENS = {}


def fudo_http(url, metodo="GET", cuerpo=None, token=None):
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    pet = urllib.request.Request(url, method=metodo, headers=h, data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    try:
        with urllib.request.urlopen(pet, timeout=FUDO_TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise FudoError("Fudo recibió demasiadas solicitudes. Espera un momento y vuelve a intentar.") from None
        if e.code >= 500:
            raise FudoError(f"Fudo tuvo un error interno ({e.code}).", True) from None
        try:
            err = json.loads(e.read()).get("errors") or [{}]
            detalle = err[0].get("detail") or err[0].get("title") or ""
        except (ValueError, AttributeError, IndexError):
            detalle = ""
        raise FudoError(f"Fudo rechazó la solicitud ({e.code}). {detalle}".strip(), False) from None
    except (OSError, ValueError):
        raise FudoError("No hubo una respuesta válida de Fudo.", True) from None


def fudo_token(cfg, renovar=False):
    guardado = FUDO_TOKENS.get(cfg["tienda_id"])
    if guardado and not renovar and guardado[0] == cfg["api_key"] and guardado[2] > time.time() + 60:
        return guardado[1]
    try:
        r = fudo_http(FUDO_AUTH, "POST", {"apiKey": cfg["api_key"], "apiSecret": cfg["api_secret"]})
        token, expira = r["token"], float(r.get("exp") or time.time() + 3600)
    except FudoError as e:
        raise FudoError("Fudo no aceptó las credenciales de esta tienda, o no respondió. " + e.mensaje) from None  # aún no se envió ningún gasto
    except (KeyError, TypeError, ValueError):
        raise FudoError("Fudo respondió sin un token de acceso.") from None
    FUDO_TOKENS[cfg["tienda_id"]] = (cfg["api_key"], token, expira)
    return token


def fudo_api(cfg, ruta, metodo="GET", cuerpo=None):
    url = FUDO_API + ruta
    try:
        return fudo_http(url, metodo, cuerpo, fudo_token(cfg))
    except FudoError as e:
        if "(401)" not in e.mensaje:
            raise
    return fudo_http(url, metodo, cuerpo, fudo_token(cfg, renovar=True))


def fuera_de_tx(db, fn):
    """Las llamadas a Fudo no retienen la base: confirma lo hecho y reabre la transacción al volver."""
    db.execute("COMMIT")
    try:
        return fn()
    finally:
        db.execute("BEGIN IMMEDIATE")


def fudo_config(db, tienda):
    cfg = row(db, "SELECT * FROM fudo_tiendas WHERE tienda_id=? AND api_key<>'' AND api_secret<>''", tienda)
    if not cfg:
        raise ApiError(400, "Esta tienda no tiene conexión con Fudo. Configúrala en Administración → Integración Fudo.")
    return cfg


def fudo_lista(cfg, ruta):
    datos = fudo_api(cfg, ruta + "?page%5Bsize%5D=500").get("data") or []
    return sorted(({"id": str(x["id"]), "nombre": x.get("attributes", {}).get("name") or str(x["id"])} for x in datos), key=lambda x: x["nombre"].lower())


@ruta("GET", "/api/fudo", "config", 2)
def fudo_tiendas_lista(c):
    return rows(c.db, """SELECT t.id tienda_id, t.nombre, COALESCE(f.categoria,'') categoria, COALESCE(f.categoria_id,'') categoria_id, COALESCE(f.proveedor,'') proveedor,
        COALESCE(f.proveedor_id,'') proveedor_id, COALESCE(f.monto,'TOTAL') monto, COALESCE(f.stock_modo,'SISTEMA') stock_modo, CASE WHEN f.api_secret<>'' THEN 1 ELSE 0 END conectada,
        CASE WHEN f.api_key<>'' THEN substr(f.api_key,-4) ELSE '' END key_final,
        (SELECT group_concat(t2.nombre, ', ') FROM fudo_tiendas f2 JOIN tiendas t2 ON t2.id=f2.tienda_id
          WHERE f2.api_key=f.api_key AND f.api_key<>'' AND f2.tienda_id<>f.tienda_id) comparte_con,
        (SELECT COUNT(*) FROM fudo_equivalencias e WHERE e.tienda_id=t.id) equivalencias
        FROM tiendas t LEFT JOIN fudo_tiendas f ON f.tienda_id=t.id WHERE t.activo=1 ORDER BY t.nombre""")


def fudo_cuenta_propia(db, tienda):
    """El stock de Fudo es por cuenta: si otra tienda usa la misma, las operaciones de stock mezclarían tiendas."""
    otras = [r["nombre"] for r in rows(db, """SELECT t.nombre FROM fudo_tiendas f JOIN fudo_tiendas f2 ON f2.api_key=f.api_key AND f2.tienda_id<>f.tienda_id
        JOIN tiendas t ON t.id=f2.tienda_id WHERE f.tienda_id=? AND f.api_key<>''""", tienda)]
    if otras:
        raise ApiError(409, f"Esta tienda usa la misma cuenta Fudo que {', '.join(otras)}. El stock de Fudo es por cuenta: "
                            "conecta cada tienda con la API Key y API Secret de su propia cuenta antes de operar stock.")


@ruta("PUT", r"/api/fudo/(\d+)/credenciales", "config", 2)
def fudo_credenciales(c, t):
    t = int(t)
    if not row(c.db, "SELECT id FROM tiendas WHERE id=?", t):
        raise ApiError(404, "Tienda no encontrada.")
    actual = row(c.db, "SELECT * FROM fudo_tiendas WHERE tienda_id=?", t) or {}
    clave = txt(c.body.get("api_key"), "la API Key", not actual.get("api_key"), 200) or actual.get("api_key")
    secreto = txt(c.body.get("api_secret"), "la API Secret", not actual.get("api_secret"), 500) or actual.get("api_secret")
    otra = row(c.db, "SELECT t.nombre FROM fudo_tiendas f JOIN tiendas t ON t.id=f.tienda_id WHERE f.api_key=? AND f.tienda_id<>?", clave, t)
    if otra:
        raise ApiError(409, f"Esa API Key ya está conectada a {otra['nombre']}. Cada tienda debe usar las credenciales de su propia cuenta Fudo.")
    if actual.get("api_key") and clave != actual["api_key"]:
        # Las equivalencias apuntan a insumos de la cuenta anterior: no sirven en la nueva.
        n = scalar(c.db, "SELECT COUNT(*) FROM fudo_equivalencias WHERE tienda_id=?", t)
        if n and not c.body.get("reiniciar_equivalencias"):
            raise ApiError(409, f"Al cambiar de cuenta Fudo se borrarán las {n} equivalencias de esta tienda (apuntan a la cuenta anterior). Confirma para continuar.")
        if fudo_stock_pendiente(c.db, t):
            raise ApiError(409, "Hay guías de esta tienda con envío de stock a Fudo por revisar. Resuélvelas antes de cambiar de cuenta.")
        c.db.execute("DELETE FROM fudo_equivalencias WHERE tienda_id=?", (t,))
        # proveedor y categoría de gasto también son de la otra cuenta: se eligen de nuevo en "Ajustar gastos"
        c.db.execute("UPDATE fudo_tiendas SET proveedor_id='', proveedor='', categoria_id='', categoria='' WHERE tienda_id=?", (t,))
    c.db.execute("INSERT INTO fudo_tiendas(tienda_id,api_key,api_secret) VALUES(?,?,?) ON CONFLICT(tienda_id) DO UPDATE SET api_key=excluded.api_key,api_secret=excluded.api_secret",
                 (t, clave, secreto))
    FUDO_TOKENS.pop(t, None)
    return {"ok": True}


@ruta("POST", r"/api/fudo/(\d+)/probar", "config", 2)
def fudo_probar(c, t):
    cfg = fudo_config(c.db, int(t))
    try:
        return fuera_de_tx(c.db, lambda: {"categorias": fudo_lista(cfg, "/expense-categories"), "proveedores": fudo_lista(cfg, "/providers")})
    except FudoError as e:
        raise ApiError(502, e.mensaje) from None


@ruta("PUT", r"/api/fudo/(\d+)/gastos", "config", 2)
def fudo_ajustes(c, t):
    d = c.body
    if d.get("monto") not in ("TOTAL", "NETO"):
        raise ApiError(400, "Indica si se envía el total o el neto.")
    modo = d.get("stock_modo") or "SISTEMA"
    if modo not in ("SISTEMA", "MANUAL"):
        raise ApiError(400, "Indica cómo se suma el stock en Fudo.")
    c.db.execute("UPDATE fudo_tiendas SET stock_modo=? WHERE tienda_id=?", (modo, int(t)))
    fudo_config(c.db, int(t))
    categoria_id = txt(d.get("categoria_id"), "la categoría de gasto", True, 10)
    if not categoria_id.isdigit() or not str(d.get("proveedor_id") or "0").isdigit():
        raise ApiError(400, "Categoría o proveedor no válidos.")
    c.db.execute("UPDATE fudo_tiendas SET categoria_id=?,categoria=?,proveedor_id=?,proveedor=?,monto=? WHERE tienda_id=?",
                 (categoria_id, txt(d.get("categoria"), "La categoría", False, 120), str(d.get("proveedor_id") or ""), txt(d.get("proveedor"), "El proveedor", False, 120), d["monto"], int(t)))
    return {"ok": True}


PROVEEDOR_FUDO = "Nata & Schlott"


def fudo_proveedor_ns(cfg):
    """Id del proveedor "Nata & Schlott" en la cuenta Fudo de la tienda; si no existe, se crea."""
    clave = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "y"))
    for p in fudo_lista(cfg, "/providers"):
        if clave(p["nombre"]) == clave(PROVEEDOR_FUDO):
            return p["id"]
    try:
        return str(fudo_api(cfg, "/providers", "POST", {"data": {"type": "Provider", "attributes": {"name": PROVEEDOR_FUDO}}})["data"]["id"])
    except (KeyError, TypeError):
        raise FudoError("Fudo no devolvió el proveedor creado.") from None


def fudo_medio_efectivo(cfg):
    """Id del medio de pago "Efectivo" en la cuenta Fudo de la tienda."""
    for m in fudo_lista(cfg, "/payment-methods"):
        if "efectivo" in m["nombre"].lower():
            return m["id"]
    raise FudoError("La cuenta Fudo de esta tienda no tiene un medio de pago llamado Efectivo.")


def fudo_gasto(g, cfg, proveedor_id, medio_id):
    num_guia = f"GD-{g['id']:06d}"
    relaciones = {"expenseCategory": {"data": {"id": cfg["categoria_id"], "type": "ExpenseCategory"}},
                  "provider": {"data": {"id": proveedor_id, "type": "Provider"}},
                  "paymentMethod": {"data": {"id": medio_id, "type": "PaymentMethod"}}}
    desc = f"{datetime.now():%d-%m-%Y %H:%M} · Guía N° {g['id']:06d}"  # comentario: fecha y hora del envío y número de guía
    return {"data": {"type": "Expense", "attributes": {
        "amount": round(g["total"] if cfg["monto"] == "TOTAL" else g["neto"]), "date": g["fecha"][:10], "paymentDate": g["fecha"][:10],
        "useInCashCount": False, "receiptNumber": num_guia, "description": desc[:255]}, "relationships": relaciones}}


def fudo_guardar(db, gid, estado, gasto=None, error=""):
    if gasto is None:
        db.execute("UPDATE despachos SET fudo_estado=?,fudo_error=? WHERE id=?", (estado, error, gid))
    else:
        db.execute("UPDATE despachos SET fudo_estado=?,fudo_gasto_id=?,fudo_error=? WHERE id=?", (estado, gasto, error, gid))


@ruta("POST", r"/api/despachos/(\d+)/fudo", "despachos", 2, accion="enviar_fudo")
def despacho_a_fudo(c, i):
    """El estado ENVIANDO se confirma antes de llamar a Fudo: si el resultado es incierto, no se reenvía sin confirmación."""
    c.sin_tienda()
    gid = int(i)
    g = row(c.db, "SELECT * FROM despachos WHERE id=?", gid)
    if not g:
        raise ApiError(404, "Guía no encontrada.")
    if g["estado"] != "VIGENTE":
        raise ApiError(409, "Una guía anulada no se envía a Fudo.")
    if g["fudo_estado"] == "ENVIADO":
        raise ApiError(409, "Esta guía ya está en Fudo.")
    if g["fudo_estado"] in ("ENVIANDO", "REVISAR") and not c.body.get("confirmar_reenvio"):
        raise ApiError(409, "No se sabe si el gasto de esta guía llegó a Fudo. Revísalo allá antes de reenviar.")
    cfg = fudo_config(c.db, g["tienda_id"])
    fudo_cuenta_propia(c.db, g["tienda_id"])  # el gasto iría a la cuenta de otra tienda
    if not cfg["categoria_id"]:
        raise ApiError(400, "Falta elegir la categoría de gasto de esta tienda en Administración → Integración Fudo.")
    try:  # proveedor y medio de pago se resuelven antes de marcar la guía: si fallan, no hay nada incierto
        prov, medio = fuera_de_tx(c.db, lambda: (fudo_proveedor_ns(cfg), fudo_medio_efectivo(cfg)))
    except FudoError as e:
        return {"ok": False, "error": "No se pudo preparar el gasto en Fudo. " + e.mensaje}
    c.db.execute("UPDATE fudo_tiendas SET proveedor_id=?, proveedor=? WHERE tienda_id=?", (prov, PROVEEDOR_FUDO, g["tienda_id"]))
    fudo_guardar(c.db, gid, "ENVIANDO")
    cuerpo = fudo_gasto(g, cfg, prov, medio)
    try:
        r = fuera_de_tx(c.db, lambda: fudo_api(cfg, "/expenses", "POST", cuerpo))
        gasto = str(r["data"]["id"])
    except (KeyError, TypeError):
        fudo_guardar(c.db, gid, "REVISAR", error="Fudo respondió sin el número del gasto.")
        return {"ok": False, "error": "Fudo respondió sin el número del gasto. Revísalo allá antes de reenviar."}
    except FudoError as e:
        fudo_guardar(c.db, gid, "REVISAR" if e.incierto else "", error=e.mensaje)
        return {"ok": False, "error": e.mensaje + (" No se sabe si el gasto llegó: revísalo en Fudo antes de reenviar." if e.incierto else "")}
    fudo_guardar(c.db, gid, "ENVIADO", gasto)
    pago = despacho_pagar(c, {**g, "fudo_gasto_id": gasto}, cfg, cuerpo["data"]["attributes"]["amount"], medio)
    return {"ok": True, "gasto_id": gasto, **pago, **despacho_stock_tras_gasto(c, g)}


def despacho_pagar(c, g, cfg, monto, medio=None):
    """Registra en Fudo el pago del gasto (Efectivo, fecha de la guía) para que quede "Pagado". Sin caja: no afecta el arqueo."""
    c.db.execute("UPDATE despachos SET fudo_pago='REVISAR' WHERE id=?", (g["id"],))  # si se corta a mitad, queda por revisar
    confirmar_tx(c.db)
    try:
        def pagar():
            m = medio or fudo_medio_efectivo(cfg)
            return fudo_api(cfg, "/payments", "POST", {"data": {"type": "Payment", "attributes": {"amount": monto, "paidAt": g["fecha"][:10]},
                "relationships": {"paymentMethod": {"data": {"id": m, "type": "PaymentMethod"}}, "expense": {"data": {"id": g["fudo_gasto_id"], "type": "Expense"}}}}})
        r = fuera_de_tx(c.db, pagar)
        pid = str(r["data"]["id"])
    except (KeyError, TypeError):
        return {"pago": "REVISAR", "pago_error": "Fudo respondió sin el número del pago. Revisa el gasto en Fudo."}
    except FudoError as e:
        c.db.execute("UPDATE despachos SET fudo_pago=? WHERE id=?", ("REVISAR" if e.incierto else "", g["id"]))
        return {"pago": "REVISAR" if e.incierto else "", "pago_error": e.mensaje + (" No se sabe si el pago llegó: revisa el gasto en Fudo antes de reintentar." if e.incierto else "")}
    c.db.execute("UPDATE despachos SET fudo_pago=? WHERE id=?", (pid, g["id"]))
    return {"pago": "PAGADO", "pago_id": pid}


@ruta("POST", r"/api/despachos/(\d+)/fudo/pago", "despachos", 2, accion="enviar_fudo")
def despacho_fudo_pago(c, i):
    """Reintenta el pago de un gasto ya creado en Fudo."""
    c.sin_tienda()
    g = row(c.db, "SELECT * FROM despachos WHERE id=?", int(i))
    if not g:
        raise ApiError(404, "Guía no encontrada.")
    if g["fudo_estado"] != "ENVIADO" or g["estado"] != "VIGENTE":
        raise ApiError(409, "Esta guía no tiene un gasto vigente en Fudo.")
    if g["fudo_pago"] not in ("", "REVISAR"):
        raise ApiError(409, "El gasto de esta guía ya está pagado en Fudo.")
    if g["fudo_pago"] == "REVISAR" and not c.body.get("confirmar_reenvio"):
        raise ApiError(409, "No se sabe si el pago anterior llegó a Fudo. Revisa el gasto allá antes de reintentar.")
    cfg = fudo_config(c.db, g["tienda_id"])
    r = despacho_pagar(c, g, cfg, round(g["total"] if cfg["monto"] == "TOTAL" else g["neto"]))
    return {"ok": r["pago"] == "PAGADO", "error": r.get("pago_error", ""), **r}


def despacho_stock_tras_gasto(c, g):
    """Con el gasto creado, suma en Fudo el stock de los insumos equivalentes (si aún no se sumó)."""
    envio = row(c.db, "SELECT * FROM fudo_stock_envios WHERE despacho_id=?", g["id"])
    if not despacho_lineas_fudo(c.db, g):
        return {"stock": "SIN_EQUIVALENCIAS"}
    if envio and envio["estado"] in ("ENVIADO", "ENVIANDO", "REVISAR"):
        return {"stock": envio["estado"]}
    confirmar_tx(c.db)  # el gasto queda guardado aunque falle el stock
    try:
        r = fudo_mover_stock(c, g, envio, 1, "ENVIADO")
    except ApiError as e:
        return {"stock": "", "stock_error": e.mensaje}
    return {"stock": r["estado"], "stock_error": r["error"], "manual": bool(r.get("manual"))}


@ruta("POST", r"/api/despachos/(\d+)/fudo/anular", "despachos", 2, accion="anular_fudo")
def despacho_fudo_anular(c, i):
    c.sin_tienda()
    gid = int(i)
    g = row(c.db, "SELECT * FROM despachos WHERE id=?", gid)
    if not g:
        raise ApiError(404, "Guía no encontrada.")
    if g["fudo_estado"] != "ENVIADO" or not g["fudo_gasto_id"]:
        raise ApiError(409, "Esta guía no tiene un gasto vigente en Fudo.")
    if g["estado"] != "ANULADO":
        raise ApiError(409, "Primero anula la guía en este sistema.")
    cfg = fudo_config(c.db, g["tienda_id"])
    try:
        fuera_de_tx(c.db, lambda: fudo_api(cfg, f"/expenses/{g['fudo_gasto_id']}", "PATCH", {"data": {"id": g["fudo_gasto_id"], "type": "Expense", "attributes": {"canceled": True}}}))
    except FudoError as e:
        fudo_guardar(c.db, gid, "ENVIADO", error=e.mensaje)
        return {"ok": False, "error": e.mensaje}
    fudo_guardar(c.db, gid, "ANULADO")
    envio = row(c.db, "SELECT * FROM fudo_stock_envios WHERE despacho_id=?", gid)
    if envio and envio["estado"] in ("ENVIADO", "ERROR") and any(it.get("estado") == "OK" for it in json.loads(envio["items"]).values()):
        confirmar_tx(c.db)  # el gasto anulado queda guardado aunque falle la resta de stock
        try:
            r = fudo_mover_stock(c, g, envio, -1, "REVERTIDO")
        except ApiError as e:
            return {"ok": True, "stock": "", "stock_error": e.mensaje}
        return {"ok": True, "stock": r["estado"], "stock_error": r["error"]}
    return {"ok": True}


# ---------------------------------------------------------------- Fudo: insumos equivalentes y stock
# Fudo no expone sus recetas: el consumo por ventas se obtiene del stock de sus insumos.
# Por cada equivalencia se guarda "base" (stock Fudo en la última lectura) y "enviado" (lo que el sistema le sumó desde entonces).
# Consumo por ventas = base + enviado − stock Fudo actual (en unidades de Fudo); × factor = unidades del sistema.

FUDO_STOCK_LOCK = threading.Lock()  # lectura y escritura de stock en Fudo no son atómicas: una operación a la vez


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def confirmar_tx(db):
    db.execute("COMMIT")
    db.execute("BEGIN IMMEDIATE")


def fudo_ingredientes(cfg):
    """{fudo_id: {id, nombre, unidad, stock (None si Fudo no controla su stock), control}} de todas las páginas."""
    out, unidades, n = {}, {}, 1
    while True:
        r = fudo_api(cfg, f"/ingredients?page%5Bsize%5D=500&page%5Bnumber%5D={n}&include=unit")
        for x in r.get("included") or []:
            if x.get("type") == "Unit":
                a = x.get("attributes") or {}
                unidades[str(x.get("id"))] = a.get("abbreviation") or a.get("symbol") or a.get("name") or ""
        datos = r.get("data") or []
        for x in datos:
            a = x.get("attributes") or {}
            uid = (((x.get("relationships") or {}).get("unit") or {}).get("data") or {}).get("id")
            out[str(x["id"])] = {"id": str(x["id"]), "nombre": a.get("name") or str(x["id"]), "unidad": unidades.get(str(uid), ""),
                                 "stock": None if a.get("stock") is None else float(a["stock"]), "control": bool(a.get("stockControl")),
                                 "costo": float(a.get("cost") or 0)}
        if len(datos) < 500 or n >= 50:
            return out
        n += 1


def fudo_stock_de(cfg, fid):
    a = (fudo_api(cfg, f"/ingredients/{fid}").get("data") or {}).get("attributes") or {}
    if a.get("stock") is None:
        raise FudoError("Este insumo no tiene control de stock en Fudo. Actívalo allá.")
    return float(a["stock"])


def fudo_poner_stock(cfg, fid, valor):
    fudo_api(cfg, f"/ingredients/{fid}", "PATCH", {"data": {"id": str(fid), "type": "Ingredient", "attributes": {"stock": round(valor, 5)}}})


def equivalencias_de(db, tienda):
    return rows(db, """SELECT e.*, a.codigo, a.nombre, un.abreviatura unidad, COALESCE(s.cantidad,0) stock_sistema FROM fudo_equivalencias e
        JOIN articulos a ON a.id=e.articulo_id JOIN unidades un ON un.id=a.unidad_id
        LEFT JOIN stock s ON s.articulo_id=e.articulo_id AND s.bodega_id=e.tienda_id WHERE e.tienda_id=? ORDER BY a.nombre""", tienda)


@ruta("GET", r"/api/fudo/(\d+)/ingredientes", "config", 2)
def fudo_ingredientes_lista(c, t):
    cfg = fudo_config(c.db, int(t))
    try:
        return sorted(fuera_de_tx_lectura(c.db, lambda: fudo_ingredientes(cfg)).values(), key=lambda x: x["nombre"].lower())
    except FudoError as e:
        raise ApiError(502, e.mensaje) from None


def fuera_de_tx_lectura(db, fn):
    """En GET no hay transacción abierta: la llamada a Fudo no retiene la base."""
    return fn() if not db.in_transaction else fuera_de_tx(db, fn)


@ruta("GET", r"/api/fudo/(\d+)/equivalencias", "config", 2)
def fudo_equivalencias_lista(c, t):
    return equivalencias_de(c.db, int(t))


def validar_equivalencia(db, d):
    aid = entero(d.get("articulo_id"), "el artículo del sistema")
    if not row(db, "SELECT id FROM articulos WHERE id=? AND activo=1 AND (tipo='PRODUCTO' OR desechable=1)", aid):
        raise ApiError(400, "Solo se pueden asociar artículos que se manejan en tiendas: productos, insumos de punto de venta y desechables.")
    return aid, num(d.get("factor"), "La equivalencia", 0, True)


@ruta("POST", r"/api/fudo/(\d+)/equivalencias", "config", 2)
def fudo_equivalencia_crear(c, t):
    t = int(t)
    cfg = fudo_config(c.db, t)
    fudo_cuenta_propia(c.db, t)
    d = c.body
    fid = txt(d.get("fudo_id"), "el insumo de Fudo", True, 12)
    if not fid.isdigit():
        raise ApiError(400, "Insumo de Fudo no válido.")
    aid, factor = validar_equivalencia(c.db, d)
    if row(c.db, "SELECT id FROM fudo_equivalencias WHERE tienda_id=? AND fudo_id=?", t, fid):
        raise ApiError(409, "Ese insumo de Fudo ya tiene equivalencia en esta tienda.")
    if row(c.db, "SELECT id FROM fudo_equivalencias WHERE tienda_id=? AND articulo_id=?", t, aid):
        raise ApiError(409, "Ese artículo del sistema ya está asociado a otro insumo de Fudo en esta tienda.")
    with FUDO_STOCK_LOCK:
        try:
            base = fuera_de_tx(c.db, lambda: fudo_stock_de(cfg, fid))
        except FudoError as e:
            raise ApiError(502, e.mensaje) from None
        eid = c.db.execute("""INSERT INTO fudo_equivalencias(tienda_id,fudo_id,fudo_nombre,fudo_unidad,articulo_id,factor,base,enviado,base_fecha,creado)
            VALUES(?,?,?,?,?,?,?,0,?,?)""", (t, fid, txt(d.get("fudo_nombre"), "El nombre en Fudo", False, 255) or fid,
                                           txt(d.get("fudo_unidad"), "La unidad en Fudo", False, 30), aid, factor, base, ahora(), ahora())).lastrowid
        confirmar_tx(c.db)
    return {"id": eid, "base": base}


@ruta("PUT", r"/api/fudo/equivalencias/(\d+)", "config", 2)
def fudo_equivalencia_editar(c, i):
    e = row(c.db, "SELECT * FROM fudo_equivalencias WHERE id=?", int(i))
    if not e:
        raise ApiError(404, "Equivalencia no encontrada.")
    aid, factor = validar_equivalencia(c.db, c.body)
    if row(c.db, "SELECT id FROM fudo_equivalencias WHERE tienda_id=? AND articulo_id=? AND id<>?", e["tienda_id"], aid, e["id"]):
        raise ApiError(409, "Ese artículo del sistema ya está asociado a otro insumo de Fudo en esta tienda.")
    c.db.execute("UPDATE fudo_equivalencias SET articulo_id=?, factor=? WHERE id=?", (aid, factor, e["id"]))
    return {"ok": True}


@ruta("DELETE", r"/api/fudo/equivalencias/(\d+)", "config", 2)
def fudo_equivalencia_borrar(c, i):
    c.db.execute("DELETE FROM fudo_equivalencias WHERE id=?", (int(i),))
    return {"ok": True}


def normalizar_nombre(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"^(in|ipv|ida|p|sp)\s+", "", s.strip())  # prefijos de código que a veces se escriben en Fudo ("IN GALLETA…")
    return re.sub(r"\s+", " ", s).strip()


def sugerir_articulo(nombre, articulos):
    """Artículo de tienda más parecido por nombre (o None)."""
    n = normalizar_nombre(nombre)
    if not n:
        return None
    mejor, puntaje = None, 0.0
    for a in articulos:
        m = normalizar_nombre(a["nombre"])
        p = 1.0 if m == n else difflib.SequenceMatcher(None, n, m).ratio()
        if m and (m in n or n in m):
            p = max(p, 0.85)
        if p > puntaje:
            mejor, puntaje = a, p
    return (mejor["id"], round(puntaje, 2)) if mejor and puntaje >= 0.72 else None


def sugerir_unidad(db, abrev):
    a = normalizar_nombre(abrev)
    # Se lleva a un nombre canónico y se compara contra nombre y abreviatura de las unidades del sistema
    canon = {"un": "unidad", "unit": "unidad", "units": "unidad", "unidades": "unidad", "u": "unidad",
             "kg": "kilogramo", "kilo": "kilogramo", "kilogram": "kilogramo", "kilos": "kilogramo",
             "g": "gramo", "gr": "gramo", "gram": "gramo", "gramos": "gramo",
             "l": "litro", "lt": "litro", "litre": "litro", "liter": "litro", "litros": "litro",
             "ml": "mililitro", "cc": "mililitro", "millilitre": "mililitro", "milliliter": "mililitro"}
    a = canon.get(a, a)
    for u in rows(db, "SELECT id, nombre, abreviatura FROM unidades"):
        if a and a in {canon.get(normalizar_nombre(u["abreviatura"]), normalizar_nombre(u["abreviatura"])),
                       canon.get(normalizar_nombre(u["nombre"]), normalizar_nombre(u["nombre"]))}:
            return u["id"]
    return None


@ruta("GET", r"/api/fudo/(\d+)/importar", "config", 2)
def fudo_importar_lista(c, t):
    """Insumos de Fudo de la tienda, con su equivalencia actual o una sugerencia de artículo y unidad para importarlos."""
    t = int(t)
    cfg = fudo_config(c.db, t)
    try:
        ing = fuera_de_tx_lectura(c.db, lambda: fudo_ingredientes(cfg))
    except FudoError as e:
        raise ApiError(502, e.mensaje) from None
    eqs = {e["fudo_id"]: e for e in equivalencias_de(c.db, t)}
    usados = {e["articulo_id"] for e in eqs.values()}
    articulos = rows(c.db, "SELECT id, nombre FROM articulos WHERE activo=1 AND (tipo='PRODUCTO' OR desechable=1)")
    libres = [a for a in articulos if a["id"] not in usados]
    out = []
    for f in sorted(ing.values(), key=lambda x: x["nombre"].lower()):
        e = eqs.get(f["id"])
        sug = None if e else sugerir_articulo(f["nombre"], libres)
        out.append({**f, "equivalencia": {"articulo_id": e["articulo_id"], "codigo": e["codigo"], "nombre": e["nombre"], "factor": e["factor"]} if e else None,
                    "sugerido_id": sug[0] if sug else None, "parecido": sug[1] if sug else None, "unidad_id": sugerir_unidad(c.db, f["unidad"])})
    return out


@ruta("POST", r"/api/fudo/(\d+)/importar", "config", 2)
def fudo_importar(c, t):
    """Crea en lote las equivalencias elegidas; si se pide, crea antes el artículo del sistema. Todo o nada."""
    t = int(t)
    cfg = fudo_config(c.db, t)
    fudo_cuenta_propia(c.db, t)
    items = c.body.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError(400, "Selecciona al menos un insumo de Fudo.")
    if any(isinstance(i, dict) and i.get("nuevo") for i in items) and c.user["permisos"].get("articulos", 0) < 2:
        raise ApiError(403, "Para crear artículos nuevos tu perfil necesita editar Artículos y catálogos.")
    with FUDO_STOCK_LOCK:
        try:
            ing = fuera_de_tx(c.db, lambda: fudo_ingredientes(cfg))
        except FudoError as e:
            raise ApiError(502, e.mensaje) from None
        creados, asociados, vistos = [], 0, set()
        for i in items:
            if not isinstance(i, dict):
                raise ApiError(400, "Detalle inválido.")
            fid = str(i.get("fudo_id") or "")
            f = ing.get(fid)
            if not f:
                raise ApiError(404, f"El insumo {fid} ya no existe en Fudo.")
            if f["stock"] is None:
                raise ApiError(400, f"{f['nombre']}: activa el control de stock de este insumo en Fudo antes de importarlo.")
            if fid in vistos or row(c.db, "SELECT id FROM fudo_equivalencias WHERE tienda_id=? AND fudo_id=?", t, fid):
                raise ApiError(409, f"{f['nombre']} ya tiene equivalencia en esta tienda.")
            vistos.add(fid)
            nuevo = i.get("nuevo")
            if nuevo:
                grupo = nuevo.get("grupo")
                if grupo not in ("PRODUCTO", "PUNTO_VENTA", "DESECHABLE"):
                    raise ApiError(400, f"{f['nombre']}: elige si es producto, insumo de punto de venta o desechable.")
                datos = {"tipo": "PRODUCTO" if grupo == "PRODUCTO" else "INSUMO", "categoria_id": nuevo.get("categoria_id"), "unidad_id": nuevo.get("unidad_id"),
                         "nombre": txt(nuevo.get("nombre") or f["nombre"], "El nombre", True, 120), "precio": f["costo"],
                         "desechable": grupo == "DESECHABLE"}
                if grupo != "PRODUCTO":
                    datos["punto_venta"] = grupo == "PUNTO_VENTA"
                try:
                    v = datos_articulo(c.db, datos)
                except ApiError as e:
                    raise ApiError(e.status, f"{f['nombre']}: {e.mensaje}") from None
                aid = c.db.execute("INSERT INTO articulos(tipo,desechable,categoria_id,unidad_id,codigo,nombre,stock_minimo,precio,costo) VALUES(?,?,?,?,?,?,?,?,?)",
                                   (*v, v[7] if v[0] == "INSUMO" else 0)).lastrowid
                creados.append({"id": aid, "codigo": v[4], "nombre": v[5]})
            else:
                aid = entero(i.get("articulo_id"), f"el artículo del sistema para {f['nombre']}")
            try:
                _, factor = validar_equivalencia(c.db, {"articulo_id": aid, "factor": i.get("factor", 1)})
            except ApiError as e:
                raise ApiError(e.status, f"{f['nombre']}: {e.mensaje}") from None
            if row(c.db, "SELECT id FROM fudo_equivalencias WHERE tienda_id=? AND articulo_id=?", t, aid):
                raise ApiError(409, f"{f['nombre']}: ese artículo del sistema ya está asociado a otro insumo de Fudo en esta tienda.")
            c.db.execute("""INSERT INTO fudo_equivalencias(tienda_id,fudo_id,fudo_nombre,fudo_unidad,articulo_id,factor,base,enviado,base_fecha,creado)
                VALUES(?,?,?,?,?,?,?,0,?,?)""", (t, fid, f["nombre"], f["unidad"], aid, factor, f["stock"], ahora(), ahora()))
            asociados += 1
        confirmar_tx(c.db)
    return {"equivalencias": asociados, "creados": creados}


def fudo_stock_pendiente(db, tienda):
    return scalar(db, "SELECT COUNT(*) FROM fudo_stock_envios WHERE tienda_id=? AND estado IN ('ENVIANDO','REVISAR')", tienda)


@ruta("GET", r"/api/fudo/(\d+)/comparar", "config", 2)
def fudo_comparar(c, t):
    """Stock del sistema y de Fudo lado a lado, y el consumo por ventas que se descontaría al sincronizar."""
    t = int(t)
    cfg = fudo_config(c.db, t)
    eqs = equivalencias_de(c.db, t)
    try:
        ing = fuera_de_tx_lectura(c.db, lambda: fudo_ingredientes(cfg)) if eqs else {}
    except FudoError as e:
        raise ApiError(502, e.mensaje) from None
    filas = []
    for e in eqs:
        f = ing.get(e["fudo_id"])
        fila = {**e, "fudo_stock": None, "fudo_en_sistema": None, "diferencia": None, "consumo_pendiente": None,
                "error": "" if f else "El insumo ya no existe en Fudo."}
        if f and f["stock"] is None:
            fila["error"] = "Fudo no controla el stock de este insumo."
        elif f:
            fila.update(fudo_stock=f["stock"], fudo_en_sistema=round(f["stock"] * e["factor"], 5),
                        diferencia=round(f["stock"] * e["factor"] - e["stock_sistema"], 5),
                        consumo_pendiente=round((e["base"] + e["enviado"] - f["stock"]) * e["factor"], 5))
        filas.append(fila)
    sin_enviar = scalar(c.db, """SELECT COUNT(DISTINCT d.id) FROM despachos d JOIN despacho_items i ON i.despacho_id=d.id
        JOIN fudo_equivalencias e ON e.articulo_id=i.articulo_id AND e.tienda_id=d.tienda_id
        LEFT JOIN fudo_stock_envios f ON f.despacho_id=d.id
        WHERE d.tienda_id=? AND d.estado='VIGENTE' AND d.fecha>=substr(e.creado,1,10) AND COALESCE(f.estado,'') NOT IN ('ENVIADO')""", t)
    comparte = [r["nombre"] for r in rows(c.db, """SELECT t.nombre FROM fudo_tiendas f JOIN fudo_tiendas f2 ON f2.api_key=f.api_key AND f2.tienda_id<>f.tienda_id
        JOIN tiendas t ON t.id=f2.tienda_id WHERE f.tienda_id=? AND f.api_key<>''""", t)]
    return {"filas": filas, "guias_sin_enviar": sin_enviar, "envios_por_revisar": fudo_stock_pendiente(c.db, t), "comparte_con": comparte}


@ruta("POST", r"/api/fudo/(\d+)/sincronizar", "config", 2, accion="stock_fudo")
def fudo_sincronizar(c, t):
    """Descuenta del stock de la tienda lo que Fudo consumió por ventas desde la sincronización anterior."""
    t = int(t)
    cfg = fudo_config(c.db, t)
    fudo_cuenta_propia(c.db, t)
    if fudo_stock_pendiente(c.db, t):
        raise ApiError(409, "Hay guías cuyo envío de stock a Fudo quedó por revisar. Resuélvelas en Despachos antes de sincronizar.")
    if not row(c.db, "SELECT id FROM fudo_equivalencias WHERE tienda_id=?", t):
        raise ApiError(400, "Esta tienda aún no tiene insumos equivalentes con Fudo.")
    fecha = fecha_valida(c.body.get("fecha"))
    with FUDO_STOCK_LOCK:
        try:
            ing = fuera_de_tx(c.db, lambda: fudo_ingredientes(cfg))
        except FudoError as e:
            raise ApiError(502, e.mensaje) from None
        sid = c.db.execute("INSERT INTO fudo_sincronizaciones(tienda_id,fecha,creado,usuario_id) VALUES(?,?,?,?)", (t, fecha, ahora(), c.uid)).lastrowid
        detalle = []
        for e in equivalencias_de(c.db, t):
            f = ing.get(e["fudo_id"])
            linea = {"articulo_id": e["articulo_id"], "codigo": e["codigo"], "nombre": e["nombre"], "unidad": e["unidad"], "fudo_nombre": e["fudo_nombre"]}
            if not f or f["stock"] is None:
                detalle.append({**linea, "error": "El insumo ya no existe en Fudo." if not f else "Fudo no controla el stock de este insumo."})
                continue
            consumo_fudo = round(e["base"] + e["enviado"] - f["stock"], 5)
            consumo = round(consumo_fudo * e["factor"], 5)
            descontado = round(min(max(consumo, 0), max(stock_de(c.db, t, e["articulo_id"]), 0)), 5)
            if descontado > 0:
                mover(c.db, e["articulo_id"], t, -descontado, "VENTA_FUDO", c.uid, fecha, "FUDO_VENTA", sid, f"Ventas Fudo #{sid}",
                      obs=f"Consumo en Fudo de {e['fudo_nombre']}: {consumo_fudo:g} {e['fudo_unidad']}".strip())
            c.db.execute("UPDATE fudo_equivalencias SET base=?, enviado=0, base_fecha=? WHERE id=?", (f["stock"], ahora(), e["id"]))
            detalle.append({**linea, "consumo": consumo + 0.0, "descontado": descontado + 0.0, "faltante": round(max(consumo - descontado, 0), 5) + 0.0,
                            "entrada_en_fudo": round(max(-consumo, 0), 5) + 0.0})
        c.db.execute("UPDATE fudo_sincronizaciones SET detalle=? WHERE id=?", (json.dumps(detalle, ensure_ascii=False), sid))
        confirmar_tx(c.db)
    return {"id": sid, "detalle": detalle}


@ruta("GET", r"/api/fudo/(\d+)/sincronizaciones", "config", 2)
def fudo_sincronizaciones_lista(c, t):
    filas = rows(c.db, """SELECT s.*, u.nombre usuario FROM fudo_sincronizaciones s LEFT JOIN usuarios u ON u.id=s.usuario_id
        WHERE s.tienda_id=? ORDER BY s.id DESC LIMIT 200""", int(t))
    for f in filas:
        f["detalle"] = json.loads(f["detalle"] or "[]")
    return filas


@ruta("POST", r"/api/fudo/sincronizaciones/(\d+)/anular", "config", 2, accion="stock_fudo")
def fudo_sincronizacion_anular(c, i):
    """Devuelve al stock lo descontado. No vuelve a contarse en la próxima sincronización."""
    anular(c.db, c.uid, "fudo_sincronizaciones", "FUDO_VENTA", int(i))
    return {"ok": True}


@ruta("POST", r"/api/fudo/(\d+)/igualar", "config", 2, accion="stock_fudo")
def fudo_igualar(c, t):
    """Deja en Fudo el stock que tiene el sistema (para partir alineados). Opcionalmente solo algunas equivalencias."""
    t = int(t)
    cfg = fudo_config(c.db, t)
    fudo_cuenta_propia(c.db, t)
    ids = c.body.get("ids")
    eqs = [e for e in equivalencias_de(c.db, t) if not ids or e["id"] in ids]
    if not eqs:
        raise ApiError(400, "No hay insumos equivalentes para igualar.")
    resultado = {}
    with FUDO_STOCK_LOCK:
        def enviar():
            for e in eqs:
                valor = round(max(e["stock_sistema"], 0) / e["factor"], 5)
                try:
                    fudo_poner_stock(cfg, e["fudo_id"], valor)
                    resultado[e["id"]] = (True, valor)
                except FudoError as x:
                    resultado[e["id"]] = (False, x.mensaje + (" No se sabe si Fudo lo aplicó: revisa ese insumo allá." if x.incierto else ""))
        fuera_de_tx(c.db, enviar)
        for eid, (ok, valor) in resultado.items():
            if ok:
                c.db.execute("UPDATE fudo_equivalencias SET base=?, enviado=0, base_fecha=? WHERE id=?", (valor, ahora(), eid))
        confirmar_tx(c.db)
    errores = [{"id": eid, "error": v} for eid, (ok, v) in resultado.items() if not ok]
    return {"ok": not errores, "igualados": len(resultado) - len(errores), "errores": errores}


@ruta("POST", r"/api/fudo/(\d+)/ajustar-sistema", "config", 2, accion="stock_fudo")
def fudo_ajustar_sistema(c, t):
    """Deja en el sistema el stock que tiene Fudo, como una toma de inventario cerrada. Fudo queda como nuevo punto de partida."""
    t = int(t)
    cfg = fudo_config(c.db, t)
    fudo_cuenta_propia(c.db, t)
    if fudo_stock_pendiente(c.db, t):
        raise ApiError(409, "Hay guías cuyo envío de stock a Fudo quedó por revisar. Resuélvelas en Despachos antes de ajustar.")
    ids = c.body.get("ids")
    if not [e for e in equivalencias_de(c.db, t) if not ids or e["id"] in ids]:
        raise ApiError(400, "No hay insumos equivalentes para ajustar.")
    fecha = fecha_valida(c.body.get("fecha"))
    with FUDO_STOCK_LOCK:
        try:
            ing = fuera_de_tx(c.db, lambda: fudo_ingredientes(cfg))
        except FudoError as e:
            raise ApiError(502, e.mensaje) from None
        if row(c.db, "SELECT id FROM inventarios WHERE bodega_id=? AND estado='ABIERTO'", t):
            raise ApiError(409, "Esta tienda tiene una toma de inventario abierta. Ciérrala o elimínala antes de ajustar.")
        iid = c.db.execute("INSERT INTO inventarios(fecha,bodega_id,seccion,obs,usuario_id,estado,cerrado) VALUES(?,?,'',?,?,'CERRADO',?)",
                           (fecha, t, "Ajuste al stock de Fudo", c.uid, ahora())).lastrowid
        ajustes, avisos = [], []
        for e in equivalencias_de(c.db, t):
            if ids and e["id"] not in ids:
                continue
            f = ing.get(e["fudo_id"])
            if not f or f["stock"] is None:
                avisos.append(f"{e['nombre']}: {'el insumo ya no existe en Fudo' if not f else 'Fudo no controla su stock'}")
                continue
            objetivo = round(max(f["stock"] * e["factor"], 0), 5)
            actual = stock_de(c.db, t, e["articulo_id"])
            dif = round(objetivo - actual, 5)
            c.db.execute("INSERT OR REPLACE INTO inventario_items(inventario_id,articulo_id,stock_sistema,conteo,diferencia) VALUES(?,?,?,?,?)",
                         (iid, e["articulo_id"], actual, objetivo, dif))
            if dif:
                mover(c.db, e["articulo_id"], t, dif, "INVENTARIO", c.uid, fecha, "INVENTARIO", iid, f"Ajuste a Fudo #{iid}",
                      obs=f"Stock en Fudo de {e['fudo_nombre']}: {f['stock']:g} {e['fudo_unidad']}".strip())
            c.db.execute("UPDATE fudo_equivalencias SET base=?, enviado=0, base_fecha=? WHERE id=?", (f["stock"], ahora(), e["id"]))
            if f["stock"] < 0:
                avisos.append(f"{e['nombre']}: Fudo tiene stock negativo ({f['stock']:g}); en el sistema queda en 0")
            ajustes.append({"articulo_id": e["articulo_id"], "nombre": e["nombre"], "unidad": e["unidad"], "antes": actual, "ahora": objetivo, "diferencia": dif})
        if not ajustes:
            raise ApiError(502, "No se pudo leer el stock de ningún insumo en Fudo. " + " · ".join(avisos))
        confirmar_tx(c.db)
    return {"inventario_id": iid, "ajustes": ajustes, "avisos": avisos}


def despacho_lineas_fudo(db, g):
    return rows(db, """SELECT e.fudo_id, e.fudo_nombre, e.factor, SUM(di.cantidad) cantidad FROM despacho_items di
        JOIN fudo_equivalencias e ON e.articulo_id=di.articulo_id AND e.tienda_id=? WHERE di.despacho_id=? GROUP BY e.id""", g["tienda_id"], g["id"])


def fudo_mover_stock(c, g, envio, signo, estado_final):
    """Suma (signo 1) o resta (−1) en Fudo las cantidades de la guía. Cada insumo se registra por separado: un fallo no repite los ya aplicados."""
    cfg = fudo_config(c.db, g["tienda_id"])
    fudo_cuenta_propia(c.db, g["tienda_id"])
    items = json.loads(envio["items"]) if envio else {}
    if signo > 0:
        lineas = [l for l in despacho_lineas_fudo(c.db, g) if (items.get(l["fudo_id"]) or {}).get("estado") != "OK"]
        if not lineas and not items:
            raise ApiError(400, "Ningún artículo de esta guía tiene un insumo equivalente en Fudo.")
        tareas = [(l["fudo_id"], l["fudo_nombre"], round(l["cantidad"] / l["factor"], 5)) for l in lineas]
    else:
        tareas = [(fid, it.get("nombre", fid), it["cantidad"]) for fid, it in items.items() if it.get("estado") == "OK"]
    # Modo MANUAL: el stock lo carga la tienda en el detalle del gasto en Fudo (o lo descuenta Fudo al anular el gasto).
    # No se llama a Fudo; solo se registra lo esperado para que el consumo por ventas siga cuadrando.
    manual = (envio or {}).get("manual") if signo < 0 else cfg.get("stock_modo") == "MANUAL"
    if manual:
        for fid, nombre, q in tareas:
            c.db.execute("UPDATE fudo_equivalencias SET enviado=enviado+? WHERE tienda_id=? AND fudo_id=?", (signo * q, g["tienda_id"], fid))
            if signo > 0:
                items[fid] = {"estado": "OK", "cantidad": q, "nombre": nombre}
            else:
                items[fid]["estado"] = "REVERTIDO"
        c.db.execute("""INSERT INTO fudo_stock_envios(despacho_id,tienda_id,estado,items,actualizado,manual) VALUES(?,?,?,?,?,1)
            ON CONFLICT(despacho_id) DO UPDATE SET estado=excluded.estado, items=excluded.items, error='', actualizado=excluded.actualizado, manual=1""",
                     (g["id"], g["tienda_id"], estado_final, json.dumps(items, ensure_ascii=False), ahora()))
        return {"ok": True, "estado": estado_final, "error": "", "manual": True}
    resultado = {}
    with FUDO_STOCK_LOCK:
        c.db.execute("""INSERT INTO fudo_stock_envios(despacho_id,tienda_id,estado,items,actualizado) VALUES(?,?,'ENVIANDO',?,?)
            ON CONFLICT(despacho_id) DO UPDATE SET estado='ENVIANDO', actualizado=excluded.actualizado""", (g["id"], g["tienda_id"], json.dumps(items), ahora()))
        confirmar_tx(c.db)

        def enviar():
            for fid, _, q in tareas:
                try:
                    actual = fudo_stock_de(cfg, fid)
                except FudoError as e:
                    resultado[fid] = ("ERROR", e.mensaje)
                    continue
                try:
                    fudo_poner_stock(cfg, fid, actual + signo * q)
                    resultado[fid] = ("OK", "")
                except FudoError as e:
                    resultado[fid] = ("REVISAR" if e.incierto else "ERROR", e.mensaje)
        fuera_de_tx(c.db, enviar)
        errores = []
        for fid, nombre, q in tareas:
            st, msg = resultado[fid]
            if st == "OK":
                c.db.execute("UPDATE fudo_equivalencias SET enviado=enviado+? WHERE tienda_id=? AND fudo_id=?", (signo * q, g["tienda_id"], fid))
                if signo > 0:
                    items[fid] = {"estado": "OK", "cantidad": q, "nombre": nombre}
                else:
                    items[fid]["estado"] = "REVERTIDO"
            else:
                if st == "REVISAR":
                    items.setdefault(fid, {"cantidad": q, "nombre": nombre})["estado"] = "REVISAR" if signo > 0 else "REVISAR_REVERSO"
                errores.append(f"{nombre}: {msg}")
        if signo < 0:
            pend = [it for it in items.values() if it.get("estado") in ("OK", "REVISAR_REVERSO")]
            estado = "REVISAR" if any(it["estado"] == "REVISAR_REVERSO" for it in pend) else estado_final if not pend else "ENVIADO"
        else:
            todos = all((items.get(l["fudo_id"]) or {}).get("estado") == "OK" for l in despacho_lineas_fudo(c.db, g))
            estado = "REVISAR" if any(it.get("estado") == "REVISAR" for it in items.values()) else estado_final if todos else "ERROR"
        c.db.execute("UPDATE fudo_stock_envios SET estado=?, items=?, error=?, actualizado=? WHERE despacho_id=?",
                     (estado, json.dumps(items, ensure_ascii=False), " · ".join(errores), ahora(), g["id"]))
        confirmar_tx(c.db)
    return {"ok": not errores, "estado": estado, "error": " · ".join(errores)}


@ruta("POST", r"/api/despachos/(\d+)/fudo-stock", "despachos", 2, accion="enviar_fudo")
def despacho_fudo_stock(c, i):
    c.sin_tienda()
    g = row(c.db, "SELECT * FROM despachos WHERE id=?", int(i))
    if not g:
        raise ApiError(404, "Guía no encontrada.")
    if g["estado"] != "VIGENTE":
        raise ApiError(409, "Una guía anulada no suma stock en Fudo.")
    envio = row(c.db, "SELECT * FROM fudo_stock_envios WHERE despacho_id=?", g["id"])
    if envio and envio["estado"] == "ENVIADO":
        raise ApiError(409, "El stock de esta guía ya se sumó en Fudo.")
    if envio and envio["estado"] in ("ENVIANDO", "REVISAR"):
        if not c.body.get("confirmar_reenvio"):
            raise ApiError(409, "No se sabe si parte del stock de esta guía llegó a Fudo. Revisa esos insumos allá antes de reenviar.")
        items = json.loads(envio["items"])
        for it in items.values():
            if it.get("estado") == "REVISAR":
                it["estado"] = "REINTENTAR"
        envio = {**envio, "items": json.dumps(items)}
    return fudo_mover_stock(c, g, envio, 1, "ENVIADO")


@ruta("POST", r"/api/despachos/(\d+)/fudo-stock/revertir", "despachos", 2, accion="anular_fudo")
def despacho_fudo_stock_revertir(c, i):
    c.sin_tienda()
    g = row(c.db, "SELECT * FROM despachos WHERE id=?", int(i))
    if not g:
        raise ApiError(404, "Guía no encontrada.")
    if g["estado"] != "ANULADO":
        raise ApiError(409, "Primero anula la guía en este sistema.")
    envio = row(c.db, "SELECT * FROM fudo_stock_envios WHERE despacho_id=?", g["id"])
    if not envio:
        raise ApiError(409, "Esta guía no tiene stock sumado en Fudo para revertir.")
    items = json.loads(envio["items"])
    if envio["estado"] in ("ENVIANDO", "REVISAR"):
        if not c.body.get("confirmar_reenvio"):
            raise ApiError(409, "No se sabe si parte del stock de esta guía cambió en Fudo. Revisa esos insumos allá antes de continuar.")
        for it in items.values():  # confirmado en Fudo que lo incierto no se aplicó
            if it.get("estado") == "REVISAR_REVERSO":
                it["estado"] = "OK"
            elif it.get("estado") in ("REVISAR", "REINTENTAR"):
                it["estado"] = "DESCARTADO"
    elif envio["estado"] not in ("ENVIADO", "ERROR"):
        raise ApiError(409, "Esta guía no tiene stock sumado en Fudo para revertir.")
    if not any(it.get("estado") == "OK" for it in items.values()):
        c.db.execute("UPDATE fudo_stock_envios SET estado='REVERTIDO', items=?, error='', actualizado=? WHERE despacho_id=?", (json.dumps(items, ensure_ascii=False), ahora(), g["id"]))
        return {"ok": True, "estado": "REVERTIDO", "error": ""}
    return fudo_mover_stock(c, g, {**envio, "items": json.dumps(items)}, -1, "REVERTIDO")


# ---------------------------------------------------------------- devoluciones a proveedores

@ruta("GET", "/api/devoluciones", "devoluciones")
def devoluciones_lista(c):
    c.sin_tienda()
    d, h = c.rango(365)
    return rows(c.db, """SELECT de.*, p.nombre proveedor, p.rut, u.nombre usuario FROM devoluciones de JOIN proveedores p ON p.id=de.proveedor_id
        LEFT JOIN usuarios u ON u.id=de.usuario_id WHERE de.fecha BETWEEN ? AND ? ORDER BY de.fecha DESC, de.id DESC LIMIT 500""", d, h)


@ruta("GET", r"/api/devoluciones/(\d+)", "devoluciones")
def devoluciones_detalle(c, i):
    c.sin_tienda()
    r = row(c.db, "SELECT de.*, p.nombre proveedor, p.rut, u.nombre usuario FROM devoluciones de JOIN proveedores p ON p.id=de.proveedor_id "
                  "LEFT JOIN usuarios u ON u.id=de.usuario_id WHERE de.id=?", int(i))
    if not r:
        raise ApiError(404, "Devolución no encontrada.")
    r["items"] = rows(c.db, "SELECT di.*, a.codigo, a.nombre, u.abreviatura unidad FROM devolucion_items di JOIN articulos a ON a.id=di.articulo_id "
                            "JOIN unidades u ON u.id=a.unidad_id WHERE di.devolucion_id=?", int(i))
    return r


@ruta("POST", "/api/devoluciones", "devoluciones", 2)
def devoluciones_crear(c):
    c.sin_tienda()
    return {"id": crear_devolucion(c.db, c.uid, c.body)}


@ruta("POST", r"/api/devoluciones/(\d+)/anular", "devoluciones", 2, accion="anular_devoluciones")
def devoluciones_anular(c, i):
    c.sin_tienda()
    anular(c.db, c.uid, "devoluciones", "DEVOLUCION", int(i))
    return {"ok": True}


# ---------------------------------------------------------------- despachos

@ruta("GET", "/api/despachos", "despachos")
def despachos_lista(c):
    d, h = c.rango(365)
    propia = c.user.get("tienda_id")
    return rows(c.db, f"""SELECT de.*, t.nombre tienda, u.nombre usuario,
        (SELECT COUNT(*) FROM despacho_items i WHERE i.despacho_id=de.id) lineas,
        (SELECT COUNT(*) FROM despacho_items i JOIN fudo_equivalencias e ON e.articulo_id=i.articulo_id AND e.tienda_id=de.tienda_id WHERE i.despacho_id=de.id) fudo_stock_lineas,
        COALESCE((SELECT estado FROM fudo_stock_envios f WHERE f.despacho_id=de.id),'') fudo_stock_estado,
        COALESCE((SELECT error FROM fudo_stock_envios f WHERE f.despacho_id=de.id),'') fudo_stock_error,
        COALESCE((SELECT manual FROM fudo_stock_envios f WHERE f.despacho_id=de.id),0) fudo_stock_manual
        FROM despachos de JOIN tiendas t ON t.id=de.tienda_id LEFT JOIN usuarios u ON u.id=de.usuario_id
        WHERE de.fecha BETWEEN ? AND ? {'AND de.tienda_id=' + str(int(propia)) if propia else ''}
        ORDER BY de.fecha DESC, de.id DESC LIMIT 500""", d, h)


@ruta("GET", r"/api/despachos/(\d+)", "despachos")
def despachos_detalle(c, i):
    r = row(c.db, "SELECT de.*, t.nombre tienda, t.direccion, t.comuna, t.region, u.nombre usuario FROM despachos de JOIN tiendas t ON t.id=de.tienda_id "
                  "LEFT JOIN usuarios u ON u.id=de.usuario_id WHERE de.id=?", int(i))
    if not r or (c.user.get("tienda_id") and c.user["tienda_id"] != r["tienda_id"]):
        raise ApiError(404, "Guía no encontrada.")
    r["items"] = rows(c.db, "SELECT di.*, a.codigo, a.nombre, a.desechable, ca.punto_venta, ca.nombre categoria, u.abreviatura unidad FROM despacho_items di JOIN articulos a ON a.id=di.articulo_id "
                            "JOIN categorias ca ON ca.id=a.categoria_id JOIN unidades u ON u.id=a.unidad_id WHERE di.despacho_id=? "
                            "ORDER BY a.desechable, ca.punto_venta, ca.nombre, a.nombre", int(i))
    envio = row(c.db, "SELECT estado, error, manual FROM fudo_stock_envios WHERE despacho_id=?", int(i)) or {}
    r.update(fudo_stock_estado=envio.get("estado", ""), fudo_stock_error=envio.get("error", ""), fudo_stock_manual=envio.get("manual", 0),
             fudo_stock_lineas=len(despacho_lineas_fudo(c.db, r)),
             fudo_lista=bool(row(c.db, "SELECT 1 FROM fudo_tiendas WHERE tienda_id=? AND api_secret<>'' AND categoria_id<>''", r["tienda_id"])))
    return r


@ruta("POST", "/api/despachos", "despachos", 2)
def despachos_crear(c):
    c.sin_tienda()
    return {"id": crear_despacho(c.db, c.uid, c.body)}


@ruta("POST", r"/api/despachos/(\d+)/anular", "despachos", 2, accion="anular_despachos")
def despachos_anular(c, i):
    c.sin_tienda()
    anular(c.db, c.uid, "despachos", "DESPACHO", int(i))
    return {"ok": True}


# ---------------------------------------------------------------- bodegas, mermas, inventario, historial

@ruta("GET", "/api/bodegas/resumen", "bodegas")
def bodegas_resumen(c):
    propia = c.user.get("tienda_id")
    out = rows(c.db, f"""SELECT t.id, t.nombre, t.comuna,
        COALESCE(SUM(CASE WHEN s.cantidad>0 THEN 1 ELSE 0 END),0) articulos, COALESCE(SUM(s.cantidad*a.costo),0) valor
        FROM tiendas t LEFT JOIN stock s ON s.bodega_id=t.id LEFT JOIN articulos a ON a.id=s.articulo_id
        WHERE t.activo=1 {'AND t.id=' + str(int(propia)) if propia else ''} GROUP BY t.id ORDER BY t.nombre""")
    return out


@ruta("GET", "/api/bodegas/stock", "bodegas")
def bodegas_stock(c):
    return articulos_de_bodega(c.db, c.bodega(c.q.get("bodega")))


@ruta("GET", "/api/actualizar-stock", "stock", 2)
def actualizar_stock_lista(c):
    return articulos_de_bodega(c.db, c.bodega(c.q.get("bodega")))


@ruta("POST", "/api/actualizar-stock", "stock", 2)
def actualizar_stock(c):
    d = c.body
    bodega, motivo = c.bodega(d.get("bodega_id")), txt(d.get("motivo"), "el motivo", True, 200)
    permitidos = {a["articulo_id"] for a in articulos_de_bodega(c.db, bodega)}
    fecha, n = date.today().isoformat(), 0
    for it in d.get("items") or []:
        aid = entero(it.get("articulo_id"), "el artículo")
        if aid not in permitidos:
            raise ApiError(400, "Hay un artículo que no pertenece a esta bodega.")
        cantidad, actual = num(it.get("cantidad"), "La cantidad"), stock_de(c.db, bodega, aid)
        if abs(actual - num(it.get("esperado"), "El stock esperado")) > 1e-6:
            raise ApiError(409, f"El stock de {articulo(c.db, aid)['nombre']} cambió mientras editabas. Recarga la página y revísalo.")
        if abs(cantidad - actual) > 1e-6:
            mover(c.db, aid, bodega, round(cantidad - actual, 5), "AJUSTE_ADMIN", c.uid, fecha, ref="Actualización de stock", obs=motivo)
            n += 1
    if not n:
        raise ApiError(400, "No hay cambios de stock para guardar.")
    return {"actualizados": n}


@ruta("GET", "/api/stock/central")
def stock_central(c):
    """Stock disponible en bodega central, para quienes operan compras, producción, despachos o mermas."""
    p = c.user["permisos"]
    if c.user.get("tienda_id") or not any(p.get(m) for m in ("despachos", "mermas", "produccion", "compras", "devoluciones", "inventario", "articulos")):
        raise ApiError(403, "No tienes acceso a la bodega central.")
    return articulos_de_bodega(c.db, CENTRAL)


@ruta("GET", "/api/stock/mermable", "mermas")
def stock_mermable(c):
    return articulos_de_bodega(c.db, c.bodega(c.q.get("bodega")))


@ruta("POST", "/api/bodegas/salidas", "bodegas", 2)
def salida_tienda(c):
    d = c.body
    tienda = c.bodega(d.get("tienda_id"))
    if tienda == CENTRAL:
        raise ApiError(400, "Selecciona una tienda.")
    motivo = d.get("motivo")
    if motivo not in ("VENTA", "CONSUMO_INTERNO"):
        raise ApiError(400, "Motivo de salida no válido.")
    a = articulo(c.db, entero(d.get("articulo_id"), "el artículo"))
    cant, fecha = num(d.get("cantidad"), "La cantidad", 0, True), fecha_valida(d.get("fecha"))
    obs = txt(d.get("obs"), "La observación", False, 500)
    sid = c.db.execute("INSERT INTO salidas_tienda(fecha,tienda_id,articulo_id,cantidad,motivo,obs,usuario_id) VALUES(?,?,?,?,?,?,?)",
                       (fecha, tienda, a["id"], cant, motivo, obs, c.uid)).lastrowid
    mover(c.db, a["id"], tienda, -cant, motivo, c.uid, fecha, "SALIDA", sid, f"Salida #{sid}", obs=obs)
    return {"id": sid}


# ---------------------------------------------------------------- POS (servidor a servidor, con clave X-POS-Token)

def pos_autorizar(c):
    origen, guardado = pos_token_guardado(c.db)
    if not origen:
        raise ApiError(503, "La conexión con el POS no está activada. Genera la clave en Configuración.")
    recibido = (c.headers.get("X-POS-Token") or "").strip()
    if not recibido or not hmac.compare_digest(hashlib.sha256(recibido.encode()).hexdigest(), guardado):
        raise ApiError(401, "Clave del POS inválida.")


def pos_referencia(v):
    ref = txt(v, "La referencia", True, 60)
    if not re.match(r"^[A-Za-z0-9._:-]+$", ref):
        raise ApiError(400, "La referencia solo admite letras, números, punto, guion y dos puntos.")
    return ref


@ruta("GET", "/api/pos/ping", publica=True)
def pos_ping(c):
    pos_autorizar(c)
    return {"ok": True}


@ruta("GET", "/api/pos/tiendas", publica=True)
def pos_tiendas(c):
    pos_autorizar(c)
    return [{"id": t["id"], "nombre": t["nombre"], "activa": bool(t["activo"])} for t in rows(c.db, "SELECT id,nombre,activo FROM tiendas ORDER BY nombre")]


@ruta("GET", "/api/pos/articulos", publica=True)
def pos_articulos(c):
    """Lo que se maneja con stock en tienda: productos e insumos de punto de venta / desechables."""
    pos_autorizar(c)
    return rows(c.db, """SELECT a.id, a.codigo, a.nombre, a.tipo, u.abreviatura unidad FROM articulos a JOIN unidades u ON u.id=a.unidad_id
        WHERE a.activo=1 AND (a.tipo='PRODUCTO' OR a.desechable=1) ORDER BY a.nombre""")


@ruta("POST", "/api/pos/consumos", publica=True)
def pos_consumo(c):
    """Descuenta del stock de la tienda lo que consumió una venta del POS. Idempotente por referencia; todo o nada."""
    pos_autorizar(c)
    d = c.body
    ref = pos_referencia(d.get("referencia"))
    previo = row(c.db, "SELECT id, estado FROM pos_consumos WHERE referencia=?", ref)
    if previo:
        return {"ok": True, "id": previo["id"], "estado": previo["estado"], "repetido": True}
    tid = entero(d.get("tienda_id"), "la tienda")
    tienda = row(c.db, "SELECT id, nombre FROM tiendas WHERE id=?", tid)
    if not tienda:
        raise ApiError(404, "Tienda no encontrada.")
    fecha = fecha_valida(d.get("fecha"))
    detalle = txt(d.get("detalle"), "El detalle", False, 200)
    items = d.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError(400, "La venta no trae artículos para descontar.")
    cantidades = {}
    for i in items:
        if not isinstance(i, dict):
            raise ApiError(400, "Detalle inválido.")
        aid = entero(i.get("articulo_id"), "el artículo en cada línea")
        cantidades[aid] = round(cantidades.get(aid, 0) + num(i.get("cantidad"), "La cantidad", 0, True), 5)
    for aid in cantidades:
        if not row(c.db, "SELECT id FROM articulos WHERE id=? AND activo=1", aid):
            raise ApiError(404, f"Artículo {aid} no encontrado o inactivo.")
    cid = c.db.execute("INSERT INTO pos_consumos(referencia,tienda_id,fecha,detalle,creado) VALUES(?,?,?,?,?)",
                       (ref, tid, fecha, detalle, f"{datetime.now():%Y-%m-%d %H:%M:%S}")).lastrowid
    for aid, cant in cantidades.items():
        mover(c.db, aid, tid, -cant, "VENTA", None, fecha, "POS", cid, f"POS {ref}", obs=detalle)
    return {"ok": True, "id": cid}


@ruta("POST", "/api/pos/consumos/anular", publica=True)
def pos_consumo_anular(c):
    pos_autorizar(c)
    ref = pos_referencia(c.body.get("referencia"))
    cons = row(c.db, "SELECT id, estado FROM pos_consumos WHERE referencia=?", ref)
    if not cons:
        raise ApiError(404, "No existe un consumo del POS con esa referencia.")
    if cons["estado"] != "ANULADO":
        anular(c.db, None, "pos_consumos", "POS", cons["id"])
        c.db.execute("UPDATE pos_consumos SET anulado=? WHERE id=?", (f"{datetime.now():%Y-%m-%d %H:%M:%S}", cons["id"]))
    return {"ok": True, "id": cons["id"]}


def pos_tienda(db, valor):
    tid = entero(valor, "la tienda")
    if not row(db, "SELECT id FROM tiendas WHERE id=?", tid):
        raise ApiError(404, "Tienda no encontrada.")
    return tid


@ruta("GET", "/api/pos/stock", publica=True)
def pos_stock(c):
    pos_autorizar(c)
    tid = pos_tienda(c.db, c.q.get("tienda_id"))
    return rows(c.db, """SELECT a.id articulo_id, a.codigo, a.nombre, a.tipo, u.abreviatura unidad, COALESCE(s.cantidad,0) cantidad, a.stock_minimo
        FROM articulos a JOIN unidades u ON u.id=a.unidad_id LEFT JOIN stock s ON s.articulo_id=a.id AND s.bodega_id=?
        WHERE a.activo=1 AND (a.tipo='PRODUCTO' OR a.desechable=1) ORDER BY a.nombre""", tid)


@ruta("GET", "/api/pos/movimientos", publica=True)
def pos_movimientos(c):
    """Historial de movimientos de los artículos de tienda (P o desechables) en la bodega de una tienda. Solo lectura."""
    pos_autorizar(c)
    tid = pos_tienda(c.db, c.q.get("tienda_id"))
    d, h = fecha_valida(c.q.get("desde"), "La fecha desde"), fecha_valida(c.q.get("hasta"), "La fecha hasta")
    if d > h:
        raise ApiError(400, "La fecha desde no puede ser posterior a la fecha hasta.")
    w, a = ["m.bodega_id=?", "substr(m.fecha,1,10) BETWEEN ? AND ?", "(ar.tipo='PRODUCTO' OR ar.desechable=1)"], [tid, d, h]
    if c.q.get("articulo_id"):
        w.append("m.articulo_id=?"); a.append(entero(c.q["articulo_id"], "el artículo"))
    return rows(c.db, f"""SELECT m.id, m.fecha, m.articulo_id, ar.codigo, ar.nombre, un.abreviatura unidad, m.tipo, m.cantidad, m.saldo,
        m.referencia, m.obs, t.nombre otra_tienda, u.nombre usuario, m.doc_tipo, m.doc_id
        FROM movimientos m JOIN articulos ar ON ar.id=m.articulo_id JOIN unidades un ON un.id=ar.unidad_id
        LEFT JOIN tiendas t ON t.id=m.tienda_destino_id LEFT JOIN usuarios u ON u.id=m.usuario_id
        WHERE {' AND '.join(w)} ORDER BY m.id DESC LIMIT 1000""", *a)


POS_DOCUMENTOS = {"DESPACHO": "despachos", "MERMA": "mermas", "SALIDA": "salidas_tienda", "SALIDA_INTERNA": "salidas_internas",
                  "INVENTARIO": "inventarios", "POS": "pos_consumos", "POS_TRF": "pos_transferencias", "FUDO_VENTA": "fudo_sincronizaciones"}


@ruta("GET", "/api/pos/documento", publica=True)
def pos_documento(c):
    """Documento que originó un movimiento de la tienda, en formato genérico. Solo si movió la bodega de esa tienda."""
    pos_autorizar(c)
    tid = pos_tienda(c.db, c.q.get("tienda_id"))
    tipo = c.q.get("doc_tipo")
    if tipo not in POS_DOCUMENTOS:
        raise ApiError(400, "Tipo de documento no válido.")
    did = entero(c.q.get("doc_id"), "el documento")
    doc = row(c.db, f"SELECT * FROM {POS_DOCUMENTOS[tipo]} WHERE id=?", did)
    movs = rows(c.db, """SELECT m.bodega_id, m.articulo_id, m.cantidad, ar.codigo, ar.nombre, un.abreviatura unidad FROM movimientos m
        JOIN articulos ar ON ar.id=m.articulo_id JOIN unidades un ON un.id=ar.unidad_id
        WHERE m.doc_tipo=? AND m.doc_id=? AND m.tipo<>'ANULACION' ORDER BY ar.nombre""", tipo, did)
    propios = [m for m in movs if m["bodega_id"] == tid]
    if not doc or not propios:
        raise ApiError(404, "Documento no encontrado para esta tienda.")
    nombre_tienda = lambda i: scalar(c.db, "SELECT nombre FROM tiendas WHERE id=?", i) or "Bodega central" if i else "Bodega central"
    usuario = scalar(c.db, "SELECT nombre FROM usuarios WHERE id=?", doc.get("usuario_id")) if doc.get("usuario_id") else None
    campos, obs = [], doc.get("obs") or ""
    if tipo == "DESPACHO":
        titulo = f"Guía de despacho N° {did:06d}"
        campos = [["Desde", "Bodega central"], ["Hacia", nombre_tienda(doc["tienda_id"])], ["Transportista", doc["transportista"]], ["Patente", doc["patente"]]]
    elif tipo == "MERMA":
        titulo = f"Merma N° {did}"
        campos = [["Bodega", nombre_tienda(doc["bodega_id"])], ["Motivo", scalar(c.db, "SELECT nombre FROM motivos_merma WHERE id=?", doc["motivo_id"])]]
    elif tipo == "SALIDA":
        titulo = f"Salida de tienda N° {did}"
        campos = [["Tienda", nombre_tienda(doc["tienda_id"])], ["Motivo", {"VENTA": "Venta", "CONSUMO_INTERNO": "Consumo interno"}.get(doc["motivo"], doc["motivo"])]]
    elif tipo == "SALIDA_INTERNA":
        titulo = f"{'Devolución a bodega central' if doc['tipo'] == 'DEVOLUCION_TIENDA' else 'Consumo interno central'} N° {did}"
        obs = doc["motivo"]
        campos = [["Desde", nombre_tienda(doc["tienda_id"])], ["Hacia", "Bodega central"]] if doc["tipo"] == "DEVOLUCION_TIENDA" else []
    elif tipo == "INVENTARIO":
        titulo = f"Toma de inventario N° {did}"
        campos = [["Bodega", nombre_tienda(doc["bodega_id"])], ["Cerrada", doc["cerrado"] or "—"]]
    elif tipo == "FUDO_VENTA":
        titulo = f"Ventas Fudo N° {did}"
        campos = [["Tienda", nombre_tienda(doc["tienda_id"])], ["Sincronizada", doc["creado"]]]
    elif tipo == "POS":
        titulo = f"Venta POS · {doc['referencia']}"
        obs = doc["detalle"]
        campos = [["Referencia", doc["referencia"]], ["Tienda", nombre_tienda(doc["tienda_id"])], ["Recibida", doc["creado"]]]
    else:
        titulo = f"Transferencia POS · {doc['referencia']}"
        obs = doc["detalle"]
        campos = [["Referencia", doc["referencia"]], ["Tipo", "Envío" if doc["tipo"] == "SALIDA" else "Recepción"],
                  ["Hacia" if doc["tipo"] == "SALIDA" else "Desde", nombre_tienda(doc["contraparte_id"])]]
    if usuario:
        campos.append(["Registrado por", usuario])
    if doc.get("anulado"):
        campos.append(["Anulado", doc["anulado"]])
    estado = doc.get("estado") or "VIGENTE"
    return {"doc_tipo": tipo, "doc_id": did, "titulo": titulo, "fecha": doc["fecha"], "estado": estado,
            "campos": [[k, v] for k, v in campos if v not in (None, "")], "obs": obs or "",
            "lineas": [{"codigo": m["codigo"], "nombre": m["nombre"], "unidad": m["unidad"], "cantidad": abs(m["cantidad"])} for m in propios],
            # La contrapartida de la central (despacho, devolución) repite los mismos artículos: solo cuenta lo que no es de esta tienda.
            "lineas_otras_bodegas": any(m["articulo_id"] not in {p["articulo_id"] for p in propios} or
                                        (m["bodega_id"] not in (tid, CENTRAL)) for m in movs if m["bodega_id"] != tid)}


@ruta("POST", "/api/pos/transferencias", publica=True)
def pos_transferencia(c):
    """Salida (descuenta) o entrada (suma) de una transferencia entre tiendas hecha en el POS. Idempotente; todo o nada."""
    pos_autorizar(c)
    d = c.body
    ref = pos_referencia(d.get("referencia"))
    previo = scalar(c.db, "SELECT id FROM pos_transferencias WHERE referencia=?", ref)
    if previo:
        return {"ok": True, "id": previo, "repetido": True}
    tipo = d.get("tipo")
    if tipo not in ("SALIDA", "ENTRADA"):
        raise ApiError(400, "El tipo debe ser SALIDA o ENTRADA.")
    tid = pos_tienda(c.db, d.get("tienda_id"))
    otra = pos_tienda(c.db, d.get("contraparte_id"))
    if otra == tid:
        raise ApiError(400, "La tienda de origen y la de destino deben ser distintas.")
    fecha = fecha_valida(d.get("fecha"))
    detalle = txt(d.get("detalle"), "El detalle", False, 200)
    items = d.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError(400, "La transferencia no trae artículos.")
    cantidades = {}
    for i in items:
        if not isinstance(i, dict):
            raise ApiError(400, "Detalle inválido.")
        aid = entero(i.get("articulo_id"), "el artículo en cada línea")
        if aid in cantidades:
            raise ApiError(400, f"El artículo {aid} viene repetido en la transferencia.")
        cantidades[aid] = num(i.get("cantidad"), "La cantidad", 0, True)
    for aid in cantidades:
        if not row(c.db, "SELECT id FROM articulos WHERE id=? AND activo=1 AND (tipo='PRODUCTO' OR desechable=1)", aid):
            raise ApiError(404, f"Artículo {aid} no encontrado o no se maneja en tiendas.")
    tid_id = c.db.execute("INSERT INTO pos_transferencias(referencia,tipo,tienda_id,contraparte_id,fecha,detalle,creado) VALUES(?,?,?,?,?,?,?)",
                          (ref, tipo, tid, otra, fecha, detalle, f"{datetime.now():%Y-%m-%d %H:%M:%S}")).lastrowid
    signo = -1 if tipo == "SALIDA" else 1
    for aid, cant in cantidades.items():
        mover(c.db, aid, tid, signo * cant, "TRANSFERENCIA_" + tipo, None, fecha, "POS_TRF", tid_id, f"POS {ref}", destino=otra, obs=detalle)
    return {"ok": True, "id": tid_id}


@ruta("POST", "/api/pos/transferencias/anular", publica=True)
def pos_transferencia_anular(c):
    pos_autorizar(c)
    ref = pos_referencia(c.body.get("referencia"))
    t = row(c.db, "SELECT id, estado FROM pos_transferencias WHERE referencia=?", ref)
    if not t:
        raise ApiError(404, "No existe una transferencia del POS con esa referencia.")
    if t["estado"] != "ANULADO":
        anular(c.db, None, "pos_transferencias", "POS_TRF", t["id"])
        c.db.execute("UPDATE pos_transferencias SET anulado=? WHERE id=?", (f"{datetime.now():%Y-%m-%d %H:%M:%S}", t["id"]))
    return {"ok": True, "id": t["id"]}


def pos_inventario_resultado(db, iid):
    return {"ok": True, "id": iid, "ajustes": rows(db, """SELECT x.articulo_id, x.stock_sistema, x.conteo, x.diferencia FROM inventario_items x
        JOIN articulos a ON a.id=x.articulo_id WHERE x.inventario_id=? ORDER BY a.nombre""", iid)}


@ruta("POST", "/api/pos/inventarios", publica=True)
def pos_inventario(c):
    """Toma de inventario contada en el POS: crea y cierra la toma en una sola llamada, ajustando el stock al conteo."""
    pos_autorizar(c)
    d = c.body
    ref = pos_referencia(d.get("referencia"))
    previo = scalar(c.db, "SELECT inventario_id FROM pos_inventarios WHERE referencia=?", ref)
    if previo:
        return {**pos_inventario_resultado(c.db, previo), "repetido": True}
    tid = pos_tienda(c.db, d.get("tienda_id"))
    fecha = fecha_valida(d.get("fecha"))
    responsable = txt(d.get("responsable"), "El responsable", False, 100)
    obs = txt(d.get("obs"), "La observación", False, 300)
    items = d.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError(400, "La toma no trae conteos.")
    conteos = {}
    for i in items:
        if not isinstance(i, dict):
            raise ApiError(400, "Detalle inválido.")
        aid = entero(i.get("articulo_id"), "el artículo en cada línea")
        if aid in conteos:
            raise ApiError(400, f"El artículo {aid} viene repetido en la toma.")
        conteos[aid] = num(i.get("conteo"), "El conteo")
    for aid in conteos:
        if not row(c.db, "SELECT id FROM articulos WHERE id=? AND activo=1 AND (tipo='PRODUCTO' OR desechable=1)", aid):
            raise ApiError(404, f"Artículo {aid} no encontrado o no se maneja en tiendas.")
    if row(c.db, "SELECT id FROM inventarios WHERE bodega_id=? AND estado='ABIERTO'", tid):
        raise ApiError(409, "Esta tienda tiene una toma de inventario abierta en el sistema de producción. Ciérrala o elimínala antes de enviar la del POS.")
    detalle = " · ".join(x for x in ("POS", responsable, obs) if x)
    iid = c.db.execute("INSERT INTO inventarios(fecha,bodega_id,seccion,obs,usuario_id) VALUES(?,?,'',?,NULL)", (fecha, tid, detalle)).lastrowid
    for aid, conteo in conteos.items():
        actual = stock_de(c.db, tid, aid)
        dif = round(conteo - actual, 5)
        c.db.execute("INSERT INTO inventario_items(inventario_id,articulo_id,stock_sistema,conteo,diferencia) VALUES(?,?,?,?,?)", (iid, aid, actual, conteo, dif))
        if dif:
            mover(c.db, aid, tid, dif, "INVENTARIO", None, fecha, "INVENTARIO", iid, f"Toma de inventario POS #{iid}",
                  obs=f"Conteo físico: {conteo:g}; sistema: {actual:g}")
    c.db.execute("UPDATE inventarios SET estado='CERRADO', cerrado=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), iid))
    c.db.execute("INSERT INTO pos_inventarios(referencia,inventario_id) VALUES(?,?)", (ref, iid))
    return pos_inventario_resultado(c.db, iid)


@ruta("GET", "/api/mermas", "mermas")
def mermas_lista(c):
    d, h = c.rango(365)
    propia = c.user.get("tienda_id")
    return rows(c.db, f"""SELECT m.*, a.codigo, a.nombre, a.tipo, un.abreviatura unidad, mo.nombre motivo, COALESCE(t.nombre,'Bodega central') bodega, u.nombre usuario
        FROM mermas m JOIN articulos a ON a.id=m.articulo_id JOIN unidades un ON un.id=a.unidad_id JOIN motivos_merma mo ON mo.id=m.motivo_id
        LEFT JOIN tiendas t ON t.id=m.bodega_id LEFT JOIN usuarios u ON u.id=m.usuario_id
        WHERE m.fecha BETWEEN ? AND ? {'AND m.bodega_id=' + str(int(propia)) if propia else ''}
        ORDER BY m.fecha DESC, m.id DESC LIMIT 500""", d, h)


@ruta("POST", "/api/mermas", "mermas", 2)
def mermas_crear(c):
    return {"id": crear_merma(c.db, c.uid, c.body, c.bodega(c.body.get("bodega_id")))}


@ruta("POST", r"/api/mermas/(\d+)/anular", "mermas", 2, accion="anular_mermas")
def mermas_anular(c, i):
    m = row(c.db, "SELECT bodega_id FROM mermas WHERE id=?", int(i))
    if not m:
        raise ApiError(404, "Merma no encontrada.")
    c.bodega(m["bodega_id"])
    anular(c.db, c.uid, "mermas", "MERMA", int(i))
    return {"ok": True}


@ruta("GET", "/api/inventarios", "inventario")
def inventarios_lista(c):
    propia = c.user.get("tienda_id")
    out = rows(c.db, f"""SELECT i.*, COALESCE(t.nombre,'Bodega central') bodega, u.nombre usuario,
        (SELECT COUNT(*) FROM inventario_items x WHERE x.inventario_id=i.id) lineas,
        (SELECT COUNT(*) FROM inventario_items x WHERE x.inventario_id=i.id AND x.conteo IS NOT NULL) contadas,
        (SELECT COUNT(*) FROM inventario_items x WHERE x.inventario_id=i.id AND ABS(COALESCE(x.diferencia,0))>0) con_diferencia
        FROM inventarios i LEFT JOIN tiendas t ON t.id=i.bodega_id LEFT JOIN usuarios u ON u.id=i.usuario_id
        {'WHERE i.bodega_id=' + str(int(propia)) if propia else ''} ORDER BY i.id DESC LIMIT 200""")
    nombres = {r["id"]: r["nombre"] for r in rows(c.db, "SELECT id, nombre FROM categorias")}
    for r in out:
        r["categorias_nombres"] = categorias_de_toma(r, nombres)
    return out


def categorias_de_toma(inv, nombres):
    """Nombres de las categorías elegidas para la toma; lista vacía = todas."""
    ids = json.loads(inv.get("categorias") or "[]")
    return sorted((nombres.get(i, f"#{i}") for i in ids), key=str.lower)


def articulos_para_toma(db, bodega, seccion, categorias=None):
    arts = articulos_de_bodega(db, bodega, seccion)
    if categorias:
        arts = [a for a in arts if a["categoria_id"] in categorias]
    return arts


def inventario_de(c, i):
    inv = row(c.db, "SELECT i.*, COALESCE(t.nombre,'Bodega central') bodega FROM inventarios i LEFT JOIN tiendas t ON t.id=i.bodega_id WHERE i.id=?", int(i))
    if not inv or (c.user.get("tienda_id") and c.user["tienda_id"] != inv["bodega_id"]):
        raise ApiError(404, "Inventario no encontrado.")
    return inv


@ruta("GET", "/api/inventarios/categorias", "inventario")
def inventarios_categorias(c):
    """Categorías con artículos en la bodega (y sección) elegida, para armar una toma por categorías."""
    bodega = c.bodega(c.q.get("bodega_id"))
    seccion = (c.q.get("seccion") or "") if bodega == CENTRAL else ""
    if seccion and seccion not in SECCIONES:
        raise ApiError(400, "Sección de bodega no válida.")
    cats = {}
    for a in articulos_de_bodega(c.db, bodega, seccion):
        x = cats.setdefault(a["categoria_id"], {"id": a["categoria_id"], "nombre": a["categoria"], "articulos": 0, "con_stock": 0})
        x["articulos"] += 1
        x["con_stock"] += 1 if a["cantidad"] else 0
    return sorted(cats.values(), key=lambda x: x["nombre"].lower())


@ruta("GET", "/api/inventarios/articulos", "inventario")
def inventarios_articulos(c):
    """Artículos contables de una bodega con su stock y categoría, para contar antes de que exista la toma."""
    return articulos_de_bodega(c.db, c.bodega(c.q.get("bodega_id")))


@ruta("GET", r"/api/inventarios/(\d+)", "inventario")
def inventarios_detalle(c, i):
    inv = inventario_de(c, i)
    inv["categorias_nombres"] = categorias_de_toma(inv, {r["id"]: r["nombre"] for r in rows(c.db, "SELECT id, nombre FROM categorias")})
    inv["items"] = rows(c.db, """SELECT x.*, a.codigo, a.nombre, a.tipo, a.desechable, a.costo, u.abreviatura unidad, COALESCE(s.cantidad,0) stock_actual,
        ca.id categoria_id, ca.nombre categoria, ca.punto_venta
        FROM inventario_items x JOIN articulos a ON a.id=x.articulo_id JOIN unidades u ON u.id=a.unidad_id JOIN categorias ca ON ca.id=a.categoria_id
        LEFT JOIN stock s ON s.articulo_id=a.id AND s.bodega_id=? WHERE x.inventario_id=? ORDER BY ca.nombre COLLATE NOCASE, a.nombre COLLATE NOCASE""", inv["bodega_id"], int(i))
    return inv


@ruta("POST", "/api/inventarios", "inventario", 2)
def inventarios_crear(c):
    bodega = c.bodega(c.body.get("bodega_id"))
    seccion = (c.body.get("seccion") or "") if bodega == CENTRAL else ""
    if seccion and seccion not in SECCIONES:
        raise ApiError(400, "Sección de bodega no válida.")
    cats = c.body.get("categorias") or []
    if not isinstance(cats, list):
        raise ApiError(400, "Las categorías no son válidas.")
    cats = sorted({entero(x, "la categoría") for x in cats})
    arts = articulos_para_toma(c.db, bodega, seccion, cats)
    if cats and not arts:
        raise ApiError(400, "Las categorías elegidas no tienen artículos en esta bodega.")
    if cats:
        # Una toma por categorías puede convivir con otras de la misma bodega, siempre que no repitan artículos.
        choque = row(c.db, f"""SELECT a.nombre, x.inventario_id FROM inventario_items x JOIN inventarios i ON i.id=x.inventario_id JOIN articulos a ON a.id=x.articulo_id
            WHERE i.bodega_id=? AND i.estado='ABIERTO' AND x.articulo_id IN ({','.join('?' * len(arts))}) LIMIT 1""", bodega, *[a["articulo_id"] for a in arts])
        if choque:
            raise ApiError(409, f"{choque['nombre']} ya está en la toma abierta #{choque['inventario_id']}. Ciérrala o elige otras categorías.")
    elif row(c.db, "SELECT id FROM inventarios WHERE bodega_id=? AND estado='ABIERTO' AND (seccion=? OR seccion='' OR ?='')", bodega, seccion, seccion):
        raise ApiError(409, "Esta bodega ya tiene una toma de inventario abierta.")
    iid = c.db.execute("INSERT INTO inventarios(fecha,bodega_id,seccion,categorias,obs,usuario_id) VALUES(?,?,?,?,?,?)",
                       (fecha_valida(c.body.get("fecha")), bodega, seccion, json.dumps(cats) if cats else "",
                        txt(c.body.get("obs"), "La observación", False, 500), c.uid)).lastrowid
    for a in arts:
        c.db.execute("INSERT INTO inventario_items(inventario_id,articulo_id,stock_sistema) VALUES(?,?,?)", (iid, a["articulo_id"], a["cantidad"]))
    return {"id": iid}


def guardar_conteos(c, iid):
    for it in c.body.get("items") or []:
        v = it.get("conteo")
        c.db.execute("UPDATE inventario_items SET conteo=? WHERE inventario_id=? AND articulo_id=?",
                     (None if v in (None, "") else num(v, "El conteo"), iid, entero(it.get("articulo_id"), "el artículo")))


@ruta("PUT", r"/api/inventarios/(\d+)", "inventario", 2)
def inventarios_guardar(c, i):
    inv = inventario_de(c, i)
    if inv["estado"] != "ABIERTO":
        raise ApiError(409, "La toma ya está cerrada.")
    if "fecha" in c.body:
        c.db.execute("UPDATE inventarios SET fecha=? WHERE id=?", (fecha_valida(c.body.get("fecha")), inv["id"]))
    if "obs" in c.body:
        c.db.execute("UPDATE inventarios SET obs=? WHERE id=?", (txt(c.body.get("obs"), "El motivo", False, 500), inv["id"]))
    guardar_conteos(c, inv["id"])
    return {"ok": True}


@ruta("POST", r"/api/inventarios/(\d+)/cerrar", "inventario", 2, accion="cerrar_inventario")
def inventarios_cerrar(c, i):
    inv = inventario_de(c, i)
    if inv["estado"] != "ABIERTO":
        raise ApiError(409, "La toma ya está cerrada.")
    guardar_conteos(c, inv["id"])
    contados = rows(c.db, "SELECT * FROM inventario_items WHERE inventario_id=? AND conteo IS NOT NULL", inv["id"])
    if not contados:
        raise ApiError(400, "Ingresa al menos un conteo antes de cerrar.")
    hoy = inv["fecha"] or date.today().isoformat()  # el ajuste queda con la fecha de la toma
    for x in contados:
        # La diferencia se calcula contra el stock al cierre, por si hubo movimientos durante el conteo.
        actual = stock_de(c.db, inv["bodega_id"], x["articulo_id"])
        dif = round(x["conteo"] - actual, 5)
        c.db.execute("UPDATE inventario_items SET stock_sistema=?, diferencia=? WHERE inventario_id=? AND articulo_id=?",
                     (actual, dif, inv["id"], x["articulo_id"]))
        mover(c.db, x["articulo_id"], inv["bodega_id"], dif, "INVENTARIO", c.uid, hoy, "INVENTARIO", inv["id"],
              f"Toma de inventario #{inv['id']}", obs=f"Conteo físico: {x['conteo']:g}; sistema: {actual:g}")
    c.db.execute("UPDATE inventarios SET estado='CERRADO', cerrado=? WHERE id=?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), inv["id"]))
    return {"ok": True}


@ruta("DELETE", r"/api/inventarios/(\d+)", "inventario", 2, accion="cerrar_inventario")
def inventarios_borrar(c, i):
    inv = inventario_de(c, i)
    if inv["estado"] != "ABIERTO":
        raise ApiError(409, "Una toma cerrada es parte del historial y no se elimina.")
    c.db.execute("DELETE FROM inventarios WHERE id=?", (inv["id"],))
    return {"ok": True}


@ruta("GET", "/api/movimientos", "historial")
def movimientos(c):
    d, h = c.rango(90)
    w, a = ["substr(m.fecha,1,10) BETWEEN ? AND ?"], [d, h]
    bodega = c.bodega(c.q.get("bodega"), requerida=False)
    if bodega is not None:
        w.append("m.bodega_id=?"); a.append(bodega)
    for campo, col in (("articulo_id", "m.articulo_id"), ("proveedor_id", "m.proveedor_id"), ("tienda_destino_id", "m.tienda_destino_id"), ("tipo", "m.tipo")):
        if c.q.get(campo):
            w.append(f"{col}=?"); a.append(c.q[campo])
    if c.q.get("clase") == "DESECHABLE":
        w.append("ar.desechable=1 AND ca.punto_venta=0")
    elif c.q.get("clase") == "PUNTO_VENTA":
        w.append("ca.punto_venta=1")
    elif c.q.get("clase") == "INSUMO":
        w.append("ar.tipo='INSUMO' AND ar.desechable=0")
    elif c.q.get("clase"):
        w.append("ar.tipo=?"); a.append(c.q["clase"])
    if c.q.get("sentido") == "entrada":
        w.append("m.cantidad>0")
    elif c.q.get("sentido") == "salida":
        w.append("m.cantidad<0")
    return rows(c.db, f"""SELECT m.*, ar.codigo, ar.nombre, ar.tipo tipo_articulo, ar.desechable, ca.punto_venta, un.abreviatura unidad,
        COALESCE(b.nombre,'Bodega central') bodega, p.nombre proveedor, t.nombre tienda_destino, mo.nombre motivo, u.nombre usuario
        FROM movimientos m JOIN articulos ar ON ar.id=m.articulo_id JOIN categorias ca ON ca.id=ar.categoria_id JOIN unidades un ON un.id=ar.unidad_id
        LEFT JOIN tiendas b ON b.id=m.bodega_id LEFT JOIN proveedores p ON p.id=m.proveedor_id LEFT JOIN tiendas t ON t.id=m.tienda_destino_id
        LEFT JOIN motivos_merma mo ON mo.id=m.motivo_id LEFT JOIN usuarios u ON u.id=m.usuario_id
        WHERE {' AND '.join(w)} ORDER BY m.fecha DESC, m.id DESC LIMIT 1000""", *a)


# ---------------------------------------------------------------- reportes

def serie_mensual(db, meses=6):
    hoy = date.today().replace(day=1)
    claves = []
    y, m = hoy.year, hoy.month
    for _ in range(meses):
        claves.insert(0, f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    def por(sql):
        return {r["mes"]: r["v"] for r in rows(db, sql)}
    co = por("SELECT substr(fecha,1,7) mes, SUM(neto) v FROM compras WHERE estado='VIGENTE' GROUP BY mes")
    pr = por("SELECT substr(fecha,1,7) mes, SUM(costo_total) v FROM producciones WHERE estado='VIGENTE' GROUP BY mes")
    de = por("SELECT substr(fecha,1,7) mes, SUM(neto) v FROM despachos WHERE estado='VIGENTE' GROUP BY mes")
    me = por("SELECT substr(fecha,1,7) mes, SUM(cantidad*costo_unit) v FROM mermas WHERE estado='VIGENTE' GROUP BY mes")
    return [{"mes": k, "compras": co.get(k, 0), "produccion": pr.get(k, 0), "despachos": de.get(k, 0), "mermas": me.get(k, 0)} for k in claves]


def alertas_stock(db):
    return rows(db, """SELECT a.id, a.codigo, a.nombre, a.tipo, a.desechable, a.stock_minimo, u.abreviatura unidad, COALESCE(s.cantidad,0) stock
        FROM articulos a JOIN unidades u ON u.id=a.unidad_id LEFT JOIN stock s ON s.articulo_id=a.id AND s.bodega_id=0
        WHERE a.activo=1 AND a.stock_minimo>0 AND COALESCE(s.cantidad,0)<a.stock_minimo
        ORDER BY COALESCE(s.cantidad,0)/a.stock_minimo""")


def variacion_precios(db, desde, hasta):
    out = []
    for a in rows(db, """SELECT DISTINCT a.id, a.codigo, a.nombre, a.desechable, u.abreviatura unidad, c.nombre categoria FROM historial_precios h JOIN articulos a ON a.id=h.articulo_id
                         JOIN unidades u ON u.id=a.unidad_id JOIN categorias c ON c.id=a.categoria_id WHERE h.fecha BETWEEN ? AND ? ORDER BY a.nombre""", desde, hasta):
        h = rows(db, "SELECT h.precio, h.fecha, p.nombre proveedor, h.proveedor_id FROM historial_precios h JOIN proveedores p ON p.id=h.proveedor_id "
                     "WHERE h.articulo_id=? AND h.fecha BETWEEN ? AND ? ORDER BY h.fecha, h.id", a["id"], desde, hasta)
        precios = [x["precio"] for x in h]
        mejor = min(h, key=lambda x: x["precio"])
        a.update(compras=len(h), inicial=precios[0], ultimo=precios[-1], minimo=min(precios), maximo=max(precios),
                 promedio=sum(precios) / len(precios), variacion=((precios[-1] - precios[0]) / precios[0] * 100) if precios[0] else 0,
                 proveedor=h[-1]["proveedor"], fecha=h[-1]["fecha"], mejor_proveedor=mejor["proveedor"])
        out.append(a)
    return out


@ruta("GET", "/api/reportes/panel", "panel")
def reporte_panel(c):
    c.sin_tienda()
    db = c.db
    desde, hasta = c.rango(30)
    compras = scalar(db, "SELECT SUM(neto) FROM compras WHERE estado='VIGENTE' AND fecha BETWEEN ? AND ?", desde, hasta)
    prod = row(db, "SELECT COALESCE(SUM(costo_total),0) costo, COUNT(*) lotes FROM producciones WHERE estado='VIGENTE' AND fecha BETWEEN ? AND ?", desde, hasta)
    desp = row(db, "SELECT COALESCE(SUM(neto),0) valor, COUNT(*) guias FROM despachos WHERE estado='VIGENTE' AND fecha BETWEEN ? AND ?", desde, hasta)
    merma = scalar(db, "SELECT SUM(cantidad*costo_unit) FROM mermas WHERE estado='VIGENTE' AND fecha BETWEEN ? AND ?", desde, hasta)
    alertas = alertas_stock(db)
    alzas = sorted((v for v in variacion_precios(db, desde, hasta) if v["variacion"] > 0), key=lambda v: -v["variacion"])[:5]
    return {
        "desde": desde, "hasta": hasta,
        "kpis": {
            "valor_central": scalar(db, "SELECT SUM(s.cantidad*a.costo) FROM stock s JOIN articulos a ON a.id=s.articulo_id WHERE s.bodega_id=0"),
            "valor_tiendas": scalar(db, "SELECT SUM(s.cantidad*a.costo) FROM stock s JOIN articulos a ON a.id=s.articulo_id WHERE s.bodega_id<>0"),
            "compras": compras, "produccion_costo": prod["costo"], "lotes": prod["lotes"],
            "despachos": desp["valor"], "guias": desp["guias"], "mermas": merma, "merma_pct": (merma / compras * 100) if compras else 0,
            "alertas": len(alertas),
        },
        "serie": serie_mensual(db),
        "top_producidos": rows(db, """SELECT a.nombre, u.abreviatura unidad, SUM(p.cantidad) cantidad FROM producciones p JOIN articulos a ON a.id=p.articulo_id JOIN unidades u ON u.id=a.unidad_id
            WHERE p.estado='VIGENTE' AND a.tipo='PRODUCTO' AND p.fecha BETWEEN ? AND ? GROUP BY a.id ORDER BY cantidad DESC LIMIT 6""", desde, hasta),
        "mermas_motivo": rows(db, """SELECT mo.nombre, SUM(m.cantidad*m.costo_unit) valor FROM mermas m JOIN motivos_merma mo ON mo.id=m.motivo_id
            WHERE m.estado='VIGENTE' AND m.fecha BETWEEN ? AND ? GROUP BY mo.id ORDER BY valor DESC""", desde, hasta),
        "despachos_tienda": rows(db, """SELECT t.nombre, SUM(d.neto) valor FROM despachos d JOIN tiendas t ON t.id=d.tienda_id
            WHERE d.estado='VIGENTE' AND d.fecha BETWEEN ? AND ? GROUP BY t.id ORDER BY valor DESC""", desde, hasta),
        "alertas": alertas[:8], "alzas": alzas,
    }


@ruta("GET", "/api/reportes/rendimiento", "reportes")
def reporte_rendimiento(c):
    c.sin_tienda()
    db = c.db
    d, h = c.rango()
    memo, out = {}, []
    for r in rows(db, """SELECT a.id, a.codigo, a.nombre, a.tipo, u.abreviatura unidad, COUNT(*) lotes, SUM(p.cantidad) producido, SUM(p.costo_total) costo
            FROM producciones p JOIN articulos a ON a.id=p.articulo_id JOIN unidades u ON u.id=a.unidad_id
            WHERE p.estado='VIGENTE' AND p.fecha BETWEEN ? AND ? GROUP BY a.id ORDER BY costo DESC""", d, h):
        r["costo_real"] = r["costo"] / r["producido"]
        r["costo_receta"] = costo_teorico(db, r["id"], memo)
        r["desviacion"] = ((r["costo_real"] - r["costo_receta"]) / r["costo_receta"] * 100) if r["costo_receta"] else 0
        r["merma"] = scalar(db, "SELECT SUM(cantidad) FROM mermas WHERE estado='VIGENTE' AND articulo_id=? AND fecha BETWEEN ? AND ?", r["id"], d, h)
        r["merma_pct"] = r["merma"] / r["producido"] * 100
        r["rendimiento"] = max(100 - r["merma_pct"], 0)
        out.append(r)
    return {"desde": d, "hasta": h, "filas": out}


@ruta("GET", "/api/reportes/precios", "reportes")
def reporte_precios(c):
    c.sin_tienda()
    d, h = c.rango(180)
    out = {"desde": d, "hasta": h, "filas": variacion_precios(c.db, d, h)}
    if c.q.get("articulo_id"):
        out["serie"] = rows(c.db, "SELECT h.fecha, h.precio, p.nombre proveedor FROM historial_precios h JOIN proveedores p ON p.id=h.proveedor_id "
                                  "WHERE h.articulo_id=? AND h.fecha BETWEEN ? AND ? ORDER BY h.fecha, h.id", c.q["articulo_id"], d, h)
    return out


@ruta("GET", "/api/reportes/margenes", "reportes")
def reporte_margenes(c):
    c.sin_tienda()
    memo, out = {}, []
    for a in rows(c.db, "SELECT a.id, a.codigo, a.nombre, a.precio, u.abreviatura unidad FROM articulos a JOIN unidades u ON u.id=a.unidad_id "
                        "JOIN recetas r ON r.articulo_id=a.id WHERE a.tipo='PRODUCTO' AND a.activo=1"):
        a["costo"] = costo_teorico(c.db, a["id"], memo)
        a["margen"] = a["precio"] - a["costo"]
        a["margen_pct"] = (a["margen"] / a["precio"] * 100) if a["precio"] else 0
        out.append(a)
    return {"filas": sorted(out, key=lambda x: x["margen_pct"])}


@ruta("GET", "/api/reportes/compras", "reportes")
def reporte_compras(c):
    c.sin_tienda()
    d, h = c.rango()
    return {"desde": d, "hasta": h, "filas": rows(c.db, """SELECT p.nombre, p.rut, COUNT(*) documentos, SUM(co.neto) neto, SUM(co.iva) iva, SUM(co.total) total
        FROM compras co JOIN proveedores p ON p.id=co.proveedor_id WHERE co.estado='VIGENTE' AND co.fecha BETWEEN ? AND ? GROUP BY p.id ORDER BY neto DESC""", d, h)}


@ruta("GET", "/api/reportes/despachos", "reportes")
def reporte_despachos(c):
    c.sin_tienda()
    d, h = c.rango()
    return {"desde": d, "hasta": h, "filas": rows(c.db, """SELECT t.nombre, t.comuna, COUNT(*) guias, SUM(de.neto) neto,
        (SELECT SUM(i.cantidad) FROM despacho_items i JOIN despachos x ON x.id=i.despacho_id WHERE x.tienda_id=t.id AND x.estado='VIGENTE' AND x.fecha BETWEEN ? AND ?) unidades
        FROM despachos de JOIN tiendas t ON t.id=de.tienda_id WHERE de.estado='VIGENTE' AND de.fecha BETWEEN ? AND ? GROUP BY t.id ORDER BY neto DESC""", d, h, d, h)}


@ruta("GET", "/api/reportes/mermas", "reportes")
def reporte_mermas(c):
    c.sin_tienda()
    d, h = c.rango()
    base = "FROM mermas m JOIN articulos a ON a.id=m.articulo_id JOIN motivos_merma mo ON mo.id=m.motivo_id LEFT JOIN tiendas t ON t.id=m.bodega_id WHERE m.estado='VIGENTE' AND m.fecha BETWEEN ? AND ?"
    return {"desde": d, "hasta": h,
            "motivos": rows(c.db, f"SELECT mo.nombre, COUNT(*) registros, SUM(m.cantidad*m.costo_unit) valor {base} GROUP BY mo.id ORDER BY valor DESC", d, h),
            "articulos": rows(c.db, f"SELECT a.codigo, a.nombre, COUNT(*) registros, SUM(m.cantidad) cantidad, SUM(m.cantidad*m.costo_unit) valor {base} GROUP BY a.id ORDER BY valor DESC LIMIT 15", d, h),
            "bodegas": rows(c.db, f"SELECT COALESCE(t.nombre,'Bodega central') nombre, COUNT(*) registros, SUM(m.cantidad*m.costo_unit) valor {base} GROUP BY m.bodega_id ORDER BY valor DESC", d, h)}


@ruta("GET", "/api/reportes/stock-tiendas", "reportes")
def reporte_stock_tiendas(c):
    """Stock actual por bodega: una columna por bodega (central y cada tienda activa), filas por artículo agrupadas por categoría."""
    c.sin_tienda()
    db = c.db
    bodegas = [{"id": CENTRAL, "nombre": "Bodega central"}] + rows(db, "SELECT id, nombre FROM tiendas WHERE activo=1 ORDER BY nombre")
    filtro, args = "", []
    tipo = (c.q.get("tipo") or "").upper()
    if tipo in ("PRODUCTO", "SUBPRODUCTO", "INSUMO"):
        filtro, args = " AND a.tipo=?", [tipo]
    filas = rows(db, f"""SELECT a.id, a.codigo, a.nombre, a.tipo, a.desechable, a.costo, a.stock_minimo, u.abreviatura unidad, ca.nombre categoria, ca.punto_venta
        FROM articulos a JOIN unidades u ON u.id=a.unidad_id JOIN categorias ca ON ca.id=a.categoria_id
        WHERE a.activo=1{filtro} ORDER BY ca.nombre COLLATE NOCASE, a.nombre COLLATE NOCASE""", *args)
    stock = {}
    for s in rows(db, "SELECT articulo_id, bodega_id, cantidad FROM stock WHERE cantidad<>0"):
        stock.setdefault(s["articulo_id"], {})[str(s["bodega_id"])] = s["cantidad"]
    for f in filas:
        f["stock"] = stock.get(f["id"], {})
    return {"bodegas": bodegas, "filas": filas}


@ruta("GET", "/api/reportes/cobertura", "reportes")
def reporte_cobertura(c):
    """Días de stock central según el consumo real del período, y cantidad sugerida de reposición."""
    c.sin_tienda()
    d, h = c.rango(30)
    dias = max((date.fromisoformat(h) - date.fromisoformat(d)).days + 1, 1)
    out = rows(c.db, """SELECT a.id, a.codigo, a.nombre, a.tipo, a.desechable, a.stock_minimo, a.costo, u.abreviatura unidad, COALESCE(s.cantidad,0) stock,
        COALESCE((SELECT -SUM(m.cantidad) FROM movimientos m WHERE m.articulo_id=a.id AND m.bodega_id=0 AND m.cantidad<0
          AND m.tipo IN ('CONSUMO_PRODUCCION','DESPACHO','MERMA','CONSUMO_CENTRAL') AND substr(m.fecha,1,10) BETWEEN ? AND ?),0) salidas
        FROM articulos a JOIN unidades u ON u.id=a.unidad_id LEFT JOIN stock s ON s.articulo_id=a.id AND s.bodega_id=0 WHERE a.activo=1 ORDER BY a.nombre""", d, h)
    for r in out:
        r["consumo_diario"] = r["salidas"] / dias
        r["dias"] = (r["stock"] / r["consumo_diario"]) if r["consumo_diario"] else None
        objetivo = max(r["stock_minimo"], r["consumo_diario"] * 14)
        r["sugerido"] = max(objetivo - r["stock"], 0)
    out.sort(key=lambda r: (r["dias"] is None, r["dias"] or 0))
    return {"desde": d, "hasta": h, "filas": out}


# ---------------------------------------------------------------- datos iniciales

def sembrar(db):
    db.executescript(SCHEMA)
    if "seccion" not in [col[1] for col in db.execute("PRAGMA table_info(inventarios)")]:  # bases creadas antes de las secciones
        db.execute("ALTER TABLE inventarios ADD COLUMN seccion TEXT NOT NULL DEFAULT ''")
    if "categorias" not in [col[1] for col in db.execute("PRAGMA table_info(inventarios)")]:  # tomas por categorías: JSON con ids; '' = todas
        db.execute("ALTER TABLE inventarios ADD COLUMN categorias TEXT NOT NULL DEFAULT ''")
    if "tipo_documento" not in [col[1] for col in db.execute("PRAGMA table_info(compras)")]:  # las compras anteriores quedan sin tipo: no se sabe cuál era
        db.execute("ALTER TABLE compras ADD COLUMN tipo_documento TEXT NOT NULL DEFAULT ''")
    if "factura_id" not in [col[1] for col in db.execute("PRAGMA table_info(compras)")]:  # guía de despacho neteada con su factura (compra_facturas)
        db.execute("ALTER TABLE compras ADD COLUMN factura_id INTEGER")
    if "stock_modo" not in [col[1] for col in db.execute("PRAGMA table_info(fudo_tiendas)")]:  # SISTEMA: suma por API; MANUAL: se carga en el detalle del gasto en Fudo
        db.execute("ALTER TABLE fudo_tiendas ADD COLUMN stock_modo TEXT NOT NULL DEFAULT 'SISTEMA'")
    if "manual" not in [col[1] for col in db.execute("PRAGMA table_info(fudo_stock_envios)")]:
        db.execute("ALTER TABLE fudo_stock_envios ADD COLUMN manual INTEGER NOT NULL DEFAULT 0")
    columnas_despacho = [col[1] for col in db.execute("PRAGMA table_info(despachos)")]
    for col in ("fudo_estado", "fudo_gasto_id", "fudo_error", "fudo_pago"):  # bases creadas antes de la integración con Fudo (fudo_pago: id del pago, '' o REVISAR)
        if col not in columnas_despacho:
            db.execute(f"ALTER TABLE despachos ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    if "punto_venta" not in [col[1] for col in db.execute("PRAGMA table_info(categorias)")]:  # bases creadas antes de este grupo
        db.execute("ALTER TABLE categorias ADD COLUMN punto_venta INTEGER NOT NULL DEFAULT 0")
    db.execute("INSERT OR IGNORE INTO config VALUES('iva','19')")
    for nombre, permisos in PERFILES.items():
        db.execute("INSERT OR IGNORE INTO perfiles(nombre,permisos) VALUES(?,?)", (nombre, json.dumps(permisos)))
    if not scalar(db, "SELECT COUNT(*) FROM categorias"):
        for n in ("Tortas", "Pastelería individual", "Galletas y alfajores", "Bases y rellenos", "Harinas y cereales", "Lácteos y huevos",
                  "Azúcares y endulzantes", "Chocolates", "Saborizantes", "Envases y desechables", "Aseo"):
            db.execute("INSERT INTO categorias(nombre) VALUES(?)", (n,))
        for n, ab in (("Kilogramo", "kg"), ("Gramo", "g"), ("Litro", "L"), ("Mililitro", "ml"), ("Unidad", "un"), ("Caja", "caja"), ("Paquete", "paq")):
            db.execute("INSERT INTO unidades(nombre,abreviatura) VALUES(?,?)", (n, ab))
        for n in ("Vencimiento", "Producto quemado o mal horneado", "Error de receta", "Quiebre o daño en traslado", "Caída o manipulación",
                  "Contaminación", "Falla de refrigeración", "Devolución de tienda", "Otro"):
            db.execute("INSERT INTO motivos_merma(nombre) VALUES(?)", (n,))
    if not scalar(db, "SELECT COUNT(*) FROM config WHERE clave='codigos_ida'"):  # el prefijo de desechables y aseo fue IND
        db.execute("UPDATE articulos SET codigo='IDA'||substr(codigo,4) WHERE desechable=1 AND codigo GLOB 'IND[0-9][0-9][0-9][0-9]*'")
        db.execute("INSERT INTO config VALUES('codigos_ida','1')")
    if not scalar(db, "SELECT COUNT(*) FROM config WHERE clave='permisos_devoluciones'"):  # los perfiles de bases anteriores no traen este módulo
        for p in rows(db, "SELECT * FROM perfiles WHERE nombre IN (?,?,?)", PERFIL_ADMIN, "Bodega y logística", "Gerencia"):
            permisos = json.loads(p["permisos"])
            permisos.setdefault("devoluciones", PERFILES[p["nombre"]]["devoluciones"])
            db.execute("UPDATE perfiles SET permisos=? WHERE id=?", (json.dumps(permisos), p["id"]))
        db.execute("INSERT INTO config VALUES('permisos_devoluciones','1')")
    if not scalar(db, "SELECT COUNT(*) FROM config WHERE clave='acciones_criticas'"):  # una sola vez: quien editaba el módulo conserva sus acciones
        for p in rows(db, "SELECT * FROM perfiles"):
            permisos = json.loads(p["permisos"])
            for a, _, modulo in ACCIONES:
                if (permisos.get(modulo) == 2) if modulo else any(permisos.get(m) == 2 for m in ("articulos", "recetas", "proveedores", "tiendas")):
                    permisos["acc_" + a] = 1
            db.execute("UPDATE perfiles SET permisos=? WHERE id=?", (json.dumps(permisos), p["id"]))
        db.execute("INSERT INTO config VALUES('acciones_criticas','1')")
    if "de_productos" not in [col[1] for col in db.execute("PRAGMA table_info(categorias)")]:
        db.execute("ALTER TABLE categorias ADD COLUMN de_productos INTEGER NOT NULL DEFAULT 0")
    if not scalar(db, "SELECT COUNT(*) FROM config WHERE clave='categorias_productos'"):  # una sola vez: clasifica las categorías existentes
        db.execute(f"""UPDATE categorias SET de_productos=1 WHERE nombre IN ({','.join('?' * len(CATEGORIAS_PRODUCTOS))})
            AND id NOT IN (SELECT categoria_id FROM articulos WHERE tipo='INSUMO')""", CATEGORIAS_PRODUCTOS)
        for cat_id, nombre in db.execute("SELECT DISTINCT k.id,k.nombre FROM categorias k JOIN articulos a ON a.categoria_id=k.id WHERE a.tipo<>'INSUMO' AND k.de_productos=0").fetchall():
            if scalar(db, "SELECT COUNT(*) FROM articulos WHERE categoria_id=? AND tipo='INSUMO'", cat_id):  # la usan ambos: los productos pasan a una categoría propia
                nueva = db.execute("INSERT INTO categorias(nombre,de_productos) VALUES(?,1)", (f"{nombre} (productos)",)).lastrowid
                db.execute("UPDATE articulos SET categoria_id=? WHERE categoria_id=? AND tipo<>'INSUMO'", (nueva, cat_id))
            else:
                db.execute("UPDATE categorias SET de_productos=1 WHERE id=?", (cat_id,))
        db.execute("INSERT INTO config VALUES('categorias_productos','1')")
    if not scalar(db, "SELECT COUNT(*) FROM config WHERE clave='categorias_punto_venta'"):  # una sola vez, para respetar lo que se elimine después
        for n in CATEGORIAS_PUNTO_VENTA:
            db.execute("INSERT INTO categorias(nombre,punto_venta) VALUES(?,1) ON CONFLICT(nombre) DO UPDATE SET punto_venta=1", (n,))
        db.execute("INSERT INTO config VALUES('categorias_punto_venta','1')")


def cargar_demo(db, uid):
    """Datos ficticios: pasan por las mismas funciones que la operación real para que el historial sea consistente."""
    rnd = random.Random(7)
    hoy = date.today()
    ids = lambda t: {r["nombre"]: r["id"] for r in rows(db, f"SELECT id,nombre FROM {t}")}
    cat, uni, mot = ids("categorias"), {r["abreviatura"]: r["id"] for r in rows(db, "SELECT * FROM unidades")}, ids("motivos_merma")
    tiendas = [db.execute("INSERT INTO tiendas(nombre,direccion,comuna,region) VALUES(?,?,?,?)", t).lastrowid for t in (
        ("Demo Tienda Centro", "Av. Ejemplo 100", "Santiago", "Metropolitana de Santiago"),
        ("Demo Tienda Oriente", "Calle Ficticia 200", "Las Condes", "Metropolitana de Santiago"),
        ("Demo Tienda Costa", "Paseo Muestra 300", "Viña del Mar", "Valparaíso"))]
    provs = []
    for cuerpo, nombre in ((76111222, "Demo Harinas del Sur SpA"), (77222333, "Demo Lácteos Andinos Ltda."), (78333444, "Demo Distribuidora Dulce SpA"), (79444555, "Demo Envases y Aseo Ltda.")):
        provs.append(db.execute("INSERT INTO proveedores(rut,nombre) VALUES(?,?)", (normalizar_rut(f"{cuerpo}{dv_rut(cuerpo)}"), nombre)).lastrowid)

    def art(tipo, cod, nombre, categoria, unidad, minimo, precio, desechable=0):
        return db.execute("INSERT INTO articulos(tipo,desechable,categoria_id,unidad_id,codigo,nombre,stock_minimo,precio,costo) VALUES(?,?,?,?,?,?,?,?,?)",
                          (tipo, desechable, cat[categoria], uni[unidad], siguiente_codigo(db, tipo, desechable, 0), nombre, minimo, precio, precio if tipo == "INSUMO" else 0)).lastrowid

    ins = {  # código: (id, proveedor, precio base, cantidad por compra)
        "harina": (art("INSUMO", "INS-001", "Harina sin polvos", "Harinas y cereales", "kg", 25, 950), 0, 950, 40),
        "azucar": (art("INSUMO", "INS-002", "Azúcar granulada", "Azúcares y endulzantes", "kg", 20, 1100), 2, 1100, 35),
        "mantequilla": (art("INSUMO", "INS-003", "Mantequilla sin sal", "Lácteos y huevos", "kg", 10, 8200), 1, 8200, 18),
        "huevo": (art("INSUMO", "INS-004", "Huevos", "Lácteos y huevos", "un", 120, 165), 1, 165, 300),
        "crema": (art("INSUMO", "INS-005", "Crema para batir", "Lácteos y huevos", "L", 8, 4300), 1, 4300, 15),
        "chocolate": (art("INSUMO", "INS-006", "Chocolate cobertura 55%", "Chocolates", "kg", 8, 12500), 2, 12500, 14),
        "vainilla": (art("INSUMO", "INS-007", "Esencia de vainilla", "Saborizantes", "L", 1, 15800), 2, 15800, 2),
        "manjar": (art("INSUMO", "INS-008", "Manjar pastelero", "Bases y rellenos", "kg", 8, 3900), 2, 3900, 16),
    }
    des = {
        "vaso": (art("INSUMO", "DES-001", "Vaso cartón 12 oz", "Envases y desechables", "un", 300, 85, 1), 3, 85, 1000),
        "bombilla": (art("INSUMO", "DES-002", "Bombilla compostable", "Envases y desechables", "un", 300, 28, 1), 3, 28, 1500),
        "azucar_s": (art("INSUMO", "DES-003", "Sachet de azúcar", "Envases y desechables", "un", 500, 12, 1), 3, 12, 2000),
        "sucralosa": (art("INSUMO", "DES-004", "Sachet de sucralosa", "Envases y desechables", "un", 300, 19, 1), 3, 19, 1000),
        "limpia": (art("INSUMO", "DES-005", "Limpiavidrios", "Aseo", "L", 4, 2400, 1), 3, 2400, 10),
    }
    bizcocho = art("SUBPRODUCTO", "SUB-001", "Bizcocho de vainilla", "Bases y rellenos", "un", 4, 0)
    ganache = art("SUBPRODUCTO", "SUB-002", "Ganache de chocolate", "Bases y rellenos", "kg", 3, 0)
    torta = art("PRODUCTO", "PRO-001", "Torta de chocolate", "Tortas", "un", 3, 32000)
    brownie = art("PRODUCTO", "PRO-002", "Brownie", "Pastelería individual", "un", 24, 2600)
    alfajor = art("PRODUCTO", "PRO-003", "Alfajor de manjar", "Galletas y alfajores", "un", 30, 1800)

    def receta(a, rend, items, texto):
        db.execute("INSERT INTO recetas VALUES(?,?,?)", (a, rend, texto))
        for ing, c in items:
            db.execute("INSERT INTO receta_items VALUES(?,?,?)", (a, ing, c))

    I = lambda k: ins[k][0]
    receta(bizcocho, 1, [(I("harina"), .35), (I("azucar"), .3), (I("huevo"), 6), (I("vainilla"), .01)], "Batir huevos y azúcar, incorporar harina y hornear a 175 °C por 35 minutos.")
    receta(ganache, 1, [(I("chocolate"), .55), (I("crema"), .45)], "Calentar la crema, verter sobre el chocolate y emulsionar.")
    receta(torta, 1, [(bizcocho, 2), (ganache, .8), (I("mantequilla"), .1)], "Rellenar y cubrir el bizcocho con ganache. Refrigerar 4 horas.")
    receta(brownie, 24, [(I("chocolate"), .6), (I("mantequilla"), .45), (I("azucar"), .7), (I("harina"), .3), (I("huevo"), 8)], "Fundir, mezclar y hornear a 170 °C por 28 minutos. Cortar en 24.")
    receta(alfajor, 30, [(I("harina"), .8), (I("mantequilla"), .3), (I("azucar"), .2), (I("huevo"), 4), (I("manjar"), .9)], "Hornear las tapas y rellenar con manjar.")

    dias = 150
    for semana, delta in enumerate(range(dias, -1, -7)):
        f = (hoy - timedelta(days=delta)).isoformat()
        alza = 1 + semana * 0.004
        por_prov = {}
        for k, (aid, p, base, cant) in {**ins, **des}.items():
            if k in des and semana % 4:
                continue
            precio = round(base * alza * rnd.uniform(.985, 1.03)) if base >= 100 else round(base * alza * rnd.uniform(.985, 1.03), 1)
            por_prov.setdefault(p, []).append({"articulo_id": aid, "cantidad": round(cant * rnd.uniform(.85, 1.15)), "precio": precio})
        for p, items in por_prov.items():
            crear_compra(db, uid, {"fecha": f, "proveedor_id": provs[p], "tipo_documento": "FACTURA", "documento": f"F-{10000 + semana * 10 + p}", "items": items})
        for a, c in ((bizcocho, 8), (ganache, 7)):
            crear_produccion(db, uid, {"fecha": f, "articulo_id": a, "cantidad": c})
        for a, c in ((torta, 4), (brownie, 72), (alfajor, 90)):
            crear_produccion(db, uid, {"fecha": f, "articulo_id": a, "cantidad": c})
        for t in tiendas:
            items = [{"articulo_id": torta, "cantidad": 1}, {"articulo_id": brownie, "cantidad": 18}, {"articulo_id": alfajor, "cantidad": 24}]
            if semana % 4 == 0:
                items += [{"articulo_id": des["vaso"][0], "cantidad": 250}, {"articulo_id": des["bombilla"][0], "cantidad": 300},
                          {"articulo_id": des["azucar_s"][0], "cantidad": 500}, {"articulo_id": des["sucralosa"][0], "cantidad": 250}, {"articulo_id": des["limpia"][0], "cantidad": 2}]
            crear_despacho(db, uid, {"fecha": f, "tienda_id": t, "transportista": "Transporte Demo", "patente": "DEMO11", "items": items})
            for aid, c in ((brownie, 15), (alfajor, 20)):
                sid = db.execute("INSERT INTO salidas_tienda(fecha,tienda_id,articulo_id,cantidad,motivo,usuario_id) VALUES(?,?,?,?,?,?)", (f, t, aid, c, "VENTA", uid)).lastrowid
                mover(db, aid, t, -c, "VENTA", uid, f, "SALIDA", sid, f"Salida #{sid}")
        crear_merma(db, uid, {"fecha": f, "articulo_id": brownie, "cantidad": rnd.randint(1, 4), "motivo_id": mot["Producto quemado o mal horneado"]}, CENTRAL)
        if semana % 2:
            crear_merma(db, uid, {"fecha": f, "articulo_id": alfajor, "cantidad": rnd.randint(1, 3), "motivo_id": mot["Quiebre o daño en traslado"]}, rnd.choice(tiendas))
        if semana % 3 == 0:
            crear_merma(db, uid, {"fecha": f, "articulo_id": I("crema"), "cantidad": rnd.randint(1, 2), "motivo_id": mot["Vencimiento"]}, CENTRAL)
    db.execute("UPDATE articulos SET stock_minimo=? WHERE id=?", (stock_de(db, CENTRAL, I("vainilla")) + 1, I("vainilla")))


# ---------------------------------------------------------------- servidor HTTP

def usuario_de_cookie(db, handler):
    jar = SimpleCookie(handler.headers.get("Cookie", ""))
    if "ns_sesion" not in jar:
        return None
    token = hashlib.sha256(jar["ns_sesion"].value.encode()).hexdigest()
    u = row(db, """SELECT u.id,u.username,u.nombre,u.tienda_id,u.perfil_id,p.nombre perfil,p.permisos,t.nombre tienda FROM sesiones s
        JOIN usuarios u ON u.id=s.usuario_id JOIN perfiles p ON p.id=u.perfil_id LEFT JOIN tiendas t ON t.id=u.tienda_id
        WHERE s.token=? AND s.expira>? AND u.activo=1""", token, time.time())
    if u:
        u["permisos"] = json.loads(u["permisos"])
        if u["perfil"] == PERFIL_ADMIN:  # el Administrador siempre puede todas las acciones críticas
            u["permisos"].update({"acc_" + a: 1 for a in ACCIONES_IDS})
        if u["perfil"] == PERFIL_ADMIN and not u["tienda_id"]:
            u["permisos"]["stock"] = 2
        u["_token"] = token
    return u


class Handler(BaseHTTPRequestHandler):
    server_version = "NataSchlott/1.0"
    sys_version = ""
    timeout = 60

    def log_message(self, *_):
        pass

    def do_GET(self):
        self.despachar("GET")

    def do_POST(self):
        self.despachar("POST")

    def do_PUT(self):
        self.despachar("PUT")

    def do_DELETE(self):
        self.despachar("DELETE")

    def responder(self, status, cuerpo, tipo="application/json; charset=utf-8", cookie=None, descarga=None):
        https = self.headers.get("X-Forwarded-Proto", "").lower() == "https"
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        if descarga:
            self.send_header("Content-Disposition", f'attachment; filename="{descarga}"')
        if https:
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            edad = SESION_HORAS * 3600 if cookie else 0
            self.send_header("Set-Cookie", f"ns_sesion={cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age={edad}{'; Secure' if https else ''}")
        self.end_headers()
        self.wfile.write(cuerpo)

    def json(self, status, data, cookie=None):
        self.responder(status, json.dumps(data, ensure_ascii=False).encode(), cookie=cookie)

    def estatico(self, path):
        nombre = "index.html" if path == "/" else path.lstrip("/")
        destino = (STATIC / nombre).resolve()
        if not destino.is_relative_to(STATIC.resolve()) or not destino.is_file():
            return self.responder(404, b"No encontrado", "text/plain; charset=utf-8")
        tipo = mimetypes.guess_type(destino.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo.endswith("javascript"):
            tipo += "; charset=utf-8"
        self.responder(200, destino.read_bytes(), tipo)

    def despachar(self, metodo):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self.estatico(url.path) if metodo == "GET" else self.responder(405, b"", "text/plain")
        db = conectar()
        en_tx = False
        try:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > MAX_BODY:
                raise ApiError(413, "La solicitud es demasiado grande.")
            body = {}
            if metodo in ("POST", "PUT"):
                if "application/json" not in self.headers.get("Content-Type", ""):
                    raise ApiError(415, "Se esperaba JSON.")
                body = json.loads(self.rfile.read(largo) or b"{}")
                if not isinstance(body, dict):
                    raise ApiError(400, "Solicitud inválida.")
            user = usuario_de_cookie(db, self)
            for m, patron, modulo, nivel, publica, accion, fn in RUTAS:
                coincide = patron.match(url.path)
                if m != metodo or not coincide:
                    continue
                if not publica:
                    if not user:
                        raise ApiError(401, "Debes iniciar sesión.")
                    if modulo and user["permisos"].get(modulo, 0) < nivel:
                        raise ApiError(403, "Tu perfil no tiene acceso a esta acción.")
                    if accion and not user["permisos"].get("acc_" + accion):
                        raise ApiError(403, f"Tu perfil no tiene permiso para: {dict((a, n) for a, n, _ in ACCIONES)[accion]}.")
                if metodo != "GET":
                    db.execute("BEGIN IMMEDIATE")
                    en_tx = True
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                resultado = fn(Ctx(db, user, body, q, self.headers), *coincide.groups())
                if en_tx:
                    db.execute("COMMIT")
                    en_tx = False
                if isinstance(resultado, Archivo):
                    return self.responder(200, resultado.contenido, "application/octet-stream", descarga=resultado.nombre)
                if isinstance(resultado, tuple):
                    return self.json(200, resultado[0], cookie=resultado[1])
                if isinstance(resultado, dict) and isinstance(resultado.get("usuario"), dict):
                    resultado["usuario"] = {k: v for k, v in resultado["usuario"].items() if not k.startswith("_")}
                return self.json(200, resultado)
            raise ApiError(404, "Ruta no encontrada.")
        except ApiError as e:
            if en_tx:
                db.execute("ROLLBACK")
            self.json(e.status, {"error": e.mensaje})
        except sqlite3.IntegrityError as e:
            if en_tx:
                db.execute("ROLLBACK")
            texto = str(e)
            msg = "Ya existe un registro con ese dato." if "UNIQUE" in texto else "No se puede completar: el registro está en uso o la referencia no es válida."
            self.json(409, {"error": msg})
        except json.JSONDecodeError:
            self.json(400, {"error": "Solicitud inválida."})
        except Exception:
            if en_tx:
                db.execute("ROLLBACK")
            import traceback
            traceback.print_exc()
            self.json(500, {"error": "Ocurrió un error interno. Revisa la consola del servidor."})
        finally:
            db.close()


def main():
    db = conectar()
    sembrar(db)
    db.close()
    host = os.environ.get("NS_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("NS_PORT", "8080"))
    print(f"Nata & Schlott disponible en http://{'localhost' if host == '127.0.0.1' else host}:{port}  (Ctrl+C para detener)")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
