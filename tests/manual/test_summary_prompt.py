#!/usr/bin/env python3
"""Manual test script for summary prompt outputs.

Run with: python tests/manual/test_summary_prompt.py

Requires CEREBRAS_API_KEY environment variable.
"""

from speakup.models import MessageEvent
from speakup.summarizers.cerebras import CerebrasSummarizer

SAMPLES = {
    MessageEvent.FINAL: """I've completed the refactoring of the authentication module. Here's a summary of the changes:

**Changes Made:**
1. Extracted the JWT token validation logic into a separate `TokenValidator` class
2. Implemented refresh token rotation for improved security
3. Added rate limiting to the login endpoint (5 attempts per minute)
4. Migrated from bcrypt to argon2 for password hashing

**Test Results:**
- All 127 tests pass
- Code coverage increased from 78% to 94%
- No breaking changes to the public API

**Files Modified:**
- `src/auth/token_validator.py` (new)
- `src/auth/login.py`
- `src/auth/middleware.py`
- `tests/auth/test_token_validator.py` (new)

The changes are backwards compatible and ready for review. You can merge this PR when approved.""",

    MessageEvent.ERROR: """I encountered an error while trying to run the database migrations:

```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) could not connect to server: Connection refused
    Is the server running on host "localhost" (127.0.0.1) and accepting
    TCP/IP connections on port 5432?
```

**What I tried:**
1. Checked if PostgreSQL is installed - yes, version 15.2
2. Ran `pg_isready` - returned "no response"
3. Checked the PostgreSQL service status - not running

**Likely cause:**
The PostgreSQL service is not running. This commonly happens after a system restart or if the service was manually stopped.

**Suggested fix:**
Run `brew services start postgresql@15` to start the database server, then retry the migration.

I cannot proceed with the migration until the database is available. Would you like me to try a different approach or wait for you to resolve this?""",

    MessageEvent.NEEDS_INPUT: """I'm setting up the deployment configuration for your application and need you to make a few decisions:

**1. Database Choice**
Which database would you like to use in production?
- **PostgreSQL** - Better for complex queries, ACID compliance, and JSON support. Recommended for most applications.
- **MySQL** - Faster for simple read-heavy workloads, wider hosting support.
- **SQLite** - Only suitable for development/testing, not recommended for production.

**2. Hosting Platform**
Where do you want to deploy?
- **AWS** (ECS + RDS)
- **Google Cloud** (Cloud Run + Cloud SQL)
- **DigitalOcean** (App Platform + Managed DB)
- **Self-hosted** (Docker Compose on VPS)

**3. Environment Variables**
I've detected 12 environment variables that need values:
- `DATABASE_URL` - Connection string (I can construct this after you choose the database)
- `SECRET_KEY` - Should I generate a secure random key?
- `REDIS_URL` - Do you need Redis for caching/sessions?
- `SENTRY_DSN` - Do you want error tracking enabled?

Please let me know your preferences and I'll generate the appropriate configuration files.""",

    MessageEvent.PROGRESS: """I'm currently analyzing your codebase for potential security vulnerabilities and performance issues. Here's my progress:

**Completed Analysis (45%):**
✓ Dependency audit - Found 2 outdated packages with known CVEs:
  - `requests>=2.28.0` has CVE-2023-32681 (moderate severity)
  - `pillow>=9.3.0` has CVE-2023-44271 (high severity)
✓ SQL injection scan - No issues found in 34 queries
✓ XSS vulnerability check - 3 potential issues flagged for review
✓ Hardcoded secrets scan - Found 1 API key in `tests/conftest.py` (test fixture, low risk)

**In Progress:**
→ Analyzing authentication flow for session management issues
→ Reviewing CORS configuration
→ Checking for insecure deserialization

**Pending:**
○ Performance profiling of database queries
○ Memory leak detection in long-running processes
○ SSL/TLS configuration review
○ Input validation audit across all endpoints

**Estimated time remaining:** ~8 minutes

I've found some issues that will need your attention. Should I continue with the full analysis or pause to address the critical findings first?""",

    MessageEvent.INFO: """The Docker build completed successfully. Here are the details:

**Build Summary:**
- Total build time: 47.3 seconds
- Final image size: 412 MB (compressed: 156 MB)
- Base image: python:3.12-slim

**Layers Created:**
1. System dependencies (apt packages) - 89 MB
2. Python dependencies (from requirements.txt) - 187 MB
3. Application code - 23 MB
4. Static assets - 12 MB

**Security Scan Results:**
- 0 critical vulnerabilities
- 0 high vulnerabilities
- 2 medium vulnerabilities (in optional dev dependencies)
- 12 low vulnerabilities (all in transitive dependencies)

**Next Steps:**
The image is tagged as `myapp:latest` and `myapp:v2.4.0`.

To run the container:
```bash
docker run -p 8000:8000 --env-file .env myapp:latest
```

To push to registry:
```bash
docker tag myapp:latest registry.example.com/myapp:latest
docker push registry.example.com/myapp:latest
```

The application is ready for deployment.""",
}

MAX_CHARS = 220


def main():
    summarizer = CerebrasSummarizer(api_key_env="CEREBRAS_API_KEY")

    print("=" * 60)
    print("SUMMARY PROMPT OUTPUT TEST")
    print("=" * 60)
    print()

    for event, message in SAMPLES.items():
        print(f"=== {event.value.upper()} ===")
        print(f"Input: {message}")
        print()

        try:
            result = summarizer.summarize(message, event, MAX_CHARS)
            print(f"Output: {result.summary}")
            print(f"Chars: {len(result.summary)}/{MAX_CHARS}")
        except Exception as e:
            print(f"ERROR: {e}")

        print()
        print("-" * 60)
        print()


if __name__ == "__main__":
    main()
