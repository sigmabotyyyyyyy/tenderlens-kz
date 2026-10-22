"""Local, explainable procurement price review workspace."""
import sqlite3

import streamlit as st

from config import DB_PATH, DEMO_PATH
from tenderlens.storage import Store
from tenderlens.ui.business import render_business
from tenderlens.ui.common import local_time
from tenderlens.ui.detail import render_detail
from tenderlens.ui.results import render_results
from tenderlens.ui.sources import render_sources
from tenderlens.ui.upload import render_import_feedback, render_import_summary, render_upload

st.set_page_config(page_title="TenderLens KZ · Анализ закупок", page_icon="🔎", layout="wide")

if "workspace_section" not in st.session_state and st.query_params.get("view") == "business":
    st.session_state["workspace_section"] = "Идея и заработок"

for pending, widget_key in (("pending_dataset", "active_dataset"), ("pending_run", "active_run"),
                            ("pending_section", "workspace_section")):
    if pending in st.session_state:
        st.session_state[widget_key] = st.session_state.pop(pending)

try:
    store = Store(DB_PATH)
    datasets = store.datasets()
except (sqlite3.Error, OSError, ValueError):
    st.title("TenderLens KZ")
    st.error("Не удалось открыть локальную базу данных. Проверьте доступ к файлу и перезапустите приложение.")
    st.stop()

with st.sidebar:
    st.title("TenderLens KZ")
    st.caption("Аналитика закупок · офисная бумага")
    st.divider()
    section = st.radio("Навигация", ("Рабочая область", "Загрузка данных", "Реальные закупки", "Метод сравнения", "Идея и заработок"),
                       key="workspace_section", label_visibility="collapsed")
    st.divider()
    if datasets and section != "Идея и заработок":
        by_id = {dataset["id"]: dataset for dataset in datasets}
        if st.session_state.get("active_dataset") not in by_id:
            st.session_state["active_dataset"] = datasets[0]["id"]
        dataset_id = st.selectbox(
            "Текущий набор", list(by_id), key="active_dataset",
            format_func=lambda key: f"№{key} · {by_id[key]['name']}")
        dataset = by_id[dataset_id]
        st.caption(f"{dataset['accepted_count']} позиций · {local_time(dataset['imported_at'])}")
        st.caption("Синтетический набор" if dataset["dataset_kind"] == "synthetic" else "Реальный набор")
    else:
        dataset = None
        st.caption("Экономика проекта по вашим вводным" if section == "Идея и заработок" else "Наборы пока не загружены")
    st.divider()
    st.caption("Локальная рабочая область")
    st.caption("Наборы данных, результаты и ручные проверки сохраняются на этом компьютере.")

st.caption("TENDERLENS / КАЗАХСТАН")
st.title({"Рабочая область": "Анализ цен закупок", "Загрузка данных": "Данные для анализа",
          "Реальные закупки": "Договоры госзакупок Казахстана",
          "Метод сравнения": "Как устроено сравнение", "Идея и заработок": "TenderLens: от идеи к заработку"}[section])
st.write("Идея, возможные клиенты, доход и срок окупаемости — на одном экране." if section == "Идея и заработок"
         else "Находите высокие цены, изучайте договоры-аналоги и фиксируйте результат проверки.")

if dataset and dataset["dataset_kind"] == "synthetic" and section != "Реальные закупки":
    st.warning("СИНТЕТИЧЕСКИЕ ДАННЫЕ · Закупки, организации и цены вымышлены. Используйте набор для демонстрации.", icon="⚠️")

if section != "Идея и заработок":
    render_import_feedback()

if section == "Идея и заработок":
    render_business()
elif section == "Реальные закупки":
    render_sources(store)
elif section == "Загрузка данных" or (section == "Рабочая область" and dataset is None):
    render_upload(store, DEMO_PATH)
    if dataset and section == "Загрузка данных":
        st.divider()
        st.subheader("Качество текущего набора")
        render_import_summary(dataset)
elif section == "Метод сравнения":
    with st.container(border=True):
        st.subheader("Цена позиции → прошлые договоры → медиана")
        st.write("Приложение сравнивает цену одной пачки офисной бумаги в тенге с похожими закупками из того же набора.")
        st.markdown(
            "1. **Подбираем сопоставимые позиции.** Совпадают формат, плотность, листов в пачке, регион, "
            "валюта и условия НДС и доставки. Количество — от ½ до 2 объёмов целевой закупки.\n"
            "2. **Берём только историю.** Аналоги заключены раньше целевой позиции, в выбранном окне. "
            "Договор целевой позиции, закупки того же дня и будущие договоры исключены.\n"
            "3. **Даём каждому договору один голос.** Сначала считаем медиану его подходящих позиций, "
            "затем медиану опорных цен разных договоров.\n"
            "4. **Проверяем порог.** Если договоров достаточно, сравниваем превышение медианы с порогом. "
            "Например, при медиане 1 000 ₸ и пороге +50% срабатывание начинается с 1 500 ₸ включительно."
        )
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Выше порога**")
        st.caption("Цена достигает или превышает заданный порог. Откройте аналоги и проверьте причины.")
    with c2:
        st.markdown("**Без срабатывания**")
        st.caption("Аналогов достаточно, цена ниже порога этого правила.")
    with c3:
        st.markdown("**Мало аналогов**")
        st.caption("Данных для решения недостаточно. Доступная медиана носит справочный характер.")
    st.info("Срабатывание — повод для ручной проверки. Белизна, класс бумаги и особые условия могут быть не учтены; "
            "результат ценового правила не является заключением о нарушении.")
    st.caption("Версия алгоритма: median_v1. Параметры и точный состав аналогов сохраняются с каждым запуском.")
else:
    with st.expander(f"Набор №{dataset['id']} · {dataset['name']} · {dataset['accepted_count']} позиций"):
        render_import_summary(dataset)
    try:
        run_id, rows = render_results(store, dataset)
        if run_id is not None:
            st.divider()
            render_detail(store, run_id, rows)
    except (sqlite3.Error, OSError):
        st.error("Не удалось прочитать или сохранить данные. Проверьте доступ к локальной базе и повторите действие.")
