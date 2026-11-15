import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Landing } from "./Landing";
import { FRAME_PX, HERO_PAIR, pictureUrl, TRY_PAIR } from "./pictures";

/** The page's first markup, which the browser builds its accessibility tree from. */
const html = renderToStaticMarkup(createElement(Landing));

/** Undo React's escaping of text and attribute values. */
function unescapeHtml(s: string): string {
  return s
    .replaceAll("&#x27;", "'")
    .replaceAll("&quot;", '"')
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

/** Every opening tag of this element that carries exactly this class. */
function openingTags(element: string, className: string): string[] {
  const tag = new RegExp(`<${element}\\s[^>]*class="${className}"[^>]*>`, "g");
  return [...html.matchAll(tag)].map((m) => m[0]);
}

/** An attribute's value as written in the markup (still escaped), or null. */
function rawAttribute(tag: string, name: string): string | null {
  return tag.match(new RegExp(`\\s${name}="([^"]*)"`))?.[1] ?? null;
}

describe("the landing page's accessible names", () => {
  it("names each epoch button with its date and which picture it is, with no space before the comma", () => {
    const buttons = openingTags("button", "tb-epoch");
    expect(buttons.map((b) => unescapeHtml(rawAttribute(b, "aria-label") ?? ""))).toEqual([
      "Aug 2025, the earlier picture",
      "Sep 2026, the later picture",
      "Nov 2025, the earlier picture",
      "May 2026, the later picture",
    ]);
  });

  it("starts each epoch button's name with the date it shows", () => {
    for (const pair of [HERO_PAIR, TRY_PAIR]) {
      for (const picture of [pair.a, pair.b]) {
        const shown = `<span class="tb-mono">${picture.date}</span></button>`;
        expect(html).toContain(shown);
      }
    }
  });

  it("names each figure by the object in it, not by its controls", () => {
    const figures = openingTags("figure", "tb-unit");
    const names = figures.map((figure) => {
      const id = rawAttribute(figure, "aria-labelledby");
      if (!id) return null;
      const at = html.indexOf(` id="${id}"`);
      if (at < 0) return null;
      const start = html.indexOf(">", at) + 1;
      return unescapeHtml(html.slice(start, html.indexOf("<", start)));
    });
    expect(names).toEqual([HERO_PAIR.name, TRY_PAIR.name]);
  });
});

describe("the landing page's pictures", () => {
  it("shows only the recorded frames, at their native 119 pixels, with their descriptions", () => {
    const images = [...html.matchAll(/<img\s[^>]*>/g)].map((m) => m[0]);
    const pictures = [HERO_PAIR.a, HERO_PAIR.b, TRY_PAIR.a, TRY_PAIR.b];
    expect(images).toHaveLength(pictures.length);
    images.forEach((img, i) => {
      expect(rawAttribute(img, "src")).toBe(pictureUrl(pictures[i]));
      expect(rawAttribute(img, "width")).toBe(String(FRAME_PX));
      expect(rawAttribute(img, "height")).toBe(String(FRAME_PX));
      expect(unescapeHtml(rawAttribute(img, "alt") ?? "")).toBe(pictures[i].alt);
    });
  });
});
