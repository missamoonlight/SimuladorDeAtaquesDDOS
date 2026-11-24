# Manual de usuario: Simulador de resiliencia y capacidad de servidores

Este manual explica cómo instalar y utilizar el simulador, qué significa cada opción y cómo leer los resultados. No necesitas saber programación ni administración de redes para seguir el recorrido de demostración.

## 1. ¿Qué hace el sistema?

El programa crea un perfil de un servidor Linux y permite estudiar, mediante un modelo matemático local, cómo podría responder ante distintas cantidades y patrones de solicitudes. Puedes observar saturación y uso estimado de CPU y RAM, evaluar las capas seleccionadas y registrar detección y recuperación.

La aplicación ofrece el **explorador interactivo**, donde configuras un escenario individual, ejecutas la simulación y ves las gráficas en vivo. La matriz factorial del protocolo se conserva como herramienta técnica opcional de línea de comandos.

**El sistema no genera ataques, paquetes ni solicitudes contra el servidor real.** SSH solo recopila diagnósticos de lectura; los bots y su tráfico existen únicamente como valores del modelo. Los resultados son estimaciones matemáticas y no mediciones obtenidas al cargar un servidor real.

## 2. Requisitos e instalación

Necesitas Python 3.10 o posterior, Tkinter y las dependencias de `requirements.txt`. Para crear un perfil mediante SSH también necesitas acceso a un servidor Linux. Para aprender o explorar, basta con el perfil de demostración.

Abre una terminal en la carpeta del proyecto.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python principal.py
```

**Linux o macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python principal.py
```

En algunas distribuciones Linux Tkinter se instala aparte (por ejemplo, mediante el paquete `python3-tk`). Si `python` no existe, usa `python3`. Para volver a abrir el programa, activa el entorno virtual y ejecuta `python principal.py` desde la carpeta del proyecto.

## 3. El flujo de trabajo

La ventana contiene dos pestañas. **Conexión y perfil** reúne ambas secciones en dos columnas: configura la conexión o carga un perfil en el lado izquierdo y revisa sus datos en el derecho. **Simulación** se habilita al obtener o cargar un perfil.

### 3.1 Conexión: elegir un perfil

Tienes tres opciones:

1. **Modo demostración:** carga un servidor ficticio y no realiza conexiones. Es la mejor opción para comenzar.
2. **Cargar perfil JSON:** importa un perfil guardado anteriormente; tampoco se conecta por SSH.
3. **Conectar / Obtener perfil:** consulta un servidor Linux por SSH. Completa host o dirección IP, puerto (normalmente `22`), usuario y método de autenticación. Si eliges contraseña, introdúcela en el campo correspondiente; si eliges clave, examina y selecciona el archivo de clave privada.

La conexión ejecuta comandos de diagnóstico fijos para recoger información del sistema, CPU, memoria, discos y red. No permite enviar comandos arbitrarios. El **método de autenticación** elige entre la contraseña de la cuenta o una clave SSH privada. Si eliges clave, selecciona el archivo privado cuya clave pública correspondiente está autorizada en el servidor. La credencial se conserva únicamente en la memoria de la aplicación mientras siga abierta para que el usuario pueda solicitar telemetría SSH en vivo; no se escribe en el perfil ni en disco. Al cerrar la aplicación desaparece de memoria.

Por seguridad, el programa rechaza hosts que no estén reconocidos en `known_hosts`. Antes de conectar por primera vez, verifica la huella del servidor por un canal confiable y registra su identidad en `known_hosts`. No aceptes una huella que no hayas verificado. Si falla la conexión, comprueba también el host, puerto, usuario y credenciales.

### 3.2 Perfil: revisar y guardar

El perfil es una captura tomada al conectar por SSH; no se actualiza automáticamente. “RAM libre” es memoria completamente sin uso y “RAM disponible” es la estimación de memoria que el sistema puede asignar sin recurrir a swap. El estimador utiliza la memoria disponible, no calcula ese valor como RAM total menos RAM usada.

