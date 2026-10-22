# Обновление, backup, rollback и смена ролей

Совместимость 0.4.1: явный протокол **3**, обновление **B → A**, без переустановки slave для обычного обновления. [Проверка совместимости и порядок обновления](REPLICATION_PROTOCOL.md).

Для канонических установок 0.4.0+: `/opt/hemlock`, `/etc/hemlock`,
`/var/lib/hemlock`, `hemlock.service`, пользователь/CLI `hemlock`.
Прежние установки сначала проходят [MIGRATION_LEGACY.md](MIGRATION_LEGACY.md).
Нельзя запускать installer поверх работающей системы. Команды — root.

## Выбранный переход существующей пары на 0.4.0

Порядок A с сохранением данных + чистая B только с INI/TLS/secret:
[PAIR_UPGRADE_040.md](PAIR_UPGRADE_040.md). Общий A-only перенос БД из
MIGRATION_LEGACY.md не относится к новой B. Ни fresh installer, ни обычный updater
не являются скрытой миграцией существующего master.

## Backup

Backup CLI использует SQLite backup API, не `cp` открытого SQLite:

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini backup \
  "/var/lib/hemlock/backup-$(date +%Y%m%d-%H%M%S).sqlite"
```

Путь назначения новый, приватный 0600, владелец БД. Копия содержит replicated data
и локальный protection cache. Отдельно безопасно сохраните INI, сертификаты/ключи,
replication secret, units/drop-ins, notification handler/credentials и provenance
GoBGP; это приватные материалы, не Git. Проверяйте offline `PRAGMA integrity_check`
на копии и восстановление в отдельном стенде. Retention не удаляет старые записи
из journal/backups/exports; автоматического VACUUM нет.

## Обновление одной совместимой канонической пары

Сначала slave, дождаться fresh In sync/отставание 0, затем master. Роли/конфиги,
node ID/owner и GoBGP не менять. Это порядок внутри совместимой линии 0.4.x;
смешанная пара с 0.3.x не поддерживается — миграция согласованная.
Выберите опубликованный фиксированный тег/полный SHA и проверьте release notes.
До замены подготовьте rollback wheel текущего установленного commit и backup.

```bash
cd /opt/hemlock
git status --short
git fetch origin refs/heads/main
git restore --source=FETCH_HEAD -- update.sh
./update.sh --version '<PUBLISHED_TAG_OR_FULL_COMMIT>'
```

`./update.sh` без аргументов выбирает последний main, фиксирует FETCH_HEAD и
устанавливает именно этот commit. Tracking ref origin/main не требуется.
Проверка существующей версии/config/role/node выполняется до остановки сервиса.
Далее build → stop hemlock → SQLite backup → locked dependencies/wheel → pip check
→ start hemlock. Ошибка после stop оставляет приложение остановленным для
диагностики; автоматического запуска неполной установки/автоматического rollback
нет. Staging и backup сохраняются. Никогда не обновляйте перемещённый venv вслепую.

```bash
systemctl is-active hemlock.service
journalctl -u hemlock.service -n 40 --no-pager
/opt/hemlock/.venv/bin/python -I -c \
  'from importlib.metadata import version; print(version("hemlock"))'
```

Проверьте браузер с cache refresh, локальную версию, generation/cursor, zero lag,
protection и fresh local RIB/export. GoBGP не перезапускается. Startup role
transition не должен выполняться при обычном обновлении с неизменной ролью.
Новые flags retention/notifications выключены, пока их явно не включил оператор.

## Откат пакета

После оценки совместимости схемы/протокола остановите только приложение,
сохраните текущую БД штатным backup и конфиги. Установите заранее проверенный
wheel предыдущего commit (с его lock-файлом), затем pip check и старт приложения.
Это **не** восстановление старой БД и не автоматический merge. Если предыдущий
релиз не понимает текущий протокол/transition marker, сначала согласуйте обе
стороны и восстановление; не downgrаde незавершённый demotion.

```bash
systemctl stop hemlock.service
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini backup \
  "/var/lib/hemlock/before-rollback-$(date +%Y%m%d-%H%M%S).sqlite"
