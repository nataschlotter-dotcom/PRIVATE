# Sistema de producción y logística de Nata & Schlott

## Iniciar

Requiere Python 3.10 o superior; no hay nada más que instalar. Haz doble clic en `iniciar.bat`, o ejecuta:

```bash
python app.py
```

Abre http://localhost:8080. La primera vez se crea la cuenta del administrador.

## Datos

- Todo se guarda en `nata_schlott.db`, junto a `app.py`. Copia ese archivo y sus acompañantes `-wal` y `-shm`, con el sistema detenido, para respaldar.
- Para quitar los datos de ejemplo y conservar usuarios e IVA, cierra el sistema y ejecuta `vaciar_datos.bat`. Pide confirmación y guarda antes un respaldo en la carpeta `respaldos`. También conserva el logo, los perfiles, las categorías, las unidades y los motivos de merma.
- Para partir de cero por completo, detén el sistema y borra esos archivos.

## Uso desde otros equipos

`NS_HOST=0.0.0.0` lo abre a la red local y `NS_PORT` cambia el puerto. El sistema no incluye HTTPS: para usarlo desde internet, publícalo detrás de un proxy con HTTPS y define `NS_CLAVE_INSTALACION` para proteger el primer inicio.

## Publicar en Render

`render.yaml` crea el servicio, un disco para la base de datos y la clave de instalación. Sube a un repositorio privado de GitHub solo el contenido de `publicar_en_github` (nunca `nata_schlott.db` ni `respaldos`) y crea un Blueprint en Render desde ese repositorio. La clave queda en las variables de entorno del servicio. Descarga respaldos desde **Configuración → Respaldo**.

## Reglas de negocio

- Todo cambio de stock queda en el historial, y ningún saldo puede quedar negativo.
- **Compra:** aumenta la bodega central, actualiza el precio del insumo al último pagado y recalcula el costo promedio ponderado.
- **Producción:** descuenta los ingredientes en proporción al rendimiento de la receta. Si falta alguno, no se descuenta nada.
- **Despacho:** mueve productos terminados y desechables de la bodega central a la tienda. Los insumos de receta no se despachan.
- **Anulaciones:** revierten el stock con un movimiento visible, solo si ese stock sigue disponible. El costo promedio no se recalcula.
- **Toma de inventario:** al cerrarla, ajusta los artículos contados según el stock de ese momento.
- **Recetas:** las cantidades van en la unidad de medida de cada ingrediente; no hay conversión entre unidades.
- **Usuarios de tienda:** un usuario asociado a una tienda solo ve la información de esa tienda.
- **Guías:** son documentos de control interno y no reemplazan la guía de despacho electrónica del SII.

## Pruebas

```bash
python test_flujos.py
```

Usa una base de datos temporal y no toca la real.
