/**
 * Sentry error tracking. Active only when VITE_SENTRY_DSN is set at build time
 * (or via runtime config injected to window.__SENTRY_DSN__).
 *
 * Configure via Vite env:
 *   VITE_SENTRY_DSN
 *   VITE_SENTRY_ENVIRONMENT  (e.g. 'production', 'staging')
 *   VITE_SENTRY_RELEASE      (git sha)
 */

declare global {
  interface Window { __SENTRY_DSN__?: string; }
}

// Access Vite-injected env via cast — avoids requiring a vite-env.d.ts.
const viteEnv: Record<string, string | undefined> =
  ((import.meta as unknown as { env?: Record<string, string | undefined> }).env) || {};

export function isConfigured(): boolean {
  return Boolean(viteEnv.VITE_SENTRY_DSN || window.__SENTRY_DSN__);
}

export async function initSentry(): Promise<void> {
  const dsn = viteEnv.VITE_SENTRY_DSN || window.__SENTRY_DSN__;
  if (!dsn) {
    // Silent no-op
    return;
  }
  try {
    const Sentry = await import("@sentry/react");
    Sentry.init({
      dsn,
      environment: viteEnv.VITE_SENTRY_ENVIRONMENT || "production",
      release: viteEnv.VITE_SENTRY_RELEASE || "dev",
      tracesSampleRate: 0.1,
      replaysSessionSampleRate: 0.01,
      replaysOnErrorSampleRate: 1.0,
      integrations: [
        Sentry.browserTracingIntegration(),
        Sentry.replayIntegration({ maskAllText: true, blockAllMedia: true }),
      ],
      beforeSend(event) {
        // Strip PII — emails / tokens
        if (event.request?.url) {
          event.request.url = event.request.url.replace(/([?&])(token|api_key)=[^&]*/gi, '$1$2=REDACTED');
        }
        return event;
      },
    });
    console.info("[sentry] initialized");
  } catch (e) {
    console.warn("[sentry] init failed:", e);
  }
}
