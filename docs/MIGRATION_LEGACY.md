# Явная миграция существующей установки hemloc → hemlock

**Единственное место, где старые имена являются действующими примерами.**
Это инструкция оператору, не выполняемый установщиком скрытый upgrade.
Не запускать новый installer/update.sh поверх старой установки. Не делать
`mv .venv`: shebang и activation-файлы сохраняют прежний абсолютный путь.
0.4.0 убирает CLI/Python aliases, меняет cookie на `hemlock_session`, peer header
с `X-Hemloc-Node` на `X-Hemlock-Node` и browser theme key. Пара 0.3.x/0.4.0 не синхронизируется.
Нужен согласованный переход обоих узлов; автоматического failover нет.

## Выбранный сценарий пары A/B

[PAIR_UPGRADE_040.md](PAIR_UPGRADE_040.md) задаёт порядок: данные существующего
master A сохраняются, B устанавливается заново installer-скриптом на чистую ОС.
На новый B переносятся только адаптированный INI, его TLS/CA и replication secret.
Старая БД/cache/cursor/сессии B не восстанавливаются. В новой установке B нет
старых путей. Правила/пользователи/аудит B приходят от A по snapshot/journal.
Protection B инициализируется отдельно; исторические сети A при необходимости
согласуются в protected_prefixes нового INI, без переноса отдельного cache файла.

**Ниже — только A-only миграция существующей установки с сохранением её БД.**
Не применяйте восстановление backup из раздела 3 к новому B. Старый B выводится
по порядку из PAIR_UPGRADE_040.md; его переустановка не останавливает GoBGP A.

## 1. Инвентаризация без предположения пути INI

На **существующем A/root**:

```bash
systemctl show hemloc.service --no-pager \
  -p ExecStart -p WorkingDirectory -p User -p Group -p FragmentPath -p DropInPaths
systemctl cat hemloc.service
```

Если сервис уже называется иначе — используйте его реальное имя. Из ExecStart
возьмите **фактические** пути Python/CLI и аргумент `--config`. Не предполагайте
`/etc/hemloc/hemloc.ini`: он мог быть изменён. Запишите без публикации секретов:

```bash
OLD_UNIT=hemloc.service
OLD_PYTHON='<ACTUAL_VENV>/bin/python'
OLD_CONFIG='<ACTUAL_CONFIG_FROM_EXECSTART>'
OLD_DATABASE='<DATABASE_RESOLVED_FROM_ACTUAL_CONFIG>'
```

Проверьте локально role, node ID, peer identity/URL, owner, реальную БД, protection
config/cache, TLS/CA/token paths, proxy, IRR/route attributes, notifications и
retention. Не выводите INI целиком в тикет/чат. Сохраните units/drop-ins, включая
CAP_NET_BIND_SERVICE для 443 и ограничения notification handler. Не меняйте
GoBGP unit, config, binary, peers, policy или его ownership namespace.

На старой совместимой паре дождитесь fresh sync/zero lag и подтверждения security
outbox B. Выведите старое приложение B, затем на A остановите **только приложение**
для окончательного backup и переноса. Во время миграции не менять правила/пользователей;
GoBGP продолжает ранее созданные маршруты. Сетевая изоляция при настоящем failover
— отдельное действие; миграция имён не меняет роль.

```bash
systemctl stop "$OLD_UNIT"
"$OLD_PYTHON" -I -m hemloc --config "$OLD_CONFIG" backup \
  '<PRIVATE_NEW_BACKUP_PATH>.sqlite'
```

Если текущий пакет уже canonical-import, используйте `-m hemlock`. Backup CLI
требует root, сам сбрасывает UID до владельца БД. Destination должен быть доступен
ему на запись (например, реальный data directory), режим backup 0600.
Сохраните separately старый wheel/requirements, config/TLS/secret/handler/unit,
DB backup и checksums в закрытом месте; не в Git.

Проверьте `transition status` старой версии. Если demotion marker незавершён,
**не мигрируйте пути**: закончите/восстановите transition по старым путям и
ROLE_TRANSITIONS.md. Terminal marker сохраните с private backup для истории;
не переносите marker со старым embedded database path как активный marker нового
пути. Не удаляйте незавершённый fence, чтобы «починить» запуск.

## 2. Новый код/venv/пользователь, без installer

Для A выберите тот же проверенный полный commit 0.4.0+, что выбран для новой B.
Git должен быть установлен до clone. Если `/opt/hemlock` уже существует, не
клонируйте поверх него и не перезаписывайте: сохраните отдельно root-owned
source/venv после остановки приложения и проверьте реальные ExecStart paths.

```bash
RELEASE='<PUBLISHED_0.4_OR_LATER_TAG_OR_FULL_COMMIT>'
git clone https://github.com/biba-odesa/hemlock.git /opt/hemlock
git -C /opt/hemlock fetch origin "$RELEASE"
COMMIT=$(git -C /opt/hemlock rev-parse --verify 'FETCH_HEAD^{commit}')
git -C /opt/hemlock checkout --detach "$COMMIT"
python3.13 -m venv /opt/hemlock/.venv
/opt/hemlock/.venv/bin/python -m pip install --require-hashes -r /opt/hemlock/requirements-build.lock
/opt/hemlock/.venv/bin/python -m pip install --require-hashes -r /opt/hemlock/requirements.lock
/opt/hemlock/.venv/bin/python -m pip install --no-deps --no-build-isolation /opt/hemlock
/opt/hemlock/.venv/bin/python -m pip check
useradd --system --user-group --home-dir /var/lib/hemlock --no-create-home --shell /usr/sbin/nologin hemlock
install -d -o root -g hemlock -m 0750 /etc/hemlock
install -d -o hemlock -g hemlock -m 0700 /var/lib/hemlock
chown -R root:root /opt/hemlock
chmod -R a+rX /opt/hemlock
chmod -R go-w /opt/hemlock
```

