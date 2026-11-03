# Manual de usuario: Simulador de resiliencia y capacidad de servidores

Este manual explica cómo instalar y utilizar el simulador, qué significa cada opción y cómo leer los resultados. No necesitas saber programación ni administración de redes para seguir el recorrido de demostración.

## 1. ¿Qué hace el sistema?

El programa crea un perfil de un servidor Linux y permite estudiar, mediante un modelo matemático local, cómo podría responder ante distintas cantidades y patrones de solicitudes. Puedes observar saturación y uso estimado de CPU y RAM, comparar mitigaciones y registrar detección y recuperación.

Hay dos modos:

- **Explorador interactivo:** permite configurar y ejecutar un escenario individual, ver las gráficas en vivo y abrir un dashboard de resultados.
- **Experimento factorial del protocolo:** ejecuta una matriz fija de condiciones repetidas y genera resúmenes y bitácoras para análisis académico. Incluye pilotaje y lote formal.

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

La ventana contiene tres pestañas: **Conexión**, **Perfil** y **Simulación**. Primero obtén o carga un perfil, revísalo y luego continúa a la simulación.

### 3.1 Conexión: elegir un perfil

Tienes tres opciones:

1. **Modo demostración:** carga un servidor ficticio y no realiza conexiones. Es la mejor opción para comenzar.
2. **Cargar perfil JSON:** importa un perfil guardado anteriormente; tampoco se conecta por SSH.
3. **Conectar / Obtener perfil:** consulta un servidor Linux por SSH. Completa host o dirección IP, puerto (normalmente `22`), usuario y método de autenticación. Si eliges contraseña, introdúcela en el campo correspondiente; si eliges clave, examina y selecciona el archivo de clave privada.

La conexión ejecuta comandos de diagnóstico fijos para recoger información del sistema, CPU, memoria, discos y red. No permite enviar comandos arbitrarios. La contraseña solo se utiliza durante la conexión y no se guarda en el perfil.

Por seguridad, el programa rechaza hosts que no estén reconocidos en `known_hosts`. Antes de conectar por primera vez, verifica la huella del servidor por un canal confiable y registra su identidad en `known_hosts`. No aceptes una huella que no hayas verificado. Si falla la conexión, comprueba también el host, puerto, usuario y credenciales.

### 3.2 Perfil: revisar y guardar

La pestaña **Perfil** presenta el resumen que utilizará el modelo y una tabla con discos e interfaces de red. Revisa especialmente CPU, memoria disponible y velocidad de red: afectan las estimaciones de capacidad.

- **Guardar perfil:** elige una carpeta. Se crean un archivo JSON (para importar más tarde) y un TXT (para leerlo fácilmente).
- **Volver:** regresa a Conexión.
- **Continuar a simulación:** abre Simulación con el perfil actual.

Si el perfil tiene valores incompletos o poco representativos, los resultados también pueden serlo. La opción de demostración es ficticia y no describe un equipo real.

## 4. Explorador interactivo

Este modo se encuentra en la pestaña **Simulación** y permite ejecutar una condición a la vez. Los botones de arriba **Pilotaje ×10** y **Lote formal ×30** pertenecen al experimento factorial, no al explorador.

### 4.1 Parámetros de carga

Los campos de la izquierda controlan la demanda virtual:

| Campo | Explicación |
|---|---|
| **Usuarios iniciales** | Usuarios virtuales al comienzo. No puede superar el máximo. |
| **Usuarios máximos** | Límite al que puede llegar la curva de usuarios. |
| **Duración (s)** | Tiempo total simulado. |
| **Intensidad base (req/s)** | Intensidad base de solicitudes. Si es cero, la demanda se calcula a partir de usuarios y solicitudes por usuario. |
| **Inicio ataque (s)** | Tiempo de referencia de la fase normal antes del aumento de carga. |
| **Tiempo detección (s)** | Demora configurada antes de abrir la ventana de detección del explorador. |
| **Ancho banda Mbps (0=perfil)** | Ancho de banda empleado por el modelo. Cero significa usar el valor derivado del perfil. |
| **Requests / usuario / s** | Solicitudes virtuales por usuario por segundo. |
| **Bytes / request** y **Bytes / response** | Tamaño estimado de solicitud y respuesta; afectan el tráfico calculado. |
| **Latencia objetivo (ms)** | Referencia para la latencia estimada. |
| **Umbral anomalía %** | Nivel a partir del cual el modelo puede considerar anómala la carga. |
| **Rampa repentina (s)** | Tiempo que usa el escenario Repentino para subir al máximo. |

Si aparece un mensaje de configuración inválida, corrige los valores señalados. Por ejemplo, la duración debe ser positiva, los bytes no pueden ser negativos y los usuarios iniciales no pueden superar a los máximos.

