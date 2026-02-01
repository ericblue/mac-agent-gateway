#!/usr/bin/env python3
"""Sign SKILL.md files with Ed25519 for integrity verification.

This script signs skill files to protect against tampering. The signature
and content hash are embedded in the YAML frontmatter.

Usage:
    # Generate a new signing keypair (first time only)
    python scripts/sign_skill.py --generate-key

    # Sign a skill file
    python scripts/sign_skill.py skills/mag-reminders/SKILL.md

    # Sign all skills
    python scripts/sign_skill.py skills/*/SKILL.md

Key storage:
    Private key: ~/.mag/signing_key.pem (keep secret!)
    Public key:  ~/.mag/signing_key.pub (share this)

The public key should be published in SECURITY.md for verification.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ed25519 signing requires cryptography library
try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError:
    print("Error: cryptography library required")
    print("Install with: pip install cryptography")
    sys.exit(1)


DEFAULT_KEY_DIR = Path.home() / ".mag"
PRIVATE_KEY_FILE = "signing_key.pem"
PUBLIC_KEY_FILE = "signing_key.pub"

# Regex to match YAML frontmatter
FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def get_key_paths(key_dir: Path | None = None) -> tuple[Path, Path]:
    """Get paths to private and public key files."""
    key_dir = key_dir or DEFAULT_KEY_DIR
    return key_dir / PRIVATE_KEY_FILE, key_dir / PUBLIC_KEY_FILE


def generate_keypair(key_dir: Path | None = None) -> tuple[Path, Path]:
    """Generate a new Ed25519 keypair and save to files.
    
    Returns paths to (private_key, public_key) files.
    """
    key_dir = key_dir or DEFAULT_KEY_DIR
    key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    private_path, public_path = get_key_paths(key_dir)
    
    if private_path.exists():
        print(f"Error: Private key already exists at {private_path}")
        print("Delete it first if you want to generate a new keypair.")
        sys.exit(1)
    
    # Generate keypair
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    
    # Save private key (PEM format, no encryption for simplicity)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    private_path.write_bytes(private_pem)
    os.chmod(private_path, 0o600)
    
    # Save public key (PEM format)
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_path.write_bytes(public_pem)
    os.chmod(public_path, 0o644)
    
    # Also output base64 format for embedding
    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(public_raw).decode()
    
    print(f"Generated Ed25519 keypair:")
    print(f"  Private key: {private_path}")
    print(f"  Public key:  {public_path}")
    print()
    print("Public key (base64, for SECURITY.md):")
    print(f"  {public_b64}")
    print()
    print("IMPORTANT: Keep the private key secret!")
    print("Add the public key to SECURITY.md for users to verify skills.")
    
    return private_path, public_path


def load_private_key(key_dir: Path | None = None) -> Ed25519PrivateKey:
    """Load the private key from file."""
    private_path, _ = get_key_paths(key_dir)
    
    if not private_path.exists():
        print(f"Error: Private key not found at {private_path}")
        print("Run with --generate-key first.")
        sys.exit(1)
    
    private_pem = private_path.read_bytes()
    private_key = serialization.load_pem_private_key(private_pem, password=None)
    
    if not isinstance(private_key, Ed25519PrivateKey):
        print(f"Error: {private_path} is not an Ed25519 private key")
        sys.exit(1)
    
    return private_key


def load_public_key(key_dir: Path | None = None) -> Ed25519PublicKey:
    """Load the public key from file."""
    _, public_path = get_key_paths(key_dir)
    
    if not public_path.exists():
        print(f"Error: Public key not found at {public_path}")
        sys.exit(1)
    
    public_pem = public_path.read_bytes()
    public_key = serialization.load_pem_public_key(public_pem)
    
    if not isinstance(public_key, Ed25519PublicKey):
        print(f"Error: {public_path} is not an Ed25519 public key")
        sys.exit(1)
    
    return public_key


def parse_frontmatter(content: str) -> tuple[str, str]:
    """Parse YAML frontmatter from content.
    
    Returns (frontmatter, body) where frontmatter excludes the --- delimiters.
    """
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        raise ValueError("No YAML frontmatter found (must start with ---)")
    
    frontmatter = match.group(1)
    body = content[match.end():]
    return frontmatter, body


def extract_base_frontmatter(frontmatter: str) -> str:
    """Remove existing integrity and signature blocks from frontmatter.
    
    This gives us the canonical content to hash/sign.
    """
    lines = frontmatter.split("\n")
    result = []
    skip_block = False
    
    for line in lines:
        # Check if we're starting an integrity or signature block
        if line.startswith("integrity:") or line.startswith("signature:"):
            skip_block = True
            continue
        
        # Check if we're exiting a block (line doesn't start with space)
        if skip_block and line and not line[0].isspace():
            skip_block = False
        
        if not skip_block:
            result.append(line)
    
    # Remove trailing empty lines
    while result and not result[-1].strip():
        result.pop()
    
    return "\n".join(result)


def compute_content_hash(frontmatter: str, body: str) -> str:
    """Compute SHA256 hash of the canonical skill content.
    
    We hash:
    1. Base frontmatter (without integrity/signature blocks)
    2. Body content
    
    This allows the signature to cover all meaningful content.
    """
    base_fm = extract_base_frontmatter(frontmatter)
    canonical = f"---\n{base_fm}\n---\n{body}"
    
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return content_hash


def sign_skill(skill_path: Path, private_key: Ed25519PrivateKey, public_key: Ed25519PublicKey) -> None:
    """Sign a SKILL.md file and update it with signature."""
    content = skill_path.read_text(encoding="utf-8")
    
    try:
        frontmatter, body = parse_frontmatter(content)
    except ValueError as e:
        print(f"Error in {skill_path}: {e}")
        sys.exit(1)
    
    # Compute hash of canonical content
    content_hash = compute_content_hash(frontmatter, body)
    
    # Sign the hash
    signature = private_key.sign(content_hash.encode("utf-8"))
    signature_b64 = base64.b64encode(signature).decode()
    
    # Get public key in base64 for embedding
    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_b64 = base64.b64encode(public_raw).decode()
    
    # Get current timestamp
    signed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Build new frontmatter with signature
    base_fm = extract_base_frontmatter(frontmatter)
    
    new_frontmatter = f"""{base_fm}
