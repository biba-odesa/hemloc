# History, audit retention и внешние уведомления

Реализовано в исходниках после v0.1.0; установка этого изменения — отдельное
действие оператора. Defaults: retention и notifications выключены. Не запускать
очистку рабочей БД без предварительного просмотра точного состава удаления.

## History и доступ

Три вкладки с серверными COUNT, фильтрами, ORDER BY и LIMIT/OFFSET в SQLite:

| Вкладка | Категория API | Срок по умолчанию |
| --- | --- | --- |
| Blocklist changes | `blocklist` | 365 дней |
| Users & access | `users_access` | 90 дней |
| Errors & security | `errors_security` | 7 дней |

Guest видит только Blocklist changes, в том числе при прямом запросе `/api/history`
или `/api/audit`, поиске и подсчёте. Admin видит все три вкладки. Неизвестные события
доступны admin через `category=unknown` API и CLI export, но не образуют четвёртую
вкладку и не удаляются автоматически. Фильтры API: `q`, `action`, `result`, `node`,
`who`, `since` (включительно), `until` (исключительно), `page_number`, `size` (1–100).
Границы API — Unix timestamps; поля дат в браузере используют локальную зону,
время события показано с зоной и UTC offset. При смене фильтра страница сбрасывается.

Классификация вычисляется из исходного action/result и сохранённого before/after;
исходные документы не переписываются. Успешные сохранённые rule create/import/
comment/delete, ASN confirm и изменившийся принятый набор при ASN refresh —
blocklist. Отказ в изменении правила — errors/security, не изменение блокировок.
Известные user/auth actions — users/access; анонимный запрещённый session/password/
user доступ — errors/security. Неизменившийся служебный refresh, maintenance и
неизвестные actions сохраняются бессрочно. На таблицах обоих источников есть
индексы выражения категории и времени; поиск выполняется SQL, не загрузкой всего
аудита в Python. Поиск включает action и его английскую подпись, автора, узел,
результат, комментарий, ASN, имя и префиксы.

Собственная карточка Users доступна guest. Последние пять успешных входов каждой
identity сохраняются независимо от retention и существования/отключения пользователя.
Порядок `(at DESC, id DESC)`, оба узла, дедупликация event ID. Источник — тот же аудит
и локальный security outbox, отдельной репликации входов нет. Guest не читает чужую
историю; admin читает историю любого пользователя. Недоступный peer не считается
актуальным источником.

## Конфигурация

```ini
[retention]
enabled = no
blocklist_days = 365
users_access_days = 90
errors_security_days = 7
cleanup_time = 01:00
timezone = Europe/Kyiv
batch_size = 200
```

Все сроки — положительные целые 1–36500 дней, партия 1–500. Ноль недопустим;
`never` не поддерживается. `enabled=no` отключает автоматическую очистку целиком,
но не запрещает явно выполненный ручной prune. Неизвестные категории бессрочны.
Для IANA timezone нужна системная база Debian `tzdata`; она указана в DEPLOYMENT.
Проверка зоны IANA и времени HH:MM выполняется при запуске. Срок — прошедшие
`days * 86400` секунд; события точно на cutoff остаются. Расписание — местное
календарное время, не фиксированный UTC offset.

Один текущий master выполняет встроенную задачу без cron. По умолчанию слот —
01:00 Europe/Kyiv, с DST. За одну локальную дату слот учитывается один раз; если
настроить неоднозначное время осеннего перехода, используется первое вхождение,
несуществующее весеннее время нормализуется вперёд. После остановки выполняется
один догоняющий запуск за последнюю наступившую дату, не по запуску за каждый
пропущенный день. В `local` сохраняются точный план, дата, retry-at проверки
доступности peer и прогресс партий. Повторная проверка отложенной задачи — через
60 секунд. При изменении истории или policy автоматическая задача строит новый
план; CLI не принимает план от другой истории/policy.

Отдельный advisory lock запрещает одновременные CLI/background очистки. Каждая
партия — короткая транзакция: проверка master/history/документов/пяти входов,
точечное удаление, receipts, maintenance-аудит и запись журнала. При аварии
незавершённая партия откатывается; завершённые IDs повторно не удаляются и
повторного maintenance-аудита для них нет. Новые события не добавляются в уже
сохранённый план. После явного включения enabled штатные ежедневные запуски не
требуют отдельных подтверждений.

## Репликация и совместимость

Новая capability — `audit-prune-v2`. Обычные документы и snapshot schema 1
совместимы с v0.1.0 **до первого prune**, пока новые notification failure/security
contexts не передаются старому peer. Поэтому и notifications включать только
после обновления обоих узлов. Протокол не меняет правила, credential versions,
сессии, protection, desired state или GoBGP.

