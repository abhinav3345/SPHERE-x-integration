/**
 * Decoder for frames.bin (Contract v1.0 section 6): little-endian IEEE 754 half floats.
 *
 * Three paths, fastest first:
 *   1. `Float16Array`, where the runtime has it and the machine is little-endian;
 *   2. `DataView.getFloat16`;
 *   3. plain bit arithmetic, for runtimes with neither.
 * All three give identical results; NaN ("no data") survives as NaN.
 */

export type Float16Path = "typed-array" | "dataview" | "bits";

type Float16ArrayConstructor = new (buffer: ArrayBuffer) => ArrayLike<number>;
type Float16DataView = DataView & {
  getFloat16(byteOffset: number, littleEndian?: boolean): number;
};

const LITTLE_ENDIAN_MACHINE = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;

function float16ArrayConstructor(): Float16ArrayConstructor | undefined {
  const candidate = (globalThis as { Float16Array?: unknown }).Float16Array;
  return typeof candidate === "function" ? (candidate as Float16ArrayConstructor) : undefined;
}

function hasDataViewFloat16(): boolean {
  return typeof (DataView.prototype as { getFloat16?: unknown }).getFloat16 === "function";
}

/** The fastest decoding path this runtime supports. */
export function float16Path(): Float16Path {
  if (LITTLE_ENDIAN_MACHINE && float16ArrayConstructor()) return "typed-array";
  return hasDataViewFloat16() ? "dataview" : "bits";
}

function valueCount(buffer: ArrayBuffer): number {
  if (buffer.byteLength % 2 !== 0) {
    throw new RangeError(`float16 data must have an even byte length, got ${buffer.byteLength}`);
  }
  return buffer.byteLength / 2;
}

/** Path 1: reinterpret the bytes with the runtime's own `Float16Array`. */
export function decodeWithTypedArray(buffer: ArrayBuffer): Float32Array {
  valueCount(buffer);
  const Float16 = float16ArrayConstructor();
  if (!Float16 || !LITTLE_ENDIAN_MACHINE) {
    throw new Error("Float16Array is not usable in this runtime");
  }
  return new Float32Array(new Float16(buffer));
}

/** Path 2: read each value with `DataView.getFloat16`. */
export function decodeWithDataView(buffer: ArrayBuffer): Float32Array {
  const out = new Float32Array(valueCount(buffer));
  const view = new DataView(buffer) as Float16DataView;
  for (let i = 0; i < out.length; i++) out[i] = view.getFloat16(i * 2, true);
  return out;
}

/** Path 3: assemble each value from its two bytes. */
export function decodeWithBits(buffer: ArrayBuffer): Float32Array {
  const out = new Float32Array(valueCount(buffer));
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < out.length; i++) {
    out[i] = halfBitsToNumber(bytes[i * 2] | (bytes[i * 2 + 1] << 8));
  }
  return out;
}

/**
 * Value of one half float given as its 16 bits: 1 sign bit, 5 exponent bits, 10 fraction bits.
 * Exponent 0 holds zero and the subnormals; exponent 31 holds the infinities and NaN.
 */
export function halfBitsToNumber(bits: number): number {
  const sign = bits & 0x8000 ? -1 : 1;
  const exponent = (bits >> 10) & 0x1f;
  const fraction = bits & 0x3ff;
  if (exponent === 0) return sign * fraction * 2 ** -24;
  if (exponent === 0x1f) return fraction === 0 ? sign * Number.POSITIVE_INFINITY : Number.NaN;
  return sign * (1 + fraction / 1024) * 2 ** (exponent - 15);
}

/** Decodes little-endian float16 bytes into float32 values, whatever the runtime offers. */
export function decodeFloat16(buffer: ArrayBuffer): Float32Array {
  switch (float16Path()) {
    case "typed-array":
      return decodeWithTypedArray(buffer);
    case "dataview":
      return decodeWithDataView(buffer);
    default:
      return decodeWithBits(buffer);
  }
}
