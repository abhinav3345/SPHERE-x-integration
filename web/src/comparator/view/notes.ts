/**
 * What the view rail derives for itself from the ViewModel (CONTRACT.md, section 1): the notes
 * under the view switch and the column count of the switch.
 */
import type { Manifest } from "../../contract";
import type { Layout } from "../geometry";
import { type SeqFrame, type ViewId, viewBlocked } from "../model";
import type { OptionVM, ViewModel } from "../vm";

/**
 * Why `view` is greyed on the field on screen (model.ts viewBlocked, as written), or null when it
 * can be used. Null too while no field is on screen: the ViewModel's own note covers that.
 */
export function greyedReason(
  view: ViewId,
  field: { sequence: readonly SeqFrame[]; manifest: Manifest } | null,
): string | null {
  return field ? viewBlocked(view, field.sequence, field.manifest) : null;
}

/**
 * The notes under the view switch: why each greyed view is greyed (Segmented card: "a note under
 * the group that says why"), in the switch's order, each sentence once. A greyed view with no
 * reason of its own (no frame on screen yet) is covered by the ViewModel's note. With nothing
 * greyed there is no note: vm.viewNote then carries only the Then and now pairing ("No older
 * survey image matches All. Then and now pairs …"), which the Then and now block prints where it
 * applies (PairInfo, from vm.extras.thenAndNow.note). Printed here as well, it was on screen twice
 * in Then and now and, at two lines, pushed the provenance out of the 1280 × 720 rail.
 */
export function viewNotes(
  views: readonly OptionVM<ViewId>[],
  viewNote: string | null,
  reasonFor: (view: ViewId) => string | null,
): string[] {
  const notes: string[] = [];
  let unexplained = false;
  for (const option of views) {
    if (!option.disabled) continue;
    const reason = reasonFor(option.id);
    if (reason === null) unexplained = true;
    else if (!notes.includes(reason)) notes.push(reason);
  }
  if (unexplained && viewNote !== null && !notes.includes(viewNote)) notes.unshift(viewNote);
  return notes;
}

/** The notes ViewSwitch prints, from the ViewModel. */
export function switchNotes(vm: Pick<ViewModel, "views" | "viewNote" | "field">): string[] {
  return viewNotes(vm.views, vm.viewNote, (view) => greyedReason(view, vm.field));
}

/** Columns of the view switch: one row from 1280; 2 × 2 on a phone and in the rail with four views. */
export function viewColumns(layout: Layout, count: number): number {
  if (layout === "three" || layout === "wide") return count;
  return count === 4 ? 2 : count;
}
