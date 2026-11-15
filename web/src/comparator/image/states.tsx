/**
 * What the square holds when no frame is on screen (StateGrammar; Main.dc.html 180–230): the
 * build with its stages and counts (a polite status, updated at most once a second by the hook),
 * no coverage, busy with its countdown, no position, and a failure in the loader's words. The
 * square keeps its size in every state; nothing spins and nothing fades.
 */
import type { CSSProperties, ReactNode } from "react";
import { Icon } from "../../design/icons";
import type { BuildVM, ViewModel } from "../vm";

/** A fixed field of `n` characters (bc-fixed reads --bc-ch). */
export const chars = (n: number) => ({ "--bc-ch": n }) as CSSProperties;

function PlainNotice({ children }: { children: ReactNode }) {
  return (
    <div className="bc-frame__state">
      <div className="bc-notice bc-notice--plain" role="status">
        <Icon name="information" />
        <div>{children}</div>
      </div>
    </div>
  );
}

function SeeTheTargets() {
  return (
    <div className="bc-notice__actions">
      <a className="bc-button" href="#tb-targets">
        See the targets
      </a>
    </div>
  );
}

function Build({ build }: { build: BuildVM }) {
  const { bar } = build;
  const share = bar.max > 0 ? Math.min(1, Math.max(0, bar.now / bar.max)) : 0;
  return (
    <div className="bc-frame__state">
      <div className="bc-progress" role="status" aria-live="polite">
        <ol className="bc-steps">
          {build.steps.map((step) => (
            <li
              key={step.label}
              className={step.state === "done" ? "bc-step bc-step--done" : "bc-step"}
              aria-current={step.state === "doing" ? "step" : undefined}
            >
              <span className="bc-mark" />
              <span>
                {step.label}
                {step.value !== null && (
                  <>
                    {": "}
                    <span className="bc-value">{step.value}</span>
                  </>
                )}
              </span>
            </li>
          ))}
        </ol>
        <div
          className="bc-bar"
          role="progressbar"
          aria-label={bar.label}
          aria-valuemin={0}
          aria-valuemax={bar.max}
          aria-valuenow={bar.now}
        >
          <span
            className="bc-bar__fill"
            style={{ "--bc-value": `${(share * 100).toFixed(1)}%` } as CSSProperties}
          />
        </div>
        <p className="bc-note">{build.sentence}</p>
      </div>
    </div>
  );
}

/** A sentence in a square that has no picture: Then and now with no older image, and the like. */
export function SquareNote({ text }: { text: string }) {
  return (
    <PlainNotice>
      <p>{text}</p>
    </PlainNotice>
  );
}

/** The state block for vm.image.state; null for a frame on screen and while a recorded field loads. */
export function FrameStateBlock({ vm }: { vm: ViewModel }) {
  const { image } = vm;
  switch (image.state) {
    case "building":
      return image.build ? <Build build={image.build} /> : null;
    case "empty":
      return (
        <PlainNotice>
          <p>No public SPHEREx image covers this position yet.</p>
          <p className="bc-note">
            Try one of the targets below, or come back after the next release.
          </p>
          <SeeTheTargets />
        </PlainNotice>
      );
    case "busy": {
      const busy = image.busy;
      const ready = busy?.canRetry ?? true;
      return (
        <PlainNotice>
          <p>
            Too many requests are being built. Try again in{" "}
            <span className="bc-value bc-fixed bc-fixed--end" style={chars(2)}>
              {busy?.secondsLeft ?? 0}
            </span>{" "}
            seconds.
          </p>
          <div className="bc-notice__actions">
            <button
              className="bc-button"
              type="button"
              aria-disabled={ready ? undefined : "true"}
              onClick={() => {
                if (ready) vm.handlers.retry();
              }}
            >
              Try again
            </button>
          </div>
        </PlainNotice>
      );
    }
    case "none":
      return (
        <PlainNotice>
          <p>No position chosen yet.</p>
          <p className="bc-note">Type a position or a name, or pick one of the five targets.</p>
          <SeeTheTargets />
        </PlainNotice>
      );
    case "failed":
      return (
        <PlainNotice>
          <p>{image.failure}</p>
          <div className="bc-notice__actions">
            <button className="bc-button" type="button" onClick={() => vm.handlers.retry()}>
              Try again
            </button>
          </div>
        </PlainNotice>
      );
    default:
      return null;
  }
}
