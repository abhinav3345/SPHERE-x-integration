import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { FRAME_PX, HERO_PAIR, type Pair, type Picture, pictureUrl, TRY_PAIR } from "./pictures";

/** The provenance file written when the frames were exported from the comparator. */
interface FrameRecord {
  file: string;
  field: string;
  key: string;
  band: string;
  wavelength_um: string;
  dates: string;
  exposures: number;
  stretch_mjy_sr: [number, number];
}

const publicDir = new URL("../../public/landing/", import.meta.url);
const records: FrameRecord[] = JSON.parse(
  readFileSync(new URL("frames.json", publicDir), "utf8"),
).frames;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function recordOf(picture: Picture): FrameRecord {
  const record = records.find((r) => r.file === picture.file);
  if (!record) throw new Error(`${picture.file} is not in frames.json`);
  return record;
}

/** "2025-08-15 to 2025-09-05" as the first and last day. */
function range(record: FrameRecord): [Date, Date] {
  const [first, last] = record.dates.split(" to ").map((d) => new Date(`${d}T00:00:00Z`));
  return [first, last];
}

/** The month and year covering most days of the date range, as the buttons write it. */
function mainMonth(record: FrameRecord): string {
  const [first, last] = range(record);
  const days = new Map<string, number>();
  for (let t = first.getTime(); t <= last.getTime(); t += 86_400_000) {
    const d = new Date(t);
    const label = `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
    days.set(label, (days.get(label) ?? 0) + 1);
  }
  return [...days.entries()].sort((x, y) => y[1] - x[1])[0][0];
}

/** Width and height from a PNG's IHDR chunk. */
function pngSize(file: string): [number, number] {
  const bytes = readFileSync(new URL(file, publicDir));
  expect(bytes.subarray(1, 4).toString("latin1")).toBe("PNG");
  expect(bytes.subarray(12, 16).toString("latin1")).toBe("IHDR");
  return [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
}

describe.each([
  ["hero", HERO_PAIR],
  ["harder one", TRY_PAIR],
] as [string, Pair][])("the %s pair", (_, pair) => {
  it("is two recorded frames of one field, band and brightness scale", () => {
    const a = recordOf(pair.a);
    const b = recordOf(pair.b);
    expect(a.key).toBe(b.key);
    expect(a.field).toBe(b.field);
    expect(a.band).toBe(b.band);
    expect(a.wavelength_um).toBe(b.wavelength_um);
    expect(a.stretch_mjy_sr).toEqual(b.stretch_mjy_sr);
  });

  it("puts the earlier picture first", () => {
    expect(range(recordOf(pair.a))[1].getTime()).toBeLessThan(range(recordOf(pair.b))[0].getTime());
  });

  it("labels each picture with the month that covers most of its date range", () => {
    expect(pair.a.date).toBe(mainMonth(recordOf(pair.a)));
    expect(pair.b.date).toBe(mainMonth(recordOf(pair.b)));
  });

  it("ships each picture at 119 by 119 pixels", () => {
    for (const picture of [pair.a, pair.b]) {
      expect(pngSize(picture.file)).toEqual([FRAME_PX, FRAME_PX]);
      expect(pictureUrl(picture)).toBe(`/landing/${picture.file}`);
    }
  });
});

/** The recorded fields bundled with the site (scripts/sync-contract.mjs copies them in). */
const fixturesDir = new URL("../../public/fixtures/", import.meta.url);
const manifestOf = (field: string) => new URL(`${field}/manifest.json`, fixturesDir);
const bundled = records.every((record) => existsSync(manifestOf(record.field)));

describe.skipIf(!bundled)("frames.json against the bundled recorded fields", () => {
  it.each(records.map((record) => [record.file, record] as const))(
    "%s names the key of the recorded field it belongs to",
    (_file, record) => {
      const manifest = JSON.parse(readFileSync(manifestOf(record.field), "utf8"));
      expect(record.key).toBe(manifest.key);
    },
  );
});
