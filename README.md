# icover-cases

Web **iCover Case Collection** de iVascular — <https://icover-casecollection.ivascular.global> —, sacada de Webflow
y alojada en un **Cloudflare Worker con assets estáticos**.

La web se mantiene **100 % igual** (es un entorno de producción del cliente): mismo HTML, mismas clases, mismas metas,
mismos scripts (Google Analytics, Heap, Matomo, Jetboost, Finsweet) y mismo CSS/JS de Webflow. Solo cambian las rutas
de los recursos (que ahora se sirven desde este Worker) y el destino del formulario «Submit a case».

## Estructura

```
site/                  Raíz pública (generada con scripts/montar.py y versionada; no hay build)
  index.html, favorites.html, submit-case.html, archive-authors.html
  use-case/<slug>.html, authors/<slug>.html
  404.html             Generada desde code-export/404.html de Webflow
  _ext/<host>/...      Recursos que servía Webflow (cdn.prod.website-files.com, assets.website-files.com)
  _ksf/formularios.js  Envío de formularios a /api/contacto (copiado de static/)
  _headers             X-Content-Type-Options: nosniff (copiado de static/)
static/                Ficheros propios que montar.py copia a site/
scripts/montar.py      Genera site/ desde el mirror de wget del backup (Python 3, sin dependencias)
src/contacto.ts        Lógica de /api/contacto (validación con lista blanca, Resend)
worker/index.ts        Worker: /api/* → contacto; el resto, assets
test/                  contacto.test.ts (node:test) y comparar_mirror.py (site/ frente al mirror)
wrangler.jsonc         Configuración del Worker `icover-cases`
```

URLs limpias como en Webflow (`/`, `/favorites`, `/submit-case`, `/archive-authors`, `/use-case/<slug>`,
`/authors/<slug>`) gracias a `html_handling: drop-trailing-slash`. Lo que no existe devuelve `404.html`.

## Regenerar site/

El origen es la copia de Webflow en el repo `kryosfera/ksf-workspace`, carpeta `backups/webflow-2026/icover-cases/`
(`mirror/`, `assets/files/`, `code-export/`).

```bash
python3 scripts/montar.py                       # busca ../ksf-workspace/backups/webflow-2026/icover-cases
python3 scripts/montar.py --backup /ruta/al/backup/icover-cases
npm test                                        # tests del endpoint + comparación con el mirror
```

`montar.py` borra y rehace `site/`, comprueba que todo recurso local referenciado existe y lista los recursos remotos
que quedan. Si `wrangler dev` estaba arrancado, reinícialo después (al borrar `site/` deja de servir).

## Desarrollo y despliegue

```bash
npx -y wrangler@4 dev                 # http://localhost:8787
npx -y wrangler@4 deploy --dry-run
npx -y wrangler@4 deploy              # Worker «icover-cases»
```

Variables del Worker (panel de Cloudflare → Worker → Settings → Variables, o `wrangler secret put`):

| Variable | Qué es |
|---|---|
| `RESEND_API_KEY` | Clave de Resend (secreto) |
| `CONTACT_TO` | Destinatario(s) de los envíos de «Submit a case», separados por comas. **Sin valor por defecto** |
| `CONTACT_FROM` | Remitente verificado en Resend (p. ej. `web@ksf.es`) |

Sin ellas, `/api/contacto` responde 500 y la web muestra el mensaje de error de Webflow («Oops! Something went wrong…»).

Dominio: iVascular debe apuntar `icover-casecollection.ivascular.global` (CNAME) al Worker, o añadirlo como
*Custom domain* si la zona `ivascular.global` está en Cloudflare.
