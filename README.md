# Akda

**Akda** means "literary work" in Filipino. It is a personal blog. Authors write and publish posts. Readers leave comments. The owner takes care of the site.

I made this project to practice three skills: **authentication** (who are you?), **authorization** (what can you do?) and **relational data** (how do the tables connect?).

![The home page](docs/screenshots/home.png)

## Who Can Do What

There are three kinds of account, and visitors need no account.

| | Visitor | Reader | Author | Owner |
|---|---|---|---|---|
| Read posts and comments | Yes | Yes | Yes | Yes |
| Write a comment, reply, report | No | Yes | Yes | Yes |
| Change your own comment (for 15 minutes) | No | Yes | Yes | Yes |
| Write and publish posts | No | No | Yes | Yes |
| Approve comments on your own posts | No | No | Yes | Yes |
| Approve any comment | No | No | No | Yes |
| Take down any published post | No | No | No | Yes |
| Read or change another person's draft | No | No | No | No |
| Invite authors, block people | No | No | No | Yes |

How you get each account:

- **Reader:** press "Sign up".
- **Author:** the owner sends you a special link. It works one time and stops after 7 days.
- **Owner:** this is made on the command line only.
- **Try Demo:** press the button on the login page. You become a sample author. Nobody else sees what you write, and it resets every hour.

## What It Can Do

**For readers**
- Read posts on a phone or a very wide screen.
- Choose light or dark mode in Settings. You don't need an account for this.
- See the latest posts on the home page, and browse by tag at the bottom.
- Find posts by month or with search. Each post shows related posts.
- Follow the blog with an RSS feed.
- Write comments and one level of replies. A new reader's first comment waits for approval.

**For authors**
- Write in Markdown and see the result at the same time.
- Drafts save by themselves while you type.
- Go back to an older version of a post.
- Choose a date and time, and the post goes live by itself.
- Add a cover picture and pictures inside the text.

**For the owner**
- Approve, reject or remove comments, and read reports from readers.
- Invite authors and block people.
- Write the About page.

**For safety**
- Passwords are saved only as hashes.
- After 5 wrong passwords, the account waits 15 minutes.
- HTML in a post is cleaned, so a post cannot run a script.
- Every form has a secret token (CSRF protection).
- Drafts and scheduled posts are hidden in every list, and a test checks this.

## Pictures

**Reading**

| | |
|---|---|
| ![An article](docs/screenshots/article.png) An article | ![Comments under an article](docs/screenshots/comments.png) Comments |
| ![The bottom of the home page, with tags to browse](docs/screenshots/browse-by-tag.png) Browse by tag | ![The search bar, open under the menu](docs/screenshots/search-bar.png) The search bar |
| ![Search results](docs/screenshots/search.png) Search results | ![All tags](docs/screenshots/tags.png) Tags |
| ![The archive](docs/screenshots/archive.png) The archive | ![The About page](docs/screenshots/about.png) About |

**Writing**

| | |
|---|---|
| ![The editor](docs/screenshots/editor.png) The editor | ![My posts](docs/screenshots/my-posts.png) My posts |
| ![Older versions of a post](docs/screenshots/versions.png) Versions | ![Comments that wait for approval](docs/screenshots/moderation.png) Approving comments |

**The owner and accounts**

| | |
|---|---|
| ![The People page](docs/screenshots/people.png) People and invites | ![Reported comments in dark mode](docs/screenshots/reports.png) Reports, in dark mode |
| ![The login page](docs/screenshots/login.png) Log in | ![The sign-up page](docs/screenshots/signup.png) Sign up |

**Settings, dark mode and phones**

| | |
|---|---|
| ![The Settings page](docs/screenshots/settings.png) Settings | ![The home page in dark mode](docs/screenshots/home-dark.png) Dark mode |
| ![The home page on a phone](docs/screenshots/phone.png) On a phone | ![The menu on a phone](docs/screenshots/phone-menu.png) The menu on a phone |

The sun, road and book pictures are demo covers. A program draws them (`docs/make_covers.py`). The people in these pictures are made up.

## Tools

| Tool | What it is | What it does here |
|---|---|---|
| Python 3.13 | Language | The whole server |
| Flask | Web framework | Pages and forms |
| SQLAlchemy | Database library | The tables, as Python classes |
| Alembic | Migration tool | Changes the tables and keeps the data |
| SQLite | Database | Saves data on my computer and in tests |
| PostgreSQL (Neon) | Database | Saves data on the live site |
| markdown-it-py | Library | Changes Markdown to HTML |
| nh3 | Library | Cleans the HTML, so it is safe |
| Pillow | Library | Makes pictures small |
| pytest | Test tool | Checks that everything works |
| Playwright | Browser tool | Takes the pictures for this page |
| Render | Hosting platform | Runs the live site |
| HTML, CSS, JavaScript | Languages | The pages. They also work without JavaScript. |

## Run It on Your Computer

You need Python 3.13. Use these commands in PowerShell, in this folder.

1. Make the virtual environment and install the tools:

   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```

2. Make the tables and your owner account (it asks for a password):

   ```
   .venv\Scripts\flask --app akda upgrade-db
   .venv\Scripts\flask --app akda create-user yourname --role owner
   ```

3. Start the site, then open http://127.0.0.1:5005

   ```
   .venv\Scripts\flask --app akda run --debug --port 5005
   ```

Run the tests with:

```
.venv\Scripts\python -m pytest
```

## Put It Online

The site uses Render (it runs the program) and Neon (it keeps the data). Both have a free plan.

1. **Neon:** make a project in the Singapore region. Copy the connection string. It starts with `postgresql://`.
2. **Render:** choose **New**, then **Blueprint**, then pick this repository. Render reads `render.yaml`. When it asks for `DATABASE_URL`, paste the Neon string.
3. **Your owner account:** run these on your computer. Use your own Neon string. Keep this string secret, and never paste it into a chat or a file.

   ```
   $env:DATABASE_URL = "postgresql://..."
   .venv\Scripts\flask --app akda create-user yourname --role owner
   Remove-Item Env:DATABASE_URL
   ```

On the free plan, the site sleeps after 15 quiet minutes. The next visit wakes it up, and this takes about 30 to 50 seconds.

## Forgot Your Password?

The site does not send email. The owner can make a new password for any account with this command:

```
.venv\Scripts\flask --app akda set-password thename
```

To do this on the live site, set `DATABASE_URL` first, as in step 3 above.
