import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import date, timedelta

DB_PATH = Path(__file__).parent / "data" / "krishilink.db"

@contextmanager
def get_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def create_tables():
    with get_db() as db:
        db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,full_name TEXT NOT NULL,phone TEXT,role TEXT NOT NULL,is_active INTEGER DEFAULT 1,is_verified INTEGER DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fpos(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE REFERENCES users(id),name TEXT NOT NULL,district TEXT,state TEXT,registration_number TEXT);
CREATE TABLE IF NOT EXISTS farmers(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE REFERENCES users(id),fpo_id INTEGER REFERENCES fpos(id),village TEXT,district TEXT,land_acres REAL);
CREATE TABLE IF NOT EXISTS buyers(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE REFERENCES users(id),company_name TEXT NOT NULL,business_type TEXT,district TEXT,state TEXT);
CREATE TABLE IF NOT EXISTS crops(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE NOT NULL,variety TEXT,unit TEXT DEFAULT 'Quintal');
CREATE TABLE IF NOT EXISTS buyer_requirements(id INTEGER PRIMARY KEY AUTOINCREMENT,buyer_id INTEGER REFERENCES buyers(id),crop_id INTEGER REFERENCES crops(id),quantity REAL NOT NULL,target_price REAL NOT NULL,required_grade TEXT,max_moisture REAL,delivery_district TEXT,deadline TEXT,notes TEXT,status TEXT NOT NULL,created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS farmer_deposits(id INTEGER PRIMARY KEY AUTOINCREMENT,farmer_id INTEGER REFERENCES farmers(id),crop_id INTEGER REFERENCES crops(id),quantity REAL NOT NULL,available_quantity REAL NOT NULL,quality_self_declared TEXT,status TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS aggregated_lots(id INTEGER PRIMARY KEY AUTOINCREMENT,lot_number TEXT UNIQUE NOT NULL,fpo_id INTEGER REFERENCES fpos(id),requirement_id INTEGER REFERENCES buyer_requirements(id),crop_id INTEGER REFERENCES crops(id),target_quantity REAL,current_quantity REAL DEFAULT 0,status TEXT,created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS lot_contributions(id INTEGER PRIMARY KEY AUTOINCREMENT,lot_id INTEGER REFERENCES aggregated_lots(id),farmer_id INTEGER REFERENCES farmers(id),deposit_id INTEGER REFERENCES farmer_deposits(id),quantity REAL NOT NULL,created_at TEXT,UNIQUE(lot_id,deposit_id));
CREATE TABLE IF NOT EXISTS lot_passports(id INTEGER PRIMARY KEY AUTOINCREMENT,lot_id INTEGER UNIQUE REFERENCES aggregated_lots(id),grade TEXT,moisture_percent REAL,foreign_matter_percent REAL,inspection_notes TEXT,inspector_name TEXT,inspected_at TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS offers(id INTEGER PRIMARY KEY AUTOINCREMENT,lot_id INTEGER REFERENCES aggregated_lots(id),buyer_id INTEGER REFERENCES buyers(id),price_per_quintal REAL,delivery_date TEXT,message TEXT,expires_at TEXT,status TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS deals(id INTEGER PRIMARY KEY AUTOINCREMENT,lot_id INTEGER UNIQUE REFERENCES aggregated_lots(id),offer_id INTEGER REFERENCES offers(id),buyer_id INTEGER REFERENCES buyers(id),fpo_id INTEGER REFERENCES fpos(id),final_price REAL,final_quantity REAL,total_value REAL,delivery_date TEXT,status TEXT,created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS deliveries(id INTEGER PRIMARY KEY AUTOINCREMENT,deal_id INTEGER UNIQUE REFERENCES deals(id),vehicle_number TEXT,driver_name TEXT,dispatch_date TEXT,delivery_date TEXT,status TEXT,notes TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,deal_id INTEGER REFERENCES deals(id),farmer_id INTEGER REFERENCES farmers(id),amount REAL,status TEXT,reference_number TEXT,created_at TEXT,updated_at TEXT,UNIQUE(deal_id,farmer_id));
CREATE TABLE IF NOT EXISTS disputes(id INTEGER PRIMARY KEY AUTOINCREMENT,deal_id INTEGER REFERENCES deals(id),raised_by INTEGER REFERENCES users(id),reason TEXT,description TEXT,status TEXT,resolution TEXT,created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER REFERENCES users(id),message TEXT,type TEXT,is_read INTEGER DEFAULT 0,link TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS activity_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id INTEGER REFERENCES users(id),entity_type TEXT,entity_id INTEGER,action TEXT,old_value TEXT,new_value TEXT,metadata TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS help_articles(id INTEGER PRIMARY KEY AUTOINCREMENT,role TEXT,screen TEXT,step_number INTEGER,title TEXT,description TEXT,image_path TEXT);
""")

def seed_demo(db, hash_password):
    password = hash_password("password123")
    db.execute("INSERT OR IGNORE INTO crops(name,variety) VALUES ('Soybean','JS-335'),('Onion','Nashik Red'),('Wheat','Lokwan'),('Maize','Hybrid'),('Potato','Jyoti')")
    db.execute("INSERT OR IGNORE INTO users(email,password_hash,full_name,role,is_active,is_verified,created_at) VALUES (?,?,?,?,?,?,?)", ("fpo@demo.com", password, "Anita Patil", "FPO", 1, 1, "2026-09-01"))
    fpo_user = db.execute("SELECT id FROM users WHERE email='fpo@demo.com'").fetchone()["id"]
    db.execute("INSERT OR IGNORE INTO fpos(user_id,name,district,state,registration_number) VALUES (?,?,?,?,?)", (fpo_user, "Nashik Agro FPO", "Nashik", "Maharashtra", "FPO-MH-2026-04"))
    fpo_id = db.execute("SELECT id FROM fpos WHERE user_id=?", (fpo_user,)).fetchone()["id"]
    farmer_names = ["Ramesh Shinde","Suresh Jadhav","Priya More","Kavita Pawar","Ganesh Wagh","Meena Chavan","Vilas Borse","Asha Gaikwad","Dinesh Salve","Sunita Kute"]
    for i, name in enumerate(farmer_names):
        email = f"farmer{i+1}@demo.com"
        db.execute("INSERT OR IGNORE INTO users(email,password_hash,full_name,role,is_active,is_verified,created_at) VALUES (?,?,?,?,?,?,?)", (email, password, name, "FARMER", 1, 1, "2026-09-01"))
        uid = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO farmers(user_id,fpo_id,village,district,land_acres) VALUES (?,?,?,?,?)", (uid, fpo_id, "Nashik village", "Nashik", 3 + i))
    for email, name, company, verified in [("buyer@demo.com","Arjun Mehta","FreshMart Foods",1),("procurement@demo.com","Neha Shah","AgroPro Industries",1),("exports@demo.com","Kabir Rao","Bharat Exports",0)]:
        db.execute("INSERT OR IGNORE INTO users(email,password_hash,full_name,role,is_active,is_verified,created_at) VALUES (?,?,?,?,?,?,?)", (email, password, name, "BUYER", 1, verified, "2026-09-01"))
        uid = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO buyers(user_id,company_name,business_type,district,state) VALUES (?,?,?,?,?)", (uid, company, "processor", "Nashik", "Maharashtra"))
    db.execute("INSERT OR IGNORE INTO users(email,password_hash,full_name,role,is_active,is_verified,created_at) VALUES (?,?,?,?,?,?,?)", ("admin@demo.com", password, "KrishiLink Admin", "ADMIN", 1, 1, "2026-09-01"))
    soybean = db.execute("SELECT id FROM crops WHERE name='Soybean'").fetchone()["id"]
    onion = db.execute("SELECT id FROM crops WHERE name='Onion'").fetchone()["id"]
    farmers = db.execute("SELECT id FROM farmers ORDER BY id").fetchall()
    amounts = [20, 25, 15, 18, 30, 22, 16, 12, 20, 14]
    for farmer, amount in zip(farmers, amounts):
        if not db.execute("SELECT id FROM farmer_deposits WHERE farmer_id=? AND crop_id=?", (farmer["id"], soybean)).fetchone():
            db.execute("INSERT INTO farmer_deposits(farmer_id,crop_id,quantity,available_quantity,quality_self_declared,status,created_at) VALUES (?,?,?,?,?,?,?)", (farmer["id"], soybean, amount, amount, "GOOD" if amount >= 18 else "AVERAGE", "AVAILABLE", "2026-09-02"))
    if not db.execute("SELECT id FROM farmer_deposits WHERE crop_id=?", (onion,)).fetchone():
        db.execute("INSERT INTO farmer_deposits(farmer_id,crop_id,quantity,available_quantity,quality_self_declared,status,created_at) VALUES (?,?,?,?,?,?,?)", (farmers[0]["id"], onion, 60, 60, "GOOD", "AVAILABLE", "2026-09-03"))
    buyer_id = db.execute("SELECT id FROM buyers WHERE company_name='FreshMart Foods'").fetchone()["id"]
    if not db.execute("SELECT id FROM buyer_requirements LIMIT 1").fetchone():
        db.execute("INSERT INTO buyer_requirements(buyer_id,crop_id,quantity,target_price,required_grade,max_moisture,delivery_district,deadline,notes,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (buyer_id, soybean, 100, 4600, "A", 13, "Nashik", (date.today()+timedelta(days=9)).isoformat(), "Institutional procurement for October processing.", "PUBLISHED", "2026-09-04", "2026-09-04"))
        db.execute("INSERT INTO buyer_requirements(buyer_id,crop_id,quantity,target_price,required_grade,max_moisture,delivery_district,deadline,notes,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (buyer_id, onion, 50, 2200, "A", 14, "Pune", (date.today()+timedelta(days=14)).isoformat(), "Clean sorted onions.", "PUBLISHED", "2026-09-04", "2026-09-04"))
        req = db.execute("SELECT id FROM buyer_requirements WHERE crop_id=?", (soybean,)).fetchone()["id"]
        db.execute("INSERT INTO aggregated_lots(lot_number,fpo_id,requirement_id,crop_id,target_quantity,current_quantity,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", ("KL-2026-0001", fpo_id, req, soybean, 100, 108, "INSPECTED", "2026-09-05", "2026-09-06"))
        lot_id = db.execute("SELECT id FROM aggregated_lots WHERE lot_number='KL-2026-0001'").fetchone()["id"]
        for farmer, qty in zip(farmers[:5], [20,25,15,18,30]):
            dep = db.execute("SELECT id FROM farmer_deposits WHERE farmer_id=? AND crop_id=?", (farmer["id"], soybean)).fetchone()
            db.execute("UPDATE farmer_deposits SET available_quantity=available_quantity-?,status='RESERVED' WHERE id=?", (qty, dep["id"]))
            db.execute("INSERT INTO lot_contributions(lot_id,farmer_id,deposit_id,quantity,created_at) VALUES(?,?,?,?,?)", (lot_id, farmer["id"], dep["id"], qty, "2026-09-05"))
        db.execute("INSERT INTO lot_passports(lot_id,grade,moisture_percent,foreign_matter_percent,inspection_notes,inspector_name,inspected_at,created_at) VALUES(?,?,?,?,?,?,?,?)", (lot_id, "A", 12.4, 1.2, "Clean pooled lot, manual FPO inspection.", "Anita Patil", "2026-09-06", "2026-09-06"))
        buyer2 = db.execute("SELECT id FROM buyers WHERE company_name='AgroPro Industries'").fetchone()["id"]
        db.execute("INSERT INTO offers(lot_id,buyer_id,price_per_quintal,delivery_date,message,expires_at,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (lot_id, buyer_id, 4650, (date.today()+timedelta(days=7)).isoformat(), "We can receive at our Nashik facility.", (date.today()+timedelta(days=3)).isoformat(), "OPEN", "2026-09-07"))
        db.execute("INSERT INTO offers(lot_id,buyer_id,price_per_quintal,delivery_date,message,expires_at,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (lot_id, buyer2, 4700, (date.today()+timedelta(days=8)).isoformat(), "Fast settlement after weighment.", (date.today()+timedelta(days=3)).isoformat(), "OPEN", "2026-09-07"))
        req2 = db.execute("SELECT id FROM buyer_requirements WHERE crop_id=? AND id<>?", (soybean, req)).fetchone()
        if req2:
            pass
    help_rows = [("FARMER","crop",1,"Choose your crop","Tap the crop you have ready to sell through your FPO.",""),("FARMER","crop",2,"Enter the amount","Use the plus and minus buttons, then choose a simple quality level.",""),("FARMER","crop",3,"Save to FPO","Press Save to FPO. Your crop is now visible to the FPO manager.",""),("FPO","lot",1,"Build a lot","Open a matching requirement and add available farmer deposits.",""),("FPO","lot",2,"Inspect the lot","When the target is reached, record the manual grade and moisture check.",""),("BUYER","requirement",1,"Post demand","Describe the crop, quantity, quality and deadline you need.","")]
    for row in help_rows:
        db.execute("INSERT OR IGNORE INTO help_articles(role,screen,step_number,title,description,image_path) VALUES(?,?,?,?,?,?)", row)
    if not db.execute("SELECT id FROM notifications LIMIT 1").fetchone():
        farmer_user = db.execute("SELECT user_id FROM farmers ORDER BY id LIMIT 1").fetchone()["user_id"]
        db.execute("INSERT INTO notifications(user_id,message,type,is_read,created_at) VALUES(?,?,?,?,?)", (farmer_user, "Your farmer account is ready. Add a crop to start.", "success", 0, "2026-09-04"))
        db.execute("INSERT INTO notifications(user_id,message,type,is_read,created_at) VALUES(?,?,?,?,?)", (fpo_user, "A buyer requirement for Soybean is ready to match.", "info", 0, "2026-09-04"))
        db.execute("INSERT INTO notifications(user_id,message,type,is_read,created_at) VALUES(?,?,?,?,?)", (db.execute("SELECT user_id FROM buyers WHERE id=?", (buyer_id,)).fetchone()["user_id"], "Your demand has a verified lot available.", "success", 0, "2026-09-06"))