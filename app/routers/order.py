import random
from datetime import datetime, timedelta
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app import models
from app.core.deps import get_db, get_current_user, user_roles
from app.schemas.order import OrderCreate, OrderOut
from app.routers.ws import order_broadcaster

router = APIRouter(prefix="/orders", tags=["orders"])


class StatusUpdatePayload(BaseModel):
    status: str | None = None


# Terminal statuses: once an order reaches a terminal status, no further transitions are allowed
TERMINAL_STATUSES = {
    models.OrderStatus.picked_up,
    models.OrderStatus.delivered,
    models.OrderStatus.cancelled,
}

# Strict forward transitions per fulfillment type
PICKUP_TRANSITIONS = {
    models.OrderStatus.pending: {models.OrderStatus.confirmed, models.OrderStatus.preparing, models.OrderStatus.cancelled},
    models.OrderStatus.confirmed: {models.OrderStatus.preparing, models.OrderStatus.cancelled},
    models.OrderStatus.preparing: {models.OrderStatus.ready, models.OrderStatus.cancelled},
    models.OrderStatus.ready: {models.OrderStatus.picked_up, models.OrderStatus.cancelled},
}

DELIVERY_TRANSITIONS = {
    models.OrderStatus.pending: {models.OrderStatus.confirmed, models.OrderStatus.preparing, models.OrderStatus.cancelled},
    models.OrderStatus.confirmed: {models.OrderStatus.preparing, models.OrderStatus.cancelled},
    models.OrderStatus.preparing: {models.OrderStatus.ready, models.OrderStatus.cancelled},
    models.OrderStatus.ready: {models.OrderStatus.out_for_delivery, models.OrderStatus.cancelled},
    models.OrderStatus.out_for_delivery: {models.OrderStatus.delivered, models.OrderStatus.cancelled},
}


async def generate_unique_order_number(db: AsyncSession) -> str:
    for _ in range(15):
        candidate = f"SRK{random.randint(1000, 9999)}"
        exists = await db.scalar(select(models.Order.id).where(models.Order.order_number == candidate))
        if not exists:
            return candidate
    return f"SRK{int(datetime.utcnow().timestamp() * 1000) % 1000000}"


