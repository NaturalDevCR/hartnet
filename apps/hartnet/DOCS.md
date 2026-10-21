# Instalación local en Home Assistant OS

1. Copia esta carpeta completa a `/addons/hartnet` de tu instalación.
2. En Ajustes → Apps → Tienda → menú, busca actualizaciones y abre **HartNet** en apps locales.
3. Instala la app y configura `api_token` con un valor aleatorio de al menos 16 caracteres.
4. Inicia y abre la interfaz. Importa tu bloque YAML y revisa la vista previa antes de guardarlo.
5. Instala también `custom_components/hartnet` en `/config/custom_components/hartnet`,
   reinicia HA y agrega **HartNet** en Ajustes → Dispositivos y servicios.
6. Usa host `127.0.0.1`, puerto `8099` y el mismo token. La app utiliza la red del host.
7. Detén o deshabilita el emisor anterior y revisa el patch antes de activar la salida.

La app guarda la configuración en `/data/project.json` y la versión anterior en
`/data/project.previous.json`. Cada inicio conserva el patch y comienza con salida detenida.
Los valores de ejecución no se restauran. Detener salida cesa los paquetes; el gateway
puede mantener el último estado según su configuración. Apaga las luces antes de detener
si ese es el efecto que necesitas. No existe confirmación del estado físico por ArtDmx.

La salida es unicast manual: solo a los destinos configurados. El universo 0 de instalaciones
existentes se conserva. El puerto UDP 6454 debe estar libre. El descubrimiento envía ArtPoll
únicamente cuando se solicita y no modifica el patch. RDM y la detección automática de
personalidades aún no están implementados.

Exportar perfiles produce offsets relativos, sin IP ni direcciones de instalación. Para una
copia íntegra del proyecto usa el editor avanzado y conserva el JSON en un lugar privado.
No se incluye publicación en una biblioteca comunitaria ni instalación HACS en esta versión.
