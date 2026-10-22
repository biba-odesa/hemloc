# Установка Hemlock-B (slave) на чистую Debian 13

Инструкция для релиза **v0.1.0**, полный commit
`2a79d8a005bee81c8adf6f11fb856e3d0eb5064a` из
https://github.com/biba-odesa/hemlock. Это последовательность действий оператора,
а не автоматический установщик. Нельзя запускать её целиком одним скриптом.
A — действующий master; B — новый slave. Рабочую БД A на B не копируют.
Тег не перемещается. Код из более новой main для этой установки не нужен.

Все значения `<...>` нужно заранее заменить согласованными значениями.
Публичная инструкция не содержит конфигурации какого-либо провайдера.
Команды A выполнять только в отдельно согласованное окно; при подготовке этой
инструкции A не изменялся. SSH, firewall, маршруты и адреса VM автоматически
не меняются. Безопасный bootstrap выполняется с **announcements=no** и тремя
административно выключенными соседями. После проверок оператор может выбрать
announcements=yes на B при сохранённых import/export DENY-ANY на роутерах (§10).
Инструкция не меняет уже выбранный режим автоматически. Приём маршрутов
роутерами и реальное применение блокировок — отдельное решение.

## 0. План и переменные

Обычный пользователь на B входит через консоль/существующий SSH и выполняет
`sudo -i`. Далее все блоки с пометкой **B/root** выполняются в этой root-сессии;
`sudo -u hemloc` внутри блока явно понижает права. Блоки **A/root**, **рабочая
станция** и **Junos** выполняются на других указанных машинах, не на B.
На A не устанавливайте код B и не запускайте init-db.

**B/root:** заполнить и экспортировать переменные (это не секреты):

```bash
export A_IP='<MASTER_IP>' B_IP='<SLAVE_IP>'
export A_NODE='<MASTER_NODE_ID>' B_NODE='<SLAVE_NODE_ID>'
export ASN='<LOCAL_AND_PEER_ASN>'
export P1_IP='<PEER_1_IP>' P2_IP='<PEER_2_IP>' P3_IP='<PEER_3_IP>'
export P1_NAME='<PEER_1_NAME>' P2_NAME='<PEER_2_NAME>' P3_NAME='<PEER_3_NAME>'
export OWNER_A='<MASTER_OWNER_COMMA_SEPARATED>'
export OWNER_B='<UNIQUE_SLAVE_OWNER_COMMA_SEPARATED>'
export NH4='<APPROVED_IPV4_NEXT_HOP>' NH6='<APPROVED_IPV6_NEXT_HOP>'
export COMM4='<IPV4_COMMUNITY>' COMM6='<IPV6_COMMUNITY>'
export LP4='200' LP6='200'
export PROTECTED_ASNS='<PROTECTED_ASNS_COMMA_SEPARATED>'
export PROTECTED_PREFIXES='<EXPLICIT_PROTECTED_PREFIXES_COMMA_SEPARATED>'
export USE_PROXY='<yes_OR_no>'
export HTTP_PROXY_URL='<HTTP_PROXY_URL_OR_EMPTY>'
export HTTPS_PROXY_URL='<HTTPS_PROXY_URL_OR_EMPTY>'
export IRR_HOST='whois.radb.net' IRR_SOURCES='RIPE,RADB'
export EXPECTED_COMMIT='2a79d8a005bee81c8adf6f11fb856e3d0eb5064a'
```

OWNER_B — три uint32 через запятую, уникальные для этого узла; например отдельный
последний компонент в согласованном namespace. Он должен отличаться от OWNER_A,
совпадать с export policy B и сохраняться при обновлениях/смене роли.
Нельзя копировать owner A. Значения next-hop/атрибутов, IRR, protection и proxy
получить из действующего INI A, а не из публичного example. Неизвестный NH6
оставляют пустым и не разрешают IPv6-анонсы. Все пути ниже — конкретная схема
новой установки: `/opt/hemloc`, `/etc/hemloc`, `/var/lib/hemloc`, `/etc/gobgp`.

## 1. Debian, время, DNS, доступы и proxy

**B/root**, до первого git clone:

```bash
cat /etc/os-release
uname -m
ip -br address
ip route get "$A_IP"
date --iso-8601=seconds
timedatectl status
getent ahosts deb.debian.org github.com pypi.org whois.radb.net stat.ripe.net
```

Ожидается Debian 13, amd64 для приведённого Go SDK, адрес B на интерфейсе,
правильное время/часовой пояс и синхронизация часов. При ошибке остановиться:
исправление сети/времени согласует администратор, инструкция не меняет их.
Для другого CPU требуется другой проверенный SDK и его checksum.

Hemlock INI proxy **не применяется** к apt, pip, curl, Git или Go. Если для них
нужен proxy без авторизации, отдельно задать в текущей root-сессии:

```bash
# Optional; omit this block for direct downloads.
export http_proxy="$HTTP_PROXY_URL" https_proxy="$HTTPS_PROXY_URL"
export HTTP_PROXY="$HTTP_PROXY_URL" HTTPS_PROXY="$HTTPS_PROXY_URL"
export no_proxy="localhost,127.0.0.1,::1,$A_IP,$B_IP"
export NO_PROXY="$no_proxy"
```

Для прямой загрузки вместо этого:

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
```

Не вставлять proxy-пароли в argv, shell history или этот документ. Для proxy
с авторизацией администратор готовит отдельный защищённый механизм credentials;
не продолжать с секретом в URL. Постоянный apt proxy этой инструкцией не создаётся.

```bash
apt-get update
apt-get install --no-install-recommends git python3.13-venv ca-certificates \
  bgpq4 openssl curl openssh-client iproute2 procps tar gzip xz-utils
python3 --version
bgpq4 -v
git --version
```

Ожидаются Python 3.13, bgpq4 1.12 из Debian 13, Git и действующие CA.
Если apt не использует переменные proxy, передать только несекретные URL явно:
`apt-get -o Acquire::http::Proxy="$HTTP_PROXY_URL" -o Acquire::https::Proxy="$HTTPS_PROXY_URL" update`
и те же `-o` для install. Не выполнять оба варианта вслепую.

Требуемые доступы, которые оператор проверяет отдельно:

| Откуда → куда | Доступ / назначение |
| --- | --- |
| B → Debian mirrors | HTTP/HTTPS через согласованный proxy или напрямую |
| B → github.com, codeload.github.com, go.dev и redirect-хосты, proxy.golang.org, sum.golang.org | HTTPS для кода/Go-сборки |
| B → pypi.org, files.pythonhosted.org | HTTPS для hash-locked wheels |
| A ↔ B | прямой HTTPS TCP/8443 в обе стороны; без HTTP proxy |
| браузеры → B | HTTPS TCP/8443 |
| B → IRR_HOST | прямой TCP/43, HTTP proxy его не переносит |
| B → stat.ripe.net | HTTPS metadata согласно proxy INI |
| B → каждый BGP-сосед | исходящий TCP/179; маршрутизатор passive |
| B локально | gRPC 127.0.0.1:50051; наружу не открывать |
| B → инфраструктура DNS/времени | действующие DNS/NTP, согласно политике сети |

Slave не раскрывает заблокированные ASN вместо A, но собственный
ProtectionWorker обращается в IRR на обоих узлах.

**HTTP_PROXY/HTTPS_PROXY не обеспечивают транспорт для bgpq4.** Приложение
удаляет proxy env при его запуске; IRR нужен прямой TCP/43 либо отдельно
спроектированный и проверенный транспорт. Встроенного WHOIS-over-HTTP proxy нет.
Slave получает готовые **blocked ASN** наборы от master, но **protection refresh**
текущий код выполняет самостоятельно на каждом узле. При ошибке IRR сохранённый
protection cache остаётся, защита не уменьшается; ошибка должна быть видна.
После повышения slave до master доступ к IRR понадобится также для добавления
и обновления заблокированных ASN. Успех pip/curl через proxy этого не проверяет.
 BGP listener будет выключен
(`port=-1`), CAP_NET_BIND_SERVICE не требуется. Ни один порт инструкция сама
в firewall не открывает.

## 2. Фиксированный код, пользователи и venv

**B/root**, чистая машина, целевой `/opt/hemloc` ещё не существует:

```bash
useradd --system --user-group --home-dir /var/lib/hemloc --shell /usr/sbin/nologin hemloc
useradd --system --user-group --no-create-home --shell /usr/sbin/nologin gobgp
install -d -o root -g hemloc -m 0750 /etc/hemloc /etc/hemloc/tls
install -d -o root -g gobgp -m 0750 /etc/gobgp
install -d -o hemloc -g hemloc -m 0700 /var/lib/hemloc /var/lib/hemloc/backups
install -d -o root -g root -m 0700 /root/hemloc-transfer

