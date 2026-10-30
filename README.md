# Prueba técnica de Ingeniería de Datos (Tuya)

[![CI](https://github.com/Alejoruizl/Prueba_Tuya/actions/workflows/ci.yml/badge.svg)](https://github.com/Alejoruizl/Prueba_Tuya/actions/workflows/ci.yml)

En este repositorio está mi solución a los cuatro ejercicios de la prueba. Los ejercicios 1 y 2 son de diseño y los documenté en `docs/`; para el 1 además armé un prototipo que corre de verdad, porque el enunciado habla de diseñar *e implementar*. Los ejercicios 3 y 4 son código, con sus pruebas, y todo se ejecuta en GitHub Actions cada vez que hago push.

Para ir rápido:

| Ejercicio | Dónde está | Para probarlo |
|---|---|---|
| 1. Dataset de teléfonos | `docs/ejercicio1_dataset_telefonos.md` + `ejercicio1_telefonos/` | `cd ejercicio1_telefonos && python -m telefonos` |
| 2. KPIs y veeduría | `docs/ejercicio2_kpis_calidad.md` | lectura |
| 3. Rachas | `ejercicio3_rachas/` | `cd ejercicio3_rachas && python -m rachas --fecha-base 2024-12-31 --n 3` |
| 4. HTML a base64 | `ejercicio4_html_base64/` | `cd ejercicio4_html_base64 && python -m html_base64 ejemplos/sitio` |

Si solo va a mirar una cosa, le sugiero la sección de calidad de datos del ejercicio 3: el Excel trae varios problemas (un duplicado con saldos distintos, un retiro con la cédula mal digitada, saldos después del retiro) y ahí explico qué hice con cada uno y por qué. En total hay 54 pruebas automatizadas; la que más me gusta es la que compara la consulta SQL contra una implementación aparte en Python en 40 escenarios distintos.

Necesita Python 3.10 o superior. La única dependencia externa es `openpyxl` en el ejercicio 3, para leer el Excel; lo demás es librería estándar.

```
.
├── docs/
│   ├── ejercicio1_dataset_telefonos.md
│   └── ejercicio2_kpis_calidad.md
├── ejercicio1_telefonos/
│   ├── telefonos/          # normalización, reglas, supervivencia, pipeline
│   ├── data/               # maestro de clientes, fuentes, contactabilidad, lista negra, config
│   └── tests/
├── ejercicio3_rachas/
│   ├── data/Rachas.xlsx
│   ├── sql/                # 01_esquema, 02_calidad_y_carga, 03_rachas
│   ├── rachas/             # carga del Excel y CLI
│   ├── resultados/         # salida de ejemplo (fecha_base 2024-12-31, n = 3)
│   └── tests/
├── ejercicio4_html_base64/
│   ├── html_base64/
│   ├── ejemplos/sitio/
│   └── tests/
└── .github/workflows/ci.yml
```

---

## Ejercicio 1: dataset de teléfonos con CI/CD

El diseño completo está en [docs/ejercicio1_dataset_telefonos.md](docs/ejercicio1_dataset_telefonos.md). En resumen:

- Tres capas: Bronze con el dato crudo de cada fuente (nunca se modifica), Silver con los teléfonos normalizados a E.164 y validados, y Gold con `dim_cliente_telefono`, que guarda historia (SCD tipo 2) y marca cuál es el teléfono principal de cada cliente. Lo que no pasa las validaciones no se bota: va a una tabla de cuarentena con el motivo.
- Las reglas de negocio son las que uno esperaría para Colombia: móviles que empiezan por 3, fijos con la marcación unificada `60X`, números basura tipo `3000000000`, un mismo número repartido entre muchos clientes, clientes que no existen en el maestro y la autorización de contacto (Ley 1581).
- Cuando un cliente tiene varios números del mismo tipo, el principal se escoge con un puntaje: pesa la fuente, si el número se verificó con un contacto efectivo, qué tan reciente es y si ha rebotado.
- La parte de CI/CD: en cada pull request corren lint, pruebas unitarias, contratos de datos y una corrida sobre una muestra anonimizada. Se promueve de DEV a QA y a PRD con aprobación del dueño del dato. El lote nuevo se escribe aparte y solo se publica si pasa los quality gates (volumen, cuarentena, unicidad, frescura, deriva); si algo falla, los consumidores siguen leyendo el lote anterior.
- Reglas, pesos y umbrales son configuración versionada en Git, no código. Así cualquier número publicado se puede rastrear hasta la versión del proceso que lo produjo.

### El prototipo

Está en `ejercicio1_telefonos/` y es Python puro, sin dependencias.

```bash
cd ejercicio1_telefonos
python -m telefonos --fecha 2026-10-30     # deja la salida en salida/
python -m unittest discover -s tests -v
```

Genera tres archivos: `dim_cliente_telefono.csv` (la tabla Gold), `cuarentena.csv` y `reporte_gates.json`. Si algún gate falla, la tabla Gold no se escribe y el comando termina con código 1, que es como lo detendría un orquestador.

Qué hay en cada módulo:

- `normalizacion.py` convierte a E.164 los formatos típicos (`+57 (300) 123-4567`, `0057...`, `03...`), decide si es móvil o fijo y, si llega un fijo viejo de 7 dígitos, lo completa con el indicativo de la ciudad del cliente.
- `reglas.py` son las reglas T01 a T06 del documento. Cada rechazo guarda la regla, el motivo y la fila de origen.
- `supervivencia.py` calcula el puntaje y elige el principal por cliente y tipo.
- `pipeline.py` une todo (Bronze, Silver, Gold) y evalúa los gates: volumen mínimo, tasa de cuarentena, unicidad del principal y cobertura de móvil.

Los pesos y umbrales están en `data/config.json`. Los datos de ejemplo los armé para que se vieran los casos interesantes: un número verificado que le gana a otro de una fuente más confiable pero que ha rebotado, un teléfono compartido por tres clientes, un cliente sin autorización (sale con `apto_contacto = false`) y uno que no está en el maestro.

## Ejercicio 2: veeduría de calidad y KPIs

Documento: [docs/ejercicio2_kpis_calidad.md](docs/ejercicio2_kpis_calidad.md)

La idea es que el mismo pipeline del ejercicio 1 vaya dejando sus resultados de calidad en tablas (`dq_corridas`, `dq_resultados_reglas`, `dq_cuarentena`), junto con lo que devuelven los canales de contacto (`hechos_contactabilidad`). Sobre eso se definen los KPIs una sola vez, en una capa semántica, cada uno con su fórmula, su dueño y su umbral: completitud, validez, unicidad, consistencia, oportunidad y exactitud (que para un teléfono es, al final, si contesta alguien). El linaje técnico va con OpenLineage y el de cada registro se lleva con `id_lote`, `version_pipeline` y `fuente_origen`; así desde el tablero se puede llegar hasta el origen de un número. Hay alertas por severidad y el tablero es de autoservicio, con seguridad por fila y columna.

---

## Ejercicio 3: rachas

Usé SQLite porque viene con Python y cualquiera puede reproducirlo sin instalar nada. La consulta es SQL estándar (CTE y funciones de ventana); pasarla a PostgreSQL o Impala sería cambiar la aritmética de fechas y poco más.

### Cómo correrlo

```bash
cd ejercicio3_rachas
pip install -r requirements.txt
python -m rachas --fecha-base 2024-12-31 --n 3 --salida resultados/rachas.csv
python -m unittest discover -s tests -v
```

Eso crea `rachas.db`, carga el Excel, aplica las reglas de calidad y muestra el resumen de incidencias y el resultado. Si prefiere correr la consulta directo en la CLI de SQLite (`sqlite3 rachas.db`), ojo con las comillas: sin ellas la CLI interpreta `2024-12-31` como una resta y devuelve cero filas sin avisar.

```sql
.parameter set :fecha_base "'2024-12-31'"
.parameter set :n 3
.read sql/03_rachas.sql
```

### Cómo está armado

Son tres scripts SQL y un cargador en Python:

1. `01_esquema.sql` crea las tablas de staging (sin tipos, para conservar el dato tal como viene), `dim_nivel` con los rangos de deuda, las tablas depuradas con llave primaria y `CHECK`, y la bitácora `dq_incidencias`. Puse los niveles en una tabla para no dejar números quemados en la consulta.
2. `cargar_excel.py` lee las hojas buscando las columnas por nombre y guarda el número de fila original. La carga es atómica: si falta una hoja, staging queda como estaba.
3. `02_calidad_y_carga.sql` aplica las reglas de calidad y pasa los datos a la capa depurada. Cada regla que se dispara deja un registro con severidad `RECHAZO`, `CORRECCION` o `ADVERTENCIA`.
4. `03_rachas.sql` es la consulta del ejercicio.

### Lo que encontré en el Excel

- **Un duplicado exacto**: `9NWFWJ38XN31WBFXG` aparece dos veces en 2023-08 con el mismo saldo. Dejé uno (regla R07).
- **Un duplicado con saldos distintos**: `R7Q4Z9AULIORDJQ9D` tiene dos saldos en 2024-12, 571.481 y 1.142.962, que es exactamente el doble. Huele a registro sumado dos veces. Me quedé con el mayor, por un criterio conservador de riesgo (prefiero no subestimar deuda), y dejé los dos en la bitácora (R08).
- **Un retiro que no cuadra**: `1LFTDYT2H0I9ZGED3S8` tiene 19 caracteres cuando todas las demás identificaciones tienen 17, y no existe en historia. Casi seguro es `1LFTDYT2H0I9ZG3S8` con un "ED" de más. No lo corregí automáticamente: cambiar una identificación sin confirmar con la fuente puede terminar aplicándole el retiro a otro cliente. La regla lo reporta junto con la coincidencia probable (R09 y R12).
- **Saldos después del retiro**: `0TTW5R9RRCJ0A9E5F` se retiró el 2024-10-10 y tiene 3 cortes posteriores; `THJ9OBJH3W6ANRCMS` se retiró el 2024-01-20 y tiene 11. Los conservé, más abajo explico por qué (R13).

Aparte de eso, el script valida cosas que este archivo no trae pero que una carga real sí: identificaciones vacías o con espacios, fechas inválidas o inexistentes (SQLite convierte `2024-02-30` en `2024-03-01` sin decir nada, y un número de serie de Excel lo toma como día juliano), cortes que no son fin de mes, saldos no numéricos o negativos y retiros repetidos.

### La consulta

Va por pasos, un CTE cada uno:

1. `historia_vigente`: la foto a la `fecha_base`, solo cortes menores o iguales a ella.
2. `calendario` y `primera_aparicion`: los fines de mes entre el primer y el último corte cargado, y el primer corte de cada cliente.
3. `saldos_mensuales`: la serie mensual de cada cliente desde su primera aparición. Un mes sin registro se imputa como saldo 0 (N0), salvo que el corte sea posterior a la fecha de retiro: en ese caso el mes simplemente no existe para ese cliente.
4. `saldos_clasificados`: el nivel sale de cruzar con `dim_nivel` por intervalo `[min, max)`. También calculo el número absoluto del mes (`año * 12 + mes`).
5. `islas` y `rachas`: la técnica clásica de gaps and islands. Dentro de un cliente y un nivel, el número de mes menos su posición (`ROW_NUMBER`) se mantiene constante mientras los meses sean consecutivos; cuando cambia el nivel o falta un mes, la diferencia cambia y arranca otra racha. Uso el número de mes y no dos `ROW_NUMBER` precisamente para que un mes inexistente corte la racha.
6. `rachas_priorizadas`: filtro `racha >= n` y me quedo con la primera ordenando por `racha DESC, fecha_fin DESC`, o sea la más larga y, si empatan, la más reciente.

La salida es `identificacion`, `racha`, `fecha_fin` y `nivel`, una fila por cliente. Con `fecha_base = 2024-12-31` y `n = 3` salen 92 clientes; el resultado está en [resultados/rachas_2024-12-31_n3.csv](ejercicio3_rachas/resultados/rachas_2024-12-31_n3.csv).

### Decisiones que tomé donde el enunciado deja espacio

- El enunciado dice que después del retiro no se imputa N0, pero no dice qué hacer con saldos que sí vienen reportados después del retiro. Los conservé: un cliente que se retira puede seguir debiendo, y borrar un saldo real me parece peor que dejarlo. En la práctica solo afecta a un cliente (`THJ9...`) y queda reportado en la bitácora para que negocio decida.
- Un retiro con fecha posterior a la `fecha_base` no cambia nada, porque todos los cortes que se miran son anteriores.
- Los meses faltantes se imputan hasta el último corte que exista en el archivo, no hasta la `fecha_base`. Si la `fecha_base` fuera 2025-06-30 y los datos llegan a diciembre de 2024, imputar hasta junio le inventaría seis meses en N0 a todo el mundo.
- El corte de un mes es su último día y cuenta solo si es menor o igual a la `fecha_base`: con `2024-06-15` el último corte que entra es el de mayo.

### Pruebas

Hay casos pequeños para cada regla del enunciado (los límites exactos de cada nivel, la imputación, el retiro a mitad de mes y a fin de mes, el desempate, el filtro por `n`, cortes y retiros después de la `fecha_base`), un escenario de calidad con cada tipo de error, y la validación cruzada: una implementación independiente en Python puro que se compara con el SQL sobre los datos reales en 40 combinaciones de `fecha_base` y `n`. Si las dos coinciden en todas, me quedo bastante tranquilo.

---

## Ejercicio 4: imágenes de HTML a base64

Paquete `html_base64`, solo librería estándar.

```bash
cd ejercicio4_html_base64
python -m html_base64 ejemplos/sitio                        # genera *_base64.html al lado de cada original
python -m html_base64 a.html b.html carpeta/ -o salida/     # o replica la estructura en otra carpeta
python -m html_base64 ejemplos/sitio --reporte resultado.json --sin-remotas
python -m unittest discover -s tests -v
```

Desde código:

```python
from html_base64 import ejecutar

resultado = ejecutar(["pagina.html", "carpeta/"]).a_dict()
# {
#   "success": {"C:/.../pagina.html": ["img/logo.png", ...]},
#   "fail":    {"C:/.../pagina.html": [{"src": "falta.png", "error": "No existe el archivo ..."}]}
# }
```

La CLI imprime ese mismo objeto en JSON y termina con código 1 si alguna imagen falló, por si se quiere encadenar en un pipeline.

### Cómo lo diseñé

Lo separé en clases con una responsabilidad cada una:

- `BuscadorHtml` recibe archivos o carpetas, recorre subcarpetas, se queda con `.html` y `.htm`, quita duplicados y salta las salidas de corridas anteriores. Si me pasan explícitamente un archivo que no es HTML, lo reporto en `fail` en vez de ignorarlo en silencio.
- `html_img` encuentra las etiquetas `<img>` con `html.parser` (así no me confundo con comentarios, `<script>` o atributos como `data-src`) y reemplaza únicamente el valor del `src` dentro del texto original. El resto del archivo queda idéntico, byte a byte.
- `fuentes` es un Strategy: `FuenteImagen` como clase abstracta y dos implementaciones, `FuenteArchivoLocal` (rutas relativas, absolutas y `file://`) y `FuenteHttp` (`http`, `https` y `//cdn...`, con timeout y tamaño máximo). Para leer de S3, por ejemplo, bastaría con agregar otra clase.
- `detectar_mime` mira la firma binaria del archivo, no la extensión. Si algo dice ser PNG y no lo es, se reporta como fallo en lugar de incrustar basura.
- `ProcesadorHtml` orquesta todo con las fuentes y el destino inyectados, cachea las imágenes y nunca escribe encima de un archivo de entrada. Si un archivo revienta por algo inesperado, se reporta y se sigue con el resto.
- `ReporteProcesamiento` es el objeto `{success, fail}`.

Casos que tuve en cuenta: `src` con comillas dobles, simples o sin comillas (incluso con `=` adentro, como `logo.png?v=2`), entidades como `&amp;`, etiquetas sin `src`, imágenes ya embebidas en `data:` (se dejan quietas), imágenes repetidas (se reportan una vez y una URL se descarga una sola vez), rutas con `\`, con query string o con `%20`, URLs malformadas o que devuelven algo que no es imagen, archivos en UTF-8, Windows-1252 o con BOM (UTF-8, UTF-16, UTF-32) conservando la codificación y los saltos de línea, y salidas que caerían sobre un archivo de entrada o que no se pueden escribir. Una imagen solo cuenta como exitosa si el archivo nuevo se escribió.

Dos supuestos: solo proceso el atributo `src` de `<img>`, como dice el enunciado (`srcset`, `<picture>` y las imágenes de CSS quedan por fuera), y una ruta que empieza por `/` se resuelve como lo haría el navegador con un archivo local, desde la raíz del disco, no desde la raíz de un sitio.

Las pruebas de descarga levantan un servidor HTTP local dentro de la misma prueba, así que corren sin internet.
