# Plan: "Akda", a personal blog

The plan agreed on 2026-10-30. What changed while building it:
- On narrower screens, On This Page sits above the article, because a list of headings is no use after them. Tags stay below.
- The owner's comment queue leaves out posts that went back to draft, so that "drafts stay private" holds for their titles too.
- The Versions panel is its own page, linked from the editor.
- Posts got an `excerpt` column (the summary, or the first words without headings) for cards.

## Context

A new learning project for https://github.com/jcatibog014/personal_blog (it only has a one-line README). People can create posts, edit drafts, publish articles and add comments. The skills to practise are **authentication, authorization and relational data**.

Python suits this well: the Flask + SQLAlchemy setup from Sangkap (`recipe_organizer`) already has most of the plumbing, so the effort can go into permissions and data rather than setup.

What you chose:
- **Name:** Akda ("literary work"). Repo `personal_blog`, package `akda`, local port 5005.
- **Accounts:** three roles (owner, author, reader).
- **Home page:** featured post + grid.
- **Look:** editorial magazine, with light and dark modes.
- **Editor:** Markdown split view with live preview.
- **Extras:** Finding Posts, Comment Extras and Writer Tools. Reader Accounts (profiles, likes, saved posts, reset link) is left out.
- **Delivery:** one PR with a commit per stage, no stops for confirmation.
- **Deploy:** Render + Neon. I prepare the files and guide you; you do the account steps.

## Stack

- Python 3.13, Flask 3, Jinja, server-rendered forms. Every page works without JavaScript; `app.js` only adds extras (live preview, autosave, theme switch, menu).
- SQLAlchemy 2.0 + Alembic. SQLite locally and in tests, Neon PostgreSQL live, no dialect-only SQL.
- New libraries: **markdown-it-py** (Markdown to HTML) and **nh3** (cleans the HTML).
- Pillow for images, stored in the database because Render's free disk is wiped on restart.
- Login is written by hand with Werkzeug password hashes, not Flask-Login, because login is the skill to practise.

## Reuse from `Documents\Workspace\recipe_organizer`

Copy and adapt rather than rewrite:
- `sangkap/db.py`: engine, per-request session, naming convention, `upgrade-db`.
- `sangkap/auth.py`: `check_login()` with its 5-try lock, `safe_next()`, `log_in()`, `load_user()`, CSRF, demo pattern, CLI.
- `sangkap/__init__.py`: cookie settings, ProxyFix, CSP and security headers.
- `sangkap/photos.py`: resize to WebP, drop EXIF, pixel guard.
- `sangkap/migrations/`, `alembic.ini`, `pytest.ini`, `tests/conftest.py`, `tests/test_migrations.py`, `render.yaml`, `.python-version`, `.gitignore`.
- `AGENTS.md` + `CLAUDE.md` structure, and `docs/take_screenshots.py`.

## Roles and permissions

All rules live in one file, `akda/permissions.py`, as pure functions (`can_edit_post(user, post)` and so on). Views call these and never check roles themselves.

| Action | Visitor | Reader | Author | Owner |
|---|---|---|---|---|
| Read published posts and comments | Yes | Yes | Yes | Yes |
| Comment, reply, report | No | Yes | Yes | Yes |
| Edit own comment (within 15 minutes) | No | Yes | Yes | Yes |
| Delete own comment | No | Yes | Yes | Yes |
| Write posts; see and edit own drafts | No | No | Yes | Yes |
| Publish, schedule, unpublish own posts | No | No | Yes | Yes |
| Moderate comments on own posts | No | No | Yes | Yes |
| Moderate any comment | No | No | No | Yes |
| Unpublish or delete anyone's published post | No | No | No | Yes |
| Read or edit someone else's draft | No | No | No | No |
| Invite authors, block users | No | No | No | Yes |

Decisions:
- **Authors publish without approval.** The owner invited them and can unpublish anything.
- **Drafts stay private, even from the owner.** Someone else's draft gives 404, so its existence isn't revealed. An action on a post you can see but may not change gives 403.
- **Owner account:** made on the command line only (`create-user --role owner`). The sign-up page can only ever make readers.
- **Authors:** join through a one-time invite link that expires after 7 days. Only a hash of the token is stored.
- **Blocking:** users are blocked, never deleted, so their comments stay linked. Block logs them out straight away.
- **Sessions:** changing a password or being blocked ends all other sessions (`session_version` is checked on every request).
- **Forgotten passwords:** there is no email service, so the owner resets them with the `set-password` command.

