from io import BytesIO
import pandas as pd
from database import get_connection, list_students, get_snapshots, get_weekly_progress, get_monthly_progress, get_badge_for_progress


def create_excel_bytes():
    students = pd.DataFrame(list_students())
    snapshots = get_snapshots()
    if students.empty:
        students = pd.DataFrame(columns=["student_id", "name", "username", "profile_url", "batch"])
    students["Student"] = students.get("name", pd.Series(dtype=str)).fillna("").where(students.get("name", pd.Series(dtype=str)).fillna("").str.strip() != "", students.get("username", pd.Series(dtype=str)))
    if not snapshots.empty:
        latest = snapshots.sort_values("snapshot_date").groupby("student_id", as_index=False).tail(1)[["student_id", "total_solved", "snapshot_date"]]
        students = students.merge(latest, on="student_id", how="left")
    else:
        students["total_solved"] = pd.NA
        students["snapshot_date"] = pd.NA
    students["Weekly Progress"] = students["student_id"].apply(get_weekly_progress)
    students["Monthly Progress"] = students["student_id"].apply(get_monthly_progress)
    students["Previous Month Badge"] = students["student_id"].apply(lambda sid: get_badge_for_progress(get_monthly_progress(sid, previous_month=True)))
    students = students.rename(columns={"batch": "Batch", "username": "LeetCode Username", "profile_url": "Profile URL", "total_solved": "All-time Distinct Solved", "snapshot_date": "Last Snapshot"})
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        overall = students.sort_values("All-time Distinct Solved", ascending=False, na_position="last")
        overall.to_excel(writer, sheet_name="Overall Leaderboard", index=False)
        students.sort_values("Weekly Progress", ascending=False, na_position="last").to_excel(writer, sheet_name="Weekly Leaderboard", index=False)
        students.sort_values("Monthly Progress", ascending=False, na_position="last").to_excel(writer, sheet_name="Monthly Leaderboard", index=False)
        if not snapshots.empty:
            snapshots.to_excel(writer, sheet_name="Daily Snapshots", index=False)
        batch_cols = [c for c in ["Batch", "All-time Distinct Solved", "Weekly Progress", "Monthly Progress"] if c in students.columns]
        if "Batch" in students.columns:
            students.groupby("Batch", dropna=False)[["All-time Distinct Solved", "Weekly Progress", "Monthly Progress"]].sum(numeric_only=True).reset_index().to_excel(writer, sheet_name="Batch Reports", index=False)
        with get_connection() as conn:
            errors = pd.read_sql_query("SELECT attempted_at, username, error_message FROM fetch_errors ORDER BY attempted_at DESC", conn)
        errors.to_excel(writer, sheet_name="Fetch Errors", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for column_cells in ws.columns:
                max_len = min(max((len(str(cell.value or "")) for cell in column_cells), default=10) + 2, 48)
                ws.column_dimensions[column_cells[0].column_letter].width = max(12, max_len)
    output.seek(0)
    return output.getvalue()
