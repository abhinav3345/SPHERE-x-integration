/**
 * The comparator's one hook: it owns everything live and returns one ViewModel.
 *
 * - State: a synchronous store over model.ts's reducer (handlers always see the latest state).
 * - Loading through api.ts: recorded fields by target, any position through the engine, the
 *   bundled recorded field when the engine does not answer, no coverage, busy, failures.
 * - Search through the search lane (overlays/resolve.ts and movers.ts).
 * - Playback: never starts by itself; every picture change passes one ChangeGate (at most 6 a
 *   second); under prefers-reduced-motion nothing plays.
 * - Hold to flip: one change down, one change up; key repeat ignored.
 * - The global keyboard map of Handoff-behaviour.
 * - The address bar (history.replaceState, never while playing) and Copy link.
 * - The extras (extras/derive.ts): the catalogue overlays of the field on screen while markers
 *   are on, and the spectrum at the ring while its panel is open, each aborted when what it was
 *   asked for changes; the recorded answers of a recorded field, asked for only when the rules of
 *   extras/derive.ts call for them; the handlers of vm.extras.
 */
import {
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  FieldError,
  type FieldRequest,
  type LoadProgress,
  loadBundledField,
  loadField,
  loadOverlays,
  loadRecordedOverlays,
  loadRecordedSpectrum,
  loadSpectrum,
  loadStatus,
  type RecordedAnswer,
  type RecordedRoute,
} from "../api";
import { nameKey } from "../overlays/known-movers";
import { readAsMessage } from "../overlays/messages";
import { findMover } from "../overlays/movers";
import { parseCoordinates } from "../overlays/parse";
import { resolveQuery, SEARCH_HINT } from "../overlays/resolve";
import { SearchError } from "../overlays/types";
import { decodeFloat16 } from "../player/float16";
import { gridOf, pixelToSky } from "../player/grid";
import { usePrefersReducedMotion } from "../player/hooks";
import { ChangeGate, clampFps } from "../player/playback";
import { FieldSynth } from "../player/synth";
import { deriveView } from "./derive";
import {
  answersField,
  modelOf,
  type OverlaysLoad,
  type RecordedField,
  type RecordedLoad,
  type RecordedLoads,
  recordedNeeded,
  type SpectrumAt,
  type SpectrumLoad,
  spectrumAt,
  spectrumShown,
} from "./extras/derive";
import { spectrumCsv, spectrumFileName } from "./extras/spectrum";
import type { ExtrasVM } from "./extras/types";
import { FEATURES } from "./features";
import { readAsSentence } from "./format";
import { LAYOUT_QUERIES, type Layout } from "./geometry";
import {
  type Action,
  type BandId,
  createReducer,
  type Fov,
  fieldOf,
  frameAnnouncement,
  INITIAL_STATE,
  type LoadRequest,
  nearestRecorded,
  type Offset,
  placeAt,
  RECORDED_FOV,
  resolve,
  round4,
  TARGETS,
  type TargetId,
  targetById,
  targetOfRecorded,
  targetPosition,
  type ViewId,
  type ViewState,
} from "./model";
import { goFromLink, linkFromState, readLink, writeLink } from "./url";
import type { EngineState, Handlers, ViewModel } from "./vm";

/** Seconds to wait when the engine says it is busy but not for how long. The client's own wait. */
const BUSY_WAIT_S = 20;
/** The build bar moves at most once a second (BuildProgress card). */
const PROGRESS_INTERVAL_MS = 1000;
/** "Link copied" stays this long. */
const COPY_STATUS_MS = 4000;
/** The address bar is written this long after the last change. */
const LINK_DELAY_MS = 250;
/** A spectrum is asked for this long after the ring stops moving, so clicks do not pile up. */
const SPECTRUM_DELAY_MS = 250;
/** Answers kept per page: overlays per field, spectra per position. */
const KEPT_ANSWERS = 24;
/** An entry that looks like a name, not a coordinate: two letters in a row. */
const NAME_LIKE = /[a-z]{2}/i;

/** Focus in one of these: the keys belong to it (Handoff-behaviour, keyboard map). */
const TEXT_FIELD = "input:not([type='range']), textarea, select, [contenteditable='true']";
const OWNS_ARROWS =
  "input, textarea, select, [contenteditable='true'], [role='radiogroup'], [role='radio'], [role='slider'], [data-own-keys]";