/opt/hemlock/.venv/bin/python -m pip install --require-hashes -r /root/rollback/requirements.lock
/opt/hemlock/.venv/bin/python -m pip install --no-deps --force-reinstall /root/rollback/hemlock-PREVIOUS-py3-none-any.whl
/opt/hemlock/.venv/bin/python -m pip check
systemctl start hemlock.service
```

## Восстановление обычного backup

Остановите приложение и все maintenance clients; при необходимости изолируйте
BGP/конкурирующий master. Проверьте роль/node ID backup и выберите авторитетную
историю. Сделайте checkpoint текущей БД штатно, сохраните её вместе с sidecars в
новом закрытом каталоге. Не смешивайте WAL/SHM с восстановленным файлом.

```bash
systemctl stop hemlock.service
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini transition checkpoint --execute
DATABASE=/var/lib/hemlock/hemlock.sqlite
SAVED=$(mktemp -d /var/lib/hemlock/before-restore.XXXXXX)
chmod 0700 "$SAVED"
for FILE in "$DATABASE" "$DATABASE-wal" "$DATABASE-shm" "$DATABASE-journal"; do
  if test -e "$FILE"; then
    mv -n -- "$FILE" "$SAVED/"
  fi
done
install -o hemlock -g hemlock -m 0600 /root/restore/VERIFIED_BACKUP.sqlite "$DATABASE"
```

Остановитесь при любой ошибке. Не копируйте чужую рабочую БД на slave: там
snapshot/journal. Если есть незавершённый role transition, используйте специальный
reset-after-restore из ROLE_TRANSITIONS.md до запуска. При обычном восстановлении
без такого marker reset не нужен. После проверки identity/role/protection
запустите hemlock и проверьте TLS, generation/cursor и actual RIB.

## Смена ролей: поведение v0.3.0 сохранено в 0.4.0

1. Изолируйте/выключите старый master. Не должно быть двух writable masters с BGP.
2. На выбранном slave сохраните backup, в **локальном INI** поменяйте только
   role=master, проверьте права и restart **только hemlock**. Promotion сохраняет
   правила, пользователей, аудит/cache, создаёт новую history UUID; старый journal
   архивируется, ничего не очищается. Автоматического promotion нет.
3. Старый master возвращайте сначала с отключённой сетью. Установите ту же версию,
   в его INI задайте role=slave и peer URL/identity нового master, сохраните собственные
   node ID/owner/TLS/secret. После review верните только необходимую связь.
4. При startup master→slave приложение сначала ставит durable fence вне БД,
   адресно отзывает все найденные local paths выделенного GoBGP и проверяет пустые
   IPv4/IPv6 RIB. Затем checkpoint/закрытие, уникальный backup старой БД, новая
   пустая slave-БД с локальными identity и protection. Старые replicated данные и
   browser sessions не переносит. После этого — штатный snapshot/journal.

Конфиги/TLS/секреты/owner не меняются кодом. GoBGP не запускается/останавливается/
перезапускается, BGP sessions адресно не сбрасываются. При сбое startup старые
данные не получают обычные фоновые задачи и не возвращаются в reconciliation.
Обычный slave→slave restart при offline master **не очищает** данные/анонсы.
Два доступных master дают role conflict, state не принимается/не объединяется.
В сетевом разделении доказать отсутствие другого master невозможно.

### Остановленный versus недоступный GoBGP

Оператор проверяет:

```bash
systemctl show gobgp.service \
  -p LoadState -p ActiveState -p SubState -p MainPID -p ControlPID
pgrep -a -x gobgpd
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini transition status
```

Для подтверждённой остановки нужны loaded/inactive/dead, PID=0/0, отсутствие
canonical gobgpd в полном host /proc и отказ всех локальных gRPC TCP endpoints.
Приложение выполняет read-only probe само. Один timeout/refused gRPC не доказывает
пустую RIB. Скрытый /proc, missing/failed/restarting unit, permission error либо
неопределённый gRPC означают **unknown** и блокируют переход; ошибки отзыва не
считаются успехом. Флага ручного обхода нет.

При доказанно остановленном GoBGP замена БД может продолжиться с
cleanup_required=true. После восстановления gRPC сначала выполняется drain и
empty-RIB verification, **затем** применение новых данных slave. Durable fence
переживает restart и проверяется и reconciliation, и AddPath. Snapshot может
приходить, но не снимает fence. Нельзя удалять marker вручную.

При обычном announcements=no route writes/withdrawals отсутствуют. Demotion —
отдельное явное действие оператора и исключение: dedicated drain выполняется и
при announcements=no. `routes withdraw-owned --execute` остаётся отдельным
способом отзыва только owned paths. Полный offline rollback demotion backup и
reset-after-restore: [ROLE_TRANSITIONS.md](ROLE_TRANSITIONS.md), без ручного SQL.
