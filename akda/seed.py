"""The demo's sample posts and comments, made fresh by auth.demo_user().

The demo is a sandbox: every row here belongs to an is_demo user, and only
demo visitors see them (posts.visible_filter). Sample readers exist so that
moderation can be tried. Nobody can log in as them: their passwords are random
and the login form skips is_demo users.

Every page the demo can open should have something to look at, including each
feature's less common cases: a post with no cover, a picture inside a post, older
versions, replies, an edited comment and a removed one. tests/test_demo.py checks this.
"""
import secrets
from datetime import timedelta
from pathlib import Path

from PIL import Image as PillowImage
from sqlalchemy import select

from . import auth, images, posts, tags
from .models import APPROVED, PENDING, READER, Comment, CommentReport, Image, Post, PostVersion, User

COVERS = Path(__file__).parent / "seed_covers"

SAMPLE_READERS = {"demo-reader-1": "Ana Reyes", "demo-reader-2": "Ben Santos", "demo-reader-3": "Carla Lim"}

ABOUT = """\
Hello! I'm a sample writer, here so you can see how Akda looks with something on every page.

## What I Write About

Slow mornings, old books, long commutes and small habits that last.

## How This Blog Works

Anyone can read. Readers who sign up can comment, and a reader's first comment waits for approval. On the real site, the owner writes this page in Settings.
"""

WRITING_BY_HAND = """\
I keep a cheap notebook in my bag. It has no app, no sync and no search, and it is the most useful thing I own.

## The Page Doesn't Interrupt

A screen is always asking for something. A page only waits. When I write by hand, the next thought has time to arrive, and I don't reach for a tab to check one small fact.

## Slow Is the Point

My hand can't keep up with my head, so I have to choose. The sentence I keep is usually better than the three I would have typed.

> Writing is thinking with a witness.

## What I Do With It

Every Sunday I type up the pages worth keeping. Most aren't, and that is fine. The notebook did its job the moment I wrote them down.
"""

SLOW_MORNING = """\
We left before sunrise, with coffee in a flask and no plan beyond the first bend in the road.

## The Ridge

The fog lifted around seven. For about ten minutes the whole lake was there, then the clouds closed over it again. Nobody took a good picture, and I think that is why I remember it so well.

{picture}

## Lunch

We ate *bulalo* at a small place with plastic chairs and a very serious cat. The soup took an hour. We were in no hurry.

## Going Home

On the drive back, nobody put on any music. It was the best part of the day.
"""

JEEPNEY_ROUTE = """\
For two years I took the same jeepney to work. It taught me more about patience than any book did.

## Nothing Leaves Until It Is Full

You can't rush a driver who is waiting for one more passenger. You can only sit, pass the coins along and watch the street.

## Everyone Helps

Your fare travels hand to hand through strangers, and your change comes back the same way. In two years I never once lost a peso.

## What I Took From It

- Most waiting isn't wasted.
- Small trust adds up.
- You always get there, just not always when you planned.
"""

READING_SLOWLY = """\
Last year I read twelve books instead of fifty, and I remember more of them.

## One Chapter, Then Stop

I now stop after a chapter and write one line about it. That one line is what stays with me.

## Reading Twice

The second reading is where a good book opens up. You know how it ends, so you can watch how it was built.

## The Pile

There will always be more books than time. I have made my peace with the pile.
"""

FLASK_NOTES = """\
These are my notes from building a small web app. They aren't finished yet.

## What Broke First

Almost everything, in a useful way.
"""

NEXT_WEEK = """\
This post goes live by itself next week, with no one pressing anything.

## Until Then

Only you can see it. Readers won't find it in any list, in search or in the RSS feed.
"""

YOUNGER_SELF = """\
You are going to be fine. Please stop rewriting the first paragraph.

## What Matters

Finish things. Most of what you are worried about won't be remembered by anyone, including you.
"""

NEXT_IDEAS = """\
A list of things to write about, so I never start from an empty page.

## Maybe Soon

- The market near my old school
- Why I stopped checking the weather

## Maybe Never

- A novel
"""

