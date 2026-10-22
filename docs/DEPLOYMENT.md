# Установка master Hemlock на чистую Debian 13

Документ относится к канонической поставке **0.4.0 и новее**. Стандарт:
`/opt/hemlock` (код и venv), `/etc/hemlock`, `/var/lib/hemlock`, пользователь и
группа `hemlock`, `hemlock.service`, CLI/Python package `hemlock`.
GoBGP — отдельные `gobgp.service`, пользователь `gobgp`, локальный gRPC.
Существующие установки сначала проходят [явную миграцию](MIGRATION_LEGACY.md).
Установщик ничего не мигрирует и отказывается при существующих каталогах,
пользователях или unit. SSH, firewall и сеть автоматически не меняются.

Все команды ниже — **root на новом master**, кроме явно помеченного переноса.
Примеры IP/ASN документационные; перед применением задайте собственные значения.

## 1. Система и доступы

```bash
cat /etc/os-release
timedatectl status
hostname -f
ip -br address
getent hosts github.com deb.debian.org pypi.org whois.radb.net
```

Ожидается Debian 13, корректное время/часовой пояс и DNS. Исправления системной
сети/SSH/firewall выполняет оператор отдельно. Нужны исходящие HTTPS к GitHub/
codeload, PyPI/files.pythonhosted.org, go.dev, proxy.golang.org/sum.golang.org для
сборки; apt к выбранным Debian mirrors; **прямой TCP/43 к IRR**; доступ к
документированным в VERSIONS.md metadata HTTP API. Между узлами — HTTPS к веб-порту
(по умолчанию 8443). gRPC 50051 только loopback. BGP TCP/179 разрешается отдельно
к согласованным маршрутизаторам; вебу не нужны SSH или права управления systemd.

При необходимости явно задайте proxy для apt/Git/pip/downloads. Это не настройка
proxy приложения. Не вставляйте credentials в argv или этот документ:

```bash
export http_proxy='http://PROXY_HOST:PORT'
export https_proxy="$http_proxy"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
```

Без proxy удалите эти переменные и `ALL_PROXY/all_proxy`. Установщик имеет
собственный `--proxy http://HOST:PORT`; без него downloads выполняются напрямую.
HTTP proxy **не переносит bgpq4 TCP/43**. Master использует IRR для blocked ASN и
protection; slave тоже самостоятельно обновляет protection и сохраняет cache при
ошибке. После повышения slave до master TCP/43 нужен и для blocked ASN.

## 2. Git, фиксированный исходник, проверенный GoBGP

Git устанавливается **до** первого clone:

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

Сверьте COMMIT с публикацией по независимому каналу. Пока тег 0.4.0 не выпущен,
используйте опубликованный **полный commit**, содержащий установщик. Старый
v0.3.0 не содержит канонической поставки; существующие теги не перемещаются.

Установщик сам скачивает GoBGP **4.10.0** и Go **1.25.14 linux-amd64**,
проверяет фиксированные SHA256 архивов до распаковки, применяет TTL patch и
собирает **4.10.0+hemlock-ibgp-ttl1**. Установленный системный Go не используется.
Нужны Linux amd64, минимум 4 GiB свободного места в /var/tmp и 1 GiB в /opt;
рекомендуется не менее 2 GiB RAM. Сборка ограничена двумя параллельными jobs.
Сетевой доступ нужен также к proxy.golang.org и sum.golang.org. Версии не
выбираются по latest; их обновляют после отдельного тестирования релиза.

GoBGP не запускается во время сборки, кроме безопасного `--version`.
Ошибка скачивания/checksum/патча/компиляции останавливает установку, без
fallback на stock binary. Отчёт с SHA256 исходника, SDK, patch и бинарника:
`/usr/local/share/hemlock/gobgp-build.json`; лицензия Apache-2.0:
`/usr/local/share/LICENSE.GoBGP`. Временные SDK/cache удаляются после сборки.
Готовый бинарник не добавляется в Git. Независимые воспроизводимые сборки и
правила сохранения notices описаны в [BUILD.md](BUILD.md).

Дополнительный вариант: передать заранее проверенный бинарник через
`--gobgp-binary /ABS/PATH --gobgp-sha256 VERIFIED_SHA256`. Оба параметра
обязательны вместе; происхождение checksum оператор проверяет отдельно.
Для обычной установки эти параметры **не нужны**.

