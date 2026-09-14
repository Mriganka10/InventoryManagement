from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import Body, Cookie, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth
from .models import init_db
from .services import (
    accounting_export, approve_stock_count, barcode_labels, bootstrap, context_for, create_appointment,
    create_customer_vehicle, create_entity, create_invoice, create_purchase, dashboard,
    import_inventory, inventory_template, issue_job_part, list_entities, list_operations,
    receive_purchase, recommendations, record_payment, set_service_package_items,
    start_stock_count, stock_movement, transfer_stock,
)

app = FastAPI(
    title="WorkshopOS Inventory Management",
    version="0.1.0",
    description="Multi-tenant automobile workshop operations, inventory, billing, and decision support.",
)
STATIC = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
init_db()


def _ctx(token: str | None) -> dict:
    return context_for(auth.require_email(token))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "workshop-os"}


@app.get("/", response_class=HTMLResponse)
def home(workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)):
    if not auth.session_email(workshop_session):
        return RedirectResponse("/login", 303)
    return HTMLResponse(APP_HTML)


@app.get("/login", response_class=HTMLResponse)
def login(workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)):
    if auth.session_email(workshop_session):
        return RedirectResponse("/", 303)
    return HTMLResponse(LOGIN_HTML)


@app.get("/register", response_class=HTMLResponse)
def register(workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)):
    if auth.session_email(workshop_session):
        return RedirectResponse("/", 303)
    return HTMLResponse(REGISTER_HTML)


@app.post("/api/auth/register-email")
def register_email(email: Annotated[str, Form()] = "", workshop_name: Annotated[str, Form()] = "") -> dict:
    return auth.register_email(email, workshop_name)


@app.post("/api/auth/request-otp")
def request_otp(email: Annotated[str, Form()] = "") -> dict:
    return auth.request_otp(email)


@app.post("/api/auth/verify")
def verify(email: Annotated[str, Form()] = "", otp: Annotated[str, Form()] = ""):
    user = auth.consume_otp(email, otp)
    response = RedirectResponse("/", 303)
    response.set_cookie(auth.SESSION_COOKIE, auth.session_token(user.email), max_age=auth.SESSION_MAX_AGE, httponly=True, secure=auth.COOKIE_SECURE, samesite="lax")
    return response


@app.post("/api/auth/logout")
def logout():
    response = RedirectResponse("/login", 303); response.delete_cookie(auth.SESSION_COOKIE); return response


@app.get("/api/bootstrap")
def api_bootstrap(workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return bootstrap(_ctx(workshop_session))


@app.get("/api/data/{kind}")
def api_list(
    kind: str, search: str = "", limit: int = Query(250, ge=1, le=1000),
    workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE),
) -> dict:
    ctx = _ctx(workshop_session)
    if kind in {"appointments", "jobs", "invoices", "purchases", "payments"}:
        return {kind: list_operations(ctx, kind, limit)}
    return {kind: list_entities(ctx, kind, search, limit)}


