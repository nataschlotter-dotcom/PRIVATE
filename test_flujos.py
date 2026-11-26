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
cid = next(x["id"] for x in cat["categorias"] if not x["punto_venta"] and not x["de_productos"])
cid_prod = next(x["id"] for x in cat["categorias"] if x["de_productos"])
assert {x["nombre"] for x in cat["categorias"] if x["de_productos"]} == set(app.CATEGORIAS_PRODUCTOS)
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
    return A("POST", "/articulos", {"tipo": tipo, "codigo": cod, "nombre": cod, "categoria_id": cid if tipo == "INSUMO" else cid_prod, "unidad_id": u,
                                    "stock_minimo": minimo, "precio": precio, "desechable": desechable})["id"]


harina = art("INSUMO", "HAR", minimo=1234.56789, precio=1000)
vaso = art("INSUMO", "VAS", un, precio=50, desechable=True)
base = art("SUBPRODUCTO", "BAS")
torta = art("PRODUCTO", "TOR", un, precio=20000)

# Códigos: correlativo por clasificación; lo enviado por el cliente se ignora
def codigo_de(i):
    return next(x["codigo"] for x in A("GET", "/articulos") if x["id"] == i)


assert [codigo_de(x) for x in (harina, vaso, base, torta)] == ["IN0001", "IDA0001", "SP0001", "P0001"]
cat_pv = next(x["id"] for x in cat["categorias"] if x["punto_venta"])
ipv = A("POST", "/articulos", {"tipo": "INSUMO", "nombre": "PV", "categoria_id": cat_pv, "unidad_id": un})
assert ipv["codigo"] == "IPV0001"
A("PUT", f"/articulos/{ipv['id']}", {"tipo": "INSUMO", "codigo": "OTRO", "nombre": "PV2", "categoria_id": cat_pv, "unidad_id": un})
assert codigo_de(ipv["id"]) == "IPV0001"  # editar conserva el código
A("DELETE", f"/articulos/{ipv['id']}")
# Cada pestaña crea en su grupo: la categoría no puede moverlo a otro
cat_comun = cid
# Tipo de categoría: productos o no productos, y clasificación de bases anteriores
A("POST", "/articulos", {"tipo": "PRODUCTO", "nombre": "M", "unidad_id": un, "categoria_id": cid}, 400)
A("POST", "/articulos", {"tipo": "SUBPRODUCTO", "nombre": "M", "unidad_id": un, "categoria_id": cid}, 400)
A("POST", "/articulos", {"tipo": "INSUMO", "nombre": "M", "unidad_id": un, "categoria_id": cid_prod}, 400)
c_nueva = A("POST", "/categorias", {"nombre": "Queques", "de_productos": "1"})["id"]
c_ins = A("POST", "/categorias", {"nombre": "Frutas", "de_productos": "0"})["id"]
por_cat = {x["id"]: x for x in A("GET", "/categorias")}
assert por_cat[c_nueva]["de_productos"] == 1 and por_cat[c_ins]["de_productos"] == 0
A("PUT", f"/categorias/{cat_pv}", {"nombre": por_cat[cat_pv]["nombre"], "de_productos": "1"}, 409)
p_nuevo = A("POST", "/articulos", {"tipo": "PRODUCTO", "nombre": "Queque", "unidad_id": un, "categoria_id": c_nueva})["id"]
i_mix = A("POST", "/articulos", {"tipo": "INSUMO", "nombre": "Mix", "unidad_id": un, "categoria_id": c_ins})["id"]
p_mix = A("POST", "/articulos", {"tipo": "PRODUCTO", "nombre": "Mix2", "unidad_id": un, "categoria_id": c_nueva})["id"]
A("PUT", f"/categorias/{c_nueva}", {"nombre": "Queques", "de_productos": "0"}, 409)  # tiene artículos
A("PUT", f"/categorias/{c_nueva}", {"nombre": "Queques 2", "de_productos": "1"})
assert {x["id"]: x["nombre"] for x in A("GET", "/categorias")}[c_nueva] == "Queques 2"
c_vacia = A("POST", "/categorias", {"nombre": "Vacia", "de_productos": "0"})["id"]
A("PUT", f"/categorias/{c_vacia}", {"nombre": "Vacia", "de_productos": "1"})  # sin artículos se puede cambiar
assert {x["id"]: x["de_productos"] for x in A("GET", "/categorias")}[c_vacia] == 1
A("DELETE", f"/categorias/{c_vacia}")
c_m = app.conectar()  # simula una base anterior: categoría usada por producto e insumo, y otra solo por producto
c_m.execute("UPDATE articulos SET categoria_id=? WHERE id=?", (c_ins, p_mix))
c_m.execute("UPDATE categorias SET de_productos=0 WHERE id=?", (c_nueva,))
c_m.execute("DELETE FROM config WHERE clave='categorias_productos'")
app.sembrar(c_m); app.sembrar(c_m)
por_cat = {x["id"]: x for x in A("GET", "/categorias")}
assert por_cat[c_nueva]["de_productos"] == 1 and por_cat[c_ins]["de_productos"] == 0
nueva_mix = next(x for x in por_cat.values() if x["nombre"] == "Frutas (productos)")
assert nueva_mix["de_productos"] == 1 and sum(x["nombre"] == "Frutas (productos)" for x in por_cat.values()) == 1
art_mix = {x["id"]: x for x in A("GET", "/articulos")}
assert art_mix[p_mix]["categoria"] == "Frutas (productos)" and art_mix[i_mix]["categoria"] == "Frutas"
for x in (p_nuevo, i_mix, p_mix):
    A("DELETE", f"/articulos/{x}")
for x in (c_nueva, c_ins, nueva_mix["id"]):
    A("DELETE", f"/categorias/{x}")
c_m.close()
base_art = {"tipo": "INSUMO", "nombre": "G", "unidad_id": un}
A("POST", "/articulos", {**base_art, "desechable": True, "punto_venta": False, "categoria_id": cat_pv}, 400)  # pestaña Desechables
A("POST", "/articulos", {**base_art, "desechable": True, "punto_venta": True, "categoria_id": cat_comun}, 400)  # pestaña Puntos de venta
A("POST", "/articulos", {**base_art, "desechable": False, "punto_venta": False, "categoria_id": cat_pv}, 400)  # pestaña Insumos
g_ida = A("POST", "/articulos", {**base_art, "desechable": True, "punto_venta": False, "categoria_id": cat_comun})
g_ipv = A("POST", "/articulos", {**base_art, "desechable": True, "punto_venta": True, "categoria_id": cat_pv})
assert g_ida["codigo"].startswith("IDA") and g_ipv["codigo"].startswith("IPV")
por_id = {x["id"]: x for x in A("GET", "/articulos")}
assert por_id[g_ida["id"]]["desechable"] == 1 and not por_id[g_ida["id"]]["punto_venta"] and por_id[g_ipv["id"]]["punto_venta"] == 1
A("PUT", f"/articulos/{g_ida['id']}", {**base_art, "desechable": True, "punto_venta": False, "categoria_id": cat_pv}, 400)  # tampoco al editar
A("DELETE", f"/articulos/{g_ida['id']}"); A("DELETE", f"/articulos/{g_ipv['id']}")
in2 = art("INSUMO", "X", un)
assert codigo_de(in2) == "IN0002"  # IDA e IPV no cuentan para IN
c_ind = app.conectar()  # los códigos IND de bases anteriores pasan a IDA, una sola vez
c_ind.execute("UPDATE articulos SET codigo='IND0001' WHERE id=?", (vaso,))
c_ind.execute("DELETE FROM config WHERE clave='codigos_ida'")
app.sembrar(c_ind)
c_ind.close()
assert codigo_de(vaso) == "IDA0001"
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
# el inventario se valoriza al último precio de compra (1.200), no al costo promedio (1.100)
casi(next(x for x in A("GET", "/bodegas/stock?bodega=0") if x["articulo_id"] == harina)["costo"], 1200)
casi(A("GET", "/reportes/panel")["kpis"]["valor_central"], sum(x["cantidad"] * x["costo"] for x in A("GET", "/bodegas/stock?bodega=0")))
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
c_p = app.conectar(); casi(c_p.execute("SELECT costo_total FROM producciones WHERE id=?", (p1,)).fetchone()[0], 2 * 1200); c_p.close()  # al último precio
A("POST", "/produccion", {"articulo_id": torta, "cantidad": 2})
s = stock(); casi(s[base], 3); casi(s[torta], 2)
costo_receta = lambda: next(r for r in A("GET", "/recetas") if r["articulo_id"] == torta)["costo_unit"]
casi(costo_receta(), 300)  # 0,5 base × (1 kg harina al último precio, 1.200 / 2 bases)
# El costo de receta sigue el último precio del insumo: editado a mano o por compra
h_art = next(x for x in A("GET", "/articulos") if x["id"] == harina)
costo_prom = h_art["costo"]
editar_h = {k: h_art[k] for k in ("tipo", "desechable", "categoria_id", "unidad_id", "nombre", "stock_minimo")}
A("PUT", f"/articulos/{harina}", {**editar_h, "precio": 2000})
casi(costo_receta(), 500)
cp = A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1600}]})["id"]
casi(costo_receta(), 400)
assert next(x for x in A("GET", "/articulos") if x["id"] == harina)["precio"] == 1600
A("POST", f"/compras/{cp}/anular", {})
casi(costo_receta(), 300)  # al anular vuelve al precio de la compra anterior
A("PUT", f"/articulos/{harina}", {**editar_h, "precio": 1200})
c_h = app.conectar(); c_h.execute("UPDATE articulos SET costo=? WHERE id=?", (costo_prom, harina)); c_h.close()  # deja el costo promedio como estaba
imp = A("GET", "/produccion/impresion?desde=2000-01-01&hasta=2100-01-01")
o_base = next(o for o in imp["ordenes"] if o["id"] == p1)
assert o_base["nombre"] == "BAS" and [(i["nombre"], i["cantidad"]) for i in o_base["items"]] == [("HAR", 2)]
assert len(A("GET", "/produccion/impresion?desde=2000-01-01&hasta=2000-01-02")["ordenes"]) == 0
A("GET", "/produccion/impresion?desde=2026-02-01&hasta=2026-01-01", esperado=400)
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
cat_libre = A("POST", "/categorias", {"nombre": "Sin uso", "de_productos": "0"})["id"]; A("DELETE", f"/categorias/{cat_libre}")
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

