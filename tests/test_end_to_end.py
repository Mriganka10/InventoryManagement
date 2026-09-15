from fastapi.testclient import TestClient

from inventory_management import auth
from inventory_management.web import app


def signed_in_client(email="owner@example.com"):
    client = TestClient(app)
    registration = client.post("/api/auth/register-email", data={"email": email, "workshop_name": "Northstar Auto Care"})
    assert registration.status_code == 200
    otp = client.post("/api/auth/request-otp", data={"email": email})
    assert otp.status_code == 200
    code = otp.json()["dev_otp"]
    verified = client.post("/api/auth/verify", data={"email": email, "otp": code}, follow_redirects=False)
    assert verified.status_code == 303
    return client


def test_login_tenant_inventory_and_dashboard_flow():
    client = signed_in_client()
    bootstrap = client.get("/api/bootstrap").json()
    assert bootstrap["workshop"]["name"] == "Northstar Auto Care"
    branch_id = bootstrap["branches"][0]["id"]

    item = client.post("/api/master/items", json={
        "sku": "BP-001", "barcode": "890000000001", "name": "Front Brake Pad",
        "category": "Brakes", "purchase_price": 800, "selling_price": 1200,
        "min_stock": 4, "reorder_quantity": 8, "track_batch": True,
    })
    assert item.status_code == 200
    item_id = item.json()["id"]

    receipt = client.post("/api/stock/movements", json={
        "branch_id": branch_id, "item_id": item_id, "movement_type": "receipt",
        "quantity": 10, "unit_cost": 800, "batch_number": "LOT-1", "expires_on": "2028-12-31",
        "reason": "Initial purchase",
    })
    assert receipt.status_code == 200
    assert receipt.json()["balance"]["quantity_on_hand"] == 10

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["kpis"]["inventory_value"] == 8000
    assert dashboard["kpis"]["low_stock_count"] == 0

    items = client.get("/api/data/items").json()["items"]
    assert items[0]["quantity_available"] == 10
    assert client.get("/api/labels.pdf").headers["content-type"] == "application/pdf"


def test_customer_invoice_and_payment_flow():
    client = signed_in_client("billing@example.com")
    branch_id = client.get("/api/bootstrap").json()["branches"][0]["id"]
    created = client.post("/api/customer-vehicles", json={
        "customer": {"name": "Asha Singh", "phone": "9999999999"},
        "vehicle": {"registration_number": "WB01AB1234", "make": "Maruti", "model": "Swift"},
    })
    assert created.status_code == 200
    data = created.json()
    invoice = client.post("/api/invoices", json={
        "branch_id": branch_id, "customer_id": data["customer"]["id"], "vehicle_id": data["vehicle"]["id"],
        "lines": [{"line_type": "labour", "description": "Scheduled service", "quantity": 1, "unit_price": 1000, "tax_rate": 18}],
    })
    assert invoice.status_code == 200
    assert invoice.json()["total"] == 1180
    payment = client.post(f"/api/invoices/{invoice.json()['id']}/payments", json={"amount": 1180, "method": "UPI"})
    assert payment.status_code == 200
    assert payment.json()["invoice"]["status"] == "paid"


def test_production_registration_requires_signed_email_link(monkeypatch):
    email = "signed-link@example.com"
    client = TestClient(app)
    monkeypatch.setattr(auth, "EMAIL_PROVIDER", "ses")
    monkeypatch.setattr(auth, "_send_verification_link", lambda destination, token: destination == email and bool(token))
    monkeypatch.setattr(auth, "_send_otp", lambda destination, otp: destination == email and len(otp) == 6)

    registration = client.post("/api/auth/register-email", data={"email": email, "workshop_name": "Signed Link Motors"})
    assert registration.status_code == 200
    assert registration.json()["status"] == "pending"
    assert client.post("/api/auth/request-otp", data={"email": email}).status_code == 403

    confirmation = client.get(f"/api/auth/verify-email?token={auth.verification_token(email)}", follow_redirects=False)
    assert confirmation.status_code == 303
    assert confirmation.headers["location"] == "/login?verified=1"
    assert client.post("/api/auth/request-otp", data={"email": email}).status_code == 200
