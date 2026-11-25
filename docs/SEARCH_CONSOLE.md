# Google Search Console: status and follow-ups

The user guide (https://csipapicsa.github.io/SongSelector/) has been in Google Search Console since 2026-11-24.

## Done

- Added a URL-prefix property, `https://csipapicsa.github.io/SongSelector/`, and verified it with the HTML-tag method.
  The tag comes from `overrides/main.html` (Material `extrahead` block), and the token is `extra.google_site_verification`
  in `mkdocs.yml` (PR #73). Leave it in place: removing the tag un-verifies the property.
- Submitted `sitemap.xml`. MkDocs builds it with 17 URLs, and it is served with `200 application/xml`.

## Open problem: sitemap shows "Couldn't fetch"

The status appeared right after submitting, and **Last read** stayed empty, so Google has not fetched the file yet.
The file itself is valid. This is a known pattern for new `*.github.io` sites: the console shows a pending sitemap as
"Couldn't fetch". It can clear within hours, or take weeks. Resubmitting does not speed it up, and the old sitemap
ping URL was removed in 2023.

Not the cause, already checked: the URL (submitted without a leading slash), XML validity, HTTP status, content type
and robots blocking (there is no robots.txt, so nothing is blocked).

## To do

1. [ ] **Remove the stray `/sitemap` entry** in Search Console (⋮ → Remove sitemap). Only `sitemap.xml` exists.
2. [ ] **Request indexing by hand** (URL inspection → Request indexing, about 10 per day). Start with the hub pages
   and let the navigation links do the rest:
   - `/` (home)
   - `/getting-started/install/`
   - `/dj-software/`
   - `/sound/similarity-map/`
   - then `/safety/`, `/troubleshooting/` and the per-program pages
3. [ ] **Re-check the sitemap row** after a few days. If it still says "Couldn't fetch" after about 2 weeks, try the
   optional steps below.
4. [ ] **GitHub repo metadata.** The description, website and topics are all empty. The website link also gives
   Google a link to the docs from a page it crawls often. One call:
   ```
   gh repo edit csipapicsa/SongSelector \
     --description "Pick the next track: a companion app for Traktor, Rekordbox and Mixxx" \
     --homepage https://csipapicsa.github.io/SongSelector/ \
     --add-topic dj --add-topic traktor --add-topic rekordbox --add-topic mixxx \
     --add-topic music-library --add-topic audio-similarity
   ```
5. [ ] **Bing Webmaster Tools.** Import the property from Search Console (one click). Bing usually reads GitHub Pages
   sitemaps without trouble, and its index also feeds Copilot and other AI search tools.

## Optional, weaker evidence

- **Root robots.txt.** Crawlers read `robots.txt` only at the host root (`https://csipapicsa.github.io/robots.txt`,
  currently 404), never at `/SongSelector/robots.txt`. Adding one means creating a `csipapicsa.github.io` user-site
  repo with:
  ```
  User-agent: *
  Disallow:
  Sitemap: https://csipapicsa.github.io/SongSelector/sitemap.xml
  ```
  Low risk, but the only report of it helping is for a user site, not a project site.
- **Custom domain.** One report says a custom domain un-stuck sitemap fetches. It costs a domain and DNS setup, and
  the property would need re-verifying. Only consider it if indexing stays poor.

## Sources

- [Google: Sitemaps report](https://support.google.com/webmasters/answer/7451001?hl=en)
- [Search Central community: sitemap could not be read](https://support.google.com/webmasters/thread/3105916/sitemap-could-not-be-read-in-new-gsc)
- [dev.to: Google can't fetch your GitHub Pages sitemap, but Bing can](https://dev.to/hexisteme/google-cant-fetch-your-github-pages-sitemap-but-bing-can-a-diagnosis-and-workaround-playbook-512k)
- [dev.to: Search Console can't fetch sitemap on GitHub Pages](https://dev.to/stankukucka/google-search-console-cant-fetch-sitemap-on-github-pages-31kn)
- [Hugo forum: Couldn't fetch for sitemap.xml](https://discourse.gohugo.io/t/unable-to-submit-sitemap-xml-feed-xml-to-google-search-console-for-my-hugo-generated-site-couldn-t-fetch/56346)
