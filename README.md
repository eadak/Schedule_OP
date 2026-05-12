# ⛏️ MB Production Planner — Planificador de Producción Minera

Aplicación Streamlit para planificación de producción minera mediante heurística **Phase-Bench** sobre un modelo de bloques.

---

## 🚀 Instalación y ejecución

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Lanzar la app
py -m streamlit run app.py
```

La app se abrirá automáticamente en `http://localhost:8501`.

---

## 📂 Estructura del proyecto

```
.
├── app.py              # Aplicación principal (Streamlit)
├── requirements.txt    # Dependencias Python
└── README.md           # Este archivo
```

---

## 📋 Formato del CSV de entrada

El archivo CSV debe contener **exactamente** estas columnas (sensible a mayúsculas):

| Columna    | Tipo    | Descripción                        |
|------------|---------|------------------------------------|
| `X`        | float   | Coordenada Este del bloque         |
| `Y`        | float   | Coordenada Norte del bloque        |
| `Z`        | float   | Elevación del banco                |
| `fase`     | int     | Número de fase de minado           |
| `Ley`      | float   | Ley de Cu en porcentaje (ej: 0.45) |
| `tonelaje` | float   | Tonelaje del bloque (t)            |

---

## ⚙️ Parámetros configurables (panel lateral)

| Parámetro               | Descripción                                             | Defecto      |
|-------------------------|---------------------------------------------------------|--------------|
| **Periodos (H)**        | Número de periodos de planificación                     | 39           |
| **Lag entre fases**     | Bancos de adelanto necesarios para activar nueva fase   | 3            |
| **Precio Cu**           | Precio del cobre (USD/lb)                               | 4.00         |
| **Descuento fundición** | Penalización de fundición/refinación (USD/lb)           | 0.10         |
| **Costo minado**        | Costo de minado (USD/t movida)                          | 2.00         |
| **Costo planta**        | Costo de procesamiento en planta (USD/t mineral)        | 10.00        |
| **Tasa de descuento**   | Tasa anual para el cálculo del VAN (%)                  | 10           |
| **Recuperación**        | Recuperación metalúrgica en planta (%)                  | 90           |
| **Cap. mineral**        | Capacidad máxima de mineral por periodo (t)             | 35 000 000   |
| **Cap. estéril**        | Capacidad máxima de estéril por periodo (t)             | 70 000 000   |
| **Cap. planta**         | Capacidad de procesamiento por periodo (t)              | 30 000 000   |

---

## 📊 Salidas de la app

### Métricas KPI
- VAN total descontado (MUSD)
- Ley de corte económica calculada automáticamente
- Mineral total procesado (Mt)
- Tiempo de cómputo (s)

### Gráficos
- **Movimiento de material**: barras apiladas mineral + estéril con ley de mina superpuesta
- **VAN acumulado**: curva de valor presente neto a lo largo de los periodos

### Descargas CSV
| Archivo                            | Contenido                                      |
|------------------------------------|------------------------------------------------|
| `plan_phase_bench.csv`             | Plan agregado por periodo (mineral, estéril, ley, VAN) |
| `clusters_phase_bench.csv`         | Clusters fase-banco con periodo asignado       |
| `modelo_bloques_phase_bench.csv`   | Modelo de bloques original + columna `periodo` |

---

## 🧮 Metodología

1. **Ley de corte económica** se calcula automáticamente:  
   `LC = (C_minado + C_planta) / (LBS_PER_TON × (Precio − Descuento) × Recuperación)`

2. **Agrupación phase-bench**: los bloques se agrupan por `(fase, Z)` para crear clusters operativos.

3. **Precedencias verticales**: cada banco solo puede minarse si el banco superior de la misma fase ya está minado.

4. **Heurística Round-Robin**: en cada periodo se itera por fases activas asignando clusters respetando capacidades y precedencias.

5. **Activación de fases**: la fase 1 inicia en el periodo 1; cada fase siguiente se activa cuando la fase anterior tiene al menos `LAG_FASE` bancos minados.

---

## 📦 Dependencias

```
streamlit>=1.35.0
pandas>=2.0.0
numpy>=1.26.0
matplotlib>=3.8.0
```

---

## 👤 Autor

Desarrollado por **Ing. Julián De Chino** — MB Visualizador 2025.
