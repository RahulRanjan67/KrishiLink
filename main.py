import os
import sqlite3
import hashlib
import secrets
from contextlib import contextmanager, asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field, ValidationError
from dotenv import load_dotenv
from database import DB_PATH, create_tables, seed_demo, get_db
from services import calculate_match_score, add_contribution, transition_lot, calculate_net, create_payouts, notify

APP_DIR = Path(__file__).parent
load_dotenv(APP_DIR / ".env")
BASE_PATH = os.getenv("BASE_PATH", "/api").rstrip("/")
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is required. Copy .env.example to .env and set a long random value.")
if len(SESSION_SECRET) < 32:
    raise RuntimeError("SESSION_SECRET must be at least 32 characters long.")

@asynccontextmanager
async def lifespan(app):
    create_tables()
    with get_db() as db:
        if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            seed_demo(db, hash_password)
    yield

app = FastAPI(title="KrishiLink API", description="Demand-driven procurement and aggregation platform", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=60 * 60 * 24 * 7)
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals["base_path"] = BASE_PATH
app.mount(f"{BASE_PATH}/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

class RequirementInput(BaseModel):
    crop_id: int
    quantity: float = Field(gt=0, le=100000)
    target_price: float = Field(gt=0)
    required_grade: str
    max_moisture: float = Field(ge=0, le=100)
    delivery_district: str
    deadline: date
    notes: str = ""

class DepositInput(BaseModel):
    crop_id: int
    quantity: float = Field(gt=0, le=100000)
    quality: str

def now():
    return datetime.now().isoformat(timespec="seconds")

def hash_password(password):
    salt = secrets.token_hex(16)
    return f"{salt}${hashlib.sha256((salt + password).encode()).hexdigest()}"

def verify_password(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        return hashlib.sha256((salt + password).encode()).hexdigest() == digest
    except ValueError:
        return False

def flash(request, message, kind="info"):
    request.session["flash"] = {"message": message, "kind": kind}

def current_user(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with get_db() as db:
        row = db.execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)).fetchone()
        return dict(row) if row else None

def page(request, template, **context):
    user = current_user(request)
    context.update({"request": request, "user": user, "base_path": BASE_PATH, "today": date.today().isoformat()})
    context["flash"] = request.session.pop("flash", None)
    return templates.TemplateResponse(request=request, name=template, context=context)

def require_role(request, roles):
    user = current_user(request)
    if not user:
        return None, RedirectResponse(f"{BASE_PATH}/login", status_code=303)
    if user["role"] not in roles:
        return user, page(request, "error.html", title="Access denied", message="This area is not available for your role.")
    return user, None

def redirect_dashboard(user):
    paths = {"FARMER": "/farmer", "FPO": "/fpo", "BUYER": "/buyer", "ADMIN": "/admin"}
    return RedirectResponse(f"{BASE_PATH}{paths.get(user['role'], '/login')}", status_code=303)

@app.get(f"{BASE_PATH}/healthz")
def health():
    return {"status": "ok", "app": "KrishiLink"}

@app.get(BASE_PATH, response_class=HTMLResponse)
@app.get(f"{BASE_PATH}/", response_class=HTMLResponse)
def home(request: Request):
    user = current_user(request)
    return redirect_dashboard(user) if user else RedirectResponse(f"{BASE_PATH}/login", status_code=303)

@app.get(f"{BASE_PATH}/login", response_class=HTMLResponse)
def login_page(request: Request):
    return page(request, "login.html")

@app.post(f"{BASE_PATH}/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    if not user or not verify_password(password, user["password_hash"]):
        return page(request, "login.html", error="Email or password is incorrect.", entered_email=email)
    request.session["user_id"] = user["id"]
    flash(request, f"Welcome back, {user['full_name'].split()[0]}.", "success")
    return redirect_dashboard(dict(user))

@app.get(f"{BASE_PATH}/register", response_class=HTMLResponse)
def register_page(request: Request):
    return page(request, "register.html")

@app.post(f"{BASE_PATH}/register", response_class=HTMLResponse)
def register(request: Request, full_name: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form(...), company_name: str = Form(""), district: str = Form("Nashik")):
    role = role.upper()
    if role not in {"FARMER", "BUYER"} or len(password) < 6:
        return page(request, "register.html", error="Choose Farmer or Buyer and use a password with at least 6 characters.")
    with get_db() as db:
        if db.execute("SELECT id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone():
            return page(request, "register.html", error="An account with this email already exists.")
        cur = db.execute("INSERT INTO users(email, password_hash, full_name, role, is_active, is_verified, created_at) VALUES (?, ?, ?, ?, 1, ?, ?)", (email.strip().lower(), hash_password(password), full_name.strip(), role, 1 if role == "FARMER" else 0, now()))
        user_id = cur.lastrowid
        if role == "FARMER":
            fpo = db.execute("SELECT id FROM fpos LIMIT 1").fetchone()
            db.execute("INSERT INTO farmers(user_id, fpo_id, village, district) VALUES (?, ?, ?, ?)", (user_id, fpo["id"] if fpo else None, "New village", district))
        else:
            db.execute("INSERT INTO buyers(user_id, company_name, business_type, district, state) VALUES (?, ?, ?, ?, ?)", (user_id, company_name or full_name, "processor", district, "Maharashtra"))
    flash(request, "Account created. You can now sign in.", "success")
    return RedirectResponse(f"{BASE_PATH}/login", status_code=303)

@app.get(f"{BASE_PATH}/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(f"{BASE_PATH}/login", status_code=303)

@app.get(f"{BASE_PATH}/farmer", response_class=HTMLResponse)
def farmer_home(request: Request):
    user, denied = require_role(request, {"FARMER"})
    if denied: return denied
    with get_db() as db:
        farmer = db.execute("SELECT * FROM farmers WHERE user_id = ?", (user["id"],)).fetchone()
        deposits = db.execute("SELECT d.*, c.name crop_name FROM farmer_deposits d JOIN crops c ON c.id=d.crop_id WHERE d.farmer_id=? ORDER BY d.created_at DESC", (farmer["id"],)).fetchall()
        payments = db.execute("SELECT p.*, c.name crop_name FROM payments p JOIN deals de ON de.id=p.deal_id JOIN aggregated_lots l ON l.id=de.lot_id JOIN crops c ON c.id=l.crop_id WHERE p.farmer_id=? ORDER BY p.created_at DESC", (farmer["id"],)).fetchall()
    return page(request, "farmer/home.html", farmer=farmer, deposits=deposits, payments=payments)

@app.get(f"{BASE_PATH}/farmer/crops", response_class=HTMLResponse)
def farmer_crops(request: Request):
    user, denied = require_role(request, {"FARMER"})
    if denied: return denied
    with get_db() as db:
        crops = db.execute("SELECT * FROM crops ORDER BY name").fetchall()
    return page(request, "farmer/crops.html", crops=crops)

@app.post(f"{BASE_PATH}/farmer/crops")
def add_crop(request: Request, crop_id: int = Form(...), quantity: str = Form(...), quality: str = Form(...)):
    user, denied = require_role(request, {"FARMER"})
    if denied: return denied
    try:
        data = DepositInput(crop_id=crop_id, quantity=float(quantity), quality=quality)
    except (ValueError, ValidationError):
        flash(request, "Please enter a quantity greater than zero.", "danger")
        return RedirectResponse(f"{BASE_PATH}/farmer/crops", status_code=303)
    with get_db() as db:
        farmer = db.execute("SELECT id FROM farmers WHERE user_id=?", (user["id"],)).fetchone()
        if not db.execute("SELECT id FROM crops WHERE id=?", (data.crop_id,)).fetchone():
            flash(request, "Please choose a valid crop.", "danger")
            return RedirectResponse(f"{BASE_PATH}/farmer/crops", status_code=303)
        db.execute("INSERT INTO farmer_deposits(farmer_id,crop_id,quantity,available_quantity,quality_self_declared,status,created_at) VALUES(?,?,?,?,?,'AVAILABLE',?)", (farmer["id"], data.crop_id, data.quantity, data.quantity, data.quality.upper(), now()))
        db.execute("INSERT INTO activity_logs(actor_id,entity_type,action,new_value,created_at) VALUES(?,?,?,?,?)", (user["id"], "deposit", "created", str(data.quantity), now()))
    flash(request, "Your crop was saved to the FPO inventory.", "success")
    return RedirectResponse(f"{BASE_PATH}/farmer", status_code=303)

@app.get(f"{BASE_PATH}/farmer/lots", response_class=HTMLResponse)
def farmer_lots(request: Request):
    user, denied = require_role(request, {"FARMER"})
    if denied: return denied
    with get_db() as db:
        farmer = db.execute("SELECT id FROM farmers WHERE user_id=?", (user["id"],)).fetchone()
        rows = db.execute("SELECT l.*, c.name crop_name, lc.quantity contribution_qty FROM lot_contributions lc JOIN aggregated_lots l ON l.id=lc.lot_id JOIN crops c ON c.id=l.crop_id WHERE lc.farmer_id=? ORDER BY l.updated_at DESC", (farmer["id"],)).fetchall()
    return page(request, "farmer/lots.html", lots=rows)

@app.get(f"{BASE_PATH}/farmer/sales", response_class=HTMLResponse)
def farmer_sales(request: Request):
    user, denied = require_role(request, {"FARMER"})
    if denied: return denied
    with get_db() as db:
        farmer = db.execute("SELECT id FROM farmers WHERE user_id=?", (user["id"],)).fetchone()
        rows = db.execute("SELECT p.*, l.lot_number, c.name crop_name FROM payments p JOIN deals d ON d.id=p.deal_id JOIN aggregated_lots l ON l.id=d.lot_id JOIN crops c ON c.id=l.crop_id WHERE p.farmer_id=? ORDER BY p.created_at DESC", (farmer["id"],)).fetchall()
    return page(request, "farmer/sales.html", payments=rows)

@app.get(f"{BASE_PATH}/fpo", response_class=HTMLResponse)
def fpo_home(request: Request):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        fpo = db.execute("SELECT * FROM fpos WHERE user_id=?", (user["id"],)).fetchone()
        stats = {
            "farmers": db.execute("SELECT COUNT(*) n FROM farmers WHERE fpo_id=?", (fpo["id"],)).fetchone()["n"],
            "supply": db.execute("SELECT COALESCE(SUM(available_quantity),0) n FROM farmer_deposits WHERE status IN ('AVAILABLE','RESERVED')").fetchone()["n"],
            "lots": db.execute("SELECT COUNT(*) n FROM aggregated_lots WHERE fpo_id=?", (fpo["id"],)).fetchone()["n"],
            "ready": db.execute("SELECT COUNT(*) n FROM aggregated_lots WHERE fpo_id=? AND status IN ('INSPECTED','OFFER_PENDING')", (fpo["id"],)).fetchone()["n"],
            "offers": db.execute("SELECT COUNT(*) n FROM offers o JOIN aggregated_lots l ON l.id=o.lot_id WHERE l.fpo_id=? AND o.status='OPEN'", (fpo["id"],)).fetchone()["n"],
            "disputes": db.execute("SELECT COUNT(*) n FROM disputes WHERE status='OPEN'").fetchone()["n"],
        }
        opportunities = db.execute("SELECT r.*, c.name crop_name, COALESCE((SELECT SUM(d.available_quantity) FROM farmer_deposits d JOIN farmers f ON f.id=d.farmer_id JOIN fpos fp ON fp.id=f.fpo_id WHERE fp.id=? AND d.crop_id=r.crop_id),0) supply FROM buyer_requirements r JOIN crops c ON c.id=r.crop_id WHERE r.status IN ('PUBLISHED','MATCHING') ORDER BY r.deadline", (fpo["id"],)).fetchall()
    opportunities = [dict(row) for row in opportunities]
    for row in opportunities:
        row["match_score"] = calculate_match_score(row, row["supply"], "Nashik")
    return page(request, "fpo/home.html", fpo=fpo, stats=stats, opportunities=opportunities)

@app.get(f"{BASE_PATH}/fpo/requirements", response_class=HTMLResponse)
def fpo_requirements(request: Request):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        fpo = db.execute("SELECT id FROM fpos WHERE user_id=?", (user["id"],)).fetchone()
        rows = db.execute("SELECT r.*, c.name crop_name, b.company_name FROM buyer_requirements r JOIN crops c ON c.id=r.crop_id JOIN buyers b ON b.id=r.buyer_id WHERE r.status NOT IN ('CANCELLED','CLOSED') ORDER BY r.deadline").fetchall()
    rows = [dict(row) for row in rows]
    for row in rows:
        with get_db() as db:
            supply = db.execute("SELECT COALESCE(SUM(d.available_quantity),0) n FROM farmer_deposits d JOIN farmers f ON f.id=d.farmer_id WHERE f.fpo_id=? AND d.crop_id=?", (fpo["id"], row["crop_id"])).fetchone()["n"]
        row["supply"] = supply
        row["match_score"] = calculate_match_score(row, supply, "Nashik")
    return page(request, "fpo/requirements.html", requirements=rows)

@app.get(f"{BASE_PATH}/fpo/requirements/{{requirement_id}}", response_class=HTMLResponse)
def fpo_requirement(request: Request, requirement_id: int):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        requirement = db.execute("SELECT r.*, c.name crop_name, b.company_name FROM buyer_requirements r JOIN crops c ON c.id=r.crop_id JOIN buyers b ON b.id=r.buyer_id WHERE r.id=?", (requirement_id,)).fetchone()
        fpo = db.execute("SELECT id FROM fpos WHERE user_id=?", (user["id"],)).fetchone()
        farmers = db.execute("SELECT f.id farmer_id, u.full_name, d.id deposit_id, d.available_quantity, d.quality_self_declared FROM farmer_deposits d JOIN farmers f ON f.id=d.farmer_id JOIN users u ON u.id=f.user_id WHERE f.fpo_id=? AND d.crop_id=? AND d.available_quantity>0 ORDER BY d.available_quantity DESC", (fpo["id"], requirement["crop_id"])).fetchall() if requirement else []
        lots = db.execute("SELECT * FROM aggregated_lots WHERE requirement_id=? ORDER BY created_at DESC", (requirement_id,)).fetchall()
    if not requirement: return page(request, "error.html", title="Requirement not found", message="This requirement no longer exists.")
    return page(request, "fpo/requirement_detail.html", requirement=requirement, farmers=farmers, lots=lots)

@app.post(f"{BASE_PATH}/fpo/requirements/{{requirement_id}}/lot")
def create_lot(request: Request, requirement_id: int):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        requirement = db.execute("SELECT * FROM buyer_requirements WHERE id=?", (requirement_id,)).fetchone()
        fpo = db.execute("SELECT id FROM fpos WHERE user_id=?", (user["id"],)).fetchone()
        if not requirement or not fpo:
            flash(request, "The requirement could not be found.", "danger")
        else:
            lot_number = f"KL-{date.today().year}-{db.execute('SELECT COALESCE(MAX(id),0)+1 n FROM aggregated_lots').fetchone()['n']:04d}"
            db.execute("INSERT INTO aggregated_lots(lot_number,fpo_id,requirement_id,crop_id,target_quantity,current_quantity,status,created_at,updated_at) VALUES(?,?,?,?,?,0,'COLLECTING',?,?)", (lot_number, fpo["id"], requirement_id, requirement["crop_id"], requirement["quantity"], now(), now()))
            db.execute("UPDATE buyer_requirements SET status='MATCHING',updated_at=? WHERE id=?", (now(), requirement_id))
            flash(request, f"Lot {lot_number} started. Add farmer quantities to build it.", "success")
    return RedirectResponse(f"{BASE_PATH}/fpo/requirements/{requirement_id}", status_code=303)

@app.get(f"{BASE_PATH}/fpo/lots/{{lot_id}}", response_class=HTMLResponse)
def lot_detail(request: Request, lot_id: int):
    user, denied = require_role(request, {"FPO", "BUYER", "ADMIN"})
    if denied: return denied
    with get_db() as db:
        lot = db.execute("SELECT l.*, c.name crop_name, r.delivery_district, r.required_grade, r.max_moisture, b.company_name FROM aggregated_lots l JOIN crops c ON c.id=l.crop_id JOIN buyer_requirements r ON r.id=l.requirement_id JOIN buyers b ON b.id=r.buyer_id WHERE l.id=?", (lot_id,)).fetchone()
        contributions = db.execute("SELECT lc.*, u.full_name, d.quality_self_declared FROM lot_contributions lc JOIN farmers f ON f.id=lc.farmer_id JOIN users u ON u.id=f.user_id JOIN farmer_deposits d ON d.id=lc.deposit_id WHERE lc.lot_id=?", (lot_id,)).fetchall()
        passport = db.execute("SELECT * FROM lot_passports WHERE lot_id=?", (lot_id,)).fetchone()
        offers = db.execute("SELECT o.*, b.company_name FROM offers o JOIN buyers b ON b.id=o.buyer_id WHERE o.lot_id=? ORDER BY o.created_at DESC", (lot_id,)).fetchall()
    if not lot: return page(request, "error.html", title="Lot not found", message="This lot could not be found.")
    with get_db() as db:
        farmer_rows = db.execute("SELECT d.id deposit_id, u.full_name, d.available_quantity FROM farmer_deposits d JOIN farmers f ON f.id=d.farmer_id JOIN users u ON u.id=f.user_id WHERE d.crop_id=? AND d.available_quantity>0", (lot["crop_id"],)).fetchall()
    return page(request, "fpo/lot_detail.html", lot=lot, contributions=contributions, passport=passport, offers=offers, farmer_rows=farmer_rows)

@app.post(f"{BASE_PATH}/fpo/lots/{{lot_id}}/contribute")
def contribute(request: Request, lot_id: int, deposit_id: int = Form(...), quantity: str = Form(...)):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    try:
        result = add_contribution(lot_id, deposit_id, float(quantity), user["id"])
        flash(request, result, "success")
    except ValueError as exc:
        flash(request, str(exc), "danger")
    return RedirectResponse(f"{BASE_PATH}/fpo/lots/{lot_id}", status_code=303)

@app.post(f"{BASE_PATH}/fpo/lots/{{lot_id}}/inspect")
def inspect_lot(request: Request, lot_id: int, grade: str = Form(...), moisture: float = Form(...), foreign_matter: float = Form(...), notes: str = Form("")):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        lot = db.execute("SELECT * FROM aggregated_lots l JOIN fpos f ON f.id=l.fpo_id WHERE l.id=? AND f.user_id=?", (lot_id, user["id"])).fetchone()
        if not lot:
            flash(request, "Lot not found or not owned by your FPO.", "danger")
        elif lot["status"] not in {"FULLY_AGGREGATED", "COLLECTING"} or lot["current_quantity"] < lot["target_quantity"]:
            flash(request, "The lot must reach its target before inspection.", "danger")
        else:
            db.execute("INSERT OR REPLACE INTO lot_passports(lot_id,grade,moisture_percent,foreign_matter_percent,inspection_notes,inspector_name,inspected_at,created_at) VALUES(?,?,?,?,?,?,?,?)", (lot_id, grade.upper(), moisture, foreign_matter, notes, user["full_name"], now(), now()))
            transition_lot(db, lot_id, "INSPECTED", user["id"])
            db.execute("UPDATE aggregated_lots SET updated_at=? WHERE id=?", (now(), lot_id))
            flash(request, "Lot inspected and passport created.", "success")
    return RedirectResponse(f"{BASE_PATH}/fpo/lots/{lot_id}", status_code=303)

@app.get(f"{BASE_PATH}/fpo/lots/{{lot_id}}/passport", response_class=HTMLResponse)
def passport(request: Request, lot_id: int):
    user, denied = require_role(request, {"FPO", "BUYER", "ADMIN"})
    if denied: return denied
    with get_db() as db:
        lot = db.execute("SELECT l.*, c.name crop_name, p.*, f.name fpo_name FROM aggregated_lots l JOIN crops c ON c.id=l.crop_id JOIN lot_passports p ON p.lot_id=l.id JOIN fpos f ON f.id=l.fpo_id WHERE l.id=?", (lot_id,)).fetchone()
    if not lot: return page(request, "error.html", title="Passport unavailable", message="This lot has not been inspected yet.")
    return page(request, "fpo/passport.html", lot=lot)

@app.get(f"{BASE_PATH}/fpo/offers", response_class=HTMLResponse)
def fpo_offers(request: Request):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        rows = db.execute("SELECT o.*, l.lot_number, c.name crop_name, b.company_name FROM offers o JOIN aggregated_lots l ON l.id=o.lot_id JOIN crops c ON c.id=l.crop_id JOIN buyers b ON b.id=o.buyer_id JOIN fpos f ON f.id=l.fpo_id WHERE f.user_id=? ORDER BY o.created_at DESC", (user["id"],)).fetchall()
    return page(request, "fpo/offers.html", offers=rows)

@app.post(f"{BASE_PATH}/fpo/offers/{{offer_id}}/accept")
def accept_offer(request: Request, offer_id: int):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        offer = db.execute("SELECT o.*, l.*, f.user_id fpo_user_id FROM offers o JOIN aggregated_lots l ON l.id=o.lot_id JOIN fpos f ON f.id=l.fpo_id WHERE o.id=?", (offer_id,)).fetchone()
        if not offer or offer["fpo_user_id"] != user["id"] or offer["status"] != "OPEN":
            flash(request, "This offer is no longer available.", "danger")
        elif offer["expires_at"] < now():
            flash(request, "This offer has expired.", "danger")
        else:
            db.execute("UPDATE offers SET status='ACCEPTED' WHERE id=?", (offer_id,))
            db.execute("UPDATE offers SET status='REJECTED' WHERE lot_id=? AND id<>? AND status='OPEN'", (offer["lot_id"], offer_id))
            db.execute("INSERT INTO deals(lot_id,offer_id,buyer_id,fpo_id,final_price,final_quantity,total_value,delivery_date,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (offer["lot_id"], offer_id, offer["buyer_id"], offer["fpo_id"], offer["price_per_quintal"], offer["current_quantity"], offer["price_per_quintal"]*offer["current_quantity"], offer["delivery_date"], "CONFIRMED", now(), now()))
            db.execute("UPDATE aggregated_lots SET status='DEAL_CONFIRMED',updated_at=? WHERE id=?", (now(), offer["lot_id"]))
            db.execute("UPDATE buyer_requirements SET status='DEAL_CREATED',updated_at=? WHERE id=?", (now(), offer["requirement_id"]))
            flash(request, "Offer accepted. The deal is confirmed.", "success")
    return RedirectResponse(f"{BASE_PATH}/fpo/offers", status_code=303)

@app.get(f"{BASE_PATH}/fpo/deals", response_class=HTMLResponse)
def fpo_deals(request: Request):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        deals = db.execute("SELECT d.*, l.lot_number, c.name crop_name, b.company_name FROM deals d JOIN aggregated_lots l ON l.id=d.lot_id JOIN crops c ON c.id=l.crop_id JOIN buyers b ON b.id=d.buyer_id JOIN fpos f ON f.id=d.fpo_id WHERE f.user_id=? ORDER BY d.created_at DESC", (user["id"],)).fetchall()
    return page(request, "fpo/deals.html", deals=deals)

@app.post(f"{BASE_PATH}/fpo/deals/{{deal_id}}/dispatch")
def dispatch_deal(request: Request, deal_id: int, vehicle_number: str = Form(...), driver_name: str = Form(...), dispatch_date: str = Form(...), notes: str = Form("")):
    user, denied = require_role(request, {"FPO"})
    if denied: return denied
    with get_db() as db:
        deal = db.execute("SELECT d.*, f.user_id FROM deals d JOIN fpos f ON f.id=d.fpo_id WHERE d.id=? AND f.user_id=?", (deal_id, user["id"])).fetchone()
        if not deal or deal["status"] != "CONFIRMED":
            flash(request, "Only a confirmed deal can be dispatched.", "danger")
        else:
            db.execute("INSERT OR REPLACE INTO deliveries(deal_id,vehicle_number,driver_name,dispatch_date,status,notes,updated_at) VALUES(?,?,?,?,?,?,?)", (deal_id, vehicle_number, driver_name, dispatch_date, "DISPATCHED", notes, now()))
            db.execute("UPDATE deals SET status='DISPATCHED',updated_at=? WHERE id=?", (now(), deal_id))
            db.execute("UPDATE aggregated_lots SET status='DISPATCHED',updated_at=? WHERE id=?", (now(), deal["lot_id"]))
            flash(request, "Dispatch recorded.", "success")
    return RedirectResponse(f"{BASE_PATH}/fpo/deals", status_code=303)

@app.post(f"{BASE_PATH}/fpo/deals/{{deal_id}}/pay")
def pay_deal(request: Request, deal_id: int):
    user, denied = require_role(request, {"FPO", "ADMIN"})
    if denied: return denied
    with get_db() as db:
        deal = db.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
        if not deal or deal["status"] not in {"DELIVERED", "PAYMENT_PENDING"}:
            flash(request, "Payment can be recorded after delivery.", "danger")
        else:
            db.execute("UPDATE payments SET status='PAID',reference_number=? WHERE deal_id=?", (f"SIM-{date.today().strftime('%Y%m%d')}-{deal_id:04d}", deal_id))
            db.execute("UPDATE deals SET status='SETTLED',updated_at=? WHERE id=?", (now(), deal_id))
            db.execute("UPDATE aggregated_lots SET status='SETTLED',updated_at=? WHERE id=?", (now(), deal["lot_id"]))
            flash(request, "Prototype payment marked as paid for all farmers.", "success")
    return RedirectResponse(f"{BASE_PATH}/fpo/deals", status_code=303)

@app.get(f"{BASE_PATH}/buyer", response_class=HTMLResponse)
def buyer_home(request: Request):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    with get_db() as db:
        buyer = db.execute("SELECT * FROM buyers WHERE user_id=?", (user["id"],)).fetchone()
        requirements = db.execute("SELECT r.*, c.name crop_name FROM buyer_requirements r JOIN crops c ON c.id=r.crop_id WHERE r.buyer_id=? ORDER BY r.created_at DESC", (buyer["id"],)).fetchall()
        offers = db.execute("SELECT o.*, l.lot_number, c.name crop_name FROM offers o JOIN aggregated_lots l ON l.id=o.lot_id JOIN crops c ON c.id=l.crop_id WHERE o.buyer_id=? ORDER BY o.created_at DESC", (buyer["id"],)).fetchall()
        deals = db.execute("SELECT d.*, l.lot_number, c.name crop_name FROM deals d JOIN aggregated_lots l ON l.id=d.lot_id JOIN crops c ON c.id=l.crop_id WHERE d.buyer_id=? ORDER BY d.created_at DESC", (buyer["id"],)).fetchall()
    return page(request, "buyer/home.html", buyer=buyer, requirements=requirements, offers=offers, deals=deals)

@app.get(f"{BASE_PATH}/buyer/requirements/new", response_class=HTMLResponse)
def new_requirement(request: Request):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    with get_db() as db: crops = db.execute("SELECT * FROM crops ORDER BY name").fetchall()
    return page(request, "buyer/requirement_form.html", crops=crops)

@app.post(f"{BASE_PATH}/buyer/requirements")
def create_requirement(request: Request, crop_id: int = Form(...), quantity: str = Form(...), target_price: str = Form(...), required_grade: str = Form(...), max_moisture: str = Form(...), delivery_district: str = Form(...), deadline: str = Form(...), notes: str = Form("")):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    try:
        data = RequirementInput(crop_id=crop_id, quantity=float(quantity), target_price=float(target_price), required_grade=required_grade, max_moisture=float(max_moisture), delivery_district=delivery_district, deadline=date.fromisoformat(deadline), notes=notes)
        if data.deadline < date.today(): raise ValueError("deadline")
    except (ValueError, ValidationError):
        flash(request, "Check the quantity, price, moisture and future deadline.", "danger")
        return RedirectResponse(f"{BASE_PATH}/buyer/requirements/new", status_code=303)
    with get_db() as db:
        buyer = db.execute("SELECT id FROM buyers WHERE user_id=?", (user["id"],)).fetchone()
        db.execute("INSERT INTO buyer_requirements(buyer_id,crop_id,quantity,target_price,required_grade,max_moisture,delivery_district,deadline,notes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,'DRAFT',?,?)", (buyer["id"], data.crop_id, data.quantity, data.target_price, data.required_grade.upper(), data.max_moisture, data.delivery_district, data.deadline.isoformat(), data.notes, now(), now()))
    flash(request, "Requirement saved as a draft. Publish it when ready.", "success")
    return RedirectResponse(f"{BASE_PATH}/buyer", status_code=303)

@app.post(f"{BASE_PATH}/buyer/requirements/{{requirement_id}}/publish")
def publish_requirement(request: Request, requirement_id: int):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    with get_db() as db:
        row = db.execute("SELECT r.*, b.user_id, u.is_verified FROM buyer_requirements r JOIN buyers b ON b.id=r.buyer_id JOIN users u ON u.id=b.user_id WHERE r.id=? AND b.user_id=?", (requirement_id, user["id"])).fetchone()
        if not row:
            flash(request, "Requirement not found.", "danger")
        elif not row["is_verified"]:
            flash(request, "An admin must verify your buyer account before you publish demand.", "warning")
        elif row["status"] != "DRAFT":
            flash(request, "Only draft requirements can be published.", "danger")
        else:
            db.execute("UPDATE buyer_requirements SET status='PUBLISHED',updated_at=? WHERE id=?", (now(), requirement_id))
            flash(request, "Requirement published. FPOs can now match supply.", "success")
    return RedirectResponse(f"{BASE_PATH}/buyer", status_code=303)

@app.get(f"{BASE_PATH}/buyer/lots", response_class=HTMLResponse)
def buyer_lots(request: Request):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    with get_db() as db:
        buyer = db.execute("SELECT id FROM buyers WHERE user_id=?", (user["id"],)).fetchone()
        lots = db.execute("SELECT l.*, c.name crop_name, f.name fpo_name, r.target_price, r.required_grade FROM aggregated_lots l JOIN buyer_requirements r ON r.id=l.requirement_id JOIN crops c ON c.id=l.crop_id JOIN fpos f ON f.id=l.fpo_id WHERE r.buyer_id=? AND l.status IN ('INSPECTED','OFFER_PENDING','DEAL_CONFIRMED','DISPATCHED','DELIVERED','SETTLED') ORDER BY l.updated_at DESC", (buyer["id"],)).fetchall()
    return page(request, "buyer/lots.html", lots=lots)

@app.get(f"{BASE_PATH}/buyer/offer/{{lot_id}}", response_class=HTMLResponse)
def offer_page(request: Request, lot_id: int):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    with get_db() as db:
        lot = db.execute("SELECT l.*, c.name crop_name, p.grade, p.moisture_percent, f.name fpo_name FROM aggregated_lots l JOIN crops c ON c.id=l.crop_id JOIN lot_passports p ON p.lot_id=l.id JOIN fpos f ON f.id=l.fpo_id WHERE l.id=? AND l.status IN ('INSPECTED','OFFER_PENDING')", (lot_id,)).fetchone()
    return page(request, "buyer/offer_form.html", lot=lot)

@app.post(f"{BASE_PATH}/buyer/offer/{{lot_id}}")
def submit_offer(request: Request, lot_id: int, price_per_quintal: str = Form(...), delivery_date: str = Form(...), expires_at: str = Form(...), message: str = Form("")):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    try:
        price = float(price_per_quintal)
        if price <= 0 or date.fromisoformat(delivery_date) < date.today(): raise ValueError
    except ValueError:
        flash(request, "Enter a positive price and a valid future delivery date.", "danger")
        return RedirectResponse(f"{BASE_PATH}/buyer/offer/{lot_id}", status_code=303)
    with get_db() as db:
        buyer = db.execute("SELECT id FROM buyers WHERE user_id=?", (user["id"],)).fetchone()
        lot = db.execute("SELECT * FROM aggregated_lots WHERE id=? AND status IN ('INSPECTED','OFFER_PENDING')", (lot_id,)).fetchone()
        if not lot:
            flash(request, "This lot is not open for offers.", "danger")
        else:
            db.execute("INSERT INTO offers(lot_id,buyer_id,price_per_quintal,delivery_date,message,expires_at,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (lot_id, buyer["id"], price, delivery_date, message, expires_at, "OPEN", now()))
            db.execute("UPDATE aggregated_lots SET status='OFFER_PENDING',updated_at=? WHERE id=?", (now(), lot_id))
            flash(request, "Offer sent to the FPO.", "success")
    return RedirectResponse(f"{BASE_PATH}/buyer/lots", status_code=303)

@app.get(f"{BASE_PATH}/buyer/deals", response_class=HTMLResponse)
def buyer_deals(request: Request):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    with get_db() as db:
        buyer = db.execute("SELECT id FROM buyers WHERE user_id=?", (user["id"],)).fetchone()
        deals = db.execute("SELECT d.*, l.lot_number, c.name crop_name, de.vehicle_number, de.driver_name, de.status delivery_status FROM deals d JOIN aggregated_lots l ON l.id=d.lot_id JOIN crops c ON c.id=l.crop_id LEFT JOIN deliveries de ON de.deal_id=d.id WHERE d.buyer_id=? ORDER BY d.created_at DESC", (buyer["id"],)).fetchall()
    return page(request, "buyer/deals.html", deals=deals)

@app.post(f"{BASE_PATH}/buyer/deals/{{deal_id}}/deliver")
def confirm_delivery(request: Request, deal_id: int):
    user, denied = require_role(request, {"BUYER"})
    if denied: return denied
    with get_db() as db:
        deal = db.execute("SELECT d.* FROM deals d WHERE d.id=? AND d.buyer_id=(SELECT id FROM buyers WHERE user_id=?)", (deal_id, user["id"])).fetchone()
        if not deal or deal["status"] != "DISPATCHED":
            flash(request, "This deal is not ready for delivery confirmation.", "danger")
        else:
            db.execute("UPDATE deliveries SET status='DELIVERED',delivery_date=?,updated_at=? WHERE deal_id=?", (date.today().isoformat(), now(), deal_id))
            db.execute("UPDATE deals SET status='PAYMENT_PENDING',updated_at=? WHERE id=?", (now(), deal_id))
            db.execute("UPDATE aggregated_lots SET status='DELIVERED',updated_at=? WHERE id=?", (now(), deal["lot_id"]))
            create_payouts(db, deal_id)
            flash(request, "Delivery confirmed. Farmer payouts are ready for payment.", "success")
    return RedirectResponse(f"{BASE_PATH}/buyer/deals", status_code=303)

@app.get(f"{BASE_PATH}/notifications", response_class=HTMLResponse)
def notifications_page(request: Request):
    user, denied = require_role(request, {"FARMER", "FPO", "BUYER", "ADMIN"})
    if denied: return denied
    with get_db() as db:
        rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
        db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user["id"],))
    return page(request, "notifications.html", notifications=rows)

@app.get(f"{BASE_PATH}/disputes", response_class=HTMLResponse)
def disputes_page(request: Request):
    user, denied = require_role(request, {"FARMER", "FPO", "BUYER", "ADMIN"})
    if denied: return denied
    with get_db() as db:
        if user["role"] == "ADMIN":
            rows = db.execute("SELECT d.*, u.full_name, de.id deal_id FROM disputes d JOIN users u ON u.id=d.raised_by JOIN deals de ON de.id=d.deal_id ORDER BY d.created_at DESC").fetchall()
        else:
            rows = db.execute("SELECT d.*, u.full_name, de.id deal_id FROM disputes d JOIN users u ON u.id=d.raised_by JOIN deals de ON de.id=d.deal_id WHERE d.raised_by=? OR de.buyer_id=(SELECT id FROM buyers WHERE user_id=?) OR de.fpo_id=(SELECT id FROM fpos WHERE user_id=?) ORDER BY d.created_at DESC", (user["id"], user["id"], user["id"])).fetchall()
        deals = db.execute("SELECT id,lot_id,status FROM deals WHERE buyer_id=(SELECT id FROM buyers WHERE user_id=?) OR fpo_id=(SELECT id FROM fpos WHERE user_id=?)", (user["id"], user["id"])).fetchall()
    return page(request, "disputes.html", disputes=rows, deals=deals)

@app.post(f"{BASE_PATH}/disputes/create")
def create_dispute(request: Request, deal_id: int = Form(...), reason: str = Form(...), description: str = Form(...)):
    user, denied = require_role(request, {"FARMER", "FPO", "BUYER", "ADMIN"})
    if denied: return denied
    with get_db() as db:
        db.execute("INSERT INTO disputes(deal_id,raised_by,reason,description,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (deal_id, user["id"], reason, description, "OPEN", now(), now()))
        flash(request, "Dispute raised for review.", "success")
    return RedirectResponse(f"{BASE_PATH}/disputes", status_code=303)

@app.post(f"{BASE_PATH}/admin/disputes/{{dispute_id}}/resolve")
def resolve_dispute(request: Request, dispute_id: int, resolution: str = Form(...), status: str = Form("RESOLVED")):
    user, denied = require_role(request, {"ADMIN"})
    if denied: return denied
    with get_db() as db:
        db.execute("UPDATE disputes SET status=?,resolution=?,updated_at=? WHERE id=?", (status, resolution, now(), dispute_id))
        flash(request, "Dispute updated.", "success")
    return RedirectResponse(f"{BASE_PATH}/disputes", status_code=303)

@app.get(f"{BASE_PATH}/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    user, denied = require_role(request, {"ADMIN"})
    if denied: return denied
    with get_db() as db:
        stats = {"users": db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"], "lots": db.execute("SELECT COUNT(*) n FROM aggregated_lots").fetchone()["n"], "deals": db.execute("SELECT COUNT(*) n FROM deals").fetchone()["n"], "disputes": db.execute("SELECT COUNT(*) n FROM disputes WHERE status='OPEN'").fetchone()["n"]}
        users = db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        logs = db.execute("SELECT a.*, u.full_name FROM activity_logs a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.created_at DESC LIMIT 12").fetchall()
    return page(request, "admin/home.html", stats=stats, users=users, logs=logs)

@app.post(f"{BASE_PATH}/admin/users/{{user_id}}/verify")
def verify_user(request: Request, user_id: int):
    user, denied = require_role(request, {"ADMIN"})
    if denied: return denied
    with get_db() as db:
        db.execute("UPDATE users SET is_verified=1 WHERE id=?", (user_id,))
    flash(request, "User verified.", "success")
    return RedirectResponse(f"{BASE_PATH}/admin", status_code=303)

@app.get(f"{BASE_PATH}/help", response_class=HTMLResponse)
def help_page(request: Request):
    user = current_user(request)
    role = user["role"] if user else "ALL"
    with get_db() as db:
        articles = db.execute("SELECT * FROM help_articles WHERE role IN (?, 'ALL') ORDER BY role, screen, step_number", (role,)).fetchall()
    return page(request, "help.html", articles=articles)

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return page(request, "error.html", title="Page not found", message="We couldn't find that KrishiLink page.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")), reload=False)