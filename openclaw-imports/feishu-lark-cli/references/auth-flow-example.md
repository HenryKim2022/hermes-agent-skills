# Feishu Lark CLI Auth & Create Event — Complete Example

## Scenario
User wants to use lark-cli but lark-cli detects Hermes context and refuses (`hermes context detected but lark-cli is not bound to it`). The App is already configured in `~/.lark-cli/config.json` (no `config bind` needed).

## 1. Check existing config
```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" lark-cli config show
# → shows appId, brand, no logged-in users
```

## 2. Device flow auth (two-round)
### Round 1: Initiate + generate QR
```bash
# Get device code (must specify --domain or --recommend)
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli auth login --no-wait --json --domain calendar

# → returns device_code, verification_url, user_code, expires_in

# Generate QR code (--output only accepts relative paths!)
cd /tmp && env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" PWD="/tmp" \
  lark-cli auth qrcode --output ./lark-login.png "<verification_url>"
```

Send the QR image to the user to scan with Feishu app.

### Round 2: Complete after user scans
```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli auth login --device-code "<device_code>"
# → returns granted scopes, user_name, user_open_id
```

## 3. Re-auth with expanded scopes

If you already authorized with e.g. `calendar` and need to add `contact`:

```bash
# Specify both old and new domains
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli auth login --no-wait --json --domain "calendar,contact"
# → generates new device code and QR
# User scans → new token has both old + new scopes
```

## 4. Verify auth
```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" lark-cli auth status
# → user identity ready, token valid, userName shown
```

## 5. Search contacts
```bash
# Search by name (returns localized_name, open_id, email, etc.)
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli contact +search-user --query "Carlton Xu"

# The open_id field is the stable identifier for operations like inviting to events
```

## 6. Create event with attendees
```bash
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli calendar +create \
    --summary "土耳其 AGIone 演示" \
    --description "AGIone土耳其演示 - June 2" \
    --start "2026-06-02T10:00:00+03:00" \
    --end "2026-06-02T12:00:00+03:00" \
    --attendee-ids "ou_xxx,ou_yyy,ou_zzz" \
    --as user
# → returns event_id, summary, start, end (auto-converted to calendar owner's timezone)
```

## ⚠️ Pitfall: `env -i` + pipe kills python3

```bash
# ❌ THIS WILL FAIL:
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli ... | python3 -c "..."

# ✅ Safe alternative — write to file then read:
env -i HOME="$HOME" PATH="/usr/local/bin:/usr/bin:/bin" \
  lark-cli ... > /tmp/out.json
python3 -c "import json; d=json.load(open('/tmp/out.json')); ..."
```