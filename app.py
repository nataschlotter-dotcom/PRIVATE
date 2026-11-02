#!/usr/bin/env python3
"""Sistema de producción y logística de Nata & Schlott.

Servidor sin dependencias externas (Python 3.10+ y SQLite).
Variables de entorno: PORT o NS_PORT (8080), NS_HOST (127.0.0.1), NS_DB (nata_schlott.db), NS_CLAVE_INSTALACION.
"""
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
import time
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
CREATE TABLE IF NOT EXISTS categorias(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, punto_venta INTEGER NOT NULL DEFAULT 0);
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
  obs TEXT NOT NULL DEFAULT '', estado TEXT NOT NULL DEFAULT 'VIGENTE', usuario_id INTEGER REFERENCES usuarios(id));
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
CREATE TABLE IF NOT EXISTS inventarios(id INTEGER PRIMARY KEY, fecha TEXT NOT NULL, bodega_id INTEGER NOT NULL, estado TEXT NOT NULL DEFAULT 'ABIERTO',
  obs TEXT NOT NULL DEFAULT '', usuario_id INTEGER REFERENCES usuarios(id), cerrado TEXT, seccion TEXT NOT NULL DEFAULT '');
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


def crear_compra(db, uid, d):
    fecha = fecha_valida(d.get("fecha"))
    prov = entero(d.get("proveedor_id"), "el proveedor")
    proveedor = row(db, "SELECT * FROM proveedores WHERE id=? AND activo=1", prov)
    if not proveedor:
        raise ApiError(400, "Proveedor no válido o inactivo.")
    items = lineas(d.get("items"), "El precio")
    pct = iva_actual(db)
    neto = round(sum(i["cantidad"] * i["precio"] for i in items), 2)
    iva = round(neto * pct / 100, 2)
    cur = db.execute("INSERT INTO compras(fecha,proveedor_id,documento,iva_pct,neto,iva,total,obs,usuario_id) VALUES(?,?,?,?,?,?,?,?,?)",
                     (fecha, prov, txt(d.get("documento"), "El documento", False, 40), pct, neto, iva, round(neto + iva, 2),
                      txt(d.get("obs"), "La observación", False, 500), uid))
    cid = cur.lastrowid
    ref = f"Compra #{cid}" + (f" · Doc. {d.get('documento')}" if d.get("documento") else "")
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
    """Costo unitario según receta vigente, resolviendo subproductos recursivamente."""
    memo = {} if memo is None else memo
    if art_id in memo:
        return memo[art_id]
    r = receta_de(db, art_id)
    if not r:
        memo[art_id] = costo_de(articulo(db, art_id))
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
        c.punto_venta, c.nombre categoria, u.abreviatura unidad, COALESCE(s.cantidad,0) cantidad
        FROM articulos a JOIN categorias c ON c.id=a.categoria_id JOIN unidades u ON u.id=a.unidad_id
        LEFT JOIN stock s ON s.articulo_id=a.id AND s.bodega_id=?
        WHERE a.activo=1 {filtro} ORDER BY a.tipo, a.nombre""", bodega)


# ---------------------------------------------------------------- enrutador

RUTAS = []


def ruta(metodo, patron, modulo=None, nivel=1, publica=False):
    def deco(fn):
        RUTAS.append((metodo, re.compile("^" + patron + "$"), modulo, nivel, publica, fn))
        return fn
    return deco


class Ctx:
    def __init__(self, db, user, body, q):
        self.db, self.user, self.body, self.q = db, user, body, q

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
            "usuario": c.user, "modulos": [{"id": m, "nombre": n} for m, n in MODULOS]}


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
    return json.dumps({m: int(v[m]) for m in TODOS if m in v and int(v[m]) in (1, 2)})


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

def crud_simple(tabla, modulo, campos):
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
        ks = ",".join(f"{k}=?" for k, _ in campos)
        c.db.execute(f"UPDATE {tabla} SET {ks} WHERE id=?", [*limpiar(c.body), int(i)])
        if "activo" in c.body:
            c.db.execute(f"UPDATE {tabla} SET activo=? WHERE id=?", (1 if c.body["activo"] else 0, int(i)))
        return {"ok": True}

    @ruta("DELETE", ruta_base + r"/(\d+)", modulo, 2)
    def borrar(c, i):
        c.db.execute(f"DELETE FROM {tabla} WHERE id=?", (int(i),))
        return {"ok": True}


nombre_campo = lambda v: txt(v, "El nombre", True, 120)
crud_simple("proveedores", "proveedores", [("nombre", nombre_campo), ("rut", normalizar_rut)])
crud_simple("categorias", "articulos", [("nombre", nombre_campo)])
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


@ruta("GET", "/api/config/respaldo", "config", 2)
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

def datos_articulo(db, d):
    tipo = d.get("tipo")
    if tipo not in ("PRODUCTO", "SUBPRODUCTO", "INSUMO"):
        raise ApiError(400, "Tipo de artículo no válido.")
    # Un insumo de punto de venta se comporta como desechable: se despacha a tiendas y no entra en recetas
    punto_venta = scalar(db, "SELECT punto_venta FROM categorias WHERE id=?", entero(d.get("categoria_id"), "la categoría"))
    if punto_venta and tipo != "INSUMO":
        raise ApiError(400, "Esa clasificación es solo para insumos de puntos de venta.")
    return (tipo, 1 if tipo == "INSUMO" and (d.get("desechable") or punto_venta) else 0, entero(d.get("categoria_id"), "la categoría"),
            entero(d.get("unidad_id"), "la unidad de medida"), txt(d.get("codigo"), "El código", True, 30).upper(),
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
                               (*v, costo)).lastrowid}


@ruta("PUT", r"/api/articulos/(\d+)", "articulos", 2)
def articulos_editar(c, i):
    v, i = datos_articulo(c.db, c.body), int(i)
    a = articulo(c.db, i)
    if a["tipo"] != v[0] and scalar(c.db, "SELECT COUNT(*) FROM movimientos WHERE articulo_id=?", i):
        raise ApiError(409, "No se puede cambiar el tipo de un artículo con movimientos.")
    if v[1] and scalar(c.db, "SELECT COUNT(*) FROM receta_items WHERE articulo_id=?", i):
        raise ApiError(409, "Este insumo está en una receta: quítalo de ella antes de marcarlo como desechable o de punto de venta.")
    c.db.execute("UPDATE articulos SET tipo=?,desechable=?,categoria_id=?,unidad_id=?,codigo=?,nombre=?,stock_minimo=?,precio=?,activo=? WHERE id=?",
                 (*v, 1 if c.body.get("activo", True) else 0, i))
    return {"ok": True}


RELACIONES_ARTICULO = (("movimientos", "movimientos en el historial"), ("compra_items", "compras"), ("devolucion_items", "devoluciones a proveedores"), ("historial_precios", "historial de precios"),
                       ("producciones", "producciones"), ("despacho_items", "guías de despacho"), ("mermas", "mermas"), ("salidas_tienda", "ventas o consumos de tienda"),
                       ("recetas", "una receta propia"), ("receta_items", "recetas donde es ingrediente"))


@ruta("DELETE", r"/api/articulos/(\d+)", "articulos", 2)
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


@ruta("DELETE", r"/api/recetas/(\d+)", "recetas", 2)
def receta_borrar(c, art_id):
    c.db.execute("DELETE FROM recetas WHERE articulo_id=?", (int(art_id),))
    return {"ok": True}


@ruta("GET", "/api/produccion", "produccion")
def produccion_lista(c):
    d, h = c.rango(365)
    return rows(c.db, """SELECT p.*, a.codigo, a.nombre, a.tipo, un.abreviatura unidad, u.nombre usuario FROM producciones p
        JOIN articulos a ON a.id=p.articulo_id JOIN unidades un ON un.id=a.unidad_id LEFT JOIN usuarios u ON u.id=p.usuario_id
        WHERE p.fecha BETWEEN ? AND ? ORDER BY p.fecha DESC, p.id DESC LIMIT 500""", d, h)


@ruta("POST", "/api/produccion", "produccion", 2)
def produccion_crear(c):
    return {"id": crear_produccion(c.db, c.uid, c.body)}


@ruta("POST", r"/api/produccion/(\d+)/anular", "produccion", 2)
def produccion_anular(c, i):
    anular(c.db, c.uid, "producciones", "PRODUCCION", int(i))
    return {"ok": True}


# ---------------------------------------------------------------- compras

@ruta("GET", "/api/compras", "compras")
def compras_lista(c):
    d, h = c.rango(365)
    return rows(c.db, """SELECT co.*, p.nombre proveedor, p.rut, u.nombre usuario FROM compras co JOIN proveedores p ON p.id=co.proveedor_id
        LEFT JOIN usuarios u ON u.id=co.usuario_id WHERE co.fecha BETWEEN ? AND ? ORDER BY co.fecha DESC, co.id DESC LIMIT 500""", d, h)


@ruta("GET", r"/api/compras/(\d+)", "compras")
def compras_detalle(c, i):
    r = row(c.db, "SELECT co.*, p.nombre proveedor, p.rut, u.nombre usuario FROM compras co JOIN proveedores p ON p.id=co.proveedor_id "
                  "LEFT JOIN usuarios u ON u.id=co.usuario_id WHERE co.id=?", int(i))
    if not r:
        raise ApiError(404, "Compra no encontrada.")
    r["items"] = rows(c.db, "SELECT ci.*, a.codigo, a.nombre, u.abreviatura unidad FROM compra_items ci JOIN articulos a ON a.id=ci.articulo_id "
                            "JOIN unidades u ON u.id=a.unidad_id WHERE ci.compra_id=?", int(i))
    return r


@ruta("POST", "/api/compras", "compras", 2)
def compras_crear(c):
    return {"id": crear_compra(c.db, c.uid, c.body)}


@ruta("POST", r"/api/compras/(\d+)/anular", "compras", 2)
def compras_anular(c, i):
    anular(c.db, c.uid, "compras", "COMPRA", int(i))
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
        COALESCE(f.proveedor_id,'') proveedor_id, COALESCE(f.monto,'TOTAL') monto, CASE WHEN f.api_secret<>'' THEN 1 ELSE 0 END conectada,
        CASE WHEN f.api_key<>'' THEN substr(f.api_key,-4) ELSE '' END key_final
        FROM tiendas t LEFT JOIN fudo_tiendas f ON f.tienda_id=t.id WHERE t.activo=1 ORDER BY t.nombre""")


