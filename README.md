# Bitácora Trader — cómo ponerla en línea (paso a paso, sin experiencia previa)

Esto es una aplicación web real: cuentas de usuario, cada trader carga sus
propias operaciones, y cobra un pago único de por vida con Stripe. Corre en
Python (Flask). Para que otros traders puedan entrar a `tubitacora.com` y
usarla, tenés que "desplegarla" (subirla a un servidor). Esta guía asume que
nunca hiciste esto y te lleva paso a paso.

Vas a necesitar crear TRES cuentas gratis:

1. **GitHub** (github.com) — ahí vive el código.
2. **Render** (render.com) — ahí corre la aplicación (el servidor).
3. **Stripe** (stripe.com) — ahí se procesan los pagos.

Ninguna de las tres pide tarjeta para arrancar en modo gratis/prueba.

---

## Antes de arrancar — lo más importante

**Este proyecto usa una base de datos simple (SQLite) para arrancar rápido y
gratis.** Es perfecta para probar el producto con vos mismo y unos primeros
usuarios de prueba. **Pero antes de cobrarle a un solo cliente real**, tenés
que migrar a una base de datos de verdad (te explico por qué y cómo, más
abajo en "Antes de aceptar pagos reales"). Si no lo hacés, corrés el riesgo
de que un reinicio del servidor borre las cuentas y operaciones de tus
usuarios — y eso, con gente que ya te pagó, es un problema serio de
confianza (y probablemente legal). No es difícil de arreglar, pero hay que
hacerlo antes de abrir las puertas de verdad.

---

## Paso 1 — Subir el código a GitHub (sin usar la terminal)

