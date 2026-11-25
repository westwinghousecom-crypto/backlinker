import { describe, expect, it } from "vitest";
import { findSocialLinks, platformFor } from "./social";

describe("social link detection", () => {
  it("recognises the major platforms, including subdomains and odd casing", () => {
    expect(platformFor("https://www.facebook.com/share/p/1JaLqV9B7M/")?.name).toBe("facebook");
    expect(platformFor("https://m.facebook.com/x")?.name).toBe("facebook");
    expect(platformFor("HTTPS://WWW.INSTAGRAM.COM/p/x")?.name).toBe("instagram");
    expect(platformFor("https://twitter.com/u/status/1")?.name).toBe("x");
    expect(platformFor("https://youtu.be/abc")?.name).toBe("youtube");
  });

  it("does not flag ordinary sites or look-alike domains", () => {
    for (const u of [
      "https://westwinghouse.com/post",
      "https://notfacebook.com/x",
      "https://facebook.com.evil.example/x",
      "https://example.com/facebook.com",
      "https://medium.com/@a/b",
      "not a url",
      "",
    ]) {
      expect(platformFor(u)).toBeNull();
    }
  });

  it("groups links by platform with counts and ignores everything else", () => {
    const groups = findSocialLinks([
      "https://www.facebook.com/a",
      "https://www.facebook.com/b",
      "https://x.com/u/status/1",
      "https://westwinghouse.com/post",
    ]);
    expect(groups.map((g) => [g.platform.name, g.count])).toEqual([
      ["facebook", 2],
      ["x", 1],
    ]);
    expect(findSocialLinks(["https://westwinghouse.com/post"])).toEqual([]);
  });

  it("gives hedged guidance, never a promise", () => {
    const advice = platformFor("https://www.facebook.com/a")!.advice;
    expect(advice).toMatch(/usually|often|rarely|sometimes|can be/i);
    expect(advice).not.toMatch(/will be indexed|guarantee/i);
  });
});
