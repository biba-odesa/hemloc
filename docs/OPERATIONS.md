# Операционные процедуры и интеграционный стенд

Статус проверок релиза — в VALIDATION.md. Команды ниже являются инструкцией оператору, а не отчётом о выполненных действиях. Изолированные тесты запускаются только по решению оператора; production-конфигурация и автозапуск системных сервисов в текущую проверку не входят. По умолчанию стенд использует отдельные БД, loopback HTTPS, тестовые IRR-данные и выключенные анонсы. Явный --gobgp-binary создаёт два собственных daemon без соседей и включает только запись тестовых маршрутов в их локальную RIB.

## CA и сертификаты с SAN

Для стенда `tools/prepare_lab.py` выпускает локальную CA и два SAN-сертификата. Он не устанавливает доверие в ОС и не запускает процессы. Для рабочего контура выпускать ключ CA отдельно от VM и использовать существующую организационную CA, если она доступна.

Пример ручного выпуска в закрытом каталоге с `umask 077`:

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out ca.key
openssl req -x509 -new -key ca.key -sha256 -days 3650 -subj /CN=Hemloc-Local-CA -out ca.crt -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out block-a.key
openssl req -new -key block-a.key -subj /CN=block-a -out block-a.csr -addext subjectAltName=DNS:block-a
```

Создать `block-a.ext`:

```ini
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:block-a,DNS:block-a.example.net
```

Подписать и проверить:

```bash
openssl x509 -req -in block-a.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out block-a.crt -days 365 -sha256 -extfile block-a.ext
openssl verify -CAfile ca.crt -verify_hostname block-a block-a.crt
```

Аналогично block-b. Если peer_url содержит IP, в сертификате нужен соответствующий **IP SAN**; CN недостаточно. Не добавлять рабочие IP в пример автоматически. В INI задать `tls=yes`, `cert`, `key`, `ca`, HTTPS peer_url. Проверка сертификата репликации не отключается. Приватный ключ CA не хранить на рабочих узлах; leaf-ключи и token локальные, не реплицируются.

Доверие браузера: импортировать только `ca.crt` в доверенные CA браузера/клиентской ОС. Установка доверия Debian через `/usr/local/share/ca-certificates/hemloc-ca.crt` и `update-ca-certificates` меняет системное хранилище: выполнять только после отдельного согласования. Приложению достаточно явного пути `ca`, без системных изменений. Планировать обновление сертификатов до истечения и перезапускать только Hemloc для перечитывания файлов.

## Подготовка двух экземпляров

После установки локальных зависимостей:

```bash
.venv/bin/python tools/prepare_lab.py --directory var/lab
.venv/bin/python tools/check_lab.py --directory var/lab
```

Первый скрипт создаёт только локальные файлы в новом каталоге; сертификаты с SAN `block-a`, `block-b`, `localhost` и `127.0.0.1`, CA, два уникальных конфига, общий random token. Не перезаписывает существующий каталог. Приватные артефакты находятся под игнорируемым `var/` и не попадают в Git. Порты по умолчанию 18443 и 18444, разные SQLite. Нет настоящих BGP-соседей; оба `announcements=no`.

Второй скрипт — **явно запускаемый оператором тест**: предлагает пароль дважды, создаёт тестовых пользователей, запускает два непривилегированных дочерних процесса Hemloc, проверяет HTTPS/репликацию/API, останавливает их, имитирует promotion и возврат старого узла и завершает процессы в finally. Без --gobgp-binary не запускает GoBGP. Systemd, сеть и firewall не меняет. Реальный прогон двух HTTPS-узлов выполнен, в том числе с неработающим proxy в INI и env. По завершении изучить созданные log-файлы и отчёт; тестовый пароль нигде не сохраняется открытым.

Для ручного запуска после подготовки пользователей в двух отдельных терминалах:

```bash
.venv/bin/hemloc --config var/lab/a.ini serve
.venv/bin/hemloc --config var/lab/b.ini serve
```

Первого пользователя на стенде создаёт check_lab.py; для CLI от root использовать владельца БД и процедуру README. Браузерные адреса: `https://127.0.0.1:18443` и `https://127.0.0.1:18444`. Для браузера предварительно доверить тестовую CA только в тестовом профиле.