# Toma por categorías: solo esas categorías, conviven si no repiten artículos, y se listan con su nombre
cats0 = {x["id"]: x for x in A("GET", "/inventarios/categorias?bodega_id=0")}
tf = A("POST", "/inventarios", {"bodega_id": 0, "fecha": "2026-03-02", "obs": "Inventario mensual"})["id"]
A("PUT", f"/inventarios/{tf}", {"fecha": "2026-03-05", "obs": "Cierre de mes", "items": [{"articulo_id": harina, "conteo": 1}]})
dt = A("GET", f"/inventarios/{tf}")
assert dt["fecha"] == "2026-03-05" and dt["obs"] == "Cierre de mes" and "punto_venta" in dt["items"][0]
assert next(i for i in dt["items"] if i["articulo_id"] == harina)["conteo"] == 1
A("DELETE", f"/inventarios/{tf}")
arts0 = A("GET", "/inventarios/articulos?bodega_id=0")
assert harina in {a["articulo_id"] for a in arts0} and all("categoria_id" in a and "cantidad" in a for a in arts0)
assert sum(x["articulos"] for x in cats0.values()) == len(arts0)
cat_h = next(a["categoria_id"] for a in A("GET", "/articulos") if a["id"] == harina)
assert cat_h in cats0 and cats0[cat_h]["articulos"] >= 1 and len(cats0) > 1, cats0
cat_v = next(k for k in cats0 if k != cat_h)
tk = A("POST", "/inventarios", {"bodega_id": 0, "categorias": [cat_h]})
det_k = A("GET", f"/inventarios/{tk['id']}")
assert {i["categoria_id"] for i in det_k["items"]} == {cat_h} and harina in {i["articulo_id"] for i in det_k["items"]}
assert det_k["categorias_nombres"] == [cats0[cat_h]["nombre"]]
A("POST", "/inventarios", {"bodega_id": 0, "categorias": [cat_h]}, 409)
A("POST", "/inventarios", {"bodega_id": 0}, 409)
tk2 = A("POST", "/inventarios", {"bodega_id": 0, "categorias": [cat_v]})["id"]
assert any(r["id"] == tk["id"] and r["categorias_nombres"] for r in A("GET", "/inventarios"))
A("POST", "/inventarios", {"bodega_id": 0, "categorias": ["x"]}, 400)
A("DELETE", f"/inventarios/{tk['id']}"); A("DELETE", f"/inventarios/{tk2}")

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
P("GET", "/compras", esperado=403); P("POST", "/usuarios", {}, 403); P("GET", "/reportes/rendimiento", esperado=403); P("GET", "/reportes/stock-tiendas", esperado=403)
P("GET", "/informes/inventario", esperado=403); P("GET", "/informes/compras?formato=xlsx", esperado=403)  # informes: requieren Reportes
P("GET", "/produccion"); P("GET", "/produccion/recetas")
T("GET", "/compras", esperado=403); T("GET", "/usuarios", esperado=403); T("POST", "/despachos", {}, 403)
T("GET", "/stock/central", esperado=403)
# Desechables: devolución de tienda a central y consumo en la central
ida = art("INSUMO", "IDA", un, precio=10, desechable=True)
assert codigo_de(ida).startswith("IDA")
A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "items": [{"articulo_id": ida, "cantidad": 20, "precio": 10}]})
gi = A("POST", "/despachos", {"tienda_id": tienda, "items": [{"articulo_id": ida, "cantidad": 8}]})["id"]
casi(stock()[ida], 12); casi(stock(tienda)[ida], 8)
dev_t = {"tipo": "DEVOLUCION_TIENDA", "tienda_id": tienda, "motivo": "Sobrante"}
for cli in (T, P):
    cli("POST", "/salidas-internas", {**dev_t, "items": [{"articulo_id": ida, "cantidad": 1}]}, 403)
P("GET", "/salidas-internas?tipo=DEVOLUCION_TIENDA", esperado=403)
T("GET", "/salidas-internas?tipo=CONSUMO_CENTRAL", esperado=403)
A("POST", "/salidas-internas", {**dev_t, "motivo": "", "items": [{"articulo_id": ida, "cantidad": 1}]}, 400)
A("POST", "/salidas-internas", {**dev_t, "tienda_id": 0, "items": [{"articulo_id": ida, "cantidad": 1}]}, 400)
A("POST", "/salidas-internas", {**dev_t, "tipo": "OTRO", "items": [{"articulo_id": ida, "cantidad": 1}]}, 400)
for no_vale in (torta, harina, cafe):
    A("POST", "/salidas-internas", {**dev_t, "items": [{"articulo_id": no_vale, "cantidad": 1}]}, 400)
A("POST", "/salidas-internas", {**dev_t, "items": [{"articulo_id": ida, "cantidad": 9}]}, 409)  # más de lo que tiene la tienda
casi(stock(tienda)[ida], 8); casi(stock()[ida], 12)
assert not A("GET", "/salidas-internas?tipo=DEVOLUCION_TIENDA")
di = A("POST", "/salidas-internas", {**dev_t, "fecha": "2026-05-05", "items": [{"articulo_id": ida, "cantidad": 3}]})["id"]
casi(stock(tienda)[ida], 5); casi(stock()[ida], 15)
det_di = A("GET", f"/salidas-internas/{di}")
assert det_di["origen"] == "T1" and det_di["items"][0]["cantidad"] == 3 and det_di["items"][0]["codigo"].startswith("IDA")
assert {x["tipo"] for x in A("GET", f"/movimientos?desde=2026-01-01&articulo_id={ida}&tipo=DEVOLUCION_TIENDA")} == {"DEVOLUCION_TIENDA"}
assert A("GET", f"/movimientos?desde=2026-01-01&articulo_id={ida}&tipo=RECEPCION_CENTRAL")[0]["obs"] == "Sobrante"
assert [x["id"] for x in T("GET", "/salidas-internas?tipo=DEVOLUCION_TIENDA&desde=2026-01-01")] == [di]  # la tienda ve la suya
T("POST", f"/salidas-internas/{di}/anular", {}, 403)
A("POST", "/salidas-internas", {"tipo": "CONSUMO_CENTRAL", "motivo": "Exceso", "items": [{"articulo_id": ida, "cantidad": 99}]}, 409)
ci = A("POST", "/salidas-internas", {"tipo": "CONSUMO_CENTRAL", "motivo": "Limpieza", "items": [{"articulo_id": ida, "cantidad": 15}]})["id"]
casi(stock()[ida], 0)
A("POST", f"/salidas-internas/{di}/anular", {}, 409)  # la central ya no tiene ese stock
casi(stock(tienda)[ida], 5)
A("POST", f"/salidas-internas/{ci}/anular", {})
casi(stock()[ida], 15)
A("POST", f"/salidas-internas/{ci}/anular", {}, 409)
A("POST", f"/salidas-internas/{di}/anular", {})
casi(stock(tienda)[ida], 8); casi(stock()[ida], 12)
A("DELETE", f"/articulos/{ida}", esperado=409)
assert {x["articulo_id"] for x in A("GET", f"/salidas-internas/stock?bodega={tienda}")} >= {ida, vaso}
assert torta not in {x["articulo_id"] for x in A("GET", f"/salidas-internas/stock?bodega={tienda}")}

# Compras: el tipo de documento (factura, boleta o guía) es obligatorio
s_doc = stock()[harina]
A("POST", "/compras", {"proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1}]}, 400)
A("POST", "/compras", {"tipo_documento": "NOTA", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1}]}, 400)
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

    proveedores, pagos, pago_modo = [], [], "ok"

    def do_POST(self):
        d, cls = self.leer(), FudoFalso
        if self.path == "/auth":
            if d.get("apiSecret") != "secreto-correcto":
                return self.responder(401, {"errors": [{"title": "Credenciales"}]})
            cls.tokens += 1
            return self.responder(200, {"token": "tok", "exp": 9999999999})
        if self.path == "/api/payments":
            if cls.pago_modo == "rechazo":
                return self.responder(422, {"errors": [{"detail": "Pago inválido"}]})
            cls.pagos.append(d)
            return self.responder(201, {"data": {"id": str(500 + len(cls.pagos)), "type": "Payment"}})
        if self.path == "/api/providers":
            cls.proveedores.append(d["data"]["attributes"]["name"])
            return self.responder(201, {"data": {"id": str(100 + len(cls.proveedores)), "type": "Provider"}})
        assert self.headers["Authorization"] == "Bearer tok" and self.path == "/api/expenses"
        if cls.modo == "rechazo":
            return self.responder(422, {"errors": [{"detail": "Categoría inválida"}]})
        cls.gastos.append(d)
        if cls.modo == "caida":
            return self.responder(500, {})
        self.responder(201, {"data": {"id": str(len(cls.gastos)), "type": "Expense"}})

    ingredientes = {}  # id -> {"name", "stock"}
    patch_modo = "ok"

    def ing_json(self, i):
        x = FudoFalso.ingredientes[i]
        return {"id": i, "type": "Ingredient", "attributes": {"name": x["name"], "stock": x["stock"], "stockControl": x["stock"] is not None},
                "relationships": {"unit": {"data": {"id": "1", "type": "Unit"}}}}

    def do_PATCH(self):
        d = self.leer()
        FudoFalso.ultimo_patch = (self.path, d)
        if self.path.startswith("/api/ingredients/"):
            FudoFalso.ingredientes[self.path.rsplit("/", 1)[1]]["stock"] = d["data"]["attributes"]["stock"]
            if FudoFalso.patch_modo == "caida":  # se aplicó, pero la respuesta no llega bien
                return self.responder(500, {})
        self.responder(200, {"data": {}})

    def do_GET(self):
        if self.path.startswith("/api/ingredients/"):
            return self.responder(200, {"data": self.ing_json(self.path.split("?")[0].rsplit("/", 1)[1])})
        if self.path.startswith("/api/ingredients"):
            return self.responder(200, {"data": [self.ing_json(i) for i in FudoFalso.ingredientes],
                                        "included": [{"id": "1", "type": "Unit", "attributes": {"name": "Unidad", "abbreviation": "un"}}]})
        if self.path.startswith("/api/payment-methods"):
            return self.responder(200, {"data": [{"id": "3", "attributes": {"name": "Tarjeta"}}, {"id": "5", "attributes": {"name": "Efectivo"}}]})
        if self.path.startswith("/api/providers"):
            return self.responder(200, {"data": [{"id": "7", "attributes": {"name": "Proveedor"}}] +
                                        [{"id": str(101 + i), "attributes": {"name": n}} for i, n in enumerate(FudoFalso.proveedores)]})
        self.responder(200, {"data": [{"id": "7", "attributes": {"name": "Categoría"}}]})


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