git clone --branch v0.1.0 --single-branch https://github.com/biba-odesa/hemlock.git /opt/hemloc
cd /opt/hemloc
test "$(git rev-parse HEAD)" = "$EXPECTED_COMMIT"
git describe --tags --exact-match
git status --short
python3 -m venv /opt/hemloc/.venv
/opt/hemloc/.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock
/opt/hemloc/.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
/opt/hemloc/.venv/bin/python -m pip install --no-build-isolation --no-deps /opt/hemloc
/opt/hemloc/.venv/bin/python -m pip check
/opt/hemloc/.venv/bin/hemloc --help
chown -R root:root /opt/hemloc
chmod -R go-w /opt/hemloc
sudo -u hemloc test ! -w /opt/hemloc/hemloc/web.py
sudo -u hemloc test ! -w /opt/hemloc/.venv/bin/python
```

Ожидается нужный commit, тег v0.1.0, пустой status, `No broken requirements found`.
Сервис не владеет кодом или venv; Python-пакеты не ставятся в системный Python.
Повторная установка не должна перезаписывать существующие каталоги/конфиги:
если useradd/clone сообщил «уже существует», выяснить причину, не удалять данные.

## 3. GoBGP 4.10.0 с TTL-патчем

Нужен **4.10.0+hemloc-ibgp-ttl1**, а не stock binary и не GoBGP 3.x.
Stock 4.10.0 игнорирует multihop TTL для iBGP. Есть два взаимоисключающих пути.
Сборка/копирование выполняется только на B; A не перезапускается.

### Путь 1: сборка из проверенных исходников

**B/root:**

```bash
cd /opt/hemloc
install -d -m 0700 var/downloads
curl --fail --location --proto '=https' --proto-redir '=https' \
  https://codeload.github.com/osrg/gobgp/tar.gz/refs/tags/v4.10.0 \
  -o var/downloads/gobgp-v4.10.0-source.tar.gz
curl --fail --location --proto '=https' --proto-redir '=https' \
  https://go.dev/dl/go1.25.14.linux-amd64.tar.gz \
  -o var/downloads/go1.25.14.linux-amd64.tar.gz
