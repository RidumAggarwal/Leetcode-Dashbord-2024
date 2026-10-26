import os
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st
from database import init_db, get_connection, list_students, get_snapshots, get_latest_snapshot_date, get_monthly_progress, get_weekly_progress, get_badge_for_progress
from leetcode_collector import collect_all_students
from export_excel import create_excel_bytes

st.set_page_config(page_title="LeetCode Progress Dashboard", page_icon="🏆", layout="wide")
init_db()

st.title("🏆 LeetCode Student Progress Dashboard")
st.caption("All-time distinct solved problems · Sunday-to-Sunday weekly progress · Calendar-month progress")

with st.sidebar:
    st.header("Controls")
    if st.button("🔄 Fetch latest LeetCode totals", use_container_width=True):
        with st.spinner("Fetching public profile totals…"):
            result = collect_all_students()
        st.success(f"Fetch finished: {result['success']} successful, {result['failed']} failed.")
        if result['failed']:
            st.warning("Some profiles could not be fetched. Their scores were not changed; see Fetch Errors.")
        st.rerun()
    st.divider()
    st.write("**Scoring rules**")
    st.write("• All-time = latest distinct problems solved")
    st.write("• Weekly = current total − previous Sunday baseline")
    st.write("• Monthly = current total − month-start baseline")
    st.write("• A failed fetch never becomes zero")

students = list_students()
if not students:
    st.info("Start by adding students to `students.csv`. A template is included in the project folder. Then run `python leetcode_collector.py` or use the fetch button.")
    st.stop()

snapshots = get_snapshots()
if snapshots.empty:
    st.warning("No successful snapshots yet. Use **Fetch latest LeetCode totals** to collect the first baseline.")

student_df = pd.DataFrame(students)
student_df["display_name"] = student_df["name"].fillna("").where(student_df["name"].fillna("").str.strip() != "", student_df["username"])

# Latest known total per student, based only on successful snapshots.
if not snapshots.empty:
    latest = snapshots.sort_values("snapshot_date").groupby("student_id", as_index=False).tail(1)
    latest = latest[["student_id", "total_solved", "snapshot_date"]].rename(columns={"snapshot_date": "last_updated"})
    student_df = student_df.merge(latest, on="student_id", how="left")
else:
    student_df["total_solved"] = pd.NA
    student_df["last_updated"] = pd.NA

student_df["total_solved"] = pd.to_numeric(student_df["total_solved"], errors="coerce")
student_df["weekly_progress"] = student_df["student_id"].apply(get_weekly_progress)
student_df["monthly_progress"] = student_df["student_id"].apply(get_monthly_progress)
student_df["monthly_badge"] = student_df["student_id"].apply(lambda sid: get_badge_for_progress(get_monthly_progress(sid, previous_month=True)))

known = student_df[student_df["total_solved"].notna()]
col1, col2, col3, col4 = st.columns(4)
col1.metric("Students", len(student_df))
col2.metric("Profiles fetched", len(known))
col3.metric("Total distinct solves", f"{int(known['total_solved'].sum()):,}" if not known.empty else "—")
col4.metric("Last successful snapshot", str(get_latest_snapshot_date() or "Not yet"))

st.subheader("Leaderboard")
tab_overall, tab_weekly, tab_monthly, tab_batches, tab_errors = st.tabs(["Overall", "This Week", "This Month", "Batches & Groups", "Fetch Errors"])

batch_options = ["All batches"] + sorted([b for b in student_df["batch"].fillna("").unique() if b.strip()])
with st.container():
    selected_batch = st.selectbox("Filter by existing batch", batch_options)
filtered = student_df if selected_batch == "All batches" else student_df[student_df["batch"] == selected_batch]

