import os
import uuid
import json
import base64
from io import BytesIO

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
import httpx
from xhtml2pdf import pisa

# -------------------- Инициализация --------------------
app = FastAPI()

# DeepSeek API key (установишь на Render)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# URL бэкенда (замени на свой после деплоя)
BACKEND_URL = os.getenv("BACKEND_URL", "https://dispomix-bot.onrender.com")

# -------------------- Матрица покрытий --------------------
SYSTEMS = [
    {
        "id": "SYS-A",
        "name": "Ferratop 652 — самостоятельное толстослойное покрытие",
        "type": "single",
        "layers": [
            {"article": "Ferratop 652", "consumption_kg_m2": 0.20, "price_kg": 787.5}
        ],
        "total_material_cost_m2": 157.5,
        "conditions": {
            "surface_prep": ["St2", "Sa2"],
            "environment": ["oil", "chemical", "uv", "moisture", "marine", "industrial", "normal"],
            "durability_min": 15,
            "durability_max": 20,
            "temperature_max": 200,
            "ph_range": [3, 14]
        },
        "description": "Высоконаполненная полиуретановая мастика. Не требует спецподготовки, можно по ржавчине (St2). Для широкого спектра сред, включая морскую воду.",
        "restrictions": []
    },
    # ... скопируй сюда остальные 9 систем из предыдущего JSON (я их опустил для краткости, но ты вставишь полный массив)
    {
        "id": "SYS-J",
        "name": "Магистраль зелёный — гидроизоляция замкнутых объёмов",
        "type": "single",
        "layers": [
            {"article": "Магистраль зелёный", "consumption_kg_m2": 0.15, "price_kg": 1209.9}
        ],
        "total_material_cost_m2": 181.5,
        "conditions": {
            "surface_prep": ["St2", "Sa2"],
            "environment": ["closed_space", "moisture", "water_contact"],
            "durability_min": 15,
            "durability_max": 20,
            "temperature_max": 180,
            "ph_range": [3, 14]
        },
        "description": "Гидроизоляция замкнутых пространств, допускает армирование стеклотканью. Без растворителей.",
        "restrictions": ["Замкнутые объёмы"]
    }
]

# Конкуренты
COMPETITORS = [
    {"name": "ХС-436 (эмаль+грунт)", "material_cost_m2": 380, "repaint_interval": 5, "work_factor": 0.7},
    {"name": "ПФ-115", "material_cost_m2": 160, "repaint_interval": 3, "work_factor": 0.7}
]

# Площади типовых объектов
AREA_PRESETS = {
    "РВС-1000": 480,
    "РВС-2000": 900,
    "РВС-5000": 1500,
    "РВС-10000": 2800
}

# -------------------- Хранилище сессий --------------------
sessions = {}

# Состояния диалога
START, OBJECT, REGION, ENVIRONMENT, PREP, DURABILITY, DIMENSIONS, RESULT, GENERATING = range(9)

# -------------------- DeepSeek helper --------------------
async def deepseek_extract_area(text: str) -> float:
    """Извлекает площадь из произвольного текста с помощью DeepSeek."""
    if not DEEPSEEK_API_KEY:
        return None
    prompt = (
        f"Извлеки площадь окрашиваемой поверхности в квадратных метрах из сообщения пользователя. "
        f"Если указан тип резервуара (РВС-...), используй стандартные площади: {AREA_PRESETS}. "
        f"Если написана труба с диаметром и длиной, вычисли площадь по формуле π*d*l. "
        f"Ответь только числом, без пояснений.\n\nСообщение: {text}"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0
                }
            )
            data = resp.json()
            result = data["choices"][0]["message"]["content"].strip()
            return float(result.replace(",", "."))
    except:
        return None

