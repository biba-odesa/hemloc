# Установка slave Hemlock на чистую Debian 13

Самостоятельная инструкция для канонической поставки **0.5.0+**. Все IP/ASN/имена
ниже — заполнители/документационные примеры. Существующий master должен поддерживать тот же явный протокол репликации
(в 0.5.0 — версия 3); версии приложений могут различаться. Старый peer без
handshake несовместим. См. [REPLICATION_PROTOCOL.md](REPLICATION_PROTOCOL.md).
Не меняйте рабочую роль master ради установки slave.

Все команды — **root на новом slave**, кроме помеченных «master»/«рабочая станция».
Сеть/SSH/firewall не меняются автоматически. Результат: приложение и отдельный
GoBGP готовы, реальные соседи выключены, `announcements=no`.

## Новая B вместо прежней B

Для обычного обновления B не переустанавливается: см. [LIFECYCLE.md](LIFECYCLE.md).
Если оператор отдельно выбрал чистую переустановку, сохранить старую установку
для отката; перенести только адаптированные локальные настройки и общий secret.
Новая pinned-пара B создаётся самим B; старые TLS/CA-файлы остаются в backup,
а не подменяют новую identity. БД/cache/cursor/sessions/venv не переносить.
Users/rules/audit придут с A после взаимного approval и snapshot/journal.
Раздел 5 описывает локальную инициализацию protection без копии master DB.
На A его БД/protection и GoBGP сохраняются. Исторический сценарий старой
поставки описан в PAIR_UPGRADE_040.md и не меняет новые TLS defaults.

## 1. Проверки и исходник

```bash
cat /etc/os-release
timedatectl status
hostname -f
ip -br address
getent hosts github.com deb.debian.org pypi.org whois.radb.net
```

Требуются Debian 13, правильное время/DNS, HTTPS к GitHub/PyPI и master,
apt mirrors, **прямой TCP/43 к IRR**. HTTP/HTTPS proxy не действует на bgpq4.
Slave получает blocked ASN-наборы от master, но protection обновляет локально;
ошибка сохраняет накопленный cache. После promotion IRR нужен и blocked ASN.
Входящий HTTPS — операторский порт (пример 8443); gRPC 50051 только loopback.
BGP TCP/179 к роутерам открывается/используется отдельно оператором.

Для системных загрузок при необходимости:

```bash
export http_proxy='http://PROXY_HOST:PORT'
export https_proxy="$http_proxy"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
```

Не помещайте credentials в argv. Без proxy уберите proxy env, включая ALL_PROXY.
Настройка proxy в INI не распространяется на apt/Git/pip. Установщик использует
только явный `--proxy`; без него downloads прямые.

```bash
apt-get update
apt-get install -y --no-install-recommends git ca-certificates nano
RELEASE='<PUBLISHED_0.5_OR_LATER_TAG_OR_FULL_40_HEX_COMMIT>'
git clone https://github.com/biba-odesa/hemlock.git /root/hemlock-source
cd /root/hemlock-source
git fetch origin "$RELEASE"
COMMIT=$(git rev-parse --verify 'FETCH_HEAD^{commit}')
git checkout --detach "$COMMIT"
printf 'Selected commit: %s\n' "$COMMIT"
```

Сверьте commit с публикацией. Не используйте moving main для первой установки и
не выбирайте старый v0.3.0: canonical installer появился после него. До выпуска
нового тега выбирайте полный опубликованный SHA, содержащий установщик.

## 2. Проверенный GoBGP и установка без старта

GoBGP **4.10.0+hemlock-ibgp-ttl1** собирается установщиком автоматически:
фиксированные Go 1.25.14 linux-amd64 и GoBGP source скачиваются по HTTPS,
SHA256 обоих архивов проверяется до распаковки, затем применяется TTL patch.
Готовый бинарник с A переносить не требуется. Stock/latest не подставляется.
Нужны Linux amd64, не менее 4 GiB свободно в /var/tmp и 1 GiB в /opt;
рекомендуется 2 GiB RAM. Сборка использует две jobs, Go modules загружаются
через proxy.golang.org с проверкой sum.golang.org. HTTP proxy задаётся явно
через `--proxy`; системный Go не используется. Подробнее: [BUILD.md](BUILD.md).

