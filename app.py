import os
import sqlite3
from flask import Flask, render_template, request, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash
from PyPDF2 import PdfReader

from config import DB_NAME, UPLOAD_FOLDER, SECRET_KEY
from auth.hr_auth import hr_required
from auth.candidate_auth import candidate_required
from selection.skill_ranker import calculate_skill_score

app = Flask(__name__)
app.secret_key = SECRET_KEY
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ================= DATABASE INIT =================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS hr_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password TEXT,
            resume_path TEXT,
            skill_score REAL,
            rank INTEGER,
            status TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT,
            weight REAL
        )
    """)

    cur.execute("SELECT * FROM hr_users WHERE username='hr'")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO hr_users (username, password) VALUES (?, ?)",
            ("hr", generate_password_hash("hr123"))
        )

    conn.commit()
    conn.close()

init_db()

# ================= HELPERS =================
def extract_text_from_pdf(path):
    reader = PdfReader(path)
    return "".join(page.extract_text() or "" for page in reader.pages)

@app.route("/")
def home():
    return redirect("/candidate/login")

# ================= HR =================
@app.route("/hr/login", methods=["GET","POST"])
def hr_login():
    if request.method == "POST":
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT password FROM hr_users WHERE username=?", (request.form["username"],))
        row = cur.fetchone()
        conn.close()

        if row and check_password_hash(row[0], request.form["password"]):
            session["hr_logged_in"] = True
            return redirect("/hr/dashboard")

        return "Invalid HR credentials"

    return render_template("hr/hr_login.html")

@app.route("/hr/dashboard")
@hr_required
def hr_dashboard():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM candidates")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM candidates WHERE resume_path IS NOT NULL")
    uploaded = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM candidates WHERE status='Selected'")
    selected = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM candidates WHERE status='Not Selected'")
    rejected = cur.fetchone()[0]

    conn.close()

    return render_template(
        "hr/hr_dashboard.html",
        total=total,
        uploaded=uploaded,
        selected=selected,
        rejected=rejected
    )

# ================= SKILLS =================
@app.route("/hr/skills", methods=["GET","POST"])
@hr_required
def hr_skills():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action")
        skill_id = request.form.get("skill_id")

        if action == "delete" and skill_id:
            cur.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        else:
            if skill_id:
                cur.execute(
                    "UPDATE skills SET skill_name=?, weight=? WHERE id=?",
                    (request.form["skill"], request.form["weight"], skill_id)
                )
            else:
                cur.execute(
                    "INSERT INTO skills (skill_name, weight) VALUES (?,?)",
                    (request.form["skill"], request.form["weight"])
                )
        conn.commit()

    cur.execute("SELECT id, skill_name, weight FROM skills")
    skills = cur.fetchall()
    conn.close()

    return render_template("hr/hr_skills.html", skills=skills)

# ================= RUN SELECTION =================
@app.route("/hr/run_selection", methods=["POST"])
@hr_required
def run_selection():
    top_n = int(request.form["top_n"])

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("SELECT skill_name, weight FROM skills")
    skills = cur.fetchall()

    cur.execute("SELECT id, resume_path FROM candidates WHERE resume_path IS NOT NULL")
    candidates = cur.fetchall()

    ranking = []
    for cid, path in candidates:
        score = calculate_skill_score(extract_text_from_pdf(path), skills)
        ranking.append((cid, score))

    ranking.sort(key=lambda x: x[1], reverse=True)

    for rank, (cid, score) in enumerate(ranking, start=1):
        status = "Selected" if rank <= top_n else "Not Selected"
        cur.execute("""
            UPDATE candidates
            SET skill_score=?, rank=?, status=?
            WHERE id=?
        """, (score, rank, status, cid))

    conn.commit()
    conn.close()
    return redirect("/hr/candidates")

# ================= CANDIDATES =================
@app.route("/hr/candidates")
@hr_required
def hr_candidates():
    search = request.args.get("search", "")
    status = request.args.get("status", "")

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    query = """
        SELECT id, name, email, resume_path, skill_score, rank, status
        FROM candidates
        WHERE (name LIKE ? OR email LIKE ?)
    """
    params = [f"%{search}%", f"%{search}%"]

    if status:
        query += " AND status=?"
        params.append(status)

    query += " ORDER BY rank"
    cur.execute(query, params)

    candidates = cur.fetchall()
    conn.close()

    return render_template(
        "hr/hr_candidates.html",
        candidates=candidates,
        search=search,
        status=status
    )

# ================= DELETE RESUME (NEW) =================
@app.route("/hr/delete_resume/<int:candidate_id>", methods=["POST"])
@hr_required
def delete_resume(candidate_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("SELECT resume_path FROM candidates WHERE id=?", (candidate_id,))
    row = cur.fetchone()

    if row and row[0]:
        if os.path.exists(row[0]):
            os.remove(row[0])

        cur.execute("""
            UPDATE candidates
            SET resume_path=NULL,
                skill_score=NULL,
                rank=NULL,
                status='Under Review'
            WHERE id=?
        """, (candidate_id,))

    conn.commit()
    conn.close()
    return redirect("/hr/candidates")

@app.route("/hr/logout")
def hr_logout():
    session.pop("hr_logged_in", None)
    return redirect("/hr/login")

# ================= CANDIDATE =================
@app.route("/candidate/register", methods=["GET","POST"])
def candidate_register():
    if request.method == "POST":
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO candidates (name,email,password,status)
            VALUES (?,?,?,?)
        """, (
            request.form["name"],
            request.form["email"],
            generate_password_hash(request.form["password"]),
            "Under Review"
        ))
        conn.commit()
        conn.close()
        return redirect("/candidate/login")

    return render_template("candidate/candidate_register.html")

@app.route("/candidate/login", methods=["GET","POST"])
def candidate_login():
    if request.method == "POST":
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT id,password FROM candidates WHERE email=?", (request.form["email"],))
        row = cur.fetchone()
        conn.close()

        if row and check_password_hash(row[1], request.form["password"]):
            session["candidate_id"] = row[0]
            return redirect("/candidate/dashboard")

        return "Invalid credentials"

    return render_template("candidate/candidate_login.html")

@app.route("/candidate/dashboard", methods=["GET","POST"])
@candidate_required
def candidate_dashboard():
    if request.method == "POST":
        resume = request.files["resume"]
        path = os.path.join(UPLOAD_FOLDER, resume.filename)
        resume.save(path)

        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE candidates SET resume_path=? WHERE id=?",
                    (path, session["candidate_id"]))
        conn.commit()
        conn.close()

    return render_template("candidate/candidate_dashboard.html")

@app.route("/candidate/result")
@candidate_required
def candidate_result():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT skill_score, rank, status FROM candidates WHERE id=?",
                (session["candidate_id"],))
    result = cur.fetchone()
    conn.close()
    return render_template("candidate/candidate_result.html", result=result)

@app.route("/candidate/logout")
def candidate_logout():
    session.pop("candidate_id", None)
    return redirect("/candidate/login")

if __name__ == "__main__":
    app.run(debug=True)