def leaderboard(df, metric, title):
    out = df.copy()
    out[metric] = pd.to_numeric(out[metric], errors="coerce")
    out = out.sort_values([metric, "display_name"], ascending=[False, True], na_position="last")
    out.insert(0, "Rank", range(1, len(out) + 1))
    out = out.rename(columns={"display_name": "Student", "batch": "Batch", "username": "LeetCode Username", "total_solved": "All-time Solved", "weekly_progress": "Weekly New", "monthly_progress": "Monthly New", "monthly_badge": "Previous Month Badge", "last_updated": "Last Updated"})
    cols = [c for c in ["Rank", "Student", "Batch", "LeetCode Username", "All-time Solved", "Weekly New", "Monthly New", "Previous Month Badge", "Last Updated"] if c in out.columns]
    st.dataframe(out[cols], use_container_width=True, hide_index=True)

with tab_overall:
    leaderboard(filtered, "total_solved", "Overall")
with tab_weekly:
    st.caption("Weekly progress is measured against the most recent Sunday baseline. If a Sunday snapshot was missed, the last available snapshot on or before the baseline date is used.")
    leaderboard(filtered, "weekly_progress", "Weekly")
with tab_monthly:
    st.caption("Monthly progress is measured against the last successful snapshot before the current calendar month began.")
    leaderboard(filtered, "monthly_progress", "Monthly")
with tab_batches:
    batch_summary = student_df.groupby("batch", dropna=False).agg(Students=("student_id", "count"), Total_Solved=("total_solved", "sum"), Weekly_New=("weekly_progress", "sum"), Monthly_New=("monthly_progress", "sum")).reset_index().rename(columns={"batch": "Batch", "Total_Solved": "All-time solved", "Weekly_New": "Weekly new", "Monthly_New": "Monthly new"})
    st.markdown("**Existing batch comparison**")
    st.dataframe(batch_summary, use_container_width=True, hide_index=True)
    st.markdown("**Performance groups**")
    st.write("Groups are derived from monthly progress: **Top Performers** (top 10%), **Progressing** (positive progress outside the top 10%), and **Needs Attention** (zero progress or no verified snapshot). Use this as a coaching signal, not as a judgment of student ability.")
    ranked = student_df.copy().sort_values("monthly_progress", ascending=False, na_position="last")
    top_n = max(1, int(len(ranked) * 0.10)) if len(ranked) else 0
    ranked["Performance Group"] = "Progressing"
    if top_n:
        ranked.iloc[:top_n, ranked.columns.get_loc("Performance Group")] = "Top Performers"
    ranked.loc[(ranked["monthly_progress"].fillna(0) <= 0) | ranked["total_solved"].isna(), "Performance Group"] = "Needs Attention"
    st.dataframe(ranked[["display_name", "batch", "total_solved", "weekly_progress", "monthly_progress", "Performance Group"]].rename(columns={"display_name": "Student", "batch": "Batch", "total_solved": "All-time solved", "weekly_progress": "Weekly new", "monthly_progress": "Monthly new"}), use_container_width=True, hide_index=True)
    st.markdown("**Monthly badges (based on previous month's progress)**")
    st.caption("Starter thresholds: Bronze 0–9, Silver 10–19, Gold 20–39, Platinum 40+. You can change these in `database.py`.")
    st.dataframe(student_df[["display_name", "batch", "monthly_badge"]].rename(columns={"display_name": "Student", "batch": "Batch", "monthly_badge": "Badge"}), use_container_width=True, hide_index=True)
with tab_errors:
    conn = get_connection()
    errors = pd.read_sql_query("SELECT attempted_at, username, error_message FROM fetch_errors ORDER BY attempted_at DESC LIMIT 500", conn)
    conn.close()
    if errors.empty:
        st.success("No fetch errors recorded.")
    else:
        st.dataframe(errors, use_container_width=True, hide_index=True)

st.divider()
col_a, col_b = st.columns([1, 3])
with col_a:
    if st.button("📥 Prepare Excel report", use_container_width=True):
        st.session_state["excel_bytes"] = create_excel_bytes()
with col_b:
    if "excel_bytes" in st.session_state:
        st.download_button("Download LeetCode Progress Report.xlsx", data=st.session_state["excel_bytes"], file_name=f"leetcode_progress_{date.today().isoformat()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.caption("Data source: publicly accessible LeetCode profile totals. Historical period progress begins from the first available baseline; earlier monthly/weekly history cannot be reconstructed unless snapshots exist.")