const OWNS_SPACE =
  "button, a[href], summary, input, textarea, select, [contenteditable='true'], [role='radio'], [role='switch'], [role='slider'], [data-own-keys]";

const reduce = createReducer(FEATURES);

function initialState(): ViewState {
  const link = readLink(window.location.search, FEATURES);
  return reduce({ ...INITIAL_STATE, view: link.view }, goFromLink(link));
}

// --------------------------------------------------------------------------------------------- store

function useStore(): [ViewState, (action: Action) => void, { readonly current: ViewState }] {
  const [state, setState] = useState(initialState);
  const ref = useRef(state);
  const dispatch = useCallback((action: Action) => {
    const next = reduce(ref.current, action);
    if (next !== ref.current) {
      ref.current = next;
      setState(next);
    }
  }, []);
  return [state, dispatch, ref];
}

// ----------------------------------------------------------------------------------- the window

function subscribeLayout(onChange: () => void): () => void {
  const lists = Object.values(LAYOUT_QUERIES).map((query) => window.matchMedia(query));
  for (const list of lists) list.addEventListener("change", onChange);
  return () => {
    for (const list of lists) list.removeEventListener("change", onChange);
  };
}

function currentLayout(): Layout {
  if (window.matchMedia(LAYOUT_QUERIES.wide).matches) return "wide";
  if (window.matchMedia(LAYOUT_QUERIES.three).matches) return "three";
  if (window.matchMedia(LAYOUT_QUERIES.rail).matches) return "rail";
  return "phone";
}

/** The layout, chosen with matchMedia so it agrees with the stylesheet's media queries. */
export function useLayout(): Layout {
  return useSyncExternalStore(subscribeLayout, currentLayout, () => "three");
}

function subscribeResize(onChange: () => void): () => void {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
}

function useDevicePixelRatio(): number {
  return useSyncExternalStore(
    subscribeResize,
    () => window.devicePixelRatio || 1,
    () => 1,
  );
}

/** Width of the phone or rail column, CSS px, kept current with a ResizeObserver. */
function useColumnWidth(): [number, (element: HTMLElement | null) => void] {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const measure = useCallback((element: HTMLElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!element) return;
    const read = () => setWidth(Math.floor(element.getBoundingClientRect().width));
    observer.current = new ResizeObserver(read);
    observer.current.observe(element);
    read();
  }, []);
  useEffect(() => () => observer.current?.disconnect(), []);
  return [width, measure];
}

// --------------------------------------------------------------------------------------- loading

function requestFor(request: LoadRequest): FieldRequest {
  return request.place.kind === "recorded"
    ? { fixture: request.place.target }
    : { ra: request.place.ra, dec: request.place.dec, fov: request.fov };
}

/** At most one progress report a second; the latest one wins. */
function throttle(report: (progress: LoadProgress) => void) {
  let last = Number.NEGATIVE_INFINITY;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let latest: LoadProgress | null = null;
  return {
    push(progress: LoadProgress) {
      latest = progress;
      const wait = last + PROGRESS_INTERVAL_MS - Date.now();
      if (wait <= 0) {
        last = Date.now();
        report(progress);
      } else if (timer === null) {
        timer = setTimeout(() => {
          timer = null;
          last = Date.now();
          if (latest) report(latest);
        }, wait);
      }
    },
    cancel() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    },
  };
}

// ------------------------------------------------------------------------------------------ hook