Al obtener el perfil por SSH, las credenciales se conservan solo en memoria durante la sesión de la aplicación para permitir **Telemetría SSH**. Desde la simulación puedes abrir una ventana independiente que consulta, cada 2 segundos, CPU, RAM disponible/libre, swap, tráfico RX/TX observado, procesos con mayor uso, PID, cantidad de hilos y sockets en escucha. La consulta es de solo lectura, no genera solicitudes al servicio y puede cerrarse en cualquier momento. Los perfiles de demostración e importados no habilitan esa función. La telemetría real se mantiene separada de las curvas estimadas del modelo.

La pestaña **Real vs simulación** del monitor compara CPU, RAM y RX/TX observados por SSH con las últimas estimaciones del modelo, y presenta la serie de solicitudes simuladas; las solicitudes maliciosas se sombrean en rojo. La telemetría genérica no puede identificar solicitudes legítimas o maliciosas porque el simulador no las envía al servicio. Procesos y puertos son datos reales del sistema; carga y solicitudes de la simulación son estimaciones locales.

El botón **Ruta al servidor** ejecuta `tracert`, `traceroute` o `tracepath` desde el equipo donde corre la aplicación hacia el host SSH. Es un diagnóstico opcional de conectividad: no representa las rutas de los clientes atacantes ni mide capacidad del servidor. Los saltos pueden no responder a estas sondas.

El panel **Perfil**, a la derecha de Conexión, presenta el resumen utilizado como referencia y una tabla con discos e interfaces de red. CPU y memoria disponible alimentan la estimación de capacidad; la velocidad de enlace se muestra como contexto y no limita la saturación calculada. “Disponible” no es lo mismo que “libre”.

- **Guardar perfil:** elige una carpeta. Se crean un archivo JSON (para importar más tarde) y un TXT (para leerlo fácilmente).
- **Continuar a simulación:** abre Simulación con el perfil actual.

Si el perfil tiene valores incompletos o poco representativos, los resultados también pueden serlo. La opción de demostración es ficticia y no describe un equipo real.

## 4. Explorador interactivo

Este modo se encuentra en la pestaña **Simulación** y permite ejecutar una condición a la vez. Al abrirla, puedes configurar el escenario; al pulsar **Iniciar exploración**, aparecen las gráficas y se actualizan durante la ejecución.

### 4.1 Parámetros de carga

El selector **Demanda legítima** modela variación normal, una hora pico o un evento de alta concurrencia. Así se puede observar si un aumento legítimo previsto se distingue de la carga atacante. El servicio seleccionado también ajusta los costos matemáticos por solicitud y sesión para la estimación; el programa no detecta qué aplicación real está instalada ni qué proceso escucha en el puerto indicado.

Los campos están distribuidos en secciones para facilitar la lectura:

| Campo | Explicación |
|---|---|
| **Usuarios iniciales** | Usuarios virtuales al comienzo. |
| **Carga maxima estimada** | Se estima a partir de CPU, RAM y solicitudes por usuario; es una referencia del modelo, no una medicion real. |
| **Duración** | Tiempo de la exploración. Cada segundo simulado tarda un segundo real. |
| **Patrón del ataque** | Describe cómo evoluciona la carga atacante sobre una línea base legítima estable: gradual, repentina, pulsante, spike o personalizada. No selecciona un protocolo de red. La rampa del patron Repentino se sortea internamente entre 1 y 10 segundos, limitada por la duracion; no se configura manualmente. |
| **Solicitudes** | El modelo las genera aleatoriamente a partir de los usuarios; usa una actividad media interna de 0.3 a 0.7 solicitudes por usuario por segundo y variaciones de llegada por segundo; los usuarios atacantes pueden generar entre 1.5 y 3 veces más solicitudes. La semilla fija permite repetir la serie. |
| **Variacion entre corridas** | Ninguna, baja, media o alta; altera usuarios, solicitudes y momento de inicio. |
| **Opciones avanzadas** | Latencia objetivo, servicio, puerto, protocolo, hora inicial y semilla manual. Si la semilla queda vacia, se genera automaticamente y se guarda con el resultado. |
| **Detección y mitigación** | El umbral y la ventana de anomalía están junto a las capas de defensa. |
| **Tiempo de detección** | No es una entrada: depende del inicio y evolución del ataque, el umbral y la ventana de anomalía, y una demora aleatoria interna de 1 a 5 segundos. Una semilla fija permite repetir el resultado. |
Si aparece un mensaje de configuracion invalida, corrige los valores senalados. La duracion debe ser positiva y los usuarios iniciales no pueden superar la carga maxima estimada.

