/*
 * Envío de formularios sin Webflow.
 *
 * Sustituye al envío de webflow.js (que manda a webflow.com/api/v1/form/...) por un POST a
 * /api/contacto, conservando el comportamiento visible de Webflow: mismas validaciones y
 * mensajes (alert), botón con el texto de data-wait mientras envía y, al terminar, se oculta
 * el formulario y se muestra .w-form-done, o se muestra .w-form-fail si falla.
 *
 * Se registra en fase de captura sobre window para adelantarse al manejador de webflow.js
 * (jQuery delegado en document) y detenerlo. webflow.js sigue inicializando los formularios
 * (atributos aria, checkboxes personalizados), solo deja de enviarlos.
 *
 * Formularios:
 * - "Submit job form" (/submit-case): se envía a /api/contacto.
 * - "Email Form" (/): es el bloque de búsqueda y filtros de Jetboost, no un formulario de
 *   contacto. En Webflow, pulsar Intro en la búsqueda lo enviaba a Webflow y ocultaba los
 *   filtros; ahora el envío se anula y no se manda nada (los filtros siguen funcionando).
 */
(function () {
  'use strict';

  var ENDPOINT = '/api/contacto';
  var ENVIABLES = { 'Submit job form': true };
  var TRAMPA = 'web'; // campo trampa (honeypot): invisible para personas

  var emailField = /e(-)?mail/i;
  var emailValue = /^\S+@\S+$/;

  function anadirTrampa(form) {
    if (form.querySelector('[data-ksf-trampa]')) return;
    var caja = document.createElement('div');
    caja.setAttribute('aria-hidden', 'true');
    caja.setAttribute('data-ksf-trampa', '');
    caja.style.cssText = 'position:absolute;left:-10000px;top:auto;width:1px;height:1px;overflow:hidden;';
    var input = document.createElement('input');
    input.type = 'text';
    input.name = TRAMPA;
    input.tabIndex = -1;
    input.autocomplete = 'off';
    caja.appendChild(input);
    form.appendChild(caja);
  }

  // Igual que getStatus() de webflow.js.
  function estado(el, tipo, nombre, valor) {
    if (tipo === 'password') return 'Passwords cannot be submitted.';
    if (el.hasAttribute('required')) {
      if (!valor) return 'Please fill out the required field: ' + nombre;
      if (emailField.test(el.getAttribute('type') || '') && !emailValue.test(valor)) {
        return 'Please enter a valid email address for: ' + nombre;
      }
    } else if (nombre === 'g-recaptcha-response' && !valor) {
      return 'Please confirm you’re not a robot.';
    }
    return null;
  }

  // Igual que findFields() de webflow.js (clave = data-name, o name, o "Field N").
  function recogerCampos(form, campos) {
    var status = null;
    var els = form.querySelectorAll('input, select, textarea, button');
    var i = -1;
    Array.prototype.forEach.call(els, function (el) {
      var tipo = el.getAttribute('type');
      if (tipo === 'submit' || tipo === 'file') return;
      i += 1;
      if (el.closest('[data-ksf-trampa]')) return;
      var nombre = el.getAttribute('data-name') || el.getAttribute('name') || 'Field ' + (i + 1);
      var valor = el.value;
      if (tipo === 'checkbox') {
        valor = el.checked;
      } else if (tipo === 'radio') {
        if (campos[nombre] === null || typeof campos[nombre] === 'string') return;
        var marcado = form.querySelector('input[name="' + el.getAttribute('name') + '"]:checked');
        valor = marcado ? marcado.value : null;
      }
      if (typeof valor === 'string') valor = valor.trim();
      campos[nombre] = valor;
      status = status || estado(el, tipo, nombre, valor);
    });
    return status;
  }

  function mostrar(el, si) {
    if (el) el.style.display = si ? 'block' : 'none';
  }

  function terminar(form, ok) {
    var caja = form.closest('div.w-form');
    var hecho = caja && caja.querySelector(':scope > .w-form-done');
    var fallo = caja && caja.querySelector(':scope > .w-form-fail');
    mostrar(hecho, ok);
    mostrar(fallo, !ok);
    var foco = ok ? hecho : fallo;
    if (foco) foco.focus();
    form.style.display = ok ? 'none' : '';
  }

  function enviar(form, nombreForm) {
    var campos = {};
    var status = recogerCampos(form, campos);
    if (status) {
      window.alert(status);
      return;
    }
    var boton = form.querySelector('input[type="submit"], button[type="submit"]');
    var etiqueta = boton ? boton.value : null;
    var espera = boton ? boton.getAttribute('data-wait') : null;
    if (boton) {
      boton.disabled = true;
      if (espera) boton.value = espera;
    }
    var trampa = form.querySelector('[data-ksf-trampa] input');
    var cuerpo = JSON.stringify({
      form: nombreForm,
      fields: campos,
      source: window.location.href,
      web: trampa ? trampa.value : ''
    });
    fetch(ENDPOINT, { method: 'POST', headers: { 'content-type': 'application/json' }, body: cuerpo, credentials: 'same-origin' })
      .then(function (r) { return r.json().catch(function () { return null; }).then(function (d) { return r.ok && d && d.ok === true; }); })
      .catch(function () { return false; })
      .then(function (ok) {
        terminar(form, ok);
        if (boton) {
          boton.disabled = false;
          if (espera && etiqueta !== null) boton.value = etiqueta;
        }
      });
  }

  window.addEventListener('submit', function (evt) {
    var form = evt.target;
    if (!form || form.tagName !== 'FORM' || !form.closest('div.w-form')) return;
    evt.preventDefault();
    evt.stopPropagation();
    evt.stopImmediatePropagation();
    var nombreForm = form.getAttribute('data-name') || form.getAttribute('name') || '';
    if (!ENVIABLES[nombreForm]) return;
    enviar(form, nombreForm);
  }, true);

  function preparar() {
    Array.prototype.forEach.call(document.querySelectorAll('div.w-form form'), function (form) {
      var nombreForm = form.getAttribute('data-name') || form.getAttribute('name') || '';
      if (ENVIABLES[nombreForm]) anadirTrampa(form);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', preparar);
  else preparar();
})();
