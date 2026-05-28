PRICE_RULES = {
    "2020000000": "2170000000",
    "1630000000": "1750000000",
    "25200": "25200",
}
FALLBACK_MAX_PRICE = "1180000000"


def apply_price_rules(buy_list):
    adjusted = []
    fallback_items = []

    for item_id, stock, price in buy_list:
        normalized_price = str(price)
        adjusted_price = PRICE_RULES.get(normalized_price)
        if adjusted_price is None:
            adjusted_price = FALLBACK_MAX_PRICE
            fallback_items.append(
                {
                    "item_id": str(item_id),
                    "detected_price": normalized_price,
                    "adjusted_price": adjusted_price,
                }
            )

        adjusted.append([str(item_id), str(stock), adjusted_price])

    return adjusted, fallback_items


def purchase_record_spend(purchase_records):
    total = 0
    for record in purchase_records:
        total += int(record["price"]) * int(record.get("count", 1))
    return total


def purchase_record_count(purchase_records):
    return sum(int(record.get("count", 1)) for record in purchase_records)