# -------------------- Генерация PDF --------------------
def generate_pdf(session_data: dict, system: dict, area: float) -> bytes:
    """Создаёт PDF-коммерческое предложение."""
    layers_html = ""
    total_material = 0
    for layer in system["layers"]:
        cost = layer["consumption_kg_m2"] * area * layer["price_kg"]
        layers_html += f"""
        <tr>
            <td>{layer['article']}</td>
            <td>{layer['consumption_kg_m2']:.2f} кг/м²</td>
            <td>{layer['price_kg']:.2f} руб/кг</td>
            <td>{cost:,.2f} руб</td>
        </tr>
        """
        total_material += cost

    # Расчёт конкурентов
    competitor_html = ""
    for comp in COMPETITORS:
        years = 15
        repaints = years // comp["repaint_interval"]
        total_comp = (repaints * comp["material_cost_m2"] * area) + (repaints * comp["material_cost_m2"] * area * comp["work_factor"])
        competitor_html += f"""
        <tr>
            <td>{comp['name']}</td>
            <td>{repaints} раз</td>
            <td>{total_comp:,.2f} руб</td>
        </tr>
        """

    html = f"""
    <html>
    <head><meta charset="utf-8"><style>body {{ font-family: Arial; }}</style></head>
    <body>
        <h1>Dispomix-Сиб — Коммерческое предложение</h1>
        <p>Объект: {session_data.get('object_type', '')} в регионе {session_data.get('region', '')}</p>
        <p>Площадь окраски: {area:,.0f} м²</p>
        <h2>Рекомендованная система: {system['name']}</h2>
        <p>{system['description']}</p>
        <table border="1" cellpadding="5">
            <tr><th>Продукт</th><th>Расход</th><th>Цена/кг</th><th>Стоимость</th></tr>
            {layers_html}
        </table>
        <p><b>Итого материалы: {total_material:,.2f} руб.</b> (без учёта доставки и работ)</p>
        <h2>Сравнение затрат за 15 лет с аналогами</h2>
        <table border="1" cellpadding="5">
            <tr><th>Материал</th><th>Кол-во перекрасок</th><th>Общие затраты</th></tr>
            {competitor_html}
        </table>
        <p><b>Экономия с Dispomix очевидна!</b></p>
        <p>Контакты: +7-XXX-XXX-XX-XX, sib@dispomix.ru</p>
    </body>
    </html>
    """
    pdf_buffer = BytesIO()
    pisa.CreatePDF(html, dest=pdf_buffer)
    pdf_buffer.seek(0)
    return pdf_buffer.read()

# -------------------- API Endpoints --------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str = None

