# AGENTS.md

This file guides AI coding agents (Claude Code, Codex, Cursor, Copilot and others) working in this repository.

## Overview

**Akda** ("literary work"), a personal blog in Python (Flask). The repo is `personal_blog` and the Python package is `akda`. Authors write and publish posts; readers comment; the owner runs everything. The plan is `docs/PLAN.md`.

It is a learning project for **authentication, authorization and relational data**, so those parts stay easy to read: short comments that explain *why*, login written by hand (no Flask-Login), and no extra libraries unless the owner asks for them. Write the README in simple (A1-level) English.

Python 3.13 is at `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`. Use the virtual environment:

- Install: `.venv\Scripts\python -m pip install -r requirements.txt` (create `.venv` with `python -m venv .venv` first if it's missing).
- First time: `.venv\Scripts\flask --app akda upgrade-db` (makes the tables), then `.venv\Scripts\flask --app akda create-user <name> --role owner`.
- Run: `.venv\Scripts\flask --app akda run --debug --port 5005`, then open http://127.0.0.1:5005. (Ports: Swap Meter 5000, Ambon Alert 5001, Ang Gastos! 5002, Sangkap 5003, Gawi 5004.)
- Test: `.venv\Scripts\python -m pytest`. Every test gets a fresh SQLite file and never uses the internet. Set `TEST_DATABASE_URL` to an **empty** Neon branch to run the same tests on PostgreSQL (each test drops and remakes the tables). SQLAlchemy warnings fail the tests (`pytest.ini`).
- Other commands: `set-password <name>`, `reset-demo`.
- Screenshots: `docs/make_practice_data.py`, then `docs/take_screenshots.py` (Playwright + Edge; its top comment has the steps). Demo covers: `docs/make_covers.py`.

## Architecture

- **`akda/permissions.py` holds EVERY rule about roles**, as plain functions (`user` is a `User` or `None`). Views and templates (`can.can_edit_post(...)`) ask these and never read `user.role` themselves. `tests/test_permissions.py` is a table of every role against every action, plus route tests. **Add new rules here, with a table row.**
  - **Roles:** owner (made only by `create-user --role owner`), author (made only by an invite link), reader (made only by sign-up, which never reads a role from the form).
  - **Only a post's author can edit it or read its draft, even the owner can't.** The owner can only take down (unpublish or delete) what is live.
  - **404 or 403:** someone else's hidden post gives 404, so its existence isn't revealed. An action on a post you can see but may not change gives 403. `views/desk.py: refuse()`.
- **"Live" has one rule:** `status = 'published' AND published_at <= now`. `posts.live_filter()` in SQL, `permissions.is_live()` in Python; change both together. Scheduling is just a future date, so there is no background job.
- **Every public list starts from `posts.visible_filter(viewer, now)`** (home, tags, search, archive, related posts, RSS), so drafts, scheduled posts and the demo's posts can't leak. `tests/test_finding.py` checks each list. RSS always uses `viewer=None`.
- **Demo:** "Try Demo" logs in as the shared sandbox author `demo` (`is_demo`). Its posts, pictures and comments are only seen by demo visitors, who also see real posts but can't comment on them. `seed.reset_demo()` remakes it when over an hour old; sample readers can't log in. **Every page the demo can open must show an example, so add sample content in `seed.py` with every new feature** (`tests/test_demo.py` checks each page). It has its own About text, and Settings shows the name and password forms switched off. People stays owner-only. Limits: 20 posts, 10 pictures, no settings changes. The owner's queue and People page leave the demo out.
- **Login:** `auth.py`. Hashes from Werkzeug, 5 wrong passwords = 15-minute lock, `load_user()` checks `is_blocked` and `session_version` on every request (adding 1 to it ends every session: password change, block). CSRF: every POST needs `csrf_token` (`{{ csrf() }}` from `_macros.html`; JS sends it in the form data; tests use `post()` from `conftest.py`). There is no email, so a forgotten password is reset by the owner with `set-password`.
- **Invites:** `invites.py`. One-time, 7 days, only a SHA-256 of the token is stored. `claim()` is an `UPDATE ... WHERE used_at IS NULL`, so two people can't both use a link.
- **Database:** SQLAlchemy 2.0 ORM (typed `Mapped[...]`), plain (not Flask-SQLAlchemy). `akda/db.py` makes one engine per app and one session per request: `db.session()`. Nothing is saved without `.commit()`. `expire_on_commit=False`. SQLite locally (`instance/akda.sqlite`, git-ignored; foreign keys on per connection), PostgreSQL (Neon, psycopg 3) when `DATABASE_URL` is set. Keep code portable: no dialect-only SQL. Times are naive UTC (`dates.utcnow()`); people see Philippine time (`dates.to_local()`, the `nice_date` filters).
- **Migrations: Alembic**, in `akda/migrations/`. `flask --app akda upgrade-db` runs them; Render runs it before gunicorn.
  - **To change the schema:** edit `models.py`, then `.venv\Scripts\alembic revision --autogenerate -m "what changed"`, **read the new file and fix it**, and commit it. Never edit a migration that has run on the live site. `tests/test_migrations.py` fails if the models and the migrations disagree.
- **`akda/models.py` is the data model** (diagram at the top): `User`, `Post`, `Tag` + `post_tags` (plain many-to-many), `PostVersion`, `Comment` (self-link `parent_id`), `CommentReport` (UNIQUE per person), `Image`, `Invite`.
  - `Post.body_md`/`body_html`, `PostVersion.body_md` and `Image.data` are `deferred`, so lists never load them. Lists use `selectinload` (`posts.card_options()`), and tests count queries to catch N+1.
  - `Post.revision` is SQLAlchemy's `version_id_col`: it goes up on every save. The editor sends the number it started from, and a stale tab gets 409 instead of overwriting newer text. **Run queries before changing a post** (or use `no_autoflush`), or a flush can raise `StaleDataError` outside the `try`.
  - The slug is empty until the first publish, then fixed, so links never break.
- **Safe HTML: `akda/render.py`.** `body_html` only ever comes from `render.to_html()`: markdown-it with `html=False`, then nh3 (allowed tags only, no `javascript:`, pictures only from `/images/<id>`). The CSP (`__init__.py`) has no inline scripts or styles and no outside sources, so **never use `style=""` or inline `<script>`**. Comments are plain text, escaped by the templates, never Markdown.
- **Comments:** `comments.py`. A reader's first comment waits; once one is approved the rest appear at once. One level of replies (a reply to a reply joins the same thread). Soft delete; a removed comment stays as a placeholder only if it has replies. 5 comments per 10 minutes (not the owner). Edit window 15 minutes. `_scope()` in `comments.py` must match `permissions.can_moderate_comment()`. A post back in draft is private, so its comments leave the owner's queue.
- **Editor:** `views/desk.py` + `templates/desk/editor.html` + `app.js`. Actions: `save`, `publish`, `update`, `publish_now`, `preview` (no JS). `posts.snapshot()` keeps a version on those saves (newest 30). **Autosave only runs on drafts** and makes no version, because half-finished sentences must not reach readers. Restoring on a draft keeps the current text as a version first; on a live post the old text opens in the editor and goes live only on Update.
- **Pictures:** `images.py`. At most 1400 px WebP, EXIF dropped, stored in the database because Render's disk is wiped. Each also gets a 160 px square `thumb` for lists (`/images/<id>/thumb`, used by the Archive; older pictures without one send the full picture). A cover belongs to one post and is deleted with it.
- **Every page works without JavaScript.** `app.js` only adds extras (the theme choice, menu, live preview, autosave, toolbar, picture upload, leave warning). Use `.no-js-only` for fallbacks.

## UI rules (the owner's priority is neatness)

- **Look: editorial magazine.** Ink on paper, thin rules, one crimson accent. Playfair Display for headlines, Source Serif 4 for reading, the system font for menus. The fonts are self-hosted in `static/fonts/`. Dark mode is defined twice in `style.css` (device setting + the choice in Settings); change both blocks together.
- **Settings holds the controls, and the menus only navigate.** The theme (Device, Light or Dark, saved per device in `localStorage`; `theme.js` applies it before the page draws) is only on `/settings`. Log out is there too, and in the Desk's account menu (`.user-menu`, a `<details>` at the bottom of the sidebar, closed until opened). `/settings` is open to visitors, so they can choose a theme too; a POST from a visitor goes to log in. Put new preferences there as a `.setting` section.
- Controls and cards use `--radius` (4px); pictures stay square. Green (`--positive-*`) is only for an approving action, and it is defined in all three theme blocks. On My Posts the title's link stretches over the whole row (`.post-row-link`), and the row's buttons sit above it.
- **No decorative emoji.** Pictures only when real: a post without a cover gets a text-only card (a tinted tile with a larger headline), never a stand-in.
- **Title Case** for the menu, page titles (`h1`), section headings, empty-state titles and anything that names a page ("My Posts", "On This Page"). Small words (a, an, the, and, or, of, in, on, to, for, with, as, at, by) stay lowercase unless first. **Sentence case** for everything else: action buttons ("New post", "Save draft"), labels, hints, messages. The main button of a page is last on the right.
- Controls are the same height (`--control-height`) with bottoms aligned. Sizes in `rem`; the root font steps up at 1600 / 1920 / 2300px. The masthead and the page share `max-width: 110rem`, so their edges line up. The article stays at reading width (42rem), with side columns on wide screens.
- Public pages have the masthead on top; the Desk (`desk_base.html`) has a sidebar from 56rem up and a ☰ menu below.
- **Tags, Archive and About stay in the main menu.** Readers must never need Settings to find posts, and Settings only holds real settings.
- **Search is a magnifying glass, not a box in the menu:** a link to `/search` that `setUpSearch()` in `app.js` turns into a button opening the `#site-search` bar under the menu (Escape closes it). The `/search` page has its own form.
- The home page is the featured post, then Latest Posts (Older Posts from page 2), then Browse by Tag (`tags.with_counts(limit=)`, all the same size for neatness).
- **Every PR must keep the README's pictures up to date (the owner's standing rule).** Screenshots live in `docs/screenshots/` and every one is shown in the README. If a PR visibly changes a page, retake its pictures; if it adds a page or feature, add a picture to `docs/take_screenshots.py` and the README. `tests/test_readme.py` fails if they disagree. Take them on a practice database (`docs/make_practice_data.py`), never with real people or posts. In a PR description, link pictures with a full `raw.githubusercontent.com` address, because relative paths don't work there.
- Commit messages and PR bodies go through files (`git commit -F`, `gh pr create --body-file`): PowerShell 5.1 breaks quotes in arguments.
