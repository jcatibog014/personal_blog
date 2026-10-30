"""Make the made-up owner and people for the README screenshots.

The People page and the About page need an owner, and pictures must never show
real people, so screenshots are taken on a separate practice database:

    $env:DATABASE_URL = "sqlite:///C:/Temp/akda-screenshots.sqlite"
    .venv\\Scripts\\python docs\\make_practice_data.py

It refuses to touch anything but a SQLite file that holds only its own people,
so it can never add these logins to the live site. See take_screenshots.py.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from akda import auth, create_app, db  # noqa: E402
from akda.models import AUTHOR, OWNER, READER, User  # noqa: E402

PASSWORD = "practice password"  # also in take_screenshots.py
PEOPLE = [
    # username, name shown, role, blocked
    ("juan", "Juan Dela Cruz", OWNER, False),
    ("maria", "Maria Santos", AUTHOR, False),
    ("pedro", "Pedro Reyes", READER, False),
    ("rosa", "Rosa Lim", READER, True),
]
ABOUT = """\
Hello! I write about slow mornings, old books and small habits.

## Why This Blog

Writing helps me think. Reading what you think helps even more, so please leave a comment.
"""


def main():
    if not os.environ.get("DATABASE_URL", "").startswith("sqlite:"):
        sys.exit("Set DATABASE_URL to a practice SQLite file first. This never runs on a real database.")
    app = create_app()
    with app.app_context():
        db.upgrade_db()
        s = db.session()
        usernames = {username for username, *_ in PEOPLE}
        others = s.scalars(select(User.username).where(User.is_demo.is_(False), User.username.not_in(usernames))).all()
        if others:
            sys.exit(f"This database has other people in it ({len(others)}). Use an empty practice file.")
        for username, name, role, blocked in PEOPLE:
            if auth.find_user(s, username) is None:
                user = auth.create_user(s, username, PASSWORD, role=role, display_name=name)
                user.is_blocked = blocked
                if role == OWNER:
                    user.bio = ABOUT
        s.commit()
    print("The practice people are ready.")


if __name__ == "__main__":
    main()
