# Матрица покрытия Backend → Frontend

Дата актуализации: 2026-10-19. Матрица относится к текущей ветке исходников в этом архиве. По инвентаризации зарегистрированных FastAPI endpoints в `app.main` присутствует **93 комбинации HTTP-метода и API-пути**; ниже каждой функциональной группе назначена страница, компонент или внутренний транспортный обработчик.

Цель — связать публичные HTTP-контракты backend с конкретными страницами, компонентами или транспортными обработчиками frontend. Отдельные технические маршруты не имеют самостоятельной страницы, поскольку используются внутри существующих сценариев.

## Авторизация и пользовательская сессия

| Backend route | Frontend | Что даёт пользователю |
|---|---|---|
| `POST /api/auth/login` | `pages/LoginPage.tsx` | Выбор роли как UX-подсказки, логин/пароль, TOTP для врача/администратора; фактическая роль берётся из ответа сервера |
| `POST /api/auth/logout` | `components/Layout.tsx`, `auth/AuthContext.tsx` | Выход и очистка сессии |
| `GET /api/auth/me` | `auth/AuthContext.tsx` | Восстановление сессии, MFA и признака `is_reviewer` |
| `POST /api/auth/password` | `pages/AccountPage.tsx` | Смена пароля с повторным входом |
| `POST /api/auth/mfa/setup`, `POST /api/auth/mfa/confirm` | `pages/AccountPage.tsx` | Настройка TOTP, QR-код и подтверждение подключения |
| `GET /api/push/key`, `GET/POST/DELETE /api/push/subscriptions`, `POST /api/push/test` | `pages/AccountPage.tsx`, `api/push.ts` | Включение и отключение push-уведомлений на устройстве, проверка доставки |
| `POST /api/auth/stream-ticket` | `api/stream.ts` | Одноразовый билет для SSE, чтобы не помещать bearer-токен в URL |

## Врач: пациенты и клинические решения

