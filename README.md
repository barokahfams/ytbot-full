# Telegram YouTube Downloader (Version B)

Fitur:
- Download video / audio dari YouTube
- Pilih kualitas (best, 720p, 480p, audio mp3)
- Menggunakan yt-dlp + ffmpeg
- Mengirim file kembali ke user jika ukuran <= MAX_SEND_MB

## Install (Ubuntu)
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg

pip3 install -r requirements.txt

## Konfigurasi
cp .env.example .env
# edit .env -> isi TELEGRAM_TOKEN

## Jalankan
python3 main.py

## Docker
docker compose up -d --build
