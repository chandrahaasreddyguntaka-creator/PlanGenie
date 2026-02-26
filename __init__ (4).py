"""Multi-Gemini key management with round-robin fallback."""
import os
from typing import List, Dict, Optional
from collections import deque
import threading


class KeyManager:
    """Manages multiple Gemini API keys with role assignments and round-robin fallback."""
    
    def __init__(self):
        self._keys: List[str] = []
        self._key_pool: deque = deque()
        self._assignments: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._load_keys()
        self._assign_roles()
    
    def _load_keys(self):
        """Load keys from environment variables."""
        keys = []
        
        # Try GEMINI_KEYS (CSV format)
        gemini_keys_env = os.getenv("GEMINI_KEYS", "")
        if gemini_keys_env:
            keys.extend([k.strip() for k in gemini_keys_env.split(",") if k.strip()])
        
        # Try GEMINI_KEY_1, GEMINI_KEY_2, etc.
        i = 1
        while True:
            key = os.getenv(f"GEMINI_KEY_{i}")
            if not key:
                break
            if key.strip():
                keys.append(key.strip())
            i += 1
        
        # Deduplicate while preserving order
        seen = set()
        for key in keys:
            if key and key not in seen:
                seen.add(key)
                self._keys.append(key)
        
        if not self._keys:
            raise ValueError(
                "No Gemini API keys found. Set GEMINI_KEYS or GEMINI_KEY_1, GEMINI_KEY_2, etc."
            )
        
        self._key_pool = deque(self._keys)
    
    def _assign_roles(self):
        """Assign keys to roles. If fewer keys than roles, share keys."""
        roles = ["ORCHESTRATOR", "FLIGHTS", "HOTELS", "ITINERARY", "SUMMARY"]
        
        # Assign unique keys until exhausted, then share
        for i, role in enumerate(roles):
            key_index = i % len(self._keys)
            self._assignments[role] = self._keys[key_index]
    
    def get_key_for_role(self, role: str) -> str:
        """Get the assigned key for a role."""
        return self._assignments.get(role, self._keys[0])
    
    def next_key(self) -> str:
        """Get next key in round-robin order (for retries)."""
        with self._lock:
            if not self._key_pool:
                self._key_pool = deque(self._keys)
            key = self._key_pool.popleft()
            self._key_pool.append(key)
            return key
    
    def get_all_keys(self) -> List[str]:
        """Get all available keys."""
        return self._keys.copy()
    
    def get_assignments(self) -> Dict[str, str]:
        """Get current role-to-key assignments."""
        return self._assignments.copy()


# Global singleton instance
_key_manager: Optional[KeyManager] = None


def get_key_manager() -> KeyManager:
    """Get the global KeyManager instance."""
    global _key_manager
    if _key_manager is None:
        _key_manager = KeyManager()
    return _key_manager

