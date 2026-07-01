"""
LLM-enhanced merchant classification via AWS Bedrock (Claude 3 Haiku).

Classifies merchant names into spending categories as a fallback for
keyword-based category matching (Step 7).  Degrades gracefully when
Bedrock is unavailable.
"""

import structlog
from langchain_aws import ChatBedrock

from src.config import settings

logger = structlog.get_logger()


_CLASSIFICATION_PROMPT = (
    "Classify this merchant into one of: Groceries, Dining, Transport, "
    "Utilities, Entertainment, Healthcare, Shopping, Travel, Education, "
    "Uncategorised. Only respond with the category name. Merchant: {merchant_name}"
)


async def classify_merchant_with_bedrock(merchant_name: str) -> str | None:
    """Classify a merchant name into a spending category via Bedrock.

    Parameters
    ----------
    merchant_name:
        The merchant name extracted from the receipt (e.g. "Tesco", "Uber").

    Returns
    -------
    str | None
        One of ``Groceries, Dining, Transport, Utilities, Entertainment,
        Healthcare, Shopping, Travel, Education, Uncategorised``, or
        ``None`` if Bedrock is unavailable or the response is unparseable.
    """
    if not merchant_name.strip():
        return None

    try:
        llm = ChatBedrock(
            model_id=settings.BEDROCK_MODEL_ID,
            region_name=settings.AWS_REGION,
            model_kwargs={
                "temperature": 0,
                "max_tokens": 32,
            },
        )

        prompt = _CLASSIFICATION_PROMPT.format(merchant_name=merchant_name)
        response = await llm.ainvoke(prompt)
        category = response.content.strip()

        valid_categories = {
            "Groceries",
            "Dining",
            "Transport",
            "Utilities",
            "Entertainment",
            "Healthcare",
            "Shopping",
            "Travel",
            "Education",
            "Uncategorised",
        }

        if category not in valid_categories:
            logger.warning(
                "bedrock_unexpected_category",
                merchant=merchant_name,
                category=category,
            )
            return "Uncategorised"

        logger.info(
            "bedrock_classification_successful",
            merchant=merchant_name,
            category=category,
        )
        return category

    except Exception:
        logger.exception("bedrock_classification_failed")
        return None
