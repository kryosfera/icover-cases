// Endpoint /api/contacto: recibe los formularios de la web (antes los recogía Webflow) y los
// reenvía por email con Resend. Adaptado de ksf-web/src/lib/contact.ts a campos genéricos:
// cada formulario declara su lista blanca de campos (las claves son el data-name de Webflow).
//
// Sin Turnstile (decisión: el widget alteraría el diseño, que debe quedar idéntico). Defensa:
// campo trampa, límite de tamaño, solo JSON, comprobación de Origin y validación estricta.

export interface ContactoEnv {
  RESEND_API_KEY?: string;
  CONTACT_TO?: string;
  CONTACT_FROM?: string;
}

export interface Campo {
  clave: string; // data-name del campo en el HTML de Webflow
  etiqueta: string; // texto de la etiqueta visible en la web
  max: number;
  obligatorio?: boolean;
  email?: boolean;
  opciones?: readonly string[]; // valores permitidos (select)
  multilinea?: boolean;
}

export interface Formulario {
  campos: readonly Campo[];
}

/** Formularios que se aceptan, por su data-name. */
export const FORMULARIOS: Record<string, Formulario> = {
  'Submit job form': {
    campos: [
      { clave: 'Name', etiqueta: 'Your Name', max: 256, obligatorio: true },
      { clave: 'Email', etiqueta: 'Your Email', max: 256, obligatorio: true, email: true },
      { clave: 'Company Name', etiqueta: 'Hospital', max: 256 },
      { clave: 'Job Title', etiqueta: 'Speciality', max: 256 },
      { clave: 'Job type', etiqueta: 'Category', max: 64, opciones: ['', 'Leaks-perforations', 'Fevar', 'Iliac-stenosys', 'Renal-stenosys', 'Renal-aneurism'] },
      { clave: 'Description', etiqueta: 'Description', max: 5000, multilinea: true },
    ],
  },
};

export const MAX_BODY_BYTES = 32 * 1024;
const ENV_KEYS = ['RESEND_API_KEY', 'CONTACT_TO', 'CONTACT_FROM'] as const;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const TRAMPA = 'web';

const s = (v: unknown) => (typeof v === 'string' ? v.trim() : '');
/** Una sola línea (asunto, cabeceras, campos cortos): sin saltos ni caracteres de control. */
const linea = (v: unknown) => s(v).replace(/[\u0000-\u001f\u007f]+/g, ' ').trim();
/** Texto multilínea: conserva saltos de línea y quita el resto de caracteres de control. */
const texto = (v: unknown) => s(v).replace(/\r\n?/g, '\n').replace(/[\u0000-\u0009\u000b-\u001f\u007f]+/g, ' ');

export function escapeHtml(t: string): string {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export type Validacion =
  | { ok: true; valores: Record<string, string> }
  | { ok: false; errores: Record<string, string> };

export function validar(form: Formulario, entrada: unknown): Validacion {
  const errores: Record<string, string> = {};
  const valores: Record<string, string> = {};
  if (!entrada || typeof entrada !== 'object' || Array.isArray(entrada)) return { ok: false, errores: { form: 'campos' } };
  const datos = entrada as Record<string, unknown>;
  for (const c of form.campos) {
    const bruto = datos[c.clave];
    if (bruto !== undefined && bruto !== null && typeof bruto !== 'string') { errores[c.clave] = 'tipo'; continue; }
    const v = c.multilinea ? texto(bruto) : linea(bruto);
    if (c.obligatorio && !v) errores[c.clave] = 'obligatorio';
    else if (v.length > c.max) errores[c.clave] = 'largo';
    else if (c.email && v && !EMAIL.test(v)) errores[c.clave] = 'email';
    else if (c.opciones && !c.opciones.includes(v)) errores[c.clave] = 'opcion';
    valores[c.clave] = v;
  }
  return Object.keys(errores).length ? { ok: false, errores } : { ok: true, valores };
}

const json = (body: unknown, status = 200, extra: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...extra } });

/** Lee el cuerpo contando bytes (haya o no Content-Length); null si pasa de `max`. */
async function leerCuerpo(request: Request, max: number): Promise<Uint8Array | null> {
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const trozos: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > max) { await reader.cancel().catch(() => {}); return null; }
    trozos.push(value);
  }
  const out = new Uint8Array(total);
  let off = 0;
  for (const t of trozos) { out.set(t, off); off += t.byteLength; }
  return out;
}

export function construirEmail(nombreForm: string, form: Formulario, valores: Record<string, string>, origen: string) {
  const filas = form.campos
    .map((c) => `<tr><td valign="top"><b>${escapeHtml(c.etiqueta)}</b></td><td>${escapeHtml(valores[c.clave] || '—').replace(/\n/g, '<br>')}</td></tr>`)
    .join('');
  const textoPlano = form.campos.map((c) => `${c.etiqueta}: ${valores[c.clave] || '—'}`).join('\n');
  const pie = origen ? `<p style="color:#888">Enviado desde ${escapeHtml(origen)}</p>` : '';
  return {
    subject: `iCover Case Collection · ${linea(nombreForm)}`,
    html: `<table>${filas}</table>${pie}`,
    text: textoPlano + (origen ? `\n\nEnviado desde ${origen}` : ''),
  };
}

export async function handleContacto(request: Request, env: ContactoEnv, fetchFn: typeof fetch = fetch): Promise<Response> {
  if (request.method !== 'POST') return json({ ok: false, error: 'metodo' }, 405, { Allow: 'POST' });
  const faltan = ENV_KEYS.filter((k) => !env?.[k]);
  if (faltan.length) {
    console.error(`contacto: falta ${faltan.join(', ')}`);
    return json({ ok: false, error: 'configuracion' }, 500);
  }
  const origin = request.headers.get('origin');
  if (origin) {
    let mismo = false;
    try { mismo = new URL(origin).host === new URL(request.url).host; } catch { mismo = false; }
    if (!mismo) return json({ ok: false, error: 'origen' }, 403);
  }
  const len = Number(request.headers.get('content-length') ?? 0);
  if (len > MAX_BODY_BYTES) return json({ ok: false, error: 'tamano' }, 413);
  const ct = (request.headers.get('content-type') ?? '').toLowerCase();
  if (!ct.includes('application/json')) return json({ ok: false, error: 'tipo' }, 415);

  let bytes: Uint8Array | null;
  try { bytes = await leerCuerpo(request, MAX_BODY_BYTES); } catch { bytes = new Uint8Array(); }
  if (!bytes) return json({ ok: false, error: 'tamano' }, 413);

  let raw: unknown;
  try { raw = JSON.parse(new TextDecoder().decode(bytes)); } catch { return json({ ok: false, error: 'formato' }, 400); }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return json({ ok: false, error: 'formato' }, 400);
  const body = raw as Record<string, unknown>;

  // Campo trampa relleno: se responde como si fuera bien, sin enviar nada ni delatar la trampa.
  if (s(body[TRAMPA])) return json({ ok: true });

  const nombreForm = s(body.form);
  const form = Object.prototype.hasOwnProperty.call(FORMULARIOS, nombreForm) ? FORMULARIOS[nombreForm] : undefined;
  if (!form) return json({ ok: false, error: 'formulario' }, 400);

  const r = validar(form, body.fields);
  if (!r.ok) return json({ ok: false, errors: r.errores }, 400);

  let origen = '';
  try {
    const u = new URL(s(body.source));
    if ((u.protocol === 'https:' || u.protocol === 'http:') && u.host === new URL(request.url).host) origen = u.origin + u.pathname;
  } catch { origen = ''; }

  const email = construirEmail(nombreForm, form, r.valores, origen.slice(0, 300));
  const replyTo = form.campos.find((c) => c.email && r.valores[c.clave]);
  const destinatarios = env.CONTACT_TO!.split(',').map((x) => x.trim()).filter(Boolean);
  const resp = await fetchFn('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      from: `iCover Case Collection <${env.CONTACT_FROM}>`,
      to: destinatarios,
      ...(replyTo ? { reply_to: r.valores[replyTo.clave] } : {}),
      ...email,
    }),
  }).catch(() => null);
  if (!resp || !resp.ok) {
    console.error('contacto: fallo resend', resp ? resp.status : 'red');
    return json({ ok: false, error: 'envio' }, 502);
  }
  return json({ ok: true });
}
