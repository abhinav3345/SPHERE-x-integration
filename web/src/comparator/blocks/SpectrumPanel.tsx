/**
 * SpectrumPanel (LANE: extras). The spectrum at the ring: flux in microjansky against wavelength,
 * with its table and its CSV file. Only what the engine measured is drawn: no example values.
 *
 * PORTS: Main.dc.html 424–498 (VIEW RAIL: the panel takes the place of Band, Field of view and
 *        Display at 1280; at 1440 Band stays, Blink-1440); Phone.dc.html 310–384 (under the
 *        playback); the SpectrumChart port is extras/chart.ts (bundle.js `spectrum`). The chart
 *        is drawn at its measured box: the panel's width and the height extras.css gives it, 24 px
 *        and 4 px under the boards' at 1280 and 1440 (and the table 6 px under at 1280), so the
 *        view rail holds the engine's warning notice and the whole provenance.
 * FLAGS: spectrum (off: never rendered; the ring row has no Spectrum button).
 * STATES: closed (null); loading ("Measuring…", or "Measuring 120 of 258" when the engine
 *         counts; no sentence while a recorded answer is read); ready (chart or table;
 *         "Indicative only: …", "A neighbour 7.5″ away may contaminate this"); saturated
 *         ("Saturated: no reliable brightness" in place of the chart); unavailable (no spectrum
 *         here, or the engine cannot measure one). Any of ready, saturated and unavailable can
 *         come from a recorded answer (extras/derive.ts, R1 to R5): then the qualifier chip
 *         "Recorded 14 Nov 2026" (vm.extras.spectrum.recorded) sits at the end of the Download
 *         CSV row, the only place it costs no height in the 688 px rail at 1280 × 720.
 * USES: vm.extras.spectrum, vm.extras.handlers.{setSpectrumMode,downloadCsv}, vm.layout,
 *       vm.field (band on screen, the visits' dates).
 */
import { type KeyboardEvent, useCallback, useEffect, useId, useRef, useState } from "react";
import { Icon } from "../../design/icons";
import { contractWaveBins } from "../../player/presets";
import { chartGeometry, outsideNote, SHAPES, seriesFor, shapePath } from "../extras/chart";
import { SATURATED } from "../extras/spectrum";
import type { SpectrumPointVM, SpectrumVM } from "../extras/types";
import { MINUS } from "../format";
import { type BandId, bandWaveBins } from "../model";
import type { ViewModel } from "../vm";
import "../extras/extras.css";

const MODES: ReadonlyArray<{ id: SpectrumVM["mode"]; label: string }> = [
  { id: "chart", label: "Chart" },
  { id: "table", label: "Table" },
];

/**
 * Chart sizes of the boards (Main.dc.html: 328 × 190 at 1280, 349 × 136 at 1440; phone 324 × 200),
 * drawn only until the chart's own box is measured: its width is the panel's, its height
 * extras.css's for the layout.
 */
function chartSize(layout: ViewModel["layout"]): { width: number; height: number } {
  if (layout === "wide") return { width: 349, height: 136 };
  if (layout === "three") return { width: 328, height: 190 };
  return { width: 324, height: 200 };
}

/** The band on screen as [lo, hi] µm, from the contract's wave bins. */
function bandSpan(band: BandId): [number, number] | null {
  const ids = new Set(bandWaveBins(band));
  const bins = contractWaveBins().filter((bin) => ids.has(bin.id));
  if (bins.length === 0) return null;
  return [Math.min(...bins.map((b) => b.lam_min)), Math.max(...bins.map((b) => b.lam_max))];
}

const signed = (text: string) => (text.startsWith("-") ? `${MINUS}${text.slice(1)}` : text);

interface Box {
  width: number;
  height: number;
}

/** Width and height of an element, CSS px, kept current. */
function useBox(fallback: Box): [Box, (element: Element | null) => void] {
  const [box, setBox] = useState(fallback);
  const observer = useRef<ResizeObserver | null>(null);
  const measure = useCallback((element: Element | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!element) return;
    const read = () => {
      const rect = element.getBoundingClientRect();
      const width = Math.floor(rect.width);
      const height = Math.floor(rect.height);
      if (width < 160 || height < 1) return;
      setBox((old) => (old.width === width && old.height === height ? old : { width, height }));
    };
    observer.current = new ResizeObserver(read);
    observer.current.observe(element);
    read();
  }, []);
  useEffect(() => () => observer.current?.disconnect(), []);
  return [box, measure];
}

