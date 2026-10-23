# Собственные сертификаты и approval SPKI

Hemlock 0.5.0 поддерживает два **явно выбранных** TLS-режима. Новая установка
использует `pinned`; существующий INI без секции `[tls]` остаётся `legacy_ca`.
Автоматического downgrade нет. Версия репликации остаётся **3**: snapshot,
journal, security outbox, token, node identity и protocol handshake не меняются.
Знакомство `/tls/introduction` отделено от authenticated replication endpoints.

## Новый узел без CA

Конфиг должен содержать уникальный node ID, ожидаемый peer node ID, HTTPS
peer_url и общий секрет репликации. Секрет передаётся отдельно по защищённому
каналу в файл 0640 root:hemlock; его значения не выводят и не передают в argv.
Следующий пример — для стандартной новой установки:

```ini
[web]
host = 192.0.2.10
port = 8443
tls = yes
cert = /var/lib/hemlock/tls/identity/server.crt
key = /var/lib/hemlock/tls/identity/server.key
ca =

[tls]
mode = pinned
state_dir = /var/lib/hemlock/tls
names = 192.0.2.10,block-a.example.invalid
days = 365
warn_days = 30
```

IP/DNS заменить своими. `names` задаёт SAN для веба, пустое значение использует
web host. Для `0.0.0.0`/`::` SAN нужно задать явно. Peer pin удостоверяет ключ,
а не сетевой адрес: смена peer_url/IP при прежних ожидаемом node ID и ключе
не требует approval. Браузеру при новом IP может потребоваться подходящий SAN.
Менять ожидаемый node ID без отдельного подтверждения нельзя.

Установщик создаёт `/var/lib/hemlock/tls` как hemlock:hemlock 0700. Identity —
отдельный каталог только для пары; приложение атомарно публикует его с правами
0700, файлы cert/key — 0600, владелец hemlock. Не размещайте там trust.json,
БД или другие файлы. StateDirectory/ReadWritePaths unit уже разрешает запись
в data directory, root или права systemd-control приложению не нужны.

Если обоих файлов нет, при старте создаётся ECDSA P-256 ключ и самоподписанный
X.509 сертификат с server/client authentication. Если отсутствует только один,
файлы повреждены, не совпадают, имеют чужого владельца, symlink или открытые
группе/остальным права — запуск завершается конкретной ошибкой. Приложение не
чинит права и не уничтожает такие файлы. До первого старта должны быть готовы
INI/секрет/peer/protection; CA key ни создавать, ни переносить не требуется.

## Знакомство и approval на КАЖДОМ узле

После заполнения конфига запустите службу. Отсутствие approval останавливает
только репликацию, а не работу по сохранённым правилам/локальную BGP reconciliation.
Пустой slave получает пользователей только после доверия и snapshot, поэтому
первый approval на нём выполняет root через CLI. Администратора на slave не создают.

На **каждом сервере**, от root:

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls self
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls peer
```

Сверьте candidate fingerprint с `tls self` на **другом** сервере через консоль
или независимый доверенный канал. Формат `SHA256:<base64 без padding>`, алгоритм
**SHA256 SPKI**: хеш DER SubjectPublicKeyInfo, не хеш всего сертификата. Заявленный
node ID — лишь заявление, до такой сверки он не доказывает личность.

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls approve \
  --fingerprint 'SHA256:<COMPLETE_VERIFIED_FINGERPRINT>'
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls trust
```

Повторите независимо на втором узле. `tls peer` должен предшествовать approval;
подтверждается конкретный просмотренный fingerprint. Перед сохранением делается
новое знакомство: изменившийся candidate даёт отказ, а не approval другого ключа.
Существующий pin не заменяется: сначала явный отзыв, затем просмотр и approval.

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls revoke \
  --fingerprint 'SHA256:<CURRENT_APPROVED_FINGERPRINT>'