@ruta("PUT", r"/api/fudo/(\d+)/credenciales", "config", 2)
def fudo_credenciales(c, t):
    t = int(t)
    if not row(c.db, "SELECT id FROM tiendas WHERE id=?", t):
        raise ApiError(404, "Tienda no encontrada.")
    actual = row(c.db, "SELECT * FROM fudo_tiendas WHERE tienda_id=?", t) or {}
    clave = txt(c.body.get("api_key"), "la API Key", not actual.get("api_key"), 200) or actual.get("api_key")
    secreto = txt(c.body.get("api_secret"), "la API Secret", not actual.get("api_secret"), 500) or actual.get("api_secret")
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
    fudo_config(c.db, int(t))
    categoria_id = txt(d.get("categoria_id"), "la categoría de gasto", True, 10)
    if not categoria_id.isdigit() or not str(d.get("proveedor_id") or "0").isdigit():
        raise ApiError(400, "Categoría o proveedor no válidos.")
    c.db.execute("UPDATE fudo_tiendas SET categoria_id=?,categoria=?,proveedor_id=?,proveedor=?,monto=? WHERE tienda_id=?",
                 (categoria_id, txt(d.get("categoria"), "La categoría", False, 120), str(d.get("proveedor_id") or ""), txt(d.get("proveedor"), "El proveedor", False, 120), d["monto"], int(t)))
    return {"ok": True}


