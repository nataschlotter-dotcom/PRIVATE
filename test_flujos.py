"""Prueba de punta a punta contra un servidor real: python test_flujos.py"""
import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
cid = next(x["id"] for x in cat["categorias"] if not x["punto_venta"])
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

# Códigos: correlativo por clasificación; lo enviado por el cliente se ignora
def codigo_de(i):
    return next(x["codigo"] for x in A("GET", "/articulos") if x["id"] == i)


assert [codigo_de(x) for x in (harina, vaso, base, torta)] == ["IN0001", "IND0001", "SP0001", "P0001"]
cat_pv = next(x["id"] for x in cat["categorias"] if x["punto_venta"])
ipv = A("POST", "/articulos", {"tipo": "INSUMO", "nombre": "PV", "categoria_id": cat_pv, "unidad_id": un})
assert ipv["codigo"] == "IPV0001"
A("PUT", f"/articulos/{ipv['id']}", {"tipo": "INSUMO", "codigo": "OTRO", "nombre": "PV2", "categoria_id": cat_pv, "unidad_id": un})
assert codigo_de(ipv["id"]) == "IPV0001"  # editar conserva el código
A("DELETE", f"/articulos/{ipv['id']}")
in2 = art("INSUMO", "X", un)
assert codigo_de(in2) == "IN0002"  # IND e IPV no cuentan para IN
c_cod = app.conectar()
c_cod.execute("UPDATE articulos SET codigo='IN0099' WHERE id=?", (in2,))  # códigos previos: se sigue desde el mayor
c_cod.close()
in3 = art("INSUMO", "Y", un)
assert codigo_de(in3) == "IN0100"
A("DELETE", f"/articulos/{in2}"); A("DELETE", f"/articulos/{in3}")


def stock(bodega=0):
    return {r["articulo_id"]: r["cantidad"] for r in A("GET", f"/bodegas/stock?bodega={bodega}")}


# Compra: stock, IVA, precio y CPP
c1 = A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "fecha": "2026-01-10", "items": [{"articulo_id": harina, "cantidad": 10, "precio": 1000}, {"articulo_id": vaso, "cantidad": 100, "precio": 50}]})["id"]
d = A("GET", f"/compras/{c1}")
casi(d["neto"], 15000); casi(d["iva"], 2850); casi(d["total"], 17850)
A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "fecha": "2026-01-20", "items": [{"articulo_id": harina, "cantidad": 10, "precio": 1200}]})
a = next(x for x in A("GET", "/articulos") if x["id"] == harina)
casi(a["precio"], 1200); casi(a["costo"], 1100); casi(a["stock"], 20); casi(a["stock_minimo"], 1234.56789)
A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "items": [{"articulo_id": torta, "cantidad": 1, "precio": 1}]}, 400)  # solo insumos
A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": -1, "precio": 1}]}, 400)
A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "items": []}, 400)

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

# Insumos puntos de venta: clasificados, en su sección, despachables y fuera de recetas
cats = {x["nombre"]: x for x in A("GET", "/categorias")}
assert all(cats[n]["punto_venta"] == 1 for n in app.CATEGORIAS_PUNTO_VENTA) and sum(x["punto_venta"] for x in cats.values()) == 8
cafe = A("POST", "/articulos", {"tipo": "INSUMO", "codigo": "CAF", "nombre": "Cafe", "categoria_id": cats["Café"]["id"], "unidad_id": kg, "precio": 100})["id"]
A("POST", "/articulos", {"tipo": "PRODUCTO", "codigo": "MAL", "nombre": "Malo", "categoria_id": cats["Café"]["id"], "unidad_id": kg}, 400)
cafe_art = next(x for x in A("GET", "/articulos") if x["id"] == cafe)
assert cafe_art["desechable"] == 1 and cafe_art["punto_venta"] == 1
A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "numero": "PV1", "items": [{"articulo_id": cafe, "cantidad": 5, "precio": 100}]})
gp = A("POST", "/despachos", {"tienda_id": tienda2, "items": [{"articulo_id": cafe, "cantidad": 2}, {"articulo_id": vaso, "cantidad": 1}]})["id"]
it = {i["articulo_id"]: i for i in A("GET", f"/despachos/{gp}")["items"]}
assert it[cafe]["punto_venta"] == 1 and it[cafe]["categoria"] == "Café"
casi(stock(tienda2)[cafe], 2)
assert all(x["punto_venta"] == 1 for x in A("GET", "/movimientos?desde=2026-01-01&clase=PUNTO_VENTA")) and A("GET", "/movimientos?desde=2026-01-01&clase=PUNTO_VENTA")
tp = A("POST", "/inventarios", {"bodega_id": 0, "seccion": "PUNTO_VENTA"})["id"]
assert {i["articulo_id"] for i in A("GET", f"/inventarios/{tp}")["items"]} == {cafe}
A("DELETE", f"/inventarios/{tp}")
A("POST", f"/despachos/{gp}/anular", {})