export function useComparator(): ViewModel {
  const [state, dispatch, stateRef] = useStore();
  const layout = useLayout();
  const dpr = useDevicePixelRatio();
  const reducedMotion = usePrefersReducedMotion();
  const [columnWidth, measureColumn] = useColumnWidth();
  const [engine, setEngine] = useState<{ state: EngineState; newest: string | null }>({
    state: "unknown",
    newest: null,
  });
  const [announcement, setAnnouncement] = useState("");
  const [now, setNow] = useState(() => Date.now());

  const markEngine = useCallback((up: boolean) => {
    setEngine((previous) => {
      const next: EngineState = up ? "up" : "down";
      return previous.state === next ? previous : { ...previous, state: next };
    });
  }, []);

  // Is the engine there, and how new is the newest exposure it has read? Asked once: at once when
  // nothing is loading, else after the first load has answered, and never once a load has shown
  // that no engine answers (so a page without an engine logs one failed request, not two).
  const statusAsked = useRef(false);
  const nothingAsked = state.request === null;
  useEffect(() => {
    if (statusAsked.current || engine.state === "down") return;
    if (engine.state === "unknown" && !nothingAsked) return;
    statusAsked.current = true;
    const controller = new AbortController();
    let answered = false;
    loadStatus({ signal: controller.signal })
      .then((status) => {
        answered = true;
        const newest = status?.newest_exposure?.date ?? null;
        setEngine({ state: status ? "up" : "down", newest });
      })
      .catch(() => {
        // Aborted: asked again on the next run of this effect.
      });
    return () => {
      controller.abort();
      if (!answered) statusAsked.current = false;
    };
  }, [engine.state, nothingAsked]);

  // Load whatever is asked for. A new request aborts the one before.
  const request = state.request;
  useEffect(() => {
    if (!request) return;
    const asked: LoadRequest = request;
    const controller = new AbortController();
    const { signal } = controller;
    const requestId = request.id;
    const progress = throttle((p) => dispatch({ type: "loadProgress", requestId, progress: p }));
    const onProgress = (p: LoadProgress) => {
      // A build stage comes only from the engine itself ("frames" also comes from the bundled copy).
      if (p.stage !== "frames") markEngine(true);
      progress.push(p);
    };

    async function open(fieldRequest: FieldRequest) {
      const loaded = await loadField(fieldRequest, { signal, onProgress });
      progress.cancel();
      return loaded;
    }

    async function run() {
      try {
        const loaded = await open(requestFor(asked));
        if (signal.aborted) return;
        markEngine(loaded.source === "api");
        if (loaded.frames === null) {
          dispatch({ type: "loadEmpty", requestId, manifest: loaded.manifest });
          return;
        }
        const synth = new FieldSynth(loaded.manifest, decodeFloat16(loaded.frames));
        const place = asked.place;
        dispatch({
          type: "loaded",
          requestId,
          field: {
            manifest: loaded.manifest,
            synth,
            source: loaded.source,
            recorded: place.kind === "recorded" ? place.target : null,
          },
          fallback: false,
        });
      } catch (error) {
        if (signal.aborted) return;
        progress.cancel();
        const place = asked.place;
        let failure: unknown = error;
        if (error instanceof FieldError && error.code === "busy") {
          markEngine(true);
          const wait = error.retryAfterS ?? BUSY_WAIT_S;
          dispatch({ type: "loadBusy", requestId, retryAt: Date.now() + 1000 * wait });
          return;
        }
        const archiveDown =
          error instanceof FieldError &&
          (error.code === "unreachable" || error.code === "upstream_unavailable");
        if (archiveDown && place.kind === "position") {
          // "The archive is not responding. Showing the recorded field instead."
          markEngine(error.code !== "unreachable");
          const target = nearestRecorded(place.ra, place.dec);
          try {
            // Known to be unreachable: take the bundled copy without asking the engine again.
            const loaded =
              error.code === "unreachable"
                ? await loadBundledField(target, { signal })
                : await loadField({ fixture: target }, { signal });
            if (signal.aborted) return;
            if (loaded.frames === null) {
              // A stand-in with no frames cannot stand in: say what failed, never keep loading.
              throw failure;
            }
            const synth = new FieldSynth(loaded.manifest, decodeFloat16(loaded.frames));
            dispatch({
              type: "loaded",
              requestId,
              field: { manifest: loaded.manifest, synth, source: loaded.source, recorded: target },
              fallback: true,
            });
            return;
          } catch (fallbackError) {
            if (signal.aborted) return;
            failure = fallbackError;
          }
        }
        const code = failure instanceof FieldError ? failure.code : "unexpected";
        if (code === "unreachable") markEngine(false);
        const message =
          failure instanceof Error
            ? failure.message
            : "Something went wrong while loading this field.";
        dispatch({ type: "loadFailed", requestId, code, message });
      }
    }

    void run();
    return () => {
      progress.cancel();
      controller.abort();
    };
  }, [request, dispatch, markEngine]);

  // The busy countdown ticks once a second, only while busy.
  const busyUntil = state.load.phase === "busy" ? state.load.retryAt : null;
  useEffect(() => {
    if (busyUntil === null) return;
    setNow(Date.now());
    const timer = setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= busyUntil) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [busyUntil]);

  // ------------------------------------------------------------------------- picture changes
  const [gate] = useState(() => new ChangeGate());
  useEffect(() => () => gate.cancel(), [gate]);

  const announceShown = useCallback(() => {
    const r = resolve(stateRef.current, FEATURES);
    if (r) setAnnouncement(frameAnnouncement(r));
  }, [stateRef]);

  /** A change of the picture: through the gate, at most 6 a second. */
  const change = useCallback(
    (action: Action, announce: boolean) => {
      gate.request(() => {
        const before = stateRef.current;
        dispatch(action);
        const changed = stateRef.current !== before;
        if (changed && announce) announceShown();
        return changed;
      });
    },
    [gate, dispatch, stateRef, announceShown],
  );

  // Playback: only while playing, never under reduced motion, capped at 6 a second.
  useEffect(() => {
    if (!state.playing || reducedMotion) return;
    const period = Math.ceil(1000 / clampFps(state.speed));
    const timer = setInterval(() => change({ type: "tick" }, false), period);
    return () => clearInterval(timer);
  }, [state.playing, state.speed, reducedMotion, change]);

  useEffect(() => {
    if (reducedMotion) dispatch({ type: "pause" });
  }, [reducedMotion, dispatch]);

  // ----------------------------------------------------------------------------- search
  const searchAbort = useRef<AbortController | null>(null);
  useEffect(() => () => searchAbort.current?.abort(), []);

  /** Stops a search still waiting for an answer, so a late answer cannot replace what was chosen since. */
  const cancelSearch = useCallback(() => {
    if (searchAbort.current === null) return;
    searchAbort.current.abort();
    searchAbort.current = null;
    dispatch({ type: "searchCancelled" });
  }, [dispatch]);

  /**
   * Opens one of the five targets: a recorded field at once ("Showing the recorded field for
   * Barnard's Star."), else a build where the target is at the frames' epoch, from its catalogue
   * position and proper motion (no name lookup, so no team backend is needed). `text` is what the
   * search field then shows.
   */
  const goToTarget = useCallback(
    (id: TargetId, text: string) => {
      const target = targetById(id);
      cancelSearch();
      if (target.recorded) {
        dispatch({
          type: "go",
          place: { kind: "recorded", target: target.recorded },
          fov: RECORDED_FOV,
          text,
          message: `Showing the recorded field for ${target.name}.`,
          target: id,
        });
        return;
      }
      const at = targetPosition(target);
      if (at === null) return;
      const fov = stateRef.current.fov;
      dispatch({
        type: "go",
        place: placeAt(at.ra, at.dec, fov, target.name),
        fov,
        text,
        message: readAsSentence(at.ra, at.dec),
        target: id,
      });
    },
    [dispatch, stateRef, cancelSearch],
  );

  const search = useCallback(
    async (text: string, target: TargetId | null) => {
      // The name of one of the five targets opens it at once (Handoff-behaviour: "WISE 0855 and
      // Barnard's Star open at once"), the others where they are now. A designation such as
      // WISE 0855-0714 is read as its catalogue position, with the moved-object banner.
      const named = TARGETS.find((t) => nameKey(t.name) === nameKey(text));
      if (named) {
        goToTarget(named.id, text);
        return;
      }
      cancelSearch();
      const controller = new AbortController();
      searchAbort.current = controller;
      const { signal } = controller;
      // A position is read at once; only the fast-mover check waits for the network. An entry
      // that cannot be read is reported by resolveQuery below, with its own sentence.
      let typed: ReturnType<typeof parseCoordinates> = null;
      try {
        typed = parseCoordinates(text);
      } catch {
        typed = null;
      }
      dispatch({
        type: "searchStarted",
        nameLike: typed === null && NAME_LIKE.test(text),
        target,
        message: typed ? readAsMessage(typed.position.ra, typed.position.dec) : null,
      });
      try {
        const resolved = await resolveQuery(text, { signal });
        const hint = FEATURES.movedBanner ? await findMover(resolved, { signal }) : null;
        if (signal.aborted) return;
        const fov = stateRef.current.fov;
        const name = resolved.name ?? (target ? targetById(target).name : null);
        const place = placeAt(resolved.position.ra, resolved.position.dec, fov, name);
        const message =
          place.kind === "recorded" && resolved.kind === "name"
            ? `Showing the recorded field for ${targetOfRecorded(place.target).name}.`
            : resolved.readAs;
        dispatch({
          type: "go",
          place,
          fov: place.kind === "recorded" ? RECORDED_FOV : fov,
          text,
          message,
          mover: hint ? { hint, from: resolved.position, jumped: false } : null,
          target,
        });
      } catch (error) {
        if (signal.aborted) return;
        const message =
          error instanceof SearchError
            ? error.message
            : "That entry could not be read. Try a position such as 133.7599 -7.2418.";
        dispatch({ type: "searchFailed", message });
      } finally {
        // Answered (or stopped): nothing is waiting any more.
        if (searchAbort.current === controller) searchAbort.current = null;
      }
    },
    [dispatch, stateRef, cancelSearch, goToTarget],
  );

  // -------------------------------------------------------------------------- the keyboard
  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      const target = event.target instanceof Element ? event.target : null;
      if (event.key === "Escape") {
        dispatch({ type: "escape" });
        return;
      }
      if (target?.closest(TEXT_FIELD)) return;
      const r = resolve(stateRef.current, FEATURES);
      // Outside Blink there is no single frame to step: Space and the arrows do nothing here.
      if (r?.view !== "blink") return;
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        if (target?.closest(OWNS_ARROWS)) return;
        event.preventDefault();
        change({ type: "step", delta: event.key === "ArrowLeft" ? -1 : 1 }, true);
      } else if (event.key === " ") {
        if (target?.closest(OWNS_SPACE)) return;
        event.preventDefault();
        if (event.repeat || reducedMotion) return;
        dispatch(stateRef.current.playing ? { type: "pause" } : { type: "play" });
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dispatch, stateRef, change, reducedMotion]);

  // ------------------------------------------------------------------------- the address bar
  const link = useMemo(() => writeLink(linkFromState(state, FEATURES)), [state]);
  const writeAddress = useCallback((query: string) => {
    const url = `${window.location.pathname}${query}${window.location.hash}`;
    const here = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (url !== here) window.history.replaceState(window.history.state, "", url);
  }, []);
  useEffect(() => {
    // Never while playing: browsers limit how often the address may change.
    if (state.playing) return;
    const timer = setTimeout(() => writeAddress(link), LINK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [link, state.playing, writeAddress]);

  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (copyTimer.current !== null) clearTimeout(copyTimer.current);
    },
    [],
  );

  // --------------------------------------------------------------------------------- extras
  // Catalogue overlays: for the field on screen, while markers are on, only from the engine (a
  // bundled copy means no engine answered). One answer per field is kept.
  const [overlays, setOverlays] = useState<OverlaysLoad>({ phase: "idle" });
  const overlaysKept = useRef(new Map<string, OverlaysLoad>());
  const shownField = fieldOf(state);
  const overlaysKey =
    FEATURES.catalogueMarkers && state.markers && shownField?.source === "api"
      ? shownField.manifest.key
      : null;
  useEffect(() => {
    if (overlaysKey === null) return;
    const key = overlaysKey;
    const kept = overlaysKept.current.get(key);
    if (kept) {
      setOverlays(kept);
      return;
    }
    const controller = new AbortController();
    setOverlays({ phase: "loading", key });
    const keep = (load: OverlaysLoad) => {
      const map = overlaysKept.current;
      map.set(key, load);
      if (map.size > KEPT_ANSWERS) map.delete(map.keys().next().value as string);
      setOverlays(load);
    };
    loadOverlays(key, { signal: controller.signal }).then(
      (data) => keep({ phase: "ready", key, data }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const code = error instanceof FieldError ? error.code : "unexpected";
        // A failure is not kept: the next time markers come on, it is asked again.
        setOverlays({ phase: "failed", key, code });
      },
    );
    return () => controller.abort();
  }, [overlaysKey]);

  // The spectrum at the ring: while its panel is open, for the field on screen from the engine.
  const [spectrum, setSpectrum] = useState<SpectrumLoad>({ phase: "idle" });
  const spectrumRef = useRef<SpectrumLoad>(spectrum);
  spectrumRef.current = spectrum;
  const spectraKept = useRef(new Map<string, SpectrumLoad>());
  const wanted: SpectrumAt | null =
    FEATURES.spectrum && state.spectrum && shownField?.source === "api"
      ? spectrumAt(shownField.manifest, gridOf(shownField.manifest), state.ring)
      : null;
  const wantedKey = wanted ? `${wanted.key}|${wanted.ra}|${wanted.dec}` : null;
  useEffect(() => {
    if (wantedKey === null) return;
    const [key, ra, dec] = wantedKey.split("|");
    const at: SpectrumAt = { key, ra: Number(ra), dec: Number(dec) };
    const kept = spectraKept.current.get(wantedKey);
    if (kept) {
      setSpectrum(kept);
      return;
    }
    const controller = new AbortController();
    setSpectrum({ phase: "loading", at, progress: null });
    const timer = setTimeout(() => {
      loadSpectrum(at.key, at.ra, at.dec, {
        signal: controller.signal,
        onProgress: (progress) => {
          if (!controller.signal.aborted) setSpectrum({ phase: "loading", at, progress });
        },
      }).then(
        (data) => {
          if (controller.signal.aborted) return;
          const load: SpectrumLoad = { phase: "ready", at, data };
          // An incomplete spectrum (some exposures not measured) is not kept, as the engine does
          // not cache it: asked again, it may be whole.
          if (!data.incomplete) {
            const map = spectraKept.current;
            map.set(wantedKey, load);
            if (map.size > KEPT_ANSWERS) map.delete(map.keys().next().value as string);
          }
          setSpectrum(load);
        },
        (error: unknown) => {
          if (controller.signal.aborted) return;
          const code = error instanceof FieldError ? error.code : "unexpected";
          setSpectrum({ phase: "failed", at, code });
        },
      );
    }, SPECTRUM_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [wantedKey]);

  // Recorded answers of a recorded field (extras/derive.ts, rules R1 to R5): read from the site's
  // own copy only when the rules call for one, that is when no live answer can be had, and never
  // for a recorded field shown instead of the place asked for (answersField). Each is read once
  // per field and route, and kept for the page's life (a missing file stays missing); a file that
  // could not be read this time counts as none until it is called for again, then is asked again.
  const recordedField: RecordedField | null = shownField
    ? {
        manifest: shownField.manifest,
        grid: gridOf(shownField.manifest),
        recorded: answersField(state),
        source: shownField.source,
      }
    : null;
  const needed = recordedNeeded(state, FEATURES, recordedField, overlays, spectrum);
  const [recordedAnswers, setRecordedAnswers] = useState<
    ReadonlyMap<string, RecordedAnswer | null>
  >(() => new Map());
  const recordedAsked = useRef(new Set<string>());
  const recordedId = (route: RecordedRoute) =>
    recordedField?.recorded
      ? `${route}|${recordedField.recorded}|${recordedField.manifest.key}`
      : "";
  const recordedWanted = [
    needed.overlays ? recordedId("overlays") : "",
    needed.spectrum ? recordedId("spectrum") : "",
  ]
    .filter(Boolean)
    .join(" ");
  useEffect(() => {
    for (const id of recordedWanted.split(" ")) {
      if (id === "" || recordedAsked.current.has(id)) continue;
      recordedAsked.current.add(id);
      const [route, name, key] = id.split("|");
      const load = route === "overlays" ? loadRecordedOverlays : loadRecordedSpectrum;
      const keep = (answer: RecordedAnswer | null) =>
        setRecordedAnswers((kept) => new Map(kept).set(id, answer));
      // A small file of the site's own: never aborted. It resolves to null when there is no
      // usable answer (R5). It rejects when the site did not answer this time (no answer, 429 or
      // 5xx): the page then behaves as without the file, and the next time the file is called
      // for (markers on again, the ring back, the field opened again) it is asked for again.
      load(name, key).then(keep, () => {
        recordedAsked.current.delete(id);
        keep(null);
      });
    }
  }, [recordedWanted]);
  const recordedLoad = <R extends RecordedRoute>(route: R, need: boolean): RecordedLoad<R> => {
    const name = recordedField?.recorded ?? null;
    if (recordedField === null || name === null) return { phase: "idle" };
    const key = recordedField.manifest.key;
    const id = recordedId(route);
    if (recordedAnswers.has(id)) {
      const answer = (recordedAnswers.get(id) ?? null) as RecordedAnswer<R> | null;
      return { phase: "done", field: name, key, answer };
    }
    // Asked for and not answered yet (or about to be asked, by the effect above).
    return need ? { phase: "loading", field: name, key } : { phase: "idle" };
  };
  const recorded: RecordedLoads = {
    overlays: recordedLoad("overlays", needed.overlays),
    spectrum: recordedLoad("spectrum", needed.spectrum),
  };
  const recordedRef = useRef<RecordedLoads>(recorded);
  recordedRef.current = recorded;

  const extrasHandlers = useMemo(
    (): ExtrasVM["handlers"] => ({
      toggleSpectrum: () => dispatch({ type: "setSpectrum", open: !stateRef.current.spectrum }),
      setSpectrumMode: (mode) => dispatch({ type: "setSpectrumMode", mode }),
      downloadCsv: () => {
        const s = stateRef.current;
        const field = fieldOf(s);
        if (!field) return;
        // Exactly what the panel shows: the live answer, or the recorded one where it stands in.
        const shown = spectrumShown({
          field: {
            manifest: field.manifest,
            grid: gridOf(field.manifest),
            recorded: answersField(s),
            source: field.source,
          },
          ring: s.ring,
          spectrum: spectrumRef.current,
          recorded: recordedRef.current.spectrum,
        });
        if (shown.kind !== "answer") return;
        const model = modelOf(shown.data, field.manifest);
        if (model.rows.length === 0) return;
        const blob = new Blob([spectrumCsv(model)], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = spectrumFileName(model, shown.recorded?.recorded_at ?? null);
        link.rel = "noopener";
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      },
    }),
    [dispatch, stateRef],
  );

  // ------------------------------------------------------------------------------- handlers
  const handlers = useMemo((): Handlers => {
    const flipDown = () => change({ type: "flip", held: true }, true);
    const flipUp = () => {
      if (stateRef.current.held) change({ type: "flip", held: false }, true);
    };
    const isFlipKey = (key: string) => key === " " || key === "Enter";
    return {
      setQuery: (text) => dispatch({ type: "setQuery", text }),
      submitSearch: () => {
        const s = stateRef.current;
        if (s.search.busy || (s.load.phase === "ready" && s.load.fallback)) return;
        void search(s.search.text.trim(), null);
      },
      openTarget: (id) => {
        const target = targetById(id);
        // A row that needs a build cannot open while no engine answers (it says so instead).
        if (!target.recorded && engine.state === "down") return;
        goToTarget(id, target.name);
      },
      retry: () => dispatch({ type: "retry" }),
      jump: () => {
        cancelSearch();
        dispatch({ type: "jump" });
      },

      step: (delta) => change({ type: "step", delta }, true),
      togglePlay: () => {
        if (reducedMotion) return;
        dispatch(stateRef.current.playing ? { type: "pause" } : { type: "play" });
      },
      setSpeed: (speed) => dispatch({ type: "setSpeed", speed }),
      pickFrame: (index) => change({ type: "pickFrame", index }, true),
      flipDown,
      flipUp,
      flipKey: {
        onPointerDown: (event: PointerEvent<HTMLElement>) => {
          if (event.button !== 0) return;
          flipDown();
        },
        onPointerUp: () => flipUp(),
        onPointerLeave: () => flipUp(),
        onPointerCancel: () => flipUp(),
        onBlur: (_event: FocusEvent<HTMLElement>) => flipUp(),
        onKeyDown: (event: KeyboardEvent<HTMLElement>) => {
          if (!isFlipKey(event.key)) return;
          event.preventDefault();
          event.stopPropagation();
          if (!event.repeat) flipDown();
        },
        onKeyUp: (event: KeyboardEvent<HTMLElement>) => {
          if (!isFlipKey(event.key)) return;
          event.preventDefault();
          event.stopPropagation();
          flipUp();
        },
        onContextMenu: (event: MouseEvent<HTMLElement>) => event.preventDefault(),
      },

      setRing: (ring: Offset) => dispatch({ type: "setRing", ring }),
      frameKeyDown: (event: KeyboardEvent<HTMLElement>) => {
        const steps: Record<string, [number, number]> = {
          ArrowLeft: [-1, 0],
          ArrowRight: [1, 0],
          ArrowUp: [0, -1],
          ArrowDown: [0, 1],
        };
        const move = steps[event.key];
        if (move) {
          event.preventDefault();
          const size = event.shiftKey ? 10 : 1;
          dispatch({ type: "moveCursor", dx: move[0] * size, dy: move[1] * size });
        } else if (event.key === "Enter") {
          event.preventDefault();
          dispatch({ type: "commitCursor" });
        }
      },
      clearCursor: () => dispatch({ type: "clearCursor" }),
      toggleSpotlight: () => dispatch({ type: "setSpotlight", on: !stateRef.current.spotlight }),
      recentre: () => {
        const s = stateRef.current;
        const field = fieldOf(s);
        if (!field) return;
        const { grid } = field.manifest;
        const sky = pixelToSky(gridOf(field.manifest), grid.cx + s.ring.dx, grid.cy + s.ring.dy);
        const ra = round4(sky.ra);
        const dec = round4(sky.dec);
        cancelSearch();
        dispatch({
          type: "go",
          place: placeAt(ra, dec, s.fov, null),
          text: `${ra} ${dec}`,
          message: readAsSentence(ra, dec),
          band: s.band,
          // The same sky at the new centre: an open spectrum stays open.
          spectrum: s.spectrum,
        });
      },

      setView: (view: ViewId) => dispatch({ type: "setView", view }),
      setBand: (band: BandId) => dispatch({ type: "setBand", band }),
      setFov: (fov: Fov) => {
        const s = stateRef.current;
        const shown = s.load.phase === "ready" ? s.load.field.recorded : null;
        const recordedOnly =
          engine.state === "down" && (shown !== null || s.request?.place.kind === "recorded");
        if (recordedOnly && fov !== RECORDED_FOV) return;
        if (fov !== s.fov) cancelSearch();
        dispatch({ type: "setFov", fov });
      },
      setContrast: (step) => dispatch({ type: "setContrast", contrast: step }),
      setInvert: (on) => dispatch({ type: "setInvert", on }),
      setMarkers: (on) => dispatch({ type: "setMarkers", on }),
      copyLink: () => {
        // The address first, so the copy is the screen as it is now.
        writeAddress(writeLink(linkFromState(stateRef.current, FEATURES)));
        const done = (ok: boolean) => {
          dispatch({ type: "copy", status: ok ? "copied" : "failed" });
          if (copyTimer.current !== null) clearTimeout(copyTimer.current);
          copyTimer.current = setTimeout(
            () => dispatch({ type: "copy", status: "idle" }),
            COPY_STATUS_MS,
          );
        };
        const clipboard = navigator.clipboard as Clipboard | undefined;
        if (!clipboard) {
          done(false);
          return;
        }
        clipboard.writeText(window.location.href).then(
          () => done(true),
          () => done(false),
        );
      },

      measureColumn,
    };
  }, [
    change,
    dispatch,
    stateRef,
    search,
    cancelSearch,
    goToTarget,
    engine.state,
    reducedMotion,
    writeAddress,
    measureColumn,
  ]);

  const derived = deriveView(
    state,
    {
      layout,
      columnWidth,
      dpr,
      reducedMotion,
      engine: engine.state,
      newest: engine.newest,
      now,
      announcement,
      searchHint: SEARCH_HINT,
      overlays,
      spectrum,
      recorded,
    },
    FEATURES,
  );

  const patch = useCallback(
    (fields: Partial<ViewState>) => dispatch({ type: "patch", patch: fields }),
    [dispatch],
  );

  const extras = useMemo(
    () => ({ ...derived.extras, handlers: extrasHandlers }),
    [derived.extras, extrasHandlers],
  );

  return { ...derived, extras, state, dispatch, patch, handlers };
}