## 3. Установщик (без запуска)

Выберите собственные node IDs и уникальный ownership marker, согласованный с
маршрутными политиками. Ни ASN, ни next-hop, ни соседи установщиком не угадываются.
Ниже marker — документационный пример, замените на свой:

```bash
bash deploy/install-debian13.sh \
  --role master --version "$COMMIT" --expected-commit "$COMMIT" \
  --node-id block-a --peer-node-id block-b --owner 64512,100,1 --check
```

После успешного preflight повторите без `--check`. Для proxy добавьте
`--proxy http://PROXY_HOST:PORT`. Установщик ставит Git/Python venv/bgpq4 и
зависимости по hash-lock, фиксированный исходник, собирает TTL-patched GoBGP и ставит units;
не создаёт секреты/БД/администратора, не включает и не запускает сервисы.
Код/venv root-owned и недоступны сервисному пользователю на запись.
При ошибке останется частичная установка: не стирайте её вслепую для повторения.

## 4. TLS: собственный CA и IP SAN

CA private key остаётся только на master либо выбранной офлайн CA-машине.
Для этой инструкции подпись обоих сертификатов выполняется на master.
Если CA уже существует, используйте его, не создавайте другой с тем же именем.

```bash
umask 077
install -d -m 0700 /root/hemlock-ca
openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
  -keyout /root/hemlock-ca/ca.key -out /root/hemlock-ca/ca.crt \
  -subj '/CN=Hemlock private CA' \
  -addext 'basicConstraints=critical,CA:TRUE' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign'
NODE_IP=192.0.2.10
openssl req -new -newkey rsa:3072 -nodes \
  -keyout /etc/hemlock/tls/server.key -out /root/hemlock-ca/master.csr \
  -subj '/CN=block-a' -addext "subjectAltName=IP:$NODE_IP"
test -s /root/hemlock-ca/master.csr
openssl req -in /root/hemlock-ca/master.csr -noout -verify
printf 'subjectAltName=IP:%s\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' \
  "$NODE_IP" > /root/hemlock-ca/master.ext
openssl x509 -req -in /root/hemlock-ca/master.csr \
  -CA /root/hemlock-ca/ca.crt -CAkey /root/hemlock-ca/ca.key -CAcreateserial \
  -days 365 -sha256 -extfile /root/hemlock-ca/master.ext \
  -out /etc/hemlock/tls/server.crt
install -o root -g hemlock -m 0640 /root/hemlock-ca/ca.crt /etc/hemlock/tls/ca.crt
chown root:hemlock /etc/hemlock/tls/server.key /etc/hemlock/tls/server.crt
chmod 0640 /etc/hemlock/tls/server.key /etc/hemlock/tls/server.crt
openssl verify -CAfile /etc/hemlock/tls/ca.crt /etc/hemlock/tls/server.crt
openssl x509 -in /etc/hemlock/tls/server.crt -noout -checkip "$NODE_IP"
openssl x509 -in /etc/hemlock/tls/server.crt -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum
openssl pkey -in /etc/hemlock/tls/server.key -pubout -outform DER | sha256sum
```

Последние два digest должны совпасть; приватный ключ в терминал не выводится.
Для DNS-имён добавьте DNS SAN при подписи. Импортируйте **публичный** CA в доверие
рабочей станции/браузера после проверки fingerprint; `verify=False` и `curl -k`
не используются. Продление через год: новый CSR и сертификат с теми же SAN,
проверки CA/key/SAN и перезапуск только Hemlock; ключ CA не переносится на slave.

## 5. Секрет, INI и GoBGP

```bash
openssl rand -hex 32 > /etc/hemlock/replication.token
chown root:hemlock /etc/hemlock/replication.token
chmod 0640 /etc/hemlock/replication.token
nano /etc/hemlock/hemlock.ini
```

Заполните существующие поля шаблона:

