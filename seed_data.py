from database import create_tables, get_db, seed_demo
from main import hash_password
create_tables()
with get_db() as db:
    seed_demo(db, hash_password)
print("KrishiLink demo data is ready.")