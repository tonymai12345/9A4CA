"""
9A4CA — Class Cube Results
Full version with:
- Multi-event + Format support
- PR / CL badges
- Personal competitor pages
- Supabase storage
"""

import streamlit as st
import pandas as pd
from datetime import date
import re
import hashlib
import sys
import asyncio
from collections import Counter, defaultdict

# ─── Windows fix ───
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# ─── Config ───
ADMIN_USERNAME = "admin"
DEFAULT_PASSWORD = "admin123"
WCA_RED = "#96120C"
WCA_BLUE = "#465D7B"

st.set_page_config(page_title="9A4CA Rankings", page_icon="🧊", layout="wide")

# ─── WCA Events & Formats ───
WCA_EVENTS = {
    "333": "3×3×3 Cube",
    "222": "2×2×2 Cube",
    "444": "4×4×4 Cube",
    "555": "5×5×5 Cube",
    "666": "6×6×6 Cube",
    "777": "7×7×7 Cube",
    "333bf": "3×3×3 Blindfolded",
    "333oh": "3×3×3 One-Handed",
    "clock": "Clock",
    "minx": "Megaminx",
    "pyram": "Pyraminx",
    "skewb": "Skewb",
    "sq1": "Square-1",
}

FORMATS = {
    "ao5": "Average of 5",
    "bo5": "Best of 5",
    "bo3": "Best of 3",
    "mo3": "Mean of 3",
    "bo1": "Best of 1",
    "bo2": "Best of 2",
}

# ─── Password ───
def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

def verify_password(p, h):
    return hash_password(p) == h

# ─── Supabase ───
from supabase import create_client, Client

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

def init_db():
    sb = get_supabase()
    try:
        res = sb.table("settings").select("value").eq("key", "admin_password_hash").execute()
        if not res.data:
            sb.table("settings").insert({
                "key": "admin_password_hash",
                "value": hash_password(DEFAULT_PASSWORD)
            }).execute()
    except Exception:
        pass

def get_admin_hash():
    sb = get_supabase()
    res = sb.table("settings").select("value").eq("key", "admin_password_hash").execute()
    return res.data[0]["value"] if res.data else hash_password(DEFAULT_PASSWORD)

def set_admin_password(pw):
    sb = get_supabase()
    sb.table("settings").upsert({
        "key": "admin_password_hash",
        "value": hash_password(pw)
    }).execute()

