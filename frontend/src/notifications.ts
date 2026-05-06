// ── Push Notifications (Web Notification API) ──────────────────

export async function requestNotificationPermission(): Promise<boolean> {
  if (!('Notification' in window)) return false;
  if (Notification.permission === 'granted') return true;
  if (Notification.permission === 'denied') return false;
  const result = await Notification.requestPermission();
  return result === 'granted';
}

export function isNotificationsSupported(): boolean {
  return 'Notification' in window;
}

export function isNotificationsEnabled(): boolean {
  return isNotificationsSupported() && Notification.permission === 'granted';
}

export function sendNotification(title: string, options?: { body?: string; icon?: string; tag?: string }) {
  if (!isNotificationsEnabled()) return;
  try {
    const n = new Notification(title, {
      body: options?.body,
      icon: options?.icon || '/favicon.ico',
      tag: options?.tag,
      silent: false,
    });
    // Auto-close after 8s
    setTimeout(() => n.close(), 8000);
  } catch {
    // Notifications may fail in some contexts (e.g. insecure origins)
  }
}

// ── Pre-built notification helpers ──────────────────────────────

export function notifyFlowWorkDone(presetName: string) {
  sendNotification('⏱️ Tempo de trabalho terminado!', {
    body: `Sessão "${presetName}" concluída. Hora da pausa!`,
    tag: 'flow-work',
  });
}

export function notifyFlowBreakDone() {
  sendNotification('☕ Pausa terminada!', {
    body: 'Pronto para mais uma sessão?',
    tag: 'flow-break',
  });
}

export function notifyHabitReminder(habitName: string, habitIcon: string) {
  sendNotification(`${habitIcon} Lembrete de hábito`, {
    body: `Não te esqueças: ${habitName}`,
    tag: `habit-${habitName}`,
  });
}

export function notifyEventSoon(eventTitle: string, minutesUntil: number) {
  sendNotification('📅 Evento em breve', {
    body: `"${eventTitle}" começa em ${minutesUntil} minutos`,
    tag: `event-${eventTitle}`,
  });
}
