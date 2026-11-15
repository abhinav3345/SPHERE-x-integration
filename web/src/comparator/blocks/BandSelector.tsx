/**
 * BandSelector (LANE: view).
 *
 * PORTS: Main.dc.html 374–422 (the wavelength rule, port of rule() at 597–644 and of the system's
 *        wavelengthRule in components/bundle.js, then the 3 × 3 options); Phone.dc.html 438–484.
 *        The rule is drawn at the measured width of the rail (view/WavelengthRule.tsx).
 * FLAGS: threeColour — on: the ninth option "Three-colour · R · G · B" completes the 3 × 3 grid; when
 *        it is the band, the rule is 86px high with every tick lit and the three channel bars
 *        under it. Off: no ninth option, "Cold objects" spans two columns, the rule keeps 58px.
 * STATES: aria-checked on the band in force; aria-disabled bands with vm.bandNote under the group.
 *         The rule is role="img" with aria-label vm.rule.label, lit for vm.rule.band.
 *         Changing band keeps the visits on screen where the new band has data there (model.ts
 *         setBand); every frame of a sequence is of one band.
 * KEYS: one Tab stop; arrows move and select, skipping greyed options, wrapping; Home, End. At most
 *       six changes a second; a held key moves once.
 * USES: vm.bands, vm.bandNote, vm.rule, vm.handlers.setBand.
 * IDS: label #tb-band; note #tb-band-note.
 */
import { RadioGroup } from "../view/RadioGroup";
import { WavelengthRule } from "../view/WavelengthRule";
import "../view/view.css";
import type { ViewModel } from "../vm";

export function BandSelector({ vm }: { vm: ViewModel }) {
  const bands = vm.bands;
  // Eight options (no three-colour): the last, "Cold objects", spans two cells of the 3 × 3 grid.
  const spanLast = bands.length % 3 === 2;

  return (
    <div className="bc-group">
      <span className="bc-group__label" id="tb-band">
        Band
      </span>
      <WavelengthRule band={vm.rule.band} label={vm.rule.label} />
      <RadioGroup
        labelledBy="tb-band"
        describedBy={vm.bandNote ? "tb-band-note" : undefined}
        options={bands}
        columns={3}
        paced
        optionClass={(_, index) => (spanLast && index === bands.length - 1 ? "vw-span2" : "")}
        onSelect={vm.handlers.setBand}
      >
        {(option) => (
          <>
            <span>{option.label}</span>
            {option.meta && <span className="bc-option__meta">{option.meta}</span>}
          </>
        )}
      </RadioGroup>
      {vm.bandNote && (
        <p className="bc-note" id="tb-band-note">
          {vm.bandNote}
        </p>
      )}
    </div>
  );
}
