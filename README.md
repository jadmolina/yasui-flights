# Yasui Flights (安い = barato)

Página web donde familia y amigos entran con su email (sin contraseña: les llega un código),
escogen a dónde quieren viajar, y reciben por email **solo** los vuelos baratos y errores de tarifa
saliendo de **San Juan (SJU)** hacia esos lugares.

## Cómo funciona

1. **Entrar:** la persona pone su email y le llega un código de 6 números, nuevo y al azar cada vez.
2. **Escoger destinos:** ciudades (Tokio, Madrid...), países (Japón...), regiones (Europa, Hawaii...),
   "cualquier error de tarifa", o **"No tengo destino fijo"** (lo más barato a cualquier lugar desde SJU).
   Al guardar ve la pantalla de **¡Listo!**
3. **Cada 4 horas** GitHub corre el buscador:
   - **Aviasales (Travelpayouts):** lo más barato desde SJU a todos lados + cada destino que la gente escogió.
   - **The Flight Deal y Fly4free:** ofertas y errores de tarifa publicados (sus feeds RSS).
   - Todo es por vías permitidas: la API oficial de Aviasales y feeds que los sitios publican.
     Google Flights está apagado (no tiene API oficial); los botones "Google Flights" son solo links.
   - **Combinados:** ofertas que salen de ciudades de EE.UU. (Miami, Nueva York, Los Ángeles...)
     + lo que cuesta llegar desde SJU. Ej.: *SJU → Los Ángeles $289 + Los Ángeles → Osaka $262 = $551*
     (directo desde SJU ~$1,080). El vuelo SJU → ciudad puente tiene que salir 1-2 días antes y regresar
     1-2 días después; si Aviasales no tiene un precio real para esas fechas, el combinado no sale.
     Siempre avisa que son boletos separados, y si hay que cambiar de aeropuerto.
4. **Emails:** cada persona recibe su propio email (nadie ve a los demás) desde yasuiflights@gmail.com,
   solo con lo de sus destinos. El primero es de bienvenida con los precios de hoy. No se repite la misma
   oferta en 14 días a menos que baje otro 10%. Cada email trae un link para darse de baja.

**Qué cuenta como oferta**

- **Posible error de tarifa:** 60% o menos del precio meta, la mitad (o menos) de lo normal, o un sitio lo reportó como error.
- **Ganga:** debajo del precio meta, o 35%+ más barato que lo normal.
- Los precios meta por región están en `config.yaml`. "Lo normal" se aprende solo con unos 4 días de datos.

---

## Ver la demo (sin cuentas ni claves)

```bash
cd ~/Sites/vuelos-baratos
bash instalar.sh
bash buscar.sh --demo
```

Se abre `docs/demo.html` con datos inventados. El código para entrar en la demo es **123456**.

---

## Montarlo de verdad

Necesitas: el token de Travelpayouts, el App Password de yasuiflights@gmail.com, una cuenta de
**GitHub** y una de **Supabase** (las dos gratis).

### 1. GitHub: subir el proyecto

1. Crea un repositorio **público** llamado `yasui-flights` (público para que Pages y Actions sean gratis;
   las claves van en *Secrets* y no se ven).
2. Sube la carpeta:
   ```bash
   cd ~/Sites/vuelos-baratos
   git init && git add . && git commit -m "Yasui Flights"
   git branch -M main
   git remote add origin https://github.com/TU_USUARIO/yasui-flights.git
   git push -u origin main
   ```
3. **Settings → Pages** → Source: *Deploy from a branch* → `main` / `docs` → Save.
   Tu link queda: `https://TU_USUARIO.github.io/yasui-flights/`

### 2. Supabase: usuarios y login con código

1. En [supabase.com](https://supabase.com) entra con **Continue with GitHub** y crea un proyecto
   (nombre `yasui-flights`, región *East US*). Guarda la contraseña de la base de datos.
2. **SQL Editor → New query**, pega todo `supabase/esquema.sql` y dale **Run**.
3. **Authentication → Sign In / Providers → Email:** que esté activado, y en *Email OTP Expiration* pon `600` (10 minutos).
4. **Authentication → Emails → SMTP Settings:** activa *custom SMTP*:
   - Host `smtp.gmail.com`, puerto `465`
   - Username: `yasuiflights@gmail.com`, Password: el App Password (16 letras)
   - Sender email: `yasuiflights@gmail.com`, Sender name: `Yasui Flights`
5. **Authentication → Emails → Templates:** en **Magic Link** y en **Confirm signup**:
   - Subject: `Tu código de Yasui Flights: {{ .Token }}`
   - Body: pega `supabase/email-codigo.html`
6. **Authentication → URL Configuration:** *Site URL* = tu link de GitHub Pages.
7. **Project Settings → API Keys:** copia el *Project URL*, la **publishable key** y la **secret key**.

### 3. GitHub: claves y primera corrida

En el repo, **Settings → Secrets and variables → Actions**:

| Pestaña | Nombre | Valor |
|---|---|---|
| Secrets | `TRAVELPAYOUTS_TOKEN` | token de Travelpayouts |
| Secrets | `GMAIL_USER` | `yasuiflights@gmail.com` |
| Secrets | `GMAIL_APP_PASSWORD` | las 16 letras |
| Secrets | `SUPABASE_SECRET_KEY` | la secret key (`sb_secret_...`) |
| Variables | `SUPABASE_URL` | `https://xxxx.supabase.co` |
| Variables | `SUPABASE_PUBLISHABLE_KEY` | la publishable key (`sb_publishable_...`, es pública) |
| Variables | `SITE_URL` | tu link de GitHub Pages |

Después: **Actions → Yasui Flights → Run workflow**. En unos minutos la página queda en tu link.
Entra tú primero, escoge tus destinos, y comparte el link con la familia.

---

## Correrlo en la Mac (opcional)

Pon las mismas claves en `.env` (`open -e .env`) y:

```bash
bash buscar.sh              # busca, actualiza la página y manda los emails
bash buscar.sh --sin-email  # sin mandar emails
bash buscar.sh --probar-email
```

Ojo: si GitHub ya está corriendo cada 4 horas, no lo corras también en la Mac con emails,
o le pueden llegar repetidos a la gente. Usa `--sin-email` para probar.

## Ajustar

Todo está en `config.yaml`: destinos base, precios meta por región, ciudades puente para combinados,
cuántos emails/ofertas, fuentes.

## Cosas a saber

- Los errores de tarifa duran horas. Desde PR aplica la regla de 24 horas del DOT: si reservas con 7+
  días de anticipación puedes cancelar gratis dentro de 24 horas.
- Los combinados son boletos separados: si el primer vuelo se atrasa, la otra aerolínea no responde.
  Llega un día antes.
- Gmail deja mandar ~500 emails al día; sobra para familia y amigos.
- Supabase pausa proyectos gratis después de 7 días sin uso; como el buscador lo usa cada 4 horas, no pasa.
- Google Flights, Secret Flying y Reddit no se usan: no permiten buscar con programas.

## Archivos

```
run.py                     programa principal
config.yaml                destinos base, metas, ciudades puente, emails
supabase/esquema.sql       tablas y seguridad de Supabase (pegar en el SQL Editor)
supabase/email-codigo.html el email con el código para entrar
vuelos/                    el código: fuentes, detector, combinados, emails, página
vuelos/app.html            la página (login, destinos, ¡Listo!, ofertas)
docs/                      lo que publica GitHub Pages (se genera solo)
data/                      historial de precios (se guarda solo)
.github/workflows/         la tarea que corre cada 4 horas
```
