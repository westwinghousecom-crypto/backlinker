/** Social platforms and what they generally allow search engines to index. Guidance, not a verdict: the live check on
 *  "Check my backlinks" is the evidence. Keep in sync with backend/app/features/diagnostics/social.py (a backend test compares them). */
export interface SocialPlatform {
  name: string;
  hosts: string[];
  advice: string;
}

export const SOCIAL_PLATFORMS: SocialPlatform[] = [
  {
    name: "facebook",
    hosts: ["facebook.com", "fb.com", "fb.watch"],
    advice: "Facebook posts are usually not indexed: they are often marked noindex or need a login, and share links redirect to the real post.",
  },
  {
    name: "instagram",
    hosts: ["instagram.com"],
    advice: "Instagram posts are rarely indexed, and links in them are nofollow.",
  },
  {
    name: "x",
    hosts: ["x.com", "twitter.com"],
    advice: "Public X posts are sometimes indexed, but X often asks crawlers to log in, and links in posts are nofollow.",
  },
  {
    name: "linkedin",
    hosts: ["linkedin.com"],
    advice: "Public LinkedIn posts and articles can be indexed, but a post must be public, and links in posts are nofollow.",
  },
  {
    name: "youtube",
    hosts: ["youtube.com", "youtu.be"],
    advice: "Public YouTube videos are indexable, but links in descriptions and comments are nofollow.",
  },
  {
    name: "reddit",
    hosts: ["reddit.com"],
    advice: "Public Reddit threads are indexable, but links in them are nofollow and low-quality or removed posts are not kept.",
  },
  {
    name: "pinterest",
    hosts: ["pinterest.com"],
    advice: "Public Pinterest pins can be indexed, but links on them are nofollow.",
  },
  {
    name: "tiktok",
    hosts: ["tiktok.com"],
    advice: "TikTok pages are rarely indexed individually, and links on them are nofollow.",
  },
];

export function platformFor(url: string): SocialPlatform | null {
  let host: string;
  try {
    host = new URL(url.trim()).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return null;
  }
  return SOCIAL_PLATFORMS.find((p) => p.hosts.some((h) => host === h || host.endsWith(`.${h}`))) ?? null;
}

export interface SocialGroup {
  platform: SocialPlatform;
  count: number;
}

/** Which social platforms appear in this list of URLs, with how many links each. */
export function findSocialLinks(urls: string[]): SocialGroup[] {
  const groups = new Map<string, SocialGroup>();
  for (const url of urls) {
    const platform = platformFor(url);
    if (!platform) continue;
    const g = groups.get(platform.name);
    if (g) g.count += 1;
    else groups.set(platform.name, { platform, count: 1 });
  }
  return [...groups.values()];
}
