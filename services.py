import sqlite3
from datetime import datetime

LOT_TRANSITIONS = {"DRAFT": {"COLLECTING"}, "COLLECTING": {"FULLY_AGGREGATED", "DRAFT"}, "FULLY_AGGREGATED": {"INSPECTED"}, "INSPECTED": {"OFFER_PENDING", "DEAL_CONFIRMED"}, "OFFER_PENDING": {"DEAL_CONFIRMED"}, "DEAL_CONFIRMED": {"DISPATCHED"}, "DISPATCHED": {"DELIVERED"}, "DELIVERED": {"SETTLED"}}

def calculate_match_score(requirement, available_supply, fpo_district):
    if requirement.get("crop_id") is None:
        return 0
    volume = min(available_supply / max(float(requirement["quantity"]), 1), 1) * 25
    distance = 15 if requirement.get("delivery_district", "").lower() == fpo_district.lower() else 10
    quality = 10
    return round(30 + volume + distance + quality)

def transition_lot(db, lot_id, new_status, actor_id):
    lot = db.execute("SELECT status FROM aggregated_lots WHERE id=?", (lot_id,)).fetchone()
    if not lot or new_status not in LOT_TRANSITIONS.get(lot["status"], set()):
        raise ValueError(f"Invalid lot transition to {new_status}.")
    db.execute("UPDATE aggregated_lots SET status=?,updated_at=? WHERE id=?", (new_status, datetime.now().isoformat(timespec="seconds"), lot_id))
    db.execute("INSERT INTO activity_logs(actor_id,entity_type,entity_id,action,old_value,new_value,created_at) VALUES(?,?,?,?,?,?,?)", (actor_id, "lot", lot_id, "state_changed", lot["status"], new_status, datetime.now().isoformat(timespec="seconds")))

def add_contribution(lot_id, deposit_id, quantity, actor_id):
    if quantity <= 0:
        raise ValueError("Contribution must be greater than zero.")
    from database import get_db
    with get_db() as db:
        lot = db.execute("SELECT * FROM aggregated_lots WHERE id=?", (lot_id,)).fetchone()
        dep = db.execute("SELECT * FROM farmer_deposits WHERE id=?", (deposit_id,)).fetchone()
        if not lot or not dep:
            raise ValueError("Lot or farmer deposit not found.")
        fpo = db.execute("SELECT id FROM fpos WHERE user_id=?", (actor_id,)).fetchone()
        farmer = db.execute("SELECT fpo_id FROM farmers WHERE id=?", (dep["farmer_id"],)).fetchone()
        if not fpo or not farmer or lot["fpo_id"] != fpo["id"] or farmer["fpo_id"] != fpo["id"]:
            raise ValueError("This deposit does not belong to your FPO.")
        if lot["status"] != "COLLECTING":
            raise ValueError("This lot is no longer collecting contributions.")
        if db.execute("SELECT id FROM lot_contributions WHERE lot_id=? AND deposit_id=?", (lot_id, deposit_id)).fetchone():
            raise ValueError("This deposit is already allocated to this lot.")
        if dep["available_quantity"] < quantity:
            raise ValueError(f"Only {dep['available_quantity']:.1f} Qtl is available from this deposit.")
        if lot["current_quantity"] + quantity > lot["target_quantity"] * 1.1:
            raise ValueError("This would exceed the 110% over-aggregation limit.")
        db.execute("UPDATE farmer_deposits SET available_quantity=available_quantity-?,status=? WHERE id=?", (quantity, "RESERVED" if dep["available_quantity"] > quantity else "SOLD", deposit_id))
        db.execute("INSERT INTO lot_contributions(lot_id,farmer_id,deposit_id,quantity,created_at) VALUES(?,?,?,?,?)", (lot_id, dep["farmer_id"], deposit_id, quantity, datetime.now().isoformat(timespec="seconds")))
        new_quantity = lot["current_quantity"] + quantity
        db.execute("UPDATE aggregated_lots SET current_quantity=?,updated_at=? WHERE id=?", (new_quantity, datetime.now().isoformat(timespec="seconds"), lot_id))
        db.execute("INSERT INTO activity_logs(actor_id,entity_type,entity_id,action,new_value,created_at) VALUES(?,?,?,?,?,?)", (actor_id, "lot", lot_id, "farmer_contributed", str(quantity), datetime.now().isoformat(timespec="seconds")))
        if new_quantity >= lot["target_quantity"]:
            transition_lot(db, lot_id, "FULLY_AGGREGATED", actor_id)
    return f"{quantity:.1f} Qtl added. Lot progress is now {new_quantity:.1f} / {lot['target_quantity']:.1f} Qtl."

def calculate_net(price, quantity, transport, other):
    gross = price * quantity
    return {"gross": gross, "costs": transport + other, "net": gross - transport - other}

def create_payouts(db, deal_id):
    deal = db.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if not deal:
        return
    contributions = db.execute("SELECT farmer_id,quantity FROM lot_contributions WHERE lot_id=?", (deal["lot_id"],)).fetchall()
    total = sum(row["quantity"] for row in contributions) or 1
    for row in contributions:
        amount = deal["total_value"] * row["quantity"] / total
        db.execute("INSERT OR IGNORE INTO payments(deal_id,farmer_id,amount,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (deal_id, row["farmer_id"], amount, "PENDING", datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds")))

def notify(db, user_id, message, kind="info", link=""):
    db.execute("INSERT INTO notifications(user_id,message,type,is_read,link,created_at) VALUES(?,?,?,?,?,?)", (user_id, message, kind, 0, link, datetime.now().isoformat(timespec="seconds")))