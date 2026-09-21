"""
9A4CA — Class Cube Results
Supports multi-round competitions (like real WCA)
"""

import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
from pathlib import Path
import re
import hashlib
import sys
import asyncio

# ─── Windows fix ───
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# ─── Config ───
DB_PATH = Path(__file__).parent / "cube_results.db"
ADMIN_USERNAME = "admin"
DEFAULT_PASSWORD = "admin123"

WCA_RED = "#96120C"
WCA_BLUE = "#465D7B"
WCA_DARK = "#1a1a2e"

st.set_page_config(page_title="9A4CA Rankings", page_icon="🧊", layout="wide")

# ─── Password ───
def hash_password(p): return hashlib.sha256(p.encode()).hexdigest()
def verify_password(p, h): return hash_password(p) == h

# ─── Database ───
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS competitors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS competitions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        date TEXT NOT NULL,
        location TEXT,
        notes TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS rounds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        competition_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        round_number INTEGER NOT NULL,
        FOREIGN KEY (competition_id) REFERENCES competitions(id) ON DELETE CASCADE)""")
    c.execute("""CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        round_id INTEGER NOT NULL,
        competitor_id INTEGER NOT NULL,
        solve1 REAL, solve2 REAL, solve3 REAL, solve4 REAL, solve5 REAL,
        average REAL,
        best REAL,
        UNIQUE(round_id, competitor_id),
        FOREIGN KEY (round_id) REFERENCES rounds(id) ON DELETE CASCADE,
        FOREIGN KEY (competitor_id) REFERENCES competitors(id) ON DELETE CASCADE)""")

    # default password
    c.execute("SELECT value FROM settings WHERE key='admin_password_hash'")
    if not c.fetchone():
        c.execute("INSERT INTO settings VALUES (?,?)",
                  ("admin_password_hash", hash_password(DEFAULT_PASSWORD)))
    conn.commit()
    conn.close()

def get_admin_hash():
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key='admin_password_hash'").fetchone()
    conn.close()
    return row["value"] if row else hash_password(DEFAULT_PASSWORD)

def set_admin_password(pw):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                 ("admin_password_hash", hash_password(pw)))
    conn.commit()
    conn.close()

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
    """
    Proper WCA-style Average of 5 (ao5).
    - Removes best and worst
    - Averages the middle 3
    - Handles DNFs correctly
    """
    # solves is a list of 5 values (float or None). None = DNF
    if len(solves) < 5:
        # pad with None if needed
        solves = solves + [None] * (5 - len(solves))
    
    solves = solves[:5]

    # Count DNFs
    dnf_count = sum(1 for s in solves if s is None)

    # Best single (ignore DNFs)
    valid_times = [s for s in solves if s is not None]
    best = min(valid_times) if valid_times else None

    # If 2 or more DNFs → Average is DNF
    if dnf_count >= 2:
        return None, best          # None means DNF for average

    # For ranking purposes, treat DNF as a very large number
    ranking_list = []
    for s in solves:
        if s is None:
            ranking_list.append(float('inf'))   # DNF = worst
        else:
            ranking_list.append(s)

    # Sort and remove best + worst
    ranking_list.sort()
    middle_three = ranking_list[1:4]   # remove index 0 (best) and index 4 (worst)

    # If any of the middle three is DNF → Average = DNF
    if float('inf') in middle_three:
        return None, best

    average = sum(middle_three) / 3
    return round(average, 2), best

# ─── Data functions ───
def list_competitors():
    conn = get_conn()
    df = pd.read_sql_query("SELECT id, name FROM competitors ORDER BY name", conn)
    conn.close()
    return df

def add_competitor(name):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO competitors (name) VALUES (?)", (name.strip(),))
        conn.commit()
        return True, "Added"
    except sqlite3.IntegrityError:
        return False, "Already exists"
    finally:
        conn.close()

def delete_competitor(cid):
    conn = get_conn()
    conn.execute("DELETE FROM results WHERE competitor_id=?", (cid,))
    conn.execute("DELETE FROM competitors WHERE id=?", (cid,))
    conn.commit()
    conn.close()

def list_competitions():
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT c.*, COUNT(DISTINCT r.id) as round_count
        FROM competitions c
        LEFT JOIN rounds r ON r.competition_id = c.id
        GROUP BY c.id
        ORDER BY c.date DESC
    """, conn)
    conn.close()
    return df

