"""Prueba de punta a punta contra un servidor real: python test_flujos.py"""
import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

os.environ["NS_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")
import app  # noqa: E402

db = app.conectar()
app.sembrar(db)
db.close()
srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
PUERTO = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


class Cliente:
    def __init__(self):
        self.cookie = ""

    def __call__(self, metodo, ruta, cuerpo=None, esperado=200):
        c = http.client.HTTPConnection("127.0.0.1", PUERTO)
        h = {"Cookie": self.cookie}
        data = None
        if cuerpo is not None:
            data = json.dumps(cuerpo)
            h["Content-Type"] = "application/json"
        c.request(metodo, "/api" + ruta, data, h)
        r = c.getresponse()
        txt = r.read().decode()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";")[0]
        d = json.loads(txt)
        assert r.status == esperado, f"{metodo} {ruta}: {r.status} {txt[:300]} (esperado {esperado})"
        return d


def casi(a, b):
    assert abs(a - b) < 1e-4, f"{a} != {b}"


A = Cliente()
assert A("GET", "/estado")["requiere_instalacion"] is True
A("GET", "/catalogos", esperado=401)
A("POST", "/instalar", {"nombre": "Admin", "username": "admin", "password": "corta"}, 400)
A("POST", "/instalar", {"nombre": "Admin", "username": "admin", "password": "prueba-segura-1", "demo": False})
A("POST", "/instalar", {"nombre": "X", "username": "x", "password": "prueba-segura-1"}, 409)

cat = A("GET", "/catalogos")
cid = cat["categorias"][0]["id"]
kg = next(u["id"] for u in cat["unidades"] if u["abreviatura"] == "kg")
un = next(u["id"] for u in cat["unidades"] if u["abreviatura"] == "un")

# RUT: dígito verificador
A("POST", "/proveedores", {"rut": "76.123.456-1", "nombre": "Malo"}, 400)
prov = A("POST", "/proveedores", {"rut": "76123456-0", "nombre": "Proveedor"})["id"]
assert A("GET", "/proveedores")[0]["rut"] == "76.123.456-0"
A("POST", "/proveedores", {"rut": "76123456-0", "nombre": "Duplicado"}, 409)
tienda = A("POST", "/tiendas", {"nombre": "T1", "direccion": "D", "comuna": "C", "region": "R"})["id"]
tienda2 = A("POST", "/tiendas", {"nombre": "T2", "direccion": "D", "comuna": "C", "region": "R"})["id"]


def art(tipo, cod, u=kg, minimo=0, precio=0, desechable=False):
    return A("POST", "/articulos", {"tipo": tipo, "codigo": cod, "nombre": cod, "categoria_id": cid, "unidad_id": u,
                                    "stock_minimo": minimo, "precio": precio, "desechable": desechable})["id"]


harina = art("INSUMO", "HAR", minimo=1234.56789, precio=1000)
vaso = art("INSUMO", "VAS", un, precio=50, desechable=True)
base = art("SUBPRODUCTO", "BAS")
torta = art("PRODUCTO", "TOR", un, precio=20000)


def stock(bodega=0):
    return {r["articulo_id"]: r["cantidad"] for r in A("GET", f"/bodegas/stock?bodega={bodega}")}


# Compra: stock, IVA, precio y CPP
c1 = A("POST", "/compras", {"proveedor_id": prov, "fecha": "2026-01-10", "items": [{"articulo_id": harina, "cantidad": 10, "precio": 1000}, {"articulo_id": vaso, "cantidad": 100, "precio": 50}]})["id"]
d = A("GET", f"/compras/{c1}")
casi(d["neto"], 15000); casi(d["iva"], 2850); casi(d["total"], 17850)
A("POST", "/compras", {"proveedor_id": prov, "fecha": "2026-01-20", "items": [{"articulo_id": harina, "cantidad": 10, "precio": 1200}]})
a = next(x for x in A("GET", "/articulos") if x["id"] == harina)
casi(a["precio"], 1200); casi(a["costo"], 1100); casi(a["stock"], 20); casi(a["stock_minimo"], 1234.56789)
A("POST", "/compras", {"proveedor_id": prov, "items": [{"articulo_id": torta, "cantidad": 1, "precio": 1}]}, 400)  # solo insumos
A("POST", "/compras", {"proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": -1, "precio": 1}]}, 400)
A("POST", "/compras", {"proveedor_id": prov, "items": []}, 400)