# ─── Time helpers ───
def format_time(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return "—"
    if s < 0:
        return "DNF"
    m = int(s // 60)
    sec = s % 60
    return f"{m}:{sec:05.2f}" if m > 0 else f"{sec:.2f}"

def parse_time(text):
    text = text.strip().upper()
    if not text or text in ("DNF", "DNS", "-", "—", ""):
        return None
    m = re.match(r"^(\d+):(\d{1,2}(?:\.\d+)?)$", text)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(text)
    except:
        return None

def calculate_average_and_best(solves, fmt="ao5"):
    """Support basic formats. Focus on ao5 / bo5 / mo3 / bo3."""
    if len(solves) < 5:
        solves = solves + [None] * (5 - len(solves))
    solves = solves[:5]

    valid = [s for s in solves if s is not None]
    best = min(valid) if valid else None

    if fmt in ("bo1", "bo2", "bo3", "bo5"):
        return None, best          # Best-of formats have no average

    # Mean of 3
    if fmt == "mo3":
        if len(valid) < 3:
            return None, best
        return round(sum(valid[:3]) / 3, 2), best

    # Average of 5 (default)
    dnf_count = sum(1 for s in solves if s is None)
    if dnf_count >= 2:
        return None, best

    ranking = [float("inf") if s is None else s for s in solves]
    ranking.sort()
    middle = ranking[1:4]
    if float("inf") in middle:
        return None, best
    return round(sum(middle) / 3, 2), best

# ─── Data functions ───
def list_competitors():
    sb = get_supabase()
    res = sb.table("competitors").select("*").order("name").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=["id", "name"])

def add_competitor(name):
    sb = get_supabase()
    try:
        sb.table("competitors").insert({"name": name.strip()}).execute()
        return True, "Added"
    except Exception:
        return False, "Already exists"

def delete_competitor(cid):
    sb = get_supabase()
    sb.table("results").delete().eq("competitor_id", cid).execute()
    sb.table("competitors").delete().eq("id", cid).execute()

def get_competitor_id_by_name(name):
    sb = get_supabase()
    res = sb.table("competitors").select("id").eq("name", name.strip()).execute()
    return res.data[0]["id"] if res.data else None

def list_competitions():
    sb = get_supabase()
    comps = sb.table("competitions").select("*").order("date", desc=True).execute().data or []
    rounds = sb.table("rounds").select("competition_id").execute().data or []
    cnt = Counter([r["competition_id"] for r in rounds])
    for c in comps:
        c["round_count"] = cnt.get(c["id"], 0)
    return pd.DataFrame(comps) if comps else pd.DataFrame(columns=["id","name","date","location","notes","round_count"])

def add_competition(name, comp_date, location, notes, round_names, events, fmt):
    sb = get_supabase()
    res = sb.table("competitions").insert({
        "name": name.strip(),
        "date": str(comp_date),
        "location": location.strip() if location else None,
        "notes": notes.strip() if notes else None
    }).execute()
    comp_id = res.data[0]["id"]

    rounds_data = []
    for event in events:
        for i, rname in enumerate(round_names, 1):
            rounds_data.append({
                "competition_id": comp_id,
                "name": rname.strip(),
                "round_number": i,
                "event": event,
                "format": fmt
            })
    if rounds_data:
        sb.table("rounds").insert(rounds_data).execute()
    return comp_id

def get_competition(comp_id):
    sb = get_supabase()
    res = sb.table("competitions").select("*").eq("id", comp_id).execute()
    return res.data[0] if res.data else None

def get_rounds(comp_id):
    sb = get_supabase()
    res = sb.table("rounds").select("*").eq("competition_id", comp_id).order("round_number").execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def delete_competition(comp_id):
    sb = get_supabase()
    rounds = sb.table("rounds").select("id").eq("competition_id", comp_id).execute().data or []
    round_ids = [r["id"] for r in rounds]
    if round_ids:
        sb.table("results").delete().in_("round_id", round_ids).execute()
    sb.table("rounds").delete().eq("competition_id", comp_id).execute()
    sb.table("competitions").delete().eq("id", comp_id).execute()

def get_results_for_round(round_id):
    sb = get_supabase()
    res = sb.table("results").select("*, competitors(name)").eq("round_id", round_id).execute()
    rows = []
    for r in (res.data or []):
        row = dict(r)
        row["name"] = r["competitors"]["name"] if r.get("competitors") else ""
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["avg_sort"] = df["average"].fillna(float("inf"))
    df["best_sort"] = df["best"].fillna(float("inf"))
    df = df.sort_values(["avg_sort", "best_sort"]).drop(columns=["avg_sort", "best_sort"])
    return df.reset_index(drop=True)

def upsert_result(round_id, competitor_id, solves, fmt="ao5"):
    average, best = calculate_average_and_best(solves, fmt)
    while len(solves) < 5:
        solves.append(None)
    solves = solves[:5]
    data = {
        "round_id": round_id,
        "competitor_id": competitor_id,
        "solve1": solves[0], "solve2": solves[1], "solve3": solves[2],
        "solve4": solves[3], "solve5": solves[4],
        "average": average, "best": best
    }
    sb = get_supabase()
    sb.table("results").upsert(data, on_conflict="round_id,competitor_id").execute()

def get_personal_bests(event="333"):
    sb = get_supabase()
    res = sb.table("results").select(
        "competitor_id, best, average, rounds!inner(event)"
    ).eq("rounds.event", event).execute()
    pbs = {}
    for r in (res.data or []):
        cid = r["competitor_id"]
        if cid not in pbs:
            pbs[cid] = {"best": None, "average": None}
        if r["best"] is not None and (pbs[cid]["best"] is None or r["best"] < pbs[cid]["best"]):
            pbs[cid]["best"] = r["best"]
        if r["average"] is not None and (pbs[cid]["average"] is None or r["average"] < pbs[cid]["average"]):
            pbs[cid]["average"] = r["average"]
    return pbs

def get_class_records(event="333"):
    sb = get_supabase()
    res = sb.table("results").select(
        "best, average, rounds!inner(event)"
    ).eq("rounds.event", event).execute()
    bests = [r["best"] for r in (res.data or []) if r["best"] is not None]
    avgs = [r["average"] for r in (res.data or []) if r["average"] is not None]
    return {
        "best": min(bests) if bests else None,
        "average": min(avgs) if avgs else None
    }

def make_time_with_badges(value, pb_value, class_value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    text = format_time(value)
    badges = ""
    if pb_value is not None and abs(value - pb_value) < 0.001:
        badges += ' <span style="background:#2563eb;color:white;padding:1px 6px;border-radius:4px;font-size:0.7rem;font-weight:700;">PR</span>'
    if class_value is not None and abs(value - class_value) < 0.001:
        badges += ' <span style="background:#d97706;color:white;padding:1px 6px;border-radius:4px;font-size:0.7rem;font-weight:700;">CL</span>'
    return f"{text}{badges}"

def get_overall_leaderboard(event="333", metric="single"):
    col = "best" if metric == "single" else "average"
    sb = get_supabase()
    res = sb.table("results").select(
        f"competitor_id, {col}, competitors(name), rounds!inner(event, competitions(name))"
    ).eq("rounds.event", event).not_.is_(col, "null").execute()

    if not res.data:
        return pd.DataFrame(columns=["name", "best", "competition", "competitions"])

    records = []
    for r in res.data:
        records.append({
            "competitor_id": r["competitor_id"],
            "name": r["competitors"]["name"] if r.get("competitors") else "",
            "value": r[col],
            "competition": r["rounds"]["competitions"]["name"] if r.get("rounds") and r["rounds"].get("competitions") else ""
        })
    df = pd.DataFrame(records)
    idx = df.groupby("competitor_id")["value"].idxmin()
    best_df = df.loc[idx].copy().rename(columns={"value": "best"})
    counts = df.groupby("competitor_id").size().rename("competitions")
    best_df = best_df.merge(counts, left_on="competitor_id", right_index=True)
    return best_df.sort_values("best").reset_index(drop=True)[["name", "best", "competition", "competitions"]]

# ─── CSS ───
def inject_css():
    st.markdown(f"""
    <style>
    .stApp {{ background: #fff; }}
    .wca-header {{
        background: linear-gradient(90deg, {WCA_RED}, {WCA_BLUE});
        color: white; padding: 1rem 1.4rem; border-radius: 8px; margin-bottom: 1.2rem;
    }}
    .wca-header h1 {{ color: white !important; margin: 0; font-size: 1.6rem; }}
    .wca-header .sub {{ font-size: 0.9rem; opacity: 0.9; }}
    .name-btn {{
        background: none; border: none; color: #c0392b; font-weight: 500;
        cursor: pointer; padding: 0; text-align: left;
    }}
    .name-btn:hover {{ text-decoration: underline; }}
    </style>
    """, unsafe_allow_html=True)

# ─── Auth ───
def check_login():
    return st.session_state.get("authenticated", False)

def login_form():
    st.markdown(f'<div class="wca-header"><h1>9A4CA</h1><div class="sub">Admin Login</div></div>', unsafe_allow_html=True)
    with st.form("login"):
        u = st.text_input("Username", value="admin")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Log in", type="primary"):
            if u == ADMIN_USERNAME and verify_password(p, get_admin_hash()):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Wrong credentials")
    st.caption("Default: admin / admin123")

# ─── Pages ───
def render_overall_table(df):
    if df.empty:
        st.info("No results yet.")
        return
    display = df.copy()
    display.insert(0, "#", range(1, len(display)+1))
    display["Result"] = display["best"].apply(format_time)
    display = display.rename(columns={"name":"Name","competition":"Competition","competitions":"Rounds"})
    st.dataframe(display[["#","Name","Result","Competition","Rounds"]], use_container_width=True, hide_index=True)

def page_home():
    st.markdown(f'''
    <div class="wca-header">
        <h1>9A4CA</h1>
        <div class="sub">Class Cubing Association</div>
    </div>
    ''', unsafe_allow_html=True)

    comps = list_competitions()
    competitors = list_competitors()
    overall = get_overall_leaderboard("333", "single")

    c1, c2, c3 = st.columns(3)
    c1.metric("Competitors", len(competitors))
    c2.metric("Competitions", len(comps))
    best = format_time(overall["best"].iloc[0]) if not overall.empty else "—"
    c3.metric("Best Single (3×3)", best)

    st.markdown("---")
    st.subheader("🏆 Overall Rankings — 3×3×3 Single")
    render_overall_table(overall)

    st.subheader("📊 Overall Rankings — 3×3×3 Average")
    render_overall_table(get_overall_leaderboard("333", "average"))

    st.markdown("---")
    st.subheader("📅 Competitions")
    if comps.empty:
        st.info("No competitions yet.")
    else:
        for _, row in comps.iterrows():
            with st.expander(f"**{row['name']}** — {row['date']} ({row['round_count']} rounds)"):
                st.write(f"📍 {row.get('location') or '—'}")
                if st.button("View results", key=f"home_{row['id']}"):
                    st.session_state.selected_comp = int(row["id"])
                    st.session_state.page = "Competition Results"
                    st.rerun()

def page_competitions():
    st.markdown(f'<div class="wca-header"><h1>Competitions</h1><div class="sub">All 9A4CA competitions</div></div>', unsafe_allow_html=True)
    comps = list_competitions()
    if comps.empty:
        st.info("No competitions yet.")
        return
    for _, row in comps.iterrows():
        col1, col2 = st.columns([5,1])
        with col1:
            st.markdown(f"### {row['name']}")
            st.caption(f"{row['date']} · {row.get('location') or '—'} · {row['round_count']} rounds")
        with col2:
            if st.button("Results →", key=f"comp_{row['id']}"):
                st.session_state.selected_comp = int(row["id"])
                st.session_state.page = "Competition Results"
                st.rerun()
        st.markdown("---")

def page_competition_results():
    comp_id = st.session_state.get("selected_comp")
    if not comp_id:
        st.warning("No competition selected")
        if st.button("← Back to competitions"):
            st.session_state.page = "Competitions"
            st.rerun()
        return

    comp = get_competition(comp_id)
    if not comp:
        st.error("Competition not found")
        return

    rounds = get_rounds(comp_id)

    st.markdown(f'''
    <div class="wca-header">
        <h1>{comp["name"]}</h1>
        <div class="sub">{comp["date"]} · {comp.get("location") or ""}</div>
    </div>
    ''', unsafe_allow_html=True)

    if rounds.empty:
        st.warning("No rounds.")
        return

    # Nice labels for the selectbox
    rounds = rounds.copy()
    rounds["label"] = rounds.apply(
        lambda r: f"{WCA_EVENTS.get(r.get('event', '333'), r.get('event', '333'))} — {r['name']} ({FORMATS.get(r.get('format', 'ao5'), 'ao5')})",
        axis=1
    )

    selected_label = st.selectbox("Select Round", rounds["label"].tolist(), key="round_selector")
    round_row = rounds[rounds["label"] == selected_label].iloc[0]
    round_id = int(round_row["id"])
    event = round_row.get("event", "333")
    fmt = round_row.get("format", "ao5")

    st.subheader(f"{WCA_EVENTS.get(event, event)} — {round_row['name']}")
    is_final = "final" in str(round_row["name"]).lower()

    results = get_results_for_round(round_id)

    if results.empty:
        st.info("No results in this round yet.")
    else:
        # Get PR & Class Record data
        pbs = get_personal_bests(event)
        class_rec = get_class_records(event)

        def add_badges(value, pb_value, class_value):
            """Return time string + PR/CL marks"""
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return "—"
            text = format_time(value)
            marks = ""
            if pb_value is not None and abs(value - pb_value) < 0.001:
                marks += " 🔵PR"
            if class_value is not None and abs(value - class_value) < 0.001:
                marks += " 🟡CL"
            return text + marks

        # Build clean dataframe
        display_df = results.copy()
        display_df.insert(0, "#", range(1, len(display_df) + 1))

        display_df["1"] = display_df["solve1"].apply(format_time)
        display_df["2"] = display_df["solve2"].apply(format_time)
        display_df["3"] = display_df["solve3"].apply(format_time)
        display_df["4"] = display_df["solve4"].apply(format_time)
        display_df["5"] = display_df["solve5"].apply(format_time)

        # Average & Best with badges
        avg_list = []
        best_list = []
        for _, row in results.iterrows():
            cid = row.get("competitor_id")
            pb = pbs.get(cid, {"best": None, "average": None})
            avg_list.append(add_badges(row["average"], pb["average"], class_rec["average"]))
            best_list.append(add_badges(row["best"], pb["best"], class_rec["best"]))

        display_df["Average"] = avg_list
        display_df["Best"] = best_list
        display_df = display_df.rename(columns={"name": "Name"})

        show_cols = ["#", "Name", "1", "2", "3", "4", "5", "Average", "Best"]
        st.dataframe(
            display_df[show_cols],
            use_container_width=True,
            hide_index=True,
            height=min(650, 45 + len(display_df) * 38)
        )

        st.caption("🔵 **PR** = Personal Record &nbsp;&nbsp;|&nbsp;&nbsp; 🟡 **CL** = Class Record")

        # Clickable names → Personal page
        st.markdown("#### Click a name to open personal page")
        cols = st.columns(4)
        for idx, row in results.iterrows():
            with cols[idx % 4]:
                if st.button(f"👤 {row['name']}", key=f"person_{row['competitor_id']}_{round_id}"):
                    st.session_state.selected_person = int(row["competitor_id"])
                    st.session_state.page = "Person"
                    st.rerun()

        if is_final and len(results) > 0:
            winner = results.iloc[0]
            st.success(f"🏆 **Champion of {comp['name']}**: **{winner['name']}** (Average: {format_time(winner['average'])})")

    st.markdown("---")
    if st.button("← Back to competitions"):
        st.session_state.selected_comp = None
        st.session_state.page = "Competitions"
        st.rerun()

def page_person():
    person_id = st.session_state.get("selected_person")
    if not person_id:
        st.warning("No competitor selected")
        return

    sb = get_supabase()
    person_res = sb.table("competitors").select("*").eq("id", person_id).execute()
    if not person_res.data:
        st.error("Competitor not found")
        return
    person = person_res.data[0]

    st.markdown(f'''
    <div class="wca-header">
        <h1>{person["name"]}</h1>
        <div class="sub">Personal Results</div>
    </div>
    ''', unsafe_allow_html=True)

    # Get all results of this person (with competition date + event)
    res = sb.table("results").select(
        "*, rounds(name, event, format, competitions(name, date))"
    ).eq("competitor_id", person_id).execute()

    if not res.data:
        st.info("No results yet.")
        if st.button("← Back"):
            st.session_state.selected_person = None
            st.session_state.page = "Home"
            st.rerun()
        return

    # ---------- helpers for current & historical records ----------
    def get_all_results_for_event(event_code):
        """All results of everyone for one event (for class records)."""
        r = sb.table("results").select(
            "competitor_id, best, average, rounds!inner(event, competitions(date))"
        ).eq("rounds.event", event_code).execute()
        return r.data or []

    # Group this person's results by event
    by_event = defaultdict(list)
    for r in res.data:
        event = r["rounds"]["event"] if r.get("rounds") else "333"
        by_event[event].append(r)

    for event_code, rows in by_event.items():
        event_name = WCA_EVENTS.get(event_code, event_code)
        st.subheader(event_name)

        # Current personal bests for this event
        person_bests = []
        person_avgs = []
        for r in rows:
            if r["best"] is not None:
                person_bests.append(r["best"])
            if r["average"] is not None:
                person_avgs.append(r["average"])
        current_pb_best = min(person_bests) if person_bests else None
        current_pb_avg = min(person_avgs) if person_avgs else None

        # Current class records for this event
        all_event_results = get_all_results_for_event(event_code)
        class_bests = [x["best"] for x in all_event_results if x["best"] is not None]
        class_avgs = [x["average"] for x in all_event_results if x["average"] is not None]
        current_cl_best = min(class_bests) if class_bests else None
        current_cl_avg = min(class_avgs) if class_avgs else None

        # Sort this person's results by competition date (oldest first)
        def get_date(r):
            try:
                return r["rounds"]["competitions"].get("date") or "9999"
            except:
                return "9999"
        rows_sorted = sorted(rows, key=get_date)

        # Track running personal bests to detect former PRs
        running_pb_best = None
        running_pb_avg = None

        data = []
        for r in rows_sorted:
            avg = r["average"]
            best = r["best"]

            # --- Average marks ---
            avg_marks = ""
            if avg is not None:
                # Current PR
                if current_pb_avg is not None and abs(avg - current_pb_avg) < 0.001:
                    avg_marks += " 🔵PR"
                # Former PR (was best at the time, but later broken)
                elif running_pb_avg is None or avg < running_pb_avg:
                    avg_marks += " ⚪ex-PR"
                    running_pb_avg = avg
                else:
                    # still update running if better (shouldn't happen because of elif)
                    pass

                # Current Class Record
                if current_cl_avg is not None and abs(avg - current_cl_avg) < 0.001:
                    avg_marks += " 🟡CL"
                # We don't easily know historical class records without more data,
                # so we only mark current CL for average

            # --- Best (single) marks ---
            best_marks = ""
            if best is not None:
                if current_pb_best is not None and abs(best - current_pb_best) < 0.001:
                    best_marks += " 🔵PR"
                elif running_pb_best is None or best < running_pb_best:
                    best_marks += " ⚪ex-PR"
                    running_pb_best = best

                if current_cl_best is not None and abs(best - current_cl_best) < 0.001:
                    best_marks += " 🟡CL"

            # Update running PBs after checking
            if avg is not None:
                if running_pb_avg is None or avg < running_pb_avg:
                    running_pb_avg = avg
            if best is not None:
                if running_pb_best is None or best < running_pb_best:
                    running_pb_best = best

            data.append({
                "Competition": r["rounds"]["competitions"]["name"] if r["rounds"].get("competitions") else "—",
                "Date": r["rounds"]["competitions"].get("date", "") if r["rounds"].get("competitions") else "",
                "Round": r["rounds"]["name"],
                "Format": FORMATS.get(r["rounds"].get("format", "ao5"), ""),
                "Average": format_time(avg) + avg_marks,
                "Best": format_time(best) + best_marks,
            })

        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)

    st.caption("🔵 **PR** = current Personal Record &nbsp;|&nbsp; 🟡 **CL** = current Class Record &nbsp;|&nbsp; ⚪ **ex-PR** = former Personal Record (broken)")

    if st.button("← Back"):
        st.session_state.selected_person = None
        st.session_state.page = "Home"
        st.rerun()
def page_overall():
    st.markdown(f'''
    <div class="wca-header">
        <h1>Rankings</h1>
        <div class="sub">Best times across all competitions</div>
    </div>
    ''', unsafe_allow_html=True)

    event = st.selectbox("Event", options=list(WCA_EVENTS.keys()),
                         format_func=lambda x: WCA_EVENTS[x], index=0)
    metric = st.radio("Type", ["Single", "Average"], horizontal=True)
    df = get_overall_leaderboard(event, "single" if metric == "Single" else "average")
    render_overall_table(df)

def page_admin():
    if not check_login():
        login_form()
        return

    st.markdown(f'<div class="wca-header"><h1>Admin Panel</h1><div class="sub">Manage 9A4CA</div></div>', unsafe_allow_html=True)
    if st.button("Log out"):
        st.session_state.authenticated = False
        st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["➕ Competition", "👤 Competitors", "📝 Enter Results", "🔑 Password"])

    with tab1:
        st.subheader("Create Competition")
        with st.form("new_comp"):
            name = st.text_input("Competition name *")
            comp_date = st.date_input("Date", value=date.today())
            location = st.text_input("Location")
            notes = st.text_area("Notes")

            selected_events = st.multiselect(
                "Events *",
                options=list(WCA_EVENTS.keys()),
                format_func=lambda x: WCA_EVENTS[x],
                default=["333"]
            )
            format_choice = st.selectbox(
                "Format",
                options=list(FORMATS.keys()),
                format_func=lambda x: FORMATS[x]
            )
            rounds_text = st.text_area(
                "Round names (one per line)",
                value="First Round\nFinal",
                height=80
            )

            if st.form_submit_button("Create Competition", type="primary"):
                if not name.strip():
                    st.error("Name required")
                elif not selected_events:
                    st.error("Select at least one event")
                else:
                    round_names = [r.strip() for r in rounds_text.splitlines() if r.strip()]
                    if not round_names:
                        st.error("Add at least one round")
                    else:
                        add_competition(name, str(comp_date), location, notes,
                                        round_names, selected_events, format_choice)
                        st.success(f"Created **{name}**!")
                        st.rerun()

        st.markdown("---")
        st.subheader("Existing Competitions")
        for _, row in list_competitions().iterrows():
            c1, c2 = st.columns([5,1])
            with c1:
                st.write(f"**{row['name']}** — {row['date']} ({row['round_count']} rounds)")
            with c2:
                if st.button("🗑️", key=f"delc{row['id']}"):
                    delete_competition(int(row["id"]))
                    st.rerun()

    with tab2:
        st.subheader("Add Competitor")
        with st.form("add_p"):
            n = st.text_input("Name *")
            if st.form_submit_button("Add"):
                if n.strip():
                    ok, msg = add_competitor(n)
                    st.success(msg) if ok else st.error(msg)
                    st.rerun()
        st.markdown("---")
        for _, row in list_competitors().iterrows():
            c1, c2 = st.columns([5,1])
            with c1:
                st.write(row["name"])
            with c2:
                if st.button("🗑️", key=f"delp{row['id']}"):
                    delete_competitor(int(row["id"]))
                    st.rerun()

    with tab3:
        st.subheader("Enter Results")
        comps = list_competitions()
        competitors = list_competitors()
        if comps.empty or competitors.empty:
            st.warning("Create competition and competitors first.")
        else:
            comp_options = {f"{r['name']} ({r['date']})": int(r["id"]) for _, r in comps.iterrows()}
            selected_comp = st.selectbox("Competition", list(comp_options.keys()))
            comp_id = comp_options[selected_comp]
            rounds = get_rounds(comp_id)

            if rounds.empty:
                st.error("No rounds.")
            else:
                rounds["label"] = rounds.apply(
                    lambda r: f"{WCA_EVENTS.get(r['event'], r['event'])} — {r['name']}", axis=1)
                selected_round_label = st.selectbox("Round", rounds["label"].tolist())
                round_row = rounds[rounds["label"] == selected_round_label].iloc[0]
                round_id = int(round_row["id"])
                fmt = round_row.get("format", "ao5")

                with st.form("enter_result"):
                    person = st.selectbox("Competitor", competitors["name"].tolist())
                    st.markdown("**Solves** (leave empty = DNF)")
                    cols = st.columns(5)
                    solves_str = []
                    for i, col in enumerate(cols):
                        with col:
                            solves_str.append(st.text_input(f"{i+1}", key=f"s{i}"))
                    if st.form_submit_button("Save", type="primary"):
                        solves = [parse_time(s) for s in solves_str]
                        cid = get_competitor_id_by_name(person)
                        if cid:
                            upsert_result(round_id, cid, solves, fmt)
                            st.success(f"Saved for **{person}**!")
                            st.rerun()

                st.markdown("---")
                current = get_results_for_round(round_id)
                if not current.empty:
                    display = current.copy()
                    for i in range(1,6):
                        display[f"S{i}"] = display[f"solve{i}"].apply(format_time)
                    display["Avg"] = display["average"].apply(format_time)
                    display["Best"] = display["best"].apply(format_time)
                    st.dataframe(display[["name","S1","S2","S3","S4","S5","Avg","Best"]].rename(columns={"name":"Name"}),
                                 use_container_width=True, hide_index=True)

    with tab4:
        st.subheader("Change Password")
        with st.form("pw"):
            cur = st.text_input("Current", type="password")
            n1 = st.text_input("New", type="password")
            n2 = st.text_input("Confirm", type="password")
            if st.form_submit_button("Update"):
                if not verify_password(cur, get_admin_hash()):
                    st.error("Wrong current password")
                elif n1 != n2 or len(n1) < 6:
                    st.error("Passwords don't match or too short")
                else:
                    set_admin_password(n1)
                    st.success("Password changed!")

