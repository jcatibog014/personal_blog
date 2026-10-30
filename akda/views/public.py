"""The pages everyone can see."""
from flask import Blueprint, render_template

bp = Blueprint("public", __name__)


@bp.get("/")
def home():
    return render_template("home.html")


@bp.get("/healthz")
def healthz():
    return "ok"
