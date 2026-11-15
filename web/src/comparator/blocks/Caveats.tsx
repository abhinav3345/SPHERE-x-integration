/**
 * Caveats (LANE: time).
 *
 * PORTS: Main.dc.html 142–156 (foot of the time rail; a list in text-caption);
 *        Phone.dc.html 394–407 (under the playback; a list in text-label; one caveat adds the
 *        line "Details are under Provenance.").
 * FLAGS: none. Never removed with a feature. catalogueMarkers adds why markers are missing, or
 *        that the markers drawn were recorded, with the date (time/rail.ts caveatList). The
 *        spectrum's own sentences stay in its panel.
 * STATES: one sentence: an ordinary warning notice; several: one warning notice with a list
 *         (aria-label "Caveats for this field"). Every sentence on screen, by date (the model
 *         writes "time bin 1" as the visit's dates): never collapsed, closed or truncated. At
 *         1280 × 720 and larger the timeline gives up height first, down to two rows; only a
 *         rail fuller still makes this notice give up height, and it then scrolls inside itself
 *         (time.css), so no sentence is ever cut off at the rail's edge.
 * USES: vm.notices.caveats, vm.extras.markers, vm.features, vm.field, vm.layout.
 */
import { Icon } from "../../design/icons";
import { CAVEATS_CUT, caveatList, isColumn, isThreeColumns } from "../time/rail";
import "../time/time.css";
import { useCut } from "../time/useCut";
import type { ViewModel } from "../vm";

export function Caveats({ vm }: { vm: ViewModel }) {
  const items = caveatList(vm.notices.caveats, vm.extras, {
    onScreen: vm.field !== null,
    catalogueMarkers: vm.features.catalogueMarkers,
  });
  // Only the rail at 1280 and 1440 can make the list scroll (time.css).
  const [body, cut] = useCut(isThreeColumns(vm.layout) && items.length > 0, items.join("\n"));
  if (items.length === 0) return null;
  return (
    <div className="bc-notice bc-notice--warning tl-caveats-notice" role="status">
      <Icon name="warning" label="Warning" />
      <div className="tl-caveats-body" ref={body}>
        {items.length === 1 ? (
          <>
            <p>{items[0]}</p>
            {isColumn(vm.layout) && <p className="bc-note">Details are under Provenance.</p>}
          </>
        ) : (
          <ul className="tl-caveats" aria-label="Caveats for this field">
            {items.map((sentence) => (
              <li key={sentence}>{sentence}</li>
            ))}
          </ul>
        )}
      </div>
      {/* For the eye only: a screen reader reads the whole list, scrolled or not. */}
      {cut && (
        <p className="bc-note tl-caveats-more" aria-hidden="true">
          {CAVEATS_CUT}
        </p>
      )}
    </div>
  );
}
