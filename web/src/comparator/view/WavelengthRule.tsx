/**
 * The wavelength rule (BandSelector card), drawn at the width of its column so that the 102 ticks
 * stay a whole number of pixels apart: the column is measured before paint and on every resize.
 * A picture with a text alternative (role="img"); never the only way to choose a band.
 */
import { useLayoutEffect, useRef, useState } from "react";
import type { BandId } from "../model";
import { RULE_HEIGHT, RULE_HEIGHT_RGB, RULE_Y, ruleDrawing } from "./rule";

export function WavelengthRule({ band, label }: { band: BandId; label: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const read = () => setWidth(Math.floor(element.getBoundingClientRect().width));
    read();
    const observer = new ResizeObserver(read);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const drawing = ruleDrawing(width, band);
  const height = drawing?.height ?? (band === "rgb" ? RULE_HEIGHT_RGB : RULE_HEIGHT);
  return (
    <div ref={box} className="vw-rule">
      <svg
        className="bc-rule"
        role="img"
        aria-label={label}
        height={height}
        viewBox={drawing ? `0 0 ${drawing.width} ${drawing.height}` : undefined}
        style={drawing ? { width: drawing.width } : undefined}
      >
        {drawing && (
          <>
            <path className="bc-rule__base" d={drawing.base} />
            <path className="bc-rule__tick" d={drawing.unlit} />
            <path className="bc-rule__tick bc-rule__tick--lit" d={drawing.lit} />
            <path className="bc-rule__edge" d={drawing.edges} />
            {drawing.span && <path className="bc-rule__span" d={drawing.span} />}
            {drawing.bands.map((b) => (
              <text
                key={b.text}
                className={b.lit ? "bc-rule__band bc-rule__band--lit" : "bc-rule__band"}
                x={b.x}
                y={RULE_Y.band}
                textAnchor={b.anchor}
              >
                {b.text}
              </text>
            ))}
            {drawing.numbers.map((n) => (
              <text
                key={n.text}
                className="bc-rule__num"
                x={n.x}
                y={RULE_Y.number}
                textAnchor={n.anchor}
              >
                {n.text}
              </text>
            ))}
            {drawing.unitX !== null && (
              <text className="bc-rule__num" x={drawing.unitX} y={RULE_Y.number}>
                µm
              </text>
            )}
            {drawing.channels?.map((c) => (
              <g key={c.key}>
                <rect
                  className={`bc-rule__channel bc-rule__channel--${c.key}`}
                  x={c.x}
                  y={RULE_Y.channel}
                  width={c.w}
                  height={RULE_Y.channelHeight}
                />
                <text className="bc-rule__letter" x={c.mid} y={RULE_Y.letter} textAnchor="middle">
                  {c.letter}
                </text>
              </g>
            ))}
          </>
        )}
      </svg>
    </div>
  );
}