# Recetas: desechable y producto no pueden ser ingrediente; sin ciclos
A("PUT", f"/recetas/{base}", {"rendimiento": 1, "items": [{"articulo_id": vaso, "cantidad": 1}]}, 400)
A("PUT", f"/recetas/{base}", {"rendimiento": 2, "items": [{"articulo_id": harina, "cantidad": 1}]})
A("PUT", f"/recetas/{torta}", {"rendimiento": 1, "items": [{"articulo_id": base, "cantidad": 0.5}]})
A("PUT", f"/recetas/{base}", {"rendimiento": 2, "items": [{"articulo_id": torta, "cantidad": 1}]}, 400)
sub2 = art("SUBPRODUCTO", "SU2")
A("PUT", f"/recetas/{sub2}", {"rendimiento": 1, "items": [{"articulo_id": base, "cantidad": 1}]})
A("PUT", f"/recetas/{base}", {"rendimiento": 2, "items": [{"articulo_id": sub2, "cantidad": 1}]}, 400)
A("PUT", f"/recetas/{sub2}", {"rendimiento": 1, "items": [{"articulo_id": sub2, "cantidad": 1}]}, 400)

# Producción descuenta según receta; falla atómicamente si falta stock
A("POST", "/produccion", {"articulo_id": torta, "cantidad": 2}, 409)
assert base not in stock() or stock()[base] == 0
p1 = A("POST", "/produccion", {"articulo_id": base, "cantidad": 4})["id"]
s = stock(); casi(s[harina], 18); casi(s[base], 4)
A("POST", "/produccion", {"articulo_id": torta, "cantidad": 2})
s = stock(); casi(s[base], 3); casi(s[torta], 2)
rec = next(r for r in A("GET", "/recetas") if r["articulo_id"] == torta)
casi(rec["costo_unit"], 275)  # 0,5 base × (1 kg harina a 1.100 / 2 bases)
A("POST", f"/produccion/{p1}/anular", {}, 409)  # la base ya se consumió: dejaría stock negativo
s = stock(); casi(s[harina], 18); casi(s[base], 3)

# Despacho: mueve de central a tienda; solo productos y desechables
A("POST", "/despachos", {"tienda_id": tienda, "items": [{"articulo_id": harina, "cantidad": 1}]}, 400)
A("POST", "/despachos", {"tienda_id": tienda, "items": [{"articulo_id": torta, "cantidad": 99}]}, 409)
g = A("POST", "/despachos", {"tienda_id": tienda, "transportista": "J", "items": [{"articulo_id": torta, "cantidad": 1}, {"articulo_id": vaso, "cantidad": 30}]})["id"]
casi(stock()[torta], 1); casi(stock()[vaso], 70); casi(stock(tienda)[torta], 1); casi(stock(tienda)[vaso], 30)
d = A("GET", f"/despachos/{g}")
assert d["direccion"] == "D" and len(d["items"]) == 2
casi(d["neto"], 20000 + 30 * 50); casi(d["total"], d["neto"] * 1.19)
assert harina not in stock(tienda)  # los insumos de receta no están en bodega de tienda

# Historial con proveedor y tienda
m = A("GET", "/movimientos?desde=2026-01-01&proveedor_id=%d" % prov)
assert m and all(x["proveedor"] == "Proveedor" for x in m)
m = A("GET", "/movimientos?desde=2026-01-01&tienda_destino_id=%d&sentido=salida" % tienda)
assert {x["tipo"] for x in m} == {"DESPACHO"} and all(x["tienda_destino"] == "T1" for x in m)