# Fudo: insumos equivalentes por tienda, stock de despachos y consumo por ventas
FudoFalso.ingredientes = {"11": {"name": "Vaso cartón", "stock": 50.0}, "12": {"name": "Sin control", "stock": None}}
ings = A("GET", f"/fudo/{tienda2}/ingredientes")
assert [(x["id"], x["unidad"], x["stock"]) for x in ings] == [("12", "un", None), ("11", "un", 50.0)]
A("POST", f"/fudo/{tienda2}/equivalencias", {"fudo_id": "11", "articulo_id": harina, "factor": 1}, 400)  # no se maneja en tiendas
A("POST", f"/fudo/{tienda2}/equivalencias", {"fudo_id": "11", "articulo_id": vaso, "factor": 0}, 400)
A("POST", f"/fudo/{tienda2}/equivalencias", {"fudo_id": "12", "articulo_id": vaso, "factor": 1}, 502)  # sin control de stock en Fudo
eq = A("POST", f"/fudo/{tienda2}/equivalencias", {"fudo_id": "11", "fudo_nombre": "Vaso cartón", "fudo_unidad": "un", "articulo_id": vaso, "factor": 1})
assert eq["base"] == 50
A("POST", f"/fudo/{tienda2}/equivalencias", {"fudo_id": "11", "articulo_id": torta, "factor": 1}, 409)
A("POST", f"/fudo/{tienda}/equivalencias", {"fudo_id": "11", "articulo_id": vaso, "factor": 1}, 400)  # tienda sin conexión
s_vaso = stock(tienda2).get(vaso, 0)
g2 = A("POST", "/despachos", {"tienda_id": tienda2, "fecha": __import__("datetime").date.today().isoformat(), "items": [{"articulo_id": vaso, "cantidad": 10}]})["id"]
fila_g2 = next(x for x in A("GET", "/despachos?desde=2026-01-01&hasta=2026-12-31") if x["id"] == g2)
assert fila_g2["fudo_stock_lineas"] == 1 and fila_g2["fudo_stock_estado"] == ""
assert A("GET", f"/fudo/{tienda2}/comparar")["guias_sin_enviar"] == 1
assert A("POST", f"/despachos/{g2}/fudo-stock", {})["ok"]
assert FudoFalso.ingredientes["11"]["stock"] == 60
A("POST", f"/despachos/{g2}/fudo-stock", {}, 409)  # no se suma dos veces
FudoFalso.ingredientes["11"]["stock"] = 54.0  # Fudo vendió 6 con sus recetas
cmp_f = A("GET", f"/fudo/{tienda2}/comparar")
fila = cmp_f["filas"][0]
assert cmp_f["guias_sin_enviar"] == 0
casi(fila["consumo_pendiente"], 6); casi(fila["stock_sistema"], s_vaso + 10)
sinc = A("POST", f"/fudo/{tienda2}/sincronizar", {"fecha": "2026-11-06"})
casi(sinc["detalle"][0]["descontado"], 6)
casi(stock(tienda2)[vaso], s_vaso + 4)
assert any(m["tipo"] == "VENTA_FUDO" for m in A("GET", f"/movimientos?desde=2026-11-06&hasta=2026-11-06&bodega={tienda2}"))
casi(A("GET", f"/fudo/{tienda2}/comparar")["filas"][0]["consumo_pendiente"], 0)
casi(A("POST", f"/fudo/{tienda2}/sincronizar", {})["detalle"][0]["descontado"], 0)  # sin ventas nuevas
FudoFalso.ingredientes["11"]["stock"] = 44.0 - s_vaso  # Fudo consumió más de lo que tiene el sistema
s2 = A("POST", f"/fudo/{tienda2}/sincronizar", {"fecha": "2026-11-06"})
casi(s2["detalle"][0]["descontado"], s_vaso + 4); casi(s2["detalle"][0]["faltante"], 6)
casi(stock(tienda2)[vaso], 0)
assert [x["id"] for x in A("GET", f"/fudo/{tienda2}/sincronizaciones")][:2] == [s2["id"], sinc["id"] + 1]
A("POST", f"/fudo/sincronizaciones/{s2['id']}/anular", {})
casi(stock(tienda2)[vaso], s_vaso + 4)
casi(A("GET", f"/fudo/{tienda2}/comparar")["filas"][0]["consumo_pendiente"], 0)  # lo anulado no se vuelve a contar
assert A("POST", f"/fudo/{tienda2}/igualar", {})["ok"]
casi(FudoFalso.ingredientes["11"]["stock"], s_vaso + 4)
casi(A("GET", f"/fudo/{tienda2}/comparar")["filas"][0]["diferencia"], 0)
# Respuesta incierta al sumar stock: queda por revisar, bloquea la sincronización y no se repite sin confirmación
g3 = A("POST", "/despachos", {"tienda_id": tienda2, "fecha": "2026-11-06", "items": [{"articulo_id": vaso, "cantidad": 5}]})["id"]
FudoFalso.patch_modo = "caida"
r3 = A("POST", f"/despachos/{g3}/fudo-stock", {})
assert not r3["ok"] and r3["estado"] == "REVISAR"
FudoFalso.patch_modo = "ok"
A("POST", f"/fudo/{tienda2}/sincronizar", {}, 409)
A("POST", f"/despachos/{g3}/fudo-stock", {}, 409)
FudoFalso.ingredientes["11"]["stock"] -= 5  # revisado en Fudo: se deshace a mano y se confirma el reenvío
assert A("POST", f"/despachos/{g3}/fudo-stock", {"confirmar_reenvio": True})["estado"] == "ENVIADO"
casi(FudoFalso.ingredientes["11"]["stock"], s_vaso + 9)
A("POST", f"/despachos/{g3}/fudo-stock/revertir", {}, 409)  # la guía sigue vigente
A("POST", f"/despachos/{g3}/anular", {})
assert A("POST", f"/despachos/{g3}/fudo-stock/revertir", {})["estado"] == "REVERTIDO"
casi(FudoFalso.ingredientes["11"]["stock"], s_vaso + 4)
casi(A("GET", f"/fudo/{tienda2}/comparar")["filas"][0]["consumo_pendiente"], 0)
A("POST", f"/despachos/{g3}/fudo-stock/revertir", {}, 409)
# Ajustar el sistema al stock de Fudo: toma de inventario cerrada, y Fudo queda como nuevo punto de partida
FudoFalso.ingredientes["11"]["stock"] = 37.0
aj = A("POST", f"/fudo/{tienda2}/ajustar-sistema", {"fecha": "2026-11-06"})
casi(stock(tienda2)[vaso], 37); casi(aj["ajustes"][0]["diferencia"], 37 - (s_vaso + 4))
inv_aj = A("GET", f"/inventarios/{aj['inventario_id']}")
assert inv_aj["estado"] == "CERRADO" and "Fudo" in inv_aj["obs"]
casi(A("GET", f"/fudo/{tienda2}/comparar")["filas"][0]["consumo_pendiente"], 0)
casi(A("GET", f"/fudo/{tienda2}/comparar")["filas"][0]["diferencia"], 0)
abierto = A("POST", "/inventarios", {"bodega_id": tienda2})["id"]
A("POST", f"/fudo/{tienda2}/ajustar-sistema", {}, 409)
A("DELETE", f"/inventarios/{abierto}")
# Gasto en Fudo: proveedor Nata & Schlott (se crea una sola vez), insumos equivalentes en la descripción y stock sumado
FudoFalso.gastos, FudoFalso.proveedores = [], []
g4 = A("POST", "/despachos", {"tienda_id": tienda2, "fecha": "2026-11-06", "items": [{"articulo_id": vaso, "cantidad": 3}]})["id"]
r4 = A("POST", f"/despachos/{g4}/fudo", {})
assert r4["ok"] and r4["stock"] == "ENVIADO", r4
assert FudoFalso.proveedores == ["Nata & Schlott"]
gasto4 = FudoFalso.gastos[-1]["data"]
assert gasto4["relationships"]["provider"]["data"]["id"] == "101"
import re as _re
assert _re.fullmatch(r"\d{2}-\d{2}-\d{4} \d{2}:\d{2} · Guía N° " + f"{g4:06d}", gasto4["attributes"]["description"]), gasto4["attributes"]["description"]
assert gasto4["relationships"]["paymentMethod"]["data"] == {"id": "5", "type": "PaymentMethod"}
assert gasto4["attributes"]["paymentDate"] == gasto4["attributes"]["date"] == "2026-11-06"
assert gasto4["attributes"]["amount"] == round(A("GET", f"/despachos/{g4}")["total"])
assert r4["pago"] == "PAGADO"
pago4 = FudoFalso.pagos[-1]["data"]
assert pago4["attributes"] == {"amount": gasto4["attributes"]["amount"], "paidAt": "2026-11-06"}
assert pago4["relationships"]["expense"]["data"]["id"] == str(len(FudoFalso.gastos)) and pago4["relationships"]["paymentMethod"]["data"]["id"] == "5"
A("POST", f"/despachos/{g4}/fudo/pago", {}, 409)  # ya pagado
det4 = A("GET", f"/despachos/{g4}")
assert det4["fudo_lista"] is True and det4["fudo_stock_estado"] == "ENVIADO" and det4["fudo_stock_lineas"] == 1
casi(FudoFalso.ingredientes["11"]["stock"], 40)
assert next(x for x in A("GET", "/fudo") if x["tienda_id"] == tienda2)["proveedor"] == "Nata & Schlott"
A("POST", f"/despachos/{g4}/anular", {})
r4b = A("POST", f"/despachos/{g4}/fudo/anular", {})
assert r4b["ok"] and r4b["stock"] == "REVERTIDO"
casi(FudoFalso.ingredientes["11"]["stock"], 37)
g6 = A("POST", "/despachos", {"tienda_id": tienda2, "fecha": "2026-11-06", "items": [{"articulo_id": vaso, "cantidad": 1}]})["id"]
FudoFalso.pago_modo = "rechazo"  # el gasto se crea igual; el pago queda pendiente y se reintenta
r6 = A("POST", f"/despachos/{g6}/fudo", {})
assert r6["ok"] and FudoFalso.proveedores == ["Nata & Schlott"] and r6["pago"] == "" and "Pago inválido" in r6["pago_error"]  # reutiliza el proveedor
assert A("GET", f"/despachos/{g6}")["fudo_pago"] == ""
FudoFalso.pago_modo = "ok"
assert A("POST", f"/despachos/{g6}/fudo/pago", {})["pago"] == "PAGADO"
assert A("GET", f"/despachos/{g6}")["fudo_pago"].isdigit()
casi(FudoFalso.ingredientes["11"]["stock"], 38)
# Modo manual: el sistema crea el gasto pero no toca el stock de Fudo; cuenta lo esperado para el consumo por ventas
A("PUT", f"/fudo/{tienda2}/gastos", {"categoria_id": "7", "categoria": "Categoría", "monto": "TOTAL", "stock_modo": "OTRO"}, 400)
A("PUT", f"/fudo/{tienda2}/gastos", {"categoria_id": "7", "categoria": "Categoría", "monto": "TOTAL", "stock_modo": "MANUAL"})
assert next(x for x in A("GET", "/fudo") if x["tienda_id"] == tienda2)["stock_modo"] == "MANUAL"
antes_m = FudoFalso.ingredientes["11"]["stock"]
g7 = A("POST", "/despachos", {"tienda_id": tienda2, "fecha": "2026-11-06", "items": [{"articulo_id": vaso, "cantidad": 4}]})["id"]
r7 = A("POST", f"/despachos/{g7}/fudo", {})
assert r7["ok"] and r7["manual"] is True and r7["stock"] == "ENVIADO"
casi(FudoFalso.ingredientes["11"]["stock"], antes_m)  # Fudo no se tocó
fila7 = next(x for x in A("GET", "/despachos?desde=2026-01-01&hasta=2026-12-31") if x["id"] == g7)
assert fila7["fudo_stock_manual"] == 1 and fila7["fudo_stock_estado"] == "ENVIADO"
FudoFalso.ingredientes["11"]["stock"] = antes_m + 4 - 1  # la tienda cargó el detalle (+4) y vendió 1
casi(A("GET", f"/fudo/{tienda2}/comparar")["filas"][0]["consumo_pendiente"], 1)
A("POST", f"/despachos/{g7}/anular", {})
r7b = A("POST", f"/despachos/{g7}/fudo/anular", {})
assert r7b["ok"] and r7b["stock"] == "REVERTIDO"
casi(FudoFalso.ingredientes["11"]["stock"], antes_m + 3)  # Fudo descuenta por su cuenta al anular el gasto
FudoFalso.ingredientes["11"]["stock"] = antes_m - 1
casi(A("GET", f"/fudo/{tienda2}/comparar")["filas"][0]["consumo_pendiente"], 1)
A("PUT", f"/fudo/{tienda2}/gastos", {"categoria_id": "7", "categoria": "Categoría", "monto": "TOTAL", "stock_modo": "SISTEMA"})
A("DELETE", f"/articulos/{vaso}", esperado=409)  # tiene equivalencia
eq_id = A("GET", f"/fudo/{tienda2}/equivalencias")[0]["id"]
A("PUT", f"/fudo/equivalencias/{eq_id}", {"articulo_id": vaso, "factor": 2})
assert A("GET", f"/fudo/{tienda2}/equivalencias")[0]["factor"] == 2
A("DELETE", f"/fudo/equivalencias/{eq_id}")
assert A("GET", f"/fudo/{tienda2}/equivalencias") == []
# Importar desde Fudo: sugerencias por nombre, asociar existentes o crear artículos nuevos, todo o nada
FudoFalso.ingredientes.update({"13": {"name": "IN TOR", "stock": 7.0}, "14": {"name": "Leche entera", "stock": 12.0}})
imp = {x["id"]: x for x in A("GET", f"/fudo/{tienda2}/importar")}
assert imp["13"]["sugerido_id"] == torta and imp["13"]["unidad_id"] == un and imp["14"]["sugerido_id"] is None
assert imp["12"]["stock"] is None and imp["11"]["equivalencia"] is None
n_art = len(A("GET", "/articulos"))
nuevo_ok = {"grupo": "PUNTO_VENTA", "categoria_id": cat_pv, "unidad_id": un, "nombre": "Leche entera"}
A("POST", f"/fudo/{tienda2}/importar", {"items": [{"fudo_id": "14", "factor": 1, "nuevo": nuevo_ok},
                                                    {"fudo_id": "13", "articulo_id": harina, "factor": 1}]}, 400)  # harina no es de tienda
