"""
9A4CA — Class Cube Results
Supports multi-round competitions + permanent Supabase storage
"""

import streamlit as st
import pandas as pd
from datetime import date
import re
import hashlib
import sys
import asyncio
from collections import Counter

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
WCA_DARK = "#1a1a2e"

st.set_page_config(page_title="9A4CA Rankings", page_icon="🧊", layout="wide")

# ─── Password helpers ───
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
    """Ensure default admin password exists."""
    sb = get_supabase()
    try:
        res = sb.table("settings").select("value").eq("key", "admin_password_hash").execute()
        if not res.data:
            sb.table("settings").insert({
                "key": "admin_password_hash",
                "value": hash_password(DEFAULT_PASSWORD)
            }).execute()
    except Exception as e:
        st.warning(f"Could not init settings: {e}")

def get_admin_hash():
    sb = get_supabase()
    res = sb.table("settings").select("value").eq("key", "admin_password_hash").execute()
    if res.data:
        return res.data[0]["value"]
    return hash_password(DEFAULT_PASSWORD)

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

def calculate_average_and_best(solves):
    """Proper WCA-style Average of 5 (ao5)."""
    if len(solves) < 5:
        solves = solves + [None] * (5 - len(solves))
    solves = solves[:5]

    dnf_count = sum(1 for s in solves if s is None)
    valid_times = [s for s in solves if s is not None]
    best = min(valid_times) if valid_times else None

    if dnf_count >= 2:
        return None, best

    ranking_list = [float("inf") if s is None else s for s in solves]
    ranking_list.sort()
    middle_three = ranking_list[1:4]

    if float("inf") in middle_three:
        return None, best

    average = sum(middle_three) / 3
    return round(average, 2), best

# ─── Data functions (Supabase) ───
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
    round_count = Counter([r["competition_id"] for r in rounds])
    for c in comps:
        c["round_count"] = round_count.get(c["id"], 0)
    return pd.DataFrame(comps) if comps else pd.DataFrame(columns=["id", "name", "date", "location", "notes", "round_count"])

def add_competition(name, comp_date, location, notes, round_names):
    sb = get_supabase()
    res = sb.table("competitions").insert({
        "name": name.strip(),
        "date": str(comp_date),
        "location": location.strip() if location else None,
        "notes": notes.strip() if notes else None
    }).execute()
    comp_id = res.data[0]["id"]

    rounds_data = [
        {"competition_id": comp_id, "name": rname.strip(), "round_number": i}
        for i, rname in enumerate(round_names, 1)
    ]
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
    return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=["id", "name", "round_number"])

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

def upsert_result(round_id, competitor_id, solves):
    average, best = calculate_average_and_best(solves)
    while len(solves) < 5:
        solves.append(None)
    solves = solves[:5]

    data = {
        "round_id": round_id,
        "competitor_id": competitor_id,
        "solve1": solves[0],
        "solve2": solves[1],
        "solve3": solves[2],
        "solve4": solves[3],
        "solve5": solves[4],
        "average": average,
        "best": best
    }
    sb = get_supabase()
    sb.table("results").upsert(data, on_conflict="round_id,competitor_id").execute()

def get_overall_leaderboard(metric="single"):
    col = "best" if metric == "single" else "average"
    sb = get_supabase()

    res = sb.table("results")\
        .select(f"competitor_id, {col}, competitors(name), rounds(competitions(name))")\
        .not_.is_(col, "null")\
        .execute()

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
    best_df = df.loc[idx].copy()
    best_df = best_df.rename(columns={"value": "best"})

    counts = df.groupby("competitor_id").size().rename("competitions")
    best_df = best_df.merge(counts, left_on="competitor_id", right_index=True)
    best_df = best_df.sort_values("best").reset_index(drop=True)
    return best_df[["name", "best", "competition", "competitions"]]

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
    display.insert(0, "#", range(1, len(display) + 1))
    display["Result"] = display["best"].apply(format_time)
    display = display.rename(columns={
        "name": "Name",
        "competition": "Competition",
        "competitions": "Rounds"
    })
    st.dataframe(display[["#", "Name", "Result", "Competition", "Rounds"]],
                 use_container_width=True, hide_index=True)