@app.post("/api/master/{kind}")
def api_create(kind: str, payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return create_entity(_ctx(workshop_session), kind, payload)


@app.post("/api/customer-vehicles")
def api_customer_vehicle(payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return create_customer_vehicle(_ctx(workshop_session), payload)


@app.post("/api/stock/movements")
def api_stock(payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return stock_movement(_ctx(workshop_session), payload)


@app.post("/api/stock/transfers")
def api_transfer(payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return transfer_stock(_ctx(workshop_session), payload)


@app.post("/api/appointments")
def api_appointment(payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return create_appointment(_ctx(workshop_session), payload)


@app.post("/api/service-packages/{package_id}/items")
def api_service_recipe(package_id: int, payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return set_service_package_items(_ctx(workshop_session), package_id, payload)


@app.post("/api/jobs/{job_id}/issue")
def api_issue(job_id: int, payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return issue_job_part(_ctx(workshop_session), job_id, payload)


@app.post("/api/purchases")
def api_purchase(payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return create_purchase(_ctx(workshop_session), payload)


@app.post("/api/purchases/{purchase_id}/receive")
def api_receive_purchase(purchase_id: int, workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return receive_purchase(_ctx(workshop_session), purchase_id)


@app.post("/api/invoices")
def api_invoice(payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return create_invoice(_ctx(workshop_session), payload)


@app.post("/api/invoices/{invoice_id}/payments")
def api_payment(invoice_id: int, payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return record_payment(_ctx(workshop_session), invoice_id, payload)


@app.post("/api/stock-counts")
def api_count(payload: Annotated[dict, Body()], workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return start_stock_count(_ctx(workshop_session), payload)


@app.post("/api/stock-counts/{count_id}/approve")
def api_approve_count(count_id: int, workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return approve_stock_count(_ctx(workshop_session), count_id)


@app.get("/api/dashboard")
def api_dashboard(branch_id: int | None = None, workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return dashboard(_ctx(workshop_session), branch_id)


@app.get("/api/advisor")
def api_advisor(branch_id: int | None = None, workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)) -> dict:
    return recommendations(_ctx(workshop_session), branch_id)


@app.get("/api/import/template")
def api_template(workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)):
    _ctx(workshop_session)
    return Response(inventory_template(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=inventory-import-template.xlsx"})


@app.post("/api/import/inventory")
async def api_import(
    branch_id: Annotated[int, Form()], file: Annotated[UploadFile, File()], dry_run: Annotated[bool, Form()] = True,
    workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE),
) -> dict:
    return await import_inventory(_ctx(workshop_session), branch_id, file, dry_run)


@app.get("/api/labels.pdf")
def api_labels(item_id: list[int] = Query(default=[]), workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)):
    return Response(barcode_labels(_ctx(workshop_session), item_id), media_type="application/pdf", headers={"Content-Disposition": "inline; filename=inventory-labels.pdf"})


@app.get("/api/accounting/export.csv")
def api_accounting_export(workshop_session: str | None = Cookie(default=None, alias=auth.SESSION_COOKIE)):
    return Response(accounting_export(_ctx(workshop_session)), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=workshop-accounting-export.csv"})


LOGIN_HTML = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>WorkshopOS · Sign in</title><link rel='stylesheet' href='/static/app.css'></head><body class='auth-body'>
<main class='auth-shell'><section class='brand-panel'><div class='logo-mark'>W</div><p class='eyebrow'>WORKSHOP OPERATIONS CLOUD</p><h1>Every part. Every job. One clear view.</h1><p>Inventory, service operations, billing and explainable decisions for growing automobile workshops.</p><div class='feature-row'><span>Live stock</span><span>Branch control</span><span>AI advisor</span></div></section>
<section class='auth-card'><p class='eyebrow accent'>SECURE ACCESS</p><h2>Welcome back</h2><p class='muted'>Enter your verified email and we’ll send a one-time code.</p><form id='request-form'><label>Email address</label><input name='email' type='email' placeholder='owner@workshop.com' required><button>Send OTP</button></form><form method='post' action='/api/auth/verify' id='otp-form' class='hidden'><input id='otp-email' name='email' type='hidden'><label>6-digit verification code</label><input name='otp' inputmode='numeric' autocomplete='one-time-code' pattern='[0-9]{6}' maxlength='6' required><button>Open my workshop</button></form><p id='status' class='status'></p><a href='/register' class='text-link'>New workshop? Verify your email →</a></section></main>
<script>const r=document.querySelector('#request-form'),o=document.querySelector('#otp-form'),s=document.querySelector('#status');r.onsubmit=async e=>{e.preventDefault();s.textContent='Sending…';const x=await fetch('/api/auth/request-otp',{method:'POST',body:new FormData(r)}),p=await x.json();if(!x.ok){s.textContent=p.detail||'Unable to send OTP';return}document.querySelector('#otp-email').value=p.email;o.classList.remove('hidden');s.textContent=p.dev_otp?'Local test OTP: '+p.dev_otp:'OTP sent to '+p.email;};</script></body></html>"""

REGISTER_HTML = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>WorkshopOS · Register</title><link rel='stylesheet' href='/static/app.css'></head><body class='auth-body'>
<main class='auth-shell'><section class='brand-panel'><div class='logo-mark'>W</div><p class='eyebrow'>NEW WORKSHOP</p><h1>Build a dependable operating system for your workshop.</h1><p>One account creates one isolated client workspace. Add branches and staff after sign-in.</p></section><section class='auth-card'><p class='eyebrow accent'>FIRST-TIME VERIFICATION</p><h2>Create your workspace</h2><p class='muted'>We’ll send an AWS verification link to this address before OTP login is enabled.</p><form id='register-form'><label>Workshop name</label><input name='workshop_name' placeholder='Northstar Auto Care' required><label>Owner email</label><input name='email' type='email' placeholder='owner@workshop.com' required><button>Send verification link</button></form><p id='status' class='status'></p><a href='/login' class='text-link'>← Back to sign in</a></section></main><script>const f=document.querySelector('#register-form'),s=document.querySelector('#status');f.onsubmit=async e=>{e.preventDefault();s.textContent='Requesting verification…';const r=await fetch('/api/auth/register-email',{method:'POST',body:new FormData(f)}),p=await r.json();s.textContent=r.ok?p.message:(p.detail||'Unable to register');};</script></body></html>"""

APP_HTML = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><meta name='theme-color' content='#111827'><link rel='manifest' href='/static/manifest.webmanifest'><link rel='stylesheet' href='/static/app.css'><title>WorkshopOS</title></head><body><aside class='sidebar'><div class='wordmark'><span class='logo-mark small'>W</span><strong>WorkshopOS</strong></div><nav><button class='nav active' data-view='dashboard'>Overview</button><button class='nav' data-view='inventory'>Inventory</button><button class='nav' data-view='stock'>Stock movement</button><button class='nav' data-view='customers'>Customers & vehicles</button><button class='nav' data-view='operations'>Appointments & jobs</button><button class='nav' data-view='purchases'>Purchases</button><button class='nav' data-view='billing'>Invoices & payments</button><button class='nav' data-view='import'>Import & verification</button><button class='nav' data-view='advisor'>AI decision advisor</button></nav><form method='post' action='/api/auth/logout'><button class='logout'>Sign out</button></form></aside><main class='workspace'><header><div><p class='eyebrow'>AUTOMOBILE WORKSHOP</p><h1 id='page-title'>Operational overview</h1></div><div class='header-controls'><select id='branch-filter'></select><button class='secondary' id='refresh'>Refresh</button></div></header><section id='content'><div class='loading'>Loading your workshop…</div></section></main><div id='toast'></div><script src='/static/app.js'></script></body></html>"""
