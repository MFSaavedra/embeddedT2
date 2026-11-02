# Tarea 2: Adquisición con BME688 y procesamiento local

**CC5328-1 Sistemas Embebidos y Sensores · Universidad de Chile · Semestre 2026-2**

Un ESP32 lee temperatura, humedad relativa y presión **reales** desde un sensor BME688 por
I²C. Sobre la temperatura calcula una media móvil temporal y detecta picos (máximos locales
sobre un umbral) **en el propio microcontrolador**, y transmite solo las variables
seleccionadas por USB-serial a una aplicación Python/PyQt. La aplicación configura la
adquisición en tiempo real, grafica las señales y muestra los eventos.

**Integrantes:**
Joaquín Acosta,
Matías Saavedra

> Enunciado completo: [`docs/Tarea2_CC5328.pdf`](docs/Tarea2_CC5328.pdf).

> **Estado: andamiaje inicial.** El firmware compila, al arrancar busca el BME688 en el bus
> I²C (aún sin probar con el sensor) y responde a `INIT`/`BAUD`. La GUI conecta, reinicia la placa y renegocia la velocidad. Faltan
> la lectura de T/H/P, la adquisición periódica, el comando de configuración, el procesamiento
> y los paneles de la GUI; el plan está en [`TODO.md`](TODO.md).

