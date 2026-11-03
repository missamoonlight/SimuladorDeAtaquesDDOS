# Inventario SSH

Aplicación de escritorio en Python para conectarse por SSH a un servidor Linux, consultar sus especificaciones y guardar el resultado en un archivo `.txt` en el dispositivo anfitrión.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Ejecución

```powershell
python main.py
```

Completa servidor/IP, puerto, usuario y contraseña, o selecciona una clave privada SSH. Pulsa **Conectar y obtener información**. Cuando el informe esté disponible, pulsa **Cargar al dispositivo anfitrión** y elige dónde guardar el `.txt`.

La contraseña solo se utiliza durante la conexión y no se escribe en el informe.

## Requisitos del servidor

# Simulador de Resiliencia y Capacidad de Servidores

Aplicación académica de escritorio para estudiar capacidad y resiliencia mediante un perfil SSH de solo lectura y un modelo matemático ejecutado completamente en el equipo anfitrión.

## Seguridad y alcance

La aplicación **no es un generador DDoS**. No usa `socket`, `requests`, `urllib`, `scapy`, `ping`, `curl`, `wget`, `iperf`, `ab` ni `wrk` para generar carga. El servidor remoto solo recibe comandos fijos de diagnóstico: `uname`, `hostname`, `/proc`, `lscpu`, `free`, `df`, `lsblk` e `ip`. No se aceptan comandos escritos por el usuario.

La conexión carga las claves del `known_hosts` del usuario y rechaza hosts desconocidos. Verifica la huella del servidor por un canal confiable y agrégala a `known_hosts` antes de conectar. La contraseña solo vive durante la conexión, se borra de la interfaz al terminar y nunca se guarda en perfiles, reportes o logs.

## Instalación y ejecución

Python 3.11+:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Dependencias directas: `paramiko` para SSH y `matplotlib` para gráficas. Tkinter normalmente viene con Python para Windows; en Linux puede requerir el paquete `python3-tk`.

## Flujo de uso

1. En **CONEXIÓN**, usa `CONECTAR / OBTENER PERFIL` con un host autorizado y un usuario con permisos de lectura.
2. Revisa el perfil en **PERFIL** y guárdalo como JSON y TXT.
3. Usa `CONTINUAR A SIMULACIÓN` para configurar usuarios, duración, requests, bytes, escenario y mitigación.
4. Ejecuta la simulación local. Las gráficas muestran tráfico, CPU, RAM, saturación y usuarios.
5. Exporta CSV o genera el reporte TXT en `data/reports/`.

## Modo demostración e importar perfiles

`MODO DEMOSTRACIÓN` carga un perfil ficticio de 4 CPU, 8 GB de RAM y red de 1 Gbps sin conectarse a ningún servidor. También puedes cargar un `.json` creado previamente desde `CARGAR PERFIL JSON`.

Los perfiles nuevos se guardan en `data/profiles/`; los reportes y CSV en `data/reports/`; el log técnico en `logs/app.log`.

## Modelo

El modelo convierte el perfil en capacidades estimadas de CPU, memoria y red. El tráfico se calcula con:

`usuarios x requests_por_usuario x (bytes_request + bytes_response) x 8 / 1,000,000`

La simulación interactiva permite explorar escenarios de manera local. Los botones **PILOTAJE ×10** y **LOTE FORMAL ×30** ejecutan, de forma independiente y reproducible, el diseño factorial descrito a continuación; las corridas experimentales no abren conexiones SSH.

## Experimento factorial del protocolo

El ejecutor usa el perfil medido (P1) y crea P2 derivado, inicialmente con CPU lógica x4 y RAM x2. Si P2 conserva el cuello de botella de P1, escala ese recurso hasta que el cuello de botella sea distinto; ambos perfiles derivados se guardan en la configuración JSON para revisión. Combina 5 niveles de usuarios (100, 500, 1,000, 5,000 y 10,000), 4 escenarios (Gradual, Súbito, Pulsado y Spike), 5 estrategias (Ninguna, Limitación de tasa, Filtrado, Escalamiento y CAPTCHA) y 2 tiempos de confirmación (5 y 20 s): 400 condiciones con carga y 2 controles, 402 en total. Cada condición se repite 30 veces (12,060 ejecuciones). La interfaz ofrece un pilotaje de 10 repeticiones y el lote formal de 30; revisa el perfil derivado y calibra `ProtocolParameters` durante el pilotaje antes de lanzar la corrida formal.

## Correspondencia con el cronograma de desarrollo

El motor formal está dividido en los cuatro módulos del cronograma y `ProtocolSimulation` solo los coordina:

| Hito | Componente | Responsabilidad |
|---|---|---|
| Tráfico normal | `app/simulation/normal_traffic.py` | Calcula usuarios y demanda legítimos de referencia. |
| Tráfico malicioso (bots) | `app/simulation/malicious_traffic.py` | Genera bots virtuales con patrones gradual, súbito, pulsado y spike; aplica ruido reproducible. |
| Servidor simulado | `app/simulation/simulated_server.py` | Calcula capacidades por recurso, inercia, saturación, solicitudes atendidas y estados. |
| Detección y mitigación | `app/simulation/detection_mitigation.py` | Confirma umbral y aplica las cuatro mitigaciones del diseño factorial. |

Los niveles del diseño y parámetros se mantienen en `experiment_design.py` y `protocol_parameters.py`. El motor integrado anterior sigue disponible como explorador de escritorio; el lote factorial usa estos módulos y las condiciones exactas del protocolo.