| Backend route | Frontend | Что даёт пользователю |
|---|---|---|
| `GET /api/doctor/patients` | `pages/doctor/PatientsPage.tsx`, `RuleTester.tsx` | Автотриаж, четыре сводные карточки/фильтра (включая серверный `needs_attention`), поиск, риск, диагноз, терапия, шкалы, приверженность, направления, пагинация |
| `POST /api/doctor/patients` | `pages/doctor/NewPatientPage.tsx` | Создание карточки пациента |
| `GET /api/doctor/patients/{pid}` | `pages/doctor/patient/PatientLayout.tsx` | Полная карточка пациента |
| `POST /api/doctor/patients/{pid}/reset-patient-password` | `pages/doctor/patient/OverviewTab.tsx` | Выпуск временного пароля пациента с ограничением доступа |
| `PATCH /api/doctor/patients/{pid}` | `pages/doctor/patient/DataTab.tsx`, `components/PatientFields.tsx` | Редактирование сведений, диагнозов, сопутствующих препаратов, профиля и порогов |
| `GET/POST /api/doctor/patients/{pid}/visits` | `pages/doctor/patient/VisitsHistory.tsx` | История визитов, создание визита, заметки и следующий визит |
| `POST /api/doctor/patients/{pid}/visit` | `pages/doctor/patient/OverviewTab.tsx` | Быстрое действие «Отметить очный приём сегодня»; расширенная запись и история доступны в `VisitsHistory.tsx` через `POST .../visits` |
| `POST /api/doctor/patients/{pid}/monitoring` | `pages/doctor/patient/OverviewTab.tsx` | Включение/остановка дистанционного наблюдения |
| `GET /api/doctor/patients/{pid}/recommendations` | `pages/doctor/patient/TherapyTab.tsx` | Рекомендации, клинические основания и источники |
| `POST /api/doctor/patients/{pid}/prescriptions` | `pages/doctor/patient/TherapyTab.tsx` | Черновик/назначение в пределах backend-проверок и подтверждений |
| `POST /api/doctor/prescriptions/{rid}` | `pages/doctor/patient/TherapyTab.tsx` | Действия с назначением: остановить, приостановить или возобновить |
| `POST /api/doctor/patients/{pid}/scales` | `pages/doctor/patient/ClinicianScalePage.tsx` | Заполнение врачебной шкалы |
| `POST /api/doctor/patients/{pid}/assignments` | `pages/doctor/patient/ScalesTab.tsx` | Назначение шкалы и расписания контроля |
| `GET/POST /api/doctor/patients/{pid}/messages` | `pages/doctor/patient/MessagesTab.tsx`, `components/Chat.tsx` | Переписка врача с пациентом |
| `GET /api/doctor/alerts` | `pages/doctor/AlertsPage.tsx` | Открытые/исторические оповещения |
| `POST /api/doctor/alerts/{aid}/delivered` | `components/Layout.tsx` | Подтверждение получения live-оповещения клиентом |
| `POST /api/doctor/alerts/{aid}/ack` | `pages/doctor/AlertsPage.tsx` | Подтверждение просмотра/принятия сигнала врачом |
| `POST /api/doctor/alerts/{aid}/resolve` | `pages/doctor/patient/OverviewTab.tsx` | Закрытие обработанного оповещения с указанием результата |
| `POST /api/doctor/adverse-events/{eid}/review` | `pages/doctor/patient/OverviewTab.tsx` | Фиксация проведённого врачебного разбора нежелательной реакции |
| `GET /api/doctor/actions` | `pages/doctor/ClinicalActionsPage.tsx` | Очередь предлагаемых, подтверждённых и отклонённых клинических действий |
| `POST /api/doctor/actions/{aid}/decide` | `pages/doctor/ClinicalActionsPage.tsx` | Явное подтверждение или отклонение решения врачом |
| `GET /api/doctor/actions/{aid}/pv-report` | `pages/doctor/ClinicalActionsPage.tsx`, `OverviewTab.tsx` | Черновик извещения фармаконадзора для проверки врачом |
| `POST /api/doctor/patients/{pid}/documents` | `pages/doctor/patient/DataTab.tsx` | Извлечение полей из текстовой выписки и проверка перед применением |
| `POST /api/doctor/documents/{did}/apply` | `pages/doctor/patient/DataTab.tsx` | Применение выбранных извлечённых данных в карточку пациента |
| `GET /api/doctor/patients/{pid}/summary` | `pages/doctor/patient/OverviewTab.tsx` / `PatientLayout.tsx` | Сводка/контекст для визита и обзора |
| `GET /api/doctor/patients/{pid}/fhir` | `pages/doctor/patient/OverviewTab.tsx` | Выгрузка FHIR-представления данных пациента |
| `GET /api/doctor/stream` | `api/stream.ts`, `components/Layout.tsx` | Общий live-поток врача; новые события также синхронизируют открытую страницу оповещений |

## Пациент: самоотчёты, согласия и данные