# Merma en tienda con motivo, y anulación
motivo = cat["motivos"][0]["id"]
A("POST", "/mermas", {"articulo_id": vaso, "bodega_id": tienda, "cantidad": 500, "motivo_id": motivo}, 409)
A("POST", "/mermas", {"articulo_id": vaso, "bodega_id": tienda, "cantidad": 5}, 400)
me = A("POST", "/mermas", {"articulo_id": vaso, "bodega_id": tienda, "cantidad": 5, "motivo_id": motivo, "obs": "rotos"})["id"]
casi(stock(tienda)[vaso], 25)
assert A("GET", f"/movimientos?desde=2026-01-01&tipo=MERMA")[0]["motivo"] == cat["motivos"][0]["nombre"]
A("POST", f"/mermas/{me}/anular", {})
A("POST", f"/mermas/{me}/anular", {}, 409)
casi(stock(tienda)[vaso], 30)

# Toma de inventario: ajusta contra stock al cierre y queda en historial
inv = A("POST", "/inventarios", {"bodega_id": tienda})["id"]
A("POST", "/inventarios", {"bodega_id": tienda}, 409)
det = A("GET", f"/inventarios/{inv}")
assert {i["articulo_id"] for i in det["items"]} == {torta, vaso}
A("PUT", f"/inventarios/{inv}", {"items": [{"articulo_id": vaso, "conteo": 28.5}]})
A("POST", "/bodegas/salidas", {"tienda_id": tienda, "articulo_id": vaso, "cantidad": 1, "motivo": "VENTA"})
A("POST", f"/inventarios/{inv}/cerrar", {"items": [{"articulo_id": vaso, "conteo": 28.5}]})
casi(stock(tienda)[vaso], 28.5); casi(stock(tienda)[torta], 1)  # torta sin contar: no cambia
aj = A("GET", "/movimientos?desde=2026-01-01&tipo=INVENTARIO")
assert len(aj) == 1 and abs(aj[0]["cantidad"] + 0.5) < 1e-6
A("POST", f"/inventarios/{inv}/cerrar", {}, 409)
A("DELETE", f"/inventarios/{inv}", esperado=409)

# Anular guía: revierte, pero no si la tienda ya no tiene el stock
A("POST", f"/despachos/{g}/anular", {}, 409)  # los vasos ya bajaron a 28,5 de 30
s0 = stock(); assert abs(s0[vaso] - 70) < 1e-6 and stock(tienda)[torta] == 1  # sin cambios parciales
g2 = A("POST", "/despachos", {"tienda_id": tienda2, "items": [{"articulo_id": vaso, "cantidad": 10}]})["id"]
A("POST", f"/despachos/{g2}/anular", {})
casi(stock()[vaso], 70); casi(stock(tienda2)[vaso], 0)

# Anular compra revierte stock y precio
c3 = A("POST", "/compras", {"proveedor_id": prov, "fecha": "2026-02-01", "items": [{"articulo_id": harina, "cantidad": 5, "precio": 2000}]})["id"]
assert next(x for x in A("GET", "/articulos") if x["id"] == harina)["precio"] == 2000
A("POST", f"/compras/{c3}/anular", {})
a = next(x for x in A("GET", "/articulos") if x["id"] == harina)
casi(a["precio"], 1200); casi(a["stock"], 18)

