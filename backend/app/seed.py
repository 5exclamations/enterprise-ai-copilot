"""Deterministic demo data for two fictional tenants. Run: `python -m app.seed --reset`.

The API keys below are DEMO values for local use only (stored hashed in the database).
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from .auth import hash_key
from .db import Base, SessionLocal, engine, init_db
from .models import Customer, Inventory, Order, OrderItem, Product, Tenant, User
from .services.documents import ingest_document

DOCS_DIR = Path(__file__).resolve().parents[1] / "sample_data" / "documents"

DEMO_KEYS = {
    "helix-admin": "demo-helix-admin-key",
    "helix-manager": "demo-helix-manager-key",
    "helix-viewer": "demo-helix-viewer-key",
    "verdant-manager": "demo-verdant-manager-key",
}
USERS = [  # (tenant, key, name, email, role)
    ("helix", "helix-admin", "Avery Admin", "avery@helix-supply.example", "admin"),
    ("helix", "helix-manager", "Morgan Manager", "morgan@helix-supply.example", "manager"),
    ("helix", "helix-viewer", "Vic Viewer", "vic@helix-supply.example", "viewer"),
    ("verdant", "verdant-manager", "Vera Manager", "vera@verdant-foods.example", "manager"),
]

# sku, name, category, description, price, reorder, supplier, hazmat, active, {warehouse: (on_hand, reserved)}
_C, _R = "Columbus", "Reno"
HELIX_PRODUCTS = [
    ("FS-1001", "Hex Bolt M8x40 Zinc (box of 100)", "Fasteners", "Zinc plated hex bolts", "18.50", 200, "Apex Fasteners", False, True, {_C: (420, 60), _R: (310, 40)}),
    ("FS-1002", "Hex Nut M8 Zinc (box of 200)", "Fasteners", "Zinc plated hex nuts", "9.75", 150, "Apex Fasteners", False, True, {_C: (180, 20), _R: (90, 10)}),
    ("FS-1003", "Stainless Washer M8 (box of 500)", "Fasteners", "Stainless steel flat washers", "14.20", 100, "Apex Fasteners", False, True, {_C: (35, 5), _R: (20, 0)}),
    ("FS-1004", "Self-Drilling Screw #10 (box of 250)", "Fasteners", "Self drilling sheet metal screws", "22.90", 250, "Apex Fasteners", False, True, {_C: (600, 120)}),
    ("FS-1005", "Anchor Bolt 1/2in x 6in (pack of 25)", "Fasteners", "Heavy duty concrete anchor bolts", "41.00", 40, "Apex Fasteners", False, True, {_C: (12, 4), _R: (8, 2)}),
    ("FS-1099", "Hex Bolt M8x40 Black Oxide (box of 100)", "Fasteners", "Discontinued black oxide hex bolts", "19.50", 0, "Apex Fasteners", False, False, {_C: (0, 0)}),
    ("SF-2001", "Nitrile Gloves Large (case of 1000)", "Safety", "Disposable nitrile gloves", "64.00", 50, "SafeGuard Co", False, True, {_C: (90, 30), _R: (60, 10)}),
    ("SF-2002", "Hard Hat Class E White", "Safety", "Class E electrical rated hard hat", "23.75", 100, "SafeGuard Co", False, True, {_C: (240, 20), _R: (130, 10)}),
    ("SF-2003", "Safety Glasses Anti-Fog (box of 12)", "Safety", "Anti fog safety glasses", "36.00", 60, "SafeGuard Co", False, True, {_C: (48, 8), _R: (30, 4)}),
    ("SF-2004", "High-Visibility Vest Class 2", "Safety", "Reflective high visibility vest", "12.40", 200, "SafeGuard Co", False, True, {_C: (500, 50), _R: (300, 30)}),
    ("SF-2005", "N95 Respirator (box of 20)", "Safety", "NIOSH approved N95 respirator masks", "28.50", 80, "SafeGuard Co", False, True, {_C: (25, 15), _R: (10, 5)}),
    ("SF-2006", "Steel-Toe Work Boots Size 10", "Safety", "Steel toe leather work boots", "89.00", 30, "SafeGuard Co", False, True, {_C: (40, 6), _R: (22, 2)}),
    ("TL-3001", "Cordless Drill 18V Kit", "Tools", "18 volt cordless drill driver kit with battery", "149.00", 10, "Forge Tools", False, True, {_C: (14, 3), _R: (6, 1)}),
    ("TL-3002", "Torque Wrench 1/2in 20-150 ft-lb", "Tools", "Click type torque wrench", "119.00", 8, "Forge Tools", False, True, {_C: (5, 2), _R: (3, 1)}),
    ("TL-3003", "Digital Caliper 150mm", "Tools", "Digital measuring caliper", "34.50", 25, "Forge Tools", False, True, {_C: (60, 5), _R: (40, 5)}),
    ("TL-3004", "Impact Socket Set 3/8in (24pc)", "Tools", "Impact rated socket set", "79.00", 10, "Forge Tools", False, True, {_C: (22, 2), _R: (10, 0)}),
    ("TL-3005", "Laser Distance Measurer 40m", "Tools", "Laser measuring device", "59.00", 10, "Forge Tools", False, True, {_C: (0, 0), _R: (0, 0)}),
    ("PK-4001", "Corrugated Box 12x12x12 (bundle of 25)", "Packaging", "Cardboard shipping boxes", "31.25", 200, "BoxWorks", False, True, {_C: (300, 100), _R: (150, 50)}),
    ("PK-4002", "Stretch Wrap 18in x 1500ft (case of 4)", "Packaging", "Pallet stretch wrap film", "58.00", 50, "BoxWorks", False, True, {_C: (80, 20), _R: (60, 10)}),
    ("PK-4003", "Packing Tape Clear 2in (case of 36)", "Packaging", "Clear packing tape rolls", "47.50", 30, "BoxWorks", False, True, {_C: (15, 5), _R: (5, 0)}),
    ("PK-4004", "Bubble Wrap 12in x 175ft", "Packaging", "Protective bubble wrap roll", "26.00", 40, "BoxWorks", False, True, {_C: (70, 10), _R: (40, 5)}),
    ("PK-4005", "Pallet Strapping Kit", "Packaging", "Strapping tool with straps and seals", "72.00", 15, "BoxWorks", False, True, {_C: (30, 4), _R: (18, 2)}),
    ("CH-5001", "Industrial Degreaser 1 gal (case of 4)", "Chemicals", "Industrial degreaser solvent", "68.00", 20, "ChemPro", True, True, {_C: (36, 6), _R: (24, 4)}),
    ("CH-5002", "Thread Locker Blue 50ml (box of 10)", "Chemicals", "Medium strength thread locking adhesive", "52.00", 40, "ChemPro", True, True, {_C: (100, 10), _R: (50, 10)}),
]
HELIX_CUSTOMERS = [  # name, tier, contact, email, phone
    ("Northwind Fabrication", "gold", "Dana Whitfield", "dana@northwindfab.example", "614-555-0142"),
    ("Cascade Builders", "standard", "Luis Ortega", "luis@cascadebuilders.example", "503-555-0177"),
    ("Ironbridge Construction", "platinum", "Priya Raman", "priya@ironbridge.example", "412-555-0120"),
    ("Summit Logistics", "standard", "Tom Becker", "tom@summitlogistics.example", "303-555-0191"),
    ("Pioneer Machining", "gold", "Grace Liu", "grace@pioneermach.example", "313-555-0165"),
    ("Lakeside Contractors", "standard", "Omar Haddad", "omar@lakesidecon.example", "216-555-0133"),
]
# number, customer, status, date, shipping, [(sku, qty)]
HELIX_ORDERS = [
    ("SO-10001", "Northwind Fabrication", "delivered", "2026-08-04", "standard", [("FS-1001", 10), ("FS-1002", 10)]),
    ("SO-10002", "Cascade Builders", "shipped", "2026-09-28", "standard", [("SF-2002", 20), ("SF-2004", 30)]),
    ("SO-10003", "Ironbridge Construction", "confirmed", "2026-09-30", "standard", [("TL-3001", 2), ("TL-3002", 1), ("TL-3004", 2)]),
    ("SO-10004", "Summit Logistics", "pending", "2026-10-02", "standard", [("PK-4001", 8), ("PK-4002", 5), ("PK-4003", 4)]),
    ("SO-10005", "Pioneer Machining", "pending", "2026-10-03", "standard", [("CH-5001", 3), ("CH-5002", 2)]),
    ("SO-10006", "Lakeside Contractors", "cancelled", "2026-09-15", "standard", [("SF-2006", 6)]),
    ("SO-10007", "Northwind Fabrication", "on_hold", "2026-10-05", "express", [("FS-1005", 10), ("FS-1003", 5)]),
    ("SO-10008", "Ironbridge Construction", "shipped", "2026-10-01", "standard", [("SF-2001", 4), ("SF-2003", 6), ("SF-2005", 2)]),
    ("SO-10009", "Cascade Builders", "pending", "2026-10-06", "standard", [("TL-3003", 5), ("TL-3005", 2)]),
    ("SO-10010", "Summit Logistics", "delivered", "2026-09-10", "standard", [("PK-4005", 3), ("PK-4004", 6)]),
    ("SO-10011", "Pioneer Machining", "confirmed", "2026-10-07", "standard", [("FS-1004", 12)]),
    ("SO-10012", "Lakeside Contractors", "pending", "2026-10-08", "standard", [("SF-2002", 4), ("SF-2003", 2)]),
]
VERDANT_PRODUCTS = [
    ("VF-1001", "Extra Virgin Olive Oil 5L", "Pantry", "Cold pressed olive oil", "42.00", 20, "Olio Sud", False, True, {"Portland": (60, 10)}),
    ("VF-1002", "Arborio Rice 10kg", "Pantry", "Italian risotto rice", "28.50", 15, "Riso Nord", False, True, {"Portland": (40, 5)}),
    ("VF-1003", "San Marzano Tomatoes (case of 12)", "Pantry", "Canned plum tomatoes", "36.00", 20, "Campania Foods", False, True, {"Portland": (80, 20)}),
    ("VF-1004", "Parmigiano Reggiano 1kg", "Dairy", "Aged parmesan wedge", "24.75", 25, "Parma Dairy", False, True, {"Portland": (18, 6)}),
    ("VF-1005", "Sea Salt Fine 25kg", "Pantry", "Fine sea salt sack", "19.00", 10, "Salina", False, True, {"Portland": (30, 0)}),
]
VERDANT_CUSTOMERS = [("Trattoria Rossi", "gold", "Marco Rossi", "marco@trattoriarossi.example", "503-555-0101"),
                     ("Harbor Bistro", "standard", "Ana Silva", "ana@harborbistro.example", "503-555-0102")]
VERDANT_ORDERS = [  # deliberately reuses SO-10001 to prove numbers are tenant-scoped
    ("SO-10001", "Trattoria Rossi", "shipped", "2026-09-20", "standard", [("VF-1001", 4), ("VF-1004", 6)]),
    ("SO-20002", "Harbor Bistro", "pending", "2026-10-04", "standard", [("VF-1003", 5)]),
]


def _add_tenant(db: Session, slug: str, name: str, products, customers, orders) -> Tenant:
    t = Tenant(slug=slug, name=name)
    db.add(t)
    db.flush()
    prods = {}
    for sku, pname, cat, desc, price, reorder, sup, haz, active, stock in products:
        p = Product(tenant_id=t.id, sku=sku, name=pname, category=cat, description=desc, unit_price=Decimal(price),
                    reorder_point=reorder, supplier=sup, hazmat=haz, active=active)
        p.inventory = [Inventory(tenant_id=t.id, warehouse=w, on_hand=oh, reserved=rs) for w, (oh, rs) in stock.items()]
        db.add(p)
        prods[sku] = p
    custs = {}
    for cname, tier, contact, email, phone in customers:
        c = Customer(tenant_id=t.id, name=cname, tier=tier, contact_name=contact, email=email, phone=phone)
        db.add(c)
        custs[cname] = c
    db.flush()
    for number, cname, status, date, ship, items in orders:
        o = Order(tenant_id=t.id, number=number, customer_id=custs[cname].id, status=status, shipping_method=ship,
                  created_on=datetime.fromisoformat(date).replace(tzinfo=UTC))
        o.items = [OrderItem(product_id=prods[s].id, quantity=q, unit_price=prods[s].unit_price) for s, q in items]
        db.add(o)
    db.flush()
    return t


def make_pdfs(out: Path) -> None:
    """Generate the sample PDFs (catalog guide and supplier onboarding) with fpdf2."""
    from fpdf import FPDF

    def pdf(path: Path, title: str, pages: list[list[str]]):
        doc = FPDF()
        doc.set_title(title)
        for lines in pages:
            doc.add_page()
            doc.set_font("Helvetica", "B", 16)
            doc.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
            doc.set_font("Helvetica", size=11)
            for ln in lines:
                doc.multi_cell(0, 6, ln, new_x="LMARGIN", new_y="NEXT")
                doc.ln(1)
        doc.output(str(path))

    pdf(out / "product-catalog-guide.pdf", "Product Catalog Guide", [
        ["Effective date: 2026-03-01", "Helix sells fasteners (FS), safety gear (SF), tools (TL), packaging (PK) and chemicals (CH).",
         "The minimum order quantity is one unit of any SKU. Prices are per box, pack, case or each as named."],
        ["Product notes", "TL-3002 torque wrenches require annual calibration; see the Warranty Policy.",
         "SF-2005 N95 respirators are NIOSH approved and are not suitable for asbestos work.",
         "FS-1099 is discontinued and replaced by FS-1001. Do not reorder FS-1099."],
    ])
    pdf(out / "supplier-onboarding-guide.pdf", "Supplier Onboarding Guide", [
        ["Effective date: 2026-02-01", "New suppliers must submit a completed tax form, proof of insurance and a quality certificate before the first purchase order.",
         "Suppliers are reviewed by the procurement team within 10 business days."],
        ["Example payment data (training only)", "Sample test card number 4111 1111 1111 1111 and sample tax ID 123-45-6789 appear in training forms only.",
         "Never store real card numbers or tax IDs in this system."],
    ])


def seed_database(db: Session, with_docs: bool = True) -> dict[str, Tenant]:
    helix = _add_tenant(db, "helix", "Helix Industrial Supply", HELIX_PRODUCTS, HELIX_CUSTOMERS, HELIX_ORDERS)
    verdant = _add_tenant(db, "verdant", "Verdant Foods Wholesale", VERDANT_PRODUCTS, VERDANT_CUSTOMERS, VERDANT_ORDERS)
    tenants = {"helix": helix, "verdant": verdant}
    for slug, key, name, email, role in USERS:
        db.add(User(tenant_id=tenants[slug].id, email=email, name=name, role=role,
                    api_key_hash=hash_key(DEMO_KEYS[key])))
    db.commit()
    if with_docs:
        make_pdfs(DOCS_DIR / "helix")
        for slug, t in tenants.items():
            for f in sorted((DOCS_DIR / slug).iterdir()):
                if f.suffix in (".md", ".txt", ".pdf"):
                    ingest_document(db, tenant_id=t.id, user_id=None, filename=f.name, data=f.read_bytes())
    return tenants


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    args = ap.parse_args()
    if args.reset:
        Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as s:
        seed_database(s)
    print("Seeded. Demo keys (local use only):")
    for k, v in DEMO_KEYS.items():
        print(f"  {k}: {v}")