Cleanup при настроенном peer требует свежего статуса (не старше 60 секунд),
capability, slave-роли peer, подтверждения текущего history/sequence и полностью
принятого известного security outbox. При недоступном/отставшем/старом peer
очистка откладывается, не угадывает совместимость. В односерверной конфигурации
без peer этот gate отсутствует. Это ограничение намеренно предпочитает сохранение
аудита его удалению во время неопределённости.

Удаление — отдельная операция `audit_prune`, IDs + SHA256 исходных документов,
не произвольный audit delete. Общий запрет редактирования/удаления аудита сохранён.
Slave применяет эту операцию транзакционно с cursor и самостоятельно TTL не считает.
Receipt хранит только ID/digest и остаётся при snapshot и promotion. Он исключает
возврат документа через повторную доставку, local outbox или старый snapshot.
Snapshot после prune имеет schema 2 с receipts в той же read transaction, что
документы и sequence. Snapshot до prune догоняется обычным журналом. Неподдерживающий
peer получает явный отказ на snapshot/events после prune; скрытого downgrade нет.

Security outbox **физически пока не сокращается**: его транспортные payload и
монотонные seq остаются, поэтому pending события и строгая непрерывность cursor
не теряются. Pruned ID исключён из History/export и повторной публикации. Master
передаёт generation/cursor подтверждения в status; slave сохраняет его локально.
Сокращение transport outbox и journal с floor/bootstrap не входит в эту поставку.
Нельзя удалять эти таблицы вручную ради экономии места.

Перед ручным failover по-прежнему изолируют прежний master и проверяют актуальность
slave. Нет гарантии сохранения ещё не доставленных изменений из изолированной
ветки. Старый master возвращается как slave и принимает snapshot без merge;
локальные protection и pending security facts сохраняются, pruned receipts не
теряются. Восстановление **старого backup без новых receipts на всех узлах** может
вернуть старый аудит: retention не стирает backups. Для восстановления выбирайте
актуальный согласованный backup и штатную синхронизацию с актуальным master.

### Порядок обновления двух узлов

1. Оставить retention/notifications выключенными, подготовить штатные backups.
2. Обновить slave на один выбранный новый commit, перезапустить только Hemlock.
3. Обновить master на тот же commit, перезапустить только Hemlock.
4. Проверить обычную репликацию, history/cursor, capability обоих, security ack,
   собственные входы и History. GoBGP не перезапускать.
5. На изолированном стенде проверить handler. На рабочих узлах сначала preview
   реального состава удаления и согласовать его с оператором.
6. После review включить retention на master; slave получает точные решения.
   Notifications включать отдельно на нужных узлах после проверки handler и прав.

После первого prune нельзя откатывать один узел на v0.1.0. Для rollback нужен
отдельный согласованный план восстановления обоих узлов; не перемещать v0.1.0 tag.

## CLI: preview, export, prune

Команды выполняет root с реальным путём INI. CLI затем использует владельца БД
для SQLite sidecars и файлов. Каталог экспорта/плана должен быть закрытым и
доступным этому пользователю; не помещать файлы в Git. Например, как root:

```bash
install -d -o hemloc -g hemloc -m 0700 /var/lib/hemloc/audit-exports
hemlock --config /etc/hemloc/hemloc.ini audit preview \
  --output /var/lib/hemloc/audit-exports/plan.json
hemlock --config /etc/hemloc/hemloc.ini audit export
hemlock --config /etc/hemloc/hemloc.ini audit export \
  --output /var/lib/hemloc/audit-exports/audit.jsonl --execute
hemlock --config /etc/hemloc/hemloc.ini audit prune \
  --plan /var/lib/hemloc/audit-exports/plan.json
```

Preview показывает counts по категориям, cutoffs, policy, историю и digest; файл
содержит **точные IDs и hashes**, не тела событий. Export без execute — только
счётчик; execute создаёт новый 0600 JSONL без перезаписи. Экспортируются события
History, не journal; before/after ограничены известными полями, неизвестный opaque
request context не экспортируется. Не выводите содержимое экспорта в общий терминал.

До первой рабочей очистки оператор должен получить состав preview и digest,
проверить сроки и исключения последних пяти входов. Только после разрешения:

```bash
hemlock --config /etc/hemloc/hemloc.ini audit prune \
  --plan /var/lib/hemloc/audit-exports/plan.json --execute
```

Это ручное действие применяет сохранённый план, не заново вычисленный расширенный
набор. Смена роли/history/policy, изменённый документ или неготовый peer запрещают
очистку. Plan digest проверяется при чтении. Повтор уже применённого плана безопасен.
Недавно созданные события остаются до согласованных cutoff, даже если их много.

