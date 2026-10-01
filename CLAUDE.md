# icover-cases · CLAUDE.md

## Qué es

Web **iCover Case Collection** de iVascular (<https://icover-casecollection.ivascular.global>), migrada de Webflow
(plan del sitio vencía el 09/10/2026) a un Cloudflare Worker con assets estáticos. Cliente: iVascular. Es un
**entorno de producción del cliente: se mantiene al 100 % igual**. No se rediseña ni se “mejora” nada: solo se cambia
el alojamiento.

## Reglas

- **No toques el HTML a mano.** `site/` se genera con `python3 scripts/montar.py` desde el backup de Webflow
  (`ksf-workspace/backups/webflow-2026/icover-cases/`). Si hay que cambiar algo, cámbialo en `montar.py` o en `static/`
  y regenera.
- Después de regenerar, `npm test` debe pasar: `test/comparar_mirror.py` verifica que texto visible, etiquetas y
  atributos (clases, metas, scripts) son idénticos al original y que solo cambian rutas.
- Nada de recursos en dominios de Webflow (`website-files.com`, `webflow.com`): todo va en `site/_ext/<host>/`.
  Los terceros (Google Fonts, GTM, Heap, Matomo, Jetboost, Finsweet, jsDelivr, Vimeo, jQuery de cloudfront) se dejan
  con su URL original.

## Estructura y funcionamiento

Ver README.md. Resumen: `site/` raíz pública; `site/_ext/<host>/` recursos de Webflow; `static/` (formularios.js,
`_headers`) se copia a `site/`; `worker/index.ts` atiende `/api/*` (`run_worker_first`) y deja el resto a los assets;
`src/contacto.ts` valida y reenvía por Resend.

### Formularios

- **Submit job form** (`/submit-case`): `static/_ksf/formularios.js` intercepta el submit (captura en `window`, antes que
  webflow.js), replica la validación y los `alert` de Webflow, hace POST JSON a `/api/contacto` y muestra
  `.w-form-done` / `.w-form-fail` igual que Webflow. Campos (data-name): Name*, Email*, Company Name, Job Title, Job type,
  Description. El email llega a `CONTACT_TO` con las etiquetas visibles (Your Name, Hospital, Speciality, Category…).
- **Email Form** (home): no es de contacto, es el bloque de búsqueda y filtros de Jetboost. Su envío (Intro en la
  búsqueda) se anula y no se manda nada; en Webflow mandaba la búsqueda a Webflow y ocultaba los filtros.
- Sin Turnstile (decisión: el widget alteraría el diseño). Defensa: campo trampa `web` inyectado por JS, límite de
  32 KB, solo JSON, Origin del mismo host, lista blanca de campos y longitudes (las del HTML: 256 y 5000).

### Jetboost (sin sustituir; probar en la vista previa)

`JETBOOST_SITE_ID = ckszslyw20bm50uzuapt2dcm4`. Funciones por página:
- `/`: búsqueda de texto (`54nw`), filtro por autor con checkboxes (`rml5`), filtro por tipo con botones (`r679`),
  botones de reset, estado vacío, estrella de favoritos en cada caso y contador de favoritos (`9o2r`).
- `/favorites`: lista de favoritos (`jetboost-favorites-list-9o2r`), estrellas y contador.
- `/use-case/*`: estrella de favorito y contador. `/authors/*`: estrella, contador y wrappers de lista.
- `/archive-authors`, `/submit-case`: solo el contador de favoritos del menú.

## Estado y siguientes pasos

**01/10/2026 · Migración de alojamiento hecha (pendiente de publicar).**

Hecho:
- `site/` generado desde el mirror: 16 páginas + 404, 108 recursos de Webflow alojados en `_ext/`; comparación con el mirror OK (texto, etiquetas,
  atributos y scripts inline idénticos). Capturas a 1440 px de la home y de un caso: idénticas píxel a píxel al original.
- og:image (banner) que wget no bajó, recuperado de `assets/files/` y servido desde `/_ext/`; meta con URL absoluta del dominio.
- Rutas locales en forma canónica (`|` → `%7C`, `@` → `%40`) para evitar las redirecciones 307 de la capa de assets.
- Worker + `/api/contacto` con 16 tests; `wrangler dev` y `deploy --dry-run` OK.

Pendiente:
- **Desplegar** (`npx wrangler deploy`) y configurar `RESEND_API_KEY`, `CONTACT_TO`, `CONTACT_FROM`.
- **Destino de los formularios**: confirmar con iVascular a quién llegan los casos (`CONTACT_TO`) y el remitente.
  El backup no dice a quién notificaba Webflow; confirmar quién los recibía.
- **Probar Jetboost** en la URL de vista previa (`*.workers.dev`): búsqueda, filtros y favoritos. Jetboost se licencia
  por sitio de Webflow y sincroniza el CMS de Webflow; puede limitar dominios o dejar de funcionar al cancelar el plan.
  Si falla: plan B en el informe `ksf-workspace/.superpowers/sdd/icover-cases-report.md` (sustitución propia).
- **CNAME de iVascular**: pedirles que apunten `icover-casecollection.ivascular.global` al Worker antes del 09/10.
- Recursos remotos que siguen en el CDN de Webflow (`d3e54v103j8qbb.cloudfront.net`): jQuery 3.5.1, dos imágenes del CSS
  (`background-image.svg`, checkmark de checkbox) y la imagen de la 404. No dependen del plan, pero conviene alojarlos
  cuando haya red (descargarlos y añadirlos en `montar.py`).
- Matomo/Heap/GA siguen igual; no se ha tocado la analítica.
