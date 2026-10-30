"""The owner's People page (invites and blocking) and the invite link itself."""
import math

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import auth, db, invites, permissions
from ..auth import login_required
from ..dates import utcnow
from ..models import AUTHOR, Comment, Invite, Post, User

bp = Blueprint("people", __name__)

PAGE_SIZE = 50


def owner_only():
    if not permissions.can_manage_people(g.user):
        abort(403, "Only the owner can manage people.")


def people_with_counts(s, page):
    """Each real user with how many posts and comments they have. Correlated
    subqueries, so one query gets it all, however many people there are."""
    post_count = select(func.count(Post.id)).where(Post.author_id == User.id).scalar_subquery()
    comment_count = select(func.count(Comment.id)).where(Comment.user_id == User.id).scalar_subquery()
    return s.execute(
        select(User, post_count, comment_count).where(User.is_demo.is_(False))
        .order_by(User.role, User.username).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()


@bp.get("/desk/people")
@login_required
def index():
    owner_only()
    s = db.session()
    page = request.args.get("page", 1, type=int)
    total = s.scalar(select(func.count()).select_from(User).where(User.is_demo.is_(False)))
    pages = max(1, math.ceil(total / PAGE_SIZE))
    if not 1 <= page <= pages:
        abort(404)
    return render_template("desk/people.html", people=people_with_counts(s, page), page=page, pages=pages,
                           invites=invites.waiting(s, utcnow()), new_link=session.pop("new_invite_link", None))


@bp.post("/desk/people/invites")
@login_required
def create_invite():
    owner_only()
    s = db.session()
    token = invites.create(s, g.user, utcnow())
    s.commit()
    # Shown once, on the next page, in the owner's own session. Redirecting means
    # a page refresh can't make a second invite.
    session["new_invite_link"] = url_for("people.accept_invite", token=token, _external=True)
    return redirect(url_for("people.index"))


@bp.post("/desk/people/invites/<int:invite_id>/cancel")
@login_required
def cancel_invite(invite_id):
    owner_only()
    s = db.session()
    invite = s.get(Invite, invite_id)
    if invite is None or invite.used_at is not None:
        abort(404)
    s.delete(invite)
    s.commit()
    flash("The invite link no longer works.")
    return redirect(url_for("people.index"))


def person_to_change(user_id):
    owner_only()
    person = db.session().get(User, user_id)
    if person is None or person.is_demo:
        abort(404)
    if not permissions.can_block_user(g.user, person):
        abort(403, "The owner can't be blocked.")
    return person


@bp.post("/desk/people/<int:user_id>/block")
@login_required
def block(user_id):
    person = person_to_change(user_id)
    person.is_blocked = True
    person.session_version += 1
    db.session().commit()
    flash(f"{person.display_name} is blocked and has been logged out.")
    return redirect(url_for("people.index"))


@bp.post("/desk/people/<int:user_id>/unblock")
@login_required
def unblock(user_id):
    person = person_to_change(user_id)
    person.is_blocked = False
    db.session().commit()
    flash(f"{person.display_name} is no longer blocked.")
    return redirect(url_for("people.index"))


def bad_invite():
    return render_template("error.html", code=404, message="This invite link doesn't work any more."), 404


@bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token):
    s = db.session()
    now = utcnow()
    invite = invites.find_usable(s, token, now)
    if invite is None:
        return bad_invite()
    if g.user is not None:
        return render_template("invite.html", token=token, errors={}, username="")

    errors = {}
    username = ""
    if request.method == "POST":
        username = auth.clean_username(request.form.get("username", ""))[:auth.USERNAME_MAX_LENGTH + 1]
        password = request.form.get("password", "")
        problem = auth.username_problem(username)
        if problem:
            errors["username"] = problem
        problem = auth.password_problem(password, request.form.get("confirm_password", ""))
        if problem:
            errors["password"] = problem
        if not errors:
            try:
                user = auth.create_user(s, username, password, role=AUTHOR)
            except IntegrityError:
                s.rollback()
                errors["username"] = "That username is already taken."
            else:
                if not invites.claim(s, invite, user, now):
                    s.rollback()  # someone else just used it: no account is made either
                    return bad_invite()
                s.commit()
                auth.log_in(user)
                flash("Welcome to Akda! You can start writing now.")
                return redirect(url_for("desk.my_posts"))
    return render_template("invite.html", token=token, errors=errors, username=username), 400 if errors else 200
