from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..keyboards import cancel_kb, confirm_kb, main_reply_kb
from ..moysklad import MoySkladClient, MoySkladError
from ..states import ShipmentForm

logger = logging.getLogger(__name__)

# Flow entry (tapping "📦 Отгрузка") is dispatched centrally from start.py,
# with StateFilter("*"), so a menu tap always wins even mid-flow. This
# router only owns the in-progress FSM steps.
router = Router(name="shipment")


async def enter_shipment_flow(message: Message, state: FSMContext) -> None:
    await state.update_data(positions=[], client_href=None, client_name=None)
    await state.set_state(ShipmentForm.waiting_for_client_query)
    await message.answer(
        "Отгрузка. Введи название клиента (можно часть названия):",
        reply_markup=cancel_kb(),
    )


@router.message(ShipmentForm.waiting_for_client_query)
async def client_query_entered(
    message: Message, state: FSMContext, moysklad: MoySkladClient
) -> None:
    query = (message.text or "").strip()
    if not query:
        await message.answer("Введи название клиента текстом:")
        return

    try:
        results = await moysklad.search_counterparty(query)
    except MoySkladError:
        logger.exception("Failed to search counterparty")
        await message.answer("Не получилось поискать в МойСклад, попробуй ещё раз:")
        return

    await state.update_data(client_candidates=results)
    builder = InlineKeyboardBuilder()
    for i, row in enumerate(results):
        builder.button(text=row["name"], callback_data=f"client_pick:{i}")
    builder.button(text=f"➕ Новый клиент «{query}»", callback_data="client_new")
    builder.button(text="Отмена", callback_data="cancel")
    builder.adjust(1)

    await state.set_state(ShipmentForm.choosing_client)
    await message.answer("Выбери клиента или создай нового:", reply_markup=builder.as_markup())


@router.callback_query(ShipmentForm.choosing_client, F.data.startswith("client_pick:"))
async def client_picked(callback: CallbackQuery, state: FSMContext) -> None:
    idx = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    candidates = data.get("client_candidates", [])
    if idx >= len(candidates):
        await callback.answer("Устарело, начни заново", show_alert=True)
        return
    chosen = candidates[idx]
    await state.update_data(client_href=chosen["meta"]["href"], client_name=chosen["name"])
    await _ask_product(callback.message, state)
    await callback.answer()


@router.callback_query(ShipmentForm.choosing_client, F.data == "client_new")
async def client_new_requested(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ShipmentForm.waiting_for_new_client_name)
    await callback.message.edit_text(
        "Введи точное название нового клиента:", reply_markup=cancel_kb()
    )
    await callback.answer()


@router.message(ShipmentForm.waiting_for_new_client_name)
async def new_client_name_entered(
    message: Message, state: FSMContext, moysklad: MoySkladClient
) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введи название клиента текстом:")
        return
    try:
        created = await moysklad.create_counterparty(name)
    except MoySkladError:
        logger.exception("Failed to create counterparty")
        await message.answer("Не получилось создать клиента в МойСклад, попробуй ещё раз:")
        return

    await state.update_data(client_href=created["meta"]["href"], client_name=created["name"])
    await _ask_product(message, state)


async def _ask_product(message: Message, state: FSMContext) -> None:
    await state.set_state(ShipmentForm.waiting_for_product_query)
    await message.answer(
        "Введи название товара (например «шпаклёвка» или «эмаль»):", reply_markup=cancel_kb()
    )


@router.message(ShipmentForm.waiting_for_product_query)
async def product_query_entered(
    message: Message, state: FSMContext, moysklad: MoySkladClient
) -> None:
    query = (message.text or "").strip()
    if not query:
        await message.answer("Введи название товара текстом:")
        return
    try:
        results = await moysklad.search_products(query)
    except MoySkladError:
        logger.exception("Failed to search products")
        await message.answer("Не получилось поискать товар в МойСклад, попробуй ещё раз:")
        return

    if not results:
        await message.answer("Ничего не нашлось, попробуй другое название:")
        return

    await state.update_data(product_candidates=results)
    builder = InlineKeyboardBuilder()
    for i, row in enumerate(results):
        builder.button(text=row["name"], callback_data=f"product_pick:{i}")
    builder.button(text="Отмена", callback_data="cancel")
    builder.adjust(1)

    await state.set_state(ShipmentForm.choosing_product)
    await message.answer("Выбери товар:", reply_markup=builder.as_markup())


