# KEC Archives — Backend API

REST API for [KEC Archives](https://kecarchives.vercel.app), the official academic platform for Krishna Engineering College, Bhilai. Built with Python FastAPI.

**Live API:** https://kec-api-pi.vercel.app  
**Frontend repo:** https://github.com/humairaambreen/kecarchives-web  
**Built by:** Humaira Ambreen

---

## Tech Stack

| Technology | Purpose |
|---|---|
| Python FastAPI | REST API framework |
| SQLAlchemy | ORM |
| Alembic | Database migrations |
| Supabase PostgreSQL | Primary database |
| JWT (HS256) | Stateless authentication |
| Resend | Transactional email (OTP delivery) |
| Cloudinary | Media storage and CDN |
| Groq | LLM inference for AI post generation |
| HuggingFace FLUX.1-schnell | AI image generation |
| pywebpush | Web Push (PWA notifications) |
| Vercel | Hosting (serverless Python) |

---

## Project Structure

```
apps/api/
├── main.py                  # Entry point — imports app from app/main.py
├── requirements.txt         # Python dependencies
├── vercel.json              # Vercel serverless config
├── alembic.ini              # Alembic migration config
├── alembic/                 # Migration scripts
└── app/
    ├── main.py              # FastAPI app, CORS, router registration
    ├── api/
    │   ├── router.py        # Central API router
    │   ├── auth.py          # Auth endpoints (login, register, OTP, refresh)
    │   ├── posts.py         # Posts, comments, reactions, saves, media upload
    │   ├── subjects.py      # Subject management and enrollment
    │   ├── messages.py      # Direct messages, conversations, calls
    │   ├── groups.py        # Group chat, members, invite links
    │   ├── notifications.py # Notification CRUD
    │   ├── admin.py         # Admin-only user and stats management
    │   ├── ai.py            # Groq LLM and HuggingFace image generation
    │   ├── push.py          # Web Push subscription endpoints
    │   └── sessions.py      # Session management helpers
    ├── core/
    │   └── config.py        # Settings (pydantic-settings, env vars)
    ├── db/
    │   ├── session.py       # SQLAlchemy engine and session factory
    │   └── base.py          # Imports all models for Alembic autogenerate
    ├── models/              # SQLAlchemy ORM models
    ├── schemas/             # Pydantic request/response schemas
    ├── security/            # JWT creation and verification
    └── services/            # Business logic (email, cloudinary, push)
```

---

## API Endpoints

All routes are prefixed with `/api/v1/`.

### Authentication
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | No | Create account |
| POST | `/auth/login` | No | Login (email or username) |
| POST | `/auth/logout` | Yes | Invalidate session |
| POST | `/auth/send-otp` | No | Send OTP email |
| POST | `/auth/verify-otp` | No | Verify OTP |
| POST | `/auth/refresh` | Cookie | Refresh access token |
| GET | `/auth/me` | Yes | Current user profile |
| PATCH | `/auth/me` | Yes | Update profile |
| DELETE | `/auth/me` | Yes | Delete own account |
| POST | `/auth/forgot-password` | No | Initiate password reset |
| POST | `/auth/reset-password` | No | Set new password |
| POST | `/auth/check-admin` | No | Check if email is admin |
| POST | `/auth/admin-login` | No | Admin password step |
| POST | `/auth/verify-admin-otp` | No | Admin OTP step |

### Posts
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/posts/feed` | Yes | Personalized feed |
| POST | `/posts` | Faculty/Admin | Create post |
| GET | `/posts/:slug` | Yes | Post detail |
| DELETE | `/posts/:postId` | Author/Admin | Delete post |
| POST | `/posts/:postId/comments` | Yes | Add comment |
| POST | `/posts/:postId/reactions` | Yes | React to post |
| POST | `/posts/:postId/save` | Yes | Bookmark post |
| POST | `/posts/:postId/upload` | Faculty/Admin | Upload media |

### Messages & Groups
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/conversations` | Yes | List conversations |
| POST | `/conversations/:id/messages` | Yes | Send message |
| POST | `/conversations/:id/call/start` | Yes | Start audio/video call |
| POST | `/groups` | Yes | Create group |
| POST | `/groups/invite/:token/join` | Yes | Join via invite link |

### Admin
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/admin/stats` | Admin | Platform statistics |
| GET | `/admin/users` | Admin | All users |
| PATCH | `/admin/users/:userId/role` | Admin | Change user role |
| PATCH | `/admin/users/:userId/ban` | Admin | Ban/unban user |

### AI
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/ai/enhance-post` | Faculty/Admin | Generate post text (Groq) |
| POST | `/ai/generate-image` | Faculty/Admin | Generate image (FLUX) |

---

## Environment Variables

Create a `.env` file in this directory (never commit it):

```env
# Database (Supabase PostgreSQL)
DATABASE_URL=postgresql+psycopg2://user:password@host:6543/dbname
DB_HOST=
DB_PORT=6543
DB_USER=
DB_PASSWORD=
DB_NAME=

# JWT
JWT_SECRET=your-secret-key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS
CORS_ORIGINS=["http://localhost:3000"]

# Email (Resend)
RESEND_API_KEY=
EMAIL_FROM=KEC Archives <onboarding@yourdomain.com>
EMAIL_PROVIDER=resend   # use "console" for local dev (prints OTPs to stdout)

# Cloudinary
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=

# AI
GROQ_API_KEY=
HF_TOKEN=

# Web Push (VAPID)
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:admin@example.com
```

For local development set `EMAIL_PROVIDER=console` — OTP codes will print to the terminal instead of being emailed.

---

## Getting Started

### Prerequisites

- Python 3.11+
- pip

### Setup

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env
```

### Database

The app auto-creates tables on startup when using SQLite (`dev.db`). For PostgreSQL, run migrations:

```bash
alembic upgrade head
```

### Run

```bash
uvicorn main:app --reload --port 8000
```

API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Deploy to Vercel

```bash
vercel --prod
```

Set all environment variables in the Vercel project dashboard before deploying.
