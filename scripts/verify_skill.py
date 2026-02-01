#!/usr/bin/env python3
"""Verify SKILL.md file signatures.

This script verifies that a skill file has not been tampered with by checking
the embedded Ed25519 signature against the content hash.

Usage:
    # Verify a single skill
    python scripts/verify_skill.py skills/mag-reminders/SKILL.md

    # Verify all skills
    python scripts/verify_skill.py skills/*/SKILL.md

    # Verify with explicit public key
    python scripts/verify_skill.py --public-key ~/.mag/signing_key.pub skills/mag-reminders/SKILL.md

Exit codes:
    0 - All skills verified successfully
    1 - One or more skills failed verification
    2 - Error (missing files, invalid format, etc.)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
from pathlib import Path

# Ed25519 verification requires cryptography library
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:
    print("Error: cryptography library required")
    print("Install with: pip install cryptography")
    sys.exit(2)


# ANSI colors for output
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def color(text: str, c: str) -> str:
    """Wrap text in ANSI color codes."""
    # Disable colors if not a TTY
    if not sys.stdout.isatty():
        return text
    return f"{c}{text}{Colors.RESET}"


# Regex to match YAML frontmatter
FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


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
    """Remove integrity and signature blocks from frontmatter.
    
    This gives us the canonical content that was signed.
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


def extract_yaml_value(frontmatter: str, *keys: str) -> str | None:
    """Extract a nested value from YAML frontmatter.
    
    Simple parser that handles the specific format we use.
    Example: extract_yaml_value(fm, "integrity", "content_hash")
    """
    lines = frontmatter.split("\n")
    current_block = None
    
    for line in lines:
        # Top-level key
        if line and not line[0].isspace() and line.endswith(":"):
            current_block = line[:-1]
            continue
        
        # Nested key-value
        if line.startswith("  ") and current_block:
            stripped = line.strip()
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                
                if len(keys) == 2 and keys[0] == current_block and keys[1] == key:
                    return value
    
    return None


def compute_content_hash(frontmatter: str, body: str) -> str:
    """Compute SHA256 hash of the canonical skill content."""
    base_fm = extract_base_frontmatter(frontmatter)
    canonical = f"---\n{base_fm}\n---\n{body}"
    
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return content_hash


def load_public_key_from_b64(key_b64: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from base64-encoded raw bytes."""
    key_bytes = base64.b64decode(key_b64)
    return Ed25519PublicKey.from_public_bytes(key_bytes)


def load_public_key_from_file(path: Path) -> Ed25519PublicKey:
    """Load an Ed25519 public key from PEM file."""
    public_pem = path.read_bytes()
    public_key = serialization.load_pem_public_key(public_pem)
    
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError(f"{path} is not an Ed25519 public key")
    
    return public_key


def verify_skill(skill_path: Path, expected_key: Ed25519PublicKey | None = None) -> tuple[bool, str]:
    """Verify a SKILL.md file's signature.
    
    Args:
        skill_path: Path to the SKILL.md file
        expected_key: Optional expected public key (if None, uses embedded key)
    
    Returns:
        (success, message) tuple
    """
    try:
        content = skill_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, "File not found"
    except Exception as e:
        return False, f"Cannot read file: {e}"
    
    try:
        frontmatter, body = parse_frontmatter(content)
    except ValueError as e:
        return False, str(e)
    
    # Extract integrity info
    algorithm = extract_yaml_value(frontmatter, "integrity", "algorithm")
    stored_hash = extract_yaml_value(frontmatter, "integrity", "content_hash")
    
    if not algorithm or not stored_hash:
        return False, "No integrity block found (skill is not signed)"
    
    if algorithm != "sha256":
        return False, f"Unsupported hash algorithm: {algorithm}"
    
    # Extract signature info
    signer_key_b64 = extract_yaml_value(frontmatter, "signature", "signer_key")
    signature_b64 = extract_yaml_value(frontmatter, "signature", "value")
    signed_at = extract_yaml_value(frontmatter, "signature", "signed_at")
    
    if not signer_key_b64 or not signature_b64:
        return False, "No signature block found (skill is not signed)"
    
    # Verify hash
    computed_hash = compute_content_hash(frontmatter, body)
    if computed_hash != stored_hash:
        return False, f"Content hash mismatch (file was modified)"
    
    # Load the signer's public key
    try:
        signer_key = load_public_key_from_b64(signer_key_b64)
    except Exception as e:
        return False, f"Invalid signer key: {e}"
    
    # If we have an expected key, verify it matches
    if expected_key is not None:
        expected_b64 = base64.b64encode(
            expected_key.public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode()
        
        if signer_key_b64 != expected_b64:
            return False, "Signer key does not match expected key"
    
    # Verify signature
    try:
        signature = base64.b64decode(signature_b64)
        signer_key.verify(signature, stored_hash.encode("utf-8"))
    except InvalidSignature:
        return False, "Invalid signature"
    except Exception as e:
        return False, f"Signature verification error: {e}"
    
    # All checks passed
    return True, f"Valid (signed {signed_at})"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify SKILL.md file signatures",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "skills",
        nargs="+",
        type=Path,
        help="SKILL.md files to verify",
    )
    parser.add_argument(
        "--public-key",
        type=Path,
        default=None,
        help="Path to expected public key PEM file (optional)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only output failures",
    )
    
    args = parser.parse_args()
    
    # Load expected key if provided
    expected_key = None
    if args.public_key:
        try:
            expected_key = load_public_key_from_file(args.public_key)
        except Exception as e:
            print(f"Error loading public key: {e}")
            return 2
    
    # Verify each skill
    all_passed = True
    for skill_path in args.skills:
        success, message = verify_skill(skill_path, expected_key)
        
        if success:
            if not args.quiet:
                print(f"{color('✓', Colors.GREEN)} {skill_path}: {message}")
        else:
            all_passed = False
            print(f"{color('✗', Colors.RED)} {skill_path}: {color(message, Colors.RED)}")
    
    if all_passed:
        if not args.quiet:
            print()
            print(color(f"All {len(args.skills)} skill(s) verified successfully", Colors.GREEN + Colors.BOLD))
        return 0
    else:
        print()
        print(color("Verification failed!", Colors.RED + Colors.BOLD))
        return 1


if __name__ == "__main__":
    sys.exit(main())
