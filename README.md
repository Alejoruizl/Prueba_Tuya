# Prueba técnica de Ingeniería de Datos (Tuya)

Solución de los cuatro ejercicios. Los ejercicios 1 y 2 son de diseño y están documentados en `docs/`. Los ejercicios 3 y 4 son código ejecutable, con pruebas automatizadas que corren en GitHub Actions en cada push.

```
.
├── docs/
│   ├── ejercicio1_dataset_telefonos.md   # Diseño CI/CD del dataset de teléfonos
│   └── ejercicio2_kpis_calidad.md        # Veeduría de calidad, linaje y KPIs
├── ejercicio3_rachas/
│   ├── data/Rachas.xlsx                  # Datos fuente
│   ├── sql/
│   │   ├── 01_esquema.sql                # Modelo: staging, niveles, capa depurada, bitácora de calidad
│   │   ├── 02_calidad_y_carga.sql        # Reglas de calidad y carga a la capa depurada
│   │   └── 03_rachas.sql                 # Consulta parametrizada (:fecha_base, :n)
│   ├── rachas/                           # Carga del Excel y CLI (Python)
│   ├── resultados/                       # Salida de ejemplo (fecha_base 2024-12-31, n = 3)
│   └── tests/
├── ejercicio4_html_base64/
│   ├── html_base64/                      # Paquete (solo librería estándar)
│   ├── ejemplos/sitio/                   # HTML de ejemplo para probar la CLI
│   └── tests/
└── .github/workflows/ci.yml              # Pruebas de los ejercicios 3 y 4
```

Requisitos: Python 3.10 o superior. El ejercicio 3 usa `openpyxl` únicamente para leer el Excel; el ejercicio 4 no tiene dependencias externas.

---

## Ejercicio 1: dataset de números de teléfono con CI/CD

Documento completo: [docs/ejercicio1_dataset_telefonos.md](docs/ejercicio1_dataset_telefonos.md)

- Arquitectura por capas: Bronze inmutable por fuente, Silver normalizado y validado, y Gold (`dim_cliente_telefono`) con historia SCD2. Los registros rechazados van a una tabla de cuarentena con el motivo; no se descartan.
- Reglas de negocio: normalización a E.164, clasificación móvil o fijo según la marcación colombiana vigente (fijos `60X` desde 2021), detección de números basura o compartidos, integridad con el maestro de clientes y autorización de contacto (Ley 1581 de 2012).
- Golden record: un puntaje determinístico (confiabilidad de la fuente, verificación, recencia y rebotes) elige el teléfono principal de cada cliente por tipo.
- CI/CD: en cada pull request corren lint, pruebas unitarias, contratos de datos y pruebas de integración sobre una muestra anonimizada. La promoción va de DEV a QA y luego a PRD con aprobación del data owner. Cada lote se publica en modo blue/green detrás de quality gates (volumen, cuarentena, unicidad, frescura y deriva), con rollback por time travel.
- Las reglas y los umbrales son configuración versionada en Git, de modo que cada número publicado se puede rastrear hasta la versión del proceso que lo produjo.

## Ejercicio 2: veeduría de calidad y KPIs

Documento completo: [docs/ejercicio2_kpis_calidad.md](docs/ejercicio2_kpis_calidad.md)

- Observatorio de calidad alimentado por el mismo pipeline: tablas `dq_corridas`, `dq_resultados_reglas`, `dq_cuarentena` y `hechos_contactabilidad`.
- KPIs por dimensión de calidad (completitud, validez, unicidad, consistencia, oportunidad y exactitud, esta última medida como contactabilidad real), de salud del proceso y de impacto en el negocio. Cada uno tiene fórmula, dueño y umbral, definidos una sola vez en una capa semántica.
- Trazabilidad: linaje técnico con OpenLineage (Marquez o DataHub) y linaje por registro (`id_lote`, `version_pipeline`, `fuente_origen`) consultable desde el tablero.
- Alertas por severidad y un tablero de autoservicio con seguridad a nivel de fila y columna.

---

## Ejercicio 3: rachas

Motor: SQLite, a través del módulo `sqlite3` de Python (no requiere instalar un servidor). La consulta usa SQL estándar (CTE y funciones de ventana); para llevarla a PostgreSQL o Impala basta con ajustar la aritmética de fechas.

### Ejecución

```bash
cd ejercicio3_rachas
pip install -r requirements.txt
python -m rachas --fecha-base 2024-12-31 --n 3 --salida resultados/rachas.csv
python -m unittest discover -s tests -v
```

El comando crea `rachas.db`, carga el Excel, aplica las reglas de calidad e imprime el resumen de incidencias y el resultado. Con la base ya construida, la consulta también se puede ejecutar desde la CLI de SQLite (`sqlite3 rachas.db`). La fecha va con comillas simples dentro de comillas dobles, porque sin ellas la CLI evalúa `2024-12-31` como una resta:

```sql
.parameter set :fecha_base "'2024-12-31'"
.parameter set :n 3
.read sql/03_rachas.sql
```

### Flujo

