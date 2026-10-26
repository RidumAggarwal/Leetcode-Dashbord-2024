"""Collect public LeetCode profile solved counts. Run daily or from the dashboard."""
import json
import re
import sys
import time
from pathlib import Path

import requests

from database import init_db, sync_roster, list_students, record_snapshot, record_error

GRAPHQL_URL = "https://leetcode.com/graphql/"
QUERY = """
query userProblemsSolved($username: String!) {
  matchedUser(username: $username) {
    username
    submitStats {
      acSubmissionNum { difficulty count }
    }
  }
}
"""
HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com/",
    "User-Agent": "Mozilla/5.0 (compatible; StudentProgressTracker/1.0; educational dashboard)"
}


def normalize_username(raw):
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "leetcode.com" in raw:
        match = re.search(r"leetcode\.com/(?:u/)?([^/?#]+)/?", raw, re.I)
        if match:
            return match.group(1)
    return raw.lstrip("@").strip("/")


def fetch_profile(username, timeout=20):
    payload = {"query": QUERY, "variables": {"username": username}, "operationName": "userProblemsSolved"}
    response = requests.post(GRAPHQL_URL, headers=HEADERS, json=payload, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"LeetCode returned HTTP {response.status_code}")
    try:
        data = response.json()
    except json.JSONDecodeError:
        raise RuntimeError("LeetCode response was not valid JSON (possible rate limit or anti-bot response)")
    if data.get("errors"):
        raise RuntimeError("LeetCode GraphQL error: " + "; ".join(str(e.get("message", e)) for e in data["errors"]))
    matched = (data.get("data") or {}).get("matchedUser")
    if not matched:
        raise RuntimeError("Profile not found or profile data is not publicly accessible")
    counts = {x.get("difficulty", ""): int(x.get("count", 0)) for x in ((matched.get("submitStats") or {}).get("acSubmissionNum") or [])}
    # The public profile's accepted problem count is the distinct solved count, not submission volume.
    if "All" not in counts:
        raise RuntimeError("Profile response did not include the total accepted-problem count")
    return {"total": counts["All"], "easy": counts.get("Easy"), "medium": counts.get("Medium"), "hard": counts.get("Hard")}


def collect_all_students():
    init_db()
    sync_roster()
    students = list_students()
    success = failed = 0
    for index, student in enumerate(students):
        username = normalize_username(student.get("username") or student.get("profile_url"))
        try:
            stats = fetch_profile(username)
            record_snapshot(student["student_id"], stats["total"], stats["easy"], stats["medium"], stats["hard"])
            print(f"OK {username}: {stats['total']} distinct solved")
            success += 1
        except Exception as exc:
            record_error(student["student_id"], username, exc)
            print(f"ERROR {username}: {exc}", file=sys.stderr)
            failed += 1
        # Small delay to avoid hammering LeetCode, especially for large batches.
        if index < len(students) - 1:
            time.sleep(1.2)
    return {"success": success, "failed": failed, "total": len(students)}


if __name__ == "__main__":
    result = collect_all_students()
    print(f"Finished: {result['success']} successful, {result['failed']} failed out of {result['total']} profiles")
    sys.exit(1 if result["failed"] else 0)
