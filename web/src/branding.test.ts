import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Wordmark } from "./ui";
import { en } from "./i18n/en";
import { zh } from "./i18n/zh";

describe("Soorin product identity", () => {
  it("uses local company artwork, source aspect ratio and accessible product name", () => {
    const html = renderToStaticMarkup(createElement(Wordmark));
    expect(html).toContain('alt="Soorin Security"');
    expect(html).toContain('width="674" height="230"');
    expect(html).toContain('aria-label="Soorin TKG"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).not.toContain('src="https:');
  });
  it("keeps product identity consistent across existing locales", () => {
    expect(en.app.name).toBe("Soorin TKG");
    expect(zh.app.name).toBe(en.app.name);
    expect(en.login.githubUrl).toContain("SoorinSecurity");
  });
});