integrity:
  algorithm: sha256
  content_hash: "{content_hash}"
signature:
  signer_key: "{public_b64}"
  value: "{signature_b64}"
  signed_at: "{signed_at}\""""
    
    # Reconstruct the file
    new_content = f"---\n{new_frontmatter}\n---\n{body}"
    
    # Write back
    skill_path.write_text(new_content, encoding="utf-8")
    print(f"Signed: {skill_path}")
    print(f"  Hash: {content_hash[:16]}...")
    print(f"  Signed at: {signed_at}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sign SKILL.md files with Ed25519",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "skills",
        nargs="*",
        type=Path,
        help="SKILL.md files to sign",
    )
    parser.add_argument(
        "--generate-key",
        action="store_true",
        help="Generate a new Ed25519 keypair",
    )
    parser.add_argument(
        "--key-dir",
        type=Path,
        default=None,
        help=f"Directory for keys (default: {DEFAULT_KEY_DIR})",
    )
    
    args = parser.parse_args()
    
    if args.generate_key:
        generate_keypair(args.key_dir)
        return 0
    
    if not args.skills:
        parser.print_help()
        return 1
    
    # Load keys
    private_key = load_private_key(args.key_dir)
    public_key = private_key.public_key()
    
    # Sign each skill
    for skill_path in args.skills:
        if not skill_path.exists():
            print(f"Error: {skill_path} not found")
            return 1
        sign_skill(skill_path, private_key, public_key)
    
    print()
    print(f"Signed {len(args.skills)} skill(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
