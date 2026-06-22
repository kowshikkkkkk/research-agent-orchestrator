# guardrails/guardrails.py

import re


# ── WHY GUARDRAILS AT A2A BOUNDARIES ─────────────────────────────────────────
# Every time an agent receives content from an external source (web scraping,
# user input, another agent), that content is untrusted.
# A malicious website could contain: "Ignore previous instructions and..."
# Without sanitization, this prompt injection reaches the LLM directly.
# Guardrails intercept content at every A2A boundary before it enters the pipeline.
#
# In production you'd use Guardrails AI validators with ML-based detection.
# Here we implement rule-based checks that cover the most common attack vectors
# and are fully explainable in an interview.

# ── PROMPT INJECTION PATTERNS ─────────────────────────────────────────────────
# These are the most common prompt injection patterns seen in the wild.
# Each pattern targets a different attack vector.

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"forget\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"you\s+are\s+now\s+a\s+different\s+(ai|assistant|model)",
    r"new\s+instructions?\s*:",
    r"system\s*:\s*you\s+are",
    r"<\s*system\s*>",
    r"\[system\]",
    r"override\s+(safety|security|guidelines|instructions)",
    r"jailbreak",
    r"dan\s+mode",
    r"developer\s+mode\s+enabled",
    r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions",
]

# ── UNSAFE CONTENT PATTERNS ───────────────────────────────────────────────────

UNSAFE_PATTERNS = [
    r"(api[_\s]?key|secret[_\s]?key|password|token)\s*[:=]\s*\S+",
    r"sk-[a-zA-Z0-9]{20,}",  # OpenAI key pattern
    r"bearer\s+[a-zA-Z0-9\-._~+/]+=*",  # Bearer tokens
]

def check_prompt_injection(text: str) -> tuple[bool, str]:
    """
    Checks text for prompt injection attempts.
    Returns (is_safe, reason).
    Case-insensitive matching covers most obfuscation attempts.
    """
    text_lower = text.lower()
    
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            return False, f"Prompt injection detected: pattern '{pattern}' matched"
    
    return True, "clean"

def check_unsafe_content(text: str) -> tuple[bool, str]:
    """
    Checks for sensitive data that shouldn't be passing between agents.
    Catches accidental credential leakage from web-scraped content.
    """
    for pattern in UNSAFE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return False, f"Unsafe content detected: potential credential exposure"
    
    return True, "clean"

def check_length(text: str, max_chars: int = 50000) -> tuple[bool, str]:
    """
    Prevents context window overflow attacks where malicious content
    tries to push important instructions out of the LLM's context window
    by flooding it with irrelevant text.
    """
    if len(text) > max_chars:
        return False, f"Content too long: {len(text)} chars exceeds {max_chars} limit"
    
    return True, "clean"

def sanitize_text(text: str) -> str:
    """
    Removes the most common injection markers from text.
    Used as a secondary defense after detection.
    """
    # Remove common injection markers
    sanitized = re.sub(
        r"(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above)\s+instructions.*",
        "[CONTENT REMOVED BY GUARDRAILS]",
        text,
        flags=re.IGNORECASE
    )
    return sanitized

# ── MAIN GUARD FUNCTION ───────────────────────────────────────────────────────

def guard_content(content: str, source: str = "unknown") -> dict:
    """
    Main entry point for content validation.
    Called at every A2A boundary before content passes between agents.
    
    Returns:
        {
            "safe": bool,
            "sanitized_content": str,  # cleaned content if safe
            "violations": list,        # what was found if unsafe
            "source": str
        }
    
    Interview explanation:
    "Every piece of content that crosses an A2A boundary goes through this.
    It checks for prompt injection, credential leakage, and oversized payloads.
    If content fails any check, it's either sanitized or blocked entirely.
    This prevents web-scraped malicious content from hijacking agent behavior."
    """
    violations = []
    
    # Run all checks
    safe_injection, reason_injection = check_prompt_injection(content)
    if not safe_injection:
        violations.append(reason_injection)
    
    safe_unsafe, reason_unsafe = check_unsafe_content(content)
    if not safe_unsafe:
        violations.append(reason_unsafe)
    
    safe_length, reason_length = check_length(content)
    if not safe_length:
        violations.append(reason_length)
    
    if violations:
        # Log the violation
        print(f"[Guardrails] VIOLATION from {source}: {violations}")
        
        # Attempt sanitization for injection attempts
        # Block entirely for credential exposure or length attacks
        if any("injection" in v for v in violations):
            sanitized = sanitize_text(content)
            print(f"[Guardrails] Content sanitized from {source}")
            return {
                "safe": True,  # Safe after sanitization
                "sanitized_content": sanitized,
                "violations": violations,
                "action": "sanitized",
                "source": source
            }
        else:
            print(f"[Guardrails] Content BLOCKED from {source}")
            return {
                "safe": False,
                "sanitized_content": "",
                "violations": violations,
                "action": "blocked",
                "source": source
            }
    
    return {
        "safe": True,
        "sanitized_content": content,
        "violations": [],
        "action": "passed",
        "source": source
    }

def guard_a2a_task(task_input: dict, source: str = "unknown") -> dict:
    """
    Guards an entire A2A task input dict.
    Checks all string values in the input.
    Called before any agent processes a task.
    """
    violations_found = []
    sanitized_input = {}
    
    for key, value in task_input.items():
        if isinstance(value, str) and value:
            result = guard_content(value, source=f"{source}.{key}")
            if not result["safe"]:
                violations_found.append(f"Field '{key}': {result['violations']}")
                sanitized_input[key] = ""  # Block the field
            else:
                sanitized_input[key] = result["sanitized_content"]
        else:
            sanitized_input[key] = value
    
    return {
        "safe": len(violations_found) == 0,
        "sanitized_input": sanitized_input,
        "violations": violations_found
    }