1. `sql/01_esquema.sql`: tablas staging sin tipos forzados (conservan el dato tal como viene), `dim_nivel` con los rangos de deuda (la consulta no tiene valores quemados), tablas depuradas con llaves primarias y `CHECK` (corte en fin de mes, saldo no negativo) y la bitácora `dq_incidencias`.
2. `rachas/cargar_excel.py`: lee las hojas ubicando las columnas por nombre y guarda el número de fila de origen para trazabilidad. La carga es atómica: si falta una hoja o una columna, staging queda como estaba.
3. `sql/02_calidad_y_carga.sql`: reglas de calidad idempotentes. Cada regla que se dispara deja un registro en `dq_incidencias` con severidad `RECHAZO`, `CORRECCION` o `ADVERTENCIA`.
4. `sql/03_rachas.sql`: la consulta del ejercicio.

### Calidad de datos

Hallazgos en el archivo entregado:

| Regla | Hallazgo | Tratamiento |
|---|---|---|
| R07 duplicado exacto | `9NWFWJ38XN31WBFXG` aparece dos veces en 2023-08 con el mismo saldo | Se deja un solo registro |
| R08 duplicado conflictivo | `R7Q4Z9AULIORDJQ9D` tiene dos saldos en 2024-12: 571.481 y 1.142.962 (exactamente el doble) | Se conserva el mayor, con un criterio conservador de riesgo (no subestimar la deuda), y ambos quedan en la bitácora |
| R09 y R12 retiro sin historia | El retiro `1LFTDYT2H0I9ZGED3S8` tiene 19 caracteres (los demás tienen 17) y no existe en historia. Muy probablemente es `1LFTDYT2H0I9ZG3S8` con "ED" de más | No se corrige automáticamente, porque cambiar una identificación requiere confirmarlo con la fuente. La regla reporta la posible coincidencia |
| R13 saldo posterior al retiro | `0TTW5R9RRCJ0A9E5F` (retiro 2024-10-10) tiene 3 cortes posteriores y `THJ9OBJH3W6ANRCMS` (retiro 2024-01-20) tiene 11 | Se conservan y se reportan (ver decisiones de interpretación) |

También se validan casos que este archivo no trae pero que una carga real sí puede traer: identificaciones vacías, con espacios o en minúsculas; fechas inválidas o inexistentes (SQLite convierte `2024-02-30` en `2024-03-01` sin avisar); números de serie de Excel sin convertir a fecha; cortes que no son fin de mes; saldos no numéricos o negativos, y retiros duplicados.

### Consulta (`03_rachas.sql`)

| Paso | CTE | Qué hace |
|---|---|---|
| 1 | `historia_vigente` | Toma la foto a la `fecha_base`: solo cortes con fecha menor o igual a la `fecha_base`. |
| 2 | `calendario`, `primera_aparicion` | Genera los fines de mes entre el primer y el último corte cargado, y la primera aparición de cada cliente. |
| 3 | `saldos_mensuales` | Arma la serie mensual de cada cliente desde su primera aparición. Un mes sin registro se imputa con saldo 0 (N0), excepto si el corte es posterior a la fecha de retiro: ese mes no existe para el cliente. |
| 4 | `saldos_clasificados` | Asigna el nivel uniendo con `dim_nivel` por intervalos `[min, max)` y calcula el número absoluto de cada mes. |
| 5 | `islas`, `rachas` | Gaps and islands: dentro de un cliente y nivel, el número de mes menos su posición (`ROW_NUMBER`) es constante mientras los meses sean consecutivos. Un cambio de nivel o un mes inexistente inicia una racha nueva. |
| 6 | `rachas_priorizadas` | Filtra las rachas de al menos `n` meses y, con `ROW_NUMBER()` ordenado por `racha DESC, fecha_fin DESC`, deja la más larga y, si hay empate, la más reciente. |

Salida: `identificacion`, `racha`, `fecha_fin` y `nivel`, con una fila por cliente que tenga al menos una racha de `n` meses o más. Con `fecha_base = 2024-12-31` y `n = 3` el resultado tiene 92 clientes: [resultados/rachas_2024-12-31_n3.csv](ejercicio3_rachas/resultados/rachas_2024-12-31_n3.csv).

### Decisiones de interpretación

- Retiro: el enunciado establece que después de la fecha de retiro no se imputa N0. Los saldos que sí aparecen reportados después del retiro se conservan, porque un cliente que se retira puede seguir teniendo saldo pendiente; la regla R13 los deja registrados para seguimiento.
- Un retiro con fecha posterior a la `fecha_base` no tiene efecto: todos los cortes evaluados son anteriores a él.
- Los meses faltantes se imputan hasta el último corte cargado que sea menor o igual a la `fecha_base`, no hasta la `fecha_base` misma. Con una `fecha_base` posterior a los datos, imputar hasta esa fecha llenaría a todos los clientes de meses N0 que la fuente todavía no ha reportado.
- El corte de un mes es su último día y solo cuenta si es menor o igual a la `fecha_base`: con `fecha_base = 2024-06-15`, el último corte considerado es 2024-05-31.

### Pruebas

