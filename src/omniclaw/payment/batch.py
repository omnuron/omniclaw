"""
Batch Payment Processor.

Handles execution of multiple payments concurrently.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from omniclaw.core.types import PaymentRequest, PaymentResult, PaymentStatus


@dataclass
class BatchPaymentResult:
    """Result of a batch payment operation."""

    total_count: int
    success_count: int
    failed_count: int
    results: list[PaymentResult]
    transaction_ids: list[str] = field(default_factory=list)


if TYPE_CHECKING:
    from omniclaw.payment.router import PaymentRouter


class BatchProcessor:
    """Processor for batch payments."""

    def __init__(self, router: PaymentRouter) -> None:
        self._router = router

    async def process(
        self, requests: list[PaymentRequest], concurrency: int = 5
    ) -> BatchPaymentResult:
        """Execute multiple payments concurrently."""
        sem = asyncio.Semaphore(concurrency)

        async def _bounded_pay(req: PaymentRequest) -> PaymentResult:
            async with sem:
                # Convert PaymentRequest to kwargs
                # Note: PaymentRequest validation happened at init
                return await self._router.pay(
                    wallet_id=req.wallet_id,
                    recipient=req.recipient,
                    amount=req.amount,
                    purpose=req.purpose,
                    idempotency_key=req.idempotency_key,
                    destination_chain=req.destination_chain,
                    **req.metadata,
                )

        # Create tasks
        tasks = [_bounded_pay(req) for req in requests]

        # Run
        # return_exceptions=True? No, we want PaymentResult objects.
        # But if pay() raises unhandled exception, we should catch it.
        # Router.pay() generally catches and returns FAILED result?
        # Let's verify Router.pay catches exceptions.
        # Checking router.py...
        # It catches specific ones but maybe not all.
        # Safe to wrap?

        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_results: list[PaymentResult] = []
        for i, res in enumerate(results):
            if isinstance(res, PaymentResult):
                final_results.append(res)
            elif isinstance(res, Exception):
                # Synthesis failed result
                req = requests[i]
                final_results.append(
                    PaymentResult(
                        success=False,
                        transaction_id=None,
                        blockchain_tx=None,
                        amount=req.amount,
                        recipient=req.recipient,
                        method=None,  # type: ignore
                        status=PaymentStatus.FAILED,
                        error=str(res),
                    )
                )

        # Aggregate
        success_count = sum(1 for r in final_results if r.success)
        failed_count = len(final_results) - success_count
        tx_ids = [r.transaction_id for r in final_results if r.transaction_id]

        return BatchPaymentResult(
            total_count=len(final_results),
            success_count=success_count,
            failed_count=failed_count,
            results=final_results,
            transaction_ids=tx_ids,
        )
