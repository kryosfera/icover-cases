#!/usr/bin/env python3
"""Genera site/ (raíz pública del Worker) a partir de la copia de wget de la web en Webflow.

Uso:
    python3 scripts/montar.py [--backup RUTA]

RUTA es la carpeta del backup de icover-cases (la que contiene mirror/, assets/ y
code-export/). Por defecto: $ICOVER_BACKUP o ../ksf-workspace/backups/webflow-2026/icover-cases
relativo a la raíz del repo.

Qué hace (solo cambia rutas; el resto del HTML queda byte a byte igual):
- Copia el HTML de mirror/<dominio>/ a site/ (index.html, favorites.html, use-case/<slug>.html...).
- Copia cada host de recursos (mirror/<host>/...) a site/_ext/<host>/...
- En el HTML reescribe las rutas relativas ../<host>/... a /_ext/<host>/... y los enlaces internos
  x.html a la URL limpia original (/, /favorites, /use-case/<slug>...), conservando query y ancla.
  wget convirtió href="#" en "pagina.html#" y src="" en "pagina.html": se devuelven a "#" y "".
- Las URLs absolutas de Webflow (cdn.prod.website-files.com, assets.website-files.com,
  uploads-ssl.webflow.com) que quedan en metas, JSON del lightbox y plantillas codificadas
  se pasan a /_ext/<host>/... (en metas og/twitter, con el dominio delante porque deben ser absolutas).
  Si el fichero no lo bajó wget, se toma de assets/files/ del backup.
- Escribe las rutas locales en forma canónica ("|" -> %7C, "@" -> %40), en HTML y CSS,
  porque la capa de assets de Cloudflare redirige (307) las que no lo están.
- Deshace sufijos de wget en nombres de recurso (query convertida en "@..." o "?...").
- Genera site/404.html a partir de code-export/404.html con rutas reescritas.
- Añade /_ksf/formularios.js a las páginas con formulario y copia los ficheros de static/.
- Comprueba que todo recurso local referenciado existe y lista los recursos remotos que quedan.
"""
from __future__ import annotations

import argparse
import os
import posixpath
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, unquote

RAIZ = Path(__file__).resolve().parent.parent
DOMINIO = "icover-casecollection.ivascular.global"
ORIGEN = f"https://{DOMINIO}"
HOSTS_WEBFLOW = ("cdn.prod.website-files.com", "assets.website-files.com", "uploads-ssl.webflow.com")
CSS_PUBLICADO = "/_ext/assets.website-files.com/612ca2f6900a4cbc8cb91efd/css/icover-cases.5d6bcd606.css"
JS_PUBLICADO = "/_ext/assets.website-files.com/612ca2f6900a4cbc8cb91efd/js/icover-cases.b7517f583.js"
FAVICON = "/_ext/cdn.prod.website-files.com/612ca2f6900a4cbc8cb91efd/612f46cdf858980e12320c3b_ivascular-logo_32x32.png"
WEBCLIP = "/_ext/cdn.prod.website-files.com/612ca2f6900a4cbc8cb91efd/612f46866227ae47e309ab5f_ivascular-logo_256x256.png"
SCRIPT_FORMULARIOS = '<script src="/_ksf/formularios.js" type="text/javascript"></script>'

ATRIBUTOS = re.compile(r'(\s(?:href|src|srcset|content|poster|data-src|action)=)"([^"]*)"')
ABS_WEBFLOW = re.compile(r"https://(" + "|".join(re.escape(h) for h in HOSTS_WEBFLOW) + r")/")
ABS_WEBFLOW_COD = re.compile(r"https%3A%2F%2F(" + "|".join(re.escape(h) for h in HOSTS_WEBFLOW) + r")%2F")
URL_LOCAL_EXT = re.compile(r"/_ext/([a-z0-9.-]+)/([^\"'\s)<>]+)")
URL_REMOTA = re.compile(r"""(?:https?:)?//[a-zA-Z0-9.-]+\.[a-z]{2,}[^"'\s)<>]*""")