# ─── Main ───
def main():
    init_db()
    inject_css()

    st.sidebar.markdown(f"""
    <div style="text-align:center;padding:1rem 0">
        <div style="font-size:2.3rem">🧊</div>
        <div style="font-weight:700;color:{WCA_RED};font-size:1.2rem">9A4CA</div>
        <div style="font-size:0.75rem;color:#666">Cubing Association</div>
    </div>
    """, unsafe_allow_html=True)
    st.sidebar.markdown("---")

    if "page" not in st.session_state:
        st.session_state.page = "Home"
    if "selected_comp" not in st.session_state:
        st.session_state.selected_comp = None
    if "selected_person" not in st.session_state:
        st.session_state.selected_person = None

    menu = st.sidebar.radio("Navigation",
        ["🏠 Home", "📅 Competitions", "🏆 Rankings", "⚙️ Admin"],
        key="sidebar_menu")

    if menu == "🏠 Home":
        st.session_state.page = "Home"
        st.session_state.selected_comp = None
        st.session_state.selected_person = None
    elif menu == "📅 Competitions":
        if st.session_state.page not in ("Competition Results", "Person"):
            st.session_state.page = "Competitions"
    elif menu == "🏆 Rankings":
        st.session_state.page = "Overall"
        st.session_state.selected_comp = None
        st.session_state.selected_person = None
    elif menu == "⚙️ Admin":
        st.session_state.page = "Admin"
        st.session_state.selected_comp = None
        st.session_state.selected_person = None

    if st.session_state.selected_person is not None:
        st.session_state.page = "Person"
    elif st.session_state.selected_comp is not None:
        st.session_state.page = "Competition Results"

    if st.session_state.page == "Home":
        page_home()
    elif st.session_state.page == "Competitions":
        page_competitions()
    elif st.session_state.page == "Competition Results":
        page_competition_results()
    elif st.session_state.page == "Person":
        page_person()
    elif st.session_state.page == "Overall":
        page_overall()
    elif st.session_state.page == "Admin":
        page_admin()

    st.sidebar.markdown("---")
    st.sidebar.caption("Inspired by WCA Live")

if __name__ == "__main__":
    main()
