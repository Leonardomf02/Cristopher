// Ligar/desligar os avisos neste dispositivo.
//
// Só funciona em contexto seguro (HTTPS ou localhost) e, no iPhone, apenas com a
// app instalada no ecrã principal — o Safari não deixa subscrever a partir do
// separador normal.
import { pushApi } from './api';

function base64ParaUint8(base64: string): ArrayBuffer {
  const preenchido = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
  const normal = preenchido.replace(/-/g, '+').replace(/_/g, '/');
  const cru = atob(normal);
  return Uint8Array.from([...cru].map(c => c.charCodeAt(0))).buffer;
}

export function podeReceberAvisos(): { pode: boolean; motivo: string } {
  if (!('serviceWorker' in navigator)) return { pode: false, motivo: 'o browser não suporta' };
  if (!('PushManager' in window)) return { pode: false, motivo: 'o browser não suporta avisos' };
  if (!window.isSecureContext) return { pode: false, motivo: 'é preciso HTTPS (ver tailscale serve)' };
  const iOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const instalada = window.matchMedia('(display-mode: standalone)').matches
    || (window.navigator as any).standalone === true;
  if (iOS && !instalada) return { pode: false, motivo: 'no iPhone, adiciona primeiro ao ecrã principal' };
  return { pode: true, motivo: '' };
}

function etiquetaDoDispositivo(): string {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return 'iPhone';
  if (/iPad/.test(ua)) return 'iPad';
  if (/Android/.test(ua)) return 'Android';
  if (/Macintosh/.test(ua)) return 'Mac';
  return 'dispositivo';
}

export async function activarAvisos(): Promise<{ ok: boolean; erro?: string }> {
  const { pode, motivo } = podeReceberAvisos();
  if (!pode) return { ok: false, erro: motivo };

  const permissao = await Notification.requestPermission();
  if (permissao !== 'granted') return { ok: false, erro: 'não deste permissão' };

  const reg = await navigator.serviceWorker.ready;
  const { public_key } = await pushApi.key();
  const existente = await reg.pushManager.getSubscription();
  const sub = existente || await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: base64ParaUint8(public_key),
  });
  await pushApi.subscribe(sub.toJSON(), etiquetaDoDispositivo());
  return { ok: true };
}

export async function desactivarAvisos(): Promise<void> {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) await sub.unsubscribe();
}

export async function avisosActivos(): Promise<boolean> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
  try {
    const reg = await navigator.serviceWorker.ready;
    return !!(await reg.pushManager.getSubscription());
  } catch {
    return false;
  }
}