1. Entrá a [github.com](https://github.com) y creá una cuenta gratis.
2. Arriba a la derecha, hacé clic en el **+** → **New repository**.
3. Ponele un nombre (por ejemplo `bitacora-trader`), dejalo en **Private**,
   y hacé clic en **Create repository**.
4. En la página del repo vacío, buscá el link que dice **"uploading an
   existing file"** (subir un archivo existente).
5. Arrastrá **todos los archivos y carpetas** de esta carpeta que te mandé
   (excepto que no hace falta subir nada más, ya está todo listo) a esa
   página, y hacé clic en **Commit changes**.

Listo, ya tenés el código en GitHub.

---

## Paso 2 — Crear tu cuenta de Stripe (modo de prueba primero)

1. Entrá a [stripe.com](https://stripe.com) y creá una cuenta.
2. Arriba vas a ver un interruptor que dice **"Test mode"** (modo de
   prueba) — dejalo activado. Así podés probar todo el flujo de pago sin
   mover dinero real.
3. Andá a **Desarrolladores → Claves de API** y copiá la **Clave secreta**
   (empieza con `sk_test_...`). La vas a necesitar en el Paso 3.

(El webhook de Stripe lo configuramos en el Paso 4, después de tener la URL
de tu app.)

---

## Paso 3 — Desplegar en Render

1. Entrá a [render.com](https://render.com) y creá una cuenta (podés
   entrar directo con tu cuenta de GitHub, es más rápido).
2. Hacé clic en **New +** → **Web Service**.
3. Conectá tu repositorio `bitacora-trader` de GitHub.
4. Render va a detectar que es Python. Completá:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: la gratis o la más barata para arrancar.
5. Antes de crear el servicio, bajá hasta **Environment Variables** y
   agregá estas (los valores son ejemplos, usá los tuyos):

   | Variable | Valor |
   |---|---|
   | `SECRET_KEY` | un texto largo y random que inventes vos (ej: 40 letras y números al azar) |
   | `STRIPE_SECRET_KEY` | la `sk_test_...` que copiaste en el Paso 2 |
   | `STRIPE_WEBHOOK_SECRET` | dejalo vacío por ahora, lo completamos en el Paso 4 |
   | `PRICE_CENTS` | `9900` (esto es $99.00 — poné el precio que quieras, en centavos) |
   | `PRICE_CURRENCY` | `usd` |
   | `PRODUCT_NAME` | `Bitácora Trader -- acceso de por vida` |

6. Hacé clic en **Create Web Service**. Esperá unos minutos — Render te va
   a dar una URL como `https://bitacora-trader.onrender.com`. Esa es tu
   página.

---

## Paso 4 — Conectar el webhook de Stripe

El webhook es lo que le avisa a tu app cuando alguien pagó de verdad
(sin esto, la cuenta nunca se activa después de pagar).

1. En Stripe (todavía en modo de prueba), andá a **Desarrolladores →
   Webhooks → Añadir destino de eventos**.
2. En la URL del endpoint poné: `https://TU-APP.onrender.com/stripe/webhook`
   (con la URL real que te dio Render).
3. En eventos a escuchar, buscá y marcá **`checkout.session.completed`**.
4. Guardalo. Stripe te va a mostrar un **"Signing secret"** que empieza con
   `whsec_...` — copialo.
5. Volvé a Render → tu servicio → **Environment** → editá
   `STRIPE_WEBHOOK_SECRET` y pegá ese valor. Guardá (Render va a reiniciar
   la app sola).

---

## Paso 5 — Probar todo el flujo (sin gastar plata real)

1. Entrá a tu URL de Render, creá una cuenta de prueba.
2. Te va a pedir pagar — hacé clic en pagar, y cuando Stripe te pida los
   datos de la tarjeta usá la tarjeta de prueba: **4242 4242 4242 4242**,
   cualquier fecha futura, cualquier CVC.
3. Si todo está bien conectado, después de "pagar" tu cuenta queda activada
   y entrás derecho a la bitácora. Cargá una operación de prueba y fijate
   que las métricas se calculen bien.

Si la cuenta no se activa sola, revisá en Stripe → Webhooks → tu endpoint →
"intentos recientes", ahí te dice si Stripe no pudo avisarle a tu app y
por qué.

---

## Paso 6 — Pasar a modo real (cuando quieras cobrar de verdad)

1. En Stripe, completá los datos de tu cuenta (Stripe te va a pedir esto
   para poder recibir pagos reales de verdad — datos personales/del
   negocio, cuenta bancaria).
2. Apagá el interruptor de "Test mode".
3. Repetí el Paso 2 y el Paso 4 pero con las claves que empiezan con
   `sk_live_...` y el webhook en modo real — vas a tener un
   `whsec_...` distinto para real.
4. Actualizá `STRIPE_SECRET_KEY` y `STRIPE_WEBHOOK_SECRET` en Render con
   los valores reales.

---

## Antes de aceptar pagos reales — la base de datos

Por defecto, Render **no garantiza** que el archivo de la base de datos
(`bitacora.db`) sobreviva a un reinicio o un redeploy en el plan gratis —
podrías perder las cuentas y operaciones de tus usuarios. Dos formas de
arreglarlo, de más simple a más robusta:

- **Disco persistente de Render** (necesita un plan pago de Render): le
  agregás un "disco" a tu servicio y le decís a la app que guarde
  `bitacora.db` ahí. Render tiene esto en su documentación bajo "Persistent
  Disks".
- **Base de datos de verdad (recomendado a mediano plazo)**: migrar de
  SQLite a Postgres (Render ofrece Postgres administrado con un par de
  clics). Es más trabajo de código — si llegás a este punto y no te sentís
  cómodo haciéndolo vos, es un buen momento para contratar a un
  desarrollador por unas horas, o pedirme que te arme esa versión.

**No aceptes pagos reales de otras personas hasta resolver esto.** Perder
los datos de un cliente que pagó es un problema serio, no solo técnico.

---

## Lo legal — leélo antes de abrir al público

Te dejé dos borradores en esta carpeta: `TERMINOS_Y_CONDICIONES.md` y
`POLITICA_DE_PRIVACIDAD.md`. Son punto de partida, **no asesoría legal** —
esta app va a guardar datos financieros de otras personas y les vas a
cobrar dinero, así que antes de lanzarlo de verdad convendría que un
abogado (aunque sea una consulta puntual, muchos la dan barata o gratis la
primera vez) los revise y los ajuste a las leyes de tu país. También fijate
si donde vivís hace falta registrar el emprendimiento o declarar estos
ingresos — varía mucho según el país.

---

## Qué NO está construido todavía (para cuando quieras seguir)

- **Análisis con IA** de las estadísticas de cada trader (lo hablamos como
  siguiente paso).
- Recuperar contraseña olvidada.
- Exportar/importar operaciones (backup).
- Edición de una operación ya cargada (por ahora solo se puede borrar y
  volver a cargar).

## Estructura del proyecto

```
app.py              -- todas las rutas de la aplicación
db.py                -- acceso a la base de datos (SQLite)
metrics.py            -- el motor de cálculo (balance, winrate, drawdown, rachas)
stripe_client.py       -- llamadas a Stripe (sin el SDK, con requests + hmac)
templates/            -- las páginas (HTML)
static/style.css       -- estilos, mismos colores/tipografía que tu bitácora personal
```
