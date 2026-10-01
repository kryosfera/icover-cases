// Worker de icover-casecollection.ivascular.global: sirve site/ como assets estáticos
// (con _headers y 404.html) y atiende los formularios en /api/contacto.
// Solo /api/* pasa por aquí (run_worker_first); el resto lo sirve directamente la capa de assets.
import { handleContacto, type ContactoEnv } from '../src/contacto.ts';

interface Env extends ContactoEnv {
  ASSETS: { fetch(request: Request): Promise<Response> };
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname === '/api/contacto') return handleContacto(request, env);
    if (pathname.startsWith('/api/')) {
      return new Response(JSON.stringify({ ok: false, error: 'no-encontrado' }), { status: 404, headers: { 'content-type': 'application/json' } });
    }
    return env.ASSETS.fetch(request);
  },
};
