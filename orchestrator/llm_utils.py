from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from groq import RateLimitError
import logging
import httpx

logger = logging.getLogger("llm_utils")


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, max=10),
    retry=retry_if_exception_type(RateLimitError),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def invoke_llm_with_retry(llm, messages_or_prompt):
    return llm.invoke(messages_or_prompt)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=8),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def post_with_retry(url: str, **kwargs):
    return httpx.post(url, **kwargs)