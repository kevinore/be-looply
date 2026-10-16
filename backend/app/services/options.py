"""Product options: groups of choices a product needs at sale time.

Generic for any business. A product linked to option groups (e.g. "Base", "Té")
must be sold with between min_select and max_select active choices of each
group. Each choice can add to the unit price (price_delta_cop); the backend
computes it (R3) and copies the chosen names and prices to sale_item_option.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import (
    OptionChoice,
    OptionGroup,
    Product,
    ProductCategory,
    ProductOptionGroup,
    SaleItem,
    SaleItemOption,
)


@dataclass
class GroupConfig:
    group: OptionGroup
    choices: list[OptionChoice] = field(default_factory=list)


async def product_groups(
    db: AsyncSession, product_ids: list[UUID]
) -> dict[UUID, list[GroupConfig]]:
    """Active option groups of each product, in display order, with active choices."""
    if not product_ids:
        return {}
    rows = (
        await db.execute(
            select(ProductOptionGroup.product_id, OptionGroup)
            .join(OptionGroup, OptionGroup.id == ProductOptionGroup.group_id)
            .where(
                ProductOptionGroup.product_id.in_(product_ids),
                ProductOptionGroup.active.is_(True),
                OptionGroup.active.is_(True),
            )
            .order_by(
                ProductOptionGroup.sort_order, OptionGroup.sort_order, OptionGroup.name
            )
        )
    ).all()
    group_ids = {g.id for _, g in rows}
    choices: dict[UUID, list[OptionChoice]] = defaultdict(list)
    if group_ids:
        for c in (
            await db.execute(
                select(OptionChoice)
                .where(
                    OptionChoice.group_id.in_(group_ids), OptionChoice.active.is_(True)
                )
                .order_by(OptionChoice.sort_order, OptionChoice.name)
            )
        ).scalars():
            choices[c.group_id].append(c)
    out: dict[UUID, list[GroupConfig]] = defaultdict(list)
    for product_id, group in rows:
        out[product_id].append(GroupConfig(group, choices[group.id]))
    return out


async def catalog(db: AsyncSession, business_id: UUID) -> list[dict]:
    """GET /api/admin/products: active products with their option groups.

    Ordered by category (sections of the sale screen), then by product. Products
    without an active category come last.
    """
    rows = (
        await db.execute(
            select(Product, ProductCategory.name)
            .outerjoin(
                ProductCategory,
                (ProductCategory.id == Product.category_id)
                & ProductCategory.active.is_(True),
            )
            .where(Product.business_id == business_id, Product.active.is_(True))
            .order_by(
                ProductCategory.sort_order.asc().nulls_last(),
                ProductCategory.name,
                Product.sort_order,
                Product.name,
            )
        )
    ).all()
    products = [p for p, _ in rows]
    category = {p.id: name for p, name in rows}
    groups = await product_groups(db, [p.id for p in products])
    return [
        {
            "id": p.id,
            "name": p.name,
            "price_cop": p.price_cop,
            "photo_url": p.photo_url,
            "description": p.description,
            "category": category[p.id],
            "category_id": p.category_id,
            "prize_eligible": p.prize_eligible,
            "option_groups": [
                {
                    "id": g.group.id,
                    "name": g.group.name,
                    "min_select": g.group.min_select,
                    "max_select": g.group.max_select,
                    "options": [
                        {
                            "id": c.id,
                            "name": c.name,
                            "price_delta_cop": c.price_delta_cop,
                        }
                        for c in g.choices
                    ],
                }
                for g in groups.get(p.id, [])
            ],
        }
        for p in products
    ]


def resolve_choices(
    groups: list[GroupConfig], option_ids: list[UUID]
) -> list[tuple[OptionGroup, OptionChoice]]:
    """Validate the chosen options of one line; returns them in display order.

    Every option must be an active choice of a group linked to the product, and
    each group needs between min_select and max_select choices.
    """
    if len(option_ids) != len(set(option_ids)):
        raise AppError("options_invalid")
    wanted = set(option_ids)
    chosen: list[tuple[OptionGroup, OptionChoice]] = []
    for g in groups:
        picked = [c for c in g.choices if c.id in wanted]
        if not g.group.min_select <= len(picked) <= g.group.max_select:
            raise AppError("options_invalid")
        chosen += [(g.group, c) for c in picked]
    if len(chosen) != len(wanted):  # an option that is not offered for this product
        raise AppError("options_invalid")
    return chosen


def option_rows(chosen: list[tuple[OptionGroup, OptionChoice]]) -> list[dict]:
    """Copies for sale_item_option (names and price at sale time)."""
    return [
        {
            "option_id": c.id,
            "group_name": g.name,
            "option_name": c.name,
            "price_delta_cop": c.price_delta_cop,
        }
        for g, c in chosen
    ]


def add_item_options(db: AsyncSession, item: SaleItem, rows: list[dict]) -> None:
    db.add_all(SaleItemOption(sale_item_id=item.id, **row) for row in rows)


async def options_by_item(
    db: AsyncSession, item_ids: list[UUID]
) -> dict[UUID, list[dict]]:
    """Chosen options of each sale line, in the order of the current configuration."""
    if not item_ids:
        return {}
    rows = (
        await db.execute(
            select(SaleItemOption)
            .join(OptionChoice, OptionChoice.id == SaleItemOption.option_id)
            .join(OptionGroup, OptionGroup.id == OptionChoice.group_id)
            .where(SaleItemOption.sale_item_id.in_(item_ids))
            .order_by(
                OptionGroup.sort_order,
                SaleItemOption.group_name,
                OptionChoice.sort_order,
                SaleItemOption.option_name,
            )
        )
    ).scalars()
    out: dict[UUID, list[dict]] = defaultdict(list)
    for o in rows:
        out[o.sale_item_id].append(
            {
                "group_name": o.group_name,
                "option_name": o.option_name,
                "price_delta_cop": o.price_delta_cop,
            }
        )
    return out


async def item_dicts(db: AsyncSession, items: list[SaleItem]) -> list[dict]:
    """Sale lines as response dicts, each with its chosen options."""
    options = await options_by_item(db, [i.id for i in items])
    return [
        {
            "product_id": i.product_id,
            "label": i.label,
            "qty": i.qty,
            "unit_price_cop": i.unit_price_cop,
            "discount_cop": i.discount_cop,
            "prize_award_id": i.prize_award_id,
            "options": options.get(i.id, []),
        }
        for i in items
    ]
