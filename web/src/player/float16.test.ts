import { afterEach, describe, expect, it, vi } from "vitest";
import {
  decodeFloat16,
  decodeWithBits,
  decodeWithDataView,
  decodeWithTypedArray,
  float16Path,
  halfBitsToNumber,
} from "./float16";

/** Little-endian float16 bytes for the given 16-bit patterns. */
function bytesOf(patterns: readonly number[]): ArrayBuffer {
  const buffer = new ArrayBuffer(patterns.length * 2);
  const view = new DataView(buffer);
  patterns.forEach((bits, i) => {
    view.setUint16(i * 2, bits, true);
  });
  return buffer;
}

// Bit patterns worked out by hand from IEEE 754 binary16: sign(1) exponent(5) fraction(10).
const HAND_CHECKED: readonly (readonly [bits: number, value: number, what: string])[] = [
  [0x0000, 0, "positive zero"],
  [0x8000, -0, "negative zero"],
  [0x3c00, 1, "one"],
  [0xbc00, -1, "minus one"],
  [0xc000, -2, "minus two"],
  [0x3e00, 1.5, "1.5 = 1 + 512/1024"],
  [0x3555, 0.333251953125, "nearest half to one third = 2^-2 * (1 + 341/1024)"],
  [0x4248, 3.140625, "nearest half to pi = 2 * (1 + 584/1024)"],
  [0x7bff, 65504, "largest finite = 2^15 * (2 - 2^-10)"],
  [0xfbff, -65504, "most negative finite"],
  [0x0400, 2 ** -14, "smallest normal"],
  [0x03ff, 1023 * 2 ** -24, "largest subnormal"],
  [0x0001, 2 ** -24, "smallest subnormal"],
  [0x8001, -(2 ** -24), "smallest negative subnormal"],
  [0x7c00, Number.POSITIVE_INFINITY, "positive infinity"],
  [0xfc00, Number.NEGATIVE_INFINITY, "negative infinity"],
  [0x7e00, Number.NaN, "quiet NaN"],
  [0x7c01, Number.NaN, "signalling NaN"],
  [0xfe00, Number.NaN, "negative NaN"],
];

const PATHS = [
  ["Float16Array", decodeWithTypedArray],
  ["DataView.getFloat16", decodeWithDataView],
  ["bit arithmetic", decodeWithBits],
] as const;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("this runtime", () => {
  it("has the native paths, so all three decoders are really exercised", () => {
    expect(typeof (globalThis as { Float16Array?: unknown }).Float16Array).toBe("function");
    expect(typeof DataView.prototype.getFloat16).toBe("function");
    expect(float16Path()).toBe("typed-array");
  });
});

describe.each(PATHS)("decoding with %s", (_name, decode) => {
  it.each(HAND_CHECKED)("0x%s -> %s (%s)", (bits, value) => {
    const decoded = decode(bytesOf([bits]));
    expect(decoded).toBeInstanceOf(Float32Array);
    expect(decoded).toHaveLength(1);
    // Object.is tells -0 from +0 and treats NaN as equal to NaN.
    expect(Object.is(decoded[0], value)).toBe(true);
  });

  it("reads the low byte first", () => {
    // 0x3c00 is 1.0; stored little-endian its bytes are 00 3c.
    const buffer = new Uint8Array([0x00, 0x3c, 0x00, 0xc0]).buffer;
    expect(Array.from(decode(buffer))).toEqual([1, -2]);
  });

  it("keeps the order of a whole row", () => {
    const decoded = decode(bytesOf([0x3c00, 0x7e00, 0x8000, 0x4248, 0x0001]));
    expect(decoded[0]).toBe(1);
    expect(decoded[1]).toBeNaN();
    expect(Object.is(decoded[2], -0)).toBe(true);
    expect(decoded[3]).toBe(3.140625);
    expect(decoded[4]).toBe(2 ** -24);
  });

  it("decodes an empty buffer to an empty array", () => {
    expect(decode(new ArrayBuffer(0))).toHaveLength(0);
  });

  it("rejects an odd number of bytes", () => {
    expect(() => decode(new ArrayBuffer(3))).toThrow(RangeError);
  });
});

describe("the three paths", () => {
  it("agree on all 65536 bit patterns", () => {
    const all = bytesOf(Array.from({ length: 65536 }, (_, bits) => bits));
    const typed = decodeWithTypedArray(all);
    const view = decodeWithDataView(all);
    const bits = decodeWithBits(all);
    let disagreements = 0;
    for (let i = 0; i < 65536; i++) {
      if (!Object.is(typed[i], view[i]) || !Object.is(view[i], bits[i])) disagreements++;
    }
    expect(disagreements).toBe(0);
  });

  it("give NaN for exactly the 2046 NaN patterns", () => {
    let nans = 0;
    for (let bits = 0; bits < 65536; bits++) {
      if (Number.isNaN(halfBitsToNumber(bits))) nans++;
    }
    expect(nans).toBe(2 * 1023);
  });
});

describe("decodeFloat16", () => {
  const sample = () => bytesOf([0x3c00, 0x7e00, 0x8000, 0x03ff]);
  const expectSample = (decoded: Float32Array) => {
    expect(decoded[0]).toBe(1);
    expect(decoded[1]).toBeNaN();
    expect(Object.is(decoded[2], -0)).toBe(true);
    expect(decoded[3]).toBe(1023 * 2 ** -24);
  };

  it("uses Float16Array when the runtime has it", () => {
    expect(float16Path()).toBe("typed-array");
    expectSample(decodeFloat16(sample()));
  });

  it("falls back to DataView.getFloat16 without Float16Array", () => {
    vi.stubGlobal("Float16Array", undefined);
    const getFloat16 = vi.spyOn(DataView.prototype, "getFloat16");
    expect(float16Path()).toBe("dataview");
    expectSample(decodeFloat16(sample()));
    expect(getFloat16).toHaveBeenCalledTimes(4);
  });

  it("falls back to bit arithmetic when neither exists", () => {
    vi.stubGlobal("Float16Array", undefined);
    const prototype = DataView.prototype as { getFloat16?: unknown };
    const original = prototype.getFloat16;
    prototype.getFloat16 = undefined;
    try {
      expect(float16Path()).toBe("bits");
      expectSample(decodeFloat16(sample()));
    } finally {
      prototype.getFloat16 = original;
    }
  });
});
