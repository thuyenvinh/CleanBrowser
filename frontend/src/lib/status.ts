/**
 * Public status feed client.
 *
 * Backs the unauthenticated ``/status`` route — must work *before*
 * useAuth has resolved (no session cookie, no ``X-Workspace-Id`` header).
 * That's why this file bypasses ``lib/api.ts`` entirely and calls
 * ``fetch`` directly: ``lib/api.ts`` injects the workspace header which
 * the public endpoint doesn't accept.
 */

export type OverallStatus = "operational" | "degraded" | "major_outage";
export type ServiceStatus = "operational" | "degraded" | "major_outage";

export interface StatusIncident {
  service_name: string;
  status: string;
  started_at: string;
  ended_at: string;
  count: number;
  error_message: string | null;
}

export interface PublicStatus {
  overall: OverallStatus;
  services: Record<string, ServiceStatus>;
  uptime_24h: Record<string, number>;
  uptime_7d: Record<string, number>;
  uptime_30d: Record<string, number>;
  recent_incidents: StatusIncident[];
}

export async function fetchPublicStatus(): Promise<PublicStatus> {
  const res = await fetch("/api/status/public", {
    headers: { Accept: "application/json" },
    // ``credentials: 'omit'`` so the browser doesn't even attach a
    // pre-existing session cookie — keeps this endpoint provably
    // un-personalised for caches / CDN edge.
    credentials: "omit",
  });
  if (!res.ok) {
    throw new Error(`status feed responded ${res.status}`);
  }
  return res.json();
}
