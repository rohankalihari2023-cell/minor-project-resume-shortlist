def calculate_skill_score(resume_text, skills):
    score = 0
    resume_text = resume_text.lower()
    for skill, weight in skills:
        if skill.lower() in resume_text:
            score += float(weight)
    return round(score, 2)