# Perfiles: el backend aplica los permisos, no solo el menú
perfiles = {p["nombre"]: p["id"] for p in A("GET", "/perfiles")}
A("POST", "/usuarios", {"nombre": "Tienda", "username": "tienda1", "password": "prueba-segura-2", "perfil_id": perfiles["Tienda"], "tienda_id": tienda})
A("POST", "/usuarios", {"nombre": "Prod", "username": "prod1", "password": "prueba-segura-3", "perfil_id": perfiles["Producción"]})
T, P = Cliente(), Cliente()
T("POST", "/login", {"username": "tienda1", "password": "mala"}, 401)
T("POST", "/login", {"username": "tienda1", "password": "prueba-segura-2"})
P("POST", "/login", {"username": "prod1", "password": "prueba-segura-3"})
assert "password" not in json.dumps(A("GET", "/usuarios"))
assert "_token" not in json.dumps(T("GET", "/estado"))
P("GET", "/compras", esperado=403); P("POST", "/usuarios", {}, 403); P("GET", "/reportes/rendimiento", esperado=403)
P("GET", "/produccion"); P("GET", "/produccion/recetas")
T("GET", "/compras", esperado=403); T("GET", "/usuarios", esperado=403); T("POST", "/despachos", {}, 403)
T("GET", "/stock/central", esperado=403)
# Usuario de tienda: solo su bodega
T("GET", f"/bodegas/stock?bodega={tienda2}", esperado=403); T("GET", "/bodegas/stock?bodega=0", esperado=403)
assert {x["articulo_id"] for x in T("GET", "/bodegas/stock") if x["cantidad"] > 0} == {torta, vaso}
assert all(x["id"] == tienda for x in T("GET", "/bodegas/resumen"))
assert all(x["bodega_id"] == tienda for x in T("GET", "/movimientos?desde=2026-01-01"))
T("GET", f"/movimientos?bodega={tienda2}", esperado=403)
assert all(x["tienda_id"] == tienda for x in T("GET", "/despachos?desde=2026-01-01"))
T("GET", f"/despachos/{g2}", esperado=404)
T("POST", "/mermas", {"articulo_id": vaso, "bodega_id": 0, "cantidad": 1, "motivo_id": motivo}, 403)
T("POST", "/inventarios", {"bodega_id": tienda2}, 403)
assert [t["id"] for t in T("GET", "/catalogos")["tiendas"]] == [tienda]

# Último administrador protegido; sesión termina al desactivar
yo = next(u for u in A("GET", "/usuarios") if u["username"] == "admin")
A("PUT", f"/usuarios/{yo['id']}", {"username": "admin", "nombre": "Admin", "perfil_id": yo["perfil_id"], "activo": False}, 409)
uid_t = next(u["id"] for u in A("GET", "/usuarios") if u["username"] == "tienda1")
A("PUT", f"/usuarios/{uid_t}", {"username": "tienda1", "nombre": "Tienda", "perfil_id": perfiles["Tienda"], "tienda_id": tienda, "activo": False})
T("GET", "/bodegas/stock", esperado=401)

# Validaciones de maestros
A("DELETE", f"/categorias/{cid}", esperado=409)  # en uso
A("PUT", "/config/iva", {"iva": 500}, 400)
A("PUT", "/config/logo", {"logo": "javascript:alert(1)"}, 400)
A("PUT", "/config/logo", {"logo": "data:image/png;base64,AAAA"})
assert A("GET", "/estado")["logo"].startswith("data:image/png")

# Coherencia: el stock siempre es igual a la suma del historial
c = app.conectar()
for r in c.execute("SELECT bodega_id, articulo_id, cantidad FROM stock").fetchall():
    t = c.execute("SELECT COALESCE(SUM(cantidad),0) FROM movimientos WHERE bodega_id=? AND articulo_id=?", (r[0], r[1])).fetchone()[0]
    casi(r[2], t)
c.close()

# Reportes
for rep in ("rendimiento", "precios", "margenes", "compras", "despachos", "mermas", "cobertura", "panel"):
    A("GET", f"/reportes/{rep}?desde=2026-01-01")
assert A("GET", "/reportes/margenes")["filas"][0]["nombre"] == "TOR"

# Datos de ejemplo: base nueva, y coherencia del historial
os.environ["NS_DB"] = app.DB_PATH = os.path.join(tempfile.mkdtemp(), "demo.db")
c = app.conectar()
app.sembrar(c)
D = Cliente()
c.close()
D("POST", "/instalar", {"nombre": "Admin", "username": "admin", "password": "prueba-segura-1", "demo": True})
for rep in ("rendimiento", "precios", "margenes", "compras", "despachos", "mermas", "cobertura", "panel"):
    D("GET", f"/reportes/{rep}")
assert D("GET", "/reportes/panel")["kpis"]["compras"] > 0
c = app.conectar()
for r in c.execute("SELECT bodega_id, articulo_id, cantidad FROM stock").fetchall():
    assert r[2] >= 0
    casi(r[2], c.execute("SELECT COALESCE(SUM(cantidad),0) FROM movimientos WHERE bodega_id=? AND articulo_id=?", (r[0], r[1])).fetchone()[0])
print("movimientos demo:", c.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0])
c.close()
srv.shutdown()
print("TODO OK")
sys.exit(0)