HOW_I_FORMAT = """\
This post shows what a post can hold. Open it in the editor to see the Markdown behind each part.

## Words

Text can be **bold**, *italic* or ~~crossed out~~, and it can hold [a link](https://www.example.com).

> A quote stands out from the rest of the page.

## Lists

1. Write the first draft
2. Leave it alone for a day
3. Cut the first paragraph

- Notebook
- Pencil
- Coffee

## Tables

| Habit | Minutes |
|---|---|
| Reading | 30 |
| Writing | 20 |

## Code

```
def write():
    return "one small page"
```
"""

MY_LOLA = """\
My grandmother never owned a watch, and she was never late.

## Start Early

She began cooking lunch at nine. Nothing she made was ever rushed, and nothing was ever cold.

## Keep Good Knives

She had two knives for fifty years and sharpened them every Sunday.

## Feed People

If you came to her house, you ate. It didn't matter why you came.
"""

KEEPING_LISTS = """\
I keep one list. It has taken me years to get down to one.

## Why Only One

Two lists means deciding which one to check, and then checking neither.

## What Goes On It

Only the next step. "Write the essay" stays on a list for months, but "Open the notes file" gets done today.
"""


def _sample_reader(s, username, display_name):
    user = s.scalar(select(User).where(User.username == username))
    if user is None:
        user = auth.create_user(s, username, secrets.token_urlsafe(32), role=READER,
                                display_name=display_name, is_demo=True)
    return user


def _picture(s, owner, name):
    path = COVERS / f"{name}.webp"
    with PillowImage.open(path) as picture:
        width, height = picture.size
    data = path.read_bytes()
    image = Image(owner_id=owner.id, data=data, thumb=images.make_thumb(data), mime="image/webp",
                  width=width, height=height, size=len(data))
    s.add(image)
    return image


def _older_versions(s, post, author, title, summary, body, newest_at):
    """Version history as if the post grew one section at a time, so every post has
    something to look at and restore on its Versions page."""
    sections = body.split("\n## ")
    for number in range(1, len(sections)):
        s.add(PostVersion(post_id=post.id, saved_by_id=author.id, title=title, summary=summary,
                          body_md="\n## ".join(sections[:number]),
                          saved_at=newest_at - timedelta(hours=len(sections) - number)))
    s.flush()


def _post(s, author, moment, title, body, summary="", tag_names=(), cover=None, published=None, picture=None):
    """published: how long ago (a negative timedelta means in the future); None makes a draft.
    picture: (cover file, alt text) to put where the body says {picture}."""
    post = Post(author=author)
    s.add(post)
    post.tags = tags.resolve(s, list(tag_names))
    post.cover = _picture(s, author, cover) if cover else None
    if picture:
        image = _picture(s, author, picture[0])
        s.flush()
        body = body.replace("{picture}", f"![{picture[1]}](/images/{image.id})")
    posts.apply_content(post, {"title": title, "summary": summary, "body_md": body}, moment)
    if published is not None:
        posts.publish(s, post, moment - published)
    s.flush()
    newest_at = moment - max(published or timedelta(0), timedelta(0))
    _older_versions(s, post, author, title, summary, body, newest_at)
    posts.snapshot(s, post, author, newest_at)
    s.flush()
    return post


def _comment(s, post, user, moment, ago, body, status=APPROVED, parent=None, edited=False, removed=False):
    created_at = moment - ago
    comment = Comment(post=post, user=user, body=body, status=status, created_at=created_at,
                      parent_id=parent.id if parent else None,
                      edited_at=created_at + timedelta(minutes=5) if edited else None,
                      deleted_at=created_at + timedelta(hours=1) if removed else None)
    s.add(comment)
    s.flush()
    return comment


def _report(s, comment, reporter, reason, moment):
    s.add(CommentReport(comment=comment, reporter=reporter, reason=reason, created_at=moment - timedelta(days=1)))


def clear(s, demo):
    """Delete everything the demo made. Comments, versions and links go with their posts."""
    for post in s.scalars(select(Post).where(Post.author_id == demo.id)):
        s.delete(post)
    s.flush()
    for image in s.scalars(select(Image).where(Image.owner_id == demo.id)):
        s.delete(image)
    s.flush()