```

CLI работает без пользователей и исправной БД. Root сбрасывает права до владельца
TLS state directory (или его подготовленного parent). Созданные файлы не становятся
root-owned. После CLI approval работающий listener перечитывает доверие в течение
10 секунд; отдельный restart для approval не нужен. Web approval применяет его
сразу. Начиная с 0.5.1 просмотр, Refresh/Approve/Revoke доступны в Settings → Peer TLS;
на Dashboard остаётся компактный статус и Review connection при проблеме.
изменения — только admin с CSRF на обеих ролях. Guest видит сведения без кнопок
и локального TLS-аудита. Остальные master-only ограничения не меняются.

## Проверка каждого соединения

До approval идёт только ограниченный публичный обмен node ID, SHA256 SPKI,
валидности сертификата и публичным подтверждением ожидаемого peer-ключа.
Нет token/cookies/credentials, snapshot, журнала или аудита. Публичный ответ
ограничен 32 KiB; redirects запрещены; соединения идут только к configured
peer_url напрямую, без HTTP proxy/environment proxy.

После approval используется mTLS. Клиент проверяет SPKI **на самом сокете**
до отправки Authorization. На том же соединении публично проверяется взаимное
approval; затем действуют прежние Bearer secret/node ID/protocol-3 handshake.
Сервер допускает обычные браузеры без client certificate, но ВСЕ replication
endpoints требуют подтверждённый TLS client certificate, token, identity и
подтверждённую версию протокола. Даже прямой endpoint-запрос при одностороннем approval отклоняется: сервер
проверяет публичное подтверждение другого узла по configured pinned peer_url.
Client DER берётся из реального TLS transport,
не из Forwarded/X-Forwarded-For/HTTP-заголовков.

CA verification заменяется explicit SPKI authentication только в специальном
pinned peer transport. Другие HTTP-клиенты и legacy_ca сохраняют обычную проверку;
глобального verify=False нет. Отзыв pin проверяется приложением на каждом
replication request, даже если OpenSSL context ещё помнит прежний client anchor.
Свежая локальная TLS-проверка также обязательна для readiness retention prune.
Незавершённый сетевой запрос при отзыве может уже находиться в обработке; отзыв
останавливает последующие запросы, не является откатом уже committed операций.

Trust и подробный TLS-аудит лежат в локальном `state_dir/trust.json`, atomically
updated, owner-only, с interprocess lock. Они НЕ входят в snapshot/journal/outbox.
Это отдельный локальный аудит TLS-администрирования; формат общего аудита не
расширялся, чтобы старый protocol-3 peer не получал неизвестные действия.
Файл ограничен 2 MiB: по достижении предела требуется отдельное операторское
архивирование; записи автоматически не удаляются. Последние 20 видны admin.
Сохраняйте весь TLS state/identity отдельно от SQLite backup с закрытыми правами.

## Истечение и ротация

`days` — срок новой пары (1..825), `warn_days` — предупреждение (1..90).
Раз в 10 секунд проверяется срок. Предупреждение о скором истечении журналируется
и, при включённых notifications, ставится в существующую ограниченную очередь
один раз на сертификат. Rotation — также одно best-effort уведомление, без retry
и воспроизведения старых сообщений. Ключи/token не входят в body или журнал.

При истечении в pinned-режиме listener HTTPS контролируемо завершает запросы и
фоновые задачи. Только после его остановки просроченная пара удаляется,
атомарно публикуется новая и HTTPS запускается снова внутри того же приложения.
Это перезапуск **Hemlock HTTPS**, а не GoBGP/systemd или BGP-сессий.
HTTP-запросам даётся до 30 секунд на завершение; затем ожидаются уже выполняемые
фоновые операции. Поэтому общая длительность зависит от их объёма и таймаутов,
это не обещание мгновенного restart. Транзакции не обрываются принудительно.
Сохранённая локальная RIB остаётся у GoBGP. Новый ключ требует повторного approval
на другом узле; автоматической замены pin по прежнему имени нет. Для ручной замены
файлов также нужен restart только Hemlock. `tls self` не ротирует просроченную
пару под работающим listener — он показывает её для диагностики.

Браузерное доверие — отдельно: самоподписанный веб-сертификат требует явной
проверки/доверия в браузере. Replication approval не устанавливает доверие браузера.
После ротации обновите и его после сверки с консолью, без безусловного обхода TLS.

## Переход существующей CA-пары B → A

1. Сохранить SQLite backup, INI, TLS и секреты; старые production keys не удалять.
2. До обновления явно оставить/задать `[tls] mode = legacy_ca` на обоих узлах,
   сохранить старые cert/key/ca пути и штатную CA/name verification.
   Обновить сначала B, затем A, перезапуская только Hemlock. Пустая секция TLS
   старого INI по умолчанию также означает legacy_ca. Протокол всё время 3.
3. После обновления обоих и проверки синхронизации выбрать pinned на обоих.
   Если retention уже включён, приостановите его на время смены TLS-режима
   до восстановления свежей синхронизации; сроки policy не менять.
   Подготовить service-owned 0700 state_dir внутри разрешённого data directory,
   новые cert/key пути в его отдельном identity directory и SANs.
   Старую CA-пару оператор сохраняет и при необходимости удаляет отдельно;
   автоматическое обновление её не удаляет. CA private key новому режиму не нужен.
4. По очереди переключить режим и перезапустить только Hemlock. Пока режимы
   различаются или нет взаимного approval, синхронизация приостановлена. Правила,
   данные, protection, роль и GoBGP сохраняются. Никакого fallback/auto downgrade.
5. Сверить fingerprints консолями, `tls peer`, затем approve на A и B. Через
   очередной polling выполняется journal catch-up или штатный snapshot;
   проверить свежий In sync, generation/cursor/zero lag и drained security outbox.
   Обычное обновление не требует переустановки slave.

Для старых путей используйте реальные config/CLI/unit из ExecStart, не копируйте
стандартные пути вслепую. Не меняйте node ID/owner/роль при TLS-переходе.

## Отдельное восстановление повреждённого slave

TLS-ошибка никогда не сбрасывает БД. Если SQLite действительно повреждена,
сначала остановить **только Hemlock**, сохранить INI/TLS/trust, установить
role=slave и announcements=no. Не использовать этот способ для master: у него
штатная процедура переключения с backup и routing fence.

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini database reinitialize
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini database reinitialize --execute
```

Первый вызов — dry-run. Execute требует process lock, сохраняет исходные DB/WAL/SHM
в новый private backup directory, ведёт отдельный recovery marker и создаёт пустую
slave DB. Не перезаписывает backup; прерванное восстановление можно продолжить.
Узнаваемый master и незавершённый role transition отклоняются. Protection cache
переносится только если он читается из старой БД; если нет — исходные файлы
остаются в backup, защита должна инициализироваться заново и быть согласована
до включения анонсов. Pin/identity остаются вне заменяемой БД. После запуска
slave получает snapshot после взаимного доверия. Пользователя на нём не создают.
Повторный execute после завершения отклоняется, не стирает новую БД снова.
