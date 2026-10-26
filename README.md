# LeetCode Student Progress Tracker

A first working version of a universal LeetCode dashboard for ADSA/DSA trainers. It tracks current distinct solved-problem totals, daily snapshots, weekly progress, monthly progress, monthly badges, batch comparisons, performance groups, and fetch errors.

## How scoring works

- **All-time total:** the distinct problems-solved total shown by the student's public LeetCode profile.
- **Weekly progress:** latest successful total minus the latest snapshot on or before the previous Sunday.
- **Monthly progress:** latest successful total minus the latest snapshot before the current calendar month began.
- **Monthly badge:** assigned from the previous month's progress: Bronze 0–9, Silver 10–19, Gold 20–39, Platinum 40+.
- A repeated accepted submission for an already-solved problem should not increase the public distinct-problem total.
- Failed profile fetches are logged and do not overwrite a student's score with zero.

The app uses daily snapshots. It cannot reconstruct weekly/monthly progress from before the first snapshot was recorded. For a fresh deployment, first successful collection establishes the starting baseline.

## 1. Prepare the roster

Edit `students.csv` in this folder. Keep these exact columns:

```csv
name,username,profile_url,batch
Aarav,aarav123,https://leetcode.com/u/aarav123/,ADSA-A
Diya,diya456,https://leetcode.com/u/diya456/,ADSA-B
```

Use one row per student. The `username` is the LeetCode username, not a display name. You can leave `name` blank if needed. Replace or delete the example row before collecting real data.

## 2. Run locally for the first test

Python 3.10+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# On Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python leetcode_collector.py
streamlit run app.py
```

Open the local Streamlit URL shown in the terminal. The database is stored in `tracker.db` next to the code by default. Keep backups of this file because it contains snapshot history.

## 3. Daily automation

Run `python leetcode_collector.py` once per day. For a cloud deployment, use a persistent host (e.g. a small VPS or a platform with a persistent disk). Set `TRACKER_DB_PATH` to a path on that persistent disk. Do **not** run a daily collector on ephemeral storage unless snapshots are written to persistent storage, or history will be lost.

The Streamlit dashboard's fetch button can also run a collection on demand. For a larger batch, schedule collection during a quiet period and keep request rates conservative. LeetCode may rate-limit or block automated requests; the collector records these failures rather than assuming zero progress.

## 4. Cloud deployment checklist

1. Create a private GitHub repository and push this folder.
2. Deploy `app.py` to a Python host that supports Streamlit and persistent storage.
3. Attach a persistent disk and set `TRACKER_DB_PATH` to its mounted path.
4. Schedule `python leetcode_collector.py` daily on a machine/job that can access the same persistent database.
5. Back up `tracker.db` regularly.
6. Keep the repository private because the roster contains student identifiers.

A simple scheduled GitHub Actions job alone is **not** enough for durable history if it runs on a fresh ephemeral runner each day. Use a persistent database/disk or a managed PostgreSQL service for production.

## Known limitations in this initial version

- LeetCode does not guarantee unrestricted access to its public GraphQL endpoint. Validate a few real profiles before onboarding the full batch. If access is blocked, do not repeatedly retry aggressively; choose an approved data source or adapt the collector.
- The collector reads public profile totals (unique problems solved), not every submission event. This fits snapshot-difference scoring but cannot determine exact solve dates for older problems.
- Weekly/monthly progress is reliable only from available snapshots. If a Sunday or month-boundary snapshot is missed, the app uses the last available baseline before that boundary.
- Counts are clamped to zero for progress if the public profile total decreases; the all-time total shown is still the latest fetched profile total.
- Badge thresholds are starter defaults and can be edited in `database.py`.
