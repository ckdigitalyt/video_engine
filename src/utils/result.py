"""
result.py — Result<T> type for structured error handling.

Every function that can fail returns a Result[T] instead of silently returning
empty strings or None. Failures include: reason, provider, query, HTTP status,
exception, and retry count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar


T = TypeVar("T")


@dataclass
class FailureDetail:
    """Detailed failure information."""

    reason: str
    provider: str = ""
    query: str = ""
    http_status: int = 0
    exception: str = ""
    retry_count: int = 0

    def __str__(self) -> str:
        parts = [f"Reason: {self.reason}"]
        if self.provider:
            parts.append(f"Provider: {self.provider}")
        if self.query:
            parts.append(f"Query: {self.query}")
        if self.http_status:
            parts.append(f"HTTP: {self.http_status}")
        if self.exception:
            parts.append(f"Exception: {self.exception}")
        if self.retry_count:
            parts.append(f"Retry: {self.retry_count}")
        return " | ".join(parts)


@dataclass
class RetryDetail:
    """Information about a retryable operation."""

    reason: str
    provider: str = ""
    query: str = ""
    retry_count: int = 0
    max_retries: int = 3
    fatal: bool = False


class Result(Generic[T]):
    """Result type that is either Success, Failure, or Retry.

    Never silently returns empty values. Every path is explicit.

    Usage::

        def fetch_asset(query: str) -> Result[list]:
            try:
                results = provider.search(query)
                if results:
                    return Result.success(results)
                return Result.failure("No results", provider="pexels", query=query)
            except Exception as e:
                return Result.retry(f"HTTP error", exception=str(e))

        result = fetch_asset("spiral galaxy")
        if result.is_success:
            assets = result.data
        elif result.is_retry:
            # Retry logic
            ...
        else:
            log.error(result.failure)
    """

    def __init__(
        self,
        data: Optional[T] = None,
        failure: Optional[FailureDetail] = None,
        retry: Optional[RetryDetail] = None,
    ):
        self._data = data
        self._failure = failure
        self._retry = retry

    # ── Factory constructors ────────────────────────────────────────────

    @classmethod
    def success(cls, data: T) -> "Result[T]":
        return cls(data=data)

    @classmethod
    def failure(
        cls,
        reason: str,
        provider: str = "",
        query: str = "",
        http_status: int = 0,
        exception: str = "",
        retry_count: int = 0,
    ) -> "Result[T]":
        return cls(
            failure=FailureDetail(
                reason=reason, provider=provider, query=query,
                http_status=http_status, exception=exception,
                retry_count=retry_count,
            )
        )

    @classmethod
    def retry(
        cls,
        reason: str,
        provider: str = "",
        query: str = "",
        retry_count: int = 0,
        max_retries: int = 3,
        fatal: bool = False,
    ) -> "Result[T]":
        return cls(
            retry=RetryDetail(
                reason=reason, provider=provider, query=query,
                retry_count=retry_count, max_retries=max_retries,
                fatal=fatal,
            )
        )

    # ── Properties ───────────────────────────────────────────────────────

    @property
    def is_success(self) -> bool:
        return self._data is not None

    @property
    def is_failure(self) -> bool:
        return self._failure is not None

    @property
    def is_retry(self) -> bool:
        return self._retry is not None

    @property
    def data(self) -> T:
        if not self.is_success:
            raise ValueError("Cannot access data on a non-success Result")
        return self._data  # type: ignore

    @property
    def failure_detail(self) -> FailureDetail:
        if not self.is_failure:
            raise ValueError("Not a failure Result")
        return self._failure  # type: ignore

    @property
    def retry_detail(self) -> RetryDetail:
        if not self.is_retry:
            raise ValueError("Not a retry Result")
        return self._retry  # type: ignore

    def unwrap(self) -> T:
        """Get the value or raise."""
        if self.is_success:
            return self._data  # type: ignore
        if self.is_failure:
            raise RuntimeError(str(self._failure))
        raise RuntimeError(f"Retry needed: {self._retry}")

    def unwrap_or(self, default: T) -> T:
        """Get value or default."""
        return self._data if self.is_success else default

    def __str__(self) -> str:
        if self.is_success:
            return f"Success({self._data!r})"
        if self.is_failure:
            return str(self._failure)
        return str(self._retry)

    def __repr__(self) -> str:
        return self.__str__()
