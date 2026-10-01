// Tests de la lógica de /api/contacto (node:test, sin dependencias). Ejecutar: npm test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { handleContacto, validar, escapeHtml, construirEmail, FORMULARIOS, MAX_BODY_BYTES } from '../src/contacto.ts';

const ENV = { RESEND_API_KEY: 're_test', CONTACT_TO: 'casos@ejemplo.com', CONTACT_FROM: 'web@ejemplo.com' };
const URL_API = 'https://icover-casecollection.ivascular.global/api/contacto';
const CAMPOS_OK = {
  Name: 'Dra. Ana Pérez', Email: 'ana@hospital.es', 'Company Name': 'Hospital Clínic', 'Job Title': 'Angiología',
  'Job type': 'Fevar', Description: 'Caso de prueba\ncon dos líneas',
};

function peticion(body: unknown, init: { headers?: Record<string, string>; method?: string; raw?: string } = {}) {
  return new Request(URL_API, {
    method: init.method ?? 'POST',
    headers: { 'content-type': 'application/json', origin: 'https://icover-casecollection.ivascular.global', ...(init.headers ?? {}) },
    body: init.method === 'GET' ? undefined : (init.raw ?? JSON.stringify(body)),
  });
}

function fetchFalso(respuesta = new Response('{"id":"x"}', { status: 200 })) {
  const llamadas: { url: string; body: any; headers: any }[] = [];
  const fn = (async (url: string, init: RequestInit) => {
    llamadas.push({ url, body: JSON.parse(String(init.body)), headers: init.headers });
    return respuesta;
  }) as unknown as typeof fetch;
  return { fn, llamadas };
}

const silenciar = () => { const e = console.error; console.error = () => {}; return () => { console.error = e; }; };

test('GET → 405 con Allow: POST', async () => {
  const r = await handleContacto(peticion(null, { method: 'GET' }), ENV);
  assert.equal(r.status, 405);
  assert.equal(r.headers.get('allow'), 'POST');
});

test('sin variables de entorno → 500 y no se llama a Resend', async () => {
  const f = fetchFalso();
  const restaurar = silenciar();
  const r = await handleContacto(peticion({ form: 'Submit job form', fields: CAMPOS_OK }), {}, f.fn);
  restaurar();
  assert.equal(r.status, 500);
  assert.equal(f.llamadas.length, 0);
});

test('CONTACT_TO no tiene valor por defecto: si falta → 500', async () => {
  const restaurar = silenciar();
  const r = await handleContacto(peticion({ form: 'Submit job form', fields: CAMPOS_OK }), { ...ENV, CONTACT_TO: '' }, fetchFalso().fn);
  restaurar();
  assert.equal(r.status, 500);
});

test('Origin de otro dominio → 403', async () => {
  const r = await handleContacto(peticion({ form: 'Submit job form', fields: CAMPOS_OK }, { headers: { origin: 'https://malo.example' } }), ENV, fetchFalso().fn);
  assert.equal(r.status, 403);
});

test('Content-Length excesivo → 413', async () => {
  const r = await handleContacto(peticion({}, { headers: { 'content-length': String(MAX_BODY_BYTES + 1) } }), ENV, fetchFalso().fn);
  assert.equal(r.status, 413);
});

test('cuerpo real excesivo aunque no declare tamaño → 413', async () => {
  const grande = JSON.stringify({ form: 'Submit job form', fields: { ...CAMPOS_OK, Description: 'x'.repeat(MAX_BODY_BYTES) } });
  const r = await handleContacto(peticion(null, { raw: grande }), ENV, fetchFalso().fn);
  assert.equal(r.status, 413);
});

test('tipo distinto de JSON → 415', async () => {
  const r = await handleContacto(peticion(null, { raw: 'Name=x', headers: { 'content-type': 'application/x-www-form-urlencoded' } }), ENV, fetchFalso().fn);
  assert.equal(r.status, 415);
});

test('JSON roto → 400', async () => {
  const r = await handleContacto(peticion(null, { raw: '{no' }), ENV, fetchFalso().fn);
  assert.equal(r.status, 400);
});

test('formulario desconocido (p. ej. el de filtros de la home) → 400', async () => {
  for (const form of ['Email Form', 'constructor', '__proto__', '']) {
    const r = await handleContacto(peticion({ form, fields: { Search: 'x' } }), ENV, fetchFalso().fn);
    assert.equal(r.status, 400, form);
  }
});