**Demo:** "Try Demo" logs in as a sandbox author. Its posts and comments are seen only by demo visitors and never appear to anyone else, in lists, search or RSS. It can't comment on real posts. It resets itself after an hour and comes with sample posts and comments from sample readers nobody can log in as, so moderation can be tried.

## Data model

```
users ─┬─< posts ─┬─< post_tags >── tags
       │          ├─< post_versions
       │          ├─< comments ──< comment_reports >── users
       │          └── images (cover)
       ├─< comments (self-link: parent_id, one level of replies)
       ├─< images
       └─< invites
```

| Table | Key columns | Notes |
|---|---|---|
| `users` | username UNIQUE, display_name, password_hash, role (CHECK), bio, is_blocked, is_demo, demo_reset_at, failed_logins, locked_until, session_version | The owner's `bio` is the About page |
| `invites` | token_hash UNIQUE, created_by, expires_at, used_by, used_at | One-time |
| `posts` | author_id, title, slug UNIQUE, summary, body_md, body_html, status (draft/published), published_at, reading_minutes, cover_image_id, revision, created_at, updated_at | `body_md` and `body_html` are deferred, so lists stay light |
| `post_versions` | post_id, title, summary, body_md, saved_by, saved_at | Last 30 per post |
| `tags` | name UNIQUE, slug UNIQUE | Shared |
| `post_tags` | post_id, tag_id (both the key) | Many-to-many |
| `comments` | post_id, user_id, parent_id (self), body, status (pending/approved/rejected), edited_at, deleted_at, created_at | Soft delete keeps replies in place |
| `comment_reports` | comment_id, reporter_id, reason, resolved_at; UNIQUE(comment_id, reporter_id) | One report per person |
| `images` | owner_id, data (deferred), mime, width, height, size | Covers and pictures in posts |

Rules that avoid common bugs:
- **One rule for "live":** `status = 'published' AND published_at <= now`. Scheduling is just a future date, so Render's free plan needs no background job. The rule is one function in `posts.py`, also used for search, RSS and tags.
- **Stable links:** the slug is fixed at first publish, so a later title change doesn't break links.
- **Safe HTML:** Markdown raw HTML is turned off, then nh3 cleans the result. Pictures only load from this site (`/images/...`), and `javascript:` links are removed. Comments are plain text, never Markdown.
- **Autosave never touches a live post.** It only runs on drafts. Published posts change when you press Update.
- **Two tabs:** `revision` is checked on save. An out-of-date tab gets "This post changed in another tab" instead of overwriting newer text.
- **Comment approval:** a reader's first comment waits for approval, and later ones appear at once. Authors and the owner are always approved. The 15-minute edit window stops someone swapping an approved comment for spam later.
- **Spam:** a hidden honeypot field on sign-up, and a limit of 5 comments per 10 minutes per user.
- **Search:** case-insensitive `LIKE` on title, summary and text, with wildcards escaped.
- **Related posts:** ranked by shared tags with `GROUP BY` + `COUNT`, a good relational exercise. A test counts queries to catch N+1 problems.

## Layouts

**Public pages: masthead on top.** The large "Akda" wordmark sits above a thin rule, with Home, Tags, Archive, About, a search box and Log in. On phones the menu is behind a ☰ button.

**Home: featured + grid.** It fills wide screens.
```
                       AKDA
 ───────────────────────────────────────────────
 Home   Tags   Archive   About     [Search]  Log in
 ═══════════════════════════════════════════════
 ┌───────────────────────┐  PYTHON
 │      cover image      │  A Very Large Serif
 │                       │  Headline Here
 └───────────────────────┘  Summary in one line.
                            Juan · Oct 30 · 5 min
 ───────────────────────────────────────────────
 [cover]        [cover]        [cover]        [cover]
 Title          Title          Title          Title
 Summary        Summary        Summary        Summary
 Oct 21 · 3 min Oct 12 · 8 min Oct 2 · 2 min  Sep 9 · 4 min
```
A post without a cover gets a text-only card with a larger headline, never a stand-in picture. Tag, search and archive pages use the same grid.

