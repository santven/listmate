import db_pg
def debug():
    db = db_pg.get_db()
    users = db.execute("SELECT id, name, email, household_id FROM auth_users").fetchall()
    hhs = db.execute("SELECT id, owner_id, is_premium, subscription_status, trial_ends_at FROM auth_households").fetchall()
    members = db.execute("SELECT household_id, count(id) as c FROM auth_users GROUP BY household_id").fetchall()
    
    print("USERS:")
    for u in users:
        print(dict(u))
        
    print("HOUSEHOLDS:")
    for h in hhs:
        print(dict(h))
        
    print("MEMBERS:")
    for m in members:
        print(dict(m))
debug()
