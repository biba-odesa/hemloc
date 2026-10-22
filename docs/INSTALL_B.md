# Установка slave Hemlock на чистую Debian 13

Самостоятельная инструкция для канонической поставки **0.4.0+**. Все IP/ASN/имена
ниже — заполнители/документационные примеры. Существующий master должен поддерживать тот же явный протокол репликации
(в 0.4.1 — версия 3); версии приложений могут различаться. Старый peer без
handshake несовместим. См. [REPLICATION_PROTOCOL.md](REPLICATION_PROTOCOL.md).
Не меняйте рабочую роль master ради установки slave.

Все команды — **root на новом slave**, кроме помеченных «master»/«рабочая станция».
Сеть/SSH/firewall не меняются автоматически. Результат: приложение и отдельный
GoBGP готовы, реальные соседи выключены, `announcements=no`.

## Новая B вместо прежней B

Для существующей пары используйте [PAIR_UPGRADE_040.md](PAIR_UPGRADE_040.md).
Новая B получает только адаптированный локальный INI, собственные TLS-файлы/CA
и общий secret. Старые БД/cache/cursor/sessions/venv не переносить; все пути
канонические. Users/rules/audit придут с A через snapshot/journal.
Раздел 5 описывает локальную инициализацию protection без переноса cache файла.
На A сохраняются его БД и накопленный protection; GoBGP A не перезапускается.

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
RELEASE='<PUBLISHED_0.4_OR_LATER_TAG_OR_FULL_40_HEX_COMMIT>'
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

Нужен GoBGP **4.10.0+hemlock-ibgp-ttl1**, API v4.10.0 и приложенный TTL patch.
Соберите дважды по [BUILD.md](BUILD.md) либо безопасно перенесите проверенный
бинарник без конфигов/секретов. При переносе получите checksum независимым каналом.
Нельзя устанавливать stock другую major-версию или класть готовый binary в Git.
Сохраните provenance, Apache-2.0 и notices модулей.

```bash
GOBGP_BINARY=/root/gobgpd-verified
GOBGP_SHA='<INDEPENDENTLY_VERIFIED_SHA256>'
printf '%s  %s\n' "$GOBGP_SHA" "$GOBGP_BINARY" | sha256sum -c -
"$GOBGP_BINARY" --version
bash deploy/install-debian13.sh \
  --role slave --version "$COMMIT" --expected-commit "$COMMIT" \
  --node-id block-b --peer-node-id block-a --owner 64512,100,2 \
  --gobgp-binary "$GOBGP_BINARY" --gobgp-sha256 "$GOBGP_SHA" --check
```

Node IDs и owner замените согласованными значениями; owner slave уникален и
сохраняется при смене роли. Повторите без `--check` (при необходимости добавьте
`--proxy http://PROXY_HOST:PORT`). Получатся `/opt/hemlock/.venv`, root-owned код,
`/etc/hemlock` root:hemlock 0750, `/var/lib/hemlock` hemlock:hemlock 0700,
`hemlock.service` и `gobgp.service`. Ни сервис, ни БД/администратор не запускаются/
создаются. Existing install/пользователи/конфиги не перезаписываются.

## 3. TLS: ключ slave остаётся на slave, подпись — на master

В этой двухузловой процедуре CA key хранится **на master**. Никогда не переносите
его на slave. Доверие к существующему CA подтвердите fingerprint по независимому
каналу. На slave:

```bash
umask 077
SLAVE_IP=192.0.2.20
install -d -m 0700 /root/hemlock-transfer
openssl req -new -newkey rsa:3072 -nodes \
  -keyout /etc/hemlock/tls/server.key \
  -out /root/hemlock-transfer/slave.csr -subj '/CN=block-b' \
  -addext "subjectAltName=IP:$SLAVE_IP"
test -s /root/hemlock-transfer/slave.csr
openssl req -in /root/hemlock-transfer/slave.csr -noout -verify
chown root:hemlock /etc/hemlock/tls/server.key
chmod 0640 /etc/hemlock/tls/server.key
```