def reset_demo(s, demo, moment):
    """Make the demo's sample content fresh. The caller commits."""
    clear(s, demo)
    demo.bio = ABOUT
    ana, ben, carla = (_sample_reader(s, username, name) for username, name in SAMPLE_READERS.items())
    hours, days = (lambda n: timedelta(hours=n)), (lambda n: timedelta(days=n))

    by_hand = _post(s, demo, moment, "Why I Still Write by Hand", WRITING_BY_HAND,
                    summary="A cheap notebook has no app, no sync and no search. It is the most useful thing I own.",
                    tag_names=["writing", "habits"], cover="writing", published=hours(5))
    morning = _post(s, demo, moment, "A Slow Morning on the Ridge", SLOW_MORNING,
                    tag_names=["travel", "habits"], cover="hills", published=days(4),
                    picture=("hills", "The ridge just after the fog lifted"))
    jeepney = _post(s, demo, moment, "What a Jeepney Route Taught Me", JEEPNEY_ROUTE,
                    tag_names=["life", "habits"], cover="road", published=days(12))
    reading = _post(s, demo, moment, "Notes on Reading Slowly", READING_SLOWLY,
                    tag_names=["books", "writing"], cover="books", published=days(30))
    # The next three have no cover, to show the text-only card and the Archive's empty tile.
    formatting = _post(s, demo, moment, "How I Format a Post", HOW_I_FORMAT,
                       summary="Headings, lists, quotes, tables, code and links, all in one post.",
                       tag_names=["writing", "code"], published=days(45))
    lola = _post(s, demo, moment, "Three Things My Lola Taught Me", MY_LOLA,
                 tag_names=["life", "food"], published=days(70))
    lists = _post(s, demo, moment, "A Note on Keeping One List", KEEPING_LISTS,
                  tag_names=["habits", "life"], published=days(100))

    _post(s, demo, moment, "Building a Small Web App", FLASK_NOTES,
          summary="Notes from my first web app, and everything that broke.", tag_names=["code"])
    _post(s, demo, moment, "Ideas for Next Month", NEXT_IDEAS, tag_names=["writing"], cover="books")
    _post(s, demo, moment, "A Post From the Future", NEXT_WEEK, tag_names=["writing"], published=-days(7))
    _post(s, demo, moment, "A Letter to My Younger Self", YOUNGER_SELF, tag_names=["life"], published=-days(14))

    first = _comment(s, by_hand, ana, moment, hours(3), "I do this too. The Sunday typing-up is the part I never manage.")
    _comment(s, by_hand, demo, moment, hours(2), "Try once a month. It still works.", parent=first)
    _comment(s, by_hand, carla, moment, hours(4), "I switched back to paper last year. Best decision I made.", edited=True)
    _comment(s, by_hand, ben, moment, hours(1), "First time here. Which notebook do you use?", status=PENDING)

    _comment(s, morning, ana, moment, days(3), "That lake is even better in the rainy season.")
    # Written minutes ago, so its Edit link shows: comments can be edited for 15 minutes.
    _comment(s, morning, demo, moment, timedelta(minutes=12), "Thanks, Ana. I'll go back in August.")

    advert = _comment(s, jeepney, ben, moment, days(2), "Buy my course and you will never need to wait for a jeepney again!")
    _report(s, advert, ana, "This looks like an advert.", moment)
    _comment(s, jeepney, carla, moment, days(8), "The part about passing the coins made me smile.")
    removed = _comment(s, jeepney, ben, moment, days(9), "This comment broke the rules, so it was removed.", removed=True)
    _comment(s, jeepney, ana, moment, days(7), "Glad that one is gone. Lovely post, though.", parent=removed)

    _comment(s, reading, carla, moment, days(20), "Twelve is still a lot. One line per chapter is a good idea.")
    _comment(s, formatting, ana, moment, days(40), "Saving this one for later.")
    _comment(s, lola, carla, moment, days(60), "Two knives for fifty years! Mine would have lost them both.")
    off_topic = _comment(s, lola, ben, moment, days(5), "Does anyone know a good phone shop near here?")
    _report(s, off_topic, carla, "This isn't about the post.", moment)
    _comment(s, lists, ana, moment, days(90), "Open the notes file. I am stealing that.")
    _comment(s, lists, carla, moment, hours(6), "I have four lists and I can't find any of them.", status=PENDING)
    s.flush()