### 4.2 Escenarios

- **Gradual:** aumenta progresivamente.
- **Repentino:** llega rápido al máximo, según la rampa configurada.
- **Pulsante:** alterna niveles altos y bajos.
- **Spike:** empieza con un pico breve y luego mantiene un nivel menor.
- **Personalizado:** aumenta según los límites configurados.

Son patrones matemáticos de carga simulada, no bots o personas reales.

### 4.3 Capas de mitigación

Marca una o varias capas. Si no marcas ninguna, se calcula el escenario sin defensa activa. El botón **¿Cómo funciona?** describe las capas seleccionadas.

| Capa | Qué representa en el modelo |
|---|---|
| **Rate Limiting** | Limita solicitudes procesadas por segundo. |
| **Rate-Based Ban** | Bloquea fuentes virtuales tras superar un umbral en varias evaluaciones. |
| **Blacklisting** | Identifica y bloquea usuarios sospechosos durante un periodo modelado. |
| **CAPTCHA / Challenge** | Envía parte del tráfico a un reto con probabilidad de resolución y demora estimada. |
| **WAF / Filtrado L7** | Filtra tráfico clasificado como malicioso e incorpora errores de clasificación, CPU y latencia. |
| **Bot Management** | Clasifica patrones virtuales y bloquea o desafía parte de los bots. |
| **Auto Scaling** | Añade instancias modeladas hasta el máximo configurado. |
| **CDN / Caching** | Atiende una proporción de solicitudes desde caché, sin enviarlas al origen. |
| **Load Balancing** | Distribuye matemáticamente la carga entre servidores modelados. |
| **Edge / Scrubbing** | Filtra una parte del tráfico antes del origen, según porcentaje y capacidad. |

Los campos **Límite req/s**, **Cache hit %**, **Edge filtrado %** y **Ventana anomalía** ajustan valores de estas capas. Los porcentajes deben estar entre 0 y 100.

### 4.4 Presets

Un preset marca un grupo de capas; puedes cambiarlo después:

- **Protección básica:** Rate Limiting.
- **Protección web:** WAF, Rate Limiting y CAPTCHA.
- **Protección avanzada:** Edge, WAF, Bot Management y Rate Limiting.
- **Alta disponibilidad:** Edge, CDN, Load Balancing y Auto Scaling.
- **Defensa multicapa:** todas las capas.

El preset solo cambia las opciones del modelo. No instala ni configura defensas en servidores reales.

### 4.5 Ejecutar y controlar

1. Confirma que el perfil sea el que deseas estudiar.
2. Ajusta los parámetros y el escenario.
3. Selecciona las mitigaciones y, si quieres, aplica un preset.
4. Pulsa **Iniciar exploración**.
5. Observa las gráficas, el informe en vivo y el registro de eventos.
6. **Pausar** detiene temporalmente la ejecución; usa **Continuar** para reanudar.
7. **Detener** termina antes de la duración prevista. El resultado incluye solo las muestras recogidas hasta ese momento.
8. **Reiniciar** borra las muestras visibles para comenzar otra ejecución.

El registro puede mostrar detección, activación de mitigación y recuperación según las reglas del modelo.

### 4.6 Comparar mitigaciones

Pulsa **Comparar mitigaciones** para volver a ejecutar el mismo escenario sin mitigación, con cada capa por separado y con todas combinadas. Se abre una tabla con saturación, CPU, RAM, latencia, solicitudes bloqueadas y recuperación. Es una comparación del modelo en condiciones equivalentes, no una evaluación de productos reales.

### 4.7 Dashboard interactivo

Al finalizar una ejecución con datos, se abre el dashboard. Incluye saturación máxima, CPU y RAM máximas, detección, recuperación, latencia máxima y estado final. Sus cuatro gráficas muestran:

- CPU y RAM estimadas durante la simulación.
- Saturación y umbral configurado.
- Solicitudes generadas y procesadas por segundo.
- Tráfico generado y tráfico que llega al origen.

**Cómo leer los valores:**

- **Saturación** es el mayor uso relativo estimado entre recursos modelados; no significa que un servidor real haya caído.
- **Detección** indica el segundo simulado en que el modelo reconoce una anomalía. “No detectada” significa que no se cumplieron las condiciones dentro del tiempo observado.
- **Mitigación** se activa dentro del modelo; no cambia la configuración del servidor real.
- **Recuperación** indica cuándo la carga vuelve por debajo del umbral de carga alta después de activar una defensa. “No alcanzada” significa que no se observó antes del final.
- **Estado final** describe el último segundo (por ejemplo, NORMAL, CARGA ALTA, SATURACIÓN, MITIGACIÓN ACTIVA o RECUPERADO).
- Las solicitudes limitadas, bloqueadas o atendidas desde caché se contabilizan de forma distinta según las capas elegidas.

