#!/usr/bin/env python3
"""
Telegram YouTube Downloader Bot (Version C)
- Accept YouTube link
- Download Video / Audio
- Quality choices: best, 720p, 480p, audio only
- yt-dlp download (supports Android client mode)
- Optional cookies for restricted videos
"""

import os
import asyncio
import subprocess
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Load .env
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
MAX_SEND_MB = int(os.getenv("MAX_SEND_MB", "45"))  # Telegram limit safe default

if not TOKEN:
    raise SystemExit("Please set TELEGRAM_TOKEN in .env")

# ---------- Helpers ----------
def sizeof_fmt(num, suffix='B'):
    for unit in ['','K','M','G','T','P']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'P', suffix)

def build_quality_keyboard():
    keyboard = [
        [InlineKeyboardButton("Video - Best", callback_data="v:best"),
         InlineKeyboardButton("Video - 720p", callback_data="v:720")],
        [InlineKeyboardButton("Video - 480p", callback_data="v:480"),
         InlineKeyboardButton("Audio - MP3", callback_data="a:mp3")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------- Bot Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hai — kirim link YouTube, saya bantu download.\n"
        "Setelah kirim link, pilih Video / Audio lalu kualitas."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - start bot\n"
        "Kirim link YouTube langsung ke chat\n"
        "Bot akan menampilkan pilihan kualitas"
    )

# ---------- Message Handler ----------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Kirimkan link YouTube.")
        return

    if "youtube.com" in text or "youtu.be" in text:
        context.user_data["yt_url"] = text
        await update.message.reply_text("Pilih format:", reply_markup=build_quality_keyboard())
    else:
        await update.message.reply_text("Ini bukan link YouTube. Coba kirim link video YouTube.")

# ---------- Callback Query Handler ----------
async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data
    url = context.user_data.get("yt_url")
    if not url:
        await q.edit_message_text("URL hilang, kirim ulang link YouTube dulu.")
        return

    action, opt = data.split(":", 1)
    await q.edit_message_text(f"Memproses {('Video' if action=='v' else 'Audio')} -> {opt}...\nSedang mendownload, tunggu ya.")
    loop = asyncio.get_event_loop()

    # Optional cookies
    cookies_file = None  # Jika ingin pakai cookies, masukkan path disini

    try:
        result_path = await loop.run_in_executor(
            None,
            lambda: download_youtube(url, action, opt, cookies_file)
        )
    except Exception as e:
        await update.effective_chat.send_message(f"Error saat download: {e}")
        return

    if not result_path:
        await update.effective_chat.send_message("Gagal mendownload.")
        return

    size_bytes = Path(result_path).stat().st_size
    size_mb = size_bytes / (1024*1024)
    caption = f"File siap: {Path(result_path).name} ({sizeof_fmt(size_bytes)})"

    try:
        if size_mb <= MAX_SEND_MB:
            await update.effective_chat.send_document(open(result_path, "rb"), caption=caption)
            os.remove(result_path)
        else:
            await update.effective_chat.send_message(
                f"File terlalu besar untuk dikirim lewat Telegram bot ({size_mb:.1f} MB). "
                f"Simpan file di VPS: {result_path}"
            )
    except Exception as e:
        await update.effective_chat.send_message(f"Gagal mengirim file: {e}")

# ---------- Download Function ----------
def download_youtube(url: str, action: str, opt: str, cookies_path: str | None = None) -> str | None:
    tmpdir = tempfile.mkdtemp(prefix="ytbot_")
    out_template = os.path.join(tmpdir, "%(title).200s.%(ext)s")

    if action == "v":
        if opt == "best":
            format_str = "bestvideo+bestaudio/best"
        elif opt == "720":
            format_str = "bestvideo[height<=720]+bestaudio/best[height<=720]"
        elif opt == "480":
            format_str = "bestvideo[height<=480]+bestaudio/best[height<=480]"
        else:
            format_str = "bestvideo+bestaudio/best"

        cmd = [
            "yt-dlp",
            "-f", format_str,
            "-o", out_template,
            "--merge-output-format", "mp4",
            "--extractor-args", "youtube:player_client=android",
            url
        ]
    else:
        cmd = [
            "yt-dlp",
            "-f", "bestaudio",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", out_template,
            "--extractor-args", "youtube:player_client=android",
            url
        ]

    # Tambahkan cookies jika valid
    if cookies_path:
        cmd.insert(1, "--cookies")
        cmd.insert(2, cookies_path)

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp error: {proc.stderr[:1000]}")

        files = list(Path(tmpdir).glob("*"))
        if not files:
            raise RuntimeError("File tidak ditemukan setelah yt-dlp selesai.")

        return str(sorted(files, key=lambda p: p.stat().st_size, reverse=True)[0])
    except Exception as e:
        for f in Path(tmpdir).glob("*"):
            f.unlink()
        Path(tmpdir).rmdir()
        raise

# ---------- Main ----------
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(callback_query))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
