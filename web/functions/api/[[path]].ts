/**
 * Cloudflare Pages Function: forwards every /api/* request of the site to the Tombaugh API, so the
 * browser talks to one origin and the API address stays out of the client bundle.
 *
 * Settings of the Pages project (Settings -> Variables and Secrets):
 *   ORIGIN_URL    address of the API, for example https://tombaugh-api.fly.dev. A trailing slash is
 *                 ignored; a path prefix is kept in front of /api.
 *   PROXY_SECRET  optional shared secret. When set it is sent as x-tombaugh-proxy-secret.
 *
 * Method, path, query string and body are forwarded as they are, and the answer is streamed back
 * unchanged. The two x- request headers below are always removed from the incoming request first,
 * so a visitor can never supply them.
 *
 * When ORIGIN_URL is missing or the API cannot be reached, the answer is the error shape of
 * Contract v1.0, section 7: HTTP 503, code "upstream_unavailable". Such an answer also carries the
 * header x-tombaugh-proxy-error ("origin_not_configured" or "origin_unreachable"), which tells it
 * apart from the API's own 503, "the archive cannot be reached".
 *
 * No npm dependency: only the Request, Response, URL and fetch globals of the Workers runtime.
 */

interface Env {
  ORIGIN_URL?: string;
  PROXY_SECRET?: string;
}

/** The part of the Pages Functions context this function reads. */
interface Context {
  request: Request;
  env: Env;
}

type ProxyError = "origin_not_configured" | "origin_unreachable";

const CONTRACT_VERSION = "1.0";
const SECRET_HEADER = "x-tombaugh-proxy-secret";
const CLIENT_IP_HEADER = "x-forwarded-client-ip";
const PROXY_ERROR_HEADER = "x-tombaugh-proxy-error";

/** Statuses that Cloudflare itself answers with when it cannot get a response from an origin. */
const EDGE_STATUS_MIN = 520;
const EDGE_STATUS_MAX = 530;

/** The contract's error body for "the API cannot be reached", as an HTTP 503 response. */
function unavailable(reason: ProxyError, message: string): Response {
  const body = {
    contract: CONTRACT_VERSION,
    status: "error",
    code: "upstream_unavailable",
    message,
  };
  return new Response(JSON.stringify(body), {
    status: 503,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      [PROXY_ERROR_HEADER]: reason,
    },
  });
}

/** The API address for an incoming request URL, or null when ORIGIN_URL is not an http(s) URL. */
function targetUrl(originUrl: string, requestUrl: string): URL | null {
  try {
    const incoming = new URL(requestUrl);
    const target = new URL(originUrl);
    if (target.protocol !== "https:" && target.protocol !== "http:") return null;
    target.pathname = `${target.pathname.replace(/\/+$/, "")}${incoming.pathname}`;
    target.search = incoming.search;
    target.hash = "";
    return target;
  } catch {
    return null;
  }
}

export async function onRequest(context: Context): Promise<Response> {
  const { request, env } = context;

  const originUrl = (env.ORIGIN_URL ?? "").trim();
  if (originUrl === "") {
    return unavailable("origin_not_configured", "The API address is not configured on this site.");
  }
  const target = targetUrl(originUrl, request.url);
  if (target === null) {
    return unavailable(
      "origin_not_configured",
      "The API address configured on this site is not valid.",
    );
  }

  // Copying the incoming request keeps its method, headers and body stream.
  const upstream = new Request(target.toString(), request);
  upstream.headers.delete(SECRET_HEADER);
  upstream.headers.delete(CLIENT_IP_HEADER);
  if (env.PROXY_SECRET) upstream.headers.set(SECRET_HEADER, env.PROXY_SECRET);
  const clientIp = request.headers.get("cf-connecting-ip");
  if (clientIp) upstream.headers.set(CLIENT_IP_HEADER, clientIp);

  let response: Response;
  try {
    // "manual": a redirect from the API goes back to the browser as it is.
    response = await fetch(upstream, { redirect: "manual" });
  } catch {
    return unavailable(
      "origin_unreachable",
      "The API cannot be reached right now. Try again in a moment.",
    );
  }
  if (response.status >= EDGE_STATUS_MIN && response.status <= EDGE_STATUS_MAX) {
    return unavailable(
      "origin_unreachable",
      `The API did not answer (edge status ${response.status}). Try again in a moment.`,
    );
  }
  return response;
}
