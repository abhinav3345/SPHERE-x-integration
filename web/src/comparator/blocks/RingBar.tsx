/**
 * RingBar (LANE: image): the buttons that act on the ring, 44 px under the image margin.
 *
 * PORTS: Main.dc.html 285–293 (hint "Click the image to move the ring.", then the buttons at the
 *        right; Recentre with its tooltip); Phone.dc.html 199–206 (equal cells, no hint).
 * FLAGS: spotlight (the Spotlight button; when off the hint takes the room at 1280, the other
 *        cells share the row on a phone), spectrum (the Spectrum button, lit while its panel is
 *        open: vm.extras.spectrum.open, vm.extras.handlers.toggleSpectrum).
 * STATES: the row is ALWAYS 44px, empty when !vm.ringBar.show. Recentre only when
 *         vm.ringBar.canRecentre (never greyed); while it is absent its place is kept, so the
 *         other buttons never move. Spotlight lit with aria-pressed. Esc closes the spotlight
 *         (the page's keyboard map). Tooltip on Recentre at 1280: "Builds this field again with
 *         the ring at its centre. About a minute the first time." Esc hides it.
 * USES: vm.ringBar, vm.handlers.{toggleSpotlight,recentre}, vm.features, vm.extras.
 */
import "../image/image.css";
import { type CSSProperties, useState } from "react";
import { Icon } from "../../design/icons";
import type { ViewModel } from "../vm";

const RECENTRE_TIP =
  "Builds this field again with the ring at its centre. About a minute the first time.";

function Recentre({ vm, wide }: { vm: ViewModel; wide: boolean }) {
  const [dismissed, setDismissed] = useState(false);
  const shown = vm.ringBar.canRecentre;
  if (!wide) {
    return shown ? (
      <button
        className="bc-button"
        type="button"
        aria-label="Recentre the field on the ring"
        onClick={() => vm.handlers.recentre()}
      >
        Recentre
      </button>
    ) : (
      <span className="img-ringbar__kept" />
    );
  }
  return (
    // Without a moved ring the button is not rendered for anyone; its place is kept.
    <span
      className={`bc-tiphost${dismissed ? " is-dismissed" : ""}${shown ? "" : " img-ringbar__kept"}`}
      onKeyDown={(event) => {
        if (event.key === "Escape") setDismissed(true);
      }}
      onMouseLeave={() => setDismissed(false)}
      onBlur={() => setDismissed(false)}
      aria-hidden={shown ? undefined : "true"}
    >
      <button
        className="bc-button"
        type="button"
        aria-describedby="tb-rec-tip"
        tabIndex={shown ? undefined : -1}
        disabled={!shown}
        onClick={() => vm.handlers.recentre()}
      >
        Recentre
      </button>
      <span className="bc-tooltip img-tooltip--end" id="tb-rec-tip" role="tooltip">
        {RECENTRE_TIP}
      </span>
    </span>
  );
}

export function RingBar({ vm }: { vm: ViewModel }) {
  const wide = vm.layout === "three" || vm.layout === "wide";
  if (!vm.ringBar.show) return <div className="img-ringbar" />;
  const spotlight = vm.features.spotlight && (
    <button
      className="bc-button"
      type="button"
      aria-pressed={vm.ringBar.spotlight}
      aria-describedby={wide ? "tb-ring-hint" : undefined}
      onClick={() => vm.handlers.toggleSpotlight()}
    >
      {wide && <Icon name="zoom" />}
      Spotlight
    </button>
  );
  const spectrum = vm.features.spectrum && (
    <button
      className="bc-button"
      type="button"
      aria-pressed={vm.extras.spectrum.open}
      onClick={() => vm.extras.handlers.toggleSpectrum()}
    >
      Spectrum
    </button>
  );
  if (wide) {
    return (
      <div className="img-ringbar">
        <p className="bc-note img-ringbar__hint" id="tb-ring-hint">
          Click the image to move the ring.
        </p>
        {spotlight}
        {spectrum}
        <Recentre vm={vm} wide />
      </div>
    );
  }
  const cells = (vm.features.spotlight ? 1 : 0) + (vm.features.spectrum ? 1 : 0) + 1;
  return (
    <div
      className="img-ringbar img-ringbar--cells"
      style={{ "--img-cells": cells } as CSSProperties}
    >
      {spotlight}
      {spectrum}
      <Recentre vm={vm} wide={false} />
    </div>
  );
}