### 4.2 Escenarios

- **Gradual:** los usuarios atacantes crecen suavemente desde la linea base hasta el maximo.
- **Repentino:** aumentan hasta el maximo en el tiempo de rampa configurado.
- **Pulsante:** el volumen atacante sube y baja en ciclos, acercandose a la linea base entre pulsos.
- **Spike:** produce un pico breve y vuelve hacia la linea base.
- **Personalizado:** aumenta progresivamente hasta el maximo.

Son patrones matemáticos de carga simulada, no bots o personas reales.

### 4.3 Capas de mitigación

Marca una o varias capas. Si no marcas ninguna, se calcula el escenario sin defensa activa.

| Capa | Qué representa en el modelo |
|---|---|
| **Rate Limiting** | Cuenta solicitudes por origen y segundo; limita el exceso antes de la cola del servidor. |
| **Rate-Based Ban** | Observa la tasa media de las fuentes maliciosas y las bloquea temporalmente si rebasa el umbral en evaluaciones consecutivas. |
| **Blacklisting** | Incorpora fuentes sospechosas gradualmente después de detectar el ataque y las bloquea durante un tiempo. |
| **CAPTCHA / Challenge** | Desafía una parte del tráfico sospechoso; las solicitudes que no superan el reto se descartan. |
| **WAF / Filtrado L7** | Inspecciona solicitudes de aplicación, bloquea parte de los patrones maliciosos y contempla falsos positivos, latencia y coste de inspección. |
| **Bot Management** | Clasifica el tráfico malicioso estimado y bloquea o desafía porciones diferentes de ese tráfico. |
| **Auto Scaling** | Agrega capacidad al superar el objetivo de carga, con demora de arranque, límite máximo y reducción después de un periodo de carga baja. |
| **CDN / Caching** | Sirve desde caché solo una parte estimada del contenido cacheable; las solicitudes dinámicas y de base de datos llegan al origen. |
| **Load Balancing** | Reparte solicitudes entre los servidores configurados según el algoritmo elegido; no simula comprobaciones reales de salud ni conexiones activas. |
| **Edge / Scrubbing** | Filtra una proporción del tráfico malicioso antes de que llegue a la aplicación. |

Las capas preventivas seleccionadas (límite por origen, WAF, gestión de bots, retos, CDN, balanceo y filtrado perimetral) pueden actuar desde el inicio. El blacklist espera a que se confirme la anomalía y el Rate-Based Ban responde a su propio umbral y ventana. El autoescalado reacciona al nivel de carga. Los campos **Límite req/s por origen**, **Cache hit %**, **Edge filtrado %** y **Ventana anomalía** ajustan valores del modelo. Los porcentajes deben estar entre 0 y 100.

Estas capas son aproximaciones educativas: el filtrado por origen, el comportamiento del caché y los umbrales reales dependen de la configuración, el servicio, el proveedor y el tráfico histórico. El modelo separa las solicitudes legítimas y maliciosas para aplicar acciones en etapas; genera solicitudes por cliente hasta 5,000 clientes y agrupa cargas mayores. No implementa firmas, reputación IP, reglas WAF ni infraestructura distribuida real.

### 4.4 Presets

Al elegir un preset en la lista, sus capas se marcan automáticamente. Después puedes cambiar las casillas manualmente:

- **Protección básica:** Rate Limiting.
- **Protección web:** WAF, Rate Limiting y CAPTCHA.
- **Protección avanzada:** Edge, WAF, Bot Management y Rate Limiting.
- **Alta disponibilidad:** Edge, CDN, Load Balancing y Auto Scaling.
- **Defensa multicapa:** todas las capas.

El preset solo cambia las opciones del modelo. No instala ni configura defensas en servidores reales.

### 4.5 Ejecutar y controlar

1. Confirma que el perfil sea el que deseas estudiar.
2. Ajusta los parametros en Usuarios y duracion, Solicitudes y variacion, y Mitigacion.
3. Elige un escenario y sus capas de defensa. Al elegir un preset, se marcan automáticamente las capas correspondientes.
4. Pulsa **Iniciar exploracion**. Los parametros desaparecen y se muestran cuatro graficas, el estado y el avance.

5. **Pausar** detiene temporalmente la ejecución; el mismo botón permite continuar.
6. **Detener** termina antes de la duración prevista. El resultado incluye solo las muestras recogidas hasta ese momento.
7. **Reiniciar** limpia la ejecución y regresa al explorador para configurar otra.
8. **Volver a configuracion** permite regresar a los parametros sin cerrar la pestana.

Las graficas muestran demanda y respuesta en solicitudes por segundo; CPU y RAM como porcentaje; consumo estimado de red de entrada y salida en Mbps; y saturacion con umbrales y marcas de deteccion, mitigacion y recuperacion. El consumo de red se estima con tamanos promedio por servicio y no limita la capacidad ni la saturacion del servidor.

Desde el dashboard final puedes guardar un reporte TXT, exportar la serie por segundo y el detalle horario a CSV, o generar un PDF con resumen y las cuatro gráficas. Los valores de CPU, RAM y saturación de esos reportes son estimaciones del modelo local.

El dashboard y el reporte incluyen una conclusión de aptitud para el escenario simulado: menos de 50% indica estado estable; 50–74% carga alta; 75–89% cerca del límite; y desde 90% sobrecarga crítica. Solo se declara **no apto para este escenario** si la saturación llega a 90% o más y además se registran solicitudes rechazadas por cola llena. Al llegar a 100% sin rechazos, se indica que se alcanzó el límite modelado, sin afirmar una caída.

## 5. Matriz factorial (herramienta técnica)

La matriz factorial se ejecuta por separado desde la terminal y no forma parte de la ventana del explorador. Puedes usar un perfil JSON propio o el perfil de demostración:

```bash
python -m aplicacion.ejecutor_experimental --repetitions 1
```

El comando guarda un resumen CSV, una bitácora comprimida y la configuración utilizada en `datos/reportes/`. La cantidad de repeticiones determina el volumen de cómputo; el modelo es matemático y no genera tráfico hacia un servidor real.

## 6. Archivos y resultados guardados

Por defecto, el programa usa estas carpetas dentro del proyecto:

- `datos/perfiles/`: carpeta del proyecto preparada para perfiles; al guardar desde el panel Perfil, el usuario elige dónde crear los archivos.
- `datos/reportes/`: reportes TXT/PDF y archivos de resultados CSV.
- `registros/app.log`: registro técnico de la aplicación.

Al guardar manualmente un perfil desde Perfil puedes elegir otra carpeta. Los nombres de los reportes y resultados incluyen fecha y hora.

## 7. Términos básicos

- **req/s:** solicitudes virtuales por segundo.
- **Mbps:** megabits por segundo; en la grafica de red se muestran como consumo estimado de entrada y salida.
- **P1:** perfil seleccionado como primer servidor modelado.
- **P2:** perfil derivado de P1 para una comparación de capacidad según los supuestos del protocolo.
- **Demanda atendida:** proporción de las solicitudes virtuales que el modelo calcula como servidas.
- **Censura de recuperación:** no se observó recuperación durante la ventana disponible; solo se sabe que tardaría más que el tiempo observado.
- **Semilla:** valor que permite repetir la misma variación aleatoria.

