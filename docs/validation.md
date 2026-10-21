# Validación y despliegue experimental

## Pruebas automatizadas

- Importación del patch de referencia: ocho equipos, universo 0, tramas completas,
  direcciones y constantes exactas; conversión opcional de cuatro dimmers a number.
- Frame esperado de RGBW, controles independientes y huecos sin asignar.
- Enteros de 8/16/24/32 bits y bytes separados.
- Rechazo atómico de comandos, solapamientos, desbordamientos y opciones desconocidas.
- Exclusión de direcciones de instalación al exportar perfiles.
- ArtDmx: endianness, padding par, secuencia y extremos de la dirección de 15 bits.
- ArtPollReply mínimo de 207 bytes y nodos con BindIndex.
- Loopback UDP real: transiciones, límite de FPS, refresh y cese del emisor.
- API: autenticación, importación sin salida, persistencia y rechazo de cambios con salida activa.
- Home Assistant 2026.10.2 real, app HTTP real y tráfico Art-Net restringido a loopback:
  config flow, entidades nativas y llamadas de servicio.
- Navegador: importación, control numérico, patch, editor de perfiles y anchuras de
  1440, 390 y 320 px, sin activar DMX.
- Construcción de la imagen Docker de la app.

Estos checks no sustituyen una instalación real de Supervisor/Ingress ni una prueba
con un gateway. Los tests de HA se ejecutan con pytest-homeassistant-custom-component;
el harness añade el directorio del proyecto al paquete de componentes del entorno.

## Secuencia de prueba en una instalación existente

1. Inventariar versión, apps y entidades del emisor anterior.
2. Conservar configuración y registros existentes. Instalar HartNet en paralelo con
   sus propios IDs; no renombrar ni cambiar automatizaciones en esta fase.
3. Verificar Ingress, importación y perfiles con el emisor HartNet detenido.
4. Instalar el componente y comprobar entidades sin paquetes hacia el gateway.
5. Revisar consumidores y estado real antes de un cambio de emisor.
6. En una ventana de prueba, suspender el emisor anterior y probar un equipo y canal
   conocido. Verificar macros, velocidad y apagado, además de color/brillo.
7. Volver al emisor anterior si la equivalencia no está comprobada.

El test del nuevo emisor sobre un universo completo transmite todos sus slots. No debe
interpretarse «un equipo de prueba» como garantía de aislamiento si se mantienen otros
controles del mismo universo sin un plan de valores. Para coexistir, usar universos o
destinos separados, o definir de forma expresa un único dueño del buffer.

## Pendiente antes de una versión estable

- Verificar amd64 y aarch64 en Supervisor y la instalación por HACS.
- Validar hardware y las tablas reales de los equipos.
- Más tests de CCT, RGBWW, recarga, evolución de perfiles y pérdida de conectividad.
- Acciones momentáneas, rangos de macros, unidades físicas y políticas de reposo.
- RDM/ArtDataRequest, entrada DMX, arbitraje de fuentes y ArtSync.
- Adaptadores sACN/KiNet, importadores OFL/GDTF y catálogo comunitario.
- Versionado/migraciones del modelo y control de revisiones para ediciones concurrentes.
