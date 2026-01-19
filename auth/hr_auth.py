from functools import wraps
from flask import session, redirect

def hr_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if not session.get("hr_logged_in"):
            return redirect("/hr/login")
        return f(*args, **kwargs)
    return wrap