assert len(A("GET", "/articulos")) == n_art and A("GET", f"/fudo/{tienda2}/equivalencias") == []  # todo o nada
A("POST", f"/fudo/{tienda2}/importar", {"items": [{"fudo_id": "14", "factor": 1, "nuevo": {**nuevo_ok, "categoria_id": cid}}]}, 400)  # categoría de otro grupo
A("POST", f"/fudo/{tienda2}/importar", {"items": [{"fudo_id": "12", "articulo_id": vaso, "factor": 1}]}, 400)  # sin control de stock
ri_ = A("POST", f"/fudo/{tienda2}/importar", {"items": [{"fudo_id": "14", "factor": 1, "nuevo": nuevo_ok}, {"fudo_id": "13", "articulo_id": torta, "factor": 1}]})
assert ri_["equivalencias"] == 2 and ri_["creados"][0]["codigo"].startswith("IPV")
eqs_i = {e["fudo_id"]: e for e in A("GET", f"/fudo/{tienda2}/equivalencias")}
assert eqs_i["14"]["nombre"] == "Leche entera" and eqs_i["14"]["base"] == 12 and eqs_i["13"]["articulo_id"] == torta
A("POST", f"/fudo/{tienda2}/importar", {"items": [{"fudo_id": "13", "articulo_id": torta, "factor": 1}]}, 409)  # ya importado
for e in eqs_i.values():
    A("DELETE", f"/fudo/equivalencias/{e['id']}")
A("DELETE", f"/articulos/{ri_['creados'][0]['id']}")
for cli in (T,):
    cli("GET", f"/fudo/{tienda2}/comparar", esperado=403)
# Cuenta Fudo compartida: no se puede conectar otra tienda con la misma API Key, y si ya ocurrió se bloquea operar stock
A("PUT", f"/fudo/{tienda}/credenciales", {"api_key": "clave-1234", "api_secret": "secreto-correcto"}, 409)
c = app.conectar()
c.execute("INSERT INTO fudo_tiendas(tienda_id,api_key,api_secret,categoria_id) VALUES(?,?,?,?)", (tienda, "clave-1234", "secreto-correcto", "7"))
c.close()
assert next(x for x in A("GET", "/fudo") if x["tienda_id"] == tienda2)["comparte_con"] == "T1"
assert A("GET", f"/fudo/{tienda2}/comparar")["comparte_con"] == ["T1"]
FudoFalso.ingredientes["11"]["stock"] = 5.0
A("POST", f"/fudo/{tienda2}/equivalencias", {"fudo_id": "11", "articulo_id": vaso, "factor": 1}, 409)
A("POST", f"/fudo/{tienda2}/sincronizar", {}, 409)
A("POST", f"/fudo/{tienda2}/igualar", {}, 409)
g8 = A("POST", "/despachos", {"tienda_id": tienda2, "fecha": "2026-11-07", "items": [{"articulo_id": vaso, "cantidad": 1}]})["id"]
assert "misma cuenta Fudo" in A("POST", f"/despachos/{g8}/fudo", {}, 409)["error"]
c = app.conectar(); c.execute("DELETE FROM fudo_tiendas WHERE tienda_id=?", (tienda,)); c.close()
# Cambiar a otra cuenta: las equivalencias y la categoría de la cuenta anterior se reinician, con confirmación
A("POST", f"/fudo/{tienda2}/equivalencias", {"fudo_id": "11", "articulo_id": vaso, "factor": 1})
A("PUT", f"/fudo/{tienda2}/credenciales", {"api_key": "otra-cuenta-99"}, 409)
A("PUT", f"/fudo/{tienda2}/credenciales", {"api_secret": "secreto-correcto"})  # misma cuenta: no se reinicia nada
assert len(A("GET", f"/fudo/{tienda2}/equivalencias")) == 1
A("PUT", f"/fudo/{tienda2}/credenciales", {"api_key": "otra-cuenta-99", "reiniciar_equivalencias": True})
assert A("GET", f"/fudo/{tienda2}/equivalencias") == []
assert next(x for x in A("GET", "/fudo") if x["tienda_id"] == tienda2)["categoria_id"] == ""
A("POST", f"/despachos/{g8}/anular", {})

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
assert {x["articulo_id"] for x in T("GET", "/bodegas/stock") if x["cantidad"] > 0} == {torta, vaso, ida}
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

# Conexión con el POS: clave, idempotencia, todo o nada y anulación
def P(metodo, ruta, cuerpo=None, esperado=200, token=None):
    cx = http.client.HTTPConnection("127.0.0.1", PUERTO)
    h = {"Content-Type": "application/json"} if cuerpo is not None else {}
    if token is not None:
        h["X-POS-Token"] = token
    cx.request(metodo, "/api" + ruta, json.dumps(cuerpo) if cuerpo is not None else None, h)
    r = cx.getresponse()
    txt = r.read().decode()
    assert r.status == esperado, f"POS {metodo} {ruta}: {r.status} {txt[:300]} (esperado {esperado})"
    return json.loads(txt)


P("GET", "/pos/ping", token="x", esperado=503)  # sin clave configurada
assert A("GET", "/config/pos")["configurado"] is False
clave = A("POST", "/config/pos/token", {})["token"]
assert A("GET", "/config/pos")["configurado"] is True
c = app.conectar()
assert clave not in str(c.execute("SELECT valor FROM config WHERE clave='pos_token_hash'").fetchone())  # solo la huella
c.close()
P("GET", "/pos/ping", esperado=401)
P("GET", "/pos/ping", token="mala", esperado=401)
assert P("GET", "/pos/ping", token=clave)["ok"] is True
assert tienda in [t["id"] for t in P("GET", "/pos/tiendas", token=clave)]
arts_pos = {x["id"]: x for x in P("GET", "/pos/articulos", token=clave)}
assert vaso in arts_pos and harina not in arts_pos
assert all(isinstance(x["costo"], (int, float)) and x["costo"] >= 0 for x in arts_pos.values())  # costo para el CMV del POS
st = stock(tienda)
con_stock = next(aid for aid, q in st.items() if q >= 2 and aid in arts_pos)
otro = next((aid for aid in arts_pos if aid != con_stock), None)
venta = {"referencia": "POS-test-1", "tienda_id": tienda, "fecha": "2026-11-04", "detalle": "Venta POS N° 1",
         "items": [{"articulo_id": con_stock, "cantidad": 0.5}, {"articulo_id": con_stock, "cantidad": 0.5}]}
r1 = P("POST", "/pos/consumos", venta, token=clave)
casi(stock(tienda)[con_stock], st[con_stock] - 1)
assert P("POST", "/pos/consumos", venta, token=clave)["id"] == r1["id"]  # repetido: no descuenta de nuevo
casi(stock(tienda)[con_stock], st[con_stock] - 1)
# Stock insuficiente: la venta ya se cobró, se descuenta igual y queda negativo; al anularla vuelve todo
falta = con_stock if otro is None else otro
st_falta = stock(tienda).get(falta, 0)
P("POST", "/pos/consumos", {**venta, "referencia": "POS-test-2", "items": [{"articulo_id": con_stock, "cantidad": 0.5}, {"articulo_id": falta, "cantidad": 99999}]}, token=clave)
assert stock(tienda)[falta] < 0
P("POST", "/pos/consumos/anular", {"referencia": "POS-test-2"}, token=clave)
casi(stock(tienda)[con_stock], st[con_stock] - 1)
casi(stock(tienda).get(falta, 0), st_falta)
# Los demás movimientos siguen sin poder dejar el stock negativo (ej. una salida manual de la tienda)
_c = app.conectar()
try:
    app.mover(_c, falta, tienda, -99999, "MERMA", None, "2026-11-04")
    raise AssertionError("mover sin negativo=True debió rechazar el stock negativo")
except app.ApiError:
    pass
finally:
    _c.rollback()
    _c.close()
P("POST", "/pos/consumos", {**venta, "referencia": "POS-test-3", "tienda_id": 999999}, token=clave, esperado=404)
P("POST", "/pos/consumos", {**venta, "referencia": "POS-test-3", "items": [{"articulo_id": 999999, "cantidad": 1}]}, token=clave, esperado=404)
P("POST", "/pos/consumos", {**venta, "referencia": "POS-test-3", "items": [{"articulo_id": con_stock, "cantidad": 0}]}, token=clave, esperado=400)
P("POST", "/pos/consumos", {**venta, "referencia": "con espacios"}, token=clave, esperado=400)
P("POST", "/pos/consumos", {**venta, "referencia": "POS-test-3"}, token="mala", esperado=401)
P("POST", "/pos/consumos/anular", {"referencia": "POS-test-1"}, token=clave)
casi(stock(tienda)[con_stock], st[con_stock])
P("POST", "/pos/consumos/anular", {"referencia": "POS-test-1"}, token=clave)  # ya anulado: 200 sin devolver dos veces
casi(stock(tienda)[con_stock], st[con_stock])
assert A("GET", "/config/pos")["consumos"] == 2  # POS-test-1 y POS-test-2 (con stock negativo)
# Cambio de producto en el POS: lo devuelto entra (ENTRADA_CAMBIO) y lo nuevo sale (SALIDA_CAMBIO); se revierte como un consumo
s_c = stock(tienda)
cambio = {"referencia": "POS-test-3-C1", "tienda_id": tienda, "fecha": "2026-11-04", "detalle": "Cambio en venta POS N° 3",
          "entradas": [{"articulo_id": con_stock, "cantidad": 1}], "salidas": [{"articulo_id": otro, "cantidad": 2}]}