@router.post("/", response_model=OrderOut, status_code=status.HTTP_200_OK)
async def create_order(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Create a new restaurant order with atomic stock validation and deduction.

    Authoritative pricing, stock limits, and customer identity are strictly calculated
    on the backend. Frontend prices and customer IDs are never trusted.
    """
    # 1. Idempotency protection (scoped to customer, double-click / network retry)
    if payload.idempotency_key:
        recent_window = datetime.utcnow() - timedelta(minutes=15)
        existing_order = await db.scalar(
            select(models.Order)
            .options(selectinload(models.Order.items))
            .where(
                models.Order.customer_id == user.id,
                models.Order.idempotency_key == payload.idempotency_key,
                models.Order.created_at >= recent_window,
            )
        )
        if existing_order:
            # Verify payload contents match
            existing_item_map = {oi.menu_item_id: oi.quantity for oi in existing_order.items}
            req_item_map: dict[int, int] = {}
            for i in payload.items:
                req_item_map[i.menu_item_id] = req_item_map.get(i.menu_item_id, 0) + i.quantity

            same_fulfillment = existing_order.fulfillment_type == (payload.fulfillment_type or "pickup").lower().strip()
            same_restaurant = existing_order.restaurant_id == payload.restaurant_id
            same_items = existing_item_map == req_item_map

            if same_fulfillment and same_restaurant and same_items:
                return existing_order
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key already used with different order payload.",
                )

    # 2. Fulfillment type validation
    fulfillment = (payload.fulfillment_type or "pickup").lower().strip()
    if fulfillment not in {"pickup", "delivery"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid fulfillment_type. Must be 'pickup' or 'delivery'.",
        )

    if fulfillment == "delivery":
        addr = (payload.delivery_address or "").strip()
        if not addr or len(addr) < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Delivery address is required for delivery orders.",
            )

    # 3. Item list validation
    if not payload.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order must contain at least one item.",
        )

    # 4. Consolidate requested quantities (prevent duplicate line exploit)
    item_quantities: dict[int, int] = {}
    item_notes: dict[int, str | None] = {}
    for i in payload.items:
        if i.quantity < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Item quantity must be at least 1.",
            )
        item_quantities[i.menu_item_id] = item_quantities.get(i.menu_item_id, 0) + i.quantity
        if i.notes:
            item_notes[i.menu_item_id] = i.notes

    # 5. Fetch authoritative menu items in a SINGLE batch query (prevents N+1 query problem)
    requested_ids = list(item_quantities.keys())
    stmt = select(models.MenuItem).where(models.MenuItem.id.in_(requested_ids))
    fetched_items = (await db.scalars(stmt)).all()
    items_by_id = {item.id: item for item in fetched_items}

    # Validate all requested items exist and belong to the specified restaurant
    for menu_item_id in requested_ids:
        item = items_by_id.get(menu_item_id)
        if not item or item.restaurant_id != payload.restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Menu item #{menu_item_id} does not exist for this restaurant.",
            )
        if not item.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{item.name}' is currently unavailable.",
            )

    subtotal = 0.0
    discount = 0.0
    total = 0.0
    order_items_to_create = []

    order_number = await generate_unique_order_number(db)

    # Validate stock and atomically decrement
    for menu_item_id, qty in item_quantities.items():
        item = items_by_id[menu_item_id]
        if item.stock < qty:
            if item.stock <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="This item is currently out of stock.",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for '{item.name}'. Available: {item.stock}, requested: {qty}.",
            )

        # Atomic query-level stock deduction:
        # WHERE id = :id AND stock >= :qty ensures atomic check-and-decrement at the DB level,
        # preventing race conditions and guaranteeing stock never becomes negative.
        deduct_res = await db.execute(
            update(models.MenuItem)
            .where(models.MenuItem.id == item.id, models.MenuItem.stock >= qty)
            .values(stock=models.MenuItem.stock - qty)
        )
        if deduct_res.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient stock for '{item.name}'. Item may have just sold out.",
            )

        # Authoritative pricing snapshot
        unit_price = float(item.price)
        if item.offer_pct and item.offer_pct > 0:
            effective_unit_price = round(unit_price * (1.0 - item.offer_pct / 100.0), 2)
            discount_per_unit = round(unit_price - effective_unit_price, 2)
        else:
            effective_unit_price = unit_price
            discount_per_unit = 0.0

        line_subtotal = round(unit_price * qty, 2)
        line_discount = round(discount_per_unit * qty, 2)
        line_total = round(effective_unit_price * qty, 2)

        subtotal += line_subtotal
        discount += line_discount
        total += line_total

        # Inventory audit log
        db.add(
            models.InventoryLog(
                restaurant_id=payload.restaurant_id,
                menu_item_id=item.id,
                change=-qty,
                reason=f"order:{order_number}",
            )
        )

        order_items_to_create.append({
            "menu_item_id": item.id,
            "item_name": item.name,
            "quantity": qty,
            "unit_price": effective_unit_price,
            "line_total": line_total,
            "notes": item_notes.get(menu_item_id),
        })

    # Standard delivery fee if applicable
    if fulfillment == "delivery":
        # Free delivery above Rs. 299, otherwise Rs. 29
        delivery_fee = 0.0 if total >= 299.0 else 29.0
        total += delivery_fee

    # 6. Preparation time calculation
    prep_time_minutes = 15 + min(15, len(order_items_to_create) * 2)
    estimated_ready = datetime.utcnow() + timedelta(minutes=prep_time_minutes)

    # 7. Create Order record
    order = models.Order(
        order_number=order_number,
        customer_id=user.id,
        customer_name=(payload.customer_name or user.name or "Customer").strip(),
        customer_phone=(payload.customer_phone or user.phone or "").strip(),
        restaurant_id=payload.restaurant_id,
        location_id=payload.location_id,
        fulfillment_type=fulfillment,
        delivery_address=(payload.delivery_address or "").strip() if fulfillment == "delivery" else None,
        status=models.OrderStatus.pending,
        payment_status=models.PaymentStatus.pending,
        subtotal=round(subtotal, 2),
        discount=round(discount, 2),
        total=round(total, 2),
        notes=(payload.notes or "").strip() or None,
        prep_time_minutes=prep_time_minutes,
        estimated_ready_at=estimated_ready,
        idempotency_key=payload.idempotency_key,
    )
    db.add(order)
    await db.flush()

    # 8. Create OrderItem snapshot records
    for oi in order_items_to_create:
        db.add(
            models.OrderItem(
                order_id=order.id,
                menu_item_id=oi["menu_item_id"],
                item_name=oi["item_name"],
                quantity=oi["quantity"],
                unit_price=oi["unit_price"],
                line_total=oi["line_total"],
                notes=oi["notes"],
            )
        )

    # 9. Commit atomic transaction (with concurrent idempotency race handling)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if payload.idempotency_key:
            existing = await db.scalar(
                select(models.Order)
                .options(selectinload(models.Order.items))
                .where(
                    models.Order.customer_id == user.id,
                    models.Order.idempotency_key == payload.idempotency_key,
                )
            )
            if existing:
                return existing
        raise

    await db.refresh(order)

    # Re-fetch with eager loaded items
    order = await db.scalar(
        select(models.Order)
        .options(selectinload(models.Order.items))
        .where(models.Order.id == order.id)
    )

    # 10. Broadcast real-time event to Chef, Admin, and Tracking (ONLY AFTER COMMIT)
    await order_broadcaster.notify("order_created", {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status.value,
        "customer_id": order.customer_id,
        "customer_name": order.customer_name,
        "restaurant_id": order.restaurant_id,
        "fulfillment_type": order.fulfillment_type,
        "total": order.total,
        "prep_time_minutes": order.prep_time_minutes,
        "estimated_ready_at": order.estimated_ready_at.isoformat() if order.estimated_ready_at else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    })

    return order


@router.get("/", response_model=list[OrderOut])
async def list_orders(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """List orders with strict role-based data partitioning.

    Customers can ONLY view their own orders. Staff (Chef, Admin, Super Admin)
    can view all restaurant operational orders.
    """
    roles = user_roles(user)
    is_staff = bool(roles & {"super_admin", "admin", "kitchen"})

    q = select(models.Order).options(selectinload(models.Order.items))
    if not is_staff:
        # BOLA protection: restrict customers strictly to their own orders
        q = q.where(models.Order.customer_id == user.id)

    if status:
        if status not in [e.value for e in models.OrderStatus]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status filter '{status}'.",
            )
        q = q.where(models.Order.status == status)

    q = q.order_by(models.Order.created_at.desc()).limit(limit)
    return (await db.scalars(q)).all()


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Get single order details with BOLA ownership verification."""
    order = await db.scalar(
        select(models.Order)
        .options(selectinload(models.Order.items))
        .where(models.Order.id == order_id)
    )
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    roles = user_roles(user)
    is_staff = bool(roles & {"super_admin", "admin", "kitchen"})

    # BOLA protection: customers can only view their own order
    if not is_staff and order.customer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this order.",
        )

    return order