Las capacidades dependen del perfil, tamaños de solicitud y respuesta, y coeficientes matemáticos. Para comparar escenarios, mantén iguales los demás valores y cambia solo los factores que quieras estudiar.

## 8. Buenas prácticas

1. Familiarízate con la aplicación usando el perfil de demostración.
2. Conserva una copia del perfil utilizado y anota su procedencia.
3. Revisa datos de CPU, memoria y red antes de experimentar.
4. Cambia pocos parámetros por comparación para poder explicar el resultado.
5. Conserva el perfil y la configuración de cada escenario que quieras comparar.
6. Separa en tus informes los valores medidos de los supuestos o derivados.
7. Describe los resultados como comportamiento del modelo; no como prueba de caída, ataque o capacidad real del servidor.
8. No compartas contraseñas, claves privadas ni datos sensibles.

## 9. Solución de problemas

| Problema | Qué revisar |
|---|---|
| No abre la ventana | Confirma Python y Tkinter. En Linux puede faltar `python3-tk`. |
| Falta una biblioteca | Activa el entorno virtual e instala con `python -m pip install -r requirements.txt`. |
| SSH rechaza la conexión | Comprueba host, puerto, usuario y método de autenticación. |
| Host SSH desconocido | Verifica su huella por un canal confiable y añádela a `known_hosts`. |
| No carga el perfil JSON | Usa un archivo JSON exportado por el sistema y comprueba que no esté incompleto. |
| No se puede exportar | Ejecuta una simulación y confirma que haya muestras. |
| No hay detección o recuperación | Puede que no se alcanzara el umbral o que faltara tiempo de observación; revisa las gráficas y los datos. |
| El experimento tarda | Procesa miles de corridas. Observa el avance y no cierres la aplicación. |

## 10. Checklist del cronograma

Los cuatro módulos del cronograma están implementados en el simulador:

- **Módulo de tráfico normal — implementado en** [`aplicacion/simulación/trafico_normal.py`](aplicacion/simulación/trafico_normal.py): define el nivel de usuarios y la demanda legítima de referencia.
- **Módulo de tráfico malicioso (bots) — implementado en** [`aplicacion/simulación/trafico_malicioso.py`](aplicacion/simulación/trafico_malicioso.py): genera la carga virtual de bots según el patrón y nivel definidos.
- **Módulo del servidor simulado — implementado en** [`aplicacion/simulación/servidor_simulado.py`](aplicacion/simulación/servidor_simulado.py): calcula capacidades, utilización, saturación, solicitudes atendidas y estado del servidor modelado.
- **Módulo de detección y mitigación — implementado en** [`aplicacion/simulación/deteccion_mitigacion.py`](aplicacion/simulación/deteccion_mitigacion.py): aplica la regla de detección y los efectos matemáticos de las estrategias del protocolo.

La coordinación de estos módulos durante cada segundo de las corridas factoriales se encuentra en [`aplicacion/simulación/modelo_protocolo.py`](aplicacion/simulación/modelo_protocolo.py). El motor que organiza las condiciones y guarda sus resultados está en [`aplicacion/ejecutor_experimental.py`](aplicacion/ejecutor_experimental.py).

## 11. Estructura del proyecto

```text
principal.py                         Inicio de la aplicación
aplicacion/
  interfaz/                          Vistas de la aplicacion
  modelos/                           Perfiles y configuración
  perfilador/                        Interpretación de diagnósticos
  conexion_ssh/                      Consulta SSH de solo lectura
  simulación/                        Modelos de carga, servidor y mitigación
  reportes/                          Exportación de perfiles y resultados
  ejecutor_experimental.py           Matriz factorial del protocolo
pruebas/                              Pruebas automatizadas
datos/
  perfiles/                           Perfiles guardados
  reportes/                           Reportes y resultados
registros/                            Registro técnico
```
