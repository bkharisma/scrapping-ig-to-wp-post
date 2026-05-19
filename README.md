# Instagram Crawler (Graph API)

Aplikasi untuk mengambil foto, video, dan caption dari Instagram Business/Creator account menggunakan **Instagram Graph API v21.0**. Tersedia dalam dua mode: **CLI** dan **Web Dashboard**.

## Daftar Isi

- [Fitur](#fitur)
- [Struktur Project](#struktur-project)
- [Instalasi](#instalasi)
- [Konfigurasi](#konfigurasi)
- [Cara Menjalankan](#cara-menjalankan)
  - [Mode 1: Web Dashboard](#mode-1-web-dashboard)
  - [Mode 2: CLI](#mode-2-cli)
- [Struktur Output](#struktur-output)
- [API Endpoints](#api-endpoints)
- [Detail File](#detail-file)
- [Cara Mendapatkan Token & ID](#cara-mendapatkan-token--id)
- [Teknologi](#teknologi)

---

## Fitur

### Web Dashboard (`app.py`)

- **Crawl real-time** dengan progress bar dan status polling
- **Filter berdasarkan** tanggal dan tipe media (IMAGE, VIDEO, CAROUSEL_ALBUM)
- **Riwayat sesi** — setiap crawl tersimpan dan bisa diakses kembali
- **Statistik sesi** — total post, likes, comments, rata-rata, post terpopuler
- **Tabel post** dengan paginasi (30 per halaman), pencarian caption, dan sorting (tanggal/likes/comments)
- **Detail post** dalam modal — tampilan media lengkap, video player, navigasi carousel
- **Download CSV** — ekspor caption ke file CSV
- **Download ZIP** — unduh semua media dalam satu file ZIP
- **Navigasi keyboard** — ArrowLeft/ArrowRight untuk carousel, Escape untuk tutup modal

### CLI (`main.py`)

- Jalankan crawling langsung dari terminal
- Progress bar menggunakan `tqdm`
- Metadata tersimpan sebagai JSON
- Media diunduh otomatis ke folder lokal

---

## Struktur Project

```
craw-ig/
├── app.py              # Flask web application (backend + API)
├── main.py             # CLI entry point
├── crawler.py          # Instagram Graph API crawler
├── downloader.py       # Media downloader (CLI & web mode)
├── exporter.py         # CSV exporter
├── config.py           # Konfigurasi dari environment variables
├── utils.py            # Helper: tanggal & MIME type
├── requirements.txt    # Python dependencies
├── .env.example        # Template konfigurasi
├── .env                # Konfigurasi (tidak di-commit)
├── templates/
│   └── index.html      # Dashboard HTML (Bootstrap 5)
├── static/
│   ├── app.js          # Frontend JavaScript
│   └── style.css       # Custom stylesheet
└── data/               # Output (dibuat otomatis)
    ├── crawls/         # Data sesi web dashboard
    │   ├── index.json
    │   └── YYYYMMDD_HHMMSS/
    │       ├── metadata.json
    │       ├── captions.csv
    │       └── media/
    │           └── YYYY-MM-DD/
    ├── media/          # Media CLI mode (flat)
    └── metadata_*.json # Metadata CLI mode
```

---

## Instalasi

### Prasyarat

- Python 3.10+
- Instagram Business atau Creator Account
- Facebook Developer App dengan akses Instagram Graph API

### Langkah Instalasi

```bash
# 1. Clone repository
git clone <repo-url>
cd craw-ig

# 2. Buat virtual environment (opsional tapi direkomendasikan)
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup konfigurasi
cp .env.example .env
# Edit file .env (lihat bagian Konfigurasi)
```

---

## Konfigurasi

Edit file `.env` berdasarkan template `.env.example`:

| Variabel | Wajib | Keterangan |
|----------|-------|------------|
| `ACCESS_TOKEN` | Ya | User Access Token dari Facebook App (scope: `instagram_basic`, `pages_show_list`) |
| `IG_USER_ID` | Ya | Instagram Business Account ID (angka) |
| `DATE_FROM` | Tidak | Awal periode filter, format `YYYY-MM-DD` (kosongkan = ambil semua) |
| `DATE_TO` | Tidak | Akhir periode filter, format `YYYY-MM-DD` |
| `OUTPUT_DIR` | Tidak | Folder output CLI mode (default: `data`) |

Parameter konfigurasi tambahan (di `config.py`):

| Parameter | Default | Keterangan |
|-----------|---------|------------|
| `GRAPH_API_BASE` | `https://graph.facebook.com/v21.0` | Facebook Graph API base URL |
| `REQUEST_DELAY` | `0.5` | Jeda antar halaman API (detik) |
| `MAX_RETRIES` | `3` | Maksimal percobaan ulang request API |

---

## Cara Menjalankan

### Mode 1: Web Dashboard

Menjalankan Flask server di port **5000** dengan UI lengkap:

```bash
python app.py
```

Buka browser ke **http://localhost:5000**

**Cara pakai dashboard:**

1. **Mulai Crawl** — isi rentang tanggal dan centang tipe media yang diinginkan, lalu klik "Mulai Crawl"
2. **Pantau Progress** — progress bar akan menampilkan status secara real-time
3. **Lihat Hasil** — setelah selesai, dashboard otomatis menampilkan post dari sesi tersebut
4. **Jelajahi Post** — klik baris tabel untuk melihat detail media dan caption lengkap
5. **Unduh Data** — gunakan tombol CSV untuk caption atau ZIP untuk semua media
6. **Riwayat Sesi** — panel kiri menampilkan daftar sesi crawl sebelumnya

### Mode 2: CLI

Menjalankan crawler langsung dari terminal tanpa web UI:

```bash
python main.py
```

Pastikan `DATE_FROM`, `DATE_TO`, `ACCESS_TOKEN`, dan `IG_USER_ID` sudah dikonfigurasi di `.env`.

---

## Struktur Output

### Web Dashboard

```
data/crawls/
├── index.json                          # Daftar semua sesi crawl
└── 20260519_135255/                    # Sesi per YYYYMMDD_HHMMSS
    ├── metadata.json                   # Metadata post (JSON)
    ├── captions.csv                    # Ekspor caption (CSV)
    └── media/                          # File media per tanggal
        ├── 2026-05-14/
        │   ├── 18228434389312680.jpg
        │   └── 18080765144409216.jpg
        ├── 2026-05-16/
        │   └── 18120218386735455.mp4
        └── 2026-05-18/
            ├── 18095134570926799_17963765607117538.jpg
            └── ...
```

### CLI

```
data/
├── metadata_20260519_131423.json       # Metadata lengkap (JSON)
└── media/                              # Semua file media (flat)
    ├── 17860509675551386.mp4
    ├── 17869483071395568.jpg
    └── ...
```

### Format `metadata.json`

```json
[
  {
    "id": "17841400123456789",
    "media_type": "IMAGE",
    "caption": "Teks caption...",
    "timestamp": "2026-05-18T10:30:00+0000",
    "permalink": "https://www.instagram.com/p/xxxxx/",
    "like_count": 120,
    "comments_count": 15,
    "media_url": "https://scontent.cdninstagram.com/...",
    "thumbnail_url": null,
    "media_files": ["media/2026-05-18/17841400123456789.jpg"],
    "children": []
  }
]
```

### Format `captions.csv`

| Kolom | Keterangan |
|-------|------------|
| `id` | Post ID Instagram |
| `date` | Tanggal post (YYYY-MM-DD) |
| `caption` | Teks caption lengkap |
| `type` | Tipe media (IMAGE/VIDEO/CAROUSEL_ALBUM) |
| `likes` | Jumlah like |
| `comments` | Jumlah komentar |
| `permalink` | URL Instagram post |

---

## API Endpoints

Semua endpoint di bawah digunakan oleh dashboard frontend:

| Method | Endpoint | Keterangan |
|--------|----------|------------|
| `GET` | `/` | Halaman dashboard |
| `POST` | `/api/crawl` | Mulai crawl baru. Body: `{date_from, date_to, media_types}` |
| `GET` | `/api/crawl/status?key=...` | Polling status crawl (dipanggil setiap 1 detik) |
| `GET` | `/api/sessions` | Daftar semua sesi crawl |
| `GET` | `/api/sessions/<id>/posts` | Daftar post (paginasi, search, sort) |
| `GET` | `/api/sessions/<id>/posts/<post_id>` | Detail satu post |
| `GET` | `/api/sessions/<id>/stats` | Statistik sesi |
| `GET` | `/api/sessions/<id>/csv` | Download caption CSV |
| `GET` | `/api/sessions/<id>/images` | Download semua media (ZIP) |
| `GET` | `/api/media/<id>/<filepath>` | Sajikan file media individual |

### Query Parameters `/api/sessions/<id>/posts`

| Parameter | Default | Keterangan |
|-----------|---------|------------|
| `page` | `1` | Nomor halaman |
| `per_page` | `30` | Post per halaman |
| `search` | `""` | Cari berdasarkan caption |
| `sort_by` | `timestamp` | Urutkan berdasarkan `timestamp`, `likes`, atau `comments` |
| `sort_order` | `desc` | Arah urutan: `asc` atau `desc` |

---

## Detail File

### `crawler.py` — Instagram Graph API Crawler

Kelas `InstagramCrawler` menangani komunikasi dengan Instagram Graph API:

- **Paginasi otomatis** — mengambil semua post dengan limit 100 per halaman
- **Filter tanggal** — penyaringan sisi klien berdasarkan `DATE_FROM` dan `DATE_TO`
- **Retry dengan exponential backoff** — hingga 3 percobaan ulang saat request gagal
- **Tipe media** — mendukung IMAGE, VIDEO, dan CAROUSEL_ALBUM (termasuk children)
- **Info akun** — mengambil username, nama, bio, jumlah followers, dan total post

### `downloader.py` — Media Downloader

Dua fungsi download:

| Fungsi | Mode | Struktur Folder |
|--------|------|-----------------|
| `download_media()` | CLI | Flat (`data/media/`) |
| `download_media_organized()` | Web | Per tanggal (`media/YYYY-MM-DD/`) |

Fitur:
- Streaming download (chunk 8192 byte)
- Timeout 60 detik per file
- Skip file yang sudah ada
- Progress callback untuk web dashboard
- Deteksi ekstensi otomatis berdasarkan URL

### `exporter.py` — CSV Exporter

Fungsi `export_captions_csv()` mengekspor metadata post ke file CSV dengan kolom: id, date, caption, type, likes, comments, permalink.

### `config.py` — Konfigurasi

Memuat semua variabel dari `.env` menggunakan `python-dotenv` dan mendefinisikan parameter default (API URL, delay, retry count).

### `utils.py` — Utilitas

- `parse_date()` — parsing string tanggal ke objek `datetime`
- `is_within_period()` — cek apakah timestamp berada dalam rentang tanggal
- `MIMETYPE_EXT` — mapping MIME type ke ekstensi file

---

## Cara Mendapatkan Token & ID

### 1. Buat Facebook App

1. Buka https://developers.facebook.com
2. Buat aplikasi baru bertipe **Business**
3. Tambahkan produk **Instagram Graph API**

### 2. Generate Access Token

1. Pergi ke **Tools > Graph API Explorer**
2. Pilih aplikasi yang sudah dibuat
3. Tambahkan permission: `instagram_basic`, `pages_show_list`
4. Klik **Generate Access Token**
5. Untuk token jangka panjang, tukar dengan Long-Lived Token melalui API

### 3. Dapatkan Instagram Business Account ID

```bash
# Step 1: Dapatkan Page ID
curl "https://graph.facebook.com/v21.0/me/accounts?access_token={TOKEN}"

# Step 2: Dapatkan IG Business Account ID dari Page ID
curl "https://graph.facebook.com/v21.0/{page_id}?fields=instagram_business_account&access_token={TOKEN}"
```

---

## Teknologi

| Komponen | Teknologi |
|----------|-----------|
| Backend | Python 3.10+, Flask 3.0 |
| API | Instagram Graph API v21.0 |
| Frontend | HTML, CSS, JavaScript (vanilla) |
| UI Framework | Bootstrap 5.3.3, Bootstrap Icons 1.11.3 |
| HTTP Client | Requests |
| Environment | python-dotenv |
| Progress Bar | tqdm (CLI mode) |

## Lisensi

Project ini untuk keperluan edukasi dan pengambilan data dari akun Instagram yang Anda kelola sendiri. Pastikan mematuhi kebijakan Instagram dan Meta Platform.