def add_competition(name, comp_date, location, notes, round_names):
    """round_names = list of strings, e.g. ['First Round', 'Second Round', 'Final']"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO competitions (name, date, location, notes) VALUES (?,?,?,?)",
                (name.strip(), comp_date, location.strip(), notes.strip()))
    comp_id = cur.lastrowid
    for i, rname in enumerate(round_names, 1):
        cur.execute("INSERT INTO rounds (competition_id, name, round_number) VALUES (?,?,?)",
                    (comp_id, rname.strip(), i))
    conn.commit()
    conn.close()
    return comp_id

def get_competition(comp_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM competitions WHERE id=?", (comp_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_rounds(comp_id):
    conn = get_conn()
    df = pd.read_sql_query("""
        SELECT * FROM rounds WHERE competition_id=? ORDER BY round_number
    """, conn, params=(comp_id,))
    conn.close()
    return df

def delete_competition(comp_id):
    conn = get_conn()
    # cascade deletes rounds + results because of foreign keys
    conn.execute("DELETE FROM results WHERE round_id IN (SELECT id FROM rounds WHERE competition_id=?)", (comp_id,))
    conn.execute("DELETE FROM rounds WHERE competition_id=?", (comp_id,))
    conn.execute("DELETE FROM competitions WHERE id=?", (comp_id,))
    conn.commit()
    conn.close()

def get_results_for_round(round_id, is_final=False):
    conn = get_conn()
    
    # Always rank primarily by average (fastest average wins)
    # In Finals we still use average, but we can emphasize it more in the display
    df = pd.read_sql_query("""
        SELECT r.*, c.name
        FROM results r
        JOIN competitors c ON c.id = r.competitor_id
        WHERE r.round_id = ?
        ORDER BY
            CASE WHEN r.average IS NULL THEN 1 ELSE 0 END,
            r.average ASC,
            CASE WHEN r.best IS NULL THEN 1 ELSE 0 END,
            r.best ASC
    """, conn, params=(round_id,))
    conn.close()
    return df

def upsert_result(round_id, competitor_id, solves):
    """solves = list of 5 floats or None"""
    avg, best = calculate_average_and_best(solves)
    # pad to 5
    while len(solves) < 5:
        solves.append(None)
    conn = get_conn()
    conn.execute("""
        INSERT INTO results (round_id, competitor_id, solve1, solve2, solve3, solve4, solve5, average, best)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(round_id, competitor_id) DO UPDATE SET
            solve1=excluded.solve1, solve2=excluded.solve2, solve3=excluded.solve3,
            solve4=excluded.solve4, solve5=excluded.solve5,
            average=excluded.average, best=excluded.best
    """, (round_id, competitor_id, *solves[:5], avg, best))
    conn.commit()
    conn.close()

def get_overall_leaderboard(metric="single"):
    col = "best" if metric == "single" else "average"
    
    conn = get_conn()
    
    # This query finds the best time AND the competition where it was achieved
    df = pd.read_sql_query(f"""
        SELECT 
            c.name,
            r.{col} AS best,
            comp.name AS competition,
            COUNT(*) OVER (PARTITION BY c.id) AS competitions
        FROM results r
        JOIN competitors c ON c.id = r.competitor_id
        JOIN rounds rd ON rd.id = r.round_id
        JOIN competitions comp ON comp.id = rd.competition_id
        WHERE r.{col} IS NOT NULL
          AND r.{col} = (
              SELECT MIN(r2.{col})
              FROM results r2
              WHERE r2.competitor_id = r.competitor_id
                AND r2.{col} IS NOT NULL
          )
        GROUP BY c.id
        ORDER BY best ASC
    """, conn)
    
    conn.close()
    return df

def get_competitor_id_by_name(name):
    conn = get_conn()
    row = conn.execute("SELECT id FROM competitors WHERE name=?", (name.strip(),)).fetchone()
    conn.close()
    return row["id"] if row else None

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
    .rank-table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
    .rank-table th {{ background: #f0f2f5; padding: 9px 10px; text-align: left; border-bottom: 2px solid #dee2e6; }}
    .rank-table td {{ padding: 8px 10px; border-bottom: 1px solid #e9ecef; }}
    .rank-table tr:hover {{ background: #f8f9fa; }}
    .rank-1 {{ color: #d4af37; font-weight: 700; }}
    .rank-2 {{ color: #a8a8a8; font-weight: 700; }}
    .rank-3 {{ color: #cd7f32; font-weight: 700; }}
    .name-link {{ color: #c0392b; font-weight: 500; }}
    .result-time {{ font-family: Consolas, Monaco, monospace; font-weight: 600; }}
    .green-rank {{ background: #d4edda !important; }}
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
                st.write(f"📍 {row['location'] or '—'}")
                if st.button("View results", key=f"home_view_{row['id']}"):
                    st.session_state.selected_comp = int(row["id"])
                    st.session_state.page = "Competition Results"
                    st.rerun()
                    st.rerun()

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

    show_cols = ["#", "Name", "Result", "Competition", "Rounds"]
    st.dataframe(
        display[show_cols],
        use_container_width=True,
        hide_index=True
    )

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
            st.caption(f"{row['date']} · {row['location'] or '—'} · {row['round_count']} rounds")
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

    # Header
    st.markdown(f'''
    <div class="wca-header">
        <h1>{comp["name"]}</h1>
        <div class="sub">{comp["date"]} · {comp.get("location") or ""}</div>
    </div>
    ''', unsafe_allow_html=True)

    if rounds.empty:
        st.warning("This competition has no rounds.")
        return

    # Round selector
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
        # Create a clean dataframe for display
        display_df = results.copy()
        display_df.insert(0, "#", range(1, len(display_df) + 1))
        
        display_df["1"] = display_df["solve1"].apply(format_time)
        display_df["2"] = display_df["solve2"].apply(format_time)
        display_df["3"] = display_df["solve3"].apply(format_time)
        display_df["4"] = display_df["solve4"].apply(format_time)
        display_df["5"] = display_df["solve5"].apply(format_time)
        display_df["Average"] = display_df["average"].apply(format_time)
        display_df["Best"] = display_df["best"].apply(format_time)

        # Show only the columns we want
        show_cols = ["#", "name", "1", "2", "3", "4", "5", "Average", "Best"]
        display_df = display_df[show_cols].rename(columns={"name": "Name"})

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=min(600, 40 + len(display_df) * 38)
        )

        # Winner message for Finals
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

    # ── Create Competition + Rounds ──
    with tab1:
        st.subheader("Create Competition")
        with st.form("new_comp"):
            name = st.text_input("Competition name *")
            comp_date = st.date_input("Date", value=date.today())
            location = st.text_input("Location")
            notes = st.text_area("Notes")

            st.markdown("**Rounds** (one per line)")
            rounds_text = st.text_area(
                "Round names",
                value="First Round\nSecond Round\nFinal",
                height=100,
                help="Write one round name per line. Example:\nFirst Round\nSecond Round\nFinal"
            )
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
            c1, c2 = st.columns([5,1])
            with c1:
                st.write(f"**{row['name']}** — {row['date']} ({row['round_count']} rounds)")
            with c2:
                if st.button("🗑️", key=f"delc{row['id']}"):
                    delete_competition(int(row["id"]))
                    st.rerun()

    # ── Competitors ──
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
            c1, c2 = st.columns([5,1])
            with c1:
                st.write(row["name"])
            with c2:
                if st.button("🗑️", key=f"delp{row['id']}"):
                    delete_competitor(int(row["id"]))
                    st.rerun()

    # ── Enter Results ──
    with tab3:
        st.subheader("Enter Results")
        comps = list_competitions()
        competitors = list_competitors()
        if comps.empty or competitors.empty:
            st.warning("Create a competition and add competitors first.")
        else:
            # Choose competition
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

                # Show current results of this round
                st.markdown("---")
                st.subheader(f"Current results — {selected_round}")
                current = get_results_for_round(round_id)
                if current.empty:
                    st.info("No results yet.")
                else:
                    display = current.copy()
                    for i in range(1,6):
                        display[f"S{i}"] = display[f"solve{i}"].apply(format_time)
                    display["Avg"] = display["average"].apply(format_time)
                    display["Best"] = display["best"].apply(format_time)
                    st.dataframe(
                        display[["name","S1","S2","S3","S4","S5","Avg","Best"]].rename(columns={"name":"Name"}),
                        use_container_width=True, hide_index=True
                    )

    # ── Password ──
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

    # Sidebar logo
    st.sidebar.markdown(f"""
    <div style="text-align:center;padding:1rem 0">
        <div style="font-size:2.3rem">🧊</div>
        <div style="font-weight:700;color:{WCA_RED};font-size:1.2rem">9A4CA</div>
        <div style="font-size:0.75rem;color:#666">Cubing Association</div>
    </div>
    """, unsafe_allow_html=True)
    st.sidebar.markdown("---")

    # Initialize session state
    if "page" not in st.session_state:
        st.session_state.page = "Home"
    if "selected_comp" not in st.session_state:
        st.session_state.selected_comp = None

    # Sidebar menu
    menu = st.sidebar.radio(
        "Navigation",
        ["🏠 Home", "📅 Competitions", "🏆 Rankings", "⚙️ Admin"],
        key="sidebar_menu"
    )

    # ===== NAVIGATION LOGIC =====
    # If user clicks a sidebar item, change the page
    if menu == "🏠 Home":
        st.session_state.page = "Home"
        st.session_state.selected_comp = None
    elif menu == "📅 Competitions":
        # Only go to Competitions list if we are not currently viewing results
        if st.session_state.page != "Competition Results":
            st.session_state.page = "Competitions"
    elif menu == "🏆 Rankings":
        st.session_state.page = "Overall"
        st.session_state.selected_comp = None
    elif menu == "⚙️ Admin":
        st.session_state.page = "Admin"
        st.session_state.selected_comp = None

    # If we have a selected competition, force the results page
    if st.session_state.selected_comp is not None:
        st.session_state.page = "Competition Results"
    # ============================

    # Render the correct page
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