def page_home():
    st.markdown(f'''
    <div class="wca-header">
        <h1>9A4CA</h1>
        <div class="sub">Class Cubing Association</div>
    </div>
    ''', unsafe_allow_html=True)

    comps = list_competitions()
    competitors = list_competitors()
    overall_single = get_overall_leaderboard("single")
    overall_avg = get_overall_leaderboard("average")

    c1, c2, c3 = st.columns(3)
    c1.metric("Competitors", len(competitors))
    c2.metric("Competitions", len(comps))
    best = format_time(overall_single["best"].iloc[0]) if not overall_single.empty else "—"
    c3.metric("Best Single", best)

    st.markdown("---")
    st.subheader("🏆 Overall Rankings (Best Single)")
    render_overall_table(overall_single)

    st.subheader("📊 Overall Rankings (Best Average)")
    render_overall_table(overall_avg)

    st.markdown("---")
    st.subheader("📅 Competitions")
    if comps.empty:
        st.info("No competitions yet.")
    else:
        for _, row in comps.iterrows():
            with st.expander(f"**{row['name']}** — {row['date']} ({row['round_count']} rounds)"):
                st.write(f"📍 {row.get('location') or '—'}")
                if st.button("View results", key=f"home_view_{row['id']}"):
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
        col1, col2 = st.columns([5, 1])
        with col1:
            st.markdown(f"### {row['name']}")
            st.caption(f"{row['date']} · {row.get('location') or '—'} · {row['round_count']} rounds")
        with col2:
            if st.button("Results →", key=f"results_btn_{row['id']}"):
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
        st.error("Competition not found.")
        return

    rounds = get_rounds(comp_id)

    st.markdown(f'''
    <div class="wca-header">
        <h1>{comp["name"]}</h1>
        <div class="sub">{comp["date"]} · {comp.get("location") or ""}</div>
    </div>
    ''', unsafe_allow_html=True)

    if rounds.empty:
        st.warning("This competition has no rounds.")
        return

    round_names = rounds["name"].tolist()
    selected_round_name = st.selectbox("Select Round", round_names, key="round_selector")
    round_row = rounds[rounds["name"] == selected_round_name].iloc[0]
    round_id = int(round_row["id"])

    st.subheader(selected_round_name)
    is_final = "final" in selected_round_name.lower()

    results = get_results_for_round(round_id)

    if results.empty:
        st.info("No results in this round yet.")
    else:
        display_df = results.copy()
        display_df.insert(0, "#", range(1, len(display_df) + 1))
        display_df["1"] = display_df["solve1"].apply(format_time)
        display_df["2"] = display_df["solve2"].apply(format_time)
        display_df["3"] = display_df["solve3"].apply(format_time)
        display_df["4"] = display_df["solve4"].apply(format_time)
        display_df["5"] = display_df["solve5"].apply(format_time)
        display_df["Average"] = display_df["average"].apply(format_time)
        display_df["Best"] = display_df["best"].apply(format_time)

        show_cols = ["#", "name", "1", "2", "3", "4", "5", "Average", "Best"]
        display_df = display_df[show_cols].rename(columns={"name": "Name"})

        st.dataframe(display_df, use_container_width=True, hide_index=True,
                     height=min(600, 40 + len(display_df) * 38))

        if is_final:
            winner_name = results.iloc[0]["name"]
            winner_avg = format_time(results.iloc[0]["average"])
            st.success(f"🏆 **Champion of {comp['name']}**: **{winner_name}** (Average: {winner_avg})")

    st.markdown("---")
    if st.button("← Back to competitions"):
        st.session_state.page = "Competitions"
        st.session_state.selected_comp = None
        st.rerun()

