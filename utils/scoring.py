"""📊 BALL HISOBLASH"""
import re, logging
log = logging.getLogger(__name__)
LETTERS = ["A","B","C","D","E","F","G","H","I","J"]

def calculate_score(questions, answers):
    max_s = sum(q.get("points",1) for q in questions)
    earned = correct = wrong = skipped = 0
    details = []
    for i, q in enumerate(questions):
        u   = answers.get(str(i))
        pts = float(q.get("points",1))
        is_c = ep = 0
        if u is None or str(u).strip() == "":
            skipped += 1
        else:
            is_c, ep = _check(q, u, pts)
            correct += is_c; wrong += not is_c; earned += ep
        details.append({"question_index":i,"is_correct":bool(is_c),
            "user_answer":u,"correct_answer":q.get("correct"),
            "explanation":q.get("explanation",""),"earned_points":ep,"max_points":pts})
    pct = round(earned/max_s*100,2) if max_s else 0.0
    return {"score":round(earned,2),"max_score":max_s,"percentage":pct,
            "correct_count":correct,"wrong_count":wrong,"skipped_count":skipped,
            "total_questions":len(questions),"grade":_grade(pct),"emoji":_emoji(pct),
            "detailed_results":details}

def _check(q, ans, pts):
    t = q.get("type","multiple_choice"); c = q.get("correct")
    if c is None: return False, 0.0
    try:
        if t == "multiple_choice":
            am = re.match(r"^([A-Za-z])",str(ans).strip())
            cm = re.match(r"^([A-Za-z])",str(c).strip())
            ok = (am.group(1).lower()==cm.group(1).lower()) if am and cm else str(ans).strip().lower()==str(c).strip().lower()
            return ok, pts if ok else 0.0
        if t == "true_false":
            ok = str(ans).strip().lower()==str(c).strip().lower(); return ok,pts if ok else 0.0
        if t == "multi_select":
            def ls(lst):
                s=set()
                for x in lst:
                    m=re.match(r"^([A-Za-z])",str(x).strip())
                    if m: s.add(m.group(1).lower())
                return s
            if isinstance(ans,list) and isinstance(c,list):
                ok=ls(ans)==ls(c); return ok,pts if ok else 0.0
        if t in ("text_input","fill_blank"):
            u=str(ans).strip().lower(); cc=str(c).strip().lower()
            acc=[str(x).strip().lower() for x in q.get("accepted_answers",[])]
            ok=u==cc or u in acc; return ok,pts if ok else 0.0
    except Exception as e: log.error(f"Scoring: {e}")
    return False,0.0

def _grade(p):
    if p>=90: return "A+"
    if p>=80: return "A"
    if p>=70: return "B"
    if p>=60: return "C"
    if p>=50: return "D"
    return "F"

def _emoji(p):
    if p>=90: return "🌟"
    if p>=80: return "🔥"
    if p>=70: return "👍"
    if p>=60: return "👌"
    if p>=50: return "⚠️"
    return "❌"

def format_result(res, test):
    pct=res.get("percentage",0); passed=pct>=test.get("passing_score",60)
    m,s=divmod(res.get("time_spent",0),60)
    holat="🎉 MUVAFFAQIYATLI O'TDINGIZ!" if passed else f"❌ YIQILDINGIZ (o'tish: {test.get('passing_score',60)}%)"
    return (f"{res.get('emoji','📝')} <b>TEST NATIJASI</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📝 <b>{test.get('title','Test')}</b>\n📁 {test.get('category','')}\n\n"
            f"📊 <b>{pct}%</b> | 🎯 {res.get('grade','F')}\n"
            f"✅ {res.get('correct_count',0)}   ❌ {res.get('wrong_count',0)}   ⏭ {res.get('skipped_count',0)}\n"
            f"⏱ {m} daq {s:02d} son\n━━━━━━━━━━━━━━━━━━━━━━━━\n🏆 {holat}")
