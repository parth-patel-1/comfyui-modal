"""One-off: delete leftover manual_* test users from failed check runs."""
import psycopg

env = dict(
    l.split("=", 1) for l in open("backend/.env").read().splitlines() if "=" in l
)
conn = psycopg.connect(env["DB_URL"])
cur = conn.cursor()
cur.execute("delete from auth.users where email like 'manual%@genstudio.dev'")
print("deleted leftover:", cur.rowcount)
conn.commit()
conn.close()

