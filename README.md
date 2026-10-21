# HartNet

**Art-Net con perfiles, una interfaz propia y entidades nativas en Home Assistant.**

Estado: **alpha experimental 0.1.0**. Motor, interfaz y componente de HA implementados;
la validación con gateways y equipos físicos todavía está pendiente. No es una
implementación de todos los paquetes de Art-Net.

HartNet separa el nodo de red, el perfil reutilizable y el equipo instalado. Eso permite
controlar funciones de cualquier equipo DMX con un mapeo conocido: intensidad y color,
pan/tilt, velocidad, macros, relés u otros valores. La semántica depende del manual del equipo.

## Qué incluye

- App para Home Assistant OS, con acceso mediante Ingress.
- Integración configurada desde la UI de HA: `light`, `number`, `select` y `switch`.
- Interfaz adaptable: equipos, controles, patch de 512 canales, biblioteca y editor de perfiles.
- Importación con vista previa de un subconjunto explícito de `ha-artnet-led` en modo directo.
- Canales de 8/16/24/32 bits, con bytes consecutivos o separados y orden configurable.
- Perfiles JSON exportables sin IP, universo ni canal inicial de la instalación.
- Salida unicast, FPS limitado por nodo, refresh y transiciones para luces/valores continuos.
- ArtPoll / ArtPollReply para descubrimiento explícito de nodos, incluyendo BindIndex.
- Validación de direcciones, colisiones de patch, límites y valores seleccionables.
- API autenticada, persistencia atómica y copia de la configuración anterior.

La salida comienza **detenida en cada arranque**. El patch se guarda; los valores de
ejecución no se restauran. Las entidades HA aparecen como no disponibles mientras
la salida esté detenida. No se requiere MQTT.

## Instalar en Home Assistant OS

1. Agrega este repositorio a la tienda de Apps:
   `https://github.com/NaturalDevCR/hartnet`.
2. Instala **HartNet**, configura `api_token` con un valor aleatorio de al menos 16 caracteres
   y abre la interfaz web. No compartas ese token.
3. En HACS, agrega este mismo repositorio como **Integration**, descarga HartNet y reinicia HA.
   También puedes copiar `custom_components/hartnet` a `/config/custom_components/hartnet`.
4. Agrega **HartNet** en Ajustes → Dispositivos y servicios. Usa host `127.0.0.1`,
   puerto `8099` y el token de la app.
5. Importa el bloque `light:` o crea nodos, perfiles y equipos. Revisa la vista previa y guarda.
6. Antes de activar la salida, detén el emisor previo que controle esos mismos canales.

La instalación local de la app también está descrita en [DOCS.md](apps/hartnet/DOCS.md).
HACS y Supervisor no se ejecutan en las pruebas unitarias; la instalación y el
funcionamiento real se documentan separadamente de las pruebas automatizadas.

## Importar desde ha-artnet-led

Se importa `artnet-direct`: nodo, puerto, universos, FPS, refresh, tramas completas/parciales,
layout RGB/RGBW/RGBWW/CCT, dimmer, binary, constantes, tamaños y orden de bytes.
Los universos no se renumeran, incluido el universo 0 usado por gateways existentes.

La opción **Convertir dimmers independientes a number** permite representar velocidad y
macros como controles numéricos. Se elige expresamente en la vista previa. Un macro solo
se convierte en `select` cuando el usuario configura sus valores y nombres documentados.

El importador rechaza funciones no implementadas (`xy`, hue/saturation, temperatura en un
canal, blanco autocalculado RGB), otros transportes y overrides de destino. No omite esos
datos para generar una configuración aparentemente completa. Las transiciones por comando
funcionan; el valor predeterminado legacy por equipo todavía no se importa.

Los valores de color de alta resolución usan todo el rango; el componente legacy escala
valores de 8 bits. Las constantes sí conservan su escalado legacy. Los IDs antiguos no se
adoptan ni se renombran. Las automatizaciones existentes requieren una migración aparte.

## Perfiles y dispositivos

Un perfil contiene funciones con slots relativos ordenados de byte más significativo a
menos significativo. Por ejemplo, `slots: [1, 8]` representa un valor de 16 bits cuyo byte
coarse está en el primer canal del equipo y el fine en el octavo.

`number`, `select` y `switch` crean controles separados dentro del dispositivo HA.
Las funciones de color y dimmer se agrupan como una luz. `constant` fija un valor.
Una función `select` elige valores representativos explícitos; no implementa aún rangos
variables, funciones condicionales ni ruedas completas de un formato profesional de fixtures.

Editar un perfil compartido afecta a todos sus equipos. Las entidades nuevas se descubren
en el siguiente sondeo. Para cambios de tipo, eliminación de controles o metadatos de un
perfil existente, recarga la integración desde HA. Las entidades obsoletas se deshabilitan
por disponibilidad, pero sus entradas de registro no se borran automáticamente.

## Desarrollo y pruebas

Motor y app requieren Python 3.13+. La integración se prueba con HA **2026.10.2 / Python 3.14**.

```sh
uv venv --python 3.13
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/pytest -q
.venv/bin/ruff check apps custom_components tests scripts
.venv/bin/python -m hartnet --dev --data data/project.json
```

Abre `http://127.0.0.1:8099`. `--dev` permite acceso sin token únicamente por loopback;
no se utiliza en la app de Home Assistant. El ejemplo distribuido utiliza `192.0.2.30`,
una dirección de documentación, y no representa un gateway real.

Pruebas con Home Assistant real, en un entorno separado:

```sh
uv venv .venv-ha --python 3.14
uv pip install --python .venv-ha/bin/python -e . pytest-homeassistant-custom-component==0.13.373
.venv-ha/bin/pytest tests/test_homeassistant.py -q
docker build -t hartnet:dev apps/hartnet
```

`scripts/check_ui.py` usa Playwright y una instalación local de Chrome en macOS para
comprobar importación, patch, edición y anchuras de 1440/390/320 px. No activa salida DMX.
Las pruebas de red se limitan a loopback; el estado ArtDmx es asumido, sin confirmación física.

## Límites y siguientes entregas

El emisor actual es **unicast manual**, con compatibilidad legacy, no un controlador Art-Net 4
completo con suscripciones y anuncios propios. RDM, ArtDataRequest, recepción/merge DMX,
ArtSync, ArtTrigger, timecode, sACN, KiNet, importación OFL/GDTF y biblioteca comunitaria están
pendientes. No se realiza barrido de canales para adivinar sus funciones.

Los huecos se emiten a 0. Detener la salida cesa los paquetes; el gateway puede mantener el
último estado. No hay un blackout universal: apagar una luz no modifica sus controles
numéricos, selectores ni relés. Los valores de reposo deben definirse en cada perfil.

Consulta el [análisis de referencia](docs/reference-review.md), la
[arquitectura](docs/architecture.md) y el [plan de validación](docs/validation.md).

## Referencias

Diseño independiente informado por [Breina/ha-artnet-led](https://github.com/Breina/ha-artnet-led)
y la [especificación oficial Art-Net](https://art-net.org.uk/downloads/art-net.pdf).
El código del repositorio de referencia no se incluye como dependencia ni se ha copiado.

**Art-Net™ Designed by and Copyright Artistic Licence**.

Código propio bajo [licencia MIT](LICENSE). Los perfiles de terceros conservan su atribución y licencia.
