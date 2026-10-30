"""Comments: writing, editing, reporting and the Desk's moderation queue."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError

from .. import comments, db, permissions
from ..auth import login_required
from ..dates import utcnow
from ..models import Comment, CommentReport, Post

bp = Blueprint("discussion", __name__)

QUEUE_TABS = {"waiting": "Waiting", "reported": "Reported", "recent": "Recent"}


@bp.app_context_processor
def template_helpers():
    # A function: only the Desk's sidebar calls it, so other pages pay no query.
    return {"waiting_comments": lambda: comments.waiting_count(db.session(), g.user)}


def comment_or_404(comment_id):
    """A comment this person can at least see, or 404."""
    comment = db.session().get(Comment, comment_id)
    now = utcnow()
    if comment is None or not permissions.can_view_post(g.user, comment.post, now):
        abort(404)
    if not permissions.can_see_comment(g.user, comment):
        abort(404)
    return comment


def back_to(comment):
    if comment.post.slug is None:
        return url_for("public.home")
    return url_for("public.show_post", slug=comment.post.slug, _anchor=f"comment-{comment.id}")


def back_to_queue_or_post(comment):
    target = request.form.get("back")
    return redirect(url_for("discussion.queue", tab=target) if target in QUEUE_TABS else back_to(comment))


@bp.post("/posts/<int:post_id>/comments")
@login_required
def add_comment(post_id):
    s = db.session()
    now = utcnow()
    post = s.get(Post, post_id)
    if post is None or not permissions.can_view_post(g.user, post, now):
        abort(404)
    if not permissions.can_comment(g.user, post, now):
        abort(403, "You can't comment on this post.")

    body = comments.clean_body(request.form.get("body"))
    problem = comments.body_problem(body)
    parent = None
    if request.form.get("parent_id"):
        parent = comments.valid_parent(s, post, request.form.get("parent_id", type=int))
        if parent is None:
            problem = "That comment can't be replied to any more."
    if problem is None and comments.over_rate_limit(s, g.user, now):
        problem = "You are commenting very quickly. Please wait a few minutes and try again."
    post_page = url_for("public.show_post", slug=post.slug)
    if problem:
        flash(problem)
        return redirect(post_page + "#comments")

    comment = comments.add(s, g.user, post, body, parent, now)
    s.commit()
    if comment.status == "pending":
        flash("Thanks! Your first comment will appear once it is approved.")
    return redirect(back_to(comment))


@bp.route("/comments/<int:comment_id>/edit", methods=["GET", "POST"])
@login_required
def edit_comment(comment_id):
    comment = comment_or_404(comment_id)
    now = utcnow()
    if not permissions.can_edit_comment(g.user, comment, now):
        abort(403, "Comments can only be edited by their writer, for 15 minutes.")
    error = None
    body = comment.body
    if request.method == "POST":
        body = comments.clean_body(request.form.get("body"))
        error = comments.body_problem(body)
        if not error:
            if body != comment.body:
                comment.body = body
                comment.edited_at = now
                db.session().commit()
            return redirect(back_to(comment))
    return render_template("comment_edit.html", comment=comment, body=body, error=error), 400 if error else 200


@bp.post("/comments/<int:comment_id>/delete")
@login_required
def delete_comment(comment_id):
    comment = comment_or_404(comment_id)
    if not permissions.can_delete_comment(g.user, comment):
        abort(403)
    comments.remove(comment, utcnow())
    db.session().commit()
    flash("The comment has been removed.")
    return back_to_queue_or_post(comment)


@bp.post("/comments/<int:comment_id>/report")
@login_required
def report_comment(comment_id):
    comment = comment_or_404(comment_id)
    if not permissions.can_report_comment(g.user, comment):
        abort(403)
    s = db.session()
    s.add(CommentReport(comment=comment, reporter=g.user,
                        reason=request.form.get("reason", "").strip()[:comments.REASON_MAX_LENGTH]))
    try:
        s.commit()
    except IntegrityError:  # the database's UNIQUE rule: this person already reported it
        s.rollback()
    flash("Thanks for your report. A moderator will look at it.")
    return redirect(back_to(comment))


# ---------- The Desk's queue ----------

def moderated_comment(comment_id):
    comment = db.session().get(Comment, comment_id)
    if comment is None:
        abort(404)
    if not permissions.can_moderate_comment(g.user, comment):
        # A pending comment on someone else's post isn't yours to know about.
        abort(403 if comment.status == "approved" else 404)
    return comment


@bp.get("/desk/comments")
@login_required
def queue():
    if not permissions.can_write(g.user):
        abort(403, "Only authors can use the Desk.")
    tab = request.args.get("tab", "waiting")
    if tab not in QUEUE_TABS:
        abort(404)
    s = db.session()
    finders = {"waiting": comments.waiting, "reported": comments.reported, "recent": comments.recent}
    return render_template("desk/comments.html", tabs=QUEUE_TABS, tab=tab, shown=finders[tab](s, g.user))


@bp.post("/desk/comments/<int:comment_id>/approve")
@login_required
def approve_comment(comment_id):
    comment = moderated_comment(comment_id)
    comments.approve(comment)
    db.session().commit()
    flash("The comment is approved.")
    return back_to_queue_or_post(comment)


@bp.post("/desk/comments/<int:comment_id>/reject")
@login_required
def reject_comment(comment_id):
    comment = moderated_comment(comment_id)
    comments.reject(comment, utcnow())
    db.session().commit()
    flash("The comment is rejected. Nobody can see it.")
    return back_to_queue_or_post(comment)


@bp.post("/desk/comments/<int:comment_id>/dismiss")
@login_required
def dismiss_reports(comment_id):
    comment = moderated_comment(comment_id)
    comments.resolve_reports(comment, utcnow())
    db.session().commit()
    flash("The reports are closed and the comment stays.")
    return back_to_queue_or_post(comment)