Через существующий проверенный SSH/SFTP передайте только CSR на master.
Например, с **рабочей станции**, где значения SSH login@host уже согласованы:

```bash
umask 077
SLAVE_SSH='<EXISTING_LOGIN_AT_SLAVE>'
MASTER_SSH='<EXISTING_LOGIN_AT_MASTER>'
ssh -T "$SLAVE_SSH" 'sudo -n cat /root/hemlock-transfer/slave.csr' > slave.csr
test -s slave.csr
openssl req -in slave.csr -noout -verify
scp slave.csr "$MASTER_SSH:slave.csr.transfer"
```

**Master/root:** установите принятый файл в закрытый каталог; сначала проверьте
непустой файл и подпись CSR, **потом** подписывайте. Укажите фактический путь CA,
не создавайте новый CA для существующего master:

```bash
install -d -m 0700 /root/hemlock-transfer
install -m 0600 /home/OPERATOR/slave.csr.transfer /root/hemlock-transfer/slave.csr
test -s /root/hemlock-transfer/slave.csr
openssl req -in /root/hemlock-transfer/slave.csr -noout -verify
SLAVE_IP=192.0.2.20
CA_DIR=/root/hemlock-ca
printf 'subjectAltName=IP:%s\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' \
  "$SLAVE_IP" > /root/hemlock-transfer/slave.ext
openssl x509 -req -in /root/hemlock-transfer/slave.csr \
  -CA "$CA_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" -CAcreateserial \
  -days 365 -sha256 -extfile /root/hemlock-transfer/slave.ext \
  -out /root/hemlock-transfer/slave.crt
```

Верните slave.crt и **публичный** ca.crt на slave через проверенный канал,
установите `/etc/hemlock/tls/server.crt` и `ca.crt` root:hemlock 0640.
CA private key остаётся на master. На **slave**:

```bash
openssl verify -CAfile /etc/hemlock/tls/ca.crt /etc/hemlock/tls/server.crt
openssl x509 -in /etc/hemlock/tls/server.crt -noout -checkip "$SLAVE_IP"
openssl x509 -in /etc/hemlock/tls/server.crt -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum
openssl pkey -in /etc/hemlock/tls/server.key -pubout -outform DER | sha256sum
```

Последние digest одинаковы. SAN должен соответствовать адресу в peer_url.
Доверие проверяется всегда, без `-k`/verify=False. Срок сертификата контролируйте,
продлевайте на CA до истечения с повторными CA/SAN/key проверками.

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
cert = /etc/hemlock/tls/server.crt
key = /etc/hemlock/tls/server.key
ca = /etc/hemlock/tls/ca.crt
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

На **master** заполните peer_url slave, peer_node_id, доверенный CA и тот же token;
проверьте права INI и перезапустите только приложение для перечитывания. Не меняйте
master role/node ID/owner. На **slave**, после полной проверки конфигов/TLS/cache:

```bash
systemctl enable --now gobgp.service hemlock.service
systemctl is-active gobgp.service hemlock.service
journalctl -u hemlock.service -n 40 --no-pager
curl --noproxy '*' --cacert /etc/hemlock/tls/ca.crt \
  "https://$SLAVE_IP:8443/api/session"
```

Ожидается `{"authenticated":false}`. Войдите прежней учётной записью master после
синхронизации. В вебе проверьте одинаковые generation/cursor, отставание 0, правила,
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

TLS error: проверяйте время, CA, SAN/URL и совпадение ключа. Auth error: одинаковый
secret, peer_node_id и версии обоих узлов. IRR error: TCP/43/sources/timeout,
включая доступ от сервисного пользователя; HTTP proxy тут не поможет. Permission
error: root:hemlock 0640 INI/keys и hemlock:hemlock 0600 SQLite. BGP Active либо
admin-prohibited не означает Established: проверьте реальные ACL/TTL/passive/
адреса и admin-down. Не исправляйте диагноз отключением TLS/protection.