**Article: reading width in the middle, side columns for wide screens.**
```
 ┌───────────────────────────────────────────────┐
 │           full-width cover image              │
 └───────────────────────────────────────────────┘
              PYTHON
              A Very Large Serif Headline
              Juan · Oct 30, 2026 · 5 min read
 ─────────────────────────────────────────────────
 On This Page │ Article text about 70 characters  │ Tags
 Heading one  │ wide, in a comfortable serif...   │ #python
 Heading two  │                                   │ #flask
 ─────────────────────────────────────────────────
              Related Posts   [card] [card] [card]
              Comments (3)    form, then the thread
```
The side columns fold under the article on narrower screens.

**The Desk (`/desk`), for authors and the owner:** a Gawi-style sidebar with My Posts (Drafts, Scheduled and Published tabs), Comments (the moderation queue and reports), Settings, plus People (invites and blocking), which only the owner sees.

**Editor:** the split view you picked. Markdown is on the left and the preview on the right, with Save draft and Publish at the top right, and tabs on phones. It adds a schedule date picker and a Versions panel. Preview is rendered by the server, so it matches the published page exactly. Without JavaScript, a Preview button does the same job.

**Login and sign-up:** a welcome panel beside one card, as in Gawi, with the Try Demo button under the login form. Readers get a small Settings page (name and password).

**Look:** near-black ink on off-white with thin rules and one deep crimson accent, and a matching dark mode. Playfair Display for headlines, Source Serif 4 for article text, the system font for menus. The two fonts are small subset files hosted by the app, which suits your limited network. Your UI rules apply: Title Case for pages and headings, sentence case for buttons, no decorative emoji, aligned controls, sizes in `rem`, wide-screen font steps.

## Stages (one PR, one commit per stage)

Setup: clone into `Documents\Workspace\personal_blog`, create `.venv`, and work on branch `build-akda`. Save this plan as `docs/PLAN.md`.

1. **Foundation:** project skeleton, Alembic, `users`, login, logout, reader sign-up, password change, lock, `session_version`, CSRF, security headers, `permissions.py`, masthead, theme, CLI (`upgrade-db`, `create-user`, `set-password`).
2. **Posts:** `posts`, the Desk's My Posts page, split-view editor with live preview, drafts, publish, unpublish, delete, slugs, safe Markdown; the public Home and Article pages.
3. **Comments:** `comments` and `comment_reports`, replies, approval queue, reporting, edit window and "edited" label, soft delete, the Desk's Comments page.
4. **Finding Posts:** tags, tag pages, search, monthly archive, related posts, RSS at `/feed.xml`, reading time, About page, On This Page list.
5. **Writer Tools:** autosave, version history and restore, scheduled publishing, cover images and pictures in posts.
6. **People and Demo:** invites, People page, blocking, sandbox demo with its sample data and reset.
7. **Finish and Deploy:** phone and wide-screen pass, `render.yaml` (service `akda`), simple A1-level README with screenshots and a table of tools, `AGENTS.md` + `CLAUDE.md`, then open the PR with step-by-step Neon and Render instructions.

## Verification

- **Automated (`pytest`, never online):**
  - `test_permissions.py`: a table of every role against every action, plus route tests showing the real 403 and 404 responses.
  - **Privacy:** drafts, scheduled posts and demo content never appear in home, tags, search, archive, related posts or RSS.
  - **Safety:** script tags and `javascript:` links are removed, POST without CSRF fails, `safe_next()` rejects other sites.
  - **Login:** lock after 5 tries, a used or expired invite fails, sign-up can't choose a role, sessions end after a password change or block.
  - **Comments:** approval flow, one-level replies, edit window, one report per person.
  - **Editor:** autosave skips live posts, stale `revision` is refused, version restore loses nothing.
  - **Data:** `test_migrations.py` confirms models and migrations agree; query counts catch N+1 problems.
- **Real browser (Playwright borrowed from `expense_tracker`'s `.venv`):** run on port 5005 and go through it as all three roles: invite an author, write and publish a post, comment as a new reader, approve it. Check screenshots at phone, laptop and ~2200px widths, in light and dark, for alignment.
- **PostgreSQL:** the same tests can run against an empty Neon branch through `TEST_DATABASE_URL`. You run this step, as you did for Ang Gastos!, because there is no local Postgres.