P("POST", "/pos/cambios", {**cambio, "entradas": [], "salidas": []}, token=clave, esperado=400)
P("POST", "/pos/cambios", cambio, token=clave)
P("POST", "/pos/cambios", cambio, token=clave)  # repetido: no mueve dos veces
casi(stock(tienda)[con_stock], s_c[con_stock] + 1); casi(stock(tienda).get(otro, 0), s_c.get(otro, 0) - 2)
tipos_c = {(m["tipo"], m["articulo_id"]): m["cantidad"] for m in P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=2026-01-01&hasta=2100-01-01", token=clave)
           if m["referencia"] == "POS POS-test-3-C1"}
assert tipos_c == {("ENTRADA_CAMBIO", con_stock): 1, ("SALIDA_CAMBIO", otro): -2}, tipos_c
P("POST", "/pos/consumos/anular", {"referencia": "POS-test-3-C1"}, token=clave)  # si se anula la venta, el cambio se revierte
casi(stock(tienda)[con_stock], s_c[con_stock]); casi(stock(tienda).get(otro, 0), s_c.get(otro, 0))
# Revertir un cambio aunque la tienda ya haya quedado en negativo (ej. vendió lo que entró por el cambio): no se bloquea
P("POST", "/pos/cambios", {**cambio, "referencia": "POS-test-4-C1"}, token=clave)
gasto = s_c[con_stock] + 1 + 5  # vende todo lo que hay y 5 más: queda en -5
P("POST", "/pos/consumos", {**venta, "referencia": "POS-test-5", "items": [{"articulo_id": con_stock, "cantidad": gasto}]}, token=clave)
casi(stock(tienda)[con_stock], -5)
P("POST", "/pos/consumos/anular", {"referencia": "POS-test-4-C1"}, token=clave)  # quita la entrada del cambio: queda en -6
casi(stock(tienda)[con_stock], -6)
P("POST", "/pos/consumos/anular", {"referencia": "POS-test-5"}, token=clave)
casi(stock(tienda)[con_stock], s_c[con_stock]); casi(stock(tienda).get(otro, 0), s_c.get(otro, 0))
# Fecha y hora de la tienda: los movimientos quedan con la hora en que ocurrió la venta / el cambio / la anulación
# (fecha_hora del POS), no con la hora en que llegó al sistema (ej. una venta hecha sin internet que se envía después)
assert app.fecha_hora_valida("2026-11-03T21:15") == "2026-11-03 21:15:00" and app.fecha_hora_valida("mañana") is None
P("POST", "/pos/consumos", {**venta, "referencia": "POS-hora-1", "fecha": "2026-11-04", "fecha_hora": "2026-11-03 21:15:07",
                            "items": [{"articulo_id": con_stock, "cantidad": 1}]}, token=clave)
