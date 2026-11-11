# CleanYourMail ten-language docs and website plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the CleanYourMail app documentation and website to the same ten-language coverage as CleanYourPhone: English, Spanish, German, French, Italian, Japanese, Korean, Brazilian Portuguese, Simplified Chinese and Traditional Chinese.

**Architecture:** The app gets nine translated README files plus language links and two real screenshots; the static website gets eight translated landing pages, a language selector, hreflang metadata, a ten-entry sitemap and a 404 language list. The pages reuse the existing CleanYourMail markup, CSP, feedback form and Worker; only visible copy and locale metadata change.

**Tech Stack:** Markdown, static HTML/CSS/JS, Python unittest, GitHub Pages, PySide6 for screenshots.

**Spec:** This plan; the reference is CleanYourPhone `a0ad5e8` (web), `bfaff3c` (app READMEs) and `5705d84` (app screenshots).

## Global Constraints

- Ten languages: `en`, `es`, `de`, `fr`, `it`, `ja`, `ko`, `pt-BR`, `zh-CN`, `zh-TW`.
- English remains the source of truth; commands, paths, product names, URLs and provider names stay unchanged.
- No content changes to safety claims, Outlook qualification, feedback consent or privacy wording; translate them, do not weaken them.
- Website remains static, no cookies, no analytics, no third-party assets; CSP still allows only the feedback Worker.
- Every page keeps the same feedback form ids, `data-endpoint`, CSP and JSON-LD hash.
- App READMEs use `README.<code>.md`; English stays `README.md`.
- No secret, email, account or screenshot of real mail.
- The website deployment is the only publish step; the app is docs-only, no new binary.

## Review Focus

- A language selector points to every page and marks the current language.
- A translated page still has the feedback form, consent and Worker endpoint.
- The JSON-LD hash in the CSP matches the translated JSON-LD.
- The sitemap and hreflang alternates list all ten pages.
- No translated page has an English leftover in a visible heading, button or status line.
- App READMEs keep the same code blocks and install links; no broken relative image or language link.

---

### Task 1: App screenshots and English README index

**Files:**
- Create: `docs/images/app-provider.png`
- Create: `docs/images/app-review.png`
- Modify: `README.md`

**Interfaces:**
- Screenshots 1040×820 or the window's natural size; no real address, provider credentials or real message data.

- [ ] **Step 1: Capture the provider and review screens**

Use a temporary `SettingsStore`/`AppServices` with `demo@example.com`, a fake plan/report/scan and no real config. Render with the Windows Qt platform, call `window.grab().save(...)`, and inspect the two PNGs. Do not use a real account or secret.

- [ ] **Step 2: Add the language index and screenshots**

At the top of `README.md`, add a centered language line with links to all ten README files. Add a `## Screenshots` section with the two images and short captions. Keep the current content; do not remove the banner or badges.

- [ ] **Step 3: Verify**

Run `python -m pytest -q` (docs-only change still must keep the suite green). Check every language link target exists.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/images
git commit -m "docs: add app screenshots and the language index"
```

---

### Task 2: App README translations

**Files:**
- Create: `README.es.md`
- Create: `README.de.md`
- Create: `README.fr.md`
- Create: `README.it.md`
- Create: `README.ja.md`
- Create: `README.ko.md`
- Create: `README.pt-BR.md`
- Create: `README.zh-CN.md`
- Create: `README.zh-TW.md`

**Interfaces:**
- Consumes: the English `README.md` and the screenshot paths from Task 1.
- Each file starts with the same banner/badges and a language line; `<b>` marks the current language.

- [ ] **Step 1: Translate the README**

Translate the visible prose, headings, table cells and alt text. Keep code blocks, commands, URLs, versions, provider names and file paths in English. Keep the same section order and links. For the internal "Provider status" link, use the translated heading anchor or plain text; never leave a broken `#provider-status` link.

- [ ] **Step 2: Add the language line**

Use the same ten language links in every file, with the current language in `<b>`. The links are relative: `README.md`, `README.es.md`, `README.de.md`, `README.fr.md`, `README.it.md`, `README.ja.md`, `README.ko.md`, `README.pt-BR.md`, `README.zh-CN.md`, `README.zh-TW.md`.

- [ ] **Step 3: Verify**

Check every file has the same code blocks, the screenshot image paths resolve, and no English paragraph remains untranslated. Run a small link/anchor check across all ten READMEs.

- [ ] **Step 4: Commit**

```bash
git add README.*.md
git commit -m "docs: add the app README in nine languages"
```

---

### Task 3: Web language infrastructure and English/Spanish pages

**Files:**
- Modify: `index.html`
- Modify: `es.html`
- Modify: `app.js`
- Modify: `styles.css`
- Modify: `tests/test_site.py`
- Modify: `404.html`
- Modify: `sitemap.xml`