def canonica(ruta: str) -> str:
    """Codifica cada segmento como encodeURIComponent (forma canónica de los assets de Cloudflare)."""
    ruta, sep, resto = ruta.partition("?") if "?" in ruta else ruta.partition("#")
    segs = [quote(unquote(x), safe="-_.!~*'()") for x in ruta.split("/")]
    return "/".join(segs) + sep + resto


class Montaje:
    def __init__(self, backup: Path, salida: Path):
        self.backup = backup
        self.mirror = backup / "mirror"
        self.web = self.mirror / DOMINIO
        self.salida = salida
        self.errores: list[str] = []
        self.renombrados: list[str] = []
        self.anadidos: list[str] = []

    # ---------- utilidades ----------
    def url_limpia(self, ruta: str) -> str:
        """use-case/case-1.html -> /use-case/case-1 ; index.html -> /"""
        if ruta == "index.html":
            return "/"
        if ruta.endswith("/index.html"):
            return "/" + ruta[: -len("index.html")]
        return "/" + (ruta[:-5] if ruta.endswith(".html") else ruta)

    def asegurar_recurso(self, host: str, ruta_codificada: str, contexto: str) -> str:
        """Comprueba que /_ext/<host>/<ruta> existirá en site/. Devuelve la ruta (codificada) final."""
        ruta = unquote(ruta_codificada)
        destino = self.salida / "_ext" / host / ruta
        if destino.is_file():
            return ruta_codificada
        origen = self.mirror / host / ruta
        if origen.is_file():
            return ruta_codificada  # se copiará al copiar el host completo
        # ¿wget añadió un sufijo de query (p. ej. "x.css@v=1" o "x.css?v=1")?
        carpeta = origen.parent
        if carpeta.is_dir():
            for f in carpeta.iterdir():
                if f.name.startswith(origen.name) and f.name[len(origen.name): len(origen.name) + 1] in ("@", "?"):
                    self.renombrados.append(f"{host}/{ruta} <- {f.name}")
                    return ruta_codificada
        # ¿Está en los binarios del CMS del backup?
        nombre = Path(ruta).name
        for cand in (self.backup / "assets" / "files").rglob(nombre):
            if cand.is_file():
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cand, destino)
                self.anadidos.append(f"{host}/{ruta} <- assets/files/{cand.relative_to(self.backup / 'assets' / 'files')}")
                return ruta_codificada
        self.errores.append(f"falta recurso {host}/{ruta} (en {contexto})")
        return ruta_codificada

    # ---------- reescritura de una URL ----------
    def reescribir_url(self, url: str, pagina: str, atributo: str) -> str:
        if url == "" or url.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
            return url
        m = ABS_WEBFLOW.match(url)
        if m:
            host, resto = m.group(1), url[m.end():]
            ruta = resto.split("#")[0].split("?")[0]
            self.asegurar_recurso(host, ruta, pagina)
            local = f"/_ext/{host}/{resto}"
            return ORIGEN + local if atributo == "content" else local
        if re.match(r"^[a-z][a-z0-9+.-]*:|^//", url, re.I):
            return url  # absoluta de terceros: se deja tal cual
        # Relativa (generada por wget): separar ancla y query.
        ruta, _, ancla = url.partition("#")
        ruta, _, query = ruta.partition("?")
        sufijo = ("?" + query if query else "") + ("#" + ancla if "#" in url else "")
        base = posixpath.dirname(f"{DOMINIO}/{pagina}")
        resuelta = posixpath.normpath(posixpath.join(base, ruta))
        host, _, resto = resuelta.partition("/")
        if host == DOMINIO:
            if resto == pagina:
                if "#" in url:
                    return "#" + ancla  # era href="#..." en el original
                if atributo in ("src", "srcset", "poster", "data-src"):
                    return ""  # era src="" (imagen CMS vacía, w-dyn-bind-empty)
            if not (self.web / unquote(resto)).is_file():
                self.errores.append(f"enlace interno a página inexistente {resto} (en {pagina})")
            return self.url_limpia(resto) + sufijo
        if (self.mirror / host).is_dir():
            ruta_final = self.asegurar_recurso(host, resto, pagina)
            return f"/_ext/{host}/{ruta_final}" + sufijo
        self.errores.append(f"ruta relativa no resuelta {url} (en {pagina})")
        return url

    def reescribir_atributo(self, m: re.Match, pagina: str) -> str:
        prefijo, valor = m.group(1), m.group(2)
        atributo = prefijo.strip()[:-1]
        if atributo == "srcset":
            partes = []
            for cand in re.split(r",\s+", valor):
                trozos = cand.strip().split(" ", 1)
                trozos[0] = self.reescribir_url(trozos[0], pagina, "srcset")
                partes.append(" ".join(trozos))
            nuevo = ", ".join(partes)
        elif atributo == "content":
            nuevo = self.reescribir_url(valor, pagina, "content") if ABS_WEBFLOW.match(valor) else valor
        else:
            nuevo = self.reescribir_url(valor, pagina, atributo)
        return f'{prefijo}"{nuevo}"'

    def reescribir_html(self, texto: str, pagina: str) -> str:
        texto = ATRIBUTOS.sub(lambda m: self.reescribir_atributo(m, pagina), texto)

        # URLs absolutas de Webflow dentro de JSON (lightbox) o scripts.
        def abs_plana(m: re.Match) -> str:
            host = m.group(1)
            ruta = re.match(r"[^\"'\s)<>\\]*", texto_actual[m.end():]).group(0)
            self.asegurar_recurso(host, ruta.split("?")[0], pagina)
            return f"/_ext/{host}/"

        texto_actual = texto
        texto = ABS_WEBFLOW.sub(abs_plana, texto)

        # Plantillas de Webflow codificadas (script type="text/x-wf-template").
        def plantilla(m: re.Match) -> str:
            cuerpo = m.group(2)
            for u in re.finditer(r"https://(" + "|".join(re.escape(h) for h in HOSTS_WEBFLOW) + r")/([^\"'\s)<>]*)", unquote(cuerpo)):
                self.asegurar_recurso(u.group(1), u.group(2), pagina + " (plantilla)")
            cuerpo = ABS_WEBFLOW_COD.sub(lambda x: f"%2F_ext%2F{x.group(1)}%2F", cuerpo)
            return m.group(1) + cuerpo + m.group(3)

        texto = re.sub(r'(<script type="text/x-wf-template"[^>]*>)(.*?)(</script>)', plantilla, texto, flags=re.S)
        # La capa de assets de Cloudflare redirige (307) a la forma canónica de la ruta
        # ("|" -> %7C, "@" -> %40...): se escribe ya canónica para evitar la redirección.
        texto = re.sub(r"/_ext/[^\"'\s)<>]*", lambda m: canonica(m.group(0)), texto)
        if ABS_WEBFLOW_COD.search(texto):
            self.errores.append(f"quedan URLs de Webflow codificadas fuera de plantillas (en {pagina})")
        return texto

    # ---------- pasos ----------
    def copiar_hosts(self) -> None:
        for host_dir in sorted(self.mirror.iterdir()):
            if not host_dir.is_dir() or host_dir.name == DOMINIO:
                continue
            for f in sorted(host_dir.rglob("*")):
                if not f.is_file():
                    continue
                rel = f.relative_to(host_dir)
                nombre = rel.name
                # Deshacer sufijos de query que wget pudo añadir al nombre (x.css@v=1 / x.css?v=1).
                limpio = re.sub(r"^(.+\.(?:css|js|png|jpe?g|gif|svg|webp|woff2?|ttf|otf))[@?].*$", r"\1", nombre, flags=re.I)
                if limpio != nombre:
                    self.renombrados.append(f"{host_dir.name}/{rel} -> {limpio}")
                destino = self.salida / "_ext" / host_dir.name / rel.parent / limpio
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, destino)

    def canonizar_css(self) -> None:
        for css in (self.salida / "_ext").rglob("*.css"):
            texto = css.read_text(encoding="utf-8")
            nuevo = re.sub(r"url\((['\"]?)(\.\./[^'\")]+)\1\)", lambda m: f"url({m.group(1)}{canonica(m.group(2))}{m.group(1)})", texto)
            if nuevo != texto:
                css.write_text(nuevo, encoding="utf-8")

    def comprobar_css(self) -> None:
        for css in (self.salida / "_ext").rglob("*.css"):
            texto = css.read_text(encoding="utf-8")
            for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", texto):
                u = m.group(1)
                if u.startswith(("data:", "http:", "https:", "//", "#")):
                    continue
                destino = (css.parent / unquote(u.split("?")[0].split("#")[0])).resolve()
                if not destino.is_file():
                    self.errores.append(f"CSS {css.name}: falta {u}")

    def generar_404(self) -> None:
        origen = self.backup / "code-export" / "404.html"
        if (self.web / "404.html").exists():
            return
        texto = origen.read_text(encoding="utf-8")
        cambios = [
            ('  <link href="css/normalize.css" rel="stylesheet" type="text/css">\n'
             '  <link href="css/components.css" rel="stylesheet" type="text/css">\n'
             '  <link href="css/icover-cases.css" rel="stylesheet" type="text/css">\n',
             f'  <link href="{CSS_PUBLICADO}" rel="stylesheet" type="text/css">\n'),
            ('href="images/favicon.png"', f'href="{FAVICON}"'),
            ('href="images/webclip.png"', f'href="{WEBCLIP}"'),
            ('src="js/icover-cases.js"', f'src="{JS_PUBLICADO}"'),
        ]
        for viejo, nuevo in cambios:
            if viejo not in texto:
                self.errores.append(f"404: no se encuentra {viejo[:40]!r} en code-export/404.html")
            texto = texto.replace(viejo, nuevo)
        restos = re.findall(r'(?:href|src)="(?!https?:|/|#)[^"]+"', texto)
        if restos:
            self.errores.append(f"404: quedan rutas relativas {restos}")
        (self.salida / "404.html").write_text(texto, encoding="utf-8")

    def copiar_estaticos(self) -> None:
        estaticos = RAIZ / "static"
        if estaticos.is_dir():
            shutil.copytree(estaticos, self.salida, dirs_exist_ok=True)

    def comprobar_salida(self) -> dict[str, set[str]]:
        """Verifica que toda ruta /_ext/ referenciada existe y recoge los recursos remotos."""
        remotos: dict[str, set[str]] = {}
        for html in sorted(self.salida.rglob("*.html")):
            pagina = str(html.relative_to(self.salida))
            texto = html.read_text(encoding="utf-8")
            plano = texto + unquote(" ".join(re.findall(r'<script type="text/x-wf-template"[^>]*>(.*?)</script>', texto, re.S)))
            for m in URL_LOCAL_EXT.finditer(plano):
                ruta = m.group(2)
                if "%2F" in ruta or "%22" in ruta:
                    continue  # trozo aún codificado; se comprueba en su forma decodificada
                if not (self.salida / "_ext" / m.group(1) / unquote(ruta.split("?")[0].split("#")[0])).is_file():
                    self.errores.append(f"{pagina}: /_ext/{m.group(1)}/{ruta} no existe")
            if re.search(r'(?:href|src)="(?:\.\./)+', texto) or re.search(r'(?:href|src)="[^"/:#]*\.html', texto):
                self.errores.append(f"{pagina}: quedan rutas relativas de wget")
            for etiqueta in re.finditer(r"<(?:script|link|img|iframe|video|source)\b[^>]*>", texto):
                for u in re.findall(r'(?:src|href)="((?:https?:)?//[^"]+)"', etiqueta.group(0)):
                    host = re.match(r"(?:https?:)?//([^/:]+)", u).group(1)
                    remotos.setdefault(host, set()).add(pagina)
            for u in re.findall(r"s\.src\s*=\s*\"([^\"]+)\"|g\.src\s*=\s*'([^']+)'|\.src=\"(https://[^\"]+)\"", texto):
                v = next(x for x in u if x)
                host = re.match(r"(?:https?:)?//([^/:]+)", v).group(1)
                remotos.setdefault(host, set()).add(pagina)
            # Ninguna URL absoluta a ficheros de Webflow (plana o codificada) debe quedar.
            for m in re.finditer(r"(?://|%2F%2F)([a-z0-9.-]*(?:website-files\.com|webflow\.com))(?:/|%2F)", texto):
                self.errores.append(f"{pagina}: referencia a Webflow sin localizar: {m.group(1)}")
        for css in (self.salida / "_ext").rglob("*.css"):
            for u in re.findall(r"url\(['\"]?((?:https?:)?//[^'\")]+)", css.read_text(encoding="utf-8")):
                host = re.match(r"(?:https?:)?//([^/:]+)", u).group(1)
                remotos.setdefault(host, set()).add(f"CSS {css.name}")
        return remotos

    def ejecutar(self) -> int:
        if not self.web.is_dir():
            print(f"No encuentro {self.web}", file=sys.stderr)
            return 2
        if self.salida.exists():
            shutil.rmtree(self.salida)
        self.salida.mkdir(parents=True)
        self.copiar_hosts()
        paginas = sorted(p.relative_to(self.web).as_posix() for p in self.web.rglob("*.html"))
        for pagina in paginas:
            texto = (self.web / pagina).read_text(encoding="utf-8")
            nuevo = self.reescribir_html(texto, pagina)
            if "<form" in nuevo:
                if nuevo.count("</body>") != 1:
                    self.errores.append(f"{pagina}: no se puede insertar el script de formularios")
                nuevo = nuevo.replace("</body>", SCRIPT_FORMULARIOS + "</body>")
            destino = self.salida / pagina
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(nuevo, encoding="utf-8")
        self.generar_404()
        self.copiar_estaticos()
        self.canonizar_css()
        self.comprobar_css()
        remotos = self.comprobar_salida()

        print(f"site/ generado: {len(paginas)} páginas + 404.html")
        for r in self.renombrados:
            print(f"  renombrado (sufijo de wget): {r}")
        for a in self.anadidos:
            print(f"  añadido desde el backup: {a}")
        print("Recursos remotos que quedan (host: dónde):")
        for host in sorted(remotos):
            dep = "  [WEBFLOW]" if re.search(r"webflow|website-files|d3e54v103j8qbb\.cloudfront\.net", host) else ""
            donde = sorted(remotos[host])
            print(f"  {host}{dep}: {len(donde)} ficheros ({', '.join(donde[:3])}{'…' if len(donde) > 3 else ''})")
        if self.errores:
            print("ERRORES:", file=sys.stderr)
            for e in self.errores:
                print("  " + e, file=sys.stderr)
            return 1
        print("OK: todos los recursos locales referenciados existen.")
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    defecto = os.environ.get("ICOVER_BACKUP") or str(RAIZ.parent / "ksf-workspace/backups/webflow-2026/icover-cases")
    ap.add_argument("--backup", default=defecto, help="carpeta del backup de icover-cases")
    ap.add_argument("--salida", default=str(RAIZ / "site"), help="carpeta de salida (por defecto site/)")
    args = ap.parse_args()
    return Montaje(Path(args.backup), Path(args.salida)).ejecutar()


if __name__ == "__main__":
    sys.exit(main())
