# Установка master Hemlock на чистую Debian 13

Документ относится к канонической поставке **0.5.0 и новее**. Стандарт:
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
RELEASE='<PUBLISHED_0.5_OR_LATER_TAG_OR_FULL_40_HEX_COMMIT>'
git clone https://github.com/biba-odesa/hemlock.git /root/hemlock-source
cd /root/hemlock-source
git fetch origin "$RELEASE"
COMMIT=$(git rev-parse --verify 'FETCH_HEAD^{commit}')
git checkout --detach "$COMMIT"
printf 'Selected commit: %s\n' "$COMMIT"
```

Сверьте COMMIT с публикацией по независимому каналу. Выберите опубликованный
тег/полный commit **0.5.0+**, содержащий новый TLS flow. Если тег ещё не создан,
используйте опубликованный полный commit. Старые теги не перемещаются.

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

## 4. Собственный сертификат без CA

В новой установке `[tls] mode = pinned`. CA/CSR не нужны: при первом старте
непривилегированный Hemlock создаёт собственную пару в отдельном каталоге
`/var/lib/hemlock/tls/identity`. Установщик уже создал родительский state directory
hemlock:hemlock 0700. Key/cert будут 0600; не создавайте один файл без другого.

Выберите management IP/DNS и задайте его в web.host и tls.names (SAN).
Для wildcard listener `0.0.0.0`/`::` names обязательны. Стандартные пути:
cert=/var/lib/hemlock/tls/identity/server.crt, key=.../server.key.
Не копируйте чужие keys/CA key. При повреждении/неверных правах приложение
откажется запускаться, не заменяя файлы. Срок 365 дней, предупреждение за 30 дней;
авторотация при истечении кратко перезапускает только HTTPS и требует approval
нового ключа на другом узле. GoBGP не перезапускается.

Старый CA-режим сохраняется только при явном `mode = legacy_ca` (старый INI без
TLS section также legacy). Для действующей пары сначала обновите B → A в legacy,
затем отдельно переключите оба в pinned; подробности [TLS_TRUST.md](TLS_TRUST.md).

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
cert = /var/lib/hemlock/tls/identity/server.crt
key = /var/lib/hemlock/tls/identity/server.key
ca =

[tls]
mode = pinned
state_dir = /var/lib/hemlock/tls
names = 192.0.2.10
days = 365
warn_days = 30

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
NODE_IP='<YOUR_MANAGEMENT_IP>'
curl --noproxy '*' --cacert /var/lib/hemlock/tls/identity/server.crt \
  "https://$NODE_IP:8443/api/session"
```

Ожидается `{"authenticated":false}`. Войдите в веб, проверьте локальную версию,
пустой список правил, GoBGP и успешную инициализацию **всех** protected ASN.
При добавлении protected ASN в INI нужен restart Hemlock для перечитывания и
успешный protection refresh до экспорта cache. Ошибка источника cache не очищает.
Сосед может пока отсутствовать — это должно быть видно как unavailable.

## 7. Подключение slave и эксплуатация

[INSTALL_B.md](INSTALL_B.md) — самостоятельная последовательность подготовки
slave с собственным ключом, безопасным переносом секрета, protection и snapshot/journal.
На master после подготовки slave задайте его `peer_url`, `peer_node_id` и общий secret,
проверьте права INI и перезапустите **только Hemlock** для перечитывания.
После старта обоих выполнить на КАЖДОМ узле:

```bash
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls self
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls peer
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls approve \
  --fingerprint 'SHA256:<VERIFIED_OTHER_NODE_SPKI>'
/opt/hemlock/.venv/bin/hemlock --config /etc/hemlock/hemlock.ini tls trust
```

Сверять candidate с консольным `tls self` ДРУГОГО сервера, не с тем же ответом
по сети. До взаимного approval данных/token нет. Пустой slave после approval
получает snapshot, прежний догоняет journal. CLI не требует пользователей/БД.
Одинаковый общий secret и независимое approval обоих ключей обязательны. Node IDs
и route owner узлов различаются. У пользователей на slave нет записи.

Обновление, rollback и ручная смена ролей: [LIFECYCLE.md](LIFECYCLE.md).
Автоматического failover/merge нет. `announcements=no` в обычной работе не отзывает
старые маршруты; явный `routes withdraw-owned --execute` отзывает только owned.
Исключение v0.3.0+: startup master→slave выполняет dedicated drain и durable fence.
Локальная RIB/Adj-RIB-Out не доказывают принятие маршрута удалённым роутером.
