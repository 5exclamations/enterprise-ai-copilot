"""Deterministic order pricing. The LLM never does arithmetic: it calls the calculator tool.

Rules (mirrored in the sample "Pricing and Discounts" / "Shipping" policy documents):
* tier discount on list price: standard 0%, gold 5%, platinum 10%
* +2% volume discount when the pre-discount subtotal is >= $2,000
* tax 8% on the discounted goods value (shipping is not taxed)
* standard shipping $25, free when discounted goods >= $500; express $60 flat
* hazmat surcharge $35 per shipment when any hazmat item is present (ground only)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

TIER_DISCOUNT = {"standard": Decimal("0"), "gold": Decimal("5"), "platinum": Decimal("10")}
VOLUME_THRESHOLD = Decimal("2000")
VOLUME_DISCOUNT = Decimal("2")
TAX_RATE = Decimal("0.08")
FREE_SHIPPING_MIN = Decimal("500")
STANDARD_SHIPPING = Decimal("25")
EXPRESS_SHIPPING = Decimal("60")
HAZMAT_SURCHARGE = Decimal("35")

CENT = Decimal("0.01")


def money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Line:
    sku: str
    name: str
    quantity: int
    unit_price: Decimal
    hazmat: bool = False

    @property
    def total(self) -> Decimal:
        return money(self.unit_price * self.quantity)


@dataclass
class Quote:
    lines: list[Line]
    tier: str
    shipping_method: str
    subtotal: Decimal = Decimal("0")
    discount_pct: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    goods_after_discount: Decimal = Decimal("0")
    shipping: Decimal = Decimal("0")
    hazmat_surcharge: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        s = lambda d: str(money(d))  # noqa: E731
        return {
            "lines": [{"sku": l.sku, "name": l.name, "quantity": l.quantity, "unit_price": s(l.unit_price),
                       "line_total": s(l.total)} for l in self.lines],
            "tier": self.tier, "shipping_method": self.shipping_method, "subtotal": s(self.subtotal),
            "discount_pct": str(self.discount_pct), "discount": s(self.discount),
            "goods_after_discount": s(self.goods_after_discount), "shipping": s(self.shipping),
            "hazmat_surcharge": s(self.hazmat_surcharge), "tax": s(self.tax), "total": s(self.total),
            "notes": self.notes,
        }


def quote(lines: list[Line], tier: str = "standard", shipping_method: str = "standard") -> Quote:
    q = Quote(lines=lines, tier=tier, shipping_method=shipping_method)
    q.subtotal = money(sum((l.total for l in lines), Decimal("0")))
    q.discount_pct = TIER_DISCOUNT.get(tier, Decimal("0"))
    if q.discount_pct:
        q.notes.append(f"{tier} tier discount {q.discount_pct}%")
    if q.subtotal >= VOLUME_THRESHOLD:
        q.discount_pct += VOLUME_DISCOUNT
        q.notes.append(f"volume discount {VOLUME_DISCOUNT}% (subtotal >= ${VOLUME_THRESHOLD})")
    q.discount = money(q.subtotal * q.discount_pct / 100)
    q.goods_after_discount = q.subtotal - q.discount
    if shipping_method == "express":
        q.shipping = EXPRESS_SHIPPING
    elif q.goods_after_discount >= FREE_SHIPPING_MIN:
        q.shipping = Decimal("0")
        q.notes.append("free standard shipping (goods >= $500)")
    else:
        q.shipping = STANDARD_SHIPPING
    if any(l.hazmat for l in lines):
        q.hazmat_surcharge = HAZMAT_SURCHARGE
        q.notes.append("hazmat surcharge applied")
    q.tax = money(q.goods_after_discount * TAX_RATE)
    q.total = money(q.goods_after_discount + q.shipping + q.hazmat_surcharge + q.tax)
    return q