- Casos sintéticos para cada regla del enunciado: límites exactos de cada nivel, imputación de meses intermedios y finales, sin imputación antes de la primera aparición, la racha más larga gana a la más reciente, desempate por la más reciente, filtro por `n`, retiro a mitad y a fin de mes, saldos reportados después del retiro, meses inexistentes que cortan una racha, y retiros y cortes posteriores a la `fecha_base`.
- Reglas de calidad: un escenario con cada tipo de error verifica la bitácora y la capa depurada.
- Validación cruzada: una implementación independiente en Python puro se compara con la consulta SQL sobre los datos reales en 40 combinaciones de `fecha_base` y `n`, incluidas fechas a mitad de mes y posteriores a los datos.

---

## Ejercicio 4: imágenes de HTML a base64

Paquete `html_base64`, escrito solo con la librería estándar y orientado a objetos.

### Ejecución

```bash
cd ejercicio4_html_base64
python -m html_base64 ejemplos/sitio                         # genera *_base64.html junto a cada original
python -m html_base64 a.html b.html carpeta/ -o salida/      # replica la estructura en otro directorio
python -m html_base64 ejemplos/sitio --reporte resultado.json --sin-remotas
python -m unittest discover -s tests -v
```

Uso desde código:

```python
from html_base64 import ejecutar

resultado = ejecutar(["pagina.html", "carpeta/"]).a_dict()
# {
#   "success": {"C:/.../pagina.html": ["img/logo.png", ...]},
#   "fail":    {"C:/.../pagina.html": [{"src": "falta.png", "error": "No existe el archivo ..."}]}
# }
```

La CLI imprime ese objeto en JSON y termina con código 1 si alguna imagen falló, para poder usarla dentro de un pipeline.

### Diseño

| Módulo | Responsabilidad |
|---|---|
| `descubrimiento.BuscadorHtml` | Recibe archivos y directorios, recorre subdirectorios, filtra `.html` y `.htm`, elimina duplicados y omite las salidas de ejecuciones anteriores (`*_base64.html`). Las rutas indicadas explícitamente que no se procesan quedan en `fail` con el motivo. |
| `html_img` | Ubica las etiquetas `<img>` con `html.parser` (ignora comentarios, `<script>` y `<style>`) y reemplaza solo el valor de `src` en el texto original, de modo que el resto del documento queda igual byte a byte. |
| `fuentes` | Patrón Strategy: `FuenteImagen` (abstracta), `FuenteArchivoLocal` (rutas relativas al HTML, absolutas y `file://`) y `FuenteHttp` (`http`, `https` y `//cdn...`, con timeout y tamaño máximo). Un origen nuevo se agrega con una clase, sin tocar el procesador. |
| `fuentes.detectar_mime` | Identifica el formato por la firma binaria del archivo. Si la extensión o el servidor dicen PNG pero el contenido no lo es, la imagen se reporta como fallida en lugar de incrustar un archivo dañado. |
| `procesador.ProcesadorHtml` | Orquesta el proceso con las dependencias inyectadas (fuentes y destino), guarda en caché las imágenes ya leídas o descargadas y nunca escribe sobre un archivo de entrada. Un error inesperado en un archivo se reporta y no detiene el resto del lote. |
| `procesador.DestinoSalida` | Calcula la ruta del archivo nuevo, junto al original o replicando la estructura en el directorio de salida. |
| `reporte.ReporteProcesamiento` | El objeto `{success, fail}` agrupado por archivo HTML. |

### Casos contemplados

- `src` con comillas dobles, simples o sin comillas (incluso con `=` en el valor, como `logo.png?v=2`), en mayúsculas o con entidades (`&amp;`).
- Atributos parecidos que no se deben tocar (`data-src`, `alt="src=..."`) y etiquetas dentro de comentarios o de `<script>`.
- `<img>` sin `src`, imágenes ya embebidas (`data:`, se dejan igual) e imágenes repetidas (se reportan una vez; una misma URL se descarga una sola vez).
- Rutas relativas al HTML (también con `\` como separador), absolutas, `file://`, con query string o con `%20`.
- URLs relativas al protocolo (`//cdn...`), con espacios, malformadas, con error HTTP o que devuelven algo distinto a una imagen.
- HTML en UTF-8, Windows-1252 o con BOM (UTF-8, UTF-16 o UTF-32), conservando la codificación y los saltos de línea.
- Rutas de entrada inexistentes o que no son HTML, salidas que caerían sobre un archivo de entrada y errores al escribir: se reportan en `fail` y una imagen solo cuenta como exitosa si el archivo nuevo se pudo escribir.

Supuestos:

- Como indica el enunciado, solo se procesa el atributo `src` de `<img>`. `srcset`, `<picture><source>` y las imágenes referenciadas desde CSS quedan fuera del alcance.
- Una ruta que empieza por `/` se resuelve como lo haría un navegador al abrir el archivo local: desde la raíz del sistema de archivos (en Windows, de la unidad del HTML), no desde la raíz de un sitio web.

Las pruebas de descarga usan un servidor HTTP local que se levanta dentro de la misma prueba, así que no dependen de internet.
