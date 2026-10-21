# Revisión de Breina/ha-artnet-led

Revisión del 21 de octubre de 2026. Snapshot inspeccionado:
[`446af6ea99a1f332f133088668e1864d04095287`](https://github.com/Breina/ha-artnet-led/tree/446af6ea99a1f332f133088668e1864d04095287).
Se revisaron las fuentes Python de producción, los tests, README, manifest,
configuraciones de staging, Dockerfile y workflows. No se probaron equipos físicos
ni se ejecutó la suite completa del proyecto de referencia.

## Inventario funcional

| Área | Implementación observada | Consecuencia para HartNet |
| --- | --- | --- |
| Instalación | Custom component `artnet_led` vía HACS; versión 0.1.23 | App y componente separados, con configuración visual |
| Configuración | Plataforma YAML en `light`, sin config flow | Conexión por UI y editor de perfiles |
| Dependencia | `pyartnet==2.0` para salida, fades y curvas | Motor propio pequeño para MVP; evitar acoplarse a internals |
| Transportes | Art-Net directo, controlador, sACN y KiNet | MVP directo; los otros requieren adaptadores posteriores |
| Universos | Varios universos, tramas completas o parciales | Un único buffer compuesto por destino/universo |
| Tipos HA | Fixed, binary, dimmer, RGB, RGBW, RGBWW, CCT y XY, todos en `light` | Funciones genéricas y dominios semánticos |
| Resolución | 8/16/24/32 bits y endian por equipo | Resolución por función y bytes separados |
| Layout | Letras de color escaladas/no escaladas, dimmer, hue, saturation, XY, CCT y constantes | Perfiles explícitos, importación validada por subconjunto |
| Estado | RestoreEntity, brillo, color y datos DMX en atributos | Separar estado deseado, salida y confirmación física |
| Efectos | Transiciones, flash corto/largo, curvas lineal/cuadrática/cúbica/cuártica | Fades y curvas de luz; flash posterior |
| Identidad | Derivada de host/universo/canal; conserva IDs antiguos por nombre cuando existen | IDs persistentes que sobrevivan editar una IP o patch |

Fuente principal de esta tabla:
[`light.py`](https://github.com/Breina/ha-artnet-led/blob/446af6ea99a1f332f133088668e1864d04095287/custom_components/artnet_led/light.py)
y [`channel_switch.py`](https://github.com/Breina/ha-artnet-led/blob/446af6ea99a1f332f133088668e1864d04095287/custom_components/artnet_led/util/channel_switch.py).

## Qué hace el modo controlador

[`ArtNetServer`](https://github.com/Breina/ha-artnet-led/blob/446af6ea99a1f332f133088668e1864d04095287/custom_components/artnet_led/client/artnet_server.py)
abre UDP 6454, consulta nodos, mantiene índices por IP/BindIndex y universo, elimina
nodos antiguos, responde a consultas y transmite a destinos descubiertos. Incluye
secuenciación y reenvío periódico. Puede recibir ArtDmx para actualizar luces mediante
`UniverseBridge` / `ChannelBridge`. Por tanto, la descripción introductoria de
«integración unidireccional» no describe todas las rutas implementadas.

También decodifica y registra diagnósticos, timecode y respuestas de programación IP.
ArtCommand modifica nombres de entrada/salida. No equivale a exponer todas estas
capacidades como controles HA: ArtTrigger no ejecuta nada; ArtSync se ignora.
RDM, cambio a sACN y ArtAddress están marcados como no soportados en el servidor.

El módulo de codecs define más opcodes y estructuras de los que el servidor utiliza.
La presencia de una enumeración no constituye soporte de la funcionalidad.

## Staging no es producto implementado

`staging/platform-configuration2.yaml` bosqueja perfiles, fan, binary_sensor, number,
switch y triggers de escenas/shows. Es una propuesta de formato: no existen esas
plataformas ni una ruta de setup que consuma dicha configuración. El Dockerfile
sirve para desarrollo de HA; no es una app de Supervisor con Ingress.

Los workflows validan HACS y hassfest. Los tests cubren conversiones de canal,
regresiones CCT/RGBWW y un loopback real de pyartnet. No hay cobertura de todas las
rutas de descubrimiento/controlador. Una regresión de mutación de tupla RGBWW está
marcada explícitamente como `xfail`.

## Problemas que no conviene heredar

Comprobación por lectura del código y, para los tres primeros casos, reproducción
aislada del codec sin abrir sockets:

1. **Dirección Art-Net incorrecta en el codec del controlador.** `PortAddress(1,0,0)`
   devuelve 8192 y `PortAddress(0,1,0)` devuelve 512; deberían representar 256 y 16.
   La especificación distribuye los bits en 7/4/4. Esto es independiente del modo
   directo de pyartnet, que utiliza otra implementación.
2. **ArtDmx pierde bits del universo.** Para dirección 16, el serializer del controlador
   emite `00 00` en los bytes de dirección en lugar de `10 00` al aplicar máscaras de 4 bits.
3. **Límite superior de polling colapsado.** El setter `target_port_bounds=(1,255)`
   guarda `(1,1)` porque asigna el primer valor a ambos extremos.
4. **Recepción frágil.** Un opcode desconocido puede producir `ValueError`; varias
   rutas acceden a posiciones sin validar una longitud mínima completa. ArtPollReply
   presupone campos modernos y no maneja con robustez todas las respuestas antiguas.
5. **Acoplamiento a pyartnet.** Los bridges acceden a buffers, jobs, fades y propiedades
   privadas; `light.py` también sustituye globalmente la fábrica de tareas de la librería.
6. **Ciclo de vida.** Hay nodos globales y tareas persistentes sin el patrón moderno
   de setup/unload por ConfigEntry. No es una base adecuada para recargas frecuentes.
7. **Documentación divergente.** README describe hasta 40 FPS mientras el schema permite
   50; el schema limita universos a 1024 aunque el controlador pretende aceptar 15 bits.
8. **Semántica limitada.** Todo es una luz. No hay biblioteca exportable ni modelado
   general de funciones discretas/continuas o canales coarse/fine separados.

Fuentes: [codecs](https://github.com/Breina/ha-artnet-led/blob/446af6ea99a1f332f133088668e1864d04095287/custom_components/artnet_led/client/__init__.py),
[bridges](https://github.com/Breina/ha-artnet-led/tree/446af6ea99a1f332f133088668e1864d04095287/custom_components/artnet_led/bridge)
y [tests](https://github.com/Breina/ha-artnet-led/tree/446af6ea99a1f332f133088668e1864d04095287/test).

## Descubrimiento frente a identificación de funciones

ArtPoll/ArtPollReply permiten conocer nodos, puertos, universos y capacidades anunciadas.
Eso no describe automáticamente el canal «velocidad», «gobo» o «pan» de un fixture detrás
del gateway. Con RDM compatible pueden obtenerse identidad, dirección y personalidad;
eso ayuda a elegir un perfil, pero no garantiza recuperar toda la tabla semántica.

La revisión 1.4dp de la especificación también contempla ArtDataRequest/Reply con URLs
de producto, manual y personalidades UDR/GDTF. Es otra vía opcional, dependiente del
fabricante. Ninguna justifica prometer automapeo universal. La asistencia manual y los
perfiles importados siguen siendo necesarios.

Fuentes: [Art-Net 4, revisión 1.4dp](https://art-net.org.uk/downloads/art-net.pdf),
[formato OFL](https://github.com/OpenLightingProject/open-fixture-library/blob/master/docs/fixture-format.md)
y [DMX en GDTF](https://gdtf-share.com/help/users/gdtf_builder/dmx/index.html).
