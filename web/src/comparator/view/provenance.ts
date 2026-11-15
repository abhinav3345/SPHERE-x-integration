/**
 * The provenance sentence (Handoff-copy, section 12): the releases with their DOIs, from the
 * manifest when a field is on screen. Without one, the two releases the product reads and their
 * DOIs, which are facts of the data product (IRSA: DR1 10.26131/IRSA678, QR3 10.26131/IRSA662).
 */
import type { BandId, Provenance, ViewId } from "../model";

const PREFIX = "SPHEREx Spectral Images";

export interface DoiLink {
  doi: string;
  href: string;
}

/** The releases the product reads, with their DOIs: what the line says before a field is open. */
export const PRODUCT_RELEASES: readonly { name: string; doi: DoiLink }[] = [
  { name: "DR1", doi: { doi: "10.26131/IRSA678", href: "https://doi.org/10.26131/IRSA678" } },
  { name: "QR3", doi: { doi: "10.26131/IRSA662", href: "https://doi.org/10.26131/IRSA662" } },
];

export interface ReleasePart {
  name: string;
  doi: DoiLink | null;
}

export interface Releases {
  /** "SPHEREx Spectral Images" */
  prefix: string;
  /** The releases in order, each with its DOI when the manifest cites one for it. */
  parts: ReleasePart[];
  /** DOIs the manifest cites that name no release of this field (none in the recorded fields). */
  others: DoiLink[];
  /** "SPHEREx Spectral Images, DR1 and QR3": the plain sentence. */
  text: string;
}

/** ", " between items and " and " before the last. */
export function separator(index: number, count: number): string {
  if (index === 0) return "";
  return index === count - 1 ? " and " : ", ";
}

/** The release names of the ViewModel's sentence "SPHEREx Spectral Images, DR1 and QR3". */
export function releaseNames(release: string): string[] | null {
  if (!release.startsWith(PREFIX)) return null;
  const rest = release.slice(PREFIX.length).replace(/^, /, "");
  if (rest === "") return [];
  const last = rest.lastIndexOf(" and ");
  const head = last > -1 ? rest.slice(0, last) : rest;
  const names = head.split(", ");
  if (last > -1) names.push(rest.slice(last + " and ".length));
  return names;
}

export function releasesOf(p: Provenance | null): Releases {
  if (!p) {
    const parts = PRODUCT_RELEASES.map((r) => ({ name: r.name, doi: r.doi }));
    return {
      prefix: PREFIX,
      parts,
      others: [],
      text: `${PREFIX}, ${parts.map((r, i) => separator(i, parts.length) + r.name).join("")}`,
    };
  }
  const names = releaseNames(p.release);
  const link = (d: Provenance["dois"][number]): DoiLink => ({ doi: d.doi, href: d.href });
  if (names === null) {
    return { prefix: p.release, parts: [], others: p.dois.map(link), text: p.release };
  }
  const parts = names.map((name) => {
    const cited = p.dois.find((d) => d.release === name);
    return { name, doi: cited ? link(cited) : null };
  });
  const others = p.dois.filter((d) => d.release === null || !names.includes(d.release)).map(link);
  return { prefix: PREFIX, parts, others, text: p.release };
}

/**
 * Whether "Brightness scale: asinh, …" describes what is on screen: one grey scale shared by every
 * frame, which is true in Blink and Side by side on one band. Three-colour has three scales,
 * Difference its σ scale and Then and now a scale per survey, so the line is left out there.
 */
export function stretchShown(p: Provenance | null, band: BandId, view: ViewId): boolean {
  return p?.stretch != null && band !== "rgb" && (view === "blink" || view === "side");
}
