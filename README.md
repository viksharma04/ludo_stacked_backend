# Ludo Stacked Backend

Backend for the Ludo Stacked game. Ludo Stacked is a variation of the popular game known as Ludo or Pachisi. The game introduces new fun rules that take strategy to the next level and increase the importance of each player decision.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Supabase project with authentication enabled

### Environment Setup

Create a `.env` file with the following variables:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_API_KEY=your-anon-key
CORS_ORIGINS=["http://localhost:3000"]
DEBUG=true
```

### Install Dependencies

```bash
uv sync
```

### Start the Development Server

```bash
uv run fastapi dev
```

Visit http://localhost:8000

API docs available at http://localhost:8000/docs

## Project Structure

```
app/
├── __init__.py
├── main.py              # FastAPI application entry point
├── config.py            # Environment configuration
├── dependencies/
│   ├── auth.py          # JWT validation via Supabase JWKS
│   └── supabase.py      # Supabase client singleton
├── routers/
│   └── auth.py          # Authentication endpoints
└── schemas/
    └── auth.py          # Request/response models
```

## API Endpoints

### Authentication (`/api/v1/auth`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/me` | Get current user profile | Yes |

### Other

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info |
| GET | `/health` | Health check |

## Authentication

This backend validates JWTs issued by Supabase via JWKS. All authentication flows (signup, signin, OAuth, token refresh) are handled by the frontend using the Supabase JS client.

### Auth Flow

```
Frontend                              Backend
   |                                     |
   |-- supabase.auth.signUp() ------->  (Supabase handles)
   |-- supabase.auth.signInWithPassword() --> (Supabase handles)
   |-- supabase.auth.signInWithOAuth() --> (Supabase handles)
   |                                     |
   |-- GET /api/v1/auth/me -----------> | Validates JWT via JWKS
   |   Authorization: Bearer <jwt>      | Returns user profile
   |<-- { id, email } ----------------- |
   |                                     |
   |-- GET /api/v1/games -------------> | Validates JWT
   |   Authorization: Bearer <jwt>      | Uses user for game logic
   |<-- [...games...] ---------------- |
```

### Using Protected Endpoints

Include the access token in the Authorization header:

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

## Supabase Configuration

### Required Settings

1. **JWT Signing Keys**: Ensure RS256 keys are active (default for new projects)
2. **Email Provider**: Configure in Supabase dashboard (for email/password auth)
3. **OAuth Providers**: Configure in Supabase dashboard (for social logins)

## Learn More

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
- [Supabase JWT Signing Keys](https://supabase.com/docs/guides/auth/signing-keys)