**Interfaces:**
- Language codes and files: `en` → `index.html`, `es` → `es.html`, `de` → `de.html`, `fr` → `fr.html`, `it` → `it.html`, `ja` → `ja.html`, `ko` → `ko.html`, `pt-BR` → `pt-BR.html`, `zh-CN` → `zh-CN.html`, `zh-TW` → `zh-TW.html`.
- The selector is `<select id="language-select">` inside the nav; `app.js` navigates on change.
- `app.js` gets a `MESSAGES` object for ten languages covering copy/toast/feedback status.

- [ ] **Step 1: Add the language selector and metadata to EN/ES**

Replace the existing single `ES` link with the ten-option language selector. Add the ten `hreflang` alternates plus `x-default`, the translated `og:locale`/alternate locales, and keep the existing canonical. Add the selector styles to `styles.css`.

- [ ] **Step 2: Add the multilingual client messages**

Copy the CleanYourPhone `MESSAGES` structure into CleanYourMail `app.js` for all ten languages, adapting the feedback copy to CleanYourMail. Replace the `lang === "es"` ternaries with `messages.*`; add the language-select change handler. Keep exactly one `fetch(` and no hardcoded remote URL.

- [ ] **Step 3: Update the 404 and sitemap**

`404.html` gets the ten-language link list; `sitemap.xml` gets ten `<url>` entries, each with the ten alternate links and `x-default`.

- [ ] **Step 4: Generalize the tests**

`PAGES` includes all ten pages plus `404.html`; `PAGES_WITH_JSONLD` includes the ten landing pages. Test each page for title/viewport/unique ids/local links, language-select options, hreflang, feedback form ids/CSP/consent/noscript/limits, app release links/note/Outlook copy, provider logos, canonical, social metadata and JSON-LD hash. Keep the specific EN/ES copy assertions where useful; avoid making every test only English.

- [ ] **Step 5: Verify**

`python -m unittest discover -s tests -v` and `node --test tests/feedback_app.test.mjs` must pass for the pages that exist at this point. The eight new pages are added in Task 4.

- [ ] **Step 6: Commit**

```bash
git add index.html es.html app.js styles.css tests/test_site.py 404.html sitemap.xml
git commit -m "site: prepare the ten-language landing pages"
```

---

### Task 4: Web pages in German, French, Italian, Japanese and Korean

**Files:**
- Create: `de.html`
- Create: `fr.html`
- Create: `it.html`
- Create: `ja.html`
- Create: `ko.html`

**Interfaces:**
- Consumes: the English page as the structural template and Task 3's selector/sitemap codes.

- [ ] **Step 1: Translate each page**

Copy the English page structure exactly. Set `<html lang>`, title/meta description, og/twitter locale, JSON-LD `inLanguage` and `url`, canonical, and the language selector's `selected` option. Translate all visible text, including nav, hero, cards, steps, provider strip, safety, FAQ, feedback form, CTA and footer. Keep URLs, ids, classes, `data-endpoint`, CSP, provider names and code samples unchanged. Recompute the JSON-LD CSP hash after translating the JSON-LD.

- [ ] **Step 2: Verify each page**

Check the feedback form ids, 10 selector options, 10 hreflang alternates, `x-default`, no English leftovers in visible copy, and CSP hash. Run `python -m unittest discover -s tests -v` after updating `PAGES`/sitemap for these five pages.

- [ ] **Step 3: Commit**

```bash
git add de.html fr.html it.html ja.html ko.html tests/test_site.py sitemap.xml
git commit -m "site: add the German, French, Italian, Japanese and Korean pages"
```

---

### Task 5: Web pages in Brazilian Portuguese, Simplified and Traditional Chinese

**Files:**
- Create: `pt-BR.html`
- Create: `zh-CN.html`
- Create: `zh-TW.html`

**Interfaces:**
- Consumes: Task 3/4 structure; never edit the existing pages.

- [ ] **Step 1: Translate each page**

Same rules as Task 4. Use `pt-BR`, `zh-CN` and `zh-TW`; set the selector's `selected` option and the JSON-LD `inLanguage`/`url`. Recompute the CSP hash.

- [ ] **Step 2: Verify**

`PAGES` and sitemap include the three pages; all tests pass; no English leftovers; all feedback forms keep the same ids and endpoint.

- [ ] **Step 3: Commit**

```bash
git add pt-BR.html zh-CN.html zh-TW.html tests/test_site.py sitemap.xml
git commit -m "site: add the Portuguese and Chinese pages"
```

---

### Task 6: Final verification and deploy

**Files:**
- No source changes expected.

- [ ] **Step 1: Verify both repos**

App: all READMEs exist, screenshot paths resolve, `python -m pytest -q` green.
Web: `python -m unittest discover -s tests -v`, `node --test tests/feedback_app.test.mjs` and `node --test feedback-worker/worker.test.mjs` green.

- [ ] **Step 2: Publish the website**

Merge the web branch to `main`, push, wait for the Pages deployment, and verify the ten language pages and selector on the live site. Do not push the app docs branch unless the user asks; it is docs-only.

- [ ] **Step 3: Report**

List the ten languages, the test counts, the live URLs and any language that needs a native-speaker review.
