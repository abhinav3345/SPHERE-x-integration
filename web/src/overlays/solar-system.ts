/**
 * Names of solar-system bodies. They cross a 6′ field in hours to days, so no fixed patch of sky
 * holds them across visits months apart; search says so instead of sending them to a name
 * service, which answers with nothing (CDS Sesame does not resolve "Pluto" or "3I/ATLAS").
 */

import { nameKey } from "./known-movers";

/** Bodies people are likely to type, with the name used in the sentence. */
const BODIES: readonly string[] = [
  "The Sun",
  "The Moon",
  "Mercury",
  "Venus",
  "Mars",
  "Jupiter",
  "Saturn",
  "Uranus",
  "Neptune",
  "Pluto",
  "Charon",
  "Ceres",
  "Eris",
  "Haumea",
  "Makemake",
  "Sedna",
  "Quaoar",
  "Orcus",
  "Gonggong",
  "Arrokoth",
  "Vesta",
  "Pallas",
  "Hygiea",
  "Bennu",
  "Ryugu",
  "Apophis",
  "Eros",
  "Itokawa",
  "Didymos",
  "Phobos",
  "Deimos",
  "Io",
  "Europa",
  "Ganymede",
  "Callisto",
  "Titan",
  "Enceladus",
  "Triton",
  "Halley",
  "Hale-Bopp",
  "NEOWISE",
  "Oumuamua",
  "Borisov",
];

const BY_KEY = new Map<string, string>();
for (const body of BODIES) {
  BY_KEY.set(nameKey(body), body);
  if (body.startsWith("The ")) BY_KEY.set(nameKey(body.slice(4)), body);
}
BY_KEY.set("luna", "The Moon");
BY_KEY.set("sol", "The Sun");

/** Comet and minor-planet designations: 1P/Halley, 3I/ATLAS, 67P, C/2023 A3, (433) Eros, 2024 YR4. */
const DESIGNATIONS: readonly RegExp[] = [
  /^\d{1,4}\s*[pdi](?:\s*[/-].*)?$/i,
  /^[cpdxai]\/\s*-?\d{1,4}\s+[a-z]{1,2}\d*\b/i,
  /^\(\d+\)\s*\S/,
  /^(?:1[89]|20)\d{2}\s+[a-z]{2}\d{0,3}$/i,
  /\b(?:comet|asteroid|minor planet|dwarf planet)\b/i,
];

/**
 * The subject for the sentence when an entry names a solar-system body ("Pluto", "The Moon", or
 * the designation as typed), else null.
 */
export function solarSystemSubject(text: string): string | null {
  const trimmed = text.trim().replace(/\s+/g, " ");
  // "134340 Pluto" and "(4) Vesta" are the numbered forms of listed names.
  const bare = trimmed.replace(/^\(?\d+\)?\s+/, "");
  const listed = BY_KEY.get(nameKey(trimmed)) ?? BY_KEY.get(nameKey(bare));
  if (listed !== undefined) return listed;
  return DESIGNATIONS.some((re) => re.test(trimmed)) ? trimmed : null;
}