| Backend route | Frontend | Что даёт пользователю |
|---|---|---|
| `GET /api/about` | `pages/AboutPage.tsx` | Сведения о сервисе из backend |
| `GET /api/consent` | `pages/patient/HomePage.tsx` | Актуальная редакция согласия на обработку персональных данных |
| `GET /api/scales/{code}` | `pages/patient/ScalePage.tsx` | Получение определения шкалы перед заполнением |
| `GET /api/consent/trusted-contact` | `pages/patient/TrustedContactsPage.tsx` | Отдельное согласие на информирование доверенного лица |
| `GET/POST /api/me/trusted-contacts`, `DELETE /api/me/trusted-contacts/{tid}` | `pages/patient/TrustedContactsPage.tsx` | Просмотр, добавление и отзыв доверенного контакта |
| `GET /api/me/overview` | `pages/patient/HomePage.tsx` | Сводка, план, приёмы доз, назначенные шкалы и сообщения |
| `POST /api/me/consent`, `POST /api/me/consent/withdraw` | `pages/patient/HomePage.tsx`, `pages/patient/MyDataPage.tsx` | Принятие и отзыв согласия |
| `POST /api/me/scales` | `pages/patient/ScalePage.tsx` | Отправка самоотчёта по шкале; офлайн-постановка в очередь при недоступности сети |
| `POST /api/me/diary` | `pages/patient/DiaryPage.tsx` | Запись дневника и очередь при временной потере связи |
| `POST /api/me/doses` | `pages/patient/HomePage.tsx` | Отметка приёма/пропуска дозы |
| `POST /api/me/adverse-events` | `pages/patient/AdverseEventPage.tsx` | Отправка нежелательной реакции |
| `GET/POST /api/me/messages` | `pages/patient/MessagesPage.tsx` | Получение и отправка сообщений врачу |
| `POST /api/me/sync` | `components/PatientOfflineSyncPanel.tsx` | Идемпотентная пакетная синхронизация офлайн-очереди; показываются результаты и неудачные элементы |
| `GET /api/me/history` | `pages/patient/HistoryPage.tsx` | История шкал, дневника, реакций и приёмов |
| `GET /api/me/export` | `pages/patient/MyDataPage.tsx` | Выгрузка собственных данных в JSON |
| `GET /api/me/doses.ics` | `pages/patient/HomePage.tsx` | Напоминания о приёме препарата для календаря телефона (iCalendar) |
| `GET /api/me/stream` | `api/stream.ts`, `components/Layout.tsx` | Живые кризисные сигналы, изменения терапии и направления |

## Справочники и клинические знания

| Backend route | Frontend | Что даёт пользователю |
|---|---|---|
| `GET /api/knowledge`, `GET /api/admin/knowledge` | `pages/knowledge/KnowledgePage.tsx` | Список справочников с учётом роли |
| `GET /api/knowledge/{kind}/{code}`, `GET /api/admin/knowledge/{kind}/{code}` | `pages/knowledge/JsonEditorPage.tsx`, специализированные редакторы препаратов/шкал/правил | Просмотр исходной активной версии |
| `GET /api/knowledge/schemas/{kind}` | `pages/knowledge/JsonEditorPage.tsx` | JSON Schema для выбранного типа знания |
| `GET /api/knowledge/variables` | `pages/knowledge/rules/RulesEditorPage.tsx` | Каталог переменных редактора правил |
| `GET /api/knowledge/actions` | `pages/knowledge/rules/ActionsEditor.tsx` | Каталог действий правила |
| `GET /api/knowledge/scoring-methods` | `pages/knowledge/scale-editor/ScaleEditorPage.tsx` | Поддерживаемые методы подсчёта шкал |
| `POST /api/knowledge/validate` | `pages/knowledge/ProposeBar.tsx`, редактор шкал | Проверка структуры до отправки изменения |
| `POST /api/knowledge/scales/preview` | `pages/knowledge/scale-editor/ScaleEditorPage.tsx` | Пробный подсчёт черновика шкалы |
| `POST /api/knowledge/rules/test` | `pages/knowledge/rules/RuleTester.tsx` | Проверка условия на разрешённом пациенте с пошаговым объяснением |
| `POST /api/knowledge/import/fhir-questionnaire`, `POST /api/knowledge/import/csv` | `pages/knowledge/ImportScalePage.tsx` | Импорт шкалы из CSV или FHIR Questionnaire |
| `GET /api/knowledge/scales/{code}/fhir` | `pages/knowledge/KnowledgePage.tsx` | Экспорт шкалы в FHIR Questionnaire JSON |
| `PUT /api/knowledge/{kind}/{code}`, `PUT /api/admin/knowledge/{kind}/{code}` | `pages/knowledge/ProposeBar.tsx`, редакторы | Отправка правок на предусмотренный backend-процесс утверждения |
| `GET /api/admin/knowledge/{kind}/{code}/versions` | `pages/knowledge/VersionsPage.tsx` | История версий |
| `POST /api/admin/knowledge/{kind}/{code}/rollback` | `pages/knowledge/VersionsPage.tsx` | Создание черновика отката |
| `POST /api/admin/knowledge/reload` | `pages/knowledge/KnowledgePage.tsx` (администратор) | Сравнение YAML в репозитории с активной базой и создание черновиков изменений |
| `GET /api/review/knowledge`, `POST /api/review/knowledge/{vid}` | `pages/knowledge/ReviewPage.tsx`, reviewer-only route | Очередь согласования и решение рецензента |