# Eliminar artículos: solo si no tienen relaciones, y sin dejar líneas sueltas en tomas
libre = art("INSUMO", "LIBRE", un)
tl = A("POST", "/inventarios", {"bodega_id": 0, "seccion": "INSUMOS"})["id"]
A("DELETE", f"/articulos/{libre}")
assert libre not in {x["id"] for x in A("GET", "/articulos")} and libre not in {i["articulo_id"] for i in A("GET", f"/inventarios/{tl}")["items"]}
A("DELETE", f"/inventarios/{tl}")
A("DELETE", "/articulos/999999", esperado=404)
for relacionado in (harina, vaso, base, torta, cafe):
    A("DELETE", f"/articulos/{relacionado}", esperado=409)
contado = art("INSUMO", "CONTADO", un)
tc = A("POST", "/inventarios", {"bodega_id": 0, "seccion": "INSUMOS"})["id"]
A("PUT", f"/inventarios/{tc}", {"items": [{"articulo_id": contado, "conteo": 0}]})
A("DELETE", f"/articulos/{contado}", esperado=409)
A("DELETE", f"/inventarios/{tc}"); A("DELETE", f"/articulos/{contado}")
cat_libre = A("POST", "/categorias", {"nombre": "Sin uso"})["id"]; A("DELETE", f"/categorias/{cat_libre}")
A("DELETE", f"/categorias/{cats['Café']['id']}", esperado=409)

# Toma por sección de la bodega central: cada una cuenta solo sus artículos y pueden coexistir
A("POST", "/inventarios", {"bodega_id": 0, "seccion": "OTRA"}, 400)
ti = A("POST", "/inventarios", {"bodega_id": 0, "seccion": "INSUMOS"})["id"]
td = A("POST", "/inventarios", {"bodega_id": 0, "seccion": "DESECHABLES"})["id"]
A("POST", "/inventarios", {"bodega_id": 0, "seccion": "INSUMOS"}, 409)
A("POST", "/inventarios", {"bodega_id": 0}, 409)
ids_i = {i["articulo_id"] for i in A("GET", f"/inventarios/{ti}")["items"]}
assert harina in ids_i and vaso not in ids_i and torta not in ids_i
assert {i["articulo_id"] for i in A("GET", f"/inventarios/{td}")["items"]} == {vaso}
A("DELETE", f"/inventarios/{ti}"); A("DELETE", f"/inventarios/{td}")
te = A("POST", "/inventarios", {"bodega_id": 0, "seccion": "ELABORADOS"})["id"]
assert torta in {i["articulo_id"] for i in A("GET", f"/inventarios/{te}")["items"]}
A("DELETE", f"/inventarios/{te}")

# Anular guía: revierte, pero no si la tienda ya no tiene el stock
A("POST", f"/despachos/{g}/anular", {}, 409)  # los vasos ya bajaron a 28,5 de 30
s0 = stock(); assert abs(s0[vaso] - 70) < 1e-6 and stock(tienda)[torta] == 1  # sin cambios parciales
g2 = A("POST", "/despachos", {"tienda_id": tienda2, "items": [{"articulo_id": vaso, "cantidad": 10}]})["id"]
A("POST", f"/despachos/{g2}/anular", {})
casi(stock()[vaso], 70); casi(stock(tienda2)[vaso], 0)

