#!/usr/bin/env python3
"""
Telegram YouTube Downloader Bot (Version B)
Features:
- Accept YouTube link
- Show options: Download Video / Download Audio
- Show some quality choices (best, 720p, 480p, audio only)
- Download using yt-dlp (subprocess)
- Convert audio to mp3 if requested (ffmpeg must be installed)
- Send file back to user (with file size check)
- If file too big, provide info and keep file on VPS (optionally serve via simple http)
"""

import os
import asyncio
import shlex
import subprocess
import tempfile
import math
from pathlib import Path
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
MAX_SEND_MB = int(os.getenv("MAX_SEND_MB", "45"))  # safe default; bots may have limits

if not TOKEN:
    raise SystemExit("Please set TELEGRAM_TOKEN in .env")

# helpers
def sizeof_fmt(num, suffix='B'):
    for unit in ['','K','M','G','T','P']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'P', suffix)

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

def build_quality_keyboard():
    keyboard = [
        [InlineKeyboardButton("Video - Best", callback_data="v:best"),
         InlineKeyboardButton("Video - 720p", callback_data="v:720")],
        [InlineKeyboardButton("Video - 480p", callback_data="v:480"),
         InlineKeyboardButton("Audio - MP3", callback_data="a:mp3")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Kirimkan link YouTube.")
        return

    # basic url check
    if "youtube.com" in text or "youtu.be" in text:
        # save url in user_data for callback use
        context.user_data["yt_url"] = text
        await update.message.reply_text("Pilih format:", reply_markup=build_quality_keyboard())
    else:
        await update.message.reply_text("Ini bukan link YouTube. Coba kirim link video YouTube.")

async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data  # format "v:720" or "a:mp3" or "v:best"
    url = context.user_data.get("yt_url")
    if not url:
        await q.edit_message_text("URL hilang, kirim ulang link YouTube dulu.")
        return

    action, opt = data.split(":", 1)
    # run downloader in background thread to avoid blocking event loop
    await q.edit_message_text(f"Memproses {('Video' if action=='v' else 'Audio')} -> {opt}...\nSedang mendownload, tunggu ya.")
    loop = asyncio.get_event_loop()
    try:
        result_path = await loop.run_in_executor(None, lambda: download_youtube(url, action, opt))
    except Exception as e:
        await update.effective_chat.send_message(f"Error saat download: {e}")
        return

    if not result_path:
        await update.effective_chat.send_message("Gagal mendownload.")
        return

    # check file size
    size_bytes = Path(result_path).stat().st_size
    size_mb = size_bytes / (1024*1024)

    caption = f"File siap: {Path(result_path).name} ({sizeof_fmt(size_bytes)})"
    try:
        if size_mb <= MAX_SEND_MB:
            # send as document to preserve quality (or audio if requested)
            await update.effective_chat.send_document(open(result_path, "rb"), caption=caption)
            # remove file afterwards
            os.remove(result_path)
        else:
            # too big to send via bot reliably
            await update.effective_chat.send_message(
                f"File terlalu besar untuk dikirim lewat Telegram bot ({size_mb:.1f} MB). "
                f"Simpan file di VPS: {result_path}\n"
                "Jika mau, saya bisa bantu host file via HTTP sementara (butuh konfirmasi)."
            )
    except Exception as e:
        await update.effective_chat.send_message(f"Gagal mengirim file: {e}")

def download_youtube(url: str, action: str, opt: str) -> str | None:
    """
    Blocking function: use yt-dlp to download video/audio.
    Returns local file path or None.
    """
    tmpdir = tempfile.mkdtemp(prefix="ytbot_")
    out_template = os.path.join(tmpdir, "%(title).200s.%(ext)s")
    # base command
    if action == "v":
        # choose quality
        if opt == "best":
            format_str = "bestvideo+bestaudio/best"
        elif opt == "720":
            # prefer 720p mp4
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
            url
        ]
    else:  # audio
        # download best audio and convert to mp3
        cmd = [
            "yt-dlp",
            "-f", "bestaudio",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "-o", out_template,
            url
        ]

    try:
        # run yt-dlp
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp error: {proc.stderr[:1000]}")
        # find downloaded file
        files = list(Path(tmpdir).glob("*"))
        if not files:
            raise RuntimeError("File tidak ditemukan setelah yt-dlp selesai.")
        # choose largest file (in case of multiple)
        files_sorted = sorted(files, key=lambda p: p.stat().st_size, reverse=True)
        return str(files_sorted[0])
    except Exception as e:
        # cleanup on error
        try:
            for f in Path(tmpdir).glob("*"):
                f.unlink()
            Path(tmpdir).rmdir()
        except:
            pass
        raise

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