/** Chart or Table: one Tab stop, arrows move and select, wrapping, Home and End. */
function ModeSwitch({ vm }: { vm: ViewModel }) {
  const { mode } = vm.extras.spectrum;
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const pick = (index: number) => {
    const next = MODES[(index + MODES.length) % MODES.length];
    vm.extras.handlers.setSpectrumMode(next.id);
    refs.current[(index + MODES.length) % MODES.length]?.focus();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const at = MODES.findIndex((m) => m.id === mode);
    const moves: Record<string, number> = {
      ArrowLeft: at - 1,
      ArrowUp: at - 1,
      ArrowRight: at + 1,
      ArrowDown: at + 1,
      Home: 0,
      End: MODES.length - 1,
    };
    if (event.key in moves) {
      event.preventDefault();
      pick(moves[event.key]);
    }
  };
  return (
    <div
      className="bc-segmented"
      role="radiogroup"
      aria-label="Show the spectrum as"
      onKeyDown={onKeyDown}
    >
      {MODES.map((m, i) => (
        // biome-ignore lint/a11y/useSemanticElements: the design system's segmented control is buttons with role="radio"
        <button
          key={m.id}
          ref={(element) => {
            refs.current[i] = element;
          }}
          className="bc-option"
          type="button"
          role="radio"
          aria-checked={mode === m.id}
          tabIndex={mode === m.id ? 0 : -1}
          onClick={() => vm.extras.handlers.setSpectrumMode(m.id)}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

function Legend({ spectrum }: { spectrum: SpectrumVM }) {
  const map = seriesFor(spectrum.visits.length);
  const anyFlagged = spectrum.points.some((p) => p.flagged);
  return (
    <div className="bc-legend">
      {spectrum.visits.map((visit, i) => {
        const n = map[i];
        return (
          <span className="bc-legend__item" key={visit.label}>
            <svg className={`bc-key bc-series-${n}`} viewBox="0 0 16 16" aria-hidden="true">
              <path className="bc-pt" d={shapePath(SHAPES[n - 1], 8, 8, 3.5)} />
            </svg>
            <span>{visit.label}</span>
          </span>
        );
      })}
      {spectrum.binned.length > 0 && (
        <span className="bc-legend__item">
          <svg className="bc-key bc-series-3" viewBox="0 0 16 16" aria-hidden="true">
            <path className="bc-pt bc-pt--binned" d={shapePath("triangle", 8, 8, 5)} />
          </svg>
          <span>Larger: binned</span>
        </span>
      )}
      {anyFlagged && (
        <span className="bc-legend__item">
          <svg className="bc-key bc-series-3" viewBox="0 0 16 16" aria-hidden="true">
            <path className="bc-pt bc-pt--flagged" d={shapePath("triangle", 8, 8, 3.5)} />
          </svg>
          <span>Hollow: flagged</span>
        </span>
      )}
    </div>
  );
}

function Chart({ vm }: { vm: ViewModel }) {
  const spectrum = vm.extras.spectrum;
  // The chart is drawn at its own box: the panel's width, and the height extras.css gives it.
  const [box, measure] = useBox(chartSize(vm.layout));
  const band = vm.field ? bandSpan(vm.field.band) : null;
  const g = chartGeometry(spectrum, box.width, box.height, band);
  const outside = outsideNote(g.outside);
  const visits = spectrum.visits.length;
  const clipId = `${useId()}-plot`;
  return (
    <div className="bc-stack">
      <svg
        ref={measure}
        className="bc-chart"
        role="img"
        viewBox={g.viewBox}
        width={g.width}
        height={g.height}
        aria-label={`Spectrum: flux in microjansky against wavelength from 0.75 to 5.0 micrometres, ${visits} ${visits === 1 ? "visit" : "visits"}. The same values are in the table view.`}
      >
        {g.band && (
          <rect
            className="bc-chart__band"
            x={g.band.x}
            y={g.top}
            width={g.band.width}
            height={g.bottom - g.top}
          />
        )}
        <path className="bc-chart__grid" d={g.grid} />
        <path className="bc-chart__axis" d={g.axis} />
        {g.yTicks.map((tick) => (
          <text
            key={`y${tick.label}`}
            className="bc-chart__num"
            x={g.left - 6}
            y={tick.at + 4}
            textAnchor="end"
          >
            {tick.label}
          </text>
        ))}
        {g.xTicks.map((tick) => (
          <text
            key={`x${tick.label}`}
            className="bc-chart__num"
            x={tick.at}
            y={g.bottom + 18}
            textAnchor={tick.anchor}
          >
            {tick.label}
          </text>
        ))}
        <text className="bc-chart__title" x={g.xTitle.x} y={g.xTitle.y} textAnchor="middle">
          Wavelength λ (µm)
        </text>
        <text className="bc-chart__title" transform={g.yTitle.transform} textAnchor="middle">
          Flux (µJy)
        </text>
        <clipPath id={clipId}>
          <rect x={g.clip.x} y={g.clip.y} width={g.clip.width} height={g.clip.height} />
        </clipPath>
        <g clipPath={`url(#${clipId})`}>
          {g.series.map((s) => (
            <g className={`bc-series-${s.series}`} key={`p${s.series}`}>
              <path className="bc-pt__err" d={s.err} />
              <path className="bc-pt" d={s.pts} />
              <path className="bc-pt bc-pt--flagged" d={s.flag} />
            </g>
          ))}
          {g.series.map((s) => (
            <g className={`bc-series-${s.series}`} key={`b${s.series}`}>
              <path className="bc-pt__err" d={s.berr} />
              <path className="bc-pt bc-pt--binned" d={s.bin} />
            </g>
          ))}
        </g>
      </svg>
      <Legend spectrum={spectrum} />
      {outside !== null && <p className="bc-note">{outside}</p>}
    </div>
  );
}

interface TableRow extends SpectrumPointVM {
  binned: boolean;
}

function Table({ vm }: { vm: ViewModel }) {
  const spectrum = vm.extras.spectrum;
  // The short form of a visit's dates ("7–14 Nov 2025", as in the timeline and the legend): the
  // fixed form ("07 Nov to 14 Nov 2025") left no room for Flux, Error and Note in the 328px
  // panel at 1280, so the flux was cut mid-number with the rest scrolled out of sight.
  const when = spectrum.visits.map((visit) => visit.label);
  const rows: TableRow[] = [
    ...spectrum.points.map((p) => ({ ...p, binned: false })),
    ...spectrum.binned.map((p) => ({ ...p, binned: true })),
  ].sort((a, b) => a.visit - b.visit || a.lam - b.lam || Number(a.binned) - Number(b.binned));
  return (
    <section
      className="bc-tablewrap cmp-sp-table"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: the design's scrolling region (Handoff-behaviour) takes focus so the keyboard can scroll it
      tabIndex={0}
      aria-label="Spectrum values"
    >
      <table className="bc-table">
        <thead>
          <tr>
            <th scope="col">Visit</th>
            <th scope="col">λ (µm)</th>
            <th scope="col">Flux (µJy)</th>
            <th scope="col">Error</th>
            <th scope="col" className="bc-table__text">
              Note
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={5} className="bc-table__text">
                No values yet.
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              // Rows are the engine's points in a fixed order; they never move.
              // biome-ignore lint/suspicious/noArrayIndexKey: positional rows of one answer
              <tr key={i}>
                <td>{when[row.visit] ?? ""}</td>
                <td>{row.lam.toFixed(3)}</td>
                <td>{signed(row.flux.toFixed(1))}</td>
                <td>±{row.err.toFixed(1)}</td>
                <td className="bc-table__text">
                  {row.flagged ? (
                    <span className="bc-table__flag">
                      <span className="bc-mark" />
                      Flagged
                    </span>
                  ) : row.binned ? (
                    "Binned"
                  ) : null}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}

function Messages({ spectrum }: { spectrum: SpectrumVM }) {
  if (spectrum.status === "loading") {
    return (
      <p className="bc-note" role="status">
        {spectrum.messages.join(" ")}
      </p>
    );
  }
  if (spectrum.status === "unavailable") {
    return (
      <div className="bc-notice bc-notice--plain" role="status">
        <Icon name="information" />
        <div>
          {spectrum.messages.map((message) => (
            <p key={message}>{message}</p>
          ))}
        </div>
      </div>
    );
  }
  const warnings = spectrum.messages.filter((m) => !m.startsWith("Showing the "));
  const notes = spectrum.messages.filter((m) => m.startsWith("Showing the "));
  return (
    <>
      {warnings.length > 0 && (
        <div className="bc-notice bc-notice--warning" role="status">
          <Icon name="warning" label="Warning" />
          <div>
            {warnings.map((message) => (
              <p key={message}>{message}</p>
            ))}
          </div>
        </div>
      )}
      {notes.map((message) => (
        <p className="bc-note" key={message}>
          {message}
        </p>
      ))}
    </>
  );
}

export function SpectrumPanel({ vm }: { vm: ViewModel }) {
  const spectrum = vm.extras.spectrum;
  // Opening the panel never moves focus or scrolls the page (Handoff-behaviour).
  if (!vm.features.spectrum || !spectrum.open) return null;
  const hasRows = spectrum.points.length > 0 || spectrum.binned.length > 0;
  const showChart = spectrum.mode === "chart" && spectrum.status === "ready" && hasRows;
  const showTable = spectrum.mode === "table" && spectrum.status !== "loading";
  return (
    <section className="bc-panel cmp-sp" aria-labelledby="tb-sp-title">
      <div className="bc-panel__head">
        <h3 className="bc-heading" id="tb-sp-title">
          Spectrum at your position
        </h3>
        <ModeSwitch vm={vm} />
      </div>
      {spectrum.status === "saturated" && spectrum.mode === "chart" ? (
        <div className="bc-notice bc-notice--warning" role="status">
          <Icon name="warning" label="Warning" />
          <div>
            <p>{SATURATED}</p>
          </div>
        </div>
      ) : (
        <Messages spectrum={spectrum} />
      )}
      {showChart && <Chart vm={vm} />}
      {showTable && <Table vm={vm} />}
      <div className="cmp-sp-foot">
        <button
          className="bc-button"
          type="button"
          disabled={!hasRows}
          onClick={vm.extras.handlers.downloadCsv}
        >
          Download CSV
        </button>
        {spectrum.recorded !== null && (
          // A recorded answer, never a live one: the header's "Recorded field" chip, with the
          // date. It shares the button's row, so the panel is no taller than with a live answer.
          <span className="bc-chip bc-chip--qualifier">
            <span className="bc-mark" />
            {spectrum.recorded}
          </span>
        )}
      </div>
    </section>
  );
}