Retention не удаляет копии из append-only journal, outbox transport, backups и
ранее созданных exports. Их файловый lifecycle отдельный. DELETE освобождает
страницы внутри SQLite и не гарантирует уменьшения файла БД. Автоматического
VACUUM, усечения journal или принудительного WAL checkpoint нет.

## Уведомления: одна попытка

```ini
[notifications]
enabled = no
script = /usr/sbin/notify_script
timeout_seconds = 15
blocklist_changes = yes
login_blocked = yes
suspicious_access = yes
queue_size = 100
workers = 1
suspicious_threshold = 30
suspicious_window_seconds = 60
suspicious_cooldown_seconds = 900
```

Абсолютный executable path; timeout `(0,120]` секунд, queue_size 1–10000,
workers 1–4, threshold 1–100000, window 1–3600 секунд, cooldown 1–86400 секунд.
Script запускается напрямую, без shell, под пользователем сервиса. Stdin — UTF-8
JSON **ровно с двумя строковыми полями** `subject` и `body`. В argv нет ни body,
ни credentials. Subject ограничен 200, body 8000 символами, недоверенные значения
внутри сводки дополнительно ограничены. stdout/stderr не читаются в память,
не попадают в аудит или журнал; stderr нельзя использовать для передачи диагностики.

Master ставит blocklist notification после commit: автор, действие, ASN/префикс,
комментарий, числа добавленных/удалённых префиксов. Импорт — одна сводка до 20
подробностей, затем число остальных. Неизменившийся ASN refresh не уведомляет.
Slave при replay/snapshot ничего не отправляет. Локальный auth/security источник
работает на любой роли без master: login limit описывает только ограничение входа
с данного IP и оставшееся время текущего 15-минутного окна. Это не firewall ban.
Одна login-limit нотификация на окно ограничений, не на каждую отклонённую попытку.

Suspicious access учитывает реальный socket IP, не Forwarded/X-Forwarded-For,
и категории unauthorized/invalid requests. Первые 29 подходящих событий за 60
секунд не вызывают уведомление; тридцатое вызывает. Повтор продолжающейся
активности — не чаще 900 секунд на IP/категорию. Для bounded memory хранятся
последние threshold timestamps, сообщение честно указывает **at least N** событий
в указанном окне; максимум 10000 отслеживаемых источников, старейший вытесняется.
При распределённой атаке вытеснение может уменьшить полноту детекции. Каждый
исходный запрет продолжает индивидуально аудироваться. 409 Conflict и 5xx не
считаются сканированием; 4xx типов 400/401/403/404/405/413/415/422/429 учитываются.
Notification failures не входят в агрегатор и не уведомляют о себе.

Ограниченная очередь в памяти и фиксированные worker threads выполняют процесс
вне HTTP и BGP reconciliation. **Ровно одна попытка**, без durable retry queue,
восстановления сообщений после рестарта или гарантий доставки. Pending сообщения
могут потеряться при остановке/аварии. Exit 0 — успех; timeout убивает группу
процесса, nonzero/отсутствующий executable/queue full — notification.failed в
Errors & security и ограниченная запись journal с reason/exit code без stderr.
Ошибка доставки не откатывает изменение и не влияет на BGP. При disabled script
не запускается. Не передавайте секреты в комментариях: они входят в нужную
операторскую сводку.

### Права и systemd

Пример без credentials: `tools/notification_example.py`. Для ручного теста под
пользователем сервиса (от root), после установки администратором handler:

```bash
printf '%s\n' '{"subject":"Hemlock test","body":"Test notification"}' | \
  sudo -u hemloc /usr/sbin/notify_script
```

Handler и его родительские каталоги не должны быть writable пользователем Hemlock.
Например root:hemloc 0750 для executable, root:hemloc 0640 для отдельного файла
credentials, закрытые родительские каталоги. Credentials выбирает/читает только
handler; Hemlock их не конфигурирует, не получает и не хранит. Не класть их в argv,
Git, /home или /root.

Поставляемый unit: User/Group hemloc, NoNewPrivileges, пустой CapabilityBoundingSet,
ProtectHome, ProtectSystem=strict, PrivateTmp, writable `/var/lib/hemloc`,
RestrictAddressFamilies AF_UNIX/AF_INET/AF_INET6. Поэтому тест `sudo -u` не полностью
воспроизводит sandbox сервиса: handler не видит home/root, общий /tmp, не может
писать произвольно в /etc или повышать privileges. Файлы в /etc можно читать при
правильных правах. Собственный CA/proxy handler настраивает самостоятельно: INI
proxy Hemlock не управляет внешним executable. Глобально ослаблять unit ради handler
не нужно; выбрать совместимый script и отдельный доступный credentials-файл.