Если canonical user/group уже существуют, сначала проверьте UID/GID и назначение,
не повторяйте useradd и не меняйте чужую учётную запись. Старую hemloc пока не
удаляйте — она нужна для rollback и может владеть другими приватными файлами.

## 3. Данные, защита и конфиг

На A восстанавливайте **его собственный локальный закрытый SQLite backup**.
Новая B этот раздел не выполняет: у неё пустая init-db и штатная репликация. Он содержит правила, пользователей, аудит, credential versions,
local protection cache и расписание. На A не выполняйте повторный init-db
и не создавайте заново администратора.

```bash
install -o hemlock -g hemlock -m 0600 '<PRIVATE_NEW_BACKUP_PATH>.sqlite' \
  /var/lib/hemlock/hemlock.sqlite
install -o root -g hemlock -m 0640 "$OLD_CONFIG" /etc/hemlock/hemlock.ini
editor /etc/hemlock/hemlock.ini
```

Меняйте только локальные пути и имя сервиса приложения. `database` задайте
абсолютно `/var/lib/hemlock/hemlock.sqlite`. Сохраните **точные** role/node_id/
peer_node_id/owner/peer_url/poll/IRR/protection/route/proxy/retention/notification
значения. TLS cert/key/CA и token **не перевыпускайте**: перенесите закрытыми
файлами в `/etc/hemlock`, обновите только соответствующие пути. Относительные
пути в старом INI сначала разрешите относительно старого config directory,
иначе при переносе изменится их значение. Для notification credentials согласуйте
чтение новой группой hemlock, не делайте world-readable и не ослабляйте sandbox.

Проверьте SQLite integrity и совпадение node ID/role/generation/cursor/числа правил,
пользователей и protection cache с backup read-only средствами. Не изменяйте SQL
вручную. WAL/SHM старой БД в новое место **не переносить**; нужен закрытый backup.
Рабочую старую БД оставьте нетронутой для отката.

```bash
chown root:hemlock /etc/hemlock/hemlock.ini
chmod 0640 /etc/hemlock/hemlock.ini
runuser -u hemlock -- test -r /etc/hemlock/hemlock.ini
runuser -u hemlock -- /opt/hemlock/.venv/bin/python -c \
  'from hemlock.config import load; load("/etc/hemlock/hemlock.ini"); print("Config OK")'
install -o root -g root -m 0644 /opt/hemlock/deploy/hemlock.service /etc/systemd/system/hemlock.service
```

Перенесите **reviewed** необходимые drop-ins старого сервиса в новый, адаптируя
пути/user/group (включая optional bind capability). Не копируйте старый ExecStart
или WorkingDirectory поверх нового. **Не меняйте** gobgp.service/его UID/конфиг.
Старый application unit должен быть stopped/disabled до enable нового:

```bash
systemctl disable "$OLD_UNIT"
systemctl daemon-reload
systemctl show hemlock.service --no-pager -p User -p Group -p ExecStart -p WorkingDirectory
```

## 4. Согласованный старт и проверка

После переноса A запустите его canonical master (новая B запускается отдельно
по INSTALL_B.md после подготовки TLS/config и пустой БД):

```bash
systemctl enable --now hemlock.service
systemctl is-active hemlock.service
journalctl -u hemlock.service -n 40 --no-pager
```

GoBGP не перезапускается. Старый hemloc.service не должен снова запускаться.
Войдите заново: изменён cookie, прежние сессии в браузере не используются.
Проверьте HTTPS CA/SAN, фактическую версию 0.4.0+, прежние node ID/owner/роли,
одинаковый generation/cursor, zero lag и complete local RIB/export/protection.
Смена имён не должна создавать новое поколение или startup demotion.

Временная ошибка репликации до обновления второго узла ожидаема, но не означает
успешной синхронизации. Не удаляйте cache/данные и не меняйте роли для её устранения.
Когда всё проверено, обычные обновления выполняет canonical update.sh.

## 5. Откат миграции A и согласованность пары

Остановите новые приложения на обоих узлах; выберите согласованную старую версию
обоих peer endpoints. Сохраните новые БД/конфиги приватно, не затирайте их.
Верните прежний unit/drop-ins, старые **неизменённые** данные/venv/config и их UID/
права, отключите новый hemlock.service, запустите старые приложения согласованно.
GoBGP не перезапускайте. Если после миграции были новые изменения, старый backup
их не содержит: оператор выбирает authoritative history, автоматического merge
нет. Нельзя незаметно откатить только одну сторону и считать пару совместимой.

В выбранном сценарии B является новой установкой: не восстанавливайте на неё
старую БД B. Возврат всей пары на предыдущие endpoints требует отдельного
согласованного возврата старого B из сохранённого offline окружения либо другого
проверенного bootstrap, а не импорта старой ветки поверх нового slave.
