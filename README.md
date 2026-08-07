# DeepBreath Backend · 后端

> FastAPI backend for the DeepBreath psychological companion platform.
>
> DeepBreath 深呼吸后端服务：FastAPI + PostgreSQL + Redis + AI。



<div align="center">

## ⭐ **喜欢这个项目吗？请给我们一个 Star！** ⭐

[![Star on GitHub](https://img.shields.io/github/stars/tylyy0223/deepbreath-backend?style=for-the-badge&logo=github&labelColor=black&color=f7df1e)](https://github.com/tylyy0223/deepbreath-backend)

<sub>你的 Star 是对我们最大的鼓励，也能让更多人发现这个项目 🚀</sub>

</div>

---

## 🛠 Tech Stack · 技术栈

| Component 组件 | Technology |
|---------------|-----------|
| Web Framework | FastAPI (async) |
| ORM | SQLAlchemy 2 (async) |
| Database | PostgreSQL |
| Cache | Redis |
| AI Chat | DeepSeek API |
| TTS | MiniMax API |
| Auth | JWT (access + refresh) |
| Deploy | Systemd + Nginx |

---

## 📁 Structure · 目录结构

```
backend/
├── app/
│   ├── api/v1/       # Route handlers 路由
│   ├── core/          # Config, DB, Security, Middleware 配置/数据库/安全/中间件
│   ├── models/        # SQLAlchemy models 数据模型
│   ├── services/      # Business logic 业务逻辑
│   │   ├── chatbot.py    # DeepSeek stream chat
│   │   ├── rag_search.py # Wiki.js knowledge base search
│   │   └── env.py        # Unified env loader
│   └── schemas/       # Pydantic schemas
├── migrations/        # Alembic migrations
├── tests/             # pytest test suite
├── alembic.ini        # DB migration config
├── monthly_gift.py    # Cron: monthly Credits gift
└── .env               # Environment variables (not committed)
```

---

## 🚀 Quick Start · 快速开始

```bash
cd deep-breath/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Fill in your API keys

# Run
uvicorn app.main:app --host 0.0.0.0 --port 8003

# Tests
pytest tests/ -v

# DB Migration
alembic revision --autogenerate -m "description"
alembic upgrade head
```

---

## 🔑 Environment Variables · 环境变量

| Key | Description 说明 |
|-----|-----------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `JWT_SECRET_KEY` | JWT signing secret |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `MINIMAX_API_KEY` | MiniMax TTS API key |
| `WIKI_DB_*` | Wiki.js database credentials (for RAG) |
| `SENTRY_DSN` | Sentry error monitoring (optional) |

---

## 📊 API Routes · 接口

| Prefix 前缀 | Module 模块 |
|-----------|------------|
| `/auth` | Login, Register, Token refresh, Phone binding |
| `/chat` | Streaming AI chat, Session management, Related articles |
| `/diary` | Mood entries, Stats, Weekly report |
| `/breath` | Breathing exercises, History, Stats |
| `/content` | Articles, Categories, Recommendations |
| `/scales` | SDS, SAS, SCL-90 assessments |
| `/community` | Posts, Replies, Likes |
| `/credits` | Balance, Transactions, Orders, Redeem |
| `/references` | Psychology e-book catalog, Book progress |
| `/tts` | Text-to-speech synthesis |
| `/admin` | Analytics, User management, Credits management |
| `/health` | Health check (DB + Redis) |

---

## 📄 License

MIT
