# Guía paso a paso: poner cadvcs en marcha desde cero

Esta guía te lleva de la mano. No damos nada por sabido. Si nunca has tocado una terminal, también es para ti. Vamos despacio y explicamos el *porqué* de cada cosa, no solo el *qué*.

---

## 1. ¿Qué es esto y para qué sirve?

Imagina que dibujas planos en el ordenador (de una pieza, una casa, un circuito). Cada día cambias algo: mueves una línea, añades un círculo, borras una pieza. Al cabo de un mes tienes veinte versiones del mismo plano con nombres como `plano_final.dwg`, `plano_final_BUENO.dwg`, `plano_final_este_si.dwg`. Un desastre.

**cadvcs** es como una máquina del tiempo para tus planos. Guarda cada versión, te deja ver qué cambió entre dos de ellas, y si dos personas editan el mismo plano a la vez, te ayuda a juntar sus cambios sin perder nada. Es lo que hace "Git" para los programadores, pero pensado para planos CAD (archivos `.dxf` y `.dwg`).

Piensa en estas cuatro palabras, que repetiremos mucho:

- **Repositorio**: la caja donde vive un proyecto con toda su historia. Como un álbum de fotos del plano a lo largo del tiempo.
- **Commit**: una foto del plano en un momento concreto, con una nota tuya ("moví la columna 2 metros"). Cada foto se guarda para siempre.
- **Rama** (*branch*): una línea de trabajo paralela. Como hacer una fotocopia para probar una idea loca sin estropear el original.
- **Fusión** (*merge*): juntar dos ramas en una. Aquí es donde cadvcs brilla: si dos personas cambiaron cosas distintas, las junta solo; si chocan en lo mismo, te pregunta cuál quieres.

---

## 2. Lo que necesitas tener instalado

Para la versión más sencilla solo hace falta **Python** (el lenguaje en el que está escrito cadvcs). Para la versión completa (con base de datos de verdad y servicios) hace falta **Docker**. Vamos a explicar las dos.

### Comprobar si ya los tienes

Abre una **terminal** (en Windows se llama "PowerShell" o "Símbolo del sistema"; en Mac y Linux, "Terminal"). Escribe esto y pulsa Enter:

```bash
python3 --version
```

