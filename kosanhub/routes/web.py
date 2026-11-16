"""Halaman web dashboard sederhana."""
from flask import Blueprint

web_bp = Blueprint("web", __name__, template_folder="templates")


@web_bp.get("/")
def index():
    """Dashboard HTML sederhana yang menampilkan statistik kos."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>KosanHub – Manajemen Sewa Kos</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f5f5; color: #333; }
            header { background: #000; color: #fff; padding: 20px; text-align: center; }
            h1 { font-size: 28px; }
            .container { max-width: 960px; margin: 40px auto; padding: 0 20px; }
            .card { background: #fff; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
            .endpoint { font-family: monospace; background: #f0f0f0; padding: 8px; margin: 10px 0; }
            a { color: #0066cc; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <header>
            <h1>🏠 KosanHub</h1>
            <p>Sistem Manajemen Sewa Kos & Tagihan Bulanan</p>
        </header>
        <div class="container">
            <div class="card">
                <h2>Selamat Datang</h2>
                <p>KosanHub adalah aplikasi manajemen kos-kosan dengan fitur tagihan otomatis dan denda keterlambatan.</p>
            </div>
            <div class="card">
                <h2>API Endpoints</h2>
                <p>Endpoint yang tersedia:</p>
                <div class="endpoint">GET /health</div>
                <div class="endpoint">POST /api/jobs/generate-bills (trigger job antrean)</div>
                <div class="endpoint">GET /api/bills</div>
                <div class="endpoint">GET /api/contracts</div>
                <p>Lihat dokumentasi lengkap di <code>README.md</code>.</p>
            </div>
            <div class="card">
                <h2>Fitur Utama</h2>
                <ul style="margin-left: 20px;">
                    <li>✓ Manajemen properti, kamar, dan penyewa</li>
                    <li>✓ Kontrak sewa dengan aturan 1 kamar = 1 kontrak aktif</li>
                    <li>✓ Tagihan otomatis dengan prorata bulan pertama</li>
                    <li>✓ Denda keterlambatan (2% per minggu, max 10%)</li>
                    <li>✓ Background worker untuk pemrosesan massal</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    """