def fudo_gasto(g, cfg):
    num_guia = f"GD-{g['id']:06d}"
    relaciones = {"expenseCategory": {"data": {"id": cfg["categoria_id"], "type": "ExpenseCategory"}}}
    if cfg["proveedor_id"]:
        relaciones["provider"] = {"data": {"id": cfg["proveedor_id"], "type": "Provider"}}
    return {"data": {"type": "Expense", "attributes": {
        "amount": round(g["total"] if cfg["monto"] == "TOTAL" else g["neto"]), "date": g["fecha"][:10], "useInCashCount": False,
        "receiptNumber": num_guia, "description": f"Guía de despacho interna N° {g['id']:06d} desde Nata & Schlott"}, "relationships": relaciones}}


def fudo_guardar(db, gid, estado, gasto=None, error=""):
    if gasto is None:
        db.execute("UPDATE despachos SET fudo_estado=?,fudo_error=? WHERE id=?", (estado, error, gid))
    else:
        db.execute("UPDATE despachos SET fudo_estado=?,fudo_gasto_id=?,fudo_error=? WHERE id=?", (estado, gasto, error, gid))


@ruta("POST", r"/api/despachos/(\d+)/fudo", "despachos", 2)
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
    if not cfg["categoria_id"]:
        raise ApiError(400, "Falta elegir la categoría de gasto de esta tienda en Administración → Integración Fudo.")
    fudo_guardar(c.db, gid, "ENVIANDO")
    cuerpo = fudo_gasto(g, cfg)
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
    return {"ok": True, "gasto_id": gasto}