## Администрирование, аналитика и мониторинг

| Backend route | Frontend | Что даёт пользователю |
|---|---|---|
| `GET/POST /api/admin/users`, `PATCH /api/admin/users/{uid}`, `POST /api/admin/users/{uid}/reset-password` | `pages/admin/UsersPage.tsx` | Учётные записи, изменение ролей/параметров и сброс пароля |
| `GET /api/admin/patients`, `POST /api/admin/patients/{pid}/attending` | `pages/admin/PatientsAdminPage.tsx` | Список пациентов и создание запроса на смену лечащего врача |
| `GET /api/admin/attending-requests` | `pages/admin/PatientsAdminPage.tsx` | Очередь запросов на смену ведущего врача |
| `POST /api/admin/attending-requests/{rid}/approve`, `POST /api/admin/attending-requests/{rid}/reject` | `pages/admin/PatientsAdminPage.tsx` | Подтверждение вторым лицом или отклонение запроса на смену ведущего врача |
| `GET /api/admin/audit`, `GET /api/admin/audit/verify` | `pages/admin/AuditPage.tsx` | Журнал аудита и проверка целостности |
| `GET /api/admin/notifications` | `pages/admin/NotificationsPage.tsx` | Журнал SMS и push: получатель, канал, статус доставки; номера маскируются |
| `GET /api/analytics/summary` | `pages/AnalyticsPage.tsx` (администратор или врач-рецензент) | Обезличенная статистика с k-анонимностью |
| `GET /api/metrics` | `pages/admin/MetricsPage.tsx` (только администратор; backend требует роль `admin`) | Метрики API, доставки, ack, рекомендаций, извлечения и backup-drill |
| `GET /api/health`, `GET /api/ready` | `pages/admin/MetricsPage.tsx`, `pages/admin/SystemPage.tsx` | Публичные liveness/readiness probes без раскрытия внутренней диагностики; подробности — через защищённый `/api/admin/system` |
| `GET /api/admin/system` | `pages/admin/SystemPage.tsx` | Состояние компонентов, очередей, задач, справочников и бэкапов |

## Поведение вне отдельных страниц

- `GET /api/doctor/stream` и `GET /api/me/stream` интегрированы в оболочку `Layout`; перед подключением SSE используется `/api/auth/stream-ticket`. Данные API не кешируются Service Worker.
- `POST /api/doctor/patients/{pid}/visit` — короткий alias того же создания визита, которое доступно в форме `VisitsHistory` через более подробный `POST /visits`; отдельной второй кнопки для дублирующего контракта намеренно нет.
- Кризисные события обрабатываются на сервере в правилах, но frontend только отображает пришедшие сигналы/инструкции; сам UI не диагностирует и не назначает лечение.
- Офлайн поддерживается для разрешённых пациентских POST-записей: они шифруются Web Crypto перед хранением в IndexedDB и отправляются только в `POST /api/me/sync`. `/api`, ответы с медицинскими данными, логин и сессии Service Worker не кеширует. Это не заменяет защиту устройства и проверку серверной авторизации.

## Что всё ещё требует проверки интеграционными тестами

1. Успешная доставка SSE-события и квитанции `delivered` в целевой multi-worker PostgreSQL окружении.
2. Сборка фронтенда/typecheck и тесты Vitest в окружении с установленными пакетами.
3. Проверка офлайн/онлайн сценария в реальном браузере и тест восстановления Service Worker.
4. Клиническая сверка справочников/шкал и production MFA-bootstrap на целевом окружении.
5. Нагрузочные и восстановительные тесты на фактической целевой инфраструктуре.
6. Регрессионные тесты часовых поясов (`backend/tests/test_visit_timezone.py`) запускаются после установки backend-зависимостей.