P("POST", "/pos/cambios", {**cambio, "referencia": "POS-hora-1-C1", "fecha_hora": "2026-11-03 21:40:00"}, token=clave)
P("POST", "/pos/consumos/anular", {"referencia": "POS-hora-1-C1", "fecha_hora": "2026-11-03 22:05:30"}, token=clave)
P("POST", "/pos/consumos/anular", {"referencia": "POS-hora-1", "fecha_hora": "2026-11-03 22:06:00"}, token=clave)
horas = {(m["referencia"], m["tipo"]): m["fecha"] for m in P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=2026-11-03&hasta=2026-11-03", token=clave)}
assert horas[("POS POS-hora-1", "VENTA")] == "2026-11-03 21:15:07", horas
assert horas[("POS POS-hora-1-C1", "ENTRADA_CAMBIO")] == "2026-11-03 21:40:00", horas
assert horas[("Anula POS POS-hora-1-C1", "ANULACION")] == "2026-11-03 22:05:30", horas
assert horas[("Anula POS POS-hora-1", "ANULACION")] == "2026-11-03 22:06:00", horas
casi(stock(tienda)[con_stock], s_c[con_stock])

# Borrar ventas del POS (mantención): se eliminan sus movimientos y el stock vuelve a como estaba antes de esas ventas
s_b = stock(tienda)
P("POST", "/pos/consumos", {**venta, "referencia": "POS-del-1", "items": [{"articulo_id": con_stock, "cantidad": 2}]}, token=clave)
P("POST", "/pos/cambios", {**cambio, "referencia": "POS-del-1-C1"}, token=clave)
P("POST", "/pos/consumos/anular", {"referencia": "POS-del-1-C1"}, token=clave)
P("POST", "/pos/cambios", {**cambio, "referencia": "POS-del-1-C2"}, token=clave)
casi(stock(tienda)[con_stock], s_b[con_stock] - 2 + 1)
r_b = P("POST", "/pos/ventas/borrar", {"referencias": ["POS-del-1", "POS-del-1-C1", "POS-del-1-C2", "POS-no-existe"]}, token=clave)
assert r_b["documentos"] == 3 and r_b["movimientos"] == 1 + 4 + 2, r_b
casi(stock(tienda)[con_stock], s_b[con_stock]); casi(stock(tienda).get(otro, 0), s_b.get(otro, 0))
movs_b = P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=2000-01-01&hasta=2100-01-01", token=clave)
assert not [m for m in movs_b if "POS-del-1" in (m["referencia"] or "")]
ult = next(m for m in movs_b if m["articulo_id"] == con_stock)  # el más reciente: su saldo cuadra con el stock
casi(ult["saldo"], s_b[con_stock])
assert P("POST", "/pos/ventas/borrar", {"referencias": ["POS-del-1"]}, token=clave)["documentos"] == 0  # repetir no hace nada
P("POST", "/pos/ventas/borrar", {"referencias": ["POS-del-1"]}, token="mala", esperado=401)
# Stock de tienda y toma de inventario desde el POS
st_pos = {x["articulo_id"]: x for x in P("GET", f"/pos/stock?tienda_id={tienda}", token=clave)}
assert set(st_pos) == set(arts_pos)  # todos los de tienda, con 0 si no hay fila
casi(st_pos[con_stock]["cantidad"], st[con_stock])
c_cat = app.conectar()
cats_sis = {r[0]: r[1] for r in c_cat.execute("SELECT a.id, c.nombre FROM articulos a JOIN categorias c ON c.id=a.categoria_id")}
c_cat.close()
assert all(x["categoria"] == cats_sis[aid] for aid, x in st_pos.items())  # el POS filtra el stock por categoría
# Despachos que la tienda recibe en el POS: la central descuenta al despachar, la tienda suma al recibir y lo que falta vuelve a la central
c_rp = app.conectar(); c_rp.execute("UPDATE tiendas SET recibe_pos=1 WHERE id=?", (tienda,)); c_rp.commit(); c_rp.close()
c0, t0 = stock().get(vaso, 0), stock(tienda).get(vaso, 0)
gr = A("POST", "/despachos", {"tienda_id": tienda, "items": [{"articulo_id": vaso, "cantidad": 4}]})["id"]
casi(stock()[vaso], c0 - 4); casi(stock(tienda).get(vaso, 0), t0)  # en camino: todavía no está en la tienda
assert A("GET", f"/despachos/{gr}")["recepcion"] == "EN_CAMINO"
lista_rp = P("GET", f"/pos/despachos?tienda_id={tienda}", token=clave)
assert lista_rp["recibe_pos"] and gr in [x["id"] for x in lista_rp["guias"] if x["recepcion"] == "EN_CAMINO"]
assert [i["cantidad"] for x in lista_rp["guias"] if x["id"] == gr for i in x["items"]] == [4]
rec = {"referencia": "POSREC-1", "tienda_id": tienda, "despacho_id": gr, "responsable": "Ana", "obs": "una caja abierta",
       "items": [{"articulo_id": vaso, "recibido": 3}]}
P("POST", "/pos/despachos/recibir", {**rec, "items": [{"articulo_id": vaso, "recibido": 5}]}, token=clave, esperado=400)  # más de lo despachado
P("POST", "/pos/despachos/recibir", rec, token=clave)
P("POST", "/pos/despachos/recibir", rec, token=clave)  # repetido (reintento del POS): no suma dos veces
casi(stock(tienda)[vaso], t0 + 3); casi(stock()[vaso], c0 - 3)  # lo que no llegó volvió a la central
P("POST", "/pos/despachos/recibir", {**rec, "referencia": "POSREC-2"}, token=clave, esperado=409)  # ya recibida
g_r = A("GET", f"/despachos/{gr}")
assert g_r["recepcion"] == "RECIBIDA" and g_r["items"][0]["recibido"] == 3 and g_r["recibido_por"] == "Ana"
assert [x["faltantes"] for x in A("GET", "/despachos?desde=2000-01-01") if x["id"] == gr] == [1]
A("POST", f"/despachos/{gr}/anular", {}); casi(stock(tienda).get(vaso, 0), t0); casi(stock()[vaso], c0)  # anularla deja todo como antes
c_rp = app.conectar(); c_rp.execute("UPDATE tiendas SET recibe_pos=0 WHERE id=?", (tienda,)); c_rp.commit(); c_rp.close()
P("GET", "/pos/stock?tienda_id=999999", token=clave, esperado=404)
P("GET", f"/pos/stock?tienda_id={tienda}", token="mala", esperado=401)
sin_fila = next((aid for aid in arts_pos if aid not in st), None)
toma = {"referencia": "POSINV-test-1", "tienda_id": tienda, "fecha": "2026-11-04", "responsable": "María", "obs": "Cierre",
        "items": [{"articulo_id": con_stock, "conteo": st[con_stock] - 0.5}] + ([{"articulo_id": sin_fila, "conteo": 3}] if sin_fila else [])}
P("POST", "/pos/inventarios", {**toma, "items": toma["items"] * 2}, token=clave, esperado=400)  # repetido
P("POST", "/pos/inventarios", {**toma, "items": [{"articulo_id": harina, "conteo": 1}]}, token=clave, esperado=404)  # no es de tienda
P("POST", "/pos/inventarios", {**toma, "items": [{"articulo_id": con_stock, "conteo": -1}]}, token=clave, esperado=400)
casi(stock(tienda)[con_stock], st[con_stock])  # nada se ajustó
inv_abierto = A("POST", "/inventarios", {"bodega_id": tienda})["id"]
P("POST", "/pos/inventarios", toma, token=clave, esperado=409)
A("DELETE", f"/inventarios/{inv_abierto}")
ri = P("POST", "/pos/inventarios", toma, token=clave)
aj = {x["articulo_id"]: x for x in ri["ajustes"]}
casi(aj[con_stock]["diferencia"], -0.5); casi(aj[con_stock]["stock_sistema"], st[con_stock])
casi(stock(tienda)[con_stock], st[con_stock] - 0.5)
if sin_fila:
    casi(stock(tienda)[sin_fila], 3)
ri2 = P("POST", "/pos/inventarios", toma, token=clave)
assert ri2["repetido"] is True and ri2["id"] == ri["id"]
casi(stock(tienda)[con_stock], st[con_stock] - 0.5)  # repetido: no ajusta de nuevo
inv = A("GET", f"/inventarios/{ri['id']}")
assert inv["estado"] == "CERRADO" and "María" in inv["obs"]
# Transferencias entre tiendas desde el POS
s1, s2 = stock(tienda), stock(tienda2)
base1, base2 = s1.get(con_stock, 0), s2.get(con_stock, 0)
trf = {"referencia": "POSTRF-test-1-S", "tipo": "SALIDA", "tienda_id": tienda, "contraparte_id": tienda2, "fecha": "2026-11-05",
       "detalle": "Transferencia POS N° 1", "items": [{"articulo_id": con_stock, "cantidad": 0.25}]}
P("POST", "/pos/transferencias", {**trf, "tipo": "OTRO"}, token=clave, esperado=400)
P("POST", "/pos/transferencias", {**trf, "contraparte_id": tienda}, token=clave, esperado=400)
P("POST", "/pos/transferencias", {**trf, "items": trf["items"] * 2}, token=clave, esperado=400)
P("POST", "/pos/transferencias", {**trf, "items": [{"articulo_id": harina, "cantidad": 1}]}, token=clave, esperado=404)
P("POST", "/pos/transferencias", {**trf, "items": [{"articulo_id": con_stock, "cantidad": 99999}]}, token=clave, esperado=409)
P("POST", "/pos/transferencias", trf, token="mala", esperado=401)
casi(stock(tienda)[con_stock], base1)
rt = P("POST", "/pos/transferencias", trf, token=clave)
casi(stock(tienda)[con_stock], base1 - 0.25)
assert P("POST", "/pos/transferencias", trf, token=clave) == {"ok": True, "id": rt["id"], "repetido": True}
casi(stock(tienda)[con_stock], base1 - 0.25)
P("POST", "/pos/transferencias", {**trf, "referencia": "POSTRF-test-1-E", "tipo": "ENTRADA", "tienda_id": tienda2, "contraparte_id": tienda,
                                  "items": [{"articulo_id": con_stock, "cantidad": 0.2}]}, token=clave)
casi(stock(tienda2)[con_stock], base2 + 0.2)  # llegó menos: el faltante no entra
P("POST", "/pos/transferencias", {**trf, "referencia": "POSTRF-hora-S", "fecha_hora": "2026-11-06 08:05:09"}, token=clave)
P("POST", "/pos/transferencias/anular", {"referencia": "POSTRF-hora-S", "fecha_hora": "2026-11-06 08:30:00"}, token=clave)
horas_t = {m["tipo"]: m["fecha"] for m in P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=2026-11-06&hasta=2026-11-06", token=clave)}
assert horas_t == {"TRANSFERENCIA_SALIDA": "2026-11-06 08:05:09", "ANULACION": "2026-11-06 08:30:00"}, horas_t
movs = A("GET", f"/movimientos?desde=2026-11-05&hasta=2026-11-05&bodega={tienda2}")
assert any(m["tipo"] == "TRANSFERENCIA_ENTRADA" for m in (movs if isinstance(movs, list) else movs.get("filas", [])))
P("POST", "/pos/transferencias/anular", {"referencia": "POSTRF-test-2-S"}, token=clave, esperado=404)
P("POST", "/pos/transferencias/anular", {"referencia": "POSTRF-test-1-S"}, token=clave)
casi(stock(tienda)[con_stock], base1)
P("POST", "/pos/transferencias/anular", {"referencia": "POSTRF-test-1-S"}, token=clave)  # idempotente
casi(stock(tienda)[con_stock], base1)
# Historial de movimientos de tienda para el POS
mv = P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=2000-01-01&hasta=2100-01-01", token=clave)
assert mv and all(x["articulo_id"] != harina for x in mv)  # solo artículos de tienda
assert [x["id"] for x in mv] == sorted((x["id"] for x in mv), reverse=True)
assert {"id", "fecha", "articulo_id", "codigo", "nombre", "unidad", "tipo", "cantidad", "saldo", "referencia", "obs", "otra_tienda", "usuario"} <= set(mv[0])
tipos = {x["tipo"] for x in mv}
assert {"VENTA", "TRANSFERENCIA_SALIDA", "ANULACION", "INVENTARIO"} <= tipos
assert any(x["otra_tienda"] == "T2" for x in mv if x["tipo"] == "TRANSFERENCIA_SALIDA")
solo = P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=2000-01-01&hasta=2100-01-01&articulo_id={con_stock}", token=clave)
assert solo and all(x["articulo_id"] == con_stock for x in solo)
assert P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=2000-01-01&hasta=2000-01-02", token=clave) == []
P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=2026-02-01&hasta=2026-01-01", token=clave, esperado=400)
P("GET", f"/pos/movimientos?tienda_id={tienda}&desde=malo", token=clave, esperado=400)
P("GET", "/pos/movimientos?tienda_id=999999", token=clave, esperado=404)
P("GET", f"/pos/movimientos?tienda_id={tienda}", token="mala", esperado=401)
# Documento de origen de cada movimiento, solo si movió la bodega de esa tienda
assert all("doc_tipo" in x and "doc_id" in x for x in mv)
vistos_doc = set()
for x in mv:
    if not x["doc_tipo"] or (x["doc_tipo"], x["doc_id"]) in vistos_doc:
        continue
    vistos_doc.add((x["doc_tipo"], x["doc_id"]))
    doc = P("GET", f"/pos/documento?tienda_id={tienda}&doc_tipo={x['doc_tipo']}&doc_id={x['doc_id']}", token=clave)
    assert doc["titulo"] and doc["lineas"] and all(l["cantidad"] > 0 for l in doc["lineas"]), doc
    assert {"doc_tipo", "doc_id", "fecha", "estado", "campos", "obs", "lineas_otras_bodegas"} <= set(doc)
assert {"POS", "POS_TRF", "INVENTARIO"} <= {t for t, _ in vistos_doc}
d_pos = P("GET", f"/pos/documento?tienda_id={tienda}&doc_tipo=POS&doc_id={r1['id']}", token=clave)
assert d_pos["estado"] == "ANULADO" and ["Referencia", "POS-test-1"] in d_pos["campos"]
assert "DESPACHO" in {t for t, _ in vistos_doc}
dd = next(i for t, i in vistos_doc if t == "DESPACHO")
assert P("GET", f"/pos/documento?tienda_id={tienda}&doc_tipo=DESPACHO&doc_id={dd}", token=clave)["lineas_otras_bodegas"] is False
P("GET", f"/pos/documento?tienda_id={tienda2}&doc_tipo=DESPACHO&doc_id={dd}", token=clave, esperado=404)  # documento de otra tienda
c = app.conectar()
entrada = c.execute("SELECT id FROM pos_transferencias WHERE referencia='POSTRF-test-1-E'").fetchone()[0]
c.close()
P("GET", f"/pos/documento?tienda_id={tienda}&doc_tipo=POS_TRF&doc_id={entrada}", token=clave, esperado=404)  # solo movió T2
assert P("GET", f"/pos/documento?tienda_id={tienda2}&doc_tipo=POS_TRF&doc_id={entrada}", token=clave)["campos"][2] == ["Desde", "T1"]
P("GET", f"/pos/documento?tienda_id={tienda}&doc_tipo=COMPRA&doc_id=1", token=clave, esperado=400)
P("GET", f"/pos/documento?tienda_id={tienda}&doc_tipo=POS&doc_id=999999", token=clave, esperado=404)
P("GET", f"/pos/documento?tienda_id={tienda}&doc_tipo=POS&doc_id=x", token=clave, esperado=400)
P("GET", f"/pos/documento?tienda_id={tienda}&doc_tipo=POS&doc_id={r1['id']}", token="mala", esperado=401)
clave2 = A("POST", "/config/pos/token", {})["token"]
P("GET", "/pos/ping", token=clave, esperado=401)  # la clave anterior deja de servir
P("GET", "/pos/ping", token=clave2)
A("DELETE", "/config/pos/token")
P("GET", "/pos/ping", token=clave2, esperado=503)
os.environ["NS_POS_TOKEN"] = "clave-de-servidor"
P("GET", "/pos/ping", token="clave-de-servidor")
A("POST", "/config/pos/token", {}, 409)  # definida en el servidor
del os.environ["NS_POS_TOKEN"]

# Acciones críticas: además de "editar" el módulo, cada una requiere su permiso propio
est = A("GET", "/estado")
assert {a["id"] for a in est["acciones"]} == set(app.ACCIONES_IDS) and all(est["usuario"]["permisos"]["acc_" + a] for a in app.ACCIONES_IDS)
perf_log = A("POST", "/perfiles", {"nombre": "Logística sin anular", "permisos": {"despachos": 2, "config": 2, "inventario": 1, "acc_anular_despachos": 0,
                                                                              "acc_respaldo": 1, "acc_cerrar_inventario": 1}})["id"]
p_log = next(p for p in A("GET", "/perfiles") if p["id"] == perf_log)["permisos"]
assert p_log.get("acc_respaldo") == 1 and "acc_cerrar_inventario" not in p_log and "acc_anular_despachos" not in p_log  # inventario solo "ver": no se guarda
A("POST", "/usuarios", {"nombre": "Log", "username": "log1", "password": "prueba-segura-4", "perfil_id": perf_log})
L = Cliente()
L("POST", "/login", {"username": "log1", "password": "prueba-segura-4"})
assert not L("GET", "/estado")["usuario"]["permisos"].get("acc_anular_despachos")
g_acc = L("POST", "/despachos", {"tienda_id": tienda, "fecha": "2026-11-06", "items": [{"articulo_id": vaso, "cantidad": 1}]})["id"]
r_acc = L("POST", f"/despachos/{g_acc}/anular", {}, 403)
assert "Anular guías de despacho" in r_acc["error"]
L("POST", f"/despachos/{g_acc}/fudo", {}, 403)  # sin permiso de envío a Fudo
conn = http.client.HTTPConnection("127.0.0.1", PUERTO); conn.request("GET", "/api/config/respaldo", headers={"Cookie": L.cookie})
assert conn.getresponse().status == 200  # tiene permiso de respaldo
A("PUT", f"/perfiles/{perf_log}", {"nombre": "Logística sin anular", "permisos": {"despachos": 2, "config": 2, "acc_anular_despachos": 1}})
L("POST", f"/despachos/{g_acc}/anular", {})
conn = http.client.HTTPConnection("127.0.0.1", PUERTO); conn.request("GET", "/api/config/respaldo", headers={"Cookie": L.cookie})
assert conn.getresponse().status == 403  # se le quitó
# Migración: perfiles anteriores conservan las acciones de los módulos que editaban
c = app.conectar()
c.execute("UPDATE perfiles SET permisos=? WHERE id=?", (json.dumps({"mermas": 2, "compras": 1}), perf_log))
c.execute("DELETE FROM config WHERE clave='acciones_criticas'")
app.sembrar(c)
mig = json.loads(c.execute("SELECT permisos FROM perfiles WHERE id=?", (perf_log,)).fetchone()[0])
assert mig.get("acc_anular_mermas") == 1 and "acc_anular_compras" not in mig
c.close()

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
# Stock por tienda: una columna por bodega, coincide con la tabla stock, filtra por tipo y ordena por categoría
st = A("GET", "/reportes/stock-tiendas")
assert st["bodegas"][0]["id"] == 0 and len(st["bodegas"]) > 1
c = app.conectar()
for b in st["bodegas"]:
    esperado = c.execute("SELECT COALESCE(SUM(s.cantidad),0) FROM stock s JOIN articulos a ON a.id=s.articulo_id WHERE a.activo=1 AND s.bodega_id=?", (b["id"],)).fetchone()[0]
    assert abs(sum(f["stock"].get(str(b["id"]), 0) for f in st["filas"]) - esperado) < 1e-6, b
c.close()
cats = [f["categoria"].lower() for f in st["filas"]]
assert cats == sorted(cats)
assert all(f["tipo"] == "INSUMO" for f in A("GET", "/reportes/stock-tiendas?tipo=insumo")["filas"])

# Informes: pantalla (JSON) y Excel (.xlsx)
import io, zipfile, xml.dom.minidom
hoy_s = app.hoy_d().isoformat()
rango_inf = f"?desde=2000-01-01&hasta={hoy_s}"
for tipo in ("ventas", "inventario", "produccion", "compras"):
    inf = A("GET", f"/informes/{tipo}{rango_inf}")
    assert inf["titulo"] and inf["resumen"] and inf["hojas"] and all(h["columnas"] for h in inf["hojas"]), tipo
    assert all(set(h["totales"]) <= {c["k"] for c in h["columnas"]} for h in inf["hojas"]), tipo
A("GET", "/informes/ventas?desde=2026-02-01&hasta=2026-01-01", esperado=400)
A("GET", "/informes/otro", esperado=404)
c = app.conectar()
# Ventas: el consumo por ventas del POS y de Fudo coincide con los movimientos
vt = A("GET", f"/informes/ventas{rango_inf}")
esperado = c.execute("SELECT COALESCE(SUM(-cantidad*costo_unit),0) FROM movimientos WHERE doc_tipo IN ('POS','FUDO_VENTA') OR (doc_tipo='SALIDA' AND tipo='VENTA')").fetchone()[0]
casi(sum(r["valor"] for r in vt["hojas"][0]["filas"]), round(esperado, 2))
assert vt["resumen"][1]["v"] == c.execute("SELECT COUNT(*) FROM pos_consumos WHERE estado='VIGENTE'").fetchone()[0]
# Inventario a hoy = stock actual; antes de cualquier movimiento no hay stock
inv = A("GET", f"/informes/inventario{rango_inf}")
actual = {(r[0], r[1]): r[2] for r in c.execute("SELECT bodega_id, articulo_id, cantidad FROM stock WHERE abs(cantidad)>1e-9")}
cod = {r[0]: r[1] for r in c.execute("SELECT id, codigo FROM articulos")}
nombres = {0: "Bodega central", **{r[0]: r[1] for r in c.execute("SELECT id, nombre FROM tiendas WHERE activo=1")}}
detalle = {(d["bodega"], d["codigo"]): d["stock"] for d in inv["hojas"][1]["filas"]}
assert detalle == {(nombres[b], cod[a]): s for (b, a), s in actual.items() if b in nombres}
assert not A("GET", "/informes/inventario?desde=1999-01-01&hasta=1999-12-31")["hojas"][1]["filas"]
# Kardex de un artículo: el saldo final de cada bodega es su stock a la fecha
kx = A("GET", f"/informes/inventario{rango_inf}&articulo={harina}")
kardex = next(h for h in kx["hojas"] if h["nombre"] == "Kardex")["filas"]
for nb in {k["bodega"] for k in kardex}:
    ultimo = [k for k in kardex if k["bodega"] == nb][-1]
    bid = next(b for b, n in nombres.items() if n == nb)
    casi(ultimo["saldo"], app.stock_a_fecha(c, bid, harina, hoy_s))
assert all(k["bodega"] for k in kardex) and kardex[0]["tipo"] == "Saldo inicial"
assert all(h["nombre"] != "Kardex" for h in inv["hojas"])  # sin artículo no hay kardex
# Compras: el neto por insumo coincide con las compras vigentes; filtrar por artículo deja solo ese
cp = A("GET", f"/informes/compras{rango_inf}")
casi(sum(r["neto"] for r in cp["hojas"][0]["filas"]),
     round(c.execute("SELECT SUM(ci.cantidad*ci.precio) FROM compra_items ci JOIN compras co ON co.id=ci.compra_id WHERE co.estado='VIGENTE'").fetchone()[0], 2))
assert {r["codigo"] for r in A("GET", f"/informes/compras{rango_inf}&articulo={harina}")["hojas"][0]["filas"]} == {cod[harina]}
c.close()
# Excel: libro válido, con hoja Resumen y una por tabla, encabezados y totales con fórmula
hc = http.client.HTTPConnection("127.0.0.1", PUERTO)
hc.request("GET", f"/api/informes/compras{rango_inf}&formato=xlsx", headers={"Cookie": A.cookie})
rx = hc.getresponse()
datos_x = rx.read()
assert rx.status == 200 and rx.getheader("Content-Type").startswith("application/vnd.openxmlformats"), rx.status
assert rx.getheader("Content-Disposition").endswith('.xlsx"')
zx = zipfile.ZipFile(io.BytesIO(datos_x))
assert zx.testzip() is None
libro = xml.dom.minidom.parseString(zx.read("xl/workbook.xml"))
hojas_x = [s.getAttribute("name") for s in libro.getElementsByTagName("sheet")]
assert hojas_x == ["Resumen", "Por insumo y proveedor", "Variación de precios", "Guías por facturar"], hojas_x
for i in range(1, len(hojas_x) + 1):
    xml.dom.minidom.parseString(zx.read(f"xl/worksheets/sheet{i}.xml"))  # XML bien formado
hoja2 = zx.read("xl/worksheets/sheet2.xml").decode()
assert "Insumo" in hoja2 and "SUM(" in hoja2 and cod[harina] in hoja2
hc.close()

# Guía de despacho de proveedor: suma stock al recibirla, queda pendiente y se netea con la factura sin volver a sumar
stock_antes = next(x for x in A("GET", "/articulos") if x["id"] == harina)["stock"]
g1 = A("POST", "/compras", {"tipo_documento": "GUIA", "documento": "G-501", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 2, "precio": 1000}]})["id"]
g2 = A("POST", "/compras", {"tipo_documento": "GUIA", "documento": "G-502", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 3, "precio": 1000}]})["id"]
casi(next(x for x in A("GET", "/articulos") if x["id"] == harina)["stock"], stock_antes + 5)
g3 = A("POST", "/compras", {"tipo_documento": "GUIA", "documento": "  ", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1000}]})["id"]
assert A("GET", f"/compras/{g3}")["documento"] == f"SN-{g3:06d}"  # guía sin número: se asigna uno automático
A("POST", f"/compras/{g3}/anular", {})
A("POST", "/compras", {"tipo_documento": "OTRO", "proveedor_id": prov, "items": [{"articulo_id": harina, "cantidad": 1, "precio": 1}]}, 400)
assert {g1, g2} <= {r["id"] for r in A("GET", f"/compras/guias-pendientes?proveedor_id={prov}")}
A("POST", "/compras/facturas", {"proveedor_id": prov, "documento": "F-900", "guias": []}, 400)
A("POST", "/compras/facturas", {"proveedor_id": prov, "documento": "", "guias": [g1]}, 400)
A("POST", "/compras/facturas", {"proveedor_id": prov, "documento": "F-900", "guias": [c1]}, 400)  # una factura no es guía
fx = A("POST", "/compras/facturas", {"proveedor_id": prov, "documento": "F-900", "fecha": "2026-02-01", "neto": 5100, "guias": [g1, g2]})
casi(fx["neto_guias"], 5000); casi(fx["diferencia"], 100)
casi(next(x for x in A("GET", "/articulos") if x["id"] == harina)["stock"], stock_antes + 5)  # la factura no mueve stock
assert not {g1, g2} & {r["id"] for r in A("GET", "/compras/guias-pendientes")}
assert A("GET", f"/compras/{g1}")["factura_doc"] == "F-900"
A("POST", "/compras/facturas", {"proveedor_id": prov, "documento": "F-901", "guias": [g1]}, 409)  # ya neteada
A("POST", "/compras/facturas", {"proveedor_id": prov, "documento": "F-900", "guias": [g1]}, 409)  # factura repetida
A("POST", f"/compras/{g1}/anular", {}, 409)  # no se anula una guía neteada
fl = next(f for f in A("GET", "/compras/facturas") if f["id"] == fx["id"])
assert fl["estado"] == "VIGENTE" and len(fl["guias"]) == 2 and abs(fl["diferencia"] - 100) < 0.01
A("POST", f"/compras/facturas/{fx['id']}/anular", {})
assert {g1, g2} <= {r["id"] for r in A("GET", "/compras/guias-pendientes")}
assert len(next(f for f in A("GET", "/compras/facturas") if f["id"] == fx["id"])["guias"]) == 2  # conserva qué guías tenía
A("POST", f"/compras/facturas/{fx['id']}/anular", {}, 409)
A("POST", f"/compras/{g1}/anular", {})
A("POST", f"/compras/{g2}/anular", {})

