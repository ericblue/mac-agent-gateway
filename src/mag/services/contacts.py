"""Contact cache service for message recipient resolution."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mag.config import get_settings
from mag.models.messages import Contact, ContactResolveResult, ContactUpsert

logger = logging.getLogger(__name__)


class ContactCache:
    """In-memory contact cache with JSON file persistence."""

    def __init__(self, file_path: Path | None = None) -> None:
        """Initialize the contact cache.

        Args:
            file_path: Path to JSON file for persistence. If None, uses config.
        """
        self._contacts: dict[str, Contact] = {}
        self._file_path = file_path or get_settings().contacts_path

        # Phone/email to contact ID lookup
        self._phone_index: dict[str, str] = {}
        self._email_index: dict[str, str] = {}

        # Load existing contacts
        self._load()

    def _load(self) -> None:
        """Load contacts from JSON file."""
        if not self._file_path.exists():
            logger.debug("Contacts file does not exist: %s", self._file_path)
            return

        try:
            with open(self._file_path) as f:
                data = json.load(f)

            if isinstance(data, list):
                for item in data:
                    contact = Contact(**item)
                    self._contacts[contact.id] = contact
                    self._index_contact(contact)

            logger.info("Loaded %d contacts from %s", len(self._contacts), self._file_path)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load contacts from %s: %s", self._file_path, e)

    def _save(self) -> None:
        """Save contacts to JSON file with secure permissions."""
        try:
            # Ensure directory exists with secure permissions (owner-only)
            self._file_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

            with open(self._file_path, "w") as f:
                contacts_list = [c.model_dump(mode="json") for c in self._contacts.values()]
                json.dump(contacts_list, f, indent=2, default=str)

            # Security: Set file permissions to owner read/write only (600)
            import os
            os.chmod(self._file_path, 0o600)

            logger.debug("Saved %d contacts to %s", len(self._contacts), self._file_path)
        except OSError as e:
            logger.error("Failed to save contacts to %s: %s", self._file_path, e)

    def _index_contact(self, contact: Contact) -> None:
        """Add contact to lookup indices."""
        for phone in contact.phones:
            normalized = self._normalize_phone(phone)
            self._phone_index[normalized] = contact.id
        for email in contact.emails:
            self._email_index[email.lower()] = contact.id

    def _unindex_contact(self, contact: Contact) -> None:
        """Remove contact from lookup indices."""
        for phone in contact.phones:
            normalized = self._normalize_phone(phone)
            self._phone_index.pop(normalized, None)
        for email in contact.emails:
            self._email_index.pop(email.lower(), None)

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Normalize a phone number for lookup.

        Basic normalization: remove non-digit characters except leading +.
        Full E.164 normalization would require a library like phonenumbers.
        """
        phone = phone.strip()
        if phone.startswith("+"):
            # Keep the + and digits only
            return "+" + "".join(c for c in phone[1:] if c.isdigit())
        # Remove all non-digits
        return "".join(c for c in phone if c.isdigit())

    def upsert(self, data: ContactUpsert) -> Contact:
        """Create or update a contact.

        Matches by phone or email if present, otherwise creates new.

        Args:
            data: Contact data to upsert.

        Returns:
            The created or updated Contact.
        """
        # Try to find existing contact by phone or email
        existing_id: str | None = None

        for phone in data.phones:
            normalized = self._normalize_phone(phone)
            if normalized in self._phone_index:
                existing_id = self._phone_index[normalized]
                break

        if not existing_id:
            for email in data.emails:
                if email.lower() in self._email_index:
                    existing_id = self._email_index[email.lower()]
                    break

        if existing_id and existing_id in self._contacts:
            # Update existing contact
            contact = self._contacts[existing_id]
            self._unindex_contact(contact)

            # Merge data
            contact.name = data.name or contact.name
            contact.phones = list(set(contact.phones + data.phones))
            contact.emails = list(set(contact.emails + data.emails))
            contact.aliases = list(set(contact.aliases + data.aliases))
            contact.updated_at = datetime.now()
        else:
            # Create new contact
            contact = Contact(
                name=data.name,
                phones=data.phones,
                emails=data.emails,
                aliases=data.aliases,
            )
            self._contacts[contact.id] = contact

        self._index_contact(contact)
        self._save()
        return contact

    def get(self, contact_id: str) -> Contact | None:
        """Get a contact by ID."""
        return self._contacts.get(contact_id)

    def resolve(
        self,
        phone: str | None = None,
        email: str | None = None,
        name: str | None = None,
    ) -> ContactResolveResult:
        """Resolve a contact by phone, email, or name.

        Resolution order:
        1. Direct phone match
        2. Email match
        3. Exact name match (case-insensitive)
        4. Substring name/alias match if unambiguous

        Args:
            phone: Phone number to match.
            email: Email address to match.
            name: Name or alias to match.

        Returns:
            ContactResolveResult with status and match(es).
        """
        # 1. Direct phone match
        if phone:
            normalized = self._normalize_phone(phone)
            if contact_id := self._phone_index.get(normalized):
                if contact := self._contacts.get(contact_id):
                    return ContactResolveResult(status="ok", contact=contact)

        # 2. Email match
        if email:
            if contact_id := self._email_index.get(email.lower()):
                if contact := self._contacts.get(contact_id):
                    return ContactResolveResult(status="ok", contact=contact)

        # 3. Exact name match (case-insensitive)
        if name:
            name_lower = name.lower()
            exact_matches: list[Contact] = []

            for contact in self._contacts.values():
                if contact.name and contact.name.lower() == name_lower:
                    exact_matches.append(contact)

            if len(exact_matches) == 1:
                return ContactResolveResult(status="ok", contact=exact_matches[0])
            if len(exact_matches) > 1:
                return ContactResolveResult(status="ambiguous", candidates=exact_matches)

            # 4. Substring match on name and aliases
            substring_matches: list[Contact] = []

            for contact in self._contacts.values():
                if contact.name and name_lower in contact.name.lower():
                    substring_matches.append(contact)
                    continue

                for alias in contact.aliases:
                    if name_lower in alias.lower():
                        substring_matches.append(contact)
                        break

            if len(substring_matches) == 1:
                return ContactResolveResult(status="ok", contact=substring_matches[0])
            if len(substring_matches) > 1:
                return ContactResolveResult(status="ambiguous", candidates=substring_matches)

        return ContactResolveResult(status="not_found")

    def search(self, query: str, limit: int = 20) -> list[Contact]:
        """Search contacts by substring match.

        Searches name, aliases, phones, and emails.

        Args:
            query: Search query (case-insensitive).
            limit: Maximum results to return.

        Returns:
            List of matching Contact objects.
        """
        query_lower = query.lower()
        results: list[Contact] = []

        for contact in self._contacts.values():
            if len(results) >= limit:
                break

            # Check name
            if contact.name and query_lower in contact.name.lower():
                results.append(contact)
                continue

            # Check aliases
            if any(query_lower in alias.lower() for alias in contact.aliases):
                results.append(contact)
                continue

            # Check phones
            if any(query in phone for phone in contact.phones):
                results.append(contact)
                continue

            # Check emails
            if any(query_lower in email.lower() for email in contact.emails):
                results.append(contact)
                continue

        return results

    def delete(self, contact_id: str) -> bool:
        """Delete a contact by ID.

        Args:
            contact_id: The contact ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        if contact := self._contacts.pop(contact_id, None):
            self._unindex_contact(contact)
            self._save()
            return True
        return False

    def list_all(self) -> list[Contact]:
        """List all contacts."""
        return list(self._contacts.values())

    def clear(self) -> None:
        """Clear all contacts."""
        self._contacts.clear()
        self._phone_index.clear()
        self._email_index.clear()
        self._save()

    def to_dict(self) -> dict[str, Any]:
        """Export contacts as a dictionary."""
        return {"contacts": [c.model_dump(mode="json") for c in self._contacts.values()]}


# Global contact cache instance (lazy-loaded)
_cache: ContactCache | None = None


def get_contact_cache() -> ContactCache:
    """Get the global contact cache instance."""
    global _cache
    if _cache is None:
        _cache = ContactCache()
    return _cache
