#!/usr/bin/env python3
"""Compara cada página de site/ con su original del mirror de wget.

Comprueba, página a página, que solo han cambiado rutas:
- el texto visible es idéntico;
- mismo número de imágenes, enlaces, scripts, metas, links y formularios
  (salvo el <script src="/_ksf/formularios.js"> añadido en las páginas con formulario);
- misma secuencia de etiquetas con los mismos atributos (clases, ids, data-*, metas...),
  ignorando solo los valores de los atributos de URL (href, src, srcset y content de og/twitter:image);
- los <head> tienen las mismas metas, mismos scripts inline (GTM, Heap, Jetboost, Matomo);
- no queda ninguna ruta de wget (../host/..., pagina.html) ni URL a ficheros de Webflow.

Uso: python3 test/comparar_mirror.py [--backup RUTA]   (sale con 1 si hay diferencias)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOMINIO = "icover-casecollection.ivascular.global"
URL_ATTRS = {"href", "src", "srcset"}
SCRIPT_PROPIO = "/_ksf/formularios.js"


class Analisis(HTMLParser):
    def __init__(self, propio: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.propio = propio  # nombre del fichero: wget convirtió src="" en src="<propio>"
        self.texto: list[str] = []
        self.etiquetas: list[tuple] = []
        self.cuenta: Counter = Counter()
        self.inline: list[str] = []
        self._pila_oculta = 0
        self._en_script = False
        self._propio = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src") == SCRIPT_PROPIO:
            self.cuenta["script_propio"] += 1
            self._en_script = True
            self._propio = True
            return
        self.cuenta[tag] += 1
        normal = []
        for k, v in attrs:
            if k in URL_ATTRS:
                v = "<url>" if v and not (k == "src" and v == self.propio) else ""
            if k == "content" and a.get("property") == "og:image" or k == "content" and a.get("name") == "twitter:image":
                v = "<url>"
            normal.append((k, v))
        self.etiquetas.append((tag, tuple(normal)))
        if tag in ("script", "style", "template", "noscript", "title"):
            self._pila_oculta += 1
            if tag == "script":
                self._en_script = True

    def handle_endtag(self, tag):
        if tag == "script" and self._propio:
            self._propio = False
            self._en_script = False
            return
        if tag in ("script", "style", "template", "noscript", "title") and self._pila_oculta:
            self._pila_oculta -= 1
        if tag == "script":
            self._en_script = False

    def handle_data(self, data):
        if self._en_script:
            self.inline.append(data.strip())
            return
        if self._pila_oculta == 0 and data.strip():
            self.texto.append(" ".join(data.split()))


def analizar(ruta: Path, propio: str = "") -> Analisis:
    a = Analisis(propio)
    a.feed(ruta.read_text(encoding="utf-8"))
    return a


def comparar(original: Path, nuevo: Path, pagina: str) -> list[str]:
    errores = []
    a, b = analizar(original, original.name), analizar(nuevo)
    if a.texto != b.texto:
        errores.append(f"{pagina}: el texto visible cambia")
    tiene_form = a.cuenta["form"] > 0
    if b.cuenta["script_propio"] != (1 if tiene_form else 0):
        errores.append(f"{pagina}: script de formularios {'ausente' if tiene_form else 'sobrante'}")
    for tag in ("img", "a", "script", "meta", "link", "form", "input", "select", "textarea", "video", "iframe", "source"):
        if a.cuenta[tag] != b.cuenta[tag]:
            errores.append(f"{pagina}: <{tag}> {a.cuenta[tag]} → {b.cuenta[tag]}")
    if a.etiquetas != b.etiquetas:
        for i, (x, y) in enumerate(zip(a.etiquetas, b.etiquetas)):
            if x != y:
                errores.append(f"{pagina}: etiqueta #{i} distinta: {x} → {y}")
                break
        else:
            errores.append(f"{pagina}: distinto número de etiquetas")
    # Scripts inline (GTM, Heap, Jetboost, Matomo, Finsweet...): idénticos salvo URLs de Webflow localizadas.
    def norm(t: str) -> str:
        t = re.sub(r"https://[a-z.-]*website-files\.com/|https?://" + re.escape(DOMINIO) + r"/_ext/[a-z.-]+/|/_ext/[a-z.-]+/", "<wf>/", t)
        return re.sub(r"https%3A%2F%2F[a-z.-]*website-files\.com%2F|%2F_ext%2F[a-z.-]+%2F", "<wf>%2F", t)
    if [norm(x) for x in a.inline] != [norm(x) for x in b.inline]:
        errores.append(f"{pagina}: cambian los scripts inline")
    texto = nuevo.read_text(encoding="utf-8")
    if re.search(r'(?:href|src|srcset)="[^"]*\.\./', texto):
        errores.append(f"{pagina}: quedan rutas ../ de wget")
    if re.search(r'(?:href|src)="(?!https?:|//)[^"]*\.html\b', texto):
        errores.append(f"{pagina}: quedan enlaces a .html")
    if re.search(r"(?://|%2F%2F)[a-z0-9.-]*(?:website-files\.com|webflow\.com)(?:/|%2F)", texto):
        errores.append(f"{pagina}: quedan URLs a ficheros de Webflow")
    return errores


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", default=os.environ.get("ICOVER_BACKUP") or str(RAIZ.parent / "ksf-workspace/backups/webflow-2026/icover-cases"))
    args = ap.parse_args()
    web = Path(args.backup) / "mirror" / DOMINIO
    site = RAIZ / "site"
    if not web.is_dir():
        print(f"SALTADO: no encuentro el mirror en {web}")
        return 0
    errores: list[str] = []
    paginas = sorted(p.relative_to(web).as_posix() for p in web.rglob("*.html"))
    for pagina in paginas:
        nuevo = site / pagina
        if not nuevo.is_file():
            errores.append(f"{pagina}: falta en site/")
            continue
        errores += comparar(web / pagina, nuevo, pagina)
    if not (site / "404.html").is_file():
        errores.append("falta site/404.html")
    sobrantes = {p.relative_to(site).as_posix() for p in site.rglob("*.html") if not p.relative_to(site).as_posix().startswith("_ext/")} - set(paginas) - {"404.html"}
    if sobrantes:
        errores.append(f"páginas que no están en el mirror: {sorted(sobrantes)}")
    for e in errores:
        print("FALLO", e)
    print(f"{len(paginas)} páginas comparadas con el mirror: {'OK' if not errores else f'{len(errores)} diferencias'}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