# Anular compra revierte stock y precio
c3 = A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "fecha": "2026-02-01", "items": [{"articulo_id": harina, "cantidad": 5, "precio": 2000}]})["id"]
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
# Compras: factura o boleta es obligatorio
s_doc = stock()[harina]
A("POST", "/compras", {"proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1}]}, 400)
A("POST", "/compras", {"tipo_documento": "GUIA", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1}]}, 400)
cb = A("POST", "/compras", {"tipo_documento": "BOLETA", "documento": "55", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1200}]})["id"]
assert A("GET", f"/compras/{cb}")["tipo_documento"] == "BOLETA" and any(x["tipo_documento"] == "BOLETA" for x in A("GET", "/compras"))
assert any(x["referencia"] == f"Compra #{cb} · Boleta 55" for x in A("GET", "/movimientos?desde=2026-01-01&tipo=COMPRA"))
A("POST", f"/compras/{cb}/anular", {})
casi(stock()[harina], s_doc)

# Fudo: contra un servidor simulado, sin duplicar gastos ante respuestas inciertas
class FudoFalso(BaseHTTPRequestHandler):
    gastos, modo, tokens = [], "ok", 0

    def log_message(self, *_):
        pass

    def responder(self, status, datos):
        b = json.dumps(datos).encode()
        self.send_response(status); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def leer(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

    def do_POST(self):
        d, cls = self.leer(), FudoFalso
        if self.path == "/auth":
            if d.get("apiSecret") != "secreto-correcto":
                return self.responder(401, {"errors": [{"title": "Credenciales"}]})
            cls.tokens += 1
            return self.responder(200, {"token": "tok", "exp": 9999999999})
        assert self.headers["Authorization"] == "Bearer tok" and self.path == "/api/expenses"
        if cls.modo == "rechazo":
            return self.responder(422, {"errors": [{"detail": "Categoría inválida"}]})
        cls.gastos.append(d)
        if cls.modo == "caida":
            return self.responder(500, {})
        self.responder(201, {"data": {"id": str(len(cls.gastos)), "type": "Expense"}})

    def do_PATCH(self):
        FudoFalso.ultimo_patch = (self.path, self.leer())
        self.responder(200, {"data": {}})

    def do_GET(self):
        n = "Categoría" if "categories" in self.path else "Proveedor"
        self.responder(200, {"data": [{"id": "7", "attributes": {"name": n}}]})


falso = ThreadingHTTPServer(("127.0.0.1", 0), FudoFalso)
threading.Thread(target=falso.serve_forever, daemon=True).start()
app.FUDO_API = f"http://127.0.0.1:{falso.server_address[1]}/api"
app.FUDO_AUTH = f"http://127.0.0.1:{falso.server_address[1]}/auth"
gf = A("POST", "/despachos", {"tienda_id": tienda2, "fecha": "2026-03-04", "items": [{"articulo_id": vaso, "cantidad": 2}]})["id"]
for cli in (T, P):
    cli("POST", f"/despachos/{gf}/fudo", {}, 403); cli("GET", "/fudo", esperado=403)
    cli("PUT", f"/fudo/{tienda2}/credenciales", {"api_key": "k", "api_secret": "s"}, 403)
A("POST", f"/despachos/{gf}/fudo", {}, 400)  # sin conexión
A("POST", f"/fudo/{tienda2}/probar", {}, 400)
A("PUT", f"/fudo/{tienda2}/credenciales", {"api_key": "clave-1234", "api_secret": "malo"})
A("POST", f"/fudo/{tienda2}/probar", {}, 502)
A("PUT", f"/fudo/{tienda2}/credenciales", {"api_secret": "secreto-correcto"})
lista_f = A("GET", "/fudo")
assert "secreto-correcto" not in json.dumps(lista_f) and "clave-1234" not in json.dumps(lista_f)
assert next(x for x in lista_f if x["tienda_id"] == tienda2)["key_final"] == "1234"
pr = A("POST", f"/fudo/{tienda2}/probar", {})
assert pr["categorias"] == [{"id": "7", "nombre": "Categoría"}]
A("POST", f"/despachos/{gf}/fudo", {}, 400)  # falta categoría
A("PUT", f"/fudo/{tienda2}/gastos", {"categoria_id": "abc", "monto": "TOTAL"}, 400)
A("PUT", f"/fudo/{tienda2}/gastos", {"categoria_id": "7", "categoria": "Categoría", "proveedor_id": "7", "proveedor": "Proveedor", "monto": "TOTAL"})
FudoFalso.modo = "rechazo"
r_f = A("POST", f"/despachos/{gf}/fudo", {})
assert not r_f["ok"] and "Categoría inválida" in r_f["error"] and A("GET", f"/despachos/{gf}")["fudo_estado"] == ""
FudoFalso.modo = "caida"
assert not A("POST", f"/despachos/{gf}/fudo", {})["ok"] and len(FudoFalso.gastos) == 1
assert A("GET", f"/despachos/{gf}")["fudo_estado"] == "REVISAR"
A("POST", f"/despachos/{gf}/fudo", {}, 409)  # incierto: no reenvía sin confirmación
assert len(FudoFalso.gastos) == 1
FudoFalso.modo, FudoFalso.gastos = "ok", []
r_f = A("POST", f"/despachos/{gf}/fudo", {"confirmar_reenvio": True})
assert r_f["ok"] and r_f["gasto_id"] == "1"
g_f = A("GET", f"/despachos/{gf}")
assert g_f["fudo_estado"] == "ENVIADO" and g_f["fudo_gasto_id"] == "1" and g_f["fudo_error"] == ""
env = FudoFalso.gastos[0]["data"]
assert env["type"] == "Expense" and env["attributes"]["date"] == "2026-03-04" and env["attributes"]["amount"] == round(g_f["total"])
assert env["attributes"]["receiptNumber"] == f"GD-{gf:06d}" and env["attributes"]["useInCashCount"] is False
assert env["relationships"]["expenseCategory"]["data"]["id"] == "7" and env["relationships"]["provider"]["data"]["type"] == "Provider"
A("POST", f"/despachos/{gf}/fudo", {"confirmar_reenvio": True}, 409)  # ya enviado
assert len(FudoFalso.gastos) == 1
A("POST", f"/despachos/{gf}/fudo/anular", {}, 409)  # la guía sigue vigente
A("POST", f"/despachos/{gf}/anular", {})
A("POST", f"/despachos/{gf}/fudo", {}, 409)  # guía anulada
assert A("POST", f"/despachos/{gf}/fudo/anular", {})["ok"]
assert FudoFalso.ultimo_patch[0] == "/api/expenses/1" and FudoFalso.ultimo_patch[1]["data"]["attributes"]["canceled"] is True
assert A("GET", f"/despachos/{gf}")["fudo_estado"] == "ANULADO"
A("POST", f"/despachos/{gf}/fudo/anular", {}, 409)
# El respaldo descargado no incluye las credenciales
conn = http.client.HTTPConnection("127.0.0.1", PUERTO); conn.request("GET", "/api/config/respaldo", headers={"Cookie": A.cookie}); resp = conn.getresponse().read()
assert b"secreto-correcto" not in resp and b"clave-1234" not in resp and resp[:15] == b"SQLite format 3"

# Devoluciones a proveedores: solo insumos, desde bodega central, con historial y anulación
for cli in (T, P):
    cli("GET", "/devoluciones", esperado=403)
    cli("POST", "/devoluciones", {}, 403)
dev = {"proveedor_id": prov, "motivo": "Mal estado", "documento": "NC-1"}
s_dev, s_vaso = stock()[harina], stock()[vaso]
costo_dev, precio_dev = (lambda a: (a["costo"], a["precio"]))(next(x for x in A("GET", "/articulos") if x["id"] == harina))
A("POST", "/devoluciones", {**dev, "items": [{"articulo_id": torta, "cantidad": 1, "precio": 1}]}, 400)
A("POST", "/devoluciones", {**dev, "items": [{"articulo_id": base, "cantidad": 1, "precio": 1}]}, 400)
A("POST", "/devoluciones", {**dev, "motivo": "", "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1}]}, 400)
A("POST", "/devoluciones", {**dev, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1}, {"articulo_id": vaso, "cantidad": s_vaso + 1, "precio": 1}]}, 409)
casi(stock()[harina], s_dev)  # sin cambios parciales
assert not A("GET", "/devoluciones")
dv = A("POST", "/devoluciones", {**dev, "items": [{"articulo_id": harina, "cantidad": 2, "precio": 1000}, {"articulo_id": vaso, "cantidad": 3, "precio": 50}]})["id"]
casi(stock()[harina], s_dev - 2); casi(stock()[vaso], s_vaso - 3)
det_dev = A("GET", f"/devoluciones/{dv}")
casi(det_dev["neto"], 2150); assert det_dev["motivo"] == "Mal estado" and len(det_dev["items"]) == 2
md = A("GET", "/movimientos?desde=2026-01-01&tipo=DEVOLUCION_PROVEEDOR")
assert len(md) == 2 and all(x["proveedor"] == "Proveedor" and x["cantidad"] < 0 for x in md)
a_dev = next(x for x in A("GET", "/articulos") if x["id"] == harina)
casi(a_dev["costo"], costo_dev); casi(a_dev["precio"], precio_dev)
A("DELETE", f"/articulos/{harina}", esperado=409)
A("POST", f"/devoluciones/{dv}/anular", {})
casi(stock()[harina], s_dev); casi(stock()[vaso], s_vaso)
A("POST", f"/devoluciones/{dv}/anular", {}, 409)
assert A("GET", f"/devoluciones/{dv}")["estado"] == "ANULADO"

# Actualizar stock: solo el perfil Administrador, sin saldos negativos y con historial
assert A("GET", "/estado")["usuario"]["permisos"]["stock"] == 2
A("PUT", f"/perfiles/{perfiles['Producción']}", {"nombre": "Producción", "permisos": {"stock": 2, "produccion": 2}})
assert "stock" not in P("GET", "/estado")["usuario"]["permisos"]
for cli in (T, P):
    cli("GET", "/actualizar-stock", esperado=403)
    cli("POST", "/actualizar-stock", {"bodega_id": 0, "motivo": "x", "items": []}, 403)
assert "stock" not in {m["id"] for m in A("GET", "/estado")["modulos"]}
A("PUT", f"/perfiles/{perfiles['Administrador']}", {"nombre": "Otro", "permisos": {"usuarios": 2}}, 409)
aj = art("INSUMO", "AJUSTE", un)
A("POST", "/actualizar-stock", {"bodega_id": 0, "motivo": "", "items": [{"articulo_id": aj, "cantidad": 5, "esperado": 0}]}, 400)
A("POST", "/actualizar-stock", {"bodega_id": 0, "motivo": "m", "items": [{"articulo_id": aj, "cantidad": -1, "esperado": 0}]}, 400)
A("POST", "/actualizar-stock", {"bodega_id": 0, "motivo": "m", "items": [{"articulo_id": aj, "cantidad": 0, "esperado": 0}]}, 400)
A("POST", "/actualizar-stock", {"bodega_id": tienda, "motivo": "m", "items": [{"articulo_id": harina, "cantidad": 1, "esperado": 0}]}, 400)
s_h = stock()[harina]
A("POST", "/actualizar-stock", {"bodega_id": 0, "motivo": "m", "items": [{"articulo_id": harina, "cantidad": s_h + 1, "esperado": s_h}, {"articulo_id": aj, "cantidad": 5, "esperado": 9}]}, 409)
casi(stock()[harina], s_h)  # sin cambios parciales
assert A("POST", "/actualizar-stock", {"bodega_id": 0, "motivo": "Carga inicial", "items": [{"articulo_id": aj, "cantidad": 5.5, "esperado": 0}]})["actualizados"] == 1
casi(stock()[aj], 5.5)
ma = A("GET", f"/movimientos?desde=2026-01-01&tipo=AJUSTE_ADMIN&articulo_id={aj}")
assert len(ma) == 1 and ma[0]["obs"] == "Carga inicial" and abs(ma[0]["saldo"] - 5.5) < 1e-6
A("POST", "/actualizar-stock", {"bodega_id": 0, "motivo": "Corrige", "items": [{"articulo_id": aj, "cantidad": 0, "esperado": 5.5}]})
casi(stock()[aj], 0)
A("POST", "/actualizar-stock", {"bodega_id": tienda, "motivo": "Local", "items": [{"articulo_id": vaso, "cantidad": stock(tienda)[vaso] + 1, "esperado": stock(tienda)[vaso]}]})
A("POST", "/actualizar-stock", {"bodega_id": tienda, "motivo": "Local", "items": [{"articulo_id": vaso, "cantidad": stock(tienda)[vaso] - 1, "esperado": stock(tienda)[vaso]}]})
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
