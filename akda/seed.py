"""The demo's sample posts and comments, made fresh by auth.demo_user().

The demo is a sandbox: every row here belongs to an is_demo user, and only
demo visitors see them (posts.visible_filter). Sample readers exist so that
moderation can be tried. Nobody can log in as them: their passwords are random
and the login form skips is_demo users.
"""
import secrets
from datetime import timedelta
from pathlib import Path

from PIL import Image as PillowImage
from sqlalchemy import select

from . import auth, posts, tags
from .models import APPROVED, PENDING, READER, Comment, CommentReport, Image, Post, User

COVERS = Path(__file__).parent / "seed_covers"

SAMPLE_READERS = {"demo-reader-1": "Ana Reyes", "demo-reader-2": "Ben Santos"}

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

NEXT_MONTH = """\
This post goes live by itself next week, with no one pressing anything. Until then, only you can see it.
"""


def _sample_reader(s, username, display_name):
    user = s.scalar(select(User).where(User.username == username))
    if user is None:
        user = auth.create_user(s, username, secrets.token_urlsafe(32), role=READER,
                                display_name=display_name, is_demo=True)
    return user


def _cover(s, owner, name):
    path = COVERS / f"{name}.webp"
    with PillowImage.open(path) as picture:
        width, height = picture.size
    data = path.read_bytes()
    image = Image(owner_id=owner.id, data=data, mime="image/webp", width=width, height=height, size=len(data))
    s.add(image)
    return image


def _post(s, author, moment, title, body, summary="", tag_names=(), cover=None, published=None):
    """published: how long ago (a negative timedelta means in the future); None makes a draft."""
    post = Post(author=author)
    s.add(post)
    post.tags = tags.resolve(s, list(tag_names))
    post.cover = _cover(s, author, cover) if cover else None
    posts.apply_content(post, {"title": title, "summary": summary, "body_md": body}, moment)
    if published is not None:
        posts.publish(s, post, moment - published)
    posts.snapshot(s, post, author, moment)
    s.flush()
    return post


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
    ana, ben = (_sample_reader(s, username, name) for username, name in SAMPLE_READERS.items())

    by_hand = _post(s, demo, moment, "Why I Still Write by Hand", WRITING_BY_HAND,
                    summary="A cheap notebook has no app, no sync and no search. It is the most useful thing I own.",
                    tag_names=["writing", "habits"], cover="writing", published=timedelta(hours=5))
    morning = _post(s, demo, moment, "A Slow Morning on the Ridge", SLOW_MORNING,
                    tag_names=["travel", "habits"], cover="hills", published=timedelta(days=4))
    jeepney = _post(s, demo, moment, "What a Jeepney Route Taught Me", JEEPNEY_ROUTE,
                    tag_names=["life", "habits"], cover="road", published=timedelta(days=12))
    _post(s, demo, moment, "Notes on Reading Slowly", READING_SLOWLY,
          tag_names=["books", "writing"], cover="books", published=timedelta(days=30))
    _post(s, demo, moment, "Building a Small Web App", FLASK_NOTES, tag_names=["code"])
    _post(s, demo, moment, "A Post From the Future", NEXT_MONTH, tag_names=["writing"], published=-timedelta(days=7))

    first = Comment(post=by_hand, user=ana, status=APPROVED, created_at=moment - timedelta(hours=3),
                    body="I do this too. The Sunday typing-up is the part I never manage.")
    s.add(first)
    s.flush()
    s.add(Comment(post=by_hand, user=demo, parent_id=first.id, status=APPROVED,
                  created_at=moment - timedelta(hours=2), body="Try once a month. It still works."))
    s.add(Comment(post=by_hand, user=ben, status=PENDING, created_at=moment - timedelta(hours=1),
                  body="First time here. Which notebook do you use?"))
    rude = Comment(post=jeepney, user=ben, status=APPROVED, created_at=moment - timedelta(days=2),
                   body="Buy my course and you will never need to wait for a jeepney again!")
    s.add(rude)
    s.add(Comment(post=morning, user=ana, status=APPROVED, created_at=moment - timedelta(days=3),
                  body="That lake is even better in the rainy season."))
    s.flush()
    s.add(CommentReport(comment=rude, reporter=ana, reason="This looks like an advert.", created_at=moment - timedelta(days=1)))
