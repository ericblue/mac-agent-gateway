# Release Process

This document describes how to prepare and publish a new release of Mac Agent Gateway.

## Prerequisites

1. **Signing key** — You need an Ed25519 keypair for signing skills
   ```bash
   # First time only: generate keypair
   make generate-signing-key
   # Keys are stored in ~/.mag/signing_key.pem (private) and ~/.mag/signing_key.pub (public)
   ```

2. **Dependencies** — Ensure cryptography is installed
   ```bash
   pip install cryptography
   # Or: pip install -e ".[signing]"
   ```

3. **Clean working directory** — All changes should be committed
   ```bash
   git status  # Should show no uncommitted changes
   ```

## Release Checklist

### 1. Update Version Numbers

Update the version in all relevant files:

```bash
# pyproject.toml
version = "X.Y.Z"

# src/mag/__init__.py
__version__ = "X.Y.Z"

# skills/mag-reminders/SKILL.md (frontmatter)
version: X.Y.Z

# skills/mag-messages/SKILL.md (frontmatter)
version: X.Y.Z
```

### 2. Update Changelog (if applicable)

Add release notes describing what's new, changed, or fixed.

### 3. Run Tests

Ensure all tests pass:

```bash
make test
```

### 4. Sign Skills

Sign all skill files with your private key:

```bash
make sign-skills
```

This updates the `integrity` and `signature` blocks in each SKILL.md file.

### 5. Verify Signatures

Confirm the signatures are valid:

```bash
make verify-skills
```

Expected output:
```
✓ skills/mag-messages/SKILL.md: Valid (signed YYYY-MM-DDTHH:MM:SSZ)
✓ skills/mag-reminders/SKILL.md: Valid (signed YYYY-MM-DDTHH:MM:SSZ)

All 2 skill(s) verified successfully
```

### 6. Commit Signed Skills

```bash
git add skills/ pyproject.toml src/mag/__init__.py
git commit -m "Release vX.Y.Z"
```

### 7. Create Git Tag

```bash
make release-tag VERSION=X.Y.Z
```

This will:
- Verify working directory is clean
- Check that the tag doesn't already exist
- Create an annotated tag `vX.Y.Z`
- Push to origin (main branch and tag)

### 8. Create GitHub Release

1. Go to https://github.com/ericblue/mac-agent-gateway/releases
2. Click "Draft a new release"
3. Select the tag `vX.Y.Z`
4. Title: `vX.Y.Z`
5. Description: Include highlights and link to changelog
6. Publish release

## Verification Instructions for Users

Users can verify skills before installing:

```bash
# Clone the repository
git clone https://github.com/ericblue/mac-agent-gateway.git
cd mac-agent-gateway

# Install verification dependencies
pip install cryptography

# Verify all skills (using make target)
make verify-skills

# Or use the script directly
python scripts/verify_skill.py skills/*/SKILL.md

# Verify against a specific release
git checkout vX.Y.Z
make verify-skills
```

## Signing Key Management

### Key Location

| File | Location | Purpose |
|------|----------|---------|
| Private key | `~/.mag/signing_key.pem` | Signs skills (keep secret!) |
| Public key | `~/.mag/signing_key.pub` | Verifies signatures |

### Backup Your Private Key

The private key cannot be regenerated. Back it up securely:

```bash
# Backup to encrypted archive
tar czf - ~/.mag/signing_key.pem | gpg -c > mag-signing-key-backup.tar.gz.gpg

# Or copy to secure storage
cp ~/.mag/signing_key.pem /path/to/secure/backup/
```

### Key Rotation

If you need to rotate the signing key (compromise, loss, etc.):

1. Generate a new keypair:
   ```bash
   rm ~/.mag/signing_key.pem ~/.mag/signing_key.pub
   make generate-signing-key
   ```

2. Update SECURITY.md with the new public key

3. Re-sign all skills:
   ```bash
   make sign-skills
   ```

4. Create a new release with the updated signatures

5. Announce the key rotation to users

## Troubleshooting

### "No signing key found"

Generate a keypair first:
```bash
make generate-signing-key
```

### "Private key already exists"

Your key already exists at `~/.mag/signing_key.pem`. If you really need to regenerate:
```bash
rm ~/.mag/signing_key.pem ~/.mag/signing_key.pub
make generate-signing-key
```

### "cryptography library required"

Install the dependency:
```bash
pip install cryptography
```

### Verification fails after signing

Ensure you're signing with the correct key. Check that the public key in SECURITY.md matches your `~/.mag/signing_key.pub`:

```bash
# Get your public key in base64
python3 -c "
from cryptography.hazmat.primitives import serialization
import base64
with open('$HOME/.mag/signing_key.pub', 'rb') as f:
    key = serialization.load_pem_public_key(f.read())
raw = key.public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw
)
print(base64.b64encode(raw).decode())
"
```

Compare with the key in SECURITY.md.

## Quick Reference

```bash
# Full release workflow
make test                          # Run tests
make sign-skills                   # Sign skills
make verify-skills                 # Verify signatures
git add -A
git commit -m "Release vX.Y.Z"
make release-tag VERSION=X.Y.Z    # Tag and push
```