@router.callback_query(ShipmentForm.choosing_product, F.data.startswith("product_pick:"))
async def product_picked(callback: CallbackQuery, state: FSMContext) -> None:
    idx = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    candidates = data.get("product_candidates", [])
    if idx >= len(candidates):
        await callback.answer("Устарело, начни заново", show_alert=True)
        return
    chosen = candidates[idx]
    sale_prices = chosen.get("salePrices") or [{}]
    default_price = (sale_prices[0].get("value", 0) or 0) / 100

    await state.update_data(
        current_product_href=chosen["meta"]["href"],
        current_product_name=chosen["name"],
        current_product_price=default_price,
    )
    await state.set_state(ShipmentForm.waiting_for_quantity)
    await callback.message.edit_text(f"«{chosen['name']}». Сколько единиц отгружаем? (число)")
    await callback.answer()


@router.message(ShipmentForm.waiting_for_quantity)
async def quantity_entered(message: Message, state: FSMContext) -> None:
    text = (message.text or "").replace(",", ".").strip()
    try:
        quantity = float(text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Не похоже на число. Введи количество ещё раз:")
        return

    data = await state.get_data()
    default_price = data.get("current_product_price", 0)
    await state.update_data(current_quantity=quantity)
    await state.set_state(ShipmentForm.waiting_for_price)
    await message.answer(
        "Цена за единицу? Отправь число или напиши «-», чтобы взять цену из МойСклад "
        f"({default_price:.2f})."
    )


@router.message(ShipmentForm.waiting_for_price)
async def price_entered(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()

    if text == "-":
        price = data.get("current_product_price", 0)
    else:
        try:
            price = float(text.replace(",", "."))
            if price < 0:
                raise ValueError
        except ValueError:
            await message.answer("Не похоже на число. Введи цену ещё раз или «-»:")
            return

    positions = data.get("positions", [])
    positions.append(
        {
            "name": data["current_product_name"],
            "href": data["current_product_href"],
            "quantity": data["current_quantity"],
            "price": price,
        }
    )
    await state.update_data(positions=positions)

    lines = "\n".join(f"• {p['name']} × {p['quantity']} по {p['price']:.2f}" for p in positions)
    await state.set_state(ShipmentForm.asking_add_more)
    await message.answer(
        f"Добавлено. В отгрузке пока:\n{lines}\n\nДобавить ещё товар?",
        reply_markup=confirm_kb("add_more:yes", "add_more:no"),
    )


@router.callback_query(ShipmentForm.asking_add_more, F.data == "add_more:yes")
async def add_more_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await _ask_product(callback.message, state)
    await callback.answer()


@router.callback_query(ShipmentForm.asking_add_more, F.data == "add_more:no")
async def add_more_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ShipmentForm.waiting_for_comment)
    await callback.message.edit_text("Комментарий к отгрузке (или «-», если не нужен):")
    await callback.answer()


@router.message(ShipmentForm.waiting_for_comment)
async def shipment_comment_entered(
    message: Message, state: FSMContext, moysklad: MoySkladClient
) -> None:
    comment = (message.text or "").strip()
    comment = "" if comment == "-" else comment

    data = await state.get_data()
    positions = data.get("positions", [])
    employee = message.from_user.full_name if message.from_user else "неизвестно"

    await message.answer("Оформляю отгрузку в МойСклад...")

    api_positions = [
        {
            "quantity": p["quantity"],
            "price": round(p["price"] * 100),
            "assortment": {
                "meta": {
                    "href": p["href"],
                    "type": "product",
                    "mediaType": "application/json",
                }
            },
        }
        for p in positions
    ]

    try:
        await moysklad.create_demand(
            counterparty_href=data["client_href"],
            positions=api_positions,
            employee=employee,
            comment=comment,
        )
    except MoySkladError:
        logger.exception("Failed to create demand in MoySklad")
        lines = "\n".join(f"• {p['name']} × {p['quantity']} по {p['price']:.2f}" for p in positions)
        await message.answer(
            "⚠️ Не получилось сохранить отгрузку в МойСклад (ошибка API). "
            "Сообщи администратору, вот детали, чтобы не потерялось:\n"
            f"Клиент: {data['client_name']}\n{lines}\nОт: {employee}"
        )
    else:
        await message.answer(
            f"Готово ✅ Отгрузка клиенту «{data['client_name']}» записана в МойСклад."
        )

    await state.clear()
    await message.answer("Выбери действие в меню внизу 👇", reply_markup=main_reply_kb())
