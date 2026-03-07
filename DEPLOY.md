# 🚀 Railway Deployment Guide

## Prerequisites
- GitHub account
- Railway account (railway.app) — sign up with GitHub
- Your project pushed to a GitHub repository

---

## Step 1 — Push to GitHub

Open terminal in your project folder (`C:\Users\Nasimjon\...\Attendance\files\`):

```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

---

## Step 2 — Create Railway Project

1. Go to **railway.app** and click **New Project**
2. Choose **Deploy from GitHub repo**
3. Select your repository
4. Railway will detect the project and start building — wait for it to finish

---

## Step 3 — Add a Volume (persistent database)

This keeps your database alive across deploys and restarts.

1. In your Railway project, click your service
2. Go to **Volumes** tab → **Add Volume**
3. Set **Mount Path** to `/data`
4. Click **Add**

---

## Step 4 — Set Environment Variables

In your Railway service, go to **Variables** tab and add these one by one:

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather |
| `BOT_USERNAME` | Your bot's username (without @) |
| `BASE_URL` | Leave blank for now — fill after Step 5 |
| `DB_PATH` | `/data/attendance.db` |
| `PROFESSOR_SECRET` | Choose a strong password |
| `ADMIN_SECRET` | Choose a strong password |

---

## Step 5 — Get Your Railway Domain

1. Go to **Settings** tab of your service
2. Under **Networking** click **Generate Domain**
3. Copy the domain — looks like `your-app-name.railway.app`
4. Go back to **Variables** and set `BASE_URL` to `https://your-app-name.railway.app`
5. Click **Deploy** to redeploy with the updated URL

---

## Step 6 — Verify Everything Works

Visit these URLs:

| URL | Should show |
|---|---|
| `https://your-app.railway.app/dashboard` | Professor login page |
| `https://your-app.railway.app/admin` | Admin login page |
| `https://your-app.railway.app/api/docs` | API documentation |

Test the Telegram bot by sending `/start` to it.

---

## Step 7 — First Time Setup

1. Open `https://your-app.railway.app/admin`
2. Login with your `ADMIN_SECRET`
3. Scroll to **👥 Groups & Enrollment** → create your groups
4. Scroll to **🔑 Professor Accounts** → create professor logins
5. Share the dashboard URL and credentials with professors
6. Share the bot link with students: `https://t.me/YOUR_BOT_USERNAME`

---

## Updating the App Later

When you make code changes locally:

```bash
git add .
git commit -m "your change description"
git push
```

Railway auto-deploys on every push. Your database is safe on the Volume.

---

## Troubleshooting

**Bot not responding:**
- Check `TELEGRAM_BOT_TOKEN` is correct in Variables
- Check Railway logs (Deployments tab → click latest deploy → View Logs)

**QR code deep link not working:**
- Make sure `BASE_URL` matches your exact Railway domain including `https://`
- No trailing slash at the end

**Database errors on first deploy:**
- The `/data` directory must exist — this is created automatically by the Volume
- Check that `DB_PATH` is set to `/data/attendance.db`

**GPS rejecting students:**
- Increase radius to 150–200m for indoor classrooms
- Students should enable High Accuracy location mode on their phone

---

## Local Development (unchanged)

```bash
# Terminal 1 — API
uvicorn api.main:app --reload --port 8000

# Terminal 2 — Bot  
python bot/main.py

# Terminal 3 — Tunnel
ngrok http 8000
```
