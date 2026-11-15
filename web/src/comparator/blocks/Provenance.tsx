/**
 * Provenance (LANE: view).
 *
 * PORTS: Main.dc.html 529 (one paragraph, always open, with the DOIs as links; the brightness
 *        scale added at 1440 × 900); Phone.dc.html 511–529 (the line, then Details: Exposures
 *        used, Data release, DOIs, Pixels, Brightness scale, Pipeline, Warnings). The rail layout
 *        uses the phone form.
 * FLAGS: none. Never removed.
 * STATES: vm.provenance (null without a field: the releases the product reads and their DOIs, no
 *         count, no pipeline); vm.loadingLine "Reading 120 of 258" while building. The releases
 *         and DOIs are the field's own (view/provenance.ts): a field built from DR1 alone cites
 *         DR1 alone. DOIs link to doi.org with rel="noopener". The brightness scale is written
 *         only where one grey scale is on screen (view/provenance.ts stretchShown).
 * USES: vm.provenance, vm.loadingLine, vm.layout, vm.field.view, vm.rule.band, vm.frameLabel.pixels.
 */
import { Fragment } from "react";
import { Icon } from "../../design/icons";
import { type Releases, releasesOf, separator, stretchShown } from "../view/provenance";
import "../view/view.css";
import type { ViewModel } from "../vm";

/** "SPHEREx Spectral Images, DR1 (10.26131/IRSA678) and QR3 (10.26131/IRSA662)", DOIs as links. */
function ReleaseSentence({ releases }: { releases: Releases }) {
  const { parts, others } = releases;
  return (
    <>
      {releases.prefix}
      {parts.length > 0 && ", "}
      {parts.map((part, index) => (
        <Fragment key={part.name}>
          {separator(index, parts.length)}
          {part.name}
          {part.doi && (
            <>
              {" ("}
              <a className="bc-link bc-value" href={part.doi.href} rel="noopener">
                {part.doi.doi}
              </a>
              {")"}
            </>
          )}
        </Fragment>
      ))}
      {others.map((doi) => (
        <Fragment key={doi.doi}>
          {" ("}
          <a className="bc-link bc-value" href={doi.href} rel="noopener">
            {doi.doi}
          </a>
          {")"}
        </Fragment>
      ))}
    </>
  );
}

function DoiLink({ href, doi }: { href: string; doi: string }) {
  return (
    <a className="bc-link bc-link--target bc-value" href={href} rel="noopener">
      {doi}
      <Icon name="external-link" />
    </a>
  );
}

export function Provenance({ vm }: { vm: ViewModel }) {
  const p = vm.provenance;
  const releases = releasesOf(p);
  const stretch = p && stretchShown(p, vm.rule.band, vm.field?.view ?? "blink") ? p.stretch : null;

  if (vm.layout === "three" || vm.layout === "wide") {
    return (
      <p className="bc-provenance">
        {vm.loadingLine && (
          <>
            <span className="bc-value">{vm.loadingLine}</span>.{" "}
          </>
        )}
        {p && (
          <>
            <span className="bc-value">{p.used}</span> exposures used.{" "}
          </>
        )}
        <ReleaseSentence releases={releases} />.
        {p && (
          <>
            {" "}
            Pipeline <span className="bc-value">{p.pipeline}</span>.
          </>
        )}
        {vm.layout === "wide" && stretch && (
          <>
            {" "}
            Brightness scale: asinh, <span className="bc-value">{stretch}</span>.
          </>
        )}
      </p>
    );
  }

  return (
    <div className="bc-stack">
      {vm.loadingLine && (
        <p className="bc-provenance">
          <span className="bc-value">{vm.loadingLine}</span>
        </p>
      )}
      {p && (
        <p className="bc-provenance">
          <span className="bc-value">{p.used}</span> exposures used. {releases.text}.
        </p>
      )}
      <details className="bc-disclosure">
        <summary>Details</summary>
        <div className="bc-disclosure__body">
          <dl className="bc-facts">
            {p && (
              <>
                <dt>Exposures used</dt>
                <dd>
                  <span className="bc-value">{p.used}</span>
                </dd>
              </>
            )}
            <dt>Data release</dt>
            <dd>{releases.text}</dd>
            {releases.parts.map(
              (part) =>
                part.doi && (
                  <Fragment key={part.name}>
                    <dt>DOI, {part.name}</dt>
                    <dd>
                      <DoiLink href={part.doi.href} doi={part.doi.doi} />
                    </dd>
                  </Fragment>
                ),
            )}
            {releases.others.map((doi) => (
              <Fragment key={doi.doi}>
                <dt>DOI</dt>
                <dd>
                  <DoiLink href={doi.href} doi={doi.doi} />
                </dd>
              </Fragment>
            ))}
            <dt>Pixels</dt>
            <dd>{p?.pixels ?? vm.frameLabel.pixels}</dd>
            {stretch && (
              <>
                <dt>Brightness scale</dt>
                <dd>
                  asinh, <span className="bc-value">{stretch}</span>, the same for every frame
                </dd>
              </>
            )}
            {p && (
              <>
                <dt>Pipeline</dt>
                <dd>
                  <span className="bc-value">{p.pipeline}</span>
                </dd>
                <dt>Warnings</dt>
                <dd>{p.warnings.join(" ")}</dd>
              </>
            )}
          </dl>
        </div>
      </details>
    </div>
  );
}