# Zona horaria del dispositivo: por nombre o, de respaldo, por la diferencia con UTC
from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402
assert app.zona_dispositivo("", "") is None and app.zona_dispositivo("../../etc/passwd", "x") is None
assert app.zona_dispositivo(None, "99999") is None
assert app.zona_dispositivo("Zona/Inexistente", "180").utcoffset(None) == _td(hours=-3)
if app.ZoneInfo:
    assert str(app.zona_dispositivo("Asia/Tokyo", "")) == "Asia/Tokyo"


def zona_por_http(offset):
    conn = http.client.HTTPConnection("127.0.0.1", PUERTO)
    conn.request("GET", "/api/estado", headers={"Cookie": A.cookie, "X-Zona-Offset": offset})
    conn.getresponse().read()
    return app.hoy_d(), app.ahora_dt()  # sin solicitud en curso: usa la zona del último dispositivo


este, h_este = zona_por_http("-840")   # UTC+14
oeste, _ = zona_por_http("660")        # UTC-11: siempre un día antes
_utc = _dt.now(_tz.utc)  # a 25 h: según la hora UTC quedan a 1 o 2 días; cada una debe ser la fecha de su zona
assert este == (_utc + _td(hours=14)).date() and oeste == (_utc - _td(hours=11)).date(), (este, oeste)
assert abs((h_este - (_dt.now(_tz.utc) + _td(hours=14)).replace(tzinfo=None)).total_seconds()) < 60
zona_por_http("180")

# Edición de compras: el stock se mueve solo por la diferencia; precio, costo promedio e historial se recalculan
ea, eb, ec = art("INSUMO", "EDA"), art("INSUMO", "EDB"), art("INSUMO", "EDC")
ce = A("POST", "/compras", {"tipo_documento": "FACTURA", "documento": "F-77", "proveedor_id": prov, "items": [
    {"articulo_id": ea, "cantidad": 10, "precio": 1000}, {"articulo_id": eb, "cantidad": 4, "precio": 500}]})["id"]
