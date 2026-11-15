/**
 * The team backend (src/backend, docs/CONTRACT.md), reached at VITE_TEAM_API_URL:
 * - GET /resolve?q=<text> -> {"name","ra","dec"}, or 404 {"error"} when the name is unknown. Names
 *   go through CDS Sesame and come back at their catalogue position (SIMBAD, epoch J2000).
 * - GET /stars?ra=&dec=&size=<arcmin> -> {"stars":[{"id","ra","dec","pmra","pmdec","mag"}]}: Gaia DR3
 *   at epoch 2016.0, brightest first, at most 200, within size/2·√2 arcmin; 502 on failure.
 * CORS is open, so the page calls it directly. Nothing else is ever fetched from here.
 */

import type { SkyPosition } from "./types";

export interface TeamApi {
  /** Base address without a trailing slash; null when none is configured (no name lookup). */
  base: string | null;
  /** The fetch to use: the browser's, or a stand-in in tests. */
  fetch: (url: string, init?: RequestInit) => Promise<Response>;
}

/** A configured address without its trailing slashes, or null when unset or blank. */
export function teamApiBaseFrom(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const base = value.trim().replace(/\/+$/, "");
  return base === "" ? null : base;
}

// Undefined outside Vite (a plain Node script); Vite and Vitest provide it.
const env: Partial<Record<string, unknown>> | undefined = import.meta.env;

/** The team backend as configured for this build. */
export const TEAM_API: TeamApi = {
  base: teamApiBaseFrom(env?.VITE_TEAM_API_URL),
  // Looked up at call time, so nothing is bound to a fetch that is replaced later.
  fetch: (url, init) => globalThis.fetch(url, init),
};

/** How long a name lookup may take before search says names cannot be looked up right now. */
export const RESOLVE_TIMEOUT_MS = 25_000;
/** The Gaia query behind /stars is slower, and the hint is optional: it may wait longer. */
export const STARS_TIMEOUT_MS = 45_000;
/** Field width asked of /stars: a circle of 5.66′ radius around the entry. */
export const STARS_SIZE_ARCMIN = 8;

/** The deadline passed before an answer came. */
export class TimeoutError extends Error {
  constructor(ms: number) {
    super(`No answer in ${ms / 1000} s`);
    this.name = "TimeoutError";
  }
}

function abortReason(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException("The search was cancelled.", "AbortError");
}

/**
 * GET base + path with a deadline. Resolves with the status and the parsed body (null when the
 * body is not JSON). Rejects on a network error, on the deadline (TimeoutError), or with the
 * signal's reason when the caller aborts.
 */
export async function getJson(
  api: TeamApi & { base: string },
  path: string,
  params: Record<string, string>,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<{ status: number; body: unknown }> {
  if (signal?.aborted) throw abortReason(signal);
  const query = new URLSearchParams(params).toString();
  const url = `${api.base}${path}${query === "" ? "" : `?${query}`}`;
  const controller = new AbortController();
  const onAbort = () => controller.abort(signal ? abortReason(signal) : undefined);
  signal?.addEventListener("abort", onAbort, { once: true });
  const timer = setTimeout(() => controller.abort(new TimeoutError(timeoutMs)), timeoutMs);
  try {
    const response = await api.fetch(url, { signal: controller.signal });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (signal?.aborted) throw abortReason(signal);
    if (controller.signal.aborted) throw controller.signal.reason;
    return { status: response.status, body };
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

/** How long a sleeping backend may take to wake (docs/CONTRACT.md: "wait up to 60 s"). */
export const WAKE_TIMEOUT_MS = 60_000;

/**
 * Wakes the team backend, whose deployed copy sleeps (docs/CONTRACT.md: call /health first and
 * wait up to 60 s). Call it when a page opens, so a name typed a little later does not meet the
 * 25 s lookup deadline cold. Resolves true when it answered; never rejects; asks nothing when no
 * backend is configured.
 */
export async function wakeTeamApi(api: TeamApi = TEAM_API): Promise<boolean> {
  if (api.base === null) return false;
  try {
    const answer = await getJson({ ...api, base: api.base }, "/health", {}, WAKE_TIMEOUT_MS);
    return answer.status >= 200 && answer.status < 300;
  } catch {
    return false;
  }
}

const isFiniteNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** The body of a 200 from /resolve, checked; null when it is not a usable position. */
export function readResolveBody(
  body: unknown,
): { name: string | null; position: SkyPosition } | null {
  if (typeof body !== "object" || body === null) return null;
  const { name, ra, dec } = body as Record<string, unknown>;
  if (!isFiniteNumber(ra) || !isFiniteNumber(dec) || dec < -90 || dec > 90) return null;
  if (ra < 0 || ra > 360) return null;
  return {
    name: typeof name === "string" && name.trim() !== "" ? name.trim() : null,
    position: { ra: ra % 360, dec },
  };
}

/** One Gaia DR3 source from /stars. Position at epoch 2016.0; proper motion in mas/yr. */
export interface GaiaStar {
  id: string;
  ra: number;
  dec: number;
  pmra: number | null;
  pmdec: number | null;
  mag: number | null;
}

/** Epoch of Gaia DR3 positions (Julian year). */
export const GAIA_DR3_EPOCH = 2016.0;

/** The body of a 200 from /stars, checked; rows without a position are dropped. Null when malformed. */
export function readStarsBody(body: unknown): GaiaStar[] | null {
  if (typeof body !== "object" || body === null) return null;
  const rows = (body as { stars?: unknown }).stars;
  if (!Array.isArray(rows)) return null;
  const stars: GaiaStar[] = [];
  for (const row of rows) {
    if (typeof row !== "object" || row === null) continue;
    const { id, ra, dec, pmra, pmdec, mag } = row as Record<string, unknown>;
    if (!isFiniteNumber(ra) || !isFiniteNumber(dec)) continue;
    if (typeof id !== "string" && typeof id !== "number") continue;
    stars.push({
      id: String(id),
      ra,
      dec,
      pmra: isFiniteNumber(pmra) ? pmra : null,
      pmdec: isFiniteNumber(pmdec) ? pmdec : null,
      mag: isFiniteNumber(mag) ? mag : null,
    });
  }
  return stars;
}