def page_overall():
    st.markdown(f'''
    <div class="wca-header">
        <h1>Rankings</h1>
        <div class="sub">Best times across all 9A4CA competitions</div>
    </div>
    ''', unsafe_allow_html=True)

    metric = st.radio("Type", ["Single", "Average"], horizontal=True)
    df = get_overall_leaderboard("single" if metric == "Single" else "average")
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
            st.markdown("**Rounds** (one per line)")
            rounds_text = st.text_area("Round names", value="First Round\nSecond Round\nFinal", height=100)
            if st.form_submit_button("Create Competition", type="primary"):
                if not name.strip():
                    st.error("Name required")
                else:
                    round_names = [r.strip() for r in rounds_text.splitlines() if r.strip()]
                    if not round_names:
                        st.error("Add at least one round")
                    else:
                        add_competition(name, str(comp_date), location, notes, round_names)
                        st.success(f"Created **{name}** with {len(round_names)} rounds!")
                        st.rerun()

        st.markdown("---")
        st.subheader("Existing Competitions")
        for _, row in list_competitions().iterrows():
            c1, c2 = st.columns([5, 1])
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
        st.subheader("All Competitors")
        for _, row in list_competitors().iterrows():
            c1, c2 = st.columns([5, 1])
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
            st.warning("Create a competition and add competitors first.")
        else:
            comp_options = {f"{r['name']} ({r['date']})": int(r["id"]) for _, r in comps.iterrows()}
            selected_comp_label = st.selectbox("Competition", list(comp_options.keys()))
            comp_id = comp_options[selected_comp_label]

            rounds = get_rounds(comp_id)
            if rounds.empty:
                st.error("This competition has no rounds.")
            else:
                round_options = {r["name"]: int(r["id"]) for _, r in rounds.iterrows()}
                selected_round = st.selectbox("Round", list(round_options.keys()))
                round_id = round_options[selected_round]

                st.markdown(f"**Entering results for:** {selected_round}")
                with st.form("enter_result"):
                    person = st.selectbox("Competitor", competitors["name"].tolist())
                    st.markdown("**Solves** (leave empty or type DNF)")
                    cols = st.columns(5)
                    solves_str = []
                    for i, col in enumerate(cols):
                        with col:
                            solves_str.append(st.text_input(f"Solve {i+1}", key=f"s{i}"))
                    if st.form_submit_button("Save Result", type="primary"):
                        solves = [parse_time(s) for s in solves_str]
                        cid = get_competitor_id_by_name(person)
                        if cid:
                            upsert_result(round_id, cid, solves)
                            st.success(f"Saved for **{person}** in {selected_round}!")
                            st.rerun()

                st.markdown("---")
                st.subheader(f"Current results — {selected_round}")
                current = get_results_for_round(round_id)
                if current.empty:
                    st.info("No results yet.")
                else:
                    display = current.copy()
                    for i in range(1, 6):
                        display[f"S{i}"] = display[f"solve{i}"].apply(format_time)
                    display["Avg"] = display["average"].apply(format_time)
                    display["Best"] = display["best"].apply(format_time)
                    st.dataframe(
                        display[["name", "S1", "S2", "S3", "S4", "S5", "Avg", "Best"]].rename(columns={"name": "Name"}),
                        use_container_width=True, hide_index=True
                    )

    with tab4:
        st.subheader("Change Password")
        with st.form("pw"):
            cur = st.text_input("Current", type="password")
            n1 = st.text_input("New", type="password")
            n2 = st.text_input("Confirm", type="password")
            if st.form_submit_button("Update"):
                if not verify_password(cur, get_admin_hash()):
                    st.error("Wrong current password")
                elif n1 != n2:
                    st.error("Passwords don't match")
                elif len(n1) < 6:
                    st.error("Too short")
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

    menu = st.sidebar.radio(
        "Navigation",
        ["🏠 Home", "📅 Competitions", "🏆 Rankings", "⚙️ Admin"],
        key="sidebar_menu"
    )

    if menu == "🏠 Home":
        st.session_state.page = "Home"
        st.session_state.selected_comp = None
    elif menu == "📅 Competitions":
        if st.session_state.page != "Competition Results":
            st.session_state.page = "Competitions"
    elif menu == "🏆 Rankings":
        st.session_state.page = "Overall"
        st.session_state.selected_comp = None
    elif menu == "⚙️ Admin":
        st.session_state.page = "Admin"
        st.session_state.selected_comp = None

    if st.session_state.selected_comp is not None:
        st.session_state.page = "Competition Results"

    if st.session_state.page == "Home":
        page_home()
    elif st.session_state.page == "Competitions":
        page_competitions()
    elif st.session_state.page == "Competition Results":
        page_competition_results()
    elif st.session_state.page == "Overall":
        page_overall()
    elif st.session_state.page == "Admin":
        page_admin()

    st.sidebar.markdown("---")
    st.sidebar.caption("Inspired by WCA Live")

if __name__ == "__main__":
    main()
