/**
 * The Segmented group of the view rail (Segmented card): a role="radiogroup" of role="radio"
 * buttons with one Tab stop. Arrows move and select, skipping greyed options (aria-disabled) and
 * wrapping; Home and End; Space and Enter press the focused option as any button. The global key
 * map of useComparator ignores keys from radios, so arrows here never step frames.
 */
import { type CSSProperties, type KeyboardEvent, type ReactNode, useRef } from "react";
import { createGate, moveTarget, tabStop } from "./radio";

export interface RadioOption<T> {
  id: T;
  checked: boolean;
  disabled: boolean;
}

export interface RadioGroupProps<T, O extends RadioOption<T>> {
  /** Id of the visible group label. */
  labelledBy: string;
  /** Id of the note that says why options are greyed, when there is one. */
  describedBy?: string;
  options: readonly O[];
  onSelect(id: T): void;
  /** Cells per row (bc-segmented--wrap); omitted: one row. */
  columns?: number;
  /** At most six changes a second: for groups whose choice changes the picture. */
  paced?: boolean;
  /** Extra class of an option's button, e.g. a cell that spans two columns. */
  optionClass?(option: O, index: number): string;
  children(option: O): ReactNode;
}

const MAX_CHANGES_PER_SECOND = 6;

export function RadioGroup<T extends string | number, O extends RadioOption<T>>({
  labelledBy,
  describedBy,
  options,
  onSelect,
  columns,
  paced = false,
  optionClass,
  children,
}: RadioGroupProps<T, O>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const gate = useRef<((now: number) => boolean) | null>(null);
  if (paced && gate.current === null) gate.current = createGate(MAX_CHANGES_PER_SECOND);
  const stop = tabStop(options);

  /** Chooses option `index`; false when it cannot be chosen now. */
  const choose = (index: number): boolean => {
    const option = options[index];
    if (!option || option.disabled) return false;
    if (option.checked) return true;
    if (gate.current && !gate.current(performance.now())) return false;
    onSelect(option.id);
    return true;
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const target = moveTarget(options, index, event.key);
    if (target === null) return;
    event.preventDefault();
    // A held key moves once: key repeat would change the picture faster than the eye should see.
    if (event.repeat || target === index) return;
    if (choose(target)) buttons.current[target]?.focus();
  };

  const style =
    columns === undefined ? undefined : ({ "--bc-cols": String(columns) } as CSSProperties);
  return (
    <div
      className={columns === undefined ? "bc-segmented" : "bc-segmented bc-segmented--wrap"}
      role="radiogroup"
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      style={style}
    >
      {options.map((option, index) => {
        const extra = optionClass?.(option, index) ?? "";
        return (
          // biome-ignore lint/a11y/useSemanticElements: the system's Segmented cell is a button with role="radio" (Segmented card), styled by bc-option
          <button
            key={String(option.id)}
            ref={(element) => {
              buttons.current[index] = element;
            }}
            className={extra ? `bc-option ${extra}` : "bc-option"}
            type="button"
            role="radio"
            aria-checked={option.checked}
            aria-disabled={option.disabled || undefined}
            tabIndex={index === stop ? 0 : -1}
            onClick={() => choose(index)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {children(option)}
          </button>
        );
      })}
    </div>
  );
}
