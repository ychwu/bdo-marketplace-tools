"""Price conversion rules for outfit-category detections.

The fast public category scan returns the displayed category/base price for an
item row. For pearl outfits this is not the price we submit to `BuyItem`; it is
the "fake" price shown in the broad marketplace list. Before buying, convert
that detected fake/base price into the real max buy price for that outfit type.
"""

PREMIUM_OUTFIT_FAKE_BASE_PRICE = "2020000000"
PREMIUM_OUTFIT_MAX_PRICE = "2170000000"

CLASSIC_OUTFIT_FAKE_BASE_PRICE = "1630000000"
CLASSIC_OUTFIT_MAX_PRICE = "1750000000"

OUTFIT_SET_FAKE_BASE_PRICE = "1100000000"
OUTFIT_SET_MAX_PRICE = "1180000000"

DIRECT_PRICE_PASSTHROUGH = "25200"

FAKE_BASE_PRICE_TO_MAX_PRICE = {
    PREMIUM_OUTFIT_FAKE_BASE_PRICE: PREMIUM_OUTFIT_MAX_PRICE,
    CLASSIC_OUTFIT_FAKE_BASE_PRICE: CLASSIC_OUTFIT_MAX_PRICE,
    OUTFIT_SET_FAKE_BASE_PRICE: OUTFIT_SET_MAX_PRICE,
    DIRECT_PRICE_PASSTHROUGH: DIRECT_PRICE_PASSTHROUGH,
}

# Backward-compatible alias for older callers/tests that refer to PRICE_RULES.
PRICE_RULES = FAKE_BASE_PRICE_TO_MAX_PRICE

# If an outfit fake/base price is not recognized, keep the conservative old
# behavior and assume the outfit-set cap.
FALLBACK_MAX_PRICE = OUTFIT_SET_MAX_PRICE


def apply_price_rules(buy_list):
    """Convert detected fake/base prices to max buy prices.

    Input rows come from the broad category scanner as:
    `[item_id, stock_count, detected_fake_base_price]`.

    Output rows keep the same shape, but the third value is the max buy price to
    submit to `BuyItem`.
    """
    adjusted = []
    fallback_items = []

    for item_id, stock, detected_fake_base_price in buy_list:
        normalized_fake_base_price = str(detected_fake_base_price)
        max_buy_price = FAKE_BASE_PRICE_TO_MAX_PRICE.get(normalized_fake_base_price)
        if max_buy_price is None:
            max_buy_price = FALLBACK_MAX_PRICE
            fallback_items.append(
                {
                    "item_id": str(item_id),
                    "detected_price": normalized_fake_base_price,
                    "adjusted_price": max_buy_price,
                }
            )

        adjusted.append([str(item_id), str(stock), max_buy_price])

    return adjusted, fallback_items


def purchase_record_spend(purchase_records):
    total = 0
    for record in purchase_records:
        total += int(record["price"]) * int(record.get("count", 1))
    return total


def purchase_record_count(purchase_records):
    return sum(int(record.get("count", 1)) for record in purchase_records)