casi(stock()[ea], 10); casi(stock()[eb], 4)
A("PUT", f"/compras/{ce}", {"items": [{"articulo_id": ea, "cantidad": 10, "precio": 1000}, {"articulo_id": eb, "cantidad": 4, "precio": 500}]}, 400)  # sin cambios
r = A("PUT", f"/compras/{ce}", {"documento": "F-77B", "items": [{"articulo_id": ea, "cantidad": 8, "precio": 1200}, {"articulo_id": ec, "cantidad": 3, "precio": 300}]})
assert len(r["cambios"]) == 4, r["cambios"]  # ea cambia, eb se quita, ec se agrega, y el N° de documento
casi(stock()[ea], 8); casi(stock().get(eb, 0), 0); casi(stock()[ec], 3)
de = A("GET", f"/compras/{ce}")
casi(de["neto"], 8 * 1200 + 3 * 300); casi(de["total"], round((8 * 1200 + 3 * 300) * 1.19, 2))
assert de["documento"] == "F-77B" and {i["articulo_id"] for i in de["items"]} == {ea, ec}
assert de["ediciones"] and "F-77 → F-77B" in de["ediciones"][0]["detalle"] and de["ediciones"][0]["usuario"]
arts_e = {x["id"]: x for x in A("GET", "/articulos")}
casi(arts_e[ea]["precio"], 1200); casi(arts_e[ea]["costo"], 1200); casi(arts_e[ec]["precio"], 300)  # solo esta compra: el promedio es el nuevo precio
c = app.conectar()
assert c.execute("SELECT COUNT(*) FROM historial_precios WHERE compra_id=? AND articulo_id=?", (ce, eb)).fetchone()[0] == 0
assert c.execute("SELECT precio FROM historial_precios WHERE compra_id=? AND articulo_id=?", (ce, ea)).fetchone()[0] == 1200
assert c.execute("SELECT COUNT(*) FROM movimientos WHERE doc_tipo='COMPRA' AND doc_id=? AND tipo='EDICION_COMPRA'", (ce,)).fetchone()[0] == 3
c.close()
# no se puede quitar lo que ya se usó: la edición se rechaza entera y no cambia nada
A("POST", "/mermas", {"articulo_id": ea, "cantidad": 7, "motivo_id": A("GET", "/catalogos")["motivos"][0]["id"], "bodega_id": 0})
A("PUT", f"/compras/{ce}", {"items": [{"articulo_id": ea, "cantidad": 2, "precio": 1200}, {"articulo_id": ec, "cantidad": 3, "precio": 300}]}, 409)
casi(stock()[ea], 1); assert len(A("GET", f"/compras/{ce}")["items"]) == 2
# anular después de editar revierte el NETO (10 − 2 − 1 = 7), no cada movimiento por separado (−10 fallaría con 7 en stock)
A("PUT", f"/compras/{ce}", {"items": [{"articulo_id": ea, "cantidad": 7, "precio": 1200}, {"articulo_id": ec, "cantidad": 3, "precio": 300}]})
casi(stock()[ea], 0)
A("POST", "/compras", {"tipo_documento": "BOLETA", "proveedor_id": prov, "items": [{"articulo_id": ea, "cantidad": 7, "precio": 1200}]})
casi(stock()[ea], 7)
A("POST", f"/compras/{ce}/anular", {})
casi(stock()[ea], 0); casi(stock().get(ec, 0), 0)
A("PUT", f"/compras/{ce}", {"items": [{"articulo_id": ec, "cantidad": 1, "precio": 1}]}, 409)  # anulada
# una guía neteada con su factura no se edita
gn = A("POST", "/compras", {"tipo_documento": "GUIA", "documento": "G-9", "proveedor_id": prov, "items": [{"articulo_id": eb, "cantidad": 2, "precio": 10}]})["id"]
fn = A("POST", "/compras/facturas", {"proveedor_id": prov, "documento": "F-999", "guias": [gn]})["id"]
A("PUT", f"/compras/{gn}", {"items": [{"articulo_id": eb, "cantidad": 1, "precio": 10}]}, 409)
A("POST", f"/compras/facturas/{fn}/anular", {})
A("PUT", f"/compras/{gn}", {"items": [{"articulo_id": eb, "cantidad": 1, "precio": 10}]})
casi(stock()[eb], 1)
A("PUT", f"/compras/{gn}", {"items": [{"articulo_id": torta, "cantidad": 1, "precio": 10}]}, 400)  # solo insumos

# Edición de guías de despacho: la diferencia se mueve entre la central y la tienda
edv = art("INSUMO", "EDV", un, desechable=True)
A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "items": [{"articulo_id": edv, "cantidad": 50, "precio": 100}]})
ge = A("POST", "/despachos", {"tienda_id": tienda2, "items": [{"articulo_id": edv, "cantidad": 10}]})["id"]
casi(stock()[edv], 40); casi(stock(tienda2)[edv], 10)
r = A("PUT", f"/despachos/{ge}", {"transportista": "Pedro", "items": [{"articulo_id": edv, "cantidad": 15, "precio": 120}]})
casi(stock()[edv], 35); casi(stock(tienda2)[edv], 15)
dg = A("GET", f"/despachos/{ge}")
casi(dg["neto"], 15 * 120); assert dg["transportista"] == "Pedro" and dg["ediciones"]
A("PUT", f"/despachos/{ge}", {"items": [{"articulo_id": edv, "cantidad": 6, "precio": 120}]})
casi(stock()[edv], 44); casi(stock(tienda2)[edv], 6)
A("PUT", f"/despachos/{ge}", {"tienda_id": tienda, "items": [{"articulo_id": edv, "cantidad": 6}]}, 400)  # no se cambia la tienda
A("PUT", f"/despachos/{ge}", {"items": [{"articulo_id": edv, "cantidad": 999}]}, 409)  # no hay tanto en la central
A("POST", f"/despachos/{ge}/anular", {})
casi(stock()[edv], 50); casi(stock(tienda2).get(edv, 0), 0)
A("PUT", f"/despachos/{ge}", {"items": [{"articulo_id": edv, "cantidad": 1}]}, 409)  # anulada
# guía en camino (tienda que recibe en el POS): solo se mueve la central; recibida: ya no se edita
tpos = A("POST", "/tiendas", {"nombre": "TPOS", "direccion": "D", "comuna": "C", "region": "R", "recibe_pos": True})["id"]
gc = A("POST", "/despachos", {"tienda_id": tpos, "items": [{"articulo_id": edv, "cantidad": 5}]})["id"]
A("PUT", f"/despachos/{gc}", {"items": [{"articulo_id": edv, "cantidad": 8}]})
casi(stock()[edv], 42); casi(stock(tpos).get(edv, 0), 0)
c = app.conectar()
app.recibir_despacho(c, gc, tpos, {}, "Ana", "", "REC-EDIT-1")
c.commit(); c.close()
casi(stock(tpos)[edv], 8)
A("PUT", f"/despachos/{gc}", {"items": [{"articulo_id": edv, "cantidad": 2}]}, 409)
# sin el permiso de edición (acción crítica), el perfil no puede editar
perf = {p["nombre"]: p for p in A("GET", "/perfiles")}
assert "acc_editar_compras" not in json.dumps(perf["Gerencia"]["permisos"])

# Unidad de receta: se compra en kg, la receta se escribe en g y se descuenta en kg
g_ = next(u["id"] for u in cat["unidades"] if u["abreviatura"] == "g")
ml_ = next(u["id"] for u in cat["unidades"] if u["abreviatura"] == "ml")
azu = A("POST", "/articulos", {"tipo": "INSUMO", "nombre": "Azúcar UR", "categoria_id": cid, "unidad_id": kg, "precio": 2000,
                               "unidad_receta_id": g_, "factor_receta": 1000})["id"]
A("POST", "/articulos", {"tipo": "INSUMO", "nombre": "Sin factor", "categoria_id": cid, "unidad_id": kg, "unidad_receta_id": g_}, 400)
ficha = next(x for x in A("GET", "/articulos") if x["id"] == azu)
assert ficha["unidad"] == "kg" and ficha["unidad_receta"] == "g" and ficha["factor_receta"] == 1000
# la misma unidad, un producto o un desechable no llevan unidad de receta
igual = A("POST", "/articulos", {"tipo": "INSUMO", "nombre": "Igual UR", "categoria_id": cid, "unidad_id": kg, "unidad_receta_id": kg, "factor_receta": 5})["id"]
assert next(x for x in A("GET", "/articulos") if x["id"] == igual)["unidad_receta"] == "kg"
gall = A("POST", "/articulos", {"tipo": "PRODUCTO", "nombre": "Galleta UR", "categoria_id": cid_prod, "unidad_id": un, "precio": 500,
                                "unidad_receta_id": g_, "factor_receta": 1000})["id"]
assert next(x for x in A("GET", "/articulos") if x["id"] == gall)["unidad_receta"] == "un"
A("POST", "/compras", {"tipo_documento": "FACTURA", "proveedor_id": prov, "items": [{"articulo_id": azu, "cantidad": 2, "precio": 2000}]})  # 2 kg
casi(stock()[azu], 2)
A("PUT", f"/recetas/{gall}", {"rendimiento": 10, "items": [{"articulo_id": azu, "cantidad": 250}]})  # 250 g por 10 galletas
rec = next(r for r in A("GET", "/recetas") if r["articulo_id"] == gall)
it = rec["items"][0]
casi(it["cantidad"], 0.25); casi(it["cantidad_receta"], 250); assert it["unidad"] == "kg" and it["unidad_receta"] == "g"
casi(rec["costo_unit"], 0.25 * 2000 / 10)  # el costo sigue en pesos por kg
casi(rec["max_producible"], 80)
pr = A("POST", "/produccion", {"articulo_id": gall, "cantidad": 40})["id"]  # 4 × 250 g = 1 kg
casi(stock()[azu], 1)
imp = A("GET", "/produccion/impresion?desde=2000-01-01&hasta=2100-12-31")
li = next(o for o in imp["ordenes"] if o["id"] == pr)["items"][0]
casi(li["cantidad"], 1); assert li["unidad"] == "kg" and li["unidad_receta"] == "g" and li["factor_receta"] == 1000
err = A("POST", "/produccion", {"articulo_id": gall, "cantidad": 60}, 409)  # 1,5 kg: falta 0,5 kg = 500 g
assert "0.5 kg (500 g)" in json.dumps(err, ensure_ascii=False), err
# corregir la equivalencia (misma unidad de receta) conserva lo escrito en la receta: 250 g
A("PUT", f"/articulos/{azu}", {"tipo": "INSUMO", "nombre": "Azúcar UR", "categoria_id": cid, "unidad_id": kg, "precio": 2000, "unidad_receta_id": g_, "factor_receta": 500})
it = next(r for r in A("GET", "/recetas") if r["articulo_id"] == gall)["items"][0]
casi(it["cantidad_receta"], 250); casi(it["cantidad"], 0.5)
# quitar la unidad de receta deja la receta en kg, con la misma cantidad real
A("PUT", f"/articulos/{azu}", {"tipo": "INSUMO", "nombre": "Azúcar UR", "categoria_id": cid, "unidad_id": kg, "precio": 2000, "unidad_receta_id": ""})
it = next(r for r in A("GET", "/recetas") if r["articulo_id"] == gall)["items"][0]
casi(it["cantidad"], 0.5); casi(it["cantidad_receta"], 0.5); assert it["unidad_receta"] == "kg"
# la unidad de stock no cambia si hay movimientos (compras e informes están en ella)
A("PUT", f"/articulos/{azu}", {"tipo": "INSUMO", "nombre": "Azúcar UR", "categoria_id": cid, "unidad_id": g_, "precio": 2000}, 409)
A("PUT", f"/articulos/{igual}", {"tipo": "INSUMO", "nombre": "Igual UR", "categoria_id": cid, "unidad_id": ml_})  # sin movimientos, sí

# Datos de ejemplo: base nueva, y coherencia del historial
os.environ["NS_DB"] = app.DB_PATH = os.path.join(tempfile.mkdtemp(), "demo.db")
c = app.conectar()
app.sembrar(c)
D = Cliente()
c.close()
D("POST", "/instalar", {"nombre": "Admin", "username": "admin", "password": "prueba-segura-1", "demo": True})
for rep in ("rendimiento", "precios", "margenes", "compras", "despachos", "mermas", "cobertura", "panel", "stock-tiendas"):
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
