# Evidencia de los módulos del protocolo

Este documento contrasta los módulos que se alcanzan a leer en la imagen de **Desarrollo** con la implementación del proyecto.

## Resultado

Los cuatro módulos existen como componentes de código y están integrados entre sí en el modelo experimental del protocolo. El ejecutor factorial utiliza esa integración y guarda resultados por escenario.

Hay una distinción importante: el **explorador interactivo de la interfaz gráfica** usa `SimulationEngine`, un motor independiente. Los módulos descritos aquí se ejecutan mediante `ProtocolSimulation`, que consume el ejecutor factorial desde la terminal. Por eso, el proyecto cumple con esos módulos en la ruta del protocolo, pero la interfaz gráfica no está usando ese mismo motor.

## Correspondencia con la imagen

| Módulo de la imagen | Implementación | Responsabilidad comprobable |
|---|---|---|
| Módulo de tráfico normal | [`trafico_normal.py`](aplicacion/simulacion/trafico_normal.py) — `NormalTraffic` | Calcula la demanda legítima de referencia a partir del 20 % de la capacidad estimada y la tasa de solicitudes por usuario. |
| Módulo de tráfico malicioso (bots) | [`trafico_malicioso.py`](aplicacion/simulacion/trafico_malicioso.py) — `MaliciousTraffic` | Genera cantidad virtual de bots según los escenarios gradual, súbito, pulsado o spike. Usa una fuente aleatoria con semilla y no envía tráfico de red. |
| Módulo del servidor simulado | [`servidor_simulado.py`](aplicacion/simulacion/servidor_simulado.py) — `SimulatedServer` | Estima capacidad y utilización de CPU, RAM, red y conexiones; identifica el cuello de botella, calcula carga atendida, saturación y estado del servidor modelado. |
| Módulo de detección y mitigación | [`deteccion_mitigacion.py`](aplicacion/simulacion/deteccion_mitigacion.py) — `DetectionMitigation` | Confirma umbrales consecutivos y modela Ninguna, Limitación de tasa, Filtrado, CAPTCHA y Escalamiento. Solo modifica la demanda o capacidad dentro del modelo. |

La cantidad de subtareas indicada debajo de cada tarjeta en la imagen (por ejemplo, `0/3`) no muestra sus nombres. Por ello, esta comprobación cubre los cuatro módulos visibles y sus funciones principales, pero no permite certificar cada subtarea oculta del tablero.

## Cómo se conectan

[`modelo_protocolo.py`](aplicacion/simulacion/modelo_protocolo.py) coordina los cuatro módulos. En cada segundo de la simulación:

1. Crea la demanda normal de referencia.
2. Añade bots virtuales según el escenario seleccionado.
3. La detección observa la saturación proyectada y, al confirmarse, calcula el efecto de la estrategia elegida.
4. El servidor simulado avanza sus recursos y registra utilización, saturación, estado, capacidad atendida y cuello de botella.
5. `ProtocolSimulation` reúne la serie temporal y los indicadores del resultado.

El ejecutor [`ejecutor_experimental.py`](aplicacion/ejecutor_experimental.py) llama a `ProtocolSimulation` para cada condición factorial y exporta un resumen CSV y una bitácora comprimida. Sus columnas incluyen saturación máxima, utilización máxima por recurso, cuello de botella, proporción atendida, estado más severo y tiempos de detección y recuperación.

```text
ProtocolSimulation
??? NormalTraffic
??? MaliciousTraffic
??? DetectionMitigation
??? SimulatedServer
    ??? muestras y resultados -> ejecutor factorial
```

## Diferencia con el explorador de la interfaz

La interfaz gráfica de [`vista_simulador.py`](aplicacion/interfaz/vista_simulador.py) construye una configuración interactiva y ejecuta [`SimulationEngine`](aplicacion/simulacion/motor_simulacion.py). Este motor también modela demanda, recursos, estados y mitigaciones, pero no instancia las clases `NormalTraffic`, `MaliciousTraffic`, `SimulatedServer` ni `DetectionMitigation`.

En consecuencia:

- Si la tarjeta de desarrollo pide que existan e integren **los módulos del protocolo y su ejecutor experimental**, la implementación está presente.
- Si pide que **la interfaz gráfica use exactamente esos cuatro módulos**, esa integración aún no está hecha y debe tratarse como un trabajo distinto.

## Pruebas relacionadas

En [`prueba_modulos_protocolo.py`](pruebas/prueba_modulos_protocolo.py) hay pruebas para la demanda normal, los patrones de bots, los estados del servidor, la detección y aplicación de estrategia, la integración y determinismo de `ProtocolSimulation`, perfiles con distintos cuellos de botella y salida del ejecutor factorial.

Para ejecutarlas desde la carpeta raíz del proyecto:

```bash
python -m unittest -v pruebas.prueba_modulos_protocolo
```

Las pruebas verifican el modelo local; no generan solicitudes hacia un servidor real.