```bash
bash deploy/install-debian13.sh \
  --role slave --version "$COMMIT" --expected-commit "$COMMIT" \
  --node-id block-b --peer-node-id block-a --owner 64512,100,2 --check
```

`--check` ничего не скачивает и не компилирует. Для самой установки повторите
без `--check`. Отчёт сборки: `/usr/local/share/hemlock/gobgp-build.json`;
лицензия GoBGP: `/usr/local/share/LICENSE.GoBGP`. Ошибка сборки останавливает
установку до создания service users/configs. Временные build-файлы удаляются.
Дополнительный вариант — явно передать оба `--gobgp-binary` и `--gobgp-sha256`
для независимо проверенного готового бинарника; по умолчанию они не нужны.

Node IDs и owner замените согласованными значениями; owner slave уникален и
сохраняется при смене роли. Повторите без `--check` (при необходимости добавьте
`--proxy http://PROXY_HOST:PORT`). Получатся `/opt/hemlock/.venv`, root-owned код,
`/etc/hemlock` root:hemlock 0750, `/var/lib/hemlock` hemlock:hemlock 0700,
`hemlock.service` и `gobgp.service`. Ни сервис, ни БД/администратор не запускаются/
создаются. Existing install/пользователи/конфиги не перезаписываются.

## 3. Собственная TLS-пара B, без CA

Установщик создал `/var/lib/hemlock/tls` hemlock:hemlock 0700. В конфиге
оставьте mode=pinned, cert/key под отдельным identity directory. При первом
старте Hemlock создаст оба файла атомарно, 0600. На B не переносить CA private
key, ключ/сертификат master или старую production-пару ради новой установки.
CA/CSR/подписание на A для pinned mode не нужны. Укажите management IP/DNS B
в tls.names для правильного SAN браузера; wildcard web host требует names.

Если существует только один файл, неверны права или пара повреждена/не совпадает,
Hemlock сообщает ошибку, не удаляет её молча. По истечении срока HTTPS
контролируемо перезапускается с новой парой; GoBGP продолжает работу, на A
понадобится отдельное approval нового B-ключа. Предупреждение за warn_days
однократное. Подробнее и переход существующей CA-пары: [TLS_TRUST.md](TLS_TRUST.md).

## 4. Секрет и INI

На **master** используйте существующий replication secret, не генерируйте другой
для пары. На рабочей станции можно перенести его без вывода/argv/history:

```bash
ssh -T "$MASTER_SSH" 'sudo -n cat /etc/hemlock/replication.token' | \
  ssh -T "$SLAVE_SSH" 'sudo -n sh -c "umask 077; set -C; cat > /etc/hemlock/replication.token"'
```

Команда требует уже разрешённого sudo/проверенных host keys, не меняет SSH.
На slave проверьте только права/длину без печати содержимого; root:hemlock 0640.
Если файл существует, команда откажет, не перезаписывайте его молча.

```bash
chown root:hemlock /etc/hemlock/replication.token
chmod 0640 /etc/hemlock/replication.token
nano /etc/hemlock/hemlock.ini
```

В полном шаблоне измените поля, сохранив остальные секции:

```ini
[node]
node_id = block-b
role = slave
database = /var/lib/hemlock/hemlock.sqlite
peer_node_id = block-a
peer_url = https://192.0.2.10:8443
token_file = /etc/hemlock/replication.token
poll_seconds = 3
[web]
host = 192.0.2.20
port = 8443
tls = yes
cert = /var/lib/hemlock/tls/identity/server.crt
key = /var/lib/hemlock/tls/identity/server.key
ca =

[tls]
mode = pinned
state_dir = /var/lib/hemlock/tls
names = 192.0.2.20
days = 365
warn_days = 30
[gobgp]
announcements = no
grpc_target = 127.0.0.1:50051
gobgp_service_unit = gobgp.service
owner = 64512,100,2
```

