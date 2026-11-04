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

La conexión ejecuta comandos de diagnóstico fijos para recoger información del sistema, CPU, memoria, discos y red. No permite enviar comandos arbitrarios. El **método de autenticación** elige entre la contraseña de la cuenta o una clave SSH privada. Si eliges clave, selecciona el archivo privado cuya clave pública correspondiente está autorizada en el servidor. La contraseña solo se utiliza durante la conexión y no se guarda en el perfil; el archivo de clave tampoco se copia al perfil.

Por seguridad, el programa rechaza hosts que no estén reconocidos en `known_hosts`. Antes de conectar por primera vez, verifica la huella del servidor por un canal confiable y registra su identidad en `known_hosts`. No aceptes una huella que no hayas verificado. Si falla la conexión, comprueba también el host, puerto, usuario y credenciales.

### 3.2 Perfil: revisar y guardar

El panel **Perfil**, a la derecha de Conexión, presenta el resumen que utilizará el modelo y una tabla con discos e interfaces de red. Revisa especialmente CPU, memoria disponible y velocidad de red: afectan las estimaciones de capacidad.

- **Guardar perfil:** elige una carpeta. Se crean un archivo JSON (para importar más tarde) y un TXT (para leerlo fácilmente).
- **Continuar a simulación:** abre Simulación con el perfil actual.

Si el perfil tiene valores incompletos o poco representativos, los resultados también pueden serlo. La opción de demostración es ficticia y no describe un equipo real.

## 4. Explorador interactivo

Este modo se encuentra en la pestaña **Simulación** y permite ejecutar una condición a la vez. Al abrirla, puedes configurar el escenario; al pulsar **Iniciar exploración**, aparecen las gráficas y se actualizan durante la ejecución.

### 4.1 Parámetros de carga

Los campos están distribuidos en secciones para facilitar la lectura:

| Campo | Explicación |
|---|---|
| **Usuarios iniciales** | Usuarios virtuales al comienzo. No puede superar el máximo. |
| **Usuarios máximos** | Límite al que puede llegar la curva de usuarios. |
| **Duración** | Tiempo de la exploración. Elige segundos o minutos en la lista; cada segundo simulado tarda un segundo real. |
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

Marca una o varias capas. Si no marcas ninguna, se calcula el escenario sin defensa activa.

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

Al elegir un preset en la lista, sus capas se marcan automáticamente. Después puedes cambiar las casillas manualmente:

- **Protección básica:** Rate Limiting.
- **Protección web:** WAF, Rate Limiting y CAPTCHA.
- **Protección avanzada:** Edge, WAF, Bot Management y Rate Limiting.
- **Alta disponibilidad:** Edge, CDN, Load Balancing y Auto Scaling.
- **Defensa multicapa:** todas las capas.

El preset solo cambia las opciones del modelo. No instala ni configura defensas en servidores reales.

### 4.5 Ejecutar y controlar

1. Confirma que el perfil sea el que deseas estudiar.
2. Ajusta los parámetros en las secciones Usuarios y duración, Tráfico y capacidad, y Mitigación.
3. Elige un escenario y sus capas de defensa. Al elegir un preset, se marcan automáticamente las capas correspondientes.
4. Pulsa **Iniciar exploración**. Los parámetros desaparecen y se muestran las seis gráficas, el estado y el avance.
Las gráficas muestran: tráfico generado y al origen; solicitudes generadas y procesadas; uso estimado de CPU, RAM y red con el cuello de botella actual; saturación, umbrales y marcas de detección, mitigación y recuperación; porcentaje de carga atendida; y solicitudes limitadas o bloqueadas. El porcentaje atendido considera las solicitudes procesadas y las servidas desde caché.
5. **Pausar** detiene temporalmente la ejecución; el mismo botón permite continuar.
6. **Detener** termina antes de la duración prevista. El resultado incluye solo las muestras recogidas hasta ese momento.
7. **Reiniciar** limpia la ejecución y regresa al explorador para configurar otra.
8. **Volver al explorador interactivo** permite regresar a los parámetros sin cerrar la pestaña.

Las gráficas permanecen visibles al finalizar. La simulación representa estimaciones matemáticas; no mide ni modifica el servidor real.

## 5. Matriz factorial (herramienta técnica)

La matriz factorial se ejecuta por separado desde la terminal y no forma parte de la ventana del explorador. Puedes usar un perfil JSON propio o el perfil de demostración:

```bash
python -m aplicacion.ejecutor_experimental --repetitions 1
```

El comando guarda un resumen CSV, una bitácora comprimida y la configuración utilizada en `datos/reportes/`. La cantidad de repeticiones determina el volumen de cómputo; el modelo es matemático y no genera tráfico hacia un servidor real.

## 6. Archivos y resultados guardados

Por defecto, el programa usa estas carpetas dentro del proyecto:

- `datos/perfiles/`: carpeta del proyecto preparada para perfiles; al guardar desde el panel Perfil, el usuario elige dónde crear los archivos.
- `datos/reportes/`: reportes TXT y archivos de resultados.
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
