/**
 * Search (LANE: time).
 *
 * PORTS: Main.dc.html 24–31 (inline form, hidden label, at the head of the time rail);
 *        Phone.dc.html 534–541 (visible label, inside "Go to another position" at the foot).
 * FLAGS: nameSearch — when off only the hint changes, and vm.search.message already carries the
 *        search lane's SEARCH_HINT. Nothing else to do.
 * STATES: hint; "Read as …"; "Looking up the name." (vm.search.busy: input read-only, button
 *         vm.search.button "Searching…", aria-busy); error (vm.search.error: aria-invalid,
 *         warning icon, role="alert", the line remounted so the alert is announced); disabled
 *         (vm.search.disabled, the archive stand-in). The message line is always two lines high
 *         (36px at 1280, the system's 44px in the column) so nothing below moves. What was typed
 *         is never rewritten, and no key typed in the field reaches the image (Esc still stops
 *         playing).
 * USES: vm.search.{text,message,error,busy,disabled,button}, vm.layout,
 *       vm.handlers.setQuery(text), vm.handlers.submitSearch() (form onSubmit, preventDefault).
 * IDS: input #tb-q, message #tb-q-msg (aria-describedby). autocomplete off, autocapitalize off,
 *      spellcheck false, enterKeyHint "search".
 */
import type { FormEvent, KeyboardEvent } from "react";
import { Icon } from "../../design/icons";
import { isThreeColumns } from "../time/rail";
import "../time/time.css";
import type { ViewModel } from "../vm";

export function Search({ vm }: { vm: ViewModel }) {
  const { text, message, error, busy, disabled, button } = vm.search;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    vm.handlers.submitSearch();
  };
  // The field's keys are its own: Space types, the arrows move the caret. Only Esc goes on.
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Escape") event.stopPropagation();
  };

  const input = (
    <input
      className="bc-input"
      id="tb-q"
      type="text"
      value={text}
      onChange={(event) => vm.handlers.setQuery(event.target.value)}
      onKeyDown={onKeyDown}
      readOnly={busy}
      disabled={disabled}
      aria-invalid={error}
      aria-describedby="tb-q-msg"
      autoComplete="off"
      autoCapitalize="off"
      spellCheck={false}
      enterKeyHint="search"
    />
  );
  const submit = (
    <button className="bc-button" type="submit" disabled={disabled} aria-busy={busy || undefined}>
      {button}
    </button>
  );
  // An error is an alert; every other message a polite status. A new element for the error, so
  // that screen readers announce it the moment it appears.
  const line = error ? (
    <p key="error" className="bc-fieldmsg bc-fieldmsg--error" id="tb-q-msg" role="alert">
      <Icon name="warning" label="Error" />
      <span>{message}</span>
    </p>
  ) : (
    <p key="message" className="bc-fieldmsg" id="tb-q-msg" aria-live="polite">
      <span>{message}</span>
    </p>
  );

  if (isThreeColumns(vm.layout)) {
    return (
      <div className="tl-search">
        {/* biome-ignore lint/a11y/useSemanticElements: the design's markup (Main.dc.html 25): the form itself is the search landmark */}
        <form className="bc-field bc-field--inline" role="search" onSubmit={onSubmit}>
          <label className="bc-sr" htmlFor="tb-q">
            Sky position or name
          </label>
          {input}
          {submit}
        </form>
        {line}
      </div>
    );
  }
  return (
    // biome-ignore lint/a11y/useSemanticElements: the design's markup (Phone.dc.html 534): the form itself is the search landmark
    <form className="bc-search" role="search" onSubmit={onSubmit}>
      <div className="bc-field">
        <label className="bc-label" htmlFor="tb-q">
          Sky position or name
        </label>
        {input}
        {submit}
        {line}
      </div>
    </form>
  );
}
