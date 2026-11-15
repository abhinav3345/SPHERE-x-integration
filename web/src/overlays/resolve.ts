import { knownMoverByName } from "./known-movers";
import {
  HINT_WITH_NAMES,
  HINT_WITHOUT_NAMES,
  NAMES_DOWN,
  NAMES_OFF,
  NOT_FOUND,
  readAsMessage,
  solarSystemMessage,
} from "./messages";
import { normaliseEntry, parseCoordinates } from "./parse";
import { solarSystemSubject } from "./solar-system";
import { getJson, RESOLVE_TIMEOUT_MS, readResolveBody, TEAM_API, type TeamApi } from "./team-api";
import { type Resolved, SearchError, type SearchOptions, type SkyPosition } from "./types";

/** True when a team backend address is configured, so names can be looked up. */
export const NAME_LOOKUP_AVAILABLE: boolean = TEAM_API.base !== null;

/** The hint for a build with or without name lookup. */
export function searchHint(namesAvailable: boolean): string {
  return namesAvailable ? HINT_WITH_NAMES : HINT_WITHOUT_NAMES;
}

/** The hint under the search field: only the forms that work in this build. */
export const SEARCH_HINT: string = searchHint(NAME_LOOKUP_AVAILABLE);

/**
 * Reads an entry: decimal degrees, hours and degrees, or a name.
 * Rejects with a SearchError whose message names the problem and the allowed range.
 * When `options.signal` aborts, rejects with the signal's reason (an AbortError, not a SearchError).
 */
export async function resolveQuery(text: string, options: SearchOptions = {}): Promise<Resolved> {
  return resolveQueryWith(text, TEAM_API, options);
}

/** What a name is sent as: true minus to hyphen, curly apostrophe to straight, single spaces. */
export function nameForLookup(text: string): string {
  return normaliseEntry(text).replace(/\s+/g, " ");
}

function resolved(
  query: string,
  kind: Resolved["kind"],
  position: SkyPosition,
  name: string | null,
  source: Resolved["source"],
): Resolved {
  return { query, kind, position, readAs: readAsMessage(position.ra, position.dec), name, source };
}

/** `resolveQuery` with the backend and its deadline given explicitly (tests, scripts). */
export async function resolveQueryWith(
  text: string,
  api: TeamApi,
  options: SearchOptions & { timeoutMs?: number } = {},
): Promise<Resolved> {
  const { signal, timeoutMs = RESOLVE_TIMEOUT_MS } = options;
  if (signal?.aborted) throw signal.reason;
  const namesAvailable = api.base !== null;
  const trimmed = text.trim();
  if (trimmed === "") throw new SearchError("empty", searchHint(namesAvailable));

  // Positions never need the network.
  const typed = parseCoordinates(trimmed);
  if (typed !== null) return resolved(text, typed.kind, typed.position, null, "typed");

  const known = knownMoverByName(trimmed);
  if (known !== null) return resolved(text, "name", known.catalogue, known.name, "known-movers");

  const subject = solarSystemSubject(trimmed);
  if (subject !== null) {
    throw new SearchError("solar_system", solarSystemMessage(subject, namesAvailable));
  }
  if (api.base === null) throw new SearchError("unavailable", NAMES_OFF);

  const sent = nameForLookup(trimmed);
  let answer: { status: number; body: unknown };
  try {
    answer = await getJson({ ...api, base: api.base }, "/resolve", { q: sent }, timeoutMs, signal);
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new SearchError("unavailable", NAMES_DOWN);
  }
  if (answer.status === 404) throw new SearchError("not_found", NOT_FOUND);
  const found = answer.status >= 200 && answer.status < 300 ? readResolveBody(answer.body) : null;
  if (found === null) throw new SearchError("unavailable", NAMES_DOWN);
  return resolved(text, "name", found.position, found.name ?? sent, "team-api");
}