@ruta("POST", r"/api/despachos/(\d+)/fudo/anular", "despachos", 2)
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
    return {"ok": True}


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


@ruta("POST", r"/api/devoluciones/(\d+)/anular", "devoluciones", 2)
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
        (SELECT COUNT(*) FROM despacho_items i WHERE i.despacho_id=de.id) lineas
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
    return r


@ruta("POST", "/api/despachos", "despachos", 2)
def despachos_crear(c):
    c.sin_tienda()
    return {"id": crear_despacho(c.db, c.uid, c.body)}


@ruta("POST", r"/api/despachos/(\d+)/anular", "despachos", 2)
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


@ruta("POST", r"/api/mermas/(\d+)/anular", "mermas", 2)
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
    return rows(c.db, f"""SELECT i.*, COALESCE(t.nombre,'Bodega central') bodega, u.nombre usuario,
        (SELECT COUNT(*) FROM inventario_items x WHERE x.inventario_id=i.id) lineas,
        (SELECT COUNT(*) FROM inventario_items x WHERE x.inventario_id=i.id AND x.conteo IS NOT NULL) contadas,
        (SELECT COUNT(*) FROM inventario_items x WHERE x.inventario_id=i.id AND ABS(COALESCE(x.diferencia,0))>0) con_diferencia
        FROM inventarios i LEFT JOIN tiendas t ON t.id=i.bodega_id LEFT JOIN usuarios u ON u.id=i.usuario_id
        {'WHERE i.bodega_id=' + str(int(propia)) if propia else ''} ORDER BY i.id DESC LIMIT 200""")


def inventario_de(c, i):
    inv = row(c.db, "SELECT i.*, COALESCE(t.nombre,'Bodega central') bodega FROM inventarios i LEFT JOIN tiendas t ON t.id=i.bodega_id WHERE i.id=?", int(i))
    if not inv or (c.user.get("tienda_id") and c.user["tienda_id"] != inv["bodega_id"]):
        raise ApiError(404, "Inventario no encontrado.")
    return inv


@ruta("GET", r"/api/inventarios/(\d+)", "inventario")
def inventarios_detalle(c, i):
    inv = inventario_de(c, i)
    inv["items"] = rows(c.db, """SELECT x.*, a.codigo, a.nombre, a.tipo, a.desechable, a.costo, u.abreviatura unidad, COALESCE(s.cantidad,0) stock_actual
        FROM inventario_items x JOIN articulos a ON a.id=x.articulo_id JOIN unidades u ON u.id=a.unidad_id
        LEFT JOIN stock s ON s.articulo_id=a.id AND s.bodega_id=? WHERE x.inventario_id=? ORDER BY a.tipo, a.nombre""", inv["bodega_id"], int(i))
    return inv


