"""Smoke test: one cheap Anthropic API call to confirm key + network are working."""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not api_key:
    print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
    sys.exit(1)

try:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        messages=[{"role": "user", "content": "Reply with the single word OK and nothing else."}],
    )
    text = resp.content[0].text.strip() if resp.content else ""
    print(f"Response: {text!r}  |  status: ok  |  tokens: {resp.usage.input_tokens}in {resp.usage.output_tokens}out")
    sys.exit(0)
except anthropic.AuthenticationError as exc:
    print(f"ERROR: authentication failed — check ANTHROPIC_API_KEY ({exc})", file=sys.stderr)
    sys.exit(2)
except Exception as exc:
    print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(3)