El repositorio parte de la infraestructura de la Tarea 1
([`MFSaavedra/embeddedT1`](https://github.com/MFSaavedra/embeddedT1)), probada sobre la misma
placa: protocolo con checksum, enlace UART con cambio de velocidad en caliente, hilo serial
de la GUI, panel de conexión y sus pruebas.

## Estructura del repositorio

```
esp32_firmware/          Firmware ESP-IDF (C)
  CMakeLists.txt         Proyecto idf.py
  sdkconfig.defaults     Configuración base (target esp32, consola a 921600 baud)
  main/
    main.c               app_main: inicializa los módulos
    app_config.h         Constantes, pines I²C y valores por defecto del enunciado
    protocol.[ch]        Paquete "$payload*XX" + checksum XOR (espejo de gui_python/protocol.py)
    uart_link.[ch]       Driver UART0, envío de paquetes, recepción por líneas, cambio de baud
    commands.[ch]        Comandos de la GUI (CFG / INIT / BAUD) y respuestas ACK / ERR
    bme688.[ch]          Bus I²C y sensor BME688 (T, H, P; calefactor de gas apagado)
    sampler.[ch]         Configuración atómica y tarea de adquisición periódica
    temp_proc.[ch]       Media móvil temporal y detección de picos (C puro, probado en el PC)
gui_python/              Aplicación PyQt5
  main.py                Punto de entrada
  main_window.py         Ventana principal: conecta paneles, gráficos y puerto serie
  serial_worker.py       Hilo de lectura/escritura serial (pyserial + QThread)
  protocol.py            Paquetes y checksum (espejo de protocol.c)
  widgets/               Un archivo por panel: conexión, lecturas, gráficos
tests/                   Pruebas automáticas (pytest)
  firmware/              Pruebas en C del firmware, compiladas para el PC
docs/                    Enunciado y capturas de pantalla
requirements.txt         Dependencias Python
Doxyfile                 Documentación del código (Doxygen)
```

## Requisitos

| Componente | Versión |
|---|---|
| Tarjeta | ESP32 DevKit (target `esp32`, puente USB-serial CP2102) |
| Sensor | BME688 en módulo con interfaz I²C |
| Framework firmware | ESP-IDF **v5.5** (probado) o v6.1 |
| Python | 3.8+ |
| Librerías GUI | PyQt5, pyserial, pyqtgraph, numpy (`requirements.txt`) |

## Conexión física

> Pendiente de confirmar con el módulo que se use (dirección, pull-ups, pin CS).

| BME688 (módulo) | ESP32 | Notas |
|---|---|---|
| VCC / VIN | 3V3 | |
| GND | GND | |
| SDA | GPIO21 | `BME688_SDA_GPIO` en `app_config.h` |
| SCL | GPIO22 | `BME688_SCL_GPIO` en `app_config.h` |
| SDO / ADDR | GND → `0x76` · 3V3 → `0x77` | el firmware prueba `0x77` y luego `0x76` |
| CS (si existe) | 3V3 | en alto selecciona I²C |

GPIO21 y GPIO22 son los pines I²C habituales del ESP32 DevKit. Están libres en la placa y no
son pines de *strapping* (0, 2, 5, 12, 15), de la flash (6–11) ni de solo entrada (34–39). El
bus funciona a 100 kHz. Los módulos traen resistencias de pull-up, y el firmware habilita
además las internas del ESP32 como respaldo. Al arrancar, el monitor serial indica si
encontró el sensor:

```
I (…) bme688: BME688 found at 0x77 (chip id 0x61, variant 0x01)
```

## Compilación y carga del firmware

```bash
# 1. Activar ESP-IDF (según la instalación)
. $IDF_PATH/export.sh                 # o el script del instalador, p. ej. ~/.espressif/tools/activate_idf_v6.1.sh

# 2. Compilar
cd esp32_firmware
idf.py build

# 3. Cargar y abrir el monitor serial (Ctrl+] para salir)
idf.py -p /dev/ttyUSB0 flash monitor
```

Notas:

- En Linux el usuario debe pertenecer al grupo `dialout` para abrir `/dev/ttyUSB0`.
- El monitor de `idf.py` y la GUI **no pueden usar el puerto al mismo tiempo**: hay que cerrar
  el monitor antes de conectar desde la aplicación.
- Los cambios permanentes de configuración van en `sdkconfig.defaults` (`sdkconfig` está
  ignorado por git). Para regenerarlo: `rm sdkconfig && idf.py reconfigure`.
- La consola y el enlace funcionan a **921600 baud** (`LINK_BAUD` en `main/app_config.h` y
  `sdkconfig.defaults`).

## Ejecución de la aplicación

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python gui_python/main.py
```

## Pruebas automáticas

`pytest`, ejecutado desde la raíz del repositorio, corre todo `tests/`:

- el protocolo en Python y los mismos casos sobre `protocol.c` compilado para el PC (requiere
  `gcc`/`cc`; sin compilador esas pruebas se omiten);
- el hilo serial contra un puerto simulado (reinicio de la placa, cambio de velocidad);
- la máquina de estados de la renegociación de velocidad;
- los widgets de lecturas y gráficos.

Pendiente: media temporal y detección de picos sobre series conocidas (`tests/firmware/`).

## Uso

1. Conectar el ESP32 por USB, elegir el puerto (los adaptadores USB-serial aparecen primero,
   con su descripción) y pulsar **Conectar**. La GUI abre el puerto a 921600, reinicia la
   tarjeta (pulso en EN) y espera ~1 s antes de habilitar los controles. El selector de baud
   rate indica la velocidad deseada del enlace; si difiere de 921600, se renegocia en cuanto
   la conexión está lista.
2. Pulsar **Inicializar ESP32**. El firmware vuelve a la configuración por defecto (1 Hz,
   T/H/P, promedio y picos desactivados, W = 10 s, θ = 28,0 °C), responde `ACK` e inicia la
   adquisición.
3. _(pendiente: configuración de adquisición y procesamiento, lecturas, gráficos y eventos)_

La barra de estado muestra las respuestas del ESP32 y un contador de paquetes válidos y
rechazados.

## Protocolo de comunicación

Protocolo de texto, un paquete por línea, heredado de la Tarea 1 e implementado de forma
idéntica en `protocol.c` y `protocol.py`:

```
$<payload>*<XX>\n
```

- `payload`: campos separados por coma; el primero es el tipo de mensaje.
- `XX`: checksum, el XOR de todos los bytes del payload, en dos dígitos hexadecimales.
  Ejemplo: `INIT` → `'I'^'N'^'I'^'T'` = `0x1A` → `$INIT*1A`.
- Cualquier línea que no cumpla el formato o cuyo checksum no coincida se descarta y se
  cuenta (mensajes de arranque, `ESP_LOG`, bytes corruptos).

Los mensajes nuevos de la Tarea 2 usan campos `clave=valor`. El conjunto de variables cambia
de un paquete a otro según la selección, y así cada valor viaja etiquetado (el enunciado pide
que el promedio viaje "etiquetado como `temp_avg_c`").

> **BORRADOR.** Los campos de `CFG`, `SMP` y `PEAK` están por confirmar (`TODO.md`, ítem P1).
> `INIT` y `BAUD` ya funcionan; `CFG` responde hoy `ERR,NOTIMPL`.

### PC → ESP32 (comandos)

| Comando | Paquete | Respuesta |
|---|---|---|
| Configurar | `$CFG,sampling_hz=<0.5\|1\|2\|5>,variables=<T\|H\|P\|TH\|TP\|HP\|THP>,avg_enabled=<0\|1>,window_s=<5\|10\|30\|60>,peak_enabled=<0\|1>,threshold_c=<-40.0..85.0>*XX` | `$ACK,CFG,<configuración aplicada, mismas claves>*XX` o `$ERR,BADARG,<clave>*XX` |
| Inicializar | `$INIT*XX`: configuración por defecto e (re)inicio de la adquisición | `$ACK,INIT,<versión>*XX` |
| Cambiar velocidad | `$BAUD,<baud>*XX`: `115200`/`230400`/`460800`/`921600` | `$ACK,BAUD,<baud>*XX` (a la velocidad **anterior**) o `$ERR,BADARG*XX` |

`CFG` lleva siempre la configuración completa y se aplica de forma atómica: si un campo es
inválido se responde `ERR` y no cambia nada. Errores posibles: `BADFRAME` (formato o
checksum), `EMPTY`, `UNKNOWN` (tipo desconocido), `BADARG` (valor fuera de las opciones
permitidas) y `NOTIMPL` (comando aún no implementado).

### ESP32 → PC (datos y eventos)

| Mensaje | Paquete | Notas |
|---|---|---|
| Muestra | `$SMP,seq=<n>,t_ms=<ms>[,temperature_c=<°C>][,humidity_pct=<%HR>][,pressure_hpa=<hPa>][,temp_avg_c=<°C>,avg_window_complete=<0\|1>]*XX` | Solo las variables seleccionadas. El promedio viaja aunque T no esté seleccionada. `t_ms`: instante de la medición desde el arranque |
| Lectura fallida | `$SMP,seq=<n>,t_ms=<ms>,error=<código>*XX` | Sin valores: nunca se inventan |
| Pico | `$PEAK,t_ms=<ms>,peak_c=<°C>,threshold_c=<°C>*XX` | Un evento por máximo local; `t_ms` es el del pico |

Ejemplo equivalente al del enunciado (T y P seleccionadas, promedio y picos activos; los
checksums son reales):

```
PC → ESP32   $CFG,sampling_hz=2,variables=TP,avg_enabled=1,window_s=10,peak_enabled=1,threshold_c=28.0*5E
ESP32 → PC   $ACK,CFG,sampling_hz=2,variables=TP,avg_enabled=1,window_s=10,peak_enabled=1,threshold_c=28.0*3B
             $SMP,seq=145,t_ms=73210,temperature_c=26.40,pressure_hpa=1012.70,temp_avg_c=26.10,avg_window_complete=1*1D
             $PEAK,t_ms=75410,peak_c=28.70,threshold_c=28.0*53
PC → ESP32   $CFG,sampling_hz=3,variables=TP,avg_enabled=1,window_s=10,peak_enabled=1,threshold_c=28.0*5F
ESP32 → PC   $ERR,BADARG,sampling_hz*18
```

## Decisiones de diseño

### Heredadas de la Tarea 1 (siguen vigentes)

- **Velocidad del enlace.** El enlace arranca a **921600 baud** en ambos extremos
  (`LINK_BAUD` en el firmware, `DEFAULT_BAUD` en la GUI). En la Tarea 1 era necesario
  (3 ejes × 1000 Hz). En la Tarea 2 el peor caso es ~125 B por muestra a 5 Hz ≈ 6,3 kbaud,
  que cualquier velocidad soporta; se mantiene 921600 porque es la configuración validada con
  esta placa.
- **Cambio de velocidad en caliente.** El selector de baud de la GUI indica la velocidad a la
  que debe funcionar el enlace. La GUI envía `$BAUD,<baud>`; el firmware detiene la
  adquisición, responde *a la velocidad antigua*, espera a que se vacíe el buffer de
  transmisión y recién entonces conmuta. La GUI conmuta al recibir esa respuesta y envía
  `$INIT`, que confirma la velocidad y reanuda la adquisición. La velocidad nueva es
  provisional: si el firmware no recibe un paquete válido en 5 s (`LINK_BAUD_REVERT_MS`)
  vuelve a 921600, y la GUI hace lo mismo a los 8 s. El puerto se abre **siempre** a
  921600, porque la placa se reinicia al conectar y arranca a `LINK_BAUD`. Una selección
  distinta se aplica renegociando una vez establecida la conexión.
- **Reinicio explícito al conectar.** Abrir el puerto conmuta DTR/RTS de forma no
  controlada, y en Linux con el puente CP2102 eso dejaba al ESP32 colgado en la mayoría de
  las conexiones (1–4 útiles de cada 10). `SerialWorker` aplica la misma secuencia que
  `esptool` para un *hard reset*: DTR inactivo, RTS activo 100 ms, RTS inactivo. Solo
  habilita los controles tras `BOOT_WAIT_S` = 1 s, con lo que se logran 10 de 10 conexiones
  útiles.
- **Consola compartida.** UART0 transporta datos y logs. Los logs no empiezan con `$` y se
  descartan en la GUI y en el parser, y `uart_vfs_dev_use_driver()` evita que un log quede
  intercalado dentro de un paquete.
- **"Inicializar ESP32" como único punto de entrada.** La adquisición no arranca al
  encender: solo `$INIT` la inicia, tras restaurar la configuración por defecto y responder
  `ACK` *antes* del primer dato, de modo que la GUI se reinicia con el `ACK`. `$BAUD` la
  detiene. **Desconectar** solo cierra el puerto local.
- **Errores de comando.** `BADARG` cubre valores fuera de rango y campos mal formados;
  `BADFRAME` queda reservado a fallos de formato o checksum del paquete.

### Propias de la Tarea 2 (en curso; ver `TODO.md`)

- **Configuración atómica.** Toda la configuración (frecuencia, variables, promedio, picos)
  es una sola estructura (`sampler_cfg_t`). `sampler_set_config()` valida todos los campos
  antes de aplicar nada, de modo que un comando inválido no deja configuraciones a medias, y
  la GUI muestra solo lo que el ESP32 confirmó.
- **Temperatura siempre adquirida.** La selección de variables decide qué se *transmite*, no
  qué se mide: la temperatura alimenta el promedio y la detección de picos aunque no viaje.
- **Sin valores inventados.** Si la inicialización o una lectura falla, no se envía nada que
  parezca una medición.
- **Procesamiento en C puro.** `temp_proc.c` no depende de ESP-IDF, para probarlo en el PC
  con series conocidas.
- _Pendientes:_ driver del BME688 (sobremuestreo, filtro, tiempo de conversión), semántica
  exacta de la ventana del promedio, criterio de picos y su estrategia contra detecciones
  espurias.

## Pruebas obligatorias (sección 6 del enunciado)

| # | Prueba | Procedimiento | Resultado |
|---|---|---|---|
| 1 | Lecturas reales (T, H, P, unidades, cableado, frecuencia) | | pendiente |
| 2 | Siete combinaciones de variables | | pendiente |
| 3 | Cambio dinámico 1 Hz → 5 Hz sin reiniciar | | pendiente |
| 4 | Promedio: cambio de W y comparación con un cálculo de referencia | | pendiente |
| 5 | Picos: ajuste de θ y un único evento por máximo | | pendiente |
| 6 | Procesamiento con T oculta | | pendiente |
| 7 | Configuración inválida y desconexión/reconexión serial | | pendiente |

## Video de demostración

_(pendiente: enlace directo, verificado sin iniciar sesión)_

## Solución de problemas

| Síntoma | Causa / solución |
|---|---|
| `Permission denied: /dev/ttyUSB0` | `sudo usermod -aG dialout $USER` y volver a iniciar sesión |
| `Device or resource busy` | Otro programa (p. ej. `idf.py monitor`) tiene el puerto abierto |
| El contador de paquetes rechazados sube al conectar | Normal: es la salida del bootloader tras el reinicio que hace la GUI al conectar |
| "Conectado", pero **Inicializar ESP32** no responde y los contadores no se mueven | Puerto equivocado: un puerto heredado como `/dev/ttyS0` o `COM1` se abre sin error y no responde. Elegir la entrada con la descripción del adaptador USB (CP2102) |
| "Conectado" a `/dev/ttyUSB0`, rechazadas subió, pero **Inicializar ESP32** no responde | El chip quedó colgado por una conmutación de DTR/RTS fuera de la GUI (p. ej. al cerrar `idf.py monitor`). **Desconectar** y **Conectar** lo reinicia; si persiste, pulsar el botón **EN** de la placa |
| "El ESP32 no respondió al cambio de velocidad" | El puente USB-serial no sostiene esa velocidad. Ambos extremos ya volvieron a 921600; pulsar **Inicializar ESP32** |
| Tras cambiar la velocidad, `idf.py monitor` muestra basura | El monitor sigue a `CONFIG_ESP_CONSOLE_UART_BAUDRATE`; abrirlo con `idf.py monitor -b <baud>` |
| Monitor: `no sensor at 0x77 or 0x76 (ESP_ERR_NOT_FOUND)` | El sensor no responde: revisar alimentación, SDA/SCL (GPIO21/22) y el pin SDO |
| Monitor: `… (ESP_ERR_TIMEOUT)` al buscar el sensor | Bus I²C trabado, normalmente por falta de pull-ups o SDA/SCL invertidos |
