"""Test suite lengkap KosanHub untuk Pytest."""
from datetime import date
import pytest

from kosanhub import create_app, db
from kosanhub.config import TestingConfig
from kosanhub.models import Property, Room, Tenant, Contract, Bill, BillingJob, User, BookingRequest
from kosanhub.services.bookings import submit_booking, approve_booking, reject_booking, lookup_status
from werkzeug.security import generate_password_hash
import base64
from kosanhub.models import Property, Room, Tenant, Contract, Bill, BillingJob
from kosanhub.services.billing import prorated_amount, late_fee_percent, days_late, late_fee_amount, due_date_for
from kosanhub.services.contracts import create_contract, pay_bill
from kosanhub.services.jobs import claim_next_job, process_job
from kosanhub.errors import ConflictError, ValidationError


@pytest.fixture
def app():
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


ADMIN_EMAIL = "admin@test.com"
ADMIN_PW = "rahasia-123"


@pytest.fixture
def admin(app):
    user = User(email=ADMIN_EMAIL, password_hash=generate_password_hash(ADMIN_PW))
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def basic(admin):
    """Header HTTP Basic untuk klien API (curl -u / Jenkins)."""
    token = base64.b64encode(f"{ADMIN_EMAIL}:{ADMIN_PW}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def adminc(app, admin):
    """Browser yang sudah login sebagai admin (session)."""
    c = app.test_client()
    res = c.post("/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert res.status_code == 302
    return c


def csrf_of(c, path="/status"):
    """Ambil token CSRF session dengan membuka halaman yang merender form."""
    assert c.get(path).status_code == 200
    with c.session_transaction() as sess:
        return sess["csrf"]


@pytest.fixture
def seed_data(app):
    prop = Property(name="Kos Sejahtera", address="Jl. Sukabirus No. 1")
    db.session.add(prop)
    db.session.flush()

    room1 = Room(property_id=prop.id, number="101", monthly_price=1000000)
    room2 = Room(property_id=prop.id, number="102", monthly_price=800000)
    db.session.add_all([room1, room2])
    db.session.flush()

    tenant1 = Tenant(name="Adli", phone="081234567890", email="adli@example.com")
    tenant2 = Tenant(name="Noval", phone="089876543210", email="noval@example.com")
    db.session.add_all([tenant1, tenant2])
    db.session.commit()

    return {"prop": prop, "room1": room1, "room2": room2, "tenant1": tenant1, "tenant2": tenant2}


# ==========================================
# TEST 1: Healthcheck endpoint (Wajib tubes)
# ==========================================
def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


# ==========================================
# TEST 2: Aturan Bisnis 1 (1 Kamar = 1 Kontrak Aktif)
# ==========================================
def test_rule_1_room_single_active_contract(app, seed_data):
    room1 = seed_data["room1"]
    tenant1 = seed_data["tenant1"]
    tenant2 = seed_data["tenant2"]

    # Kontrak pertama sukses
    c1 = create_contract(room1.id, tenant1.id, date(2026, 11, 1))
    db.session.commit()
    assert c1.status == Contract.ACTIVE

    # Kontrak kedua di kamar yang sama harus ditolak (ConflictError)
    with pytest.raises(ConflictError):
        create_contract(room1.id, tenant2.id, date(2026, 11, 5))


# ==========================================
# TEST 2b: Aturan Bisnis 1 dijaga juga oleh database (bukan hanya cek di aplikasi)
# ==========================================
def test_rule_1_enforced_by_database_constraint(app, seed_data):
    from sqlalchemy.exc import IntegrityError

    room1, tenant1, tenant2 = seed_data["room1"], seed_data["tenant1"], seed_data["tenant2"]
    # Simulasi dua request bersamaan yang sama-sama lolos cek aplikasi: insert langsung ke tabel.
    db.session.add(Contract(room_id=room1.id, tenant_id=tenant1.id, start_date=date(2026, 11, 1),
                            monthly_price=1000000, status=Contract.ACTIVE))
    db.session.commit()
    db.session.add(Contract(room_id=room1.id, tenant_id=tenant2.id, start_date=date(2026, 11, 2),
                            monthly_price=1000000, status=Contract.ACTIVE))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_rule_1_room_reusable_after_contract_ended(app, seed_data):
    from kosanhub.services.contracts import end_contract

    room1, tenant1, tenant2 = seed_data["room1"], seed_data["tenant1"], seed_data["tenant2"]
    c1 = create_contract(room1.id, tenant1.id, date(2026, 10, 1))
    db.session.commit()
    end_contract(c1, date(2026, 10, 31))
    db.session.commit()
    assert c1.active_room_id is None

    c2 = create_contract(room1.id, tenant2.id, date(2026, 11, 1))
    db.session.commit()
    assert c2.status == Contract.ACTIVE and c2.active_room_id == room1.id


def test_rule_1_api_returns_409_for_second_active_contract(client, basic, seed_data):
    body = {"room_id": seed_data["room1"].id, "tenant_id": seed_data["tenant1"].id, "start_date": "2026-11-01"}
    assert client.post("/api/contracts", json=body, headers=basic).status_code == 201
    body["tenant_id"] = seed_data["tenant2"].id
    assert client.post("/api/contracts", json=body, headers=basic).status_code == 409


# ==========================================
# TEST 3: Aturan Bisnis 2 (Prorata Bulan Pertama)
# ==========================================
def test_rule_2_prorated_first_month(app):
    # Misal masuk 15 November 2026 (November ada 30 hari).
    # Sisa hari = 30 - 15 + 1 = 16 hari.
    # Harga sewa = Rp 1.500.000
    # Prorata = (16 / 30) * 1.500.000 = Rp 800.000
    start = date(2026, 11, 15)
    amount = prorated_amount(1500000, start)
    assert amount == 800000

    # Masuk tanggal 1 (sebulan penuh) = Rp 1.500.000
    start_full = date(2026, 11, 1)
    assert prorated_amount(1500000, start_full) == 1500000


# ==========================================
# TEST 4: Aturan Bisnis 3 (Denda 2% per minggu, max 10%)
# ==========================================
def test_rule_3_late_fee_calculation():
    # 0 hari (tepat waktu) = 0%
    assert late_fee_percent(0) == 0
    # 1 - 7 hari (minggu 1) = 2%
    assert late_fee_percent(1) == 2
    assert late_fee_percent(7) == 2
    # 8 - 14 hari (minggu 2) = 4%
    assert late_fee_percent(8) == 4
    assert late_fee_percent(14) == 4
    # 15 - 21 hari (minggu 3) = 6%
    assert late_fee_percent(15) == 6
    # 22 - 28 hari (minggu 4) = 8%
    assert late_fee_percent(22) == 8
    # > 28 hari = cap di 10%
    assert late_fee_percent(29) == 10
    assert late_fee_percent(60) == 10

    # Uji rupiah nominal (Rp 1.000.000)
    assert late_fee_amount(1000000, 3) == 20000    # 2%
    assert late_fee_amount(1000000, 10) == 40000   # 4%
    assert late_fee_amount(1000000, 35) == 100000  # Max 10%


# ==========================================
# TEST 5: Aturan Bisnis 4 (Tagihan Tidak Boleh Terbit 2x)
# ==========================================
def test_rule_4_unique_monthly_bill(app, client, basic, seed_data):
    room2 = seed_data["room2"]
    tenant2 = seed_data["tenant2"]

    c = create_contract(room2.id, tenant2.id, date(2026, 11, 1))
    db.session.commit()

    # Terbitkan tagihan pertama
    res1 = client.post("/api/bills", json={"contract_id": c.id, "year": 2026, "month": 11}, headers=basic)
    assert res1.status_code == 201

    # Terbitkan tagihan kedua untuk periode yang sama -> Wajib Conflict (409)
    res2 = client.post("/api/bills", json={"contract_id": c.id, "year": 2026, "month": 11}, headers=basic)
    assert res2.status_code == 409


# ==========================================
# TEST 6: Tantangan K12 - Job Queue & Worker Processing
# ==========================================
def test_k12_worker_processes_billing_queue(app, client, basic, seed_data):
    room1 = seed_data["room1"]
    tenant1 = seed_data["tenant1"]
    c = create_contract(room1.id, tenant1.id, date(2026, 11, 1))
    db.session.commit()

    # 1. API menerima request trigger job (POST /api/jobs/generate-bills)
    res = client.post("/api/jobs/generate-bills", json={"year": 2026, "month": 11}, headers=basic)
    assert res.status_code == 202
    job_id = res.get_json()["id"]

    # 2. Worker meng-claim job
    job = claim_next_job()
    assert job is not None
    assert job.id == job_id
    assert job.status == BillingJob.PROCESSING

    # 3. Worker memproses job sampai selesai
    process_job(job)
    assert job.status == BillingJob.COMPLETED
    assert job.created_count >= 1

    # 4. Verifikasi tagihan benar-benar masuk di database
    bill = Bill.query.filter_by(contract_id=c.id, period_year=2026, period_month=11).first()
    assert bill is not None
    assert bill.status == Bill.UNPAID