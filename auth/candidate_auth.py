from functools import wraps
from flask import session, redirect

def candidate_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("candidate_id"):
            return redirect("/candidate/login")
        return f(*args, **kwargs)
    return wrap