Проверить вручную: обе темы, узкий экран, поиск и пагинацию, комментарии с HTML отображаются текстом, несколько origin ASN/неизвестный ASN, все совпадения IP, pending-предложения, ошибки IRR, disabled/guest/admin, пароль и отзыв сессий, различия protection и понятную давность данных соседа. Chromium headless/Playwright проверил вход и cookie, обе темы, mobile viewport, экранирование HTML, все совпадения IP, canonical-network errors, ошибки поиска и guest restrictions. Ошибка в открытом редакторе теперь отображается внутри dialog; после успешного запроса старая ошибка очищается. Полная нагрузочная и доступностная проверка ещё не проводилась.

## Изолированный GoBGP

Изолированные daemon запускаются только по решению оператора. Бинарник с проверенным SHA256 находится в var/toolchains/gobgp-4.10.0. Системные службы не устанавливались. Пример ручного запуска отдельного peer-free daemon:

```bash
var/toolchains/gobgp-4.10.0/gobgpd -f deploy/gobgpd.example.toml --api-hosts=127.0.0.1:50051
```

Проверить, что в TOML **нет neighbors**, BGP слушает исключительно loopback:1179. Не использовать рабочий конфиг или рабочий gRPC target. Сервисный unit не требует root/capabilities. Для рабочего TCP/179 нужны отдельно согласованные права; в примере их нет.

Для адаптерного теста после отдельного запуска пустого демона:

```bash
HEMLOC_LIVE_GOBGP=127.0.0.1:50051 .venv/bin/python -m unittest discover -s tests -p test_gobgp_live.py -v
```

Тест требует нулевое число BGP-соседей, использует отдельную тестовую ownership community и TEST-NET/IPv6 documentation prefixes, удаляет только наблюдаемые локальные пути с его marker и path identifier; UUID из ListPath не ожидается. Он не запускается без явного env-параметра. Не направлять его к рабочему демону. Projection сверена с официальными дескрипторами, реальная совместимость с 4.10.0 проверена. Само наличие локального пути не означает его принятия соседом.

Дополнительно выполнить сценарии: перезапуск изолированного gobgpd при сохранённом desired state; ошибка между AddPath и локальным подтверждением; появление чужого локального маршрута с тем же prefix; изменение local-pref/community/next-hop; локальная protection с последующим отзывом; IPv6 при пустом next-hop; получение BGP session/Adj-RIB-Out от отдельно согласованного тестового peer. Local RIB и Adj-RIB-Out никогда не подписывать как принятие рабочим маршрутизатором.


## Повтор проверенного связанного сценария

Установить зависимости тестов с хешами и код из текущего каталога:

```bash
.venv/bin/python -m pip install --require-hashes -r requirements-test.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python tools/check_gobgp_schema.py
.venv/bin/python tools/check_gobgp.py --binary var/toolchains/gobgp-4.10.0/gobgpd --suite --cli
.venv/bin/python tools/prepare_lab.py --directory var/lab-new-run
.venv/bin/python tools/check_lab.py --directory var/lab-new-run --cli --gobgp-binary var/toolchains/gobgp-4.10.0/gobgpd
.venv/bin/python tools/check_browser.py --directory var/browser-new-run
```

Каждый каталог должен быть новым. --cli использует обычный sudo и настоящий PTY для интерактивного reset-password, проверяет отказ старого пароля, новые логины и отзыв сессий обоих узлов; пароль не передаётся в argv. Для автоматического сценария нужен заранее доступный sudo -n; при его отсутствии выполнить CLI-проверку вручную в терминале.