@app.post("/chat")
async def chat(request: ChatRequest):
    msg = request.message.strip()
    session_id = request.session_id or str(uuid.uuid4())
    
    # Создать или восстановить сессию
    if session_id not in sessions:
        sessions[session_id] = {"state": START, "data": {}}
    session = sessions[session_id]
    state = session["state"]
    data = session["data"]

    # ----- Обработка состояний -----
    if state == START:
        # Шаг 0: Приветствие
        session["state"] = OBJECT
        reply = "Здравствуйте! Я — помощник Dispomix-Сиб. Подберу антикоррозионную защиту и посчитаю экономию. Что будем защищать?"
        buttons = ["Резервуар (РВС)", "Трубопровод / эстакада", "Металлоконструкции", "Гидросооружение / причал", "Другое"]

    elif state == OBJECT:
        data["object_type"] = msg
        session["state"] = REGION
        reply = "Где находится объект? Укажите город или регион."
        buttons = ["Якутск", "Иркутск", "Хабаровск", "Владивосток", "Новосибирск", "Другое"]

    elif state == REGION:
        data["region"] = msg
        session["state"] = ENVIRONMENT
        reply = "Какие агрессивные факторы воздействуют на металл? (можно выбрать несколько через запятую)"
        buttons = ["Нефтепродукты / сероводород", "Морская соль / туман", "Открытое солнце (УФ)", "Промышленная атмосфера", "Замкнутый объём", "Ничего особенного"]

    elif state == ENVIRONMENT:
        data["environment"] = [e.strip() for e in msg.split(",")]
        session["state"] = PREP
        reply = "Возможна ли пескоструйная очистка металла?"
        buttons = ["Да, пескоструй (Sa2)", "Только ручная очистка (St2)"]

    elif state == PREP:
        data["prep"] = msg
        session["state"] = DURABILITY
        reply = "На какой минимальный срок без ремонта рассчитываете?"
        buttons = ["10 лет", "15 лет", "20 лет", "Максимально возможный"]

    elif state == DURABILITY:
        data["durability"] = msg
        session["state"] = DIMENSIONS
        reply = "Укажите примерную площадь окрашиваемой поверхности (м²) или размеры объекта. Например: «РВС-5000», «труба 200 м, диаметр 530 мм»."
        buttons = []  # здесь кнопки не нужны

    elif state == DIMENSIONS:
        # Пробуем распарсить площадь
        area = None
        # проверка на пресет
        for key, val in AREA_PRESETS.items():
            if key in msg.upper():
                area = val
                break
        if area is None:
            # попробуем вытащить число
            try:
                area = float(msg.replace(",", "."))
            except:
                # обратимся к DeepSeek
                area = await deepseek_extract_area(msg)
        if area is None or area <= 0:
            reply = "Не удалось определить площадь. Пожалуйста, введите число или известный тип (например, РВС-5000)."
            buttons = []
        else:
            data["area"] = area
            # Подбор системы
            filters = {
                "prep": data["prep"],
                "env": data["environment"],
                "durability": data["durability"],
                "area": area
            }
            # простой фильтр
            suitable = []
            for sys in SYSTEMS:
                # проверка подготовки
                prep_condition = "St2" if "St2" in data["prep"] else "Sa2"
                if prep_condition not in sys["conditions"]["surface_prep"]:
                    continue
                # проверка среды (хотя бы одно совпадение)
                env_match = any(e in sys["conditions"]["environment"] for e in data["environment"])
                if not env_match and "normal" not in sys["conditions"]["environment"]:
                    continue
                # срок службы: извлечём минимальный срок из сообщения
                dur_text = data["durability"].lower()
                if "максималь" in dur_text:
                    req_dur = 25
                elif "20" in dur_text:
                    req_dur = 20
                elif "15" in dur_text:
                    req_dur = 15
                else:
                    req_dur = 10
                if sys["conditions"]["durability_min"] >= req_dur:
                    suitable.append(sys)
            if not suitable:
                # если ничего не подошло, берём первое попавшееся
                suitable = [SYSTEMS[0]]
            chosen = suitable[0]  # пока берём первое подходящее
            data["chosen_system"] = chosen

            # расчёт экономии
            # упрощённо: берём самого дешёвого конкурента
            comp = COMPETITORS[0]  # ХС-436
            years = 15
            repaints = years // comp["repaint_interval"]
            comp_total = (repaints * comp["material_cost_m2"] * area) + (repaints * comp["material_cost_m2"] * area * comp["work_factor"])
            dispomix_cost = chosen["total_material_cost_m2"] * area
            saving = comp_total - dispomix_cost

            reply = (
                f"✅ Рекомендую систему: **{chosen['name']}**\n"
                f"Расход: {chosen['layers'][0]['consumption_kg_m2']:.2f} кг/м²\n"
                f"Стоимость материалов: {chosen['total_material_cost_m2']:.2f} руб/м²\n"
                f"Общая стоимость: {dispomix_cost:,.2f} руб. (на {area:.0f} м²)\n\n"
                f"Для сравнения: {comp['name']} потребует {repaints} перекрасок за 15 лет, "
                f"общие затраты около {comp_total:,.2f} руб.\n"
                f"💰 Ваша экономия: {saving:,.2f} руб."
            )
            buttons = ["Скачать КП в PDF", "Связаться с инженером", "Новый расчёт"]
            session["state"] = RESULT

    elif state == RESULT:
        if msg == "Скачать КП в PDF":
            area = data.get("area", 0)
            system = data.get("chosen_system")
            if not system:
                reply = "Ошибка: система не выбрана. Начните заново."
                buttons = ["Новый расчёт"]
                session["state"] = START
            else:
                pdf_bytes = generate_pdf(data, system, area)
                filename = f"KP_Dispomix_{session_id[:8]}.pdf"
                filepath = f"/tmp/{filename}"
                with open(filepath, "wb") as f:
                    f.write(pdf_bytes)
                download_url = f"{BACKEND_URL}/download/{filename}"
                reply = f"Ваше КП готово! [Скачать PDF]({download_url})"
                buttons = ["Новый расчёт"]
                session["state"] = START
                # Сохраним имя файла для удаления позже? Пока ок.
        elif msg == "Связаться с инженером":
            reply = "Наш инженер свяжется с вами в ближайшее время. Оставьте контакты, или позвоните: +7-XXX-XXX-XX-XX."
            buttons = ["Новый расчёт"]
            session["state"] = START
        else:
            reply = "Выберите действие."
            buttons = ["Скачать КП в PDF", "Связаться с инженером", "Новый расчёт"]

    elif state == GENERATING:
        # не используется
        pass

    else:
        reply = "Что-то пошло не так. Начнём заново?"
        buttons = ["Начать сначала"]
        session["state"] = START

    # Формируем ответ
    response = {
        "message": reply,
        "buttons": buttons,
        "session_id": session_id
    }
    return JSONResponse(content=response)

@app.get("/download/{filename}")
async def download_file(filename: str):
    filepath = f"/tmp/{filename}"
    if os.path.exists(filepath):
        return FileResponse(filepath, media_type="application/pdf", filename=filename)
    raise HTTPException(status_code=404, detail="Файл не найден")

@app.get("/")
async def root():
    return {"status": "Dispomix Bot is running"}
