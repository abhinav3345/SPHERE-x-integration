/**
 * Keyboard and pace rules of the view rail's option groups (Segmented card; Handoff-behaviour,
 * Keyboard map): one Tab stop per group; arrows move and select, skipping greyed options and
 * wrapping at the ends; Home and End jump to the first and last option that can be chosen.
 */

export interface RadioLike {
  checked: boolean;
  disabled: boolean;
}

/** The option that holds the group's one Tab stop: the chosen one, else the first that can be chosen, else the first. */
export function tabStop(options: readonly RadioLike[]): number {
  const checked = options.findIndex((o) => o.checked);
  if (checked > -1) return checked;
  const enabled = options.findIndex((o) => !o.disabled);
  return enabled > -1 ? enabled : 0;
}

/**
 * Where a key moves the focus from option `from`, or null when the key is not one of the group's
 * or no option can be chosen. Left and Up go back, Right and Down go on, both wrapping.
 */
export function moveTarget(
  options: readonly RadioLike[],
  from: number,
  key: string,
): number | null {
  const n = options.length;
  if (n === 0) return null;
  const enabled = (i: number) => !options[i].disabled;
  const scan = (start: number, step: 1 | -1): number | null => {
    for (let k = 1; k <= n; k++) {
      const i = (((start + step * k) % n) + n) % n;
      if (enabled(i)) return i;
    }
    return null;
  };
  switch (key) {
    case "ArrowRight":
    case "ArrowDown":
      return scan(from, 1);
    case "ArrowLeft":
    case "ArrowUp":
      return scan(from, -1);
    case "Home":
      return scan(-1, 1);
    case "End":
      return scan(n, -1);
    default:
      return null;
  }
}

/**
 * A gate that lets at most `perSecond` changes through in any second: a held arrow key or fast
 * clicks in Band or View change the picture, and the picture never changes more than six times a
 * second (Handoff-behaviour; README rule 4). Returns true when the change may go ahead.
 */
export function createGate(perSecond: number): (now: number) => boolean {
  const interval = 1000 / perSecond;
  let last = Number.NEGATIVE_INFINITY;
  return (now: number) => {
    if (now - last < interval) return false;
    last = now;
    return true;
  };
}