Si responde algo como `Python 3.10.x` o superior, lo tienes. Si dice "no se encuentra", instala Python desde [python.org](https://www.python.org/downloads/) (marca la casilla "Add Python to PATH" durante la instalación en Windows).

Para Docker (lo necesitarás más adelante, no ahora):

```bash
docker --version
```

Si no lo tienes, descárgalo de [docker.com](https://www.docker.com/products/docker-desktop/). Pero **no lo necesitas para empezar**, así que no te preocupes todavía.

---

## 3. Conseguir cadvcs y prepararlo

### Paso 3.1 — Descargar el código

```bash
git clone https://github.com/EroPerez/cadvcs.git
cd cadvcs
```

El primer comando copia todo el proyecto a tu ordenador. El segundo (`cd`, de *change directory*) te mete dentro de la carpeta que se acaba de crear. A partir de aquí, todos los comandos se ejecutan desde dentro de esa carpeta.

> Si no tienes `git`, puedes descargar el proyecto como ZIP desde la página de GitHub (botón verde "Code" → "Download ZIP"), descomprimirlo, y entrar en la carpeta con `cd`.

### Paso 3.2 — Crear un "entorno aislado" para Python

Esto suena técnico pero es sencillo. Un *entorno virtual* es como una caja de herramientas separada solo para este proyecto, para que las cosas que instalemos no se mezclen con el resto de tu ordenador.

```bash
python3 -m venv .venv
```

Esto crea una carpeta `.venv`. Ahora hay que **activarla** (entrar en la caja):

- En **Mac o Linux**:
  ```bash
  source .venv/bin/activate
  ```
- En **Windows** (PowerShell):
  ```powershell
  .venv\Scripts\Activate.ps1
  ```

Sabrás que funcionó porque al principio de la línea de la terminal aparecerá `(.venv)`. A partir de ahora, mientras veas ese `(.venv)`, estás dentro de la caja.

### Paso 3.3 — Instalar cadvcs y sus piezas

```bash
pip install -e ".[dev]"
```

`pip` es el instalador de Python. Este comando lee la lista de piezas que cadvcs necesita y las descarga. El `-e` significa "modo editable" (los cambios al código se reflejan al instante) y `[dev]` añade las herramientas de desarrollo y prueba. Tardará un minuto.

¿Funcionó? Compruébalo:

```bash
python -m cadvcs.cli --help
```

Si ves una lista de comandos (`init`, `commit`, `log`, `merge`...), ¡lo tienes funcionando! 🎉

---

## 4. Tu primer proyecto (la forma más sencilla, sin nada extra)

Esta es la manera más simple de usar cadvcs: desde la terminal, sin base de datos ni servidores. Todo se guarda en archivos en tu disco. Perfecto para aprender y para uso personal.

### Paso 4.1 — Crear el repositorio

Haz una carpeta para tu proyecto y entra en ella:

```bash
mkdir mi-proyecto
cd mi-proyecto
python -m cadvcs.cli init
```

`init` (de *initialize*, inicializar) crea la "caja con historia" dentro de esta carpeta. Por dentro aparece una carpeta oculta `.cadvcs` donde cadvcs guarda todo. No la toques a mano; es su cocina.

### Paso 4.2 — Meter un plano

Copia o crea un archivo `.dxf` en esta carpeta (un plano CAD; cualquier programa de dibujo técnico exporta a ese formato). Digamos que se llama `plano.dxf`. Ahora dile a cadvcs que lo vigile:

```bash
python -m cadvcs.cli add plano.dxf
```

`add` (añadir) significa "quiero que sigas este archivo". Es como poner una foto en el álbum pero todavía sin pegarla.

### Paso 4.3 — Hacer tu primer commit (la primera foto)

```bash
python -m cadvcs.cli commit --user tu_nombre -m "Primera versión del plano"
```

`commit` toma la foto y la guarda para siempre. Dos partes importantes:
- `--user tu_nombre` dice **quién** hace la foto (pon tu nombre, sin espacios: `ana`, `juan_perez`). Es obligatorio, para que quede registrado quién hizo cada cambio.
- `-m` (de *message*, mensaje) es tu nota explicando qué hay en esta versión.

**Pon siempre un mensaje claro**: tu yo del futuro te lo agradecerá.

### Paso 4.4 — Ver la historia

```bash
python -m cadvcs.cli log
```

`log` te muestra la lista de todas las fotos (commits) que has hecho, de la más nueva a la más vieja. Cada una tiene un número (c1, c2, c3...), tu nombre y tu mensaje.

### Paso 4.5 — Hacer un cambio y ver qué cambió

Abre `plano.dxf` en tu programa de CAD, mueve algo, guárdalo. Vuelve a la terminal:

```bash
python -m cadvcs.cli status
```

`status` te dice qué archivos han cambiado desde la última foto. Verás `plano.dxf` en "modificados". Ahora guarda esta nueva versión:

```bash
python -m cadvcs.cli commit --user tu_nombre -m "Moví la columna central"
```

Y mira la diferencia entre las dos versiones:

```bash
python -m cadvcs.cli diff 1 2
```

`diff` (de *difference*, diferencia) te dice qué entidades (líneas, círculos...) se añadieron, se borraron o se movieron entre la foto 1 y la foto 2. Esto es magia: no compara los archivos byte a byte, sino las **piezas del dibujo**.

> **Ojo a un detalle:** cuando haces `log`, las fotos aparecen con una "c" delante (`c1`, `c2`). Pero al comparar con `diff` se usa solo el número, **sin la c**: `diff 1 2`, no `diff c1 c2`. También puedes comparar ramas por su nombre: `diff main idea-nueva`.

### Paso 4.6 — Probar una idea sin miedo (ramas)

¿Quieres probar un rediseño arriesgado sin estropear lo bueno? Haz una rama:

```bash
python -m cadvcs.cli branch idea-nueva
python -m cadvcs.cli switch idea-nueva
```

`branch` crea la línea paralela; `switch` te cambia a ella. Ahora cualquier commit que hagas va a "idea-nueva" y no toca tu trabajo principal (que se llama `main`). Si la idea sale bien, la fusionas; si sale mal, la borras y no ha pasado nada.

Para volver a lo principal:

```bash
python -m cadvcs.cli switch main
```

### Paso 4.7 — Juntar dos ramas (fusión)

Estando en `main`, para traer los cambios de tu rama:

```bash
python -m cadvcs.cli merge idea-nueva --user tu_nombre -m "Junto la idea nueva"
```

Igual que en `commit`, la fusión necesita `--user tu_nombre` (quién la hace) y acepta un `-m` con la nota.

Si los cambios no chocan, se juntan solos. Si ambas ramas tocaron la misma pieza del plano, cadvcs te avisará de un "conflicto" y te dirá qué piezas resolver. Para eso, más adelante, está la interfaz web (sección 6), que lo hace visual y fácil.

---

## 5. La versión completa: con servidor y servicios (usando Docker)

La sección 4 te basta para trabajar tú solo. Pero si quieres que **varias personas** usen los mismos repositorios a través de la red, con una base de datos de verdad, conversión de archivos `.dwg`, y una página web, necesitas levantar el "servidor" completo. Aquí es donde entra Docker.

### ¿Por qué Docker?

El servidor completo tiene varias piezas que deben funcionar juntas: una base de datos, un sistema de mensajes, una memoria rápida, etc. Instalar y configurar cada una a mano es un lío. Docker es como una caja de mudanzas mágica: cada pieza viene en su propia caja lista para usar, y un solo comando las enciende todas y las conecta entre sí.

### Las piezas que se encienden (y qué hace cada una)

Cuando levantes el sistema completo, arrancan seis cajas. No te asustes; aquí va qué hace cada una con una analogía:

| Pieza | Qué es | Analogía |
|-------|--------|----------|
| **api** | El cerebro al que todos hablan | La recepción de un hotel: recibe peticiones y responde |
| **db** (PostgreSQL) | La base de datos | El archivo donde se anota quién hizo qué y cuándo |
| **redis** | Memoria súper rápida | Una libreta de notas a mano para no recalcular cosas |
| **kafka** | Cola de tareas | La cinta transportadora de una fábrica que reparte trabajo |
| **relay** | Pone tareas en la cinta | El operario que coloca paquetes en la cinta |
| **worker** | Hace las tareas pesadas | Los operarios al final de la cinta que procesan cada paquete |

La idea importante: cuando subes un plano, la recepción (api) no se pone a hacer el trabajo pesado (analizar el dibujo, convertir un `.dwg`) ella misma, porque tardaría y haría esperar a todos. En vez de eso, anota la tarea y la pone en la cinta (kafka). Los operarios (workers) la recogen cuando pueden. Así la recepción siempre responde rápido.

### Paso 5.1 — Preparar la contraseña

El sistema usa una contraseña para la base de datos. Hay un archivo de ejemplo; cópialo y ponle tus valores:

```bash
cp .env.example .env
```

Abre el archivo `.env` con cualquier editor de texto y pon una contraseña en `POSTGRES_PASSWORD` (algo como `mi_clave_secreta_123`). Guarda y cierra.

### Paso 5.2 — Encender todo

Desde la carpeta principal de cadvcs (donde está el archivo `docker-compose.yml`):

```bash
docker compose up -d
```

`docker compose up` enciende todas las cajas. El `-d` (de *detached*, separado) las deja corriendo en segundo plano para que recuperes la terminal. La primera vez tardará varios minutos porque descarga las cajas; las siguientes será rápido.

### Paso 5.3 — Comprobar que está vivo

```bash
curl http://localhost:8000/health
```

`curl` es una herramienta para hablar con servidores web desde la terminal. `localhost:8000` significa "mi propio ordenador, puerta 8000", que es donde escucha la api. Si responde algo con `"status": "ok"`, ¡el sistema está en marcha! La respuesta también te dice qué piezas están activas (base de datos, redis, kafka, conversor de dwg).

> Si prefieres verlo en el navegador, abre `http://localhost:8000/health` directamente.

### Paso 5.4 — Apagar todo

Cuando termines:

```bash
docker compose down
```

Esto apaga las cajas pero **conserva tus datos** (viven en "volúmenes" que sobreviven al apagado). La próxima vez que hagas `up`, todo sigue ahí.

---

## 6. La página web (la forma más fácil y bonita de usarlo)

Con el sistema completo encendido (sección 5), abre tu navegador y ve a:

```
http://localhost:8000/ui/
```

Esta es la interfaz visual. Aquí puedes, sin escribir comandos:

- **Ver tus repositorios** en la columna de la izquierda, y crear nuevos.
- **Historial**: la lista de versiones, con las ramas y etiquetas marcadas.
- **Comparar**: elige dos versiones y un plano, y verás el dibujo con los cambios pintados en colores (verde = añadido, ámbar = modificado, rojo = eliminado).
- **Fusionar**: junta ramas. Y si hay conflicto, aparece el **resolutor visual**: cada pieza en disputa se muestra con sus dos versiones (la tuya y la de la otra rama), y tú haces clic en la que quieres conservar. Cuando resuelves todas, pulsas un botón y listo. Esta es la parte estrella del programa.
- **Autoría**: quién hizo cada pieza del plano.
- **Bloqueos**: para planos `.dwg` (que no se pueden fusionar pieza a pieza), puedes "bloquear" un archivo para que nadie más lo edite mientras tú trabajas.

Si tu sistema usa autenticación (ver sección 7), arriba a la derecha hay una casilla para pegar tu "token" (tu llave de acceso). Sin autenticación (modo de pruebas), no hace falta.

---

## 7. Encender las piezas avanzadas (opcional)

Estas piezas son **opcionales**. El sistema funciona sin ellas; si las enciendes, gana capacidades. Se controlan con "variables de entorno" (ajustes que le pasas al programa al arrancar). En el archivo `.env` o al lanzar Docker.

### Convertir archivos `.dwg`

Los planos vienen en dos sabores: `.dxf` (abierto, cadvcs lo entiende del todo) y `.dwg` (cerrado, propiedad de una empresa). Para que cadvcs pueda comparar piezas dentro de un `.dwg`, necesita convertirlo a `.dxf` por dentro. Eso lo hace un "conversor", que es software de pago aparte. Eliges cuál con:

```
CADVCS_DWG_CONVERTER=aspose      # usa la librería Aspose.CAD (necesita licencia)
CADVCS_DWG_CONVERTER=oda         # usa el ODA File Converter (programa externo)
CADVCS_DWG_CONVERTER=none        # (por defecto) sin conversor: el .dwg se guarda
                                 # pero no se puede comparar pieza a pieza
```

Sin conversor, un `.dwg` se guarda y versiona perfectamente como archivo, solo que cadvcs no mira dentro. Cuando consigas la licencia de Aspose o instales ODA, cambias esta variable y ya está; nada más cambia.

### Memoria rápida (Redis)

Para que las comparaciones visuales no se recalculen cada vez:

```
CADVCS_REDIS_URL=redis://redis:6379/0
```

Si no la pones, simplemente recalcula cada vez (más lento, pero funciona igual).

### Cola de tareas (Kafka)

Para repartir el trabajo pesado entre varios operarios:

```
CADVCS_KAFKA_BROKERS=kafka:9092
```

Sin ella, un único proceso hace las tareas en orden (suficiente para empezar).

### Guardar planos en la nube (S3)

Por defecto los planos se guardan en tu disco. Para guardarlos en almacenamiento en la nube (Amazon S3, o equivalentes como OCI o MinIO):

```
CADVCS_BLOB_URL=s3://nombre-de-tu-cubo/carpeta
```

### Pedir contraseña para entrar (autenticación)

Por defecto, en modo de pruebas, cualquiera puede usar la api. Para producción, se conecta a un sistema de login (OIDC, el mismo que usan "Entrar con Google" y similares):

```
CADVCS_OIDC_ISSUER=https://tu-servidor-de-login.com
CADVCS_OIDC_AUDIENCE=cadvcs
```

A partir de ahí, cada petición necesita una "llave" (token) válida, y según tu rol puedes mirar (viewer), editar (editor) o administrar (admin).

---

## 8. Si algo va mal (problemas típicos)

**"command not found: python3"** — Python no está instalado o no está en el PATH. Reinstálalo marcando "Add to PATH" (sección 2).

**El `(.venv)` no aparece** — No activaste el entorno. Vuelve al paso 3.2 y ejecuta el comando de activación. Cada vez que abres una terminal nueva, hay que activarlo de nuevo.

**"the following arguments are required: --user"** — Olvidaste decir quién hace el commit. Añade `--user tu_nombre` al comando: `commit --user ana -m "..."`.

**"Ref desconocida: c1"** — Al comparar con `diff`, usa el número **sin la "c"**: `diff 1 2`. La "c" solo aparece cuando miras el `log`.

**"Nada que commitear"** — No has cambiado ningún archivo desde la última foto, o no añadiste el archivo con `add` primero. Comprueba con `status`.

**`docker compose up` falla** — Asegúrate de que Docker Desktop está abierto y funcionando (su icono debe estar en la barra de tareas). En Linux, que el servicio de Docker esté arrancado.

**La web en `localhost:8000/ui/` no carga** — El sistema no está encendido. Comprueba con `docker compose ps` que las cajas están "running", y con `curl http://localhost:8000/health` que la api responde.

**Quiero empezar de cero** — `docker compose down -v` apaga todo y **borra los datos** (el `-v` borra los volúmenes). Úsalo con cuidado: no hay vuelta atrás.

---

## 9. Resumen de los comandos que más usarás

Trabajando tú solo desde la terminal (sección 4):

```bash
python -m cadvcs.cli init                    # crear el repositorio
python -m cadvcs.cli add ARCHIVO             # empezar a vigilar un archivo
python -m cadvcs.cli commit --user TU_NOMBRE -m "MENSAJE"   # guardar una foto
python -m cadvcs.cli status                  # ver qué cambió
python -m cadvcs.cli log                      # ver la historia
python -m cadvcs.cli diff 1 2                # comparar versiones 1 y 2 (sin la "c")
python -m cadvcs.cli branch NOMBRE           # crear una rama
python -m cadvcs.cli switch NOMBRE           # cambiar de rama
python -m cadvcs.cli merge NOMBRE --user TU_NOMBRE -m "MENSAJE"  # fusionar
```

Usando el sistema completo (sección 5):

```bash
docker compose up -d                          # encender todo
docker compose ps                             # ver qué está corriendo
docker compose logs api                       # ver los mensajes de la api
curl http://localhost:8000/health             # comprobar que está vivo
docker compose down                           # apagar (conserva datos)
```

---

## 10. ¿Y ahora qué?

Si has llegado hasta aquí, ya sabes lo esencial. Para profundizar:

- Cada pieza del sistema tiene su explicación técnica detallada en `docs/specs/` (numeradas del 1 al 18).
- La visión de conjunto está en `ARCHITECTURE.md`.
- El índice de toda la documentación está en `docs/README.md`.

Empieza por la sección 4 (tú solo, en tu ordenador). Cuando le cojas el truco, monta el sistema completo de la sección 5. Y recuerda: cada foto que tomas (commit) se guarda para siempre, así que **no puedes romper nada de forma permanente**. Experimenta sin miedo.