test('trampa rellena → 200 sin enviar nada', async () => {
  const f = fetchFalso();
  const r = await handleContacto(peticion({ form: 'Submit job form', fields: CAMPOS_OK, web: 'http://spam' }), ENV, f.fn);
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { ok: true });
  assert.equal(f.llamadas.length, 0);
});

test('campos obligatorios, email, opciones y longitudes', () => {
  const form = FORMULARIOS['Submit job form'];
  const r = validar(form, { Name: '', Email: 'no-es-email', 'Job type': 'Otra', 'Job Title': 'x'.repeat(257), Description: 'y'.repeat(5001) });
  assert.equal(r.ok, false);
  if (!r.ok) {
    assert.equal(r.errores.Name, 'obligatorio');
    assert.equal(r.errores.Email, 'email');
    assert.equal(r.errores['Job type'], 'opcion');
    assert.equal(r.errores['Job Title'], 'largo');
    assert.equal(r.errores.Description, 'largo');
  }
  assert.equal(validar(form, { ...CAMPOS_OK, Name: ['a'] }).ok, false);
  assert.equal(validar(form, 'texto').ok, false);
  assert.equal(validar(form, { Name: 'A', Email: 'a@b.es' }).ok, true); // los opcionales pueden faltar
});

test('envío correcto: lista blanca, escape HTML, asunto con el nombre del formulario, reply_to', async () => {
  const f = fetchFalso();
  const campos = { ...CAMPOS_OK, Name: 'Ana <script>x</script>\r\nBcc: otro@x.com', Extra: 'no debe aparecer' };
  const r = await handleContacto(peticion({ form: 'Submit job form', fields: campos, source: 'https://icover-casecollection.ivascular.global/submit-case?x=1' }), ENV, f.fn);
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { ok: true });
  assert.equal(f.llamadas.length, 1);
  const { url, body } = f.llamadas[0];
  assert.equal(url, 'https://api.resend.com/emails');
  assert.deepEqual(body.to, ['casos@ejemplo.com']);
  assert.equal(body.from, 'iCover Case Collection <web@ejemplo.com>');
  assert.equal(body.reply_to, 'ana@hospital.es');
  assert.equal(body.subject, 'iCover Case Collection · Submit job form');
  assert.ok(!body.html.includes('<script>'));
  assert.ok(body.html.includes('Ana &lt;script&gt;x&lt;/script&gt; Bcc: otro@x.com'));
  assert.ok(!body.html.includes('no debe aparecer'));
  assert.ok(!body.text.includes('no debe aparecer'));
  assert.ok(body.html.includes('Caso de prueba<br>con dos líneas'));
  assert.ok(body.html.includes('Hospital'));
  assert.ok(body.html.includes('https://icover-casecollection.ivascular.global/submit-case'));
  assert.ok(!body.html.includes('x=1'));
});

test('source de otro dominio no se incluye en el email', async () => {
  const f = fetchFalso();
  await handleContacto(peticion({ form: 'Submit job form', fields: CAMPOS_OK, source: 'https://phishing.example/x' }), ENV, f.fn);
  assert.ok(!f.llamadas[0].body.html.includes('phishing'));
});

test('CONTACT_TO admite varios destinatarios separados por comas', async () => {
  const f = fetchFalso();
  await handleContacto(peticion({ form: 'Submit job form', fields: CAMPOS_OK }), { ...ENV, CONTACT_TO: 'a@x.com, b@x.com' }, f.fn);
  assert.deepEqual(f.llamadas[0].body.to, ['a@x.com', 'b@x.com']);
});

test('fallo de Resend → 502 y el log no lleva datos personales', async () => {
  const logs: string[] = [];
  const e = console.error;
  console.error = (...a: unknown[]) => { logs.push(a.join(' ')); };
  const r = await handleContacto(peticion({ form: 'Submit job form', fields: CAMPOS_OK }), ENV, fetchFalso(new Response('x', { status: 500 })).fn);
  console.error = e;
  assert.equal(r.status, 502);
  assert.ok(logs.length > 0);
  assert.ok(logs.every((l) => !l.includes('ana@hospital.es') && !l.includes('Ana')));
});

test('escapeHtml y construirEmail', () => {
  assert.equal(escapeHtml(`<a href="x">'&'</a>`), '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;');
  const e = construirEmail('Submit job form', FORMULARIOS['Submit job form'], { Name: 'A', Email: 'a@b.es' }, '');
  assert.ok(e.html.includes('—'));
  assert.ok(!e.html.includes('Enviado desde'));
});