Согласуйте protected ASN, явные сети, **накопленный cache**, IRR sources/server,
next-hop/communities/local preference с master. IPv6 next-hop не угадывать.
Owner узлов должен отличаться. Proxy приложения настраивается отдельно в [proxy].
Retention/notifications оставьте выключенными до отдельного решения.

```bash
chown root:hemlock /etc/hemlock/hemlock.ini
chmod 0640 /etc/hemlock/hemlock.ini
stat -c '%U:%G %a %n' /etc/hemlock/hemlock.ini
runuser -u hemlock -- test -r /etc/hemlock/hemlock.ini
runuser -u hemlock -- /opt/hemlock/.venv/bin/python -c \
  'from hemlock.config import load; load("/etc/hemlock/hemlock.ini"); print("Config OK")'
```

Редактор мог поменять права — повторять проверку после каждой правки.

## 5. Пустая БД и локальная инициализация protection

На slave, пока сервис остановлен:

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini init-db
chown -R hemlock:hemlock /var/lib/hemlock
```

**Не создавайте администратора.** Правила, пользователи/хеши и общий аудит придут
через snapshot/journal. Сессии, конфиг и protection не реплицируются.

### Выбранная переустановка B: без переноса cache

Не экспортируйте/импортируйте protection.json для этого сценария. Согласуйте
локальный INI B: protected ASN/явные сети и исторические protected сети A,
которые должны сохраниться на B (последние внести как protected_prefixes).
После старта B его protection worker должен самостоятельно успешно раскрыть
каждый configured protected ASN. IRR требует прямой TCP/43. Старый cache B и
БД B не копируются. Snapshot не переносит protection. До проверки эффективной
защиты announcements=no; успешная репликация сама по себе не доказывает защиту.

Свежий IRR-ответ не воспроизводит автоматически накопленный protection A. Если
состав исторических сетей ещё не согласован в INI B, это блокер B-анонсов,
а не повод очистить cache A или объявить bootstrap завершённым.

## 6. GoBGP без рабочих соседей и первый запуск

Выберите собственные ASN/router-id; не копируйте документационные значения:

```bash
LOCAL_ASN='<YOUR_ASN>'
ROUTER_ID='<YOUR_IPV4_ROUTER_ID>'
printf '[global.config]\nas = %s\nrouter-id = "%s"\nport = -1\n' \
  "$LOCAL_ASN" "$ROUTER_ID" > /etc/gobgp/gobgpd.toml
chown root:gobgp /etc/gobgp/gobgpd.toml
chmod 0640 /etc/gobgp/gobgpd.toml
runuser -u gobgp -- /usr/local/bin/gobgpd --dry-run --pprof-disable \
  --api-hosts=127.0.0.1:50051 -f /etc/gobgp/gobgpd.toml
```

На **master** заполните peer_url slave, peer_node_id и тот же token;
проверьте права INI и перезапустите только приложение для перечитывания. Не меняйте
master role/node ID/owner. На **slave**, после проверки конфигов/SAN/protection:

```bash
systemctl enable --now gobgp.service hemlock.service
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls self
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls peer
systemctl is-active gobgp.service hemlock.service
journalctl -u hemlock.service -n 40 --no-pager
curl --noproxy '*' --cacert /var/lib/hemlock/tls/identity/server.crt \
  "https://<YOUR_SLAVE_IP>:8443/api/session"
