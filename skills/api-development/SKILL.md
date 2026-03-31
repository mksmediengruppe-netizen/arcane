# REST API Development

## When to Use
This skill applies when the user requests an API, backend, REST endpoints, or server-side application.

## Best Practices
1. **Framework**: Use FastAPI (Python) for rapid development with auto-docs
2. **Validation**: Use Pydantic models for request/response validation
3. **Auth**: Implement JWT authentication with refresh tokens
4. **CORS**: Configure CORS for frontend access
5. **Error handling**: Return consistent error format: `{"detail": "message", "code": "ERROR_CODE"}`
6. **Pagination**: Use cursor-based pagination for large datasets
7. **Rate limiting**: Implement per-user rate limiting
8. **Logging**: Structured JSON logging with request IDs

## File Structure
```
api/
├── main.py             # FastAPI app entry point
├── routers/            # Route handlers by domain
├── models/             # Pydantic schemas
├── database/           # SQLAlchemy models + migrations
├── auth/               # JWT + password hashing
├── middleware/          # CORS, rate limiting, logging
└── requirements.txt
```

## Deployment
1. Use uvicorn with --workers for production
2. Set up Nginx as reverse proxy
3. Use systemd for process management
4. Configure SSL with Let's Encrypt