В режиме --gobgp-binary изменяются **только свежие lab INI**: анонсы включаются для двух создаваемых скриптом loopback-daemon с разными портами, а IPv6 next-hop задаётся явно из documentation prefix. Ни один daemon не имеет соседей. Проверяются две независимые фоновые сверки, локальные protection-расхождения slave без потери исходных данных, восстановление RIB после перезапуска slave GoBGP, работа slave при остановленном master, promotion и возврат старого master. PID обоих daemon сохраняются при переключении роли Hemloc. После проверки все дочерние процессы останавливаются; lab INI не применять к рабочему daemon.

Обычный check_gobgp дополнительно проверяет два разных owner/path ID на одном NLRI: адресный отзыв одного сохраняет второй. Он также проверяет восстановление после успешного AddPath с потерянным подтверждением и нового экземпляра адаптера. Proxy env намеренно указывает на недоступный loopback-порт: gRPC остаётся прямым.

Браузерная проверка использует явный HTTP bootstrap на loopback, а HTTPS/проверка CA/SAN/secure cookies отдельно проверяются двумя HTTPS-приложениями. CA в системное хранилище не устанавливается. Browser screenshots и отчёты остаются только под игнорируемым var/.

Проверки BGP-соседа, upstream, backup/restore и нагрузки добавлены в эксплуатационный этап ниже; результаты в VALIDATION.md. Постоянное systemd-развёртывание/обновление/восстановление целой VM остаются отдельным этапом. Рабочие соседи и production-анонсы не использовались.

## announcements=no и отдельный отзыв собственных маршрутов

`announcements=no` — **заморозка gRPC-записей**, включая DeletePath. Она не
отзывает старые маршруты и не останавливает их экспорт уже работающим GoBGP.
Desired state, правила и наблюдение продолжают работать. Надпись в вебе явно
напоминает, что старые маршруты не отозваны. Остановка Hemloc тоже не очищает
GoBGP. Переход обратно в yes вновь приводит локальную RIB к desired state.

Для контролируемого отзыва **всех только собственных путей** без удаления правил:

1. Установить `announcements=no` в локальном INI и остановить **только Hemloc**.
   GoBGP оставить работающим. Это отдельное эксплуатационное действие; в этой
   сессии постоянные службы не останавливались и не запускались.
2. Не менять ownership marker. CLI использует именно marker текущей установки
   и соответствующий стабильный path identifier. Для другого исторического
   marker требуется отдельный проверенный конфиг, не подбор чужих marker.
3. Выполнить dry-run от root, проверить target и количество путей:

```bash
sudo /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini routes withdraw-owned
```

4. После просмотра результата выполнить явный отзыв:

```bash
sudo /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini routes withdraw-owned --execute
sudo /opt/hemloc/.venv/bin/hemloc --config /etc/hemloc/hemloc.ini routes withdraw-owned
```

Последний dry-run должен показать `owned=0`. Команда требует announcements=no
и свободную блокировку приложения. Перед каждым отзывом она заново читает
**точный** NLRI и проверяет local origin, owner community и path identifier.
DeletePath содержит наблюдаемый путь; blanket withdraw не используется. Чужие
локальные/полученные пути не удаляются, итоговый список сверяется. Конкурентное
изменение RIB может привести к ошибке проверки; изучить состояние и повторить.
Прерывание оставляет частично выполненный отзыв: повтор безопасен. Успех/ошибка
пишутся в аудит без wire payload и секретов; на slave факт остаётся в локальном
outbox до получения master. CLI не меняет роль и поколение.

Правила и desired state остаются: после запуска с announcements=yes маршруты
будут добавлены снова. Если блокировки нужно удалить окончательно, удалить их
на master и проверить репликацию. Пока обслуживание продолжается, сохранять
announcements=no. Локальный отзыв одного узла не отзывает маршруты второго:
выполнить процедуру отдельно на каждом узле, когда это требуется оператору.
Dry-run подтверждает только локальную RIB; проверить Adj-RIB-Out и состояние
соседнего маршрутизатора отдельно. Не перезапускать GoBGP ради отзыва.

