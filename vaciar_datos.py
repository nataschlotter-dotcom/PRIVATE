#!/usr/bin/env python3
"""Deja el sistema listo para cargar datos reales: respalda la base y borra los datos operacionales.

Conserva el IVA, el logo, los usuarios, los perfiles y las listas base (categorías, unidades y motivos de merma).
"""
import socket
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import app

# Orden: primero las tablas que dependen de otras.
A_VACIAR = [
    "pos_inventarios", "inventario_items", "inventarios", "movimientos", "historial_precios", "compra_items", "compras", "compra_facturas","devolucion_items", "devoluciones", "salida_interna_items", "salidas_internas",
    "fudo_stock_envios", "fudo_sincronizaciones", "fudo_equivalencias", "despacho_items", "despachos", "mermas", "salidas_tienda", "pos_consumos", "pos_transferencias", "producciones", "receta_items", "recetas",
    "stock", "articulos", "proveedores", "fudo_tiendas", "tiendas",
]


def sistema_abierto():
    host = app.os.environ.get("NS_HOST", "127.0.0.1")
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1" if host == "0.0.0.0" else host, int(app.os.environ.get("NS_PORT", "8080")))) == 0


def respaldar(db):
    base = Path(app.DB_PATH)
    # Los respaldos van junto al programa (en OneDrive, si ahí está); la base de datos puede estar en otra carpeta (NS_DB).
    carpeta = Path(app.__file__).resolve().parent / "respaldos"
    carpeta.mkdir(exist_ok=True)
    destino = carpeta / f"{base.stem}_antes_de_vaciar_{datetime.now():%Y%m%d_%H%M%S}.db"
    copia = sqlite3.connect(destino)
    with copia:
        db.backup(copia)
    copia.close()
    return destino


def vaciar(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("UPDATE usuarios SET tienda_id=NULL")
        for tabla in A_VACIAR:
            db.execute(f"DELETE FROM {tabla}")
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def main():
    if not Path(app.DB_PATH).exists():
        print("No se encontró la base de datos: no hay nada que vaciar.")
        return 1
    if sistema_abierto():
        print("El sistema está abierto. Cierra su ventana negra y vuelve a ejecutar esto.")
        return 1
    db = app.conectar()
    usuarios = app.scalar(db, "SELECT COUNT(*) FROM usuarios")
    print("Se BORRARÁN: artículos, recetas, proveedores, tiendas, stock, compras, devoluciones, producciones,")
    print("despachos, mermas, inventarios e historial.")
    print(f"Se conservan: IVA ({app.iva_actual(db):g}%), logo, {usuarios} usuario(s), perfiles,")
    print("categorías, unidades de medida y motivos de merma.")
    print("Los usuarios asociados a una tienda quedarán sin tienda: vuelve a asignarla al crear las tiendas.\n")
    if input("Para continuar escribe VACIAR y presiona Enter: ").strip() != "VACIAR":
        print("Cancelado. No se borró nada.")
        return 1
    destino = respaldar(db)
    vaciar(db)
    db.execute("VACUUM")
    db.close()
    print(f"\nListo. Respaldo guardado en: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
