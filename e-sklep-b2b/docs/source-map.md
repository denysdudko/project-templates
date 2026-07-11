# Source Map — WBS → Официальная документация Comarch

Таблица связывает каждый узел WBS с фактически используемыми в задачах ссылками на официальную документацию.
Статус:
- ✅ — все задачи WBS ссылаются на официальную документацию.
- ⚠️ Internal — часть/все задачи используют `Internal Project Methodology` (документация не описывает процесс, применяется наш опыт — это ожидаемо для управленческих/приёмочных работ).
- ❌ Missing URL — задача помечена как `Official Comarch Documentation`, но URL не указан. Требует решения.

Статус проекта на текущий момент: незакрытых `❌ Missing URL` не осталось (M1 переклассифицирован в Internal — см. CHANGELOG v1.2).

| WBS | Milestone | Название WBS | Источник(и) документации | Статус |
|---|---|---|---|---|
| WBS-1.1 | M1 — Анализ требований | Анализ бизнес-процессов | — | ⚠️ Internal (полностью) |
| WBS-1.2 | M1 — Анализ требований | Анализ функциональных требований | — | ⚠️ Internal (полностью) |
| WBS-1.3 | M1 — Анализ требований | Анализ интеграций | — | ⚠️ Internal (полностью) |
| WBS-1.4 | M1 — Анализ требований | Анализ исходных данных | — | ⚠️ Internal (полностью) |
| WBS-1.5 | M1 — Анализ требований | Подготовка спецификации проекта | — | ⚠️ Internal (полностью) |
| WBS-2.1 | M2 — Подготовка ERP | Подготовка Comarch ERP Optima к интеграции | [pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/wspolpraca-z-comarch-e-sklep/)<br>[pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/formularz-comarch-e-sklep/) | ✅ |
| WBS-2.2 | M2 — Подготовка ERP | Настройка интеграции e-Sklep | [pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/formularz-comarch-e-sklep/) | ✅ |
| WBS-2.3 | M2 — Подготовка ERP | Настройка параметров обмена | [pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/formularz-comarch-e-sklep/) | ✅ |
| WBS-2.4 | M2 — Подготовка ERP | Подготовка к подключению e-Sklep | [pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/formularz-comarch-e-sklep/) | ✅ |
| WBS-3.1 | M3 — Подключение e-Sklep | Подключение e-Sklep к ERP | [pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/formularz-comarch-e-sklep/) | ✅ |
| WBS-3.2 | M3 — Подключение e-Sklep | Настройка параметров подключения | [pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/formularz-comarch-e-sklep/) | ✅ |
| WBS-3.3 | M3 — Подключение e-Sklep | Проверка подключения | [pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/wspolpraca-z-comarch-e-sklep/)<br>[pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/formularz-comarch-e-sklep/) | ✅ |
| WBS-4.1 | M4 — Настройка e-Sklep | Настройка общих параметров магазина | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/dane-sklepu/)<br>[pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/konfiguracja-domeny/) | ✅ |
| WBS-4.2 | M4 — Настройка e-Sklep | Настройка внешнего вида магазина | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/wybor-szablonu-startowego/) | ✅ |
| WBS-4.3 | M4 — Настройка e-Sklep | Настройка способов оплаты | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/macierz-dostaw/) | ✅ |
| WBS-4.4 | M4 — Настройка e-Sklep | Настройка способов доставки | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/macierz-dostaw/) | ✅ |
| WBS-4.5 | M4 — Настройка e-Sklep | Настройка уведомлений и параметров магазина | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/konfiguracja-konta-e-mail/)<br>[pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/powiadomienia-e-mail-dla-administratorow/)<br>[pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/regulamin-e-sklepu/) | ✅ |
| WBS-5.1 | M5 — Подготовка данных | Подготовка товаров | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/dodawanie-towarow-w-erp-optima/) | ✅ |
| WBS-5.2 | M5 — Подготовка данных | Подготовка структуры каталога | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/dodawanie-towarow-w-erp-optima/) | ✅ |
| WBS-5.3 | M5 — Подготовка данных | Подготовка описаний и мультимедиа | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/towary-w-panelu/) | ✅ |
| WBS-5.4 | M5 — Подготовка данных | Подготовка атрибутов и данных | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/dodawanie-towarow-w-erp-optima/) | ✅ |
| WBS-5.5 | M5 — Подготовка данных | Первая синхронизация данных | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/pierwsza-synchronizacja/) | ✅ |
| WBS-5.6 | M5 — Подготовка данных | Проверка результатов синхронизации | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/towary-w-panelu/) | ✅ |
| WBS-6.1 | M6 — Настройка B2B и интеграций | Настройка функций B2B | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/jak-skonfigurowac-sklep-pod-obsluge-b2b/) | ✅ |
| WBS-6.2 | M6 — Настройка B2B и интеграций | Настройка цен и скидок B2B | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/rabaty-z-comarch-erp-optima/)<br>[pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/jak-ustawic-indywidualne-ceny-dla-kontrahentow/)<br>[pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/indywidualne-cenniki-dla-kontrahentow/) | ✅ |
| WBS-6.3 | M6 — Настройка B2B и интеграций | Настройка условий сотрудничества | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/limit-kredytu-i-limit-przeterminowanych-platnosci/) | ✅ |
| WBS-6.4 | M6 — Настройка B2B и интеграций | Настройка интеграций | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/kategoria/integracje/) | ✅ |
| WBS-6.5 | M6 — Настройка B2B и интеграций | Проверка функций B2B и интеграций | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/kategoria/b2b/) | ✅ |
| WBS-7.1 | M7 — Презентация и приёмка проекта | Подготовка к презентации проекта | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/jak-przebiega-proces-zamowienia/) | ✅ + ⚠️ Internal (частично) |
| WBS-7.2 | M7 — Презентация и приёмка проекта | Презентация решения заказчику | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/jak-przebiega-proces-zamowienia/) | ✅ + ⚠️ Internal (частично) |
| WBS-7.3 | M7 — Презентация и приёмка проекта | Обработка замечаний, выявленных на презентации | — | ⚠️ Internal (полностью) |
| WBS-7.4 | M7 — Презентация и приёмка проекта | Приемка проекта | — | ⚠️ Internal (полностью) |
| WBS-8.1 | M8 — Обучение пользователей | Подготовка обучения | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/kategoria/jak-zaczac/) | ✅ + ⚠️ Internal (частично) |
| WBS-8.2 | M8 — Обучение пользователей | Проведение обучения | — | ⚠️ Internal (полностью) |
| WBS-8.3 | M8 — Обучение пользователей | Подтверждение готовности пользователей | — | ⚠️ Internal (полностью) |
| WBS-9.1 | M9 — Запуск и гиперподдержка | Подготовка к запуску | [pomoc.comarchesklep.pl...](https://pomoc.comarchesklep.pl/artykul/lista-czynnosci-na-start/)<br>[pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026/dokumentacja/pytanie-34608-jak-odbywa-sie-synchronizacja-pomiedzy-comarch-erp-optima-a-comarch-e-sklep/) | ✅ |
| WBS-9.2 | M9 — Запуск и гиперподдержка | Запуск в эксплуатацию | [pomoc.comarch.pl...](https://pomoc.comarch.pl/optima/pl/2026/dokumentacja/pytanie-34608-jak-odbywa-sie-synchronizacja-pomiedzy-comarch-erp-optima-a-comarch-e-sklep/) | ✅ + ⚠️ Internal (частично) |
| WBS-9.4 | M9 — Запуск и гиперподдержка | Завершение проекта | — | ⚠️ Internal (полностью) |
