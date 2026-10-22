# Отдельный offline перенос protection cache

Это maintenance-процедура для других согласованных развёртываний.
**Не применять к выбранной чистой переустановке B:** там переносится только
локальный INI, TLS/CA и secret, см. PAIR_UPGRADE_040.md и INSTALL_B.md.

На обоих узлах должна быть canonical установка, config валиден и БД уже
инициализирована. Источник может работать; целевой slave должен быть остановлен,
announcements=no. Подготовьте закрытый /root/hemlock-transfer на обоих узлах.

Для cache имеется отдельный проверяемый maintenance tool, **не встроенная
CLI-команда**. На master он только читает SQLite в read-only транзакции.
Все protected ASN должны иметь successful cache metadata. Если ASN добавили в
INI, сначала отдельно перечитайте конфиг restart Hemlock и дождитесь успешного
refresh; новый INI сам по себе инициализацию не доказывает.

**Master/root:**

```bash
/opt/hemlock/.venv/bin/python /opt/hemlock/tools/protection_transfer.py export \
  --config /etc/hemlock/hemlock.ini --file /root/hemlock-transfer/protection.json
sha256sum /root/hemlock-transfer/protection.json
```

Файл должен быть новым (существующий не перезаписывается). Передайте JSON через
закрытый проверенный SSH/SFTP на slave; сверяйте SHA256 отдельно. Это приватные
операционные данные, не Git. На **slave/root**, файл доступен только root:

```bash
/opt/hemlock/.venv/bin/python /opt/hemlock/tools/protection_transfer.py import \
  --config /etc/hemlock/hemlock.ini --file /root/hemlock-transfer/protection.json
```

Tool требует slave, announcements=no и lock остановленного приложения; проверяет
source node/config/digest/готовность ASN, затем **union** cache, ничего не сокращая.
Не переносит правила/пользователей/БД. Не заменяйте накопленный cache новым IRR
ответом: исторические сети могут исчезнуть из текущего ответа источника.