@ruta("POST", "/api/inventarios", "inventario", 2)
def inventarios_crear(c):
    bodega = c.bodega(c.body.get("bodega_id"))
    seccion = (c.body.get("seccion") or "") if bodega == CENTRAL else ""
    if seccion and seccion not in SECCIONES:
        raise ApiError(400, "Sección de bodega no válida.")
    if row(c.db, "SELECT id FROM inventarios WHERE bodega_id=? AND estado='ABIERTO' AND (seccion=? OR seccion='' OR ?='')", bodega, seccion, seccion):
        raise ApiError(409, "Esta bodega ya tiene una toma de inventario abierta.")
    iid = c.db.execute("INSERT INTO inventarios(fecha,bodega_id,seccion,obs,usuario_id) VALUES(?,?,?,?,?)",
                       (fecha_valida(c.body.get("fecha")), bodega, seccion, txt(c.body.get("obs"), "La observación", False, 500), c.uid)).lastrowid
    for a in articulos_de_bodega(c.db, bodega, seccion):
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
    guardar_conteos(c, inv["id"])
    return {"ok": True}


@ruta("POST", r"/api/inventarios/(\d+)/cerrar", "inventario", 2)
def inventarios_cerrar(c, i):
    inv = inventario_de(c, i)
    if inv["estado"] != "ABIERTO":
        raise ApiError(409, "La toma ya está cerrada.")
    guardar_conteos(c, inv["id"])
    contados = rows(c.db, "SELECT * FROM inventario_items WHERE inventario_id=? AND conteo IS NOT NULL", inv["id"])
    if not contados:
        raise ApiError(400, "Ingresa al menos un conteo antes de cerrar.")
    hoy = date.today().isoformat()
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


@ruta("DELETE", r"/api/inventarios/(\d+)", "inventario", 2)
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


@ruta("GET", "/api/reportes/cobertura", "reportes")
def reporte_cobertura(c):
    """Días de stock central según el consumo real del período, y cantidad sugerida de reposición."""
    c.sin_tienda()
    d, h = c.rango(30)
    dias = max((date.fromisoformat(h) - date.fromisoformat(d)).days + 1, 1)
    out = rows(c.db, """SELECT a.id, a.codigo, a.nombre, a.tipo, a.desechable, a.stock_minimo, a.costo, u.abreviatura unidad, COALESCE(s.cantidad,0) stock,
        COALESCE((SELECT -SUM(m.cantidad) FROM movimientos m WHERE m.articulo_id=a.id AND m.bodega_id=0 AND m.cantidad<0
          AND m.tipo IN ('CONSUMO_PRODUCCION','DESPACHO','MERMA') AND substr(m.fecha,1,10) BETWEEN ? AND ?),0) salidas
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
    columnas_despacho = [col[1] for col in db.execute("PRAGMA table_info(despachos)")]
    for col in ("fudo_estado", "fudo_gasto_id", "fudo_error"):  # bases creadas antes de la integración con Fudo
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
    if not scalar(db, "SELECT COUNT(*) FROM config WHERE clave='permisos_devoluciones'"):  # los perfiles de bases anteriores no traen este módulo
        for p in rows(db, "SELECT * FROM perfiles WHERE nombre IN (?,?,?)", PERFIL_ADMIN, "Bodega y logística", "Gerencia"):
            permisos = json.loads(p["permisos"])
            permisos.setdefault("devoluciones", PERFILES[p["nombre"]]["devoluciones"])
            db.execute("UPDATE perfiles SET permisos=? WHERE id=?", (json.dumps(permisos), p["id"]))
        db.execute("INSERT INTO config VALUES('permisos_devoluciones','1')")
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
                          (tipo, desechable, cat[categoria], uni[unidad], cod, nombre, minimo, precio, precio if tipo == "INSUMO" else 0)).lastrowid

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
            crear_compra(db, uid, {"fecha": f, "proveedor_id": provs[p], "documento": f"F-{10000 + semana * 10 + p}", "items": items})
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
            for m, patron, modulo, nivel, publica, fn in RUTAS:
                coincide = patron.match(url.path)
                if m != metodo or not coincide:
                    continue
                if not publica:
                    if not user:
                        raise ApiError(401, "Debes iniciar sesión.")
                    if modulo and user["permisos"].get(modulo, 0) < nivel:
                        raise ApiError(403, "Tu perfil no tiene acceso a esta acción.")
                if metodo != "GET":
                    db.execute("BEGIN IMMEDIATE")
                    en_tx = True
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                resultado = fn(Ctx(db, user, body, q), *coincide.groups())
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
