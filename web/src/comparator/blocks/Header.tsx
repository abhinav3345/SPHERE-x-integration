/**
 * Header (LANE: view).
 *
 * PORTS: Main.dc.html 353–361 (head of the view rail: wordmark, copy status, chip, Copy link with
 *        its tooltip); Phone.dc.html 21–29 (bc-appbar; no tooltip). The app bar is used on a
 *        phone and in the rail layout, where Comparator places the header in the column.
 * FLAGS: copyLink — when off, Copy link and its status are not rendered and the chip moves to the
 *        end of the header.
 * STATES: chip vm.chip: "recorded" (dashed qualifier, empty mark: "Recorded field"), "live"
 *         (solid, full mark: "Live data"), null (no chip). Status vm.copyStatus (role="status",
 *         reserved 11ch). The name is SITE_NAME from src/site.ts, linking to "/". Esc hides the
 *         tooltip without moving focus (Handoff-behaviour, Keyboard map).
 * USES: vm.chip, vm.copyStatus, vm.handlers.copyLink, vm.layout, vm.features.copyLink.
 */
import { useState } from "react";
import { Icon } from "../../design/icons";
import { SITE_NAME } from "../../site";
import "../view/view.css";
import type { ViewModel } from "../vm";

function Chip({ chip }: { chip: ViewModel["chip"] }) {
  if (chip === "recorded") {
    return (
      <span className="bc-chip bc-chip--qualifier">
        <span className="bc-mark" />
        Recorded field
      </span>
    );
  }
  if (chip === "live") {
    return (
      <span className="bc-chip">
        <span className="bc-mark bc-mark--full" />
        Live data
      </span>
    );
  }
  return null;
}

function CopyButton({ vm }: { vm: ViewModel }) {
  return (
    <button
      className="bc-button bc-button--quiet bc-button--icon"
      type="button"
      aria-label="Copy link"
      onClick={vm.handlers.copyLink}
    >
      <Icon name="copy-link" />
    </button>
  );
}

/** Copy link with its tooltip (1280 and 1440): shown on hover and focus; Esc hides it. */
function CopyWithTooltip({ vm }: { vm: ViewModel }) {
  const [dismissed, setDismissed] = useState(false);
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: the host only listens for Esc bubbling from the button inside it, to hide the tooltip
    <span
      className={dismissed ? "bc-tiphost is-dismissed" : "bc-tiphost"}
      onKeyDown={(event) => {
        if (event.key === "Escape") setDismissed(true);
      }}
      onBlur={() => setDismissed(false)}
      onMouseLeave={() => setDismissed(false)}
    >
      <CopyButton vm={vm} />
      <span className="bc-tooltip" role="tooltip">
        Copy link
      </span>
    </span>
  );
}

export function Header({ vm }: { vm: ViewModel }) {
  const copy = vm.features.copyLink;
  const status = copy ? (
    <span className="bc-copy__status vw-status" role="status" aria-live="polite">
      {vm.copyStatus}
    </span>
  ) : null;

  if (vm.layout === "phone" || vm.layout === "rail") {
    return (
      <header className="bc-appbar">
        <a className="bc-wordmark" href="/">
          {SITE_NAME}
        </a>
        <span className="bc-appbar__end">
          {status}
          <Chip chip={vm.chip} />
          {copy && <CopyButton vm={vm} />}
        </span>
      </header>
    );
  }

  return (
    <div className="vw-head">
      <a className="bc-wordmark" href="/">
        {SITE_NAME}
      </a>
      <span className="vw-head__end">
        {status}
        <Chip chip={vm.chip} />
        {copy && <CopyWithTooltip vm={vm} />}
      </span>
    </div>
  );
}