```ini
[node]
node_id = block-a
role = master
database = /var/lib/hemlock/hemlock.sqlite
peer_node_id = block-b
# Empty until the slave is prepared; then use its verified HTTPS URL.
peer_url =
token_file = /etc/hemlock/replication.token

[web]
host = 192.0.2.10
port = 8443
tls = yes
cert = /etc/hemlock/tls/server.crt
key = /etc/hemlock/tls/server.key
ca = /etc/hemlock/tls/ca.crt

[gobgp]
announcements = no
grpc_target = 127.0.0.1:50051
gobgp_service_unit = gobgp.service
owner = 64512,100,1
```

Это фрагмент: сохраняйте остальные секции полного шаблона. Заполните protection
собственными ASN/сетями и согласованные IPv4/IPv6 next-hop/local preference/
communities. Если IPv6 next-hop неизвестен — оставьте пустым. Не берите значение
из первого адреса/догадки. Пустой protected ASN разрешает только намеренно
выбранную оператором конфигурацию, а не заменяет план защиты собственных сетей.
Retention и notifications оставьте выключенными до отдельного включения.

После редактора **всегда** проверьте права, он мог заменить файл:

```bash
chown root:hemlock /etc/hemlock/hemlock.ini
chmod 0640 /etc/hemlock/hemlock.ini
stat -c '%U:%G %a %n' /etc/hemlock/hemlock.ini
runuser -u hemlock -- test -r /etc/hemlock/hemlock.ini
runuser -u hemlock -- /opt/hemlock/.venv/bin/python -c \
  'from hemlock.config import load; load("/etc/hemlock/hemlock.ini"); print("Config OK")'
```

GoBGP сначала настраивается **без реальных соседей**. Укажите собственный ASN и
router-id, не копируйте документационные значения. Для подготовки можно создать
минимальный локальный TOML, где `LOCAL_ASN`/`ROUTER_ID` уже выбраны оператором:

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

Для пиров используйте managed template: каждый реальный сосед `admin-down=true`,
import reject; export reject до согласования policy. `tools.export_policy`
создаёт политику экспорта только local owned-путей, не общий allow-all. Политики
и подключение реальных роутеров — отдельный этап, не финал установщика.

## 6. Первый запуск master

Только после TLS/config review:

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini init-db
chown -R hemlock:hemlock /var/lib/hemlock
chmod 0700 /var/lib/hemlock
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini user create admin --role admin
systemctl enable --now gobgp.service hemlock.service
systemctl is-active gobgp.service hemlock.service
journalctl -u hemlock.service -n 40 --no-pager
```

Пароль вводится дважды интерактивно, 6–1024 символа, минимум буква и цифра.
GoBGP инициализируется один раз; при изменениях правил не перезапускается.
Если порт HTTPS 443, раскомментируйте **обе** capability-строки в unit/drop-in,
оставив NoNewPrivileges; `daemon-reload`, затем только restart hemlock.
Проверка HTTPS без отключения доверия:

```bash
curl --noproxy '*' --cacert /etc/hemlock/tls/ca.crt \
  "https://$NODE_IP:8443/api/session"
```

Ожидается `{"authenticated":false}`. Войдите в веб, проверьте локальную версию,
пустой список правил, GoBGP и успешную инициализацию **всех** protected ASN.
При добавлении protected ASN в INI нужен restart Hemlock для перечитывания и
успешный protection refresh до экспорта cache. Ошибка источника cache не очищает.
Сосед может пока отсутствовать — это должно быть видно как unavailable.

## 7. Подключение slave и эксплуатация

[INSTALL_B.md](INSTALL_B.md) — самостоятельная последовательность подготовки
slave с CSR, безопасным переносом секрета и protection, snapshot/journal.
На master после подготовки slave задайте его `peer_url`, `peer_node_id`, CA/secret,
проверьте права INI и перезапустите **только Hemlock** для перечитывания.
Одинаковый общий secret и взаимное доверие сертификатам обязательны. Node IDs
и route owner узлов различаются. У пользователей на slave нет записи.

Обновление, rollback и ручная смена ролей: [LIFECYCLE.md](LIFECYCLE.md).
Автоматического failover/merge нет. `announcements=no` в обычной работе не отзывает
старые маршруты; явный `routes withdraw-owned --execute` отзывает только owned.
Исключение v0.3.0+: startup master→slave выполняет dedicated drain и durable fence.
Локальная RIB/Adj-RIB-Out не доказывают принятие маршрута удалённым роутером.