sha256sum var/downloads/*.tar.gz
```

Ожидаемые SHA256:

- GoBGP source: `27d8ef958100557344be98e459fa43a20d2a15b5ce943d2aed2772958a3bf397`.
- Go SDK: `a21ae5633a269bcd7e90cf767e48225633795e99d831742cbf3397064fee7712`.

```bash
/opt/hemloc/.venv/bin/python tools/build_release.py \
  --ref v0.1.0 --output var/build-b \
  --gobgp-source var/downloads/gobgp-v4.10.0-source.tar.gz \
  --go-archive var/downloads/go1.25.14.linux-amd64.tar.gz \
  --gomodcache var/gomod --gocache var/gocache --fetch-modules
install -o root -g root -m 0755 var/build-b/gobgpd-1 /usr/local/bin/gobgpd
/usr/local/bin/gobgpd --version
sha256sum /usr/local/bin/gobgpd
```

Переносится только результат успешного `Two independent builds match`.
Скрипт сам проверяет checksum архивов, применяет оба изменения patch,
делает `go mod verify` и две offline-сборки после явного скачивания modules.
Версия/target/flags описаны в build-report.json. Новая воспроизводимая сборка
может иметь другой SHA, чем старый установленный binary A; совпадение версии
не заменяет происхождение и проверку патча.

### Путь 2: защищённый перенос проверенного binary A

**A/root:** `sha256sum /usr/local/bin/gobgpd` и
`/usr/local/bin/gobgpd --version`. Передать binary через существующий SSH/SFTP
с проверенным host key на рабочую станцию и затем B, без изменения sshd.
`/usr/local/bin/gobgpd` не содержит конфиг/секреты, но его checksum надо получить
независимо от канала передачи. **B/root:**

```bash
export EXPECTED_GOBGP_SHA='<VERIFIED_A_BINARY_SHA256>'
printf '%s  %s\n' "$EXPECTED_GOBGP_SHA" /root/hemloc-transfer/gobgpd | sha256sum -c -
install -o root -g root -m 0755 /root/hemloc-transfer/gobgpd /usr/local/bin/gobgpd
/usr/local/bin/gobgpd --version
```

В обоих случаях сохранить происхождение: upstream osrg/gobgp v4.10.0,
`deploy/patches/gobgp-4.10.0-ibgp-ttl.patch`, Go SDK checksum или акт переноса
binary A и checksum. GoBGP — Apache-2.0; приложенная
`deploy/patches/LICENSE.GoBGP` не заменяет notices транзитивных модулей при
дальнейшем распространении бинарника. Hemlock — MIT, biba-odesa.

## 4. Конфиг B GoBGP: все соседи Disabled, импорт запрещён

**B/root:** генератор использует только экспортированные несекретные переменные.
Глобальный import разрешает **локальные owned** пути для AddPath; импорт от
каждого BGP-соседа отдельно DENY-ALL. Экспорт — только local + OWNER_B,
остальное reject. Это не общий allow-all.

```bash
cd /opt/hemloc
/opt/hemloc/.venv/bin/python - <<'PY'
import os, re
from pathlib import Path
from tools.export_policy import owned_local_config
text = Path('deploy/gobgpd.managed.example.toml').read_text()
values = {'64496':os.environ['ASN'], '192.0.2.10':os.environ['B_IP'],
          '192.0.2.1':os.environ['P1_IP'], '192.0.2.2':os.environ['P2_IP'],
          '192.0.2.3':os.environ['P3_IP'], 'peer-one':os.environ['P1_NAME'],
          'peer-two':os.environ['P2_NAME'], 'peer-three':os.environ['P3_NAME']}
pattern = '|'.join(re.escape(k) for k in sorted(values, key=len, reverse=True))
text = re.sub(pattern, lambda m: values[m[0]], text)
owner = tuple(map(int, os.environ['OWNER_B'].split(',')))
assert owner != tuple(map(int, os.environ['OWNER_A'].split(',')))
text = owned_local_config(text, owner, enable_peers=False)
with Path('/etc/gobgp/gobgpd.toml').open('x') as out:
    out.write(text)
PY
chown root:gobgp /etc/gobgp/gobgpd.toml
chmod 0640 /etc/gobgp/gobgpd.toml
sudo -u gobgp /usr/local/bin/gobgpd --dry-run --pprof-disable \
  -f /etc/gobgp/gobgpd.toml --api-hosts=127.0.0.1:50051
```

Ожидается успешная проверка без запуска сессий. Полученный TOML проверить:
router-id/local-address B; local/peer ASN согласованы; `port=-1`;
три `admin-down=true`; оба unicast; hold 180 / keepalive 60 / connect-retry 10;
`passive-mode=false`; remote-port 179; multihop-ttl 25. Приложенный шаблон
задаёт именно эти таймеры. Listener/gRPC ограничивается unit ниже.

## 5. TLS: ключ B остаётся на B, CA key не переносится

Использовать доверенный A CA, проверить его fingerprint по независимому каналу.
Не генерировать новый CA под тем же именем: одинаковый CN не означает доверие.
В этой двухузловой схеме сертификат B подписывается **на A**, где хранится
приватный ключ CA. CA key остаётся на A и **никогда** не идёт на B.

**B/root:**

```bash
openssl req -new -newkey rsa:3072 -nodes \
  -keyout /etc/hemloc/tls/hemloc-b.key \
  -out /root/hemloc-transfer/hemloc-b.csr -subj "/CN=$B_NODE" \
  -addext "subjectAltName=IP:$B_IP"
chown root:hemloc /etc/hemloc/tls/hemloc-b.key
chmod 0640 /etc/hemloc/tls/hemloc-b.key
```

**Рабочая станция:** с проверенными SSH host keys передать CSR с B на A
(через login с sudo или согласованный SFTP staging, не root SSH по умолчанию).
CSR публичный. Ни ключ B, ни CA key не передавать. Пример команд **рабочей
станции**, после задания A_SSH/B_SSH (существующие login@host, не root):

```bash
umask 077
export A_SSH='<EXISTING_SSH_LOGIN_AT_MASTER>' B_SSH='<EXISTING_SSH_LOGIN_AT_SLAVE>'
ssh -T "$B_SSH" 'sudo -n cat /root/hemloc-transfer/hemloc-b.csr' > hemloc-b.csr.transfer && \
  test -s hemloc-b.csr.transfer && \
  openssl req -in hemloc-b.csr.transfer -noout -verify && \
  scp hemloc-b.csr.transfer "$A_SSH:hemloc-b.csr.transfer"
```

**A/root:** принять CSR в закрытый каталог и проверить именно принятую копию:

```bash
install -d -m 0700 /root/hemloc-transfer
install -o root -g root -m 0600 /home/<A_OPERATOR_LOGIN>/hemloc-b.csr.transfer \
  /root/hemloc-transfer/hemloc-b.csr
test -s /root/hemloc-transfer/hemloc-b.csr && \
  openssl req -in /root/hemloc-transfer/hemloc-b.csr -noout -verify
```

При ошибке SSH/sudo, пустом файле или неуспешной проверке CSR остановиться.
Для root-owned файлов нужен staging оператора; root SSH включать не требуется.

**A/root — подпись сертификата B на A**, переменные задать именно в консоли A:

```bash
export B_IP='<SLAVE_IP>' B_NODE='<SLAVE_NODE_ID>'
export CA_CERT='<EXISTING_CA_CERT_PATH>' CA_KEY='<EXISTING_CA_PRIVATE_KEY_PATH>'
export CSR='<RECEIVED_B_CSR_PATH>' OUT='<NEW_B_CERTIFICATE_PATH>'
install -d -m 0700 /root/hemloc-sign-b
cat > /root/hemloc-sign-b/b.ext <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:$B_IP
EOF
test -s "$CSR" && \
  openssl req -in "$CSR" -noout -verify && \
  openssl x509 -req -in "$CSR" -CA "$CA_CERT" -CAkey "$CA_KEY" \
  -set_serial "0x$(openssl rand -hex 16)" -days 365 -sha256 \
  -extfile /root/hemloc-sign-b/b.ext -out "$OUT" && \
  openssl verify -CAfile "$CA_CERT" "$OUT" && \
  openssl x509 -in "$OUT" -noout -ext subjectAltName -dates && \
  openssl x509 -in "$CA_CERT" -noout -fingerprint -sha256
```

Если test -s или openssl req завершились с ошибкой, **не подписывать**: повторить
передачу CSR и выяснить причину. Проверка размера и подписи обязательна именно
для принятого файла на A, а не только исходного файла B.

Явный serial не меняет действующий ca.srl. Не продлевать сертификат за пределы
срока CA. На B вернуть **только** ca.crt и hemloc-b.crt через проверенный канал.

После подписи, **рабочая станция**:

```bash
ssh -T "$A_SSH" 'sudo -n cat /root/hemloc-transfer/hemloc-b.crt' > hemloc-b.crt
ssh -T "$A_SSH" 'sudo -n cat /etc/hemloc/tls/ca.crt' > ca.crt
scp hemloc-b.crt ca.crt "$B_SSH:"
```

**B/root:** перенести оба принятых файла из staging. Проверить успешный
SSH/SFTP transfer и CA fingerprint по независимому каналу.

```bash
install -o root -g root -m 0600 /home/<OPERATOR_LOGIN>/hemloc-b.crt \
  /root/hemloc-transfer/hemloc-b.crt
install -o root -g root -m 0600 /home/<OPERATOR_LOGIN>/ca.crt \
  /root/hemloc-transfer/ca.crt
```

После установки проверить CA, IP SAN и совпадение публичных ключей:

```bash
install -o root -g hemloc -m 0640 /root/hemloc-transfer/ca.crt /etc/hemloc/tls/ca.crt
install -o root -g hemloc -m 0640 /root/hemloc-transfer/hemloc-b.crt /etc/hemloc/tls/hemloc-b.crt
openssl verify -CAfile /etc/hemloc/tls/ca.crt /etc/hemloc/tls/hemloc-b.crt
openssl x509 -in /etc/hemloc/tls/hemloc-b.crt -noout -checkip "$B_IP"
openssl x509 -in /etc/hemloc/tls/hemloc-b.crt -pubkey -noout | openssl pkey -pubin -outform DER | sha256sum
openssl pkey -in /etc/hemloc/tls/hemloc-b.key -pubout -outform DER | sha256sum
```

Последние два SHA должны совпасть; это public-key digests, секрет не выводится.
При ошибке verify/checkip или несовпадении SHA не запускать Hemlock и не считать
сертификат установленным корректно. Эта тройная проверка обязательна **после**
установки сертификата, включая случай повторного копирования файлов.
Для браузера установить **публичный CA** в доверенное хранилище рабочей станции
по её правилам. Для Debian-клиента выполнить:

```bash
sudo install -m 0644 ca.crt \
  /usr/local/share/ca-certificates/hemloc-ca.crt
sudo update-ca-certificates
```
На сервере приложения `web.ca` используется для проверки HTTPS соседа; системное
доверие не обязательно, если CA явно задан. Не применять `curl -k`/verify=False.

## 6. Репликационный секрет и изменения A (отдельное окно)

Нужны взаимные peer identities и **один и тот же** случайный token, минимум
32 непробельных символа. Это bearer-auth + проверяемый HTTPS, не mTLS.
Если A уже имеет token_file, использовать его существующий secret, не вращать
его и не генерировать другой. Если secret ещё нет — создать один на A:

**A/root**, только после разрешения изменения локального конфига A:

```bash
install -d -o root -g hemloc -m 0750 /etc/hemloc
umask 077
python3 - <<'PY'
from pathlib import Path
import secrets
with Path('/etc/hemloc/replication.token').open('x') as out:
    out.write(secrets.token_urlsafe(48) + '\n')
PY
chown root:hemloc /etc/hemloc/replication.token
chmod 0640 /etc/hemloc/replication.token
```

Никогда не использовать cat/echo, `set -x`, argv curl headers или shell variable
для самого token. Через уже настроенный SSH и sudo безопасно читать файл
командой на удалённом A и направить stdout **сразу в файл**, не терминал.
Например, **рабочая станция** с private umask (sudo на A должен быть заранее
авторизован; без него использовать защищённый согласованный file transfer):

```bash
umask 077
export A_SSH='<EXISTING_SSH_LOGIN_AT_MASTER>' B_SSH='<EXISTING_SSH_LOGIN_AT_SLAVE>'
ssh -T "$A_SSH" 'sudo -n cat /etc/hemloc/replication.token' > replication.token.transfer
# Stop on any SSH/sudo error; never install an empty or partial file.
test "$(wc -c < replication.token.transfer)" -ge 33
scp replication.token.transfer "$B_SSH:replication.token.transfer"
```

**B/root:**

```bash
install -o root -g hemloc -m 0640 \
  /home/<OPERATOR_LOGIN>/replication.token.transfer /etc/hemloc/replication.token
```

Удалить staging секрет с рабочего места и из home оператора после сверки и
успешной авторизации; обычный rm не гарантирует физическое стирание SSD/backup.
Не пересылать token в чат или Git. На A этот путь уже не менять без согласования.

**A/root**, сохранить копию INI вне Git, затем согласовать только перечисленные
ключи (выполнять позже, не при чтении инструкции):

```bash
cp -p /etc/hemloc/hemloc.ini "/etc/hemloc/hemloc.ini.before-b-$(date -u +%Y%m%dT%H%M%SZ)"
sudoedit /etc/hemloc/hemloc.ini
chown root:hemloc /etc/hemloc/hemloc.ini
chmod 0640 /etc/hemloc/hemloc.ini
stat -c '%U:%G %a %n' /etc/hemloc/hemloc.ini
sudo -u hemloc test -r /etc/hemloc/hemloc.ini
sudo -u hemloc /opt/hemloc/.venv/bin/python -c \
  'from hemloc.config import load; load("/etc/hemloc/hemloc.ini"); print("Configuration readable and valid")'
```


```ini
[node]
peer_node_id = <SLAVE_NODE_ID>
peer_url = https://<SLAVE_IP>:8443
token_file = /etc/hemloc/replication.token
[web]
ca = /etc/hemloc/tls/ca.crt
```

Это фрагмент для изменения существующих ключей, не второй дублирующий `[node]`.
Не менять role A, owner, announcements, protection или GoBGP. CA A должен
проверять цепочку B. Только после подготовки B выполнить
**A/root**:

```bash
systemctl restart hemloc
systemctl is-active hemloc
journalctl -u hemloc --since '-5 minutes' --no-pager
```

GoBGP A не трогать. Пока B ещё не поднят, peer unavailable нормально, но не In sync.
A обязан опрашивать B для Dashboard status/ack и забора локального security/audit
outbox B; только B→A snapshot polling недостаточно для полной двусторонней истории.
Без token_file A отклоняет запросы B даже если A сам никуда не опрашивает.

## 7. Полный INI B

**B/root:** этот генератор создаёт новый файл, не перезаписывает существующий:

```bash
/opt/hemloc/.venv/bin/python - <<'PY'
import configparser, os
from pathlib import Path
v = os.environ
c = configparser.ConfigParser(interpolation=None)
c.read_dict({
 'node': {'node_id':v['B_NODE'], 'role':'slave', 'database':'/var/lib/hemloc/hemloc.sqlite',
          'peer_node_id':v['A_NODE'], 'peer_url':f"https://{v['A_IP']}:8443",
          'token_file':'/etc/hemloc/replication.token', 'poll_seconds':'3'},
 'web': {'host':v['B_IP'], 'port':'8443', 'tls':'yes',
         'cert':'/etc/hemloc/tls/hemloc-b.crt', 'key':'/etc/hemloc/tls/hemloc-b.key',
         'ca':'/etc/hemloc/tls/ca.crt'},
 'gobgp': {'announcements':'no', 'grpc_target':'127.0.0.1:50051', 'owner':v['OWNER_B']},
 'gobgp_ipv4': {'next_hop':v['NH4'], 'local_preference':v['LP4'], 'community':v['COMM4']},
 'gobgp_ipv6': {'next_hop':v['NH6'], 'local_preference':v['LP6'], 'community':v['COMM6']},
 'irr': {'irr_command':'bgpq4', 'irr_server':v['IRR_HOST'], 'irr_sources':v['IRR_SOURCES'],
         'irr_refresh_days':'30', 'timeout':'15', 'change_ratio':'0.5',
         'change_absolute':'10000', 'max_prefixes':'100000'},
 'protection': {'protected_asns':v['PROTECTED_ASNS'], 'protected_prefixes':v['PROTECTED_PREFIXES']},
 'proxy': {'use_proxy':v['USE_PROXY'], 'http':v['HTTP_PROXY_URL'], 'https':v['HTTPS_PROXY_URL'],
           'no_proxy':f"localhost,127.0.0.1,::1,{v['A_NODE']},{v['B_NODE']},{v['A_IP']},{v['B_IP']}"},
 'metadata': {'metadata_enabled':'yes'}
})
with Path('/etc/hemloc/hemloc.ini').open('x') as out:
    c.write(out)
PY
chown root:hemloc /etc/hemloc/hemloc.ini
chmod 0640 /etc/hemloc/hemloc.ini
stat -c '%U:%G %a %n' /etc/hemloc/hemloc.ini
sudo -u hemloc test -r /etc/hemloc/hemloc.ini
sudo -u hemloc /opt/hemloc/.venv/bin/python -c \
  'from hemloc.config import load; load("/etc/hemloc/hemloc.ini"); print("Configuration readable and valid")'
sudo -u hemloc /opt/hemloc/.venv/bin/python - <<'PY'
from hemloc.config import load
c = load('/etc/hemloc/hemloc.ini')
assert c.role == 'slave' and not c.announcements
print('Valid slave configuration; announcements disabled')
PY
```

После **каждого** создания или редактирования INI повторить chown/chmod/stat,
проверку чтения от hemloc и разбор Config, как в блоке выше. Редактор может
заменить файл и изменить владельца/права, в том числе на root:root 0600.
Ожидается root:hemloc 640; только root-чтения недостаточно.
Проверка Config не проверяет сетевую доступность, TLS key match и наличие token.
`use_proxy=no` игнорирует системные proxy env; yes использует INI http/https/no_proxy
для внешних metadata. Репликация и локальный gRPC всегда напрямую. Произвольные
X-Forwarded-For не доверяются. Формат owner — запятые в INI, двоеточия в BGP policy.

## 8. Init-db и перенос накопленного protection

**Пробел v0.1.0:** в `hemloc --help` нет `protection export/import`; нельзя
выдумывать эти команды. IRR refresh не восстановит исторически накопленный
монотонный cache, а обычная репликация его намеренно не передаёт.
Долгосрочное решение — отдельная проверенная maintenance CLI в будущем релизе.
Ниже — явная временная процедура для v0.1.0, требующая проверки оператором:
маленький standalone переносчик, A только read-only; B — offline, slave,
announcements=no, импорт через `Store.transaction/write_local`, только union.
Это **не встроенная CLI-команда** и не новый канал автоматической репликации.
Без переноса/проверки cache этап реальных анонсов заблокирован.

### Новый protected ASN в изменённом INI

Добавление ASN в файл ещё не означает его инициализацию. Текущий процесс читает
INI при запуске: после разрешённого изменения надо восстановить права/чтение
INI и отдельно согласовать **перезапуск только Hemlock** для перечитывания.
GoBGP для этого не перезапускают. На каждом узле protection refresh должен
успешно завершиться: проверить Info и наличие success metadata **для каждого**
protected ASN. При недоступном IRR не выдумывать success и не удалять ASN ради
экспорта. Старый cache сохраняется, но отсутствие success нового ASN означает,
что готовность ещё не подтверждена. После успешной инициализации сделать новый
read-only export; импортировать прежний файл, созданный до неё, недостаточно.
Если переносчик разрешил экспорт неполного состояния, его строгий import всё
равно должен отказать. Процедура не копирует рабочую БД между узлами.

**B/root:** init-db требует root, а не sudo -u hemloc. База пока пустая.

```bash
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini init-db
chown -R hemloc:hemloc /var/lib/hemloc
chmod 0700 /var/lib/hemloc
```

Создать приведённый ниже `/root/hemloc-transfer/protection-transfer.py` на A и B
(обычный текст программы, не секрет; режим 0700). A не останавливать.
Импортировать только после успешного init-db B и до старта Hemlock B.
Не использовать Python `-O`: проверочные assert должны быть включены.
Переносчик не копирует документы, пользователей, сессии, route owner или БД.
Контроль digest обнаруживает порчу файла, но не заменяет доверенный SSH-канал.

```python
"""Explicit v0.1.0 offline protection transfer, never a database clone."""
import argparse
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from hemloc.config import load
from hemloc.domain import asn, prefix
from hemloc.store import Store, digest
from hemloc.workers import process_lock


def validate(payload):
    assert set(payload) == {'schema', 'node', 'exported_at', 'asns', 'explicit', 'cache'}
    assert payload['schema'] == 1 and isinstance(payload['node'], str)
    assert type(payload['exported_at']) in (int, float) and math.isfinite(payload['exported_at'])
    assert isinstance(payload['asns'], list) and all(type(n) is int and asn(n) == n for n in payload['asns'])
    assert len(set(payload['asns'])) == len(payload['asns'])
    for values in (payload['explicit'], payload['cache']['prefixes']):
        assert isinstance(values, list) and len(values) <= 1000000
        assert all(isinstance(p, str) and prefix(p) == p for p in values)
    assert set(payload['cache']) == {'prefixes', 'success'}
    assert isinstance(payload['cache']['success'], dict)
    for key, value in payload['cache']['success'].items():
        assert str(asn(key)) == key
        assert type(value) in (int, float) and math.isfinite(value) and value > 0
    assert all(str(n) in payload['cache']['success'] for n in payload['asns'])
    assert not payload['asns'] or payload['cache']['prefixes']


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('export', 'import'))
    parser.add_argument('--config', required=True)
    parser.add_argument('--file', required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0, 'Root only; run without Python -O'
    config = load(args.config)
    assert Path(config.database).is_file(), 'Initialize the target database first'
    target = Path(args.file)
    if args.operation == 'export':
        # Read-only SQLite snapshot; do not construct Store on a running source.
        uri = Path(config.database).resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            row = db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
            cache = json.loads(row[0]) if row else {'prefixes': [], 'success': {}}
        payload = dict(schema=1, node=config.node_id, exported_at=time.time(),
                       asns=list(config.protected_asns), explicit=list(config.protected_prefixes), cache=cache)
        validate(payload)
        envelope = dict(payload=payload, digest=digest(payload))
        with target.open('x', encoding='utf-8') as out:
            json.dump(envelope, out, ensure_ascii=False, sort_keys=True)
        target.chmod(0o600)
    else:
        assert config.role == 'slave' and not config.announcements, 'Offline slave, announcements=no required'
        assert target.stat().st_size <= 32 * 1024 * 1024
        envelope = json.loads(target.read_text())
        assert set(envelope) == {'payload', 'digest'}
        payload = envelope['payload']
        assert digest(payload) == envelope['digest'], 'Transfer integrity check failed'
        validate(payload)
        assert payload['node'] == config.peer_node_id, 'Unexpected protection source node'
        assert set(payload['asns']) <= set(config.protected_asns), 'Configure source protected ASNs first'
        assert set(payload['explicit']) <= set(config.protected_prefixes), 'Configure source explicit prefixes first'
        owner = Path(config.database).stat()
        if owner.st_uid:
            os.setgroups([])
            os.setgid(owner.st_gid)
            os.setuid(owner.st_uid)
        with process_lock(config.database):
            store = Store(config, activate=False)
            with store.transaction() as db:
                assert store.meta(db, 'role') == 'slave'
                assert store.meta(db, 'node_id') == config.node_id
                row = db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
                old = json.loads(row[0]) if row else {'prefixes': [], 'success': {}}
                state = dict(prefixes=sorted(set(old['prefixes']) | set(payload['cache']['prefixes'])),
                             success=dict(old['success']))
                for key, value in payload['cache']['success'].items():
                    state['success'][key] = max(state['success'].get(key, 0), value)
                store.write_local(db, 'protection', state)
    print('Protection transfer complete; no rules, users, sessions, keys or tokens transferred.')


if __name__ == '__main__':
    main()
```

**A/root**, будущий явно разрешённый read-only export, файл назначения новый:

```bash
install -d -m 0700 /root/hemloc-transfer
/opt/hemloc/.venv/bin/python /root/hemloc-transfer/protection-transfer.py export \
  --config /etc/hemloc/hemloc.ini --file /root/hemloc-transfer/protection.json
sha256sum /root/hemloc-transfer/protection.json
```

Передать JSON через проверенный SFTP/SSH в `/root/hemloc-transfer/protection.json`
B. Файл не содержит credential/правил, но раскрывает собственные сети — private,
не коммитить. SHA сверить отдельно. Не переиспользовать старый export молча:
записать время и согласовать отсутствие новых protection изменений на A между
экспортом и включением B. При новых изменениях повторить export/import union.
Явные protected ASN/prefixes A из envelope должны входить в INI B; переносчик
откажет иначе. Не удалять дополнительную локальную protection B.

**B/root**, файл читается root до понижения UID; Hemlock B должен быть остановлен:

```bash
/opt/hemloc/.venv/bin/python /root/hemloc-transfer/protection-transfer.py import \
  --config /etc/hemloc/hemloc.ini --file /root/hemloc-transfer/protection.json
```

Повтор безопасен: наборы объединяются, success timestamps сохраняются по max,
защита не уменьшается; root CLI не меняет history/cursor или роль. Схема,
нормализация, целостность, source node и настроенные ASN/сети проверяются.
Общий cache не хранит привязку каждого префикса к ASN — он переносится целиком,
без выдумывания происхождения или обнуления исторических timestamp.
ProtectionWorker B впоследствии может **добавить** новые сети из IRR, ошибки
не снимают импортированную защиту. Exact и more-specific запрещены;
охватывающий less-specific агрегат разрешён, IPv4/IPv6 одинаково.

## 9. Установка units и первый старт

**B/root:**

```bash
install -o root -g root -m 0644 /opt/hemloc/deploy/gobgp.service /etc/systemd/system/gobgp.service
install -o root -g root -m 0644 /opt/hemloc/deploy/hemlock.service /etc/systemd/system/hemloc.service
systemd-analyze verify /etc/systemd/system/gobgp.service /etc/systemd/system/hemloc.service
sudo -u hemloc test -r /etc/hemloc/tls/hemloc-b.key
sudo -u hemloc test -r /etc/hemloc/replication.token
sudo -u hemloc test -w /var/lib/hemloc
systemctl daemon-reload
systemctl enable --now gobgp.service
systemctl enable --now hemloc.service
systemctl is-active gobgp.service hemloc.service
systemctl show gobgp hemloc -p MainPID -p NRestarts
ss -lntp
curl --noproxy '*' --cacert /etc/hemloc/tls/ca.crt --fail --silent --show-error "https://$B_IP:8443/" -o /dev/null
journalctl -u hemloc -u gobgp --since '-10 minutes' --no-pager
```

Ожидается active; HTTPS только на B:8443, gRPC только 127.0.0.1:50051;
BGP listener отсутствует. Три соседа Disabled, не Established. Не считать
описание соседа доказательством сессии. Сервис один, никаких Uvicorn workers>1.

На slave **не создавать администратора**, не сбрасывать пароли, не импортировать
правила. Snapshot A передаёт пользователей/Argon2id-хеши, правила, ASN-наборы и
общий аудит. После него journal догоняет изменения; локальная protection остаётся.
Перед первым snapshot B резервирует прежнюю пустую БД. Свободного диска должно
хватить для snapshot и резервных БД. Журнал/снимок ограничен размером 128 MiB ответа.

### Проверка authenticated status без token в argv

**B/root:** создать read-only диагностический клиент; он не делает login и не
передаёт изменения/аудит. На A его можно запускать после настройки peer_url:

```bash
/opt/hemloc/.venv/bin/python - <<'PY'
import json
from hemloc.config import load
from hemloc.replication import PeerTransport
c = load('/etc/hemloc/hemloc.ini')
p = PeerTransport(c).get('/replication/status')
print(json.dumps({k:p.get(k) for k in ('node_id','role','history','sequence','master_id')}, indent=2))
PY
```

Это показывает **соседа**, на B — A, на A — B. На обоих должны совпасть history
(поколение), sequence/cursor при отсутствии текущих записей; master_id — A.
Одного одинакового sequence при разных history недостаточно.
Для локальных счётчиков — без создания Store/миграций — read-only снимок:

```bash
/opt/hemloc/.venv/bin/python - <<'PY'
import json, sqlite3
from pathlib import Path
from hemloc.config import load
c = load('/etc/hemloc/hemloc.ini')
with sqlite3.connect(Path(c.database).as_uri()+'?mode=ro', uri=True) as db:
    db.execute('BEGIN')
    meta = dict(db.execute('SELECT key,value FROM meta'))
    counts = dict(db.execute('SELECT kind,count(*) FROM documents GROUP BY kind'))
    row = db.execute("SELECT body FROM local WHERE key='protection'").fetchone()
    cache = json.loads(row[0]) if row else {'prefixes':[], 'success':{}}
    print({k:meta.get(k) for k in ('node_id','role','history','sequence','master_id')})
    print('Document counts:', counts)
    print('Cached protection prefixes:', len(cache['prefixes']))
    print('Protection initialized:', all(str(a) in cache['success'] for a in c.protected_asns))
PY
```

Это чтение, не ручное редактирование SQLite. Счётчики правил/пользователей
сопоставить с A; аудит может расти из-за реальных входов/работы системы, поэтому
сравнивать при догнавшем cursor. Ни хеши, ни содержимое аудита команда не печатает.

В браузере `https://<SLAVE_IP>:8443/` после доверия CA войти прежней учётной
записью A. Это настоящий вход и штатно появится в истории. Dashboard: статус A
In sync, last success свежий, lag 0; на A статус B тоже свежий. Info: protection
явные сети + накопленный cache, готовность ASN. Users: учётная запись только
для просмотра, смена пароля отключена с указанием master; формы изменений
недоступны. API запрет записи проверять тестами на отдельной БД, не созданием
фиктивных production-правил. `hemlock user list` от root B — допустимое чтение.
`hemloc desired` выводит реальные сети/причины; использовать только в приватный
файл с umask077, не в публичный тикет. До включения announcements маршруты
могут быть Pending/Unknown; desired не означает Applied или экспорт.

## 10. Отдельный этап: Junos и включение BGP B

Только после подтверждения TLS/репликации/protection. На **каждом** из трёх
роутеров оператор сначала смотрит существующую группу; модель/версию Junos,
унаследованные local-address/authentication/TTL-security и разрешённые семейства
надо сверить с фактической конфигурацией. Не копировать group source-address A
в новый neighbor B и не менять настройки других соседей.

**Junos**, подставить B IP, ASN и свой адрес конкретного роутера:

```text
show configuration protocols bgp group <BGP_GROUP> | display inheritance
show configuration policy-options policy-statement DENY-ANY
configure exclusive
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> description "Hemlock-B"
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> passive
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> peer-as <LOCAL_AND_PEER_ASN>
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> local-address <THIS_ROUTER_IP>
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> hold-time 180
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> family inet unicast
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> family inet6 unicast
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> import DENY-ANY
set protocols bgp group <BGP_GROUP> neighbor <SLAVE_IP> export DENY-ANY
show | compare
commit check
commit confirmed 5
run show bgp neighbor <SLAVE_IP>
commit
exit
```

DENY-ANY должен существовать и действительно reject все маршруты. Если иначе —
остановиться, не создавать/менять общую policy вслепую. Neighbor import/export
явно перекрывают наследование; group policies и существующие соседи не меняются.
Peer ASN тот же iBGP ASN. Исходящий TTL B=25 не означает настроенный GTSM на Junos:
при inherited TTL security/MD5 потребуется отдельное согласование. Не отключать
защиту группы ради B. Проверить compare: только один **новый** neighbor.
На каждом роутере `<THIS_ROUTER_IP>` — адрес, который B использует для него.
Это шаблон Junos, не результат проверки на ваших роутерах. Синтаксис и
семантика сверены с официальными справочниками: [neighbor settings](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/neighbor-edit-protocols-bgp.html),
[family](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/family-edit-protocols-bgp.html),
[peer import/export](https://www.juniper.net/documentation/us/en/software/junos/bgp/topics/topic-map/basic-routing-policies.html).
Хранение rejected routes зависит от [keep](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/keep-edit-protocols-bgp.html).

### Включать соседей на B по одному

**B/root:** пока announcements=no, выбрать P1. Сохранить TOML за пределами /opt,
затем поменять только его admin-down, не общий replace всех true:

```bash
cp -p /etc/gobgp/gobgpd.toml /root/hemloc-transfer/gobgpd.before-first-peer.toml
export ENABLE_PEER="$P1_IP"
/opt/hemloc/.venv/bin/python - <<'PY'
import os, re, tomllib
from pathlib import Path
p = Path('/etc/gobgp/gobgpd.toml')
text = p.read_text()
parts = re.split(r'(?m)(?=^\[\[neighbors\]\]$)', text)
changed = 0
for i, block in enumerate(parts):
    if f'neighbor-address = "{os.environ["ENABLE_PEER"]}"' in block:
        assert block.count('admin-down = true') == 1
        parts[i] = block.replace('admin-down = true', 'admin-down = false', 1)
        changed += 1
assert changed == 1
text = ''.join(parts)
tomllib.loads(text)
p.write_text(text)
PY
sudo -u gobgp /usr/local/bin/gobgpd --dry-run --pprof-disable -f /etc/gobgp/gobgpd.toml --api-hosts=127.0.0.1:50051
systemctl restart gobgp
systemctl is-active gobgp hemloc
```

Для первоначального подключения нового B используется restart **его** GoBGP:
unit v0.1.0 не включает config-auto-reload; SIGHUP/reload здесь не обещается.
Это прервёт уже включённые сессии **B**, поэтому каждый следующий restart
согласовывается отдельно. GoBGP A никогда не трогать. Это не операция изменения
правила Hemlock. Для P2/P3 повторить с `ENABLE_PEER="$P2_IP"`/`"$P3_IP"` после
проверки предыдущего. Dashboard B должен показать фактический Established/uptime;
прочие пока Disabled. На Junos `show bgp neighbor <SLAVE_IP>` проверяет реальную
сессию. До announcements RIB/Adj-RIB-Out нового B должны быть пустыми.

### Отдельное разрешение announcements

**Допустимый выбранный оператором сценарий:** на B announcements=yes, а на
каждом роутере import/export нового соседа остаются DENY-ANY. B поддерживает
локальную RIB и экспортирует собственные пути; роутер их отклоняет своей
политикой. Этот сценарий не равен announcements=no и не доказывает FIB/blackhole.
Не переключать уже выбранный режим автоматически ради соответствия инструкции.
Bootstrap и offline import выше требуют no; переход к yes — отдельное решение
после импорта, синхронизации и готовности protection.

Для **разрешённого оператором изменения**, B/root: изменить только
[gobgp] announcements через редактор, затем проверить права/INI:

```bash
sudoedit /etc/hemloc/hemloc.ini
chown root:hemloc /etc/hemloc/hemloc.ini
chmod 0640 /etc/hemloc/hemloc.ini
stat -c '%U:%G %a %n' /etc/hemloc/hemloc.ini
sudo -u hemloc test -r /etc/hemloc/hemloc.ini
sudo -u hemloc /opt/hemloc/.venv/bin/python -c \
  'from hemloc.config import load; load("/etc/hemloc/hemloc.ini"); print("Configuration readable and valid")'
systemctl restart hemloc
systemctl is-active hemloc
```

Этот блок — инструкция на случай изменения, **не действие при чтении документа**.
Если настройка уже yes и проверена, повторный restart не нужен. GoBGP не
перезапускать, Junos DENY-ANY оставить.
Dashboard: desired IPv4/IPv6 совпадают с ожидаемым набором после локальной protection,
нет ошибочного Applied при stale наблюдениях; свежая локальная RIB содержит owner B,
утверждённые next-hop/local-pref/communities. Детали prefix показывают экспорт
по каждому Established соседу. Все excluded protection причины объяснимы.

На каждом Junos отдельно проверить:

```text
show bgp summary
show bgp neighbor <SLAVE_IP>
show route receive-protocol bgp <SLAVE_IP> hidden
```

Команда hidden не гарантирует полный pre-policy Adj-RIB-In на любой версии Junos:
сохранение rejected routes зависит от keep policy. Нулевой вывод при DENY-ANY
не опровергает локальный экспорт B. Сверять session counters/доступные received
routes и policy на роутере. Hemlock Adj-RIB-Out не подтверждает приём/установку/FIB.
**DENY-ANY пока оставить**. Перевод в реально применяемый blackhole требует
отдельного изменения только neighbor policies и проверки MTR из сети провайдера.
Это не автоматический последний шаг установки.

`announcements=no` не отзывает существующие пути! Для аварийного отключения
локальных owned путей B: установить no, остановить только Hemlock B, затем root:

```bash
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini routes withdraw-owned
# Review the dry-run target and counts before the next command.
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini routes withdraw-owned --execute
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini routes withdraw-owned
```

Ожидается owned=0, чужие пути не удалены. Owner не менять. При старте с yes
desired будут добавлены заново. Для maintenance оставить no; GoBGP не останавливать.

## 11. Приёмка, reboot и безопасная проверка репликации

После согласованной перезагрузки **только B** (`systemctl reboot`) повторить
is-active, ss, HTTPS с CA, generation/cursor, cache, счётчики, Dashboard обеих
сторон, uptime/соседей и локальные/экспортируемые пути. IP/CA/token/INI должны
сохраниться; owner не меняется. Reboot прерывает сессии B, согласовать окно.

Чтобы проверить **новое** journal-событие без изменения блокируемого пространства:
оператор выбирает существующее правило на A, сохраняет прежний comment локально,
через веб A добавляет к comment согласованную заметку, наблюдает её и новый cursor
на B; затем восстанавливает **точный** исходный comment на A и проверяет догон.
Префиксы/учётные записи не меняются, аудит обеих редакций остаётся навсегда.
Если такое production-изменение не разрешено, не делать его: выполнить тот же
сценарий на двух отдельных лабораторных экземплярах. Тестовый IP в рабочие
списки не добавлять. API mutations на slave не проверять ценой фиктивного аудита.

Автономность B проверять лабораторией, не останавливая A и не меняя firewall:
**обычный пользователь** в отдельном user-owned checkout v0.1.0, с его venv
и hash-locked requirements-test.lock, выполняет:

```bash
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-test.lock
.venv/bin/python tools/prepare_lab.py --directory var/b-outage-lab
.venv/bin/python tools/check_lab.py --directory var/b-outage-lab
```

Имена каталогов должны быть новыми. check_lab интерактивно запросит временный
пароль дважды (минимум буква и цифра); не использовать рабочий пароль.
Это собственные loopback HTTPS процессы,
отдельные DB/CA/порты, без production peers; script останавливает только lab master,
проверяет сохранение правил/slave read-only, рестарт/догон, ручную смену ролей.
Для проверки реальных **тестовых** RIB можно добавить
`--gobgp-binary /usr/local/bin/gobgpd`: harness сам поднимет peer-free daemons,
не подключится к рабочему gRPC. Не запускать с рабочим INI.

## 12. Backup, restore и обновление B

**B/root**, online backup штатным SQLite backup API; CLI временно принимает UID
владельца DB, поэтому destination должен быть доступен hemloc:

```bash
export STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
export BACKUP="/var/lib/hemloc/backups/hemloc-$STAMP.sqlite.backup"
/opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini backup "$BACKUP"
```

Это завершённый backup, не cp открытой SQLite. Он содержит пользователей/хеши,
аудит, generation/cursor, локальную protection, ownership observations и сессии:
хранить закрыто/зашифрованно, отдельно от Git. Секреты INI/token/TLS сохранить
отдельным защищённым архивом в каталоге root, с правами и retention:

```bash
umask 077
tar -C / -czf "/root/hemloc-transfer/config-$STAMP.tar.gz" etc/hemloc etc/gobgp
chmod 0600 "/root/hemloc-transfer/config-$STAMP.tar.gz"
```

Скопировать DB backup и config archive в защищённое backup-хранилище. Не класть
его в публичные artifacts. CA private key B не имеет и не резервирует.
Snapshot backups `.backup-*` могут накапливаться: disk monitoring/retention —
отдельная задача, удалять только явно выбранные завершённые backup.

Restore drill сначала в отдельном каталоге/лаборатории, не поверх работающей БД:
проверить `PRAGMA integrity_check`, документы/пользователей/аудит, generation/cursor,
protection и последующий journal. Для изолированного готового drill:
`/opt/hemloc/.venv/bin/python /opt/hemloc/tools/check_restore.py`
(пакетные зависимости runtime достаточны; создаёт только временные DB).

При реальном восстановлении B: согласовать простой и изолировать BGP B на роутерах/
гипервизоре; остановить Hemlock B. GoBGP может продолжать экспорт старой RIB,
поэтому одной остановки приложения недостаточно. На потерянной VM не поднимать
вторую одновременно с тем же IP/owner. Использовать **B backup**, не рабочую DB A:

```bash
systemctl stop hemloc
export RESTORE_DB='<COMPLETED_B_BACKUP_PATH>'
```

До mv/install проверить выбранный backup, **B/root** (сначала задать RESTORE_DB):

```bash
/opt/hemloc/.venv/bin/python - <<'PY'
import os, sqlite3
from pathlib import Path
from hemloc.config import load
c = load('/etc/hemloc/hemloc.ini')
with sqlite3.connect(Path(os.environ['RESTORE_DB']).resolve().as_uri()+'?mode=ro', uri=True) as db:
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    meta = dict(db.execute('SELECT key,value FROM meta'))
    assert meta['node_id'] == c.node_id and meta['role'] == 'slave'
print('Valid completed backup for this slave')
PY
```

Только после успешной проверки выполнить **B/root**:

```bash
export SAVED="/var/lib/hemloc/pre-restore-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -o hemloc -g hemloc -m 0700 "$SAVED"
for part in hemloc.sqlite hemloc.sqlite-wal hemloc.sqlite-shm hemloc.sqlite.owner.lock; do
  if test -e "/var/lib/hemloc/$part"; then mv "/var/lib/hemloc/$part" "$SAVED/"; fi
done
install -o hemloc -g hemloc -m 0600 "$RESTORE_DB" /var/lib/hemloc/hemloc.sqlite
```

Исходная завершённая резервная копия остаётся нетронутой. Через read-only
проверку из §9 сверить node_id B/role slave, history/cursor/cache. Восстановить
локальный INI B/TLS/token из закрытого config backup при необходимости, **не**
накатывать архив на A. Если protection backup старее текущего cache, до запуска
импортировать свежий export union, не терять накопленную защиту.
Оставить announcements=no, затем старт Hemlock, полная синхронизация/догон,
проверка desired и local RIB. Только после актуализации маршрутов разрешать BGP;
no само по себе старые пути GoBGP не отзывает. Восстановленные браузерные сессии
могут оставаться до срока/credential-version проверки; для утраты/компрометации
backup нужна отдельная процедура отзыва credentials, не молчаливое доверие им.

Для обновления выбрать **существующий фиксированный** новый tag и полный commit,
прочитать его изменения/миграции. Сделать оба backup, поставить announcements=no
и сохранить неизменный owner. Остановить только Hemlock B. `git fetch --tags origin`,
`git checkout --detach <NEW_TAG>`, `test "$(git rev-parse HEAD)" = '<NEW_FULL_COMMIT>'`.
Обновить зависимости из новых lock в **новом** root-owned venv, собрать/установить
пакет и выполнить pip check; поменять `.venv` только при остановленном Hemlock.
Пример точной последовательности **B/root** после backup/установки no:

```bash
export NEXT_TAG='<APPROVED_NEW_TAG>' NEXT_COMMIT='<APPROVED_NEW_FULL_COMMIT>'
export STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
systemctl stop hemloc
cd /opt/hemloc
git fetch --tags origin
git checkout --detach "$NEXT_TAG"
test "$(git rev-parse HEAD)" = "$NEXT_COMMIT"
export NEXT_VENV="/opt/hemloc/var/venvs/$NEXT_TAG"
test ! -e "$NEXT_VENV"
python3 -m venv "$NEXT_VENV"
"$NEXT_VENV/bin/python" -m pip install --require-hashes --only-binary=:all: -r requirements.lock
"$NEXT_VENV/bin/python" -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock
"$NEXT_VENV/bin/python" -m pip install --no-build-isolation --no-deps /opt/hemloc
"$NEXT_VENV/bin/python" -m pip check
mv /opt/hemloc/.venv "/opt/hemloc/var/venvs/previous-$STAMP"
ln -s "$NEXT_VENV" /opt/hemloc/.venv
systemctl start hemloc
systemctl is-active hemloc
```

Останавливаться при любой ошибке, не копировать блок в script без error handling.
Новый venv остаётся по постоянному пути NEXT_VENV: перемещение готового venv
сломало бы shebang. Для rollback при остановленном Hemlock убрать только новый
symlink `.venv`, вернуть previous в исходный `.venv` и старый checkout, затем
проверить совместимость DB/миграций. Не удалять новый venv/backup автоматически.
Конфиг/DB/ключи не перезаписывать примерами. При rollback вернуть прежние tag/venv,
а для несовместимой миграции — завершённый backup, сохранив новые данные отдельно.
GoBGP/его binary не обновлять попутно. После старта проверять HTTPS, cursor,
protection и no; возвращение yes — отдельное действие оператора.

## 13. Ручной failover и возврат A

Автоматического promotion нет. При недоступном A B продолжает использовать
последние данные, локальную protection и собственный GoBGP. Изменения правил/
пользователей запрещены; не менять роль только для обхода read-only.

Если переключение необходимо:

1. Подтвердить, что старый A выключен или полностью изолирован от сети/BGP.
   Во время partition нельзя гарантированно обнаружить второго master.
2. На B консолью изменить только role на master в локальном INI, перезапустить
   **Hemlock**, не GoBGP. Проверить новый history, sequence, сохранение правил/users/
   protection/owner. Если B был в no, само promotion не разрешает анонсы.
3. Все дальнейшие изменения выполнять на новом master B. Не включать старый A
   без процедуры ниже; ветки никогда не объединяются.

Возврат старого A:

1. Запустить его с **отключённой сетью гипервизора**. Через консоль поставить
   role=slave, peer_url нового master B, identity/token/CA; сохранить owner A.
2. Перезапустить только Hemlock A. Независимый GoBGP может сохранять старые пути;
   смена роли не блокирует reconciliation на старых данных до snapshot.
3. Разрешить только канал репликации, **сохраняя изоляцию BGP A**. Если невозможно
   разделить доступы, не включать сеть целиком; согласовать изоляцию на роутерах.
4. Дождаться полного snapshot/догоняющего journal нового history, проверить
   protection/desired/локальную RIB и отозванные старые owned пути. Старую DB
   snapshot сохранит SQLite backup; source documents заменятся, локальный cache
   и конфиг останутся. Данные старой ветки не объединяются.
5. Только после этих проверок возвращать BGP/connectivity A и наблюдать экспорт.

Изолировать старый master — действие оператора, инструкция не меняет сеть сама.

## 14. Диагностика без раскрытия секретов

| Признак | Проверка / ожидаемое действие |
| --- | --- |
| TLS verify failed / certificate expired / IP mismatch | date/timedatectl, openssl verify/checkip/dates, SAN B_IP, тот же CA; не -k |
| Peer rejected / 403 | одинаковый token_file, длина/права без печати содержимого; A.peer_node_id=B.node_id, обратная пара; X-Hemloc-Node задаёт приложение |
| A не видит B / login history B не появляется на A | A.peer_url/token_file/CA, прямой TCP8443 A→B, свежий sync; A должен забрать local-audit outbox |
| Peer sync failed / stale | journalctl, HTTPS CA/status client, cursor/history; working data не очищать; разные history требуют snapshot |
| Proxy errors | отдельно apt/pip/curl env и Hemlock INI; use_proxy=no игнорирует env; IRR43/репликация/gRPC прямые |
| Protection not initialized / IRR error | imported success keys и cache, INI ASNs, прямой IRR43, bgpq4; не заменять пустым и не включать yes |
| Permission denied / SQLite readonly | namei -l путей, root:hemloc 0640 для INI/key/token, hemloc:hemloc 0700 DB directory; unit ReadWritePaths; код остаётся root-owned |
| Another Hemlock process owns background tasks | один serve на DB; systemctl show, ps; не удалять lock ради второго worker |
| BGP Disabled | admin-down=true ожидаемо на bootstrap; наличие соседа не означает сессию |
| BGP Active/Idle | source B IP, route к peer, TCP179, passive на Junos, ASN/families, TTL/MD5/GTSM; DENY policy обычно не мешает Established |
| ICMP administratively prohibited / admin-prohibited | это сетевой ACL/отказ по пути, не признак ошибки replication; согласовать с сетевой командой, не менять firewall автоматически |
| Established, export=0 | announcements=no, пустой/неподтверждённый desired, protection, owner policy mismatch, stale observation; смотреть локальную RIB и attrs |
| Adj-RIB-Out есть, роутер не применяет | DENY-ANY на роутере намеренно оставлен; экспорт B не доказывает принятие/FIB; отдельная операторская проверка |

Минимум: `systemctl status hemloc gobgp`,

```bash
journalctl -u hemloc -u gobgp --since \
  '-15 minutes'
```

Дополнительно: `ss -lntp`, HTTPS с CA, Dashboard/Info и диагностический status
выше. Журналы/backup/config не публиковать целиком. Ошибки не исправлять удалением
БД, сбросом protection, сменой owner или перезапуском GoBGP A.

## 15. Что проверено при подготовке

Команды сверены с CLI/config loader, replication transport, SQLite snapshot/
backup и policy renderer v0.1.0. Переносчик protection проверяется на временных
DB: экспорт не меняет source, импорт идемпотентен/монотонен, неверные source,
digest и незавершённая инициализация отвергаются; активный process lock мешает
импорту. INI/GoBGP TOML и systemd units проверяются отдельно без production peers.

Полной чистой Debian VM с init/systemd для этой проверки нет: запуск services,
reboot, реальные адреса B, сертификат production CA, межузловые доступы и Junos
остаются **операторской приёмкой**, а не выполненными действиями. B при подготовке
не посещался; A читался без изменения services/config/DB. Никакой public tag не
перемещён. Локальная инструкция/операционные значения остаются под ignored var/.

The v0.1.0 commands above deliberately retain legacy import identities for that
immutable historical release. For the corrected Hemlock package upgrade, use
[RENAMING.md](RENAMING.md) and a reviewed current commit.