```

Ожидается `{"authenticated":false}`. Теперь выполните взаимное approval по разделу 9
ниже. До этого синхронизации и пользователей на пустом B нет. После approval и
синхронизации войдите прежней учётной записью master. В вебе проверьте одинаковые generation/cursor, отставание 0, правила,
пользователей, аудит и protection обоих узлов. На slave редактирование отключено,
включая прямой API. На master сосед должен быть свежим In sync, а не stale.
Проверьте запрет startup-редактирования без тестовых мутаций в рабочем аудите.

## 7. Реальные BGP-соседи — отдельное решение оператора

На роутерах сначала создают peer slave с import/export DENY-ANY, не меняя политики
группы и существующих peers. Для согласованной Junos-группы пример:

```text
set protocols bgp group <GROUP> neighbor <SLAVE_IP> peer-as <LOCAL_ASN>
set protocols bgp group <GROUP> neighbor <SLAVE_IP> passive
set protocols bgp group <GROUP> neighbor <SLAVE_IP> import DENY-ANY
set protocols bgp group <GROUP> neighbor <SLAVE_IP> export DENY-ANY
show | compare
commit confirmed 5
```

Проверьте diff и подтвердите commit после диагностики; не подставляйте рабочие
значения из догадок. На GoBGP подготовьте managed template с операторскими
адресами, import reject и export только owned local paths (`tools.export_policy`).
Все новые соседи первоначально admin-down; включайте по одному отдельным действием.
Изменение GoBGP config/peer state требует отдельного согласования.

`announcements=yes` на slave при router import DENY-ANY — допустимый выбранный
оператором этап проверки local RIB/атрибутов/Adj-RIB-Out, не автоматический финал.
Настройка не переключается установщиком. Неизвестный IPv6 next-hop оставляют пустым.
Приём/установка удалённым роутером не подтверждаются локальным экспортом.

## 8. Обслуживание

После reboot проверьте active обоих сервисов, валидный HTTPS, protection, fresh
replication/отставание 0, локальные маршруты и disabled peers. Новая версия видна
над Sign out. Обновление/rollback/failover: [LIFECYCLE.md](LIFECYCLE.md).
Проверять обрыв связи с master следует только в изолированном стенде; рабочий
master не останавливать. Для штатного теста репликации оператор может изменить
комментарий отдельного тестового правила на master, проверить slave и вернуть
прежний комментарий — это реальные audit events, не скрывать их.

TLS error: проверяйте время, SPKI approval на обоих узлах, SAN веба, режим и пару ключа. CA проверяется только в legacy_ca. Auth error: одинаковый
secret, peer_node_id и версии обоих узлов. IRR error: TCP/43/sources/timeout,
включая доступ от сервисного пользователя; HTTP proxy тут не поможет. Permission
error: root:hemlock 0640 INI/keys и hemlock:hemlock 0600 SQLite. BGP Active либо
admin-prohibited не означает Established: проверьте реальные ACL/TTL/passive/
адреса и admin-down. Не исправляйте диагноз отключением TLS/protection.


## 9. Взаимное approval после запуска, до первого входа B

На root-консоли B сохраните вывод tls self. На root-консоли A выполните tls peer
и сравните candidate fingerprint с выводом B по независимому доверенному каналу.
Аналогично сравните candidate на B с tls self на A. На каждом узле:

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls approve \
  --fingerprint 'SHA256:<VERIFIED_OTHER_NODE_SPKI>'
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls trust
```

Если candidate сменился, обновить tls peer и снова сверить, не подтверждать
вслепую. Root CLI нужен именно потому, что пустой slave ещё без пользователей.
После обоих approval дождитесь автоматического snapshot/journal и свежего
In sync/нулевого отставания. Только затем входите на B существующим пользователем.
Admin может управлять локальным доверием и на slave с CSRF; guest не может.
Отзыв: tls revoke --fingerprint 'SHA256:<CURRENT_APPROVED_SPKI>'. Trust/identity
не входят в SQLite snapshot и не теряются при смене роли/reinitialize.
Обычные обновления B → A не требуют переустановки slave; старую CA-пару обновляют
в legacy_ca, затем оба явно переводят в pinned, без автоматического downgrade.