## Дополнительные эксплуатационные проверки

Только новые временные каталоги/БД, без рабочего конфига:

```bash
.venv/bin/python tools/check_peer.py --binary var/toolchains/gobgp-4.10.0/gobgpd
.venv/bin/python tools/check_sources.py
.venv/bin/python tools/check_restore.py
.venv/bin/python tools/check_load.py --binary var/toolchains/gobgp-4.10.0/gobgpd --count 10000
.venv/bin/python tools/check_load.py --binary var/toolchains/gobgp-4.10.0/gobgpd --count 100000
```

Peer harness создаёт **только** два своих daemon, AS64512, 127.0.0.1/127.0.0.2,
случайные непривилегированные BGP/gRPC порты, IPv4/IPv6 unicast iBGP. Проверяет
приём обоих префиксов документации, next-hop/local-pref/community, совпадение
веб-API Adj-RIB-Out с RIB соседа, SIGKILL/новый процесс соседа, восстановление и
отзыв. Имеет собственные конфиги без подключения к существующим daemon.
Это не проверка production policy/eBGP, TCP/179 или реального маршрутизатора.

Sources harness принудительно включает proxy из примера для RIPEstat HTTPS,
IRR RIPE,RADB к whois.radb.net/TCP43 остаётся прямым. Результат AS64496 растит
protection **только временной БД**. Ошибки записываются категориями без сырого
текста исключения. Это сетевой тест, результаты и длительность зависят от сети.

Restore harness делает online backup двух временных SQLite, восстанавливает
завершённые backup в отдельные каталоги, сверяет правила, пароли/пользователей,
аудит, историю/cursor, local protection, integrity_check и последующий journal.
Копирование открытой БД не используется. INI/ключи/CA не восстанавливаются из
БД: они локальны и резервируются отдельно. Это drill БД, не восстановление VM.

Load harness импортирует обычным Service.import_manual пакетами по 1000
**ручных правил**, каждое со своим IPv6 /128 внутри 2001:db8::/32. Сохраняет
полный штатный аудит/journal, проверяет snapshot+catchup, поиск и последнюю
страницу через аутентифицированный FastAPI TestClient; применяет все маршруты
к собственному peer-free GoBGP, повторную сверку и один отзыв. Измеряет wall
clock, peak RSS Python, текущий RSS GoBGP, DB после checkpoint WAL. Время
импорта не является временем HTTP bulk upload, а ASGI latency не включает TLS.
Изолированный процесс и каталог удаляются в finally. RAM Python включает
снимок/JSON/ASGI, RSS daemon снят после применения (не peak).

Для дополнительного замера настоящего HTTPS snapshot/journal во время фазы
GoBGP большого теста запустить в другом терминале:

```bash
.venv/bin/python tools/check_load_transport.py --database /tmp/hemloc-load-ИМЯ/a.sqlite
.venv/bin/python tools/check_load_transport.py --database /tmp/hemloc-load-ИМЯ/a.sqlite --journal-only
```

Принимается только активный временный каталог load harness. TLS CA и IP SAN
проверяются, используется настоящая аутентификация репликации. В обычном режиме меняется лишь
комментарий синтетического правила для создания догоняемого события.
--journal-only проверяет полный replay от пустой sequence=0 этого нового
изолированного поколения. Он не откатывает cursor существующего slave.
Установка/units и будущие команды запуска: [DEPLOYMENT.md](DEPLOYMENT.md).
Точные измерения и ограничения текущего прогона: [VALIDATION.md](VALIDATION.md).

`check_gobgp.py --cli` дополнительно проверяет root CLI отзыва через sudo -n; без этого флага проверка maintenance использует тот же сервисный код без смены UID.