Desde el dashboard puedes pulsar **Exportar CSV** o **Generar reporte TXT**. Los mismos botones están en la pestaña Simulación después de ejecutar.

## 5. Experimento factorial del protocolo

Los botones **Pilotaje ×10** y **Lote formal ×30** ejecutan la matriz definida en el protocolo. No usan los campos del explorador para construir sus factores.

### 5.1 Factores y volumen

El diseño combina dos perfiles (P1 y P2), cinco niveles de usuarios (100, 500, 1,000, 5,000 y 10,000), cuatro escenarios (Gradual, Súbito, Pulsado y Spike), cinco estrategias (Ninguna, Limitación de tasa, Filtrado, Escalamiento y CAPTCHA) y dos confirmaciones de detección (5 y 20 segundos). Añade un control sin ataque por cada perfil. En total son 402 condiciones por repetición:

- **Pilotaje ×10:** 4,020 corridas.
- **Lote formal ×30:** 12,060 corridas.

Cada corrida simula 60 segundos normales, 120 segundos de ataque y 120 segundos de observación de recuperación, en pasos de un segundo. Las corridas usan semillas reproducibles. El procesamiento puede tardar; observa el avance y no cierres la aplicación mientras se ejecuta.

P1 es el perfil que cargaste. P2 es un perfil derivado, inicialmente con CPU lógica ×4 y RAM ×2. El ejecutor intenta que su cuello de botella modelado difiera del de P1 y puede ajustar el perfil derivado; revisa en la configuración JSON qué valores quedaron finalmente usados. Es una comparación matemática, no una máquina física adicional.

### 5.2 Orden sugerido

1. Carga o importa el perfil que será P1.
2. Ejecuta **Pilotaje ×10**.
3. Revisa los resultados y la configuración JSON; verifica datos de red y supuestos de capacidad.
4. Documenta y calibra los parámetros con fundamento antes de interpretar resultados.
5. Ejecuta **Lote formal ×30** cuando el diseño esté revisado.

El modelo usa coeficientes iniciales para CPU, memoria, red, conexiones, inercia, ruido y mitigaciones. El pilotaje ayuda a revisar esos supuestos; por sí solo no demuestra que coincidan con el rendimiento real.

### 5.3 Dashboard factorial y archivos

Al finalizar se abre un dashboard con número de corridas, saturación máxima media, porcentaje de detecciones y demanda atendida media. Las gráficas resumen saturación por usuarios (separada por P1/P2), saturación por escenario, demanda atendida por estrategia y recuperación observada por estrategia.

El tiempo medio de recuperación considera solo corridas que alcanzaron la regla de recuperación. Si una corrida no se recuperó durante los 120 segundos de observación, queda censurada: no se debe tratar como una recuperación de cero segundos.

La ventana indica dónde están los resultados:

- **Resumen CSV:** una fila por corrida con factores y métricas principales.
- **Bitácora CSV comprimida (`.csv.gz`):** observaciones de cada segundo.
- **Configuración JSON:** factores, parámetros y perfiles utilizados.

Conserva los tres archivos juntos para poder relacionar las corridas con la configuración exacta.

## 6. Archivos y resultados guardados

Por defecto, el programa usa estas carpetas dentro del proyecto:

- `datos/perfiles/`: carpeta del proyecto preparada para perfiles; al guardar desde la pestaña Perfil, el usuario elige dónde crear los archivos.
- `datos/reportes/`: reportes TXT, CSV y resultados del experimento factorial.
- `registros/app.log`: registro técnico de la aplicación.

Al guardar manualmente un perfil desde Perfil puedes elegir otra carpeta. Los nombres de los reportes y resultados incluyen fecha y hora.

## 7. Términos básicos

- **req/s:** solicitudes virtuales por segundo.
- **Mbps:** megabits por segundo, unidad de tráfico de red.
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
5. Ejecuta el pilotaje antes del lote formal y conserva su configuración.
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

## 10. Estructura del proyecto

```text
principal.py                         Inicio de la aplicación
aplicacion/
  interfaz/                          Pantallas y dashboards
  modelos/                           Perfiles y configuración
  perfilador/                        Interpretación de diagnósticos
  conexion_ssh/                      Consulta SSH de solo lectura
  simulacion/                        Modelos de carga, servidor y mitigación
  reportes/                          Exportación de perfiles y resultados
  ejecutor_experimental.py           Matriz factorial del protocolo
pruebas/                              Pruebas automatizadas
datos/
  perfiles/                           Perfiles guardados
  reportes/                           Reportes y resultados
registros/                            Registro técnico
```