Cada ejecución usa pasos de 1 s y fases de 60 s normal, 120 s de ataque simulado y 120 s de recuperación. El modelo usa `C_cpu = h / 0.005`, `C_ram = RAM_disponible / (0.05 × 0.5)`, `C_red = Mbps × 1,000,000 / 160,000` y `C_con = 256 × h / 0.05`; la capacidad estimada es el mínimo de las cuatro capacidades. La utilización evoluciona con inercia `u(t+1) = u(t) + (ρ(t) - u(t))/10`. El ruido multiplicativo normal tiene desviación de 5% y se limita a ±15%.

La demanda virtual es `D(t) = 0.2 × [U_n + U_a(t) × φ]`, donde `U_n` equivale al 20% de la capacidad estimada, `U_a(t)` es el pico de usuarios del factor F2 por la forma temporal del escenario y `φ` es el efecto de la estrategia (1 sin mitigación). La simulación nunca convierte esa demanda en paquetes ni solicitudes de red.

En los 120 segundos de ataque, `g(t)` es `t/120` para Gradual, `1` para Súbito, alterna `1` y `0.25` en pulsos de 10 s para Pulsado, y vale `1` durante 10 s seguido de `0.25` para Spike. La detección se registra como segundos desde el inicio del ataque; la recuperación, como segundos desde el fin del ataque. La bitácora marca las fases `DETECTION` y `MITIGATION` además de las fases normal, ataque y recuperación.

Limitación de tasa aplica φ=0.5, filtrado φ=0.3, CAPTCHA φ=0.4 y escalamiento multiplica las cuatro capacidades por 2. La confirmación de detección requiere saturación ≥70% por 5 o 20 s consecutivos. Los estados son NORMAL (<70%), HIGH_LOAD (70–<90%), SATURATION (≥90% o sobrecapacidad por menos de 10 s) y SIMULATED_COLLAPSE (sobrecapacidad durante al menos 10 s). La recuperación requiere saturación <70% durante 10 s consecutivos y se censura al terminar los 120 s de observación.

La carpeta `data/reports/` recibe tres artefactos con sello de tiempo: `experimento_resumen_*.csv` (una fila por corrida), `experimento_bitacora_*.csv.gz` (la bitácora CSV por segundo comprimida; 3.6 millones de filas en el experimento formal) y `experimento_configuracion_*.json` (factores, parámetros y perfiles P1/P2). Si el perfil no incluye velocidad de interfaz, el modelo declara y registra el valor de referencia de 100 Mbps; debe verificarse o sustituirse y congelarse durante el pilotaje. P2 y los coeficientes son supuestos iniciales del protocolo y deben registrarse/calibrarse en el pilotaje antes de interpretar resultados.

También se puede ejecutar desde terminal: `python -m app.experiment_runner --profile data/profiles/perfil.json`. Para un piloto de 10 repeticiones, agrega `--repetitions 10`; el experimento formal usa 30 por defecto. Si no se indica `--profile`, se usa el perfil demostrativo.

Todos los resultados son estimaciones. No sustituyen una prueba de carga controlada y autorizada.

## Mitigaciones del explorador interactivo

El simulador permite seleccionar individualmente o combinar: Rate Limiting, Rate-Based Ban, Blacklisting, CAPTCHA/Challenge, WAF de capa 7, Bot Management, Auto Scaling, CDN/Caching, Load Balancing y Edge/Scrubbing. También incluye presets de protección básica, web, avanzada, alta disponibilidad y defensa multicapa.

Estas capas ampliadas pertenecen al explorador interactivo. El lote factorial del protocolo usa exclusivamente sus cinco niveles: ninguna, limitación de tasa, filtrado, escalamiento y CAPTCHA.

Cada capa tiene una función distinta. Rate Limiting aplica una capacidad máxima de requests/s; Rate-Based Ban usa evaluaciones consecutivas, fuentes abstractas y expiración; Blacklisting bloquea usuarios sospechosos; CAPTCHA usa una probabilidad de resolución y latencia adicional; WAF separa tráfico legítimo, sospechoso y malicioso e incorpora falsos positivos/negativos; Bot Management clasifica comportamiento sintético; Auto Scaling añade instancias solo por intervalos cuando la carga supera capacidad; CDN atiende `requests_generadas x cache_hit_ratio` sin llegar al origen; Load Balancing distribuye capacidad modelada; Edge filtra tráfico antes del origen con capacidad y porcentaje configurables.

El orden conceptual de la combinación es Edge, CDN, WAF, Bot Management, Ban/Blacklist/Challenge, Rate Limiting, Auto Scaling y Load Balancing. Las métricas distinguen tráfico generado, tráfico al origen, requests limitadas, bloqueadas, cacheadas y procesadas, además de usuarios legítimos preservados y falsos positivos.

La detección usa una línea base de requests normales, desviación de carga, saturación y una ventana de evaluaciones consecutivas; no depende únicamente de `saturation > 70%`. La CPU, RAM, red y capacidad de instancias parten del `ServerProfile` seleccionado.

## Limitaciones del modelo

Las fuentes, bots, clientes, distribución de balanceo, resolución de challenges y comportamiento de WAF son entidades abstractas generadas localmente. No representan IPs reales, reglas reales ni una infraestructura cloud concreta. Las capacidades son estimaciones matemáticas parametrizadas; P2 también es un perfil derivado. Los resultados describen el modelo, no el rendimiento probado de un servidor real. El simulador no sustituye una prueba de carga autorizada ni una solución profesional de protección DDoS.

## Estructura

```text
main.py
app/models/       dataclasses de perfil y configuración
app/ssh/          conexión segura y comandos fijos
app/profiler/     parseo de diagnósticos
app/simulation/   tráfico normal y bot, servidor virtual, detección y mitigación
app/reports/      TXT, JSON y CSV
app/gui/          vistas Tkinter y gráficas Matplotlib
data/profiles/    perfiles exportados
data/reports/     reportes y resultados
logs/             app.log
```