@router.patch("/{order_id}/status")
async def update_status(
    order_id: int,
    status_query: str | None = Query(None, alias="status"),
    body: StatusUpdatePayload | None = None,
    db: AsyncSession = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Update order status with strict state machine and role verification."""
    status_val = (body.status if body and body.status else None) or status_query
    if not status_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status value must be provided in request body or as ?status= query parameter.",
        )

    order = await db.scalar(
        select(models.Order)
        .options(selectinload(models.Order.items))
        .where(models.Order.id == order_id)
    )
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    # Validate target status exists in enum
    valid_statuses = [e.value for e in models.OrderStatus]
    if status_val not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{status_val}'. Allowed: {valid_statuses}",
        )

    target_status = models.OrderStatus(status_val)
    current_status = order.status
    roles = user_roles(user)
    is_sa = "super_admin" in roles
    is_adm = "admin" in roles or is_sa
    is_kitch = "kitchen" in roles

    # 1. Customer RBAC check: Customers cannot change operational status; can only cancel own pending/confirmed order
    if not (is_adm or is_kitch):
        if target_status != models.OrderStatus.cancelled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customers cannot update order operational status.",
            )
        if order.customer_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot cancel another customer's order.",
            )
        if current_status not in {models.OrderStatus.pending, models.OrderStatus.confirmed}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel an order that is already being prepared or completed.",
            )

    # 2. Terminal state check (applies to ALL roles, including Super Admin)
    if current_status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot transition order from terminal status '{current_status.value}'.",
        )

    # 3. State Machine transition matrix check (Permission and validity are separate checks)
    if order.fulfillment_type == "delivery":
        valid_transitions = DELIVERY_TRANSITIONS.get(current_status, set())
    else:
        valid_transitions = PICKUP_TRANSITIONS.get(current_status, set())

    if target_status not in valid_transitions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid transition from '{current_status.value}' to '{target_status.value}' for {order.fulfillment_type} orders.",
        )

    # 4. Kitchen operational permission check
    if is_kitch and not is_adm:
        allowed_kitchen_targets = {
            models.OrderStatus.pending: {models.OrderStatus.confirmed, models.OrderStatus.preparing},
            models.OrderStatus.confirmed: {models.OrderStatus.preparing},
            models.OrderStatus.preparing: {models.OrderStatus.ready},
            models.OrderStatus.ready: {models.OrderStatus.picked_up} if order.fulfillment_type == "pickup" else set(),
        }
        if target_status not in allowed_kitchen_targets.get(current_status, set()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Kitchen cannot transition order from '{current_status.value}' to '{target_status.value}'.",
            )
    # Admin / Super Admin: permitted to execute any transition verified valid by the state machine

    # 4. Stock handling on cancellation
    # Business Rule: Inventory is ONLY restored if cancelled prior to food preparation
    # (i.e. pending or confirmed). Once preparation has begun (preparing, ready, out_for_delivery),
    # inventory is NOT restored to prevent artificial inventory inflation on cooked/wasted food.
    if target_status == models.OrderStatus.cancelled and current_status in {models.OrderStatus.pending, models.OrderStatus.confirmed}:
        for oi in order.items:
            await db.execute(
                update(models.MenuItem)
                .where(models.MenuItem.id == oi.menu_item_id)
                .values(stock=models.MenuItem.stock + oi.quantity)
            )
            db.add(
                models.InventoryLog(
                    restaurant_id=order.restaurant_id,
                    menu_item_id=oi.menu_item_id,
                    change=oi.quantity,
                    reason=f"order_cancelled:{order.order_number}",
                )
            )

    # 5. Update status and commit
    order.status = target_status
    await db.commit()

    # 6. Broadcast event (ONLY AFTER COMMIT)
    await order_broadcaster.notify("order_status_changed", {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status.value,
        "customer_id": order.customer_id,
        "restaurant_id": order.restaurant_id,
        "fulfillment_type": order.fulfillment_type,
    })

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status.value,
    }